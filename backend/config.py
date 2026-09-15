"""
Compass — Application configuration.

Uses pydantic-settings to load from environment variables and .env file.
All model IDs, database URLs, and auth tokens are configured here.
"""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables / .env file."""

    # --- Database ---
    DATABASE_URL: str = "postgresql://compass:compass@localhost:5432/compass"

    # --- Nebius Token Factory ---
    NEBIUS_API_KEY: str = ""  # Required — set in .env
    NEBIUS_BASE_URL: str = "https://api.tokenfactory.nebius.com/v1/"

    # --- Model IDs ---
    ROUTER_MODEL: str = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"
    SKILL_MODEL: str = "nvidia/nemotron-3-super-120b-a12b"
    SYNTHESIS_MODEL: str = "nvidia/Nemotron-3-Ultra-550b-a55b"
    EMBEDDING_MODEL: str = "Qwen/Qwen3-Embedding-8B"
    EMBEDDING_DIMENSION: int = 768

    # --- Auth ---
    AUTH_TOKEN: str = ""  # Required — set in .env

    # --- Tavily Search API ---
    TAVILY_ENABLED: bool = False  # Feature flag: disabled by default pending team sign-off
    TAVILY_API_KEY: str = ""  # Optional — enables search_web skill when TAVILY_ENABLED is True

    # --- App ---
    LOG_LEVEL: str = "INFO"
    PORT: int = 8000

    CORS_ORIGINS: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:80",
        "http://localhost",
        "https://compass-farmlytics.vercel.app",
        "https://compass-frontend.vercel.app",
        "https://compass.nebius.app",
    ]

    # --- Cost tracking (USD per 1M tokens, verified Nebius Token Factory rates) ---
    COST_PER_1M_INPUT: dict[str, float] = {
        "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B": 0.06,
        "nvidia/nemotron-3-super-120b-a12b": 0.30,
        "nvidia/Nemotron-3-Ultra-550b-a55b": 0.80,
        "Qwen/Qwen3-Embedding-8B": 0.02,
    }
    COST_PER_1M_OUTPUT: dict[str, float] = {
        "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B": 0.24,
        "nvidia/nemotron-3-super-120b-a12b": 0.90,
        "nvidia/Nemotron-3-Ultra-550b-a55b": 2.40,
        "Qwen/Qwen3-Embedding-8B": 0.00,
    }

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance. Use this instead of a module-level global
    so the import doesn't crash when .env is missing (e.g. during tests)."""
    return Settings()
