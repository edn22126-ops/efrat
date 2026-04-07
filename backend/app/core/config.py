from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    DATABASE_URL: str = "postgresql://plms:plms@localhost:5432/plms"

    # AWS
    AWS_REGION: str = "us-east-1"
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    S3_BUCKET: str = "plms-documents"
    SQS_OCR_QUEUE_URL: str = ""

    # App
    SECRET_KEY: str = "change-me-in-production"
    PRESIGNED_URL_EXPIRY: int = 3600  # seconds


settings = Settings()
