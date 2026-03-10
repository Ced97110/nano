"""JWT-based RBAC authentication with Clerk support.

Three roles:
  - viewer:  read-only access to results and audit trails
  - analyst: run analyses, submit HITL feedback, approve sharing
  - admin:   all analyst permissions + manage users + system stats

Auth modes (checked in order):
  1. Clerk:  If clerk_secret_key is set, verify Clerk-issued JWTs via JWKS
  2. Legacy: If jwt_secret is set, verify self-signed HS256 JWTs
  3. Dev:    If neither is set, all requests get admin access (dev mode)
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Annotated

import structlog
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = structlog.get_logger(__name__)

# Lazy import to avoid circular deps at module level
_jwt = None


def _get_jwt():
    global _jwt
    if _jwt is None:
        import jwt as pyjwt
        _jwt = pyjwt
    return _jwt


class Role(str, Enum):
    viewer = "viewer"
    analyst = "analyst"
    admin = "admin"


# Role hierarchy: admin > analyst > viewer
_ROLE_LEVEL = {Role.viewer: 0, Role.analyst: 1, Role.admin: 2}

_bearer = HTTPBearer(auto_error=False)


class AuthUser:
    """Represents the authenticated user extracted from JWT."""

    def __init__(self, user_id: str, role: Role, email: str = ""):
        self.user_id = user_id
        self.role = role
        self.email = email

    def has_role(self, required: Role) -> bool:
        return _ROLE_LEVEL[self.role] >= _ROLE_LEVEL[required]


def _get_settings():
    from app.infrastructure.config import settings
    return settings


# ── Clerk JWKS cache ──

_jwks_cache: dict | None = None
_jwks_cache_time: float = 0
_JWKS_CACHE_TTL = 3600  # 1 hour


async def _fetch_clerk_jwks(issuer: str) -> dict:
    """Fetch Clerk's JWKS from the well-known endpoint. Cache for 1 hour."""
    global _jwks_cache, _jwks_cache_time

    now = time.time()
    if _jwks_cache and (now - _jwks_cache_time) < _JWKS_CACHE_TTL:
        return _jwks_cache

    import httpx

    jwks_url = f"{issuer.rstrip('/')}/.well-known/jwks.json"
    logger.info("clerk.jwks.fetching", url=jwks_url)

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(jwks_url)
            resp.raise_for_status()
            _jwks_cache = resp.json()
            _jwks_cache_time = now
            logger.info("clerk.jwks.cached", keys=len(_jwks_cache.get("keys", [])))
            return _jwks_cache
    except Exception as exc:
        logger.error("clerk.jwks.fetch_failed", error=str(exc))
        # Return stale cache if available
        if _jwks_cache:
            logger.warning("clerk.jwks.using_stale_cache")
            return _jwks_cache
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to fetch Clerk JWKS for token verification",
        )


async def _verify_clerk_token(token: str) -> AuthUser:
    """Verify a Clerk-issued JWT using JWKS (RS256).

    Extracts user_id from `sub`, email from claims, and role from
    Clerk's public metadata (`publicMetadata.role`).
    """
    s = _get_settings()
    jwt = _get_jwt()

    # Fetch JWKS
    jwks_data = await _fetch_clerk_jwks(s.clerk_jwt_issuer)

    try:
        # Get the signing key from JWKS
        from jwt import PyJWKClient, PyJWK

        # Build a PyJWKClient-compatible key set from cached data
        # We parse the header to find the right kid
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")

        if not kid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token missing key ID (kid)",
            )

        # Find matching key in JWKS
        matching_key = None
        for key_data in jwks_data.get("keys", []):
            if key_data.get("kid") == kid:
                matching_key = PyJWK(key_data)
                break

        if not matching_key:
            # Key not found — maybe rotated. Clear cache and retry once.
            global _jwks_cache, _jwks_cache_time
            _jwks_cache = None
            _jwks_cache_time = 0
            jwks_data = await _fetch_clerk_jwks(s.clerk_jwt_issuer)

            for key_data in jwks_data.get("keys", []):
                if key_data.get("kid") == kid:
                    matching_key = PyJWK(key_data)
                    break

            if not matching_key:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token signing key not found in JWKS",
                )

        # Verify the token
        decode_options = {}
        decode_kwargs = {
            "algorithms": ["RS256"],
            "issuer": s.clerk_jwt_issuer,
        }

        payload = jwt.decode(
            token,
            matching_key.key,
            **decode_kwargs,
            options=decode_options,
        )

    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
        )
    except jwt.InvalidIssuerError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token issuer",
        )
    except jwt.InvalidTokenError as exc:
        logger.warning("clerk.token.invalid", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )

    # Extract user info from Clerk JWT claims
    user_id = payload.get("sub", "unknown")

    # Clerk stores email in various claim locations
    email = ""
    if "email" in payload:
        email = payload["email"]
    elif "email_addresses" in payload:
        # Some Clerk JWT templates include email_addresses array
        addrs = payload["email_addresses"]
        if isinstance(addrs, list) and addrs:
            email = addrs[0] if isinstance(addrs[0], str) else addrs[0].get("email_address", "")

    # Extract role from Clerk's public metadata
    # Users should set `publicMetadata.role` in Clerk Dashboard
    role_str = "viewer"  # default role for Clerk users
    metadata = payload.get("public_metadata", payload.get("publicMetadata", {}))
    if isinstance(metadata, dict) and "role" in metadata:
        role_str = metadata["role"]
    # Also check top-level "role" claim (for custom JWT templates)
    elif "role" in payload:
        role_str = payload["role"]

    try:
        role = Role(role_str)
    except ValueError:
        role = Role.viewer

    logger.debug("clerk.auth.success", user_id=user_id, role=role.value)
    return AuthUser(user_id=user_id, role=role, email=email)


async def _verify_legacy_token(token: str) -> AuthUser:
    """Verify a self-signed HS256 JWT (legacy auth mode)."""
    s = _get_settings()
    jwt = _get_jwt()

    try:
        payload = jwt.decode(
            token,
            s.jwt_secret,
            algorithms=[s.jwt_algorithm],
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    role_str = payload.get("role", "viewer")
    try:
        role = Role(role_str)
    except ValueError:
        role = Role.viewer

    return AuthUser(
        user_id=payload.get("sub", "unknown"),
        role=role,
        email=payload.get("email", ""),
    )


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
) -> AuthUser:
    """Extract and validate the JWT bearer token.

    Auth modes (checked in order):
      1. Clerk:  clerk_secret_key is set → verify via JWKS (RS256)
      2. Legacy: jwt_secret is set → verify self-signed HS256
      3. Dev:    neither set → return admin user (dev mode)
    """
    s = _get_settings()

    # Dev mode: auth disabled (no Clerk key AND no legacy JWT secret)
    if not s.clerk_secret_key and not s.jwt_secret:
        return AuthUser(user_id="dev", role=Role.admin, email="dev@local")

    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials

    # Clerk mode: verify via JWKS
    if s.clerk_secret_key:
        return await _verify_clerk_token(token)

    # Legacy mode: verify self-signed JWT
    return await _verify_legacy_token(token)


def require_role(required: Role):
    """Dependency that checks the user has at least the required role."""

    async def checker(user: Annotated[AuthUser, Depends(get_current_user)]) -> AuthUser:
        if not user.has_role(required):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires {required.value} role or higher",
            )
        return user

    return checker


# ── Token generation (for /auth/token endpoint — legacy mode only) ──

def create_token(user_id: str, role: Role, email: str = "") -> str:
    """Create a signed JWT token (legacy mode).

    Not used when Clerk auth is active — Clerk handles token issuance.
    """
    s = _get_settings()
    if not s.jwt_secret:
        raise ValueError("JWT_SECRET must be set to create tokens (legacy auth mode)")

    jwt = _get_jwt()
    payload = {
        "sub": user_id,
        "role": role.value,
        "email": email,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(hours=s.jwt_expiry_hours),
    }
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm)
