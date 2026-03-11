"""
Application configuration using pydantic-settings.
Senior Engineering Note: Environment-based config with validation and type safety.
"""
import re
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, ValidationInfo, field_validator
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
    api_key: SecretStr = Field(  # type: ignore[assignment]
        default="",
        description="API key for authenticating requests. "
        "Leave empty to disable auth (development only)."
    )
    notification_token_secret: SecretStr = Field(  # type: ignore[assignment]
        default="",
        description=(
            "Dedicated HMAC secret for signing notification acknowledgement tokens "
            "(set AIRRA_NOTIFICATION_TOKEN_SECRET). Rotated independently of api_key "
            "so key rotation does not invalidate in-flight acknowledgement links. "
            "Falls back to api_key if empty."
        ),
    )

    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://airra:airra@localhost:5432/airra",
        description="PostgreSQL connection string"
    )
    database_pool_size: int = Field(default=10, ge=1, le=50)
    database_max_overflow: int = Field(default=20, ge=0, le=100)
    database_echo: bool = Field(default=False, description="Log SQL queries")

    # Redis
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection string"
    )
    redis_cache_ttl: int = Field(default=300, ge=60, description="Cache TTL in seconds")

    # LLM Configuration
    llm_provider: Literal["anthropic", "openai", "openrouter", "groq"] = "anthropic"
    anthropic_api_key: SecretStr = Field(default="", description="Anthropic API key")  # type: ignore[assignment]
    openai_api_key: SecretStr = Field(default="", description="OpenAI API key")  # type: ignore[assignment]
    openrouter_api_key: SecretStr = Field(default="", description="OpenRouter API key")  # type: ignore[assignment]
    groq_api_key: SecretStr = Field(  # type: ignore[assignment]
        default="",
        description=(
            "Groq API key (set AIRRA_GROQ_API_KEY). Used when llm_provider='groq'. "
            "Alternatively, set a Groq key in AIRRA_OPENAI_API_KEY (legacy)."
        ),
    )
    llm_model: str = Field(
        default="claude-3-5-sonnet-20241022",
        description="LLM model for reasoning tasks (hypothesis analysis, structured output)"
    )
    llm_generator_model: str = Field(
        default="llama-3.1-8b-instant",
        description=(
            "LLM model for creative generation tasks (AI incident generator). "
            "Defaults to llama-3.1-8b-instant which is on Groq's free tier. "
            "Override via AIRRA_LLM_GENERATOR_MODEL."
        ),
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

    # RAG Similarity Skip
    similarity_skip_threshold: float = Field(
        default=0.75,
        ge=0.0,
        le=1.0,
        description=(
            "Multi-signal composite confidence threshold (0–1) above which LLM analysis "
            "is skipped and the past incident's resolution is reused. "
            "Composite = 0.5×vector_similarity + 0.3×service_match + 0.2×metric_overlap. "
            "Default 0.75 requires strong agreement across all three signals. "
            "Set AIRRA_SIMILARITY_SKIP_THRESHOLD to tune."
        ),
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
    verification_stabilization_seconds: int = Field(
        default=30,
        ge=5,
        description=(
            "Seconds to wait after action execution before sampling Prometheus metrics "
            "for post-action verification. Production should be 120+; 30s is suitable "
            "for demo environments where scrape intervals are short. "
            "Set AIRRA_VERIFICATION_STABILIZATION_SECONDS to override."
        ),
    )

    # Rate Limiting
    rate_limit_trust_x_forwarded_for: bool = Field(
        default=False,
        description=(
            "Trust X-Forwarded-For header for client IP extraction in rate limiting. "
            "Enable only when running behind a trusted reverse proxy (nginx/Envoy). "
            "When False, uses request.client.host (the direct TCP connection IP)."
        ),
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
    smtp_password: SecretStr = Field(  # type: ignore[assignment]
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
    slack_webhook_url: str = Field(
        default="",
        description=(
            "Slack Incoming Webhook URL for incident notifications. "
            "Set AIRRA_SLACK_WEBHOOK_URL to enable. Empty = disabled (simulation mode)."
        ),
    )

    @field_validator("cors_origins")
    @classmethod
    def validate_cors_origins(cls, v: list[str], info: ValidationInfo) -> list[str]:
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

    @field_validator("anthropic_api_key", "openai_api_key", "groq_api_key")
    @classmethod
    def validate_api_keys(cls, v: SecretStr, info: ValidationInfo) -> SecretStr:
        """Validate that required API keys are set in non-development environments."""
        if info.data.get("environment") != "production":
            return v
        provider = info.data.get("llm_provider", "")
        field = info.field_name
        # Only require the key that matches the configured provider
        required = (
            (field == "anthropic_api_key" and provider == "anthropic")
            or (field == "openai_api_key" and provider == "openai")
            or (field == "groq_api_key" and provider == "groq")
        )
        if required and not v.get_secret_value():
            raise ValueError(f"{field} must be set in production when llm_provider='{provider}'")
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
