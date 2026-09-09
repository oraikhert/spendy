"""Application configuration"""
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings"""
    
    # Application
    APP_NAME: str = "Spendy"
    DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"
    
    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./spendy.db"
    UPLOAD_DIR: str = "data/uploads"
    MAX_UPLOAD_SIZE_BYTES: int = 20 * 1024 * 1024
    
    # Exchange Rate API (Open Access)
    EXCHANGE_RATE_API_BASE_URL: str = "https://open.er-api.com"
    EXCHANGE_RATE_CACHE_TTL_SECONDS: int = 3600

    # Security
    REGISTRATION_ENABLED: bool = True  # Set False to block self-registration
    SECRET_KEY: str = "09d25e094faa6ca2556c818166b7a9563b93f7099f6f0f4caa6cf63b88e8d3e7"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # Workspace invitations (request-driven SMTP; no background worker)
    SMTP_HOST: str = "localhost"
    SMTP_PORT: int = Field(default=587, ge=1, le=65535)
    SMTP_USERNAME: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_SENDER: str = "noreply@localhost"
    SMTP_STARTTLS: bool = True
    PUBLIC_BASE_URL: str = "http://localhost:8000"
    SMTP_TIMEOUT_SECONDS: float = Field(default=10.0, gt=0, le=60)
    WORKSPACE_INVITATION_LIFETIME_DAYS: int = Field(default=7, ge=1, le=30)

    @field_validator("SMTP_USERNAME", "SMTP_PASSWORD", mode="before")
    @classmethod
    def empty_smtp_credentials_are_absent(cls, value):
        return None if value == "" else value
    
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore"
    )


settings = Settings()
