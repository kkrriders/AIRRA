"""
Application configuration using pydantic-settings.
Senior Engineering Note: Environment-based config with validation and type safety.
"""
import re
from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings with environment variable support.

    All settings can be overridden via environment variables with AIRRA_ prefix.
    Example: AIRRA_DATABASE_URL=postgresql://...
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="AIRRA_",
        case_sensitive=False,
    )

    # Application
    app_name: str = "AIRRA Backend"
    app_version: str = "0.1.0"
    environment: Literal["development", "staging", "production"] = "development"
    debug: bool = Field(default=False, description="Enable debug mode")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    # API
    api_v1_prefix: str = "/api/v1"
    cors_origins: list[str] = Field(
        default=["http://localhost:3000"],
        description="Allowed CORS origins"
    )
    api_key: SecretStr = Field(
        default="",
        description="API key for authenticating requests. "
        "Leave empty to disable auth (development only)."
    )

    # Database
    database_url: PostgresDsn = Field(
        default="postgresql+asyncpg://airra:airra@localhost:5432/airra",
        description="PostgreSQL connection string"
    )
    database_pool_size: int = Field(default=10, ge=1, le=50)
    database_max_overflow: int = Field(default=20, ge=0, le=100)
    database_echo: bool = Field(default=False, description="Log SQL queries")

    # Redis
    redis_url: RedisDsn = Field(
        default="redis://localhost:6379/0",
        description="Redis connection string"
    )
    redis_cache_ttl: int = Field(default=300, ge=60, description="Cache TTL in seconds")

    # LLM Configuration
    llm_provider: Literal["anthropic", "openai", "openrouter", "groq"] = "anthropic"
    anthropic_api_key: SecretStr = Field(default="", description="Anthropic API key")
    openai_api_key: SecretStr = Field(default="", description="OpenAI API key")
    openrouter_api_key: SecretStr = Field(default="", description="OpenRouter API key")
    llm_model: str = Field(
        default="claude-3-5-sonnet-20241022",
        description="LLM model identifier"
    )
    llm_temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    llm_max_tokens: int = Field(default=4096, ge=100, le=8192)
    llm_timeout: int = Field(default=60, ge=10, le=300, description="Timeout in seconds")

    # Prometheus
    prometheus_url: str = Field(
        default="http://localhost:9090",
        description="Prometheus server URL"
    )
    prometheus_scrape_interval: int = Field(
        default=60,
        ge=10,
        description="Metric scrape interval in seconds"
    )

    # Monitored Services
    monitored_services: list[str] = Field(
        default=[
            "payment-service",
            "order-service",
            "user-service",
            "inventory-service",
            "notification-service",
        ],
        description="Services to monitor for anomalies. "
        "Set via AIRRA_MONITORED_SERVICES as a JSON array.",
    )

    # Incident Detection
    anomaly_detection_window: int = Field(
        default=300,
        ge=60,
        description="Time window for anomaly detection in seconds"
    )
    anomaly_threshold_sigma: float = Field(
        default=3.0,
        ge=1.0,
        le=5.0,
        description="Standard deviation threshold for anomaly detection"
    )
    confidence_threshold_high: float = Field(
        default=0.8,
        ge=0.5,
        le=1.0,
        description="High confidence threshold"
    )
    confidence_threshold_low: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Low confidence threshold for human escalation"
    )

    # Execution
    dry_run_mode: bool = Field(
        default=True,
        description="Run in dry-run mode (no actual actions executed)"
    )
    action_timeout: int = Field(
        default=300,
        ge=30,
        description="Action execution timeout in seconds"
    )

    # Background Tasks
    worker_concurrency: int = Field(default=4, ge=1, le=32)
    max_retries: int = Field(default=3, ge=0, le=10)
    retry_backoff_seconds: int = Field(default=5, ge=1, le=60)

    # Email/SMTP Configuration
    smtp_enabled: bool = Field(
        default=False,
        description="Enable real SMTP email sending (False = simulation mode)"
    )
    smtp_host: str = Field(
        default="smtp.gmail.com",
        description="SMTP server hostname"
    )
    smtp_port: int = Field(
        default=587,
        ge=1,
        le=65535,
        description="SMTP server port (587 for TLS, 465 for SSL)"
    )
    smtp_username: str = Field(
        default="",
        description="SMTP authentication username (email address)"
    )
    smtp_password: SecretStr = Field(
        default="",
        description="SMTP authentication password (app-specific password for Gmail)"
    )
    smtp_from_email: str = Field(
        default="airra-alerts@example.com",
        description="From address for outgoing emails"
    )
    smtp_use_tls: bool = Field(
        default=True,
        description="Use TLS encryption (recommended)"
    )

    # Notification Settings
    frontend_url: str = Field(
        default="http://localhost:3000",
        description="Frontend URL for generating links in notifications"
    )

    @field_validator("cors_origins")
    @classmethod
    def validate_cors_origins(cls, v: list[str], info) -> list[str]:
        """
        Validate CORS origins are properly formatted URLs.

        Security Note:
        - Rejects wildcard '*' in production
        - Validates URL format to prevent injection attacks
        - Ensures origins use http:// or https:// schemes
        """
        # Reject wildcard in production
        if info.data.get("environment") == "production" and "*" in v:
            raise ValueError(
                "Wildcard '*' CORS origin is not allowed in production. "
                "Specify explicit origins instead."
            )

        # Validate URL format for each origin (except wildcard in dev)
        valid_origin_pattern = re.compile(
            r"^https?://"  # Must start with http:// or https://
            r"[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?"  # Hostname (alphanumeric, hyphens)
            r"(\.[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?)*"  # Optional domain parts
            r"(:[0-9]{1,5})?"  # Optional port
            r"$"
        )

        for origin in v:
            # Skip wildcard validation (already checked above)
            if origin == "*":
                continue

            # Validate URL format
            if not valid_origin_pattern.match(origin):
                raise ValueError(
                    f"Invalid CORS origin format: '{origin}'. "
                    f"Must be a valid URL like 'http://localhost:3000' or 'https://example.com'"
                )

            # Additional security checks
            if "@" in origin:
                raise ValueError(
                    f"CORS origin cannot contain '@' character: '{origin}'. "
                    f"This may indicate a URL injection attempt."
                )

        return v

    @field_validator("anthropic_api_key", "openai_api_key")
    @classmethod
    def validate_api_keys(cls, v: SecretStr, info) -> SecretStr:
        """Validate that required API keys are set in non-development environments."""
        # In production, we need the appropriate API key
        if info.data.get("environment") == "production" and not v.get_secret_value():
            raise ValueError(f"{info.field_name} must be set in production")
        return v


@lru_cache
def get_settings() -> Settings:
    """
    Get cached settings instance.

    Using lru_cache ensures we only parse environment variables once.
    This is a common pattern for FastAPI dependency injection.
    """
    return Settings()


# Convenience instance for direct imports
settings = get_settings()
