"""Application settings loaded from environment / .env file."""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_env: str = "development"
    secret_key: str = "change-me"

    database_url: str = "postgresql+asyncpg://efrat:efrat@localhost:5432/efrat"

    aws_region: str = "us-east-1"
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""

    s3_bucket: str = "efrat-evidence-files"
    sqs_queue_url: str = ""

    textract_region: str = "us-east-1"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()
