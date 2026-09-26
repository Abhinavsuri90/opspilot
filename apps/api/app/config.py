from functools import lru_cache
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://opspilot_app:app_dev_password@localhost:5432/opspilot"
    jwt_secret: str = "dev-only-change-me-before-deployment"
    cookie_secure: bool = False
    web_origin: str = "http://localhost:3300"
    environment: str = "development"
    s3_endpoint_url: str | None = None
    s3_bucket: str = "documents"
    s3_region: str = "us-east-1"
    s3_addressing_style: Literal["auto", "path", "virtual"] = "auto"
    s3_access_key_id: str = "local"
    s3_secret_access_key: str = "local"
    llm_provider: str = "mock"
    openrouter_api_key: str | None = None
    openrouter_model: str = "google/gemini-3.8-flash"
    max_documents_per_org: int = Field(default=100, ge=1, le=100_000)

    @model_validator(mode="after")
    def reject_unsafe_deployment(self) -> "Settings":
        if self.environment != "development":
            if (
                self.jwt_secret == "dev-only-change-me-before-deployment"
                or len(self.jwt_secret) < 32
            ):
                raise ValueError("JWT_SECRET must be a strong deployment secret")
            if not self.cookie_secure:
                raise ValueError("COOKIE_SECURE must be true outside development")
            web_origin = urlparse(self.web_origin)
            if (
                web_origin.scheme != "https"
                or web_origin.hostname is None
                or web_origin.username is not None
                or web_origin.password is not None
                or web_origin.path
                or web_origin.params
                or web_origin.query
                or web_origin.fragment
            ):
                raise ValueError("WEB_ORIGIN must be an HTTPS origin outside development")
            try:
                if web_origin.port == 0:
                    raise ValueError("WEB_ORIGIN must have a valid port")
            except ValueError as exc:
                raise ValueError("WEB_ORIGIN must have a valid port") from exc
            database = urlparse(self.database_url)
            if (
                database.scheme not in {"postgres", "postgresql", "postgresql+psycopg"}
                or database.username != "opspilot_app"
                or not database.password
                or not database.path.strip("/")
                or database.hostname in {None, "localhost", "127.0.0.1", "host.docker.internal"}
            ):
                raise ValueError("DATABASE_URL must use the remote restricted Postgres role")
            if not self.s3_bucket.strip() or self.s3_bucket == "documents":
                raise ValueError("Set a nondefault S3_BUCKET outside development")
            if "s3_region" not in self.model_fields_set or not self.s3_region.strip():
                raise ValueError("Set S3_REGION outside development")
            key = self.s3_access_key_id.strip()
            secret = self.s3_secret_access_key.strip()
            if key == "local" or secret == "local":
                raise ValueError("Local S3 credentials cannot be used outside development")
            if bool(key) != bool(secret):
                raise ValueError("Set both S3 credential values, or neither for AWS IAM")
            if self.s3_endpoint_url:
                endpoint = urlparse(self.s3_endpoint_url)
                hostname = endpoint.hostname or ""
                if (
                    endpoint.scheme != "https"
                    or not hostname
                    or hostname in {"localhost", "127.0.0.1", "s3mock"}
                    or "s3mock" in hostname
                    or endpoint.username is not None
                    or endpoint.password is not None
                ):
                    raise ValueError("S3_ENDPOINT_URL must be a remote HTTPS endpoint")
                if not key:
                    raise ValueError("Custom S3 endpoints require explicit credentials")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
