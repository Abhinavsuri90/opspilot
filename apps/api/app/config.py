from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://opspilot_app:app_dev_password@localhost:5432/opspilot"
    jwt_secret: str = "dev-only-change-me-before-deployment"
    cookie_secure: bool = False
    web_origin: str = "http://localhost:3300"
    environment: str = "development"

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
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
