"""Application configuration using Pydantic Settings."""

import os
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    """Central configuration parameters for Norwegian Company Intelligence Agent."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Project directories
    BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent
    DATA_DIR: Path = BASE_DIR / "data"
    PROFILES_DIR: Path = BASE_DIR / "profiles"
    REPORTS_DIR: Path = BASE_DIR / "reports"

    # Gemini Settings
    GEMINI_API_KEY: Optional[str] = Field(default=None, description="Google Gemini API key")
    GEMINI_MODEL: str = Field(default="gemini-2.5-flash-lite", description="Primary extraction model")
    GEMINI_FALLBACK_MODEL: str = Field(default="gemini-2.0-flash", description="High-capability conflict model")

    # Browser Automation Settings
    BROWSER_PROVIDER: str = Field(
        default="mock",
        description="Browser provider: 'browser_use', 'tinyfish', 'http', or 'mock'",
    )
    TINYFISH_API_KEY: Optional[str] = Field(default=None, description="TinyFish Agent API key")
    BROWSER_USE_HEADLESS: bool = Field(default=True, description="Run browser-use headless")

    # Database
    DATABASE_URL: str = Field(
        default="sqlite:///./data/company_agent.db",
        description="Database connection string",
    )

    # Budget & Execution Limits (Daily Competition Evaluation)
    MAX_DAILY_REQUESTS: int = Field(default=2000, description="Hard ceiling for outbound requests")
    MAX_DAILY_COST_USD: float = Field(default=10.0, description="Hard ceiling for external API spend ($)")
    INTERNAL_COST_CEILING_USD: float = Field(default=8.0, description="Internal safety ceiling ($)")
    MAX_RUN_TIME_SECONDS: int = Field(default=2700, description="Maximum execution time (45 mins)")
    MAX_TOKEN_BUDGET_PER_COMPANY: int = Field(default=3000, description="Max Gemini tokens per company")
    MAX_SNIPPETS_PER_MODEL_CALL: int = Field(default=5, description="Max evidence snippets per prompt")

    # Freshness TTLs (Days)
    IDENTITY_FRESHNESS_DAYS: int = Field(default=30, description="Freshness TTL for core identity")
    DYNAMIC_FRESHNESS_DAYS: int = Field(default=7, description="Freshness TTL for financial/employee data")

    # Public Data Sources
    BRREG_API_BASE: str = Field(
        default="https://data.brreg.no/enhetsregisteret/api",
        description="Brønnøysund Enhetsregisteret API base URL",
    )
    BRREG_REGNSKAP_BASE: str = Field(
        default="https://data.brreg.no/regnskapsregisteret",
        description="Brønnøysund Regnskapsregisteret API base URL",
    )
    HTTP_TIMEOUT_SECONDS: float = Field(default=15.0, description="Default HTTP request timeout")
    HTTP_MAX_RETRIES: int = Field(default=3, description="Max HTTP retries with exponential backoff")
    USER_AGENT: str = Field(
        default="NorwegianCompanyIntelligenceAgent/1.0 (+https://github.com/karthik-ak-Git/nano-research; evaluation-bot)",
        description="Outbound HTTP User-Agent",
    )

    # Operation Flags
    DRY_RUN: bool = Field(default=False, description="Dry run mode: does not incur external API costs")
    LOG_LEVEL: str = Field(default="INFO", description="Log level")


# Global singleton settings instance
settings = Settings()
