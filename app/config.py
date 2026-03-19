"""
Application configuration.

All settings are loaded from environment variables, validated at startup.
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = Field(default="development")
    ai_model: str = Field(default="claude-3-5-sonnet-20241022")
    anthropic_api_key: str

    slack_webhook_url: str | None = Field(default=None)
    service_account_file: str = Field(default="service_account.json")
    sheets_document_name: str = Field(default="Invoices")

    approval_threshold: float = Field(default=500.0)

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")


settings = Settings()
