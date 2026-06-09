from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # App
    APP_NAME: str = "AirYield"
    DEBUG: bool = False

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:password@localhost:5432/airyield"
    DATABASE_URL_SYNC: str = "postgresql://postgres:password@localhost:5432/airyield"

    # Auth
    SECRET_KEY: str = "change-me-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours

    # Redis / Celery
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"

    # File uploads
    UPLOAD_DIR: str = "uploads"
    MAX_UPLOAD_SIZE_MB: int = 50

    # CORS
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    # OpenAI
    OPENAI_API_KEY: str = ""

    # GCP Cloud Storage
    GCS_DEALS_BUCKET_NAME: str = ""
    GCS_TICKETS_BUCKET_NAME: str = ""
    GCS_SERVICE_ACCOUNT_EMAIL: str = ""
    GCS_SERVICE_ACCOUNT_PRIVATE_KEY: str = ""
    GCS_PROJECT_ID: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
