"""Authentication controller — token generation and user info."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Annotated

from app.interface.auth import (
    AuthUser, Role, create_token, get_current_user, require_role,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class TokenRequest(BaseModel):
    user_id: str = Field(..., description="User identifier")
    role: str = Field("analyst", description="Role: viewer, analyst, or admin")
    email: str = Field("", description="User email")


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    user_id: str


@router.post("/token", response_model=TokenResponse)
async def create_auth_token(
    body: TokenRequest,
    user: Annotated[AuthUser, Depends(require_role(Role.admin))],
):
    """Create a JWT token for a user. Requires admin role."""
    try:
        role = Role(body.role)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid role: {body.role}")

    token = create_token(body.user_id, role, body.email)
    return TokenResponse(
        access_token=token,
        role=body.role,
        user_id=body.user_id,
    )


class UserInfoResponse(BaseModel):
    user_id: str
    role: str
    email: str


@router.get("/me", response_model=UserInfoResponse)
async def get_current_user_info(
    user: Annotated[AuthUser, Depends(get_current_user)],
):
    """Get the current authenticated user's info."""
    return UserInfoResponse(
        user_id=user.user_id,
        role=user.role.value,
        email=user.email,
    )
