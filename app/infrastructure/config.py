from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    llm_provider: str = "openai"  # "openai" or "anthropic"
    openai_api_key: str = ""
    openai_base_url: str = ""  # Custom base URL (e.g. Ollama: http://localhost:11434/v1)
    anthropic_api_key: str = ""
    redis_url: str = "redis://localhost:6379/0"
    database_url: str = "postgresql://nanobana:nanobana_dev@localhost:5432/nanobana"
    llm_model: str = "gpt-4o"
    llm_max_tokens: int = 4096
    log_level: str = "INFO"

    # ChromaDB Cloud
    chroma_api_key: str = ""  # ChromaDB Cloud API key
    chroma_tenant: str = ""   # ChromaDB Cloud tenant ID
    chroma_database: str = "" # ChromaDB Cloud database name

    # Web search (Tavily)
    tavily_api_key: str = ""  # Set to enable web search; empty = search disabled

    # Auth (RBAC) — legacy self-signed JWT (kept for backwards compatibility)
    jwt_secret: str = ""  # Set to enable legacy auth; empty = auth disabled (dev mode)
    jwt_algorithm: str = "HS256"
    jwt_expiry_hours: int = 24

    # Auth (Clerk) — takes precedence over legacy JWT when clerk_secret_key is set
    clerk_publishable_key: str = ""
    clerk_secret_key: str = ""  # Set to enable Clerk auth; empty = falls back to legacy/dev mode
    clerk_jwt_issuer: str = ""  # e.g., "https://your-app.clerk.accounts.dev"

    # Data ingestion — pre-warm these tickers at startup
    # Comma-separated in .env: WATCHLIST_TICKERS=AAPL,MSFT,TSLA
    watchlist_tickers: str = ""
    ingestion_concurrency: int = 3

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @property
    def watchlist(self) -> list[str]:
        """Parse comma-separated watchlist into a list."""
        if not self.watchlist_tickers:
            return []
        return [t.strip().upper() for t in self.watchlist_tickers.split(",") if t.strip()]


settings = Settings()
