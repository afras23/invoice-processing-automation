"""
Application configuration.

All settings are loaded from environment variables and validated at startup.
No hardcoded values — every configurable parameter is defined here with
documented defaults.
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # ── Server ────────────────────────────────────────────────────────────────
    app_env: str = Field(default="development", description="Runtime environment name")

    # ── AI provider ───────────────────────────────────────────────────────────
    anthropic_api_key: str = Field(description="Anthropic API key")
    ai_model: str = Field(
        default="claude-3-5-sonnet-20241022",
        description="Claude model identifier",
    )

    # ── AI cost tracking (USD per token) ──────────────────────────────────────
    ai_cost_per_input_token_usd: float = Field(
        default=0.000003,
        description="Cost per input token in USD (default: claude-3-5-sonnet)",
    )
    ai_cost_per_output_token_usd: float = Field(
        default=0.000015,
        description="Cost per output token in USD (default: claude-3-5-sonnet)",
    )
    max_daily_cost_usd: float = Field(
        default=10.0,
        description="Maximum daily AI spend in USD; new requests are rejected once reached",
    )

    # ── AI retry / circuit breaker ────────────────────────────────────────────
    ai_max_retries: int = Field(
        default=3,
        description="Maximum retry attempts per AI call",
    )
    ai_retry_base_delay_seconds: float = Field(
        default=1.0,
        description="Base delay for exponential backoff in seconds",
    )
    ai_circuit_breaker_threshold: int = Field(
        default=5,
        description="Number of consecutive failures before circuit opens",
    )
    ai_circuit_breaker_reset_seconds: float = Field(
        default=60.0,
        description="Seconds before a tripped circuit breaker resets",
    )

    # ── Business rules ────────────────────────────────────────────────────────
    approval_threshold: float = Field(
        default=500.0,
        description="Invoice amounts above this value require manual approval",
    )

    # ── Integrations ─────────────────────────────────────────────────────────
    slack_webhook_url: str | None = Field(
        default=None,
        description="Slack incoming webhook URL; omit to disable notifications",
    )
    service_account_file: str = Field(
        default="service_account.json",
        description="Path to Google service account JSON; omit file to disable Sheets",
    )
    sheets_document_name: str = Field(
        default="Invoices",
        description="Name of the Google Sheets document to append rows to",
    )

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str | None = Field(
        default=None,
        description="Async SQLAlchemy database URL (e.g. postgresql+asyncpg://...)",
    )

    # ── Review queue ──────────────────────────────────────────────────────────
    confidence_review_threshold: float = Field(
        default=0.7,
        description="Pipeline confidence scores below this value are queued for human review",
    )

    # ── Airtable (optional) ───────────────────────────────────────────────────
    airtable_api_key: str | None = Field(
        default=None,
        description="Airtable personal access token; omit to disable Airtable export",
    )
    airtable_base_id: str | None = Field(
        default=None,
        description="Airtable base ID (e.g. appXXXXXXXXXXXXXX)",
    )
    airtable_table_name: str = Field(
        default="Invoices",
        description="Airtable table to store extracted invoice records",
    )

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")


settings = Settings()  # type: ignore[call-arg]  # pydantic-settings reads from env
