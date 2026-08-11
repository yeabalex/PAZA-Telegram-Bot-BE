"""Core configuration module."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "Paza Event Bot Backend"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    PORT: int = 8000
    HOST: str = "0.0.0.0"

    # PostgreSQL Database Settings
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "addis_event_db"
    DATABASE_URL: str | None = None

    @property
    def sqlalchemy_database_uri(self) -> str:
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    # Redis Settings
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_URL: str = "redis://localhost:6379/0"

    # LLM API Keys
    GEMINI_API_KEY: str = ""
    DEEPSEEK_API_KEY: str = ""
    GROQ_API_KEY: str = ""

    # Security / Auth Settings
    JWT_SECRET_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_DAYS: int = 30
    GOOGLE_CLIENT_ID: str = ""

    # Telegram Bot & Mini App Settings
    TELEGRAM_BOT_TOKEN: str = ""
    MINI_APP_URL: str = ""
    ADMIN_TELEGRAM_CHAT_ID: str = ""

    # Scraper Session Cookies
    INSTAGRAM_SESSION_ID: str = ""
    TIKTOK_SESSION_ID: str = ""

    # Cloudflare R2 Storage Settings
    R2_ACCOUNT_ID: str = ""
    R2_ACCESS_KEY_ID: str = ""
    R2_SECRET_ACCESS_KEY: str = ""
    R2_BUCKET_NAME: str = "paza-events"
    R2_PUBLIC_URL: str = ""
    UPLOAD_DIR: str = "static/uploads"

    # Cloudinary Storage Settings
    CLOUDINARY_CLOUD_NAME: str = ""
    CLOUDINARY_API_KEY: str = ""
    CLOUDINARY_API_SECRET: str = ""
    CLOUDINARY_URL: str = ""

    from pydantic import field_validator

    @field_validator(
        "PORT",
        "POSTGRES_PORT",
        "REDIS_PORT",
        "JWT_ACCESS_TOKEN_EXPIRE_DAYS",
        mode="before",
    )
    @classmethod
    def parse_empty_int(cls, v, info):
        if v == "" or v is None:
            defaults = {
                "PORT": 8000,
                "POSTGRES_PORT": 5432,
                "REDIS_PORT": 6379,
                "JWT_ACCESS_TOKEN_EXPIRE_DAYS": 30,
            }
            return defaults.get(info.field_name, 30)
        return int(v)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()


