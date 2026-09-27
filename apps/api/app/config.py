import ipaddress
import json
from functools import lru_cache
from typing import Literal
from urllib.parse import urlparse

from cryptography.fernet import Fernet
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://opspilot_app:app_dev_password@localhost:5432/opspilot"
    jwt_secret: str = "dev-only-change-me-before-deployment"
    cookie_secure: bool = False
    web_origin: str = "http://localhost:3300"
    # Fail closed: an unset ENVIRONMENT gets the production checks below. Local
    # development, tests and CI set ENVIRONMENT=development explicitly.
    environment: str = "production"
    s3_endpoint_url: str | None = None
    s3_bucket: str = "documents"
    s3_region: str = "us-east-1"
    s3_addressing_style: Literal["auto", "path", "virtual"] = "auto"
    s3_access_key_id: str = "local"
    s3_secret_access_key: str = "local"
    llm_provider: str = "rules"
    openrouter_api_key: str | None = None
    openrouter_model: str = "google/gemini-3.8-flash"
    # Model router (app/llm/router.py): tier 1 defaults to OPENROUTER_MODEL; tier 2 is a
    # stronger OpenRouter model that re-runs only the fields tier 1 could not settle. Unset
    # means no escalation.
    llm_tier1_model: str | None = None
    llm_tier2_model: str | None = None
    # JSON object {model id: [input cents per 1M tokens, output cents per 1M tokens]} merged
    # over the built-in table in app/llm/pricing.py.
    llm_price_table_json: str | None = None
    # What the worker does for a paid provider once an organization's daily budget is spent:
    # "defer" retries the document after 00:05 UTC, "rules" extracts with the rules provider.
    llm_budget_fallback: Literal["defer", "rules"] = "defer"
    # Optional OpenAI-compatible embeddings endpoint for memory retrieval; unset means the
    # deterministic local hashing embedder (app/llm/embeddings.py).
    embeddings_base_url: str | None = None
    embeddings_model: str | None = None
    embeddings_api_key: str | None = None
    max_documents_per_org: int = Field(default=100, ge=1, le=100_000)
    # Wall-clock limits for PDF parsing and extraction; see app/timeouts.py. The
    # extraction limit stays under the worker's 5-minute lease (app/worker.py).
    extraction_timeout_seconds: float = Field(default=60, gt=0, le=240)
    upload_parse_timeout_seconds: float = Field(default=15, gt=0, le=120)
    # Per-process cap on concurrent PDF parses; see app/timeouts.py.
    max_concurrent_parses: int = Field(default=4, ge=1, le=64)
    # Wall-clock limit for one connector execution; see app/worker.py. It stays under
    # the worker lease so a hung destination cannot be reclaimed mid-call.
    action_execute_timeout_seconds: float = Field(default=30, gt=0, le=120)
    # Per-process cap on concurrent connector calls, separate from PDF parsing.
    max_concurrent_connector_calls: int = Field(default=4, ge=1, le=64)
    # Fernet key for connector credentials at rest; see app/connectors/credentials.py.
    # Development derives a local-only key from JWT_SECRET when this is unset.
    connector_encryption_key: str | None = None
    # Development-only email backend: the Mailpit HTTP API the worker polls for
    # <slug>@opspilot.local mailboxes; see app/email_intake.py. Unset outside development.
    mailpit_api_url: str | None = None
    # Peers allowed to supply X-Forwarded-For; see app/client_ip.py.
    trusted_proxy_cidrs: str = (
        "127.0.0.0/8,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,::1/128,fc00::/7"
    )

    @field_validator("connector_encryption_key")
    @classmethod
    def parse_connector_encryption_key(cls, value: str | None) -> str | None:
        key = (value or "").strip()
        if not key:
            return None
        try:
            Fernet(key.encode("ascii"))
        except (ValueError, TypeError) as exc:
            raise ValueError(
                "CONNECTOR_ENCRYPTION_KEY must be a Fernet key (44 URL-safe base64 characters)"
            ) from exc
        return key

    @field_validator("llm_tier1_model", "llm_tier2_model", "embeddings_model", "embeddings_api_key")
    @classmethod
    def blank_is_unset(cls, value: str | None) -> str | None:
        text = (value or "").strip()
        return text or None

    @field_validator("llm_price_table_json")
    @classmethod
    def parse_price_table_json(cls, value: str | None) -> str | None:
        text = (value or "").strip()
        if not text:
            return None
        try:
            decoded = json.loads(text)
        except ValueError as exc:
            raise ValueError("LLM_PRICE_TABLE_JSON must be a JSON object") from exc
        if not isinstance(decoded, dict):
            raise ValueError("LLM_PRICE_TABLE_JSON must be a JSON object")
        for model, prices in decoded.items():
            if (
                not isinstance(model, str)
                or not isinstance(prices, list)
                or len(prices) != 2
                or not all(isinstance(price, int | float) and price >= 0 for price in prices)
            ):
                raise ValueError(
                    "LLM_PRICE_TABLE_JSON entries must be model id -> [input, output] cents per 1M"
                )
        return text

    @field_validator("embeddings_base_url")
    @classmethod
    def parse_embeddings_base_url(cls, value: str | None) -> str | None:
        url = (value or "").strip().rstrip("/")
        if not url:
            return None
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("EMBEDDINGS_BASE_URL must be an absolute http(s) URL")
        return url

    @field_validator("mailpit_api_url")
    @classmethod
    def parse_mailpit_api_url(cls, value: str | None) -> str | None:
        url = (value or "").strip().rstrip("/")
        if not url:
            return None
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("MAILPIT_API_URL must be an absolute http(s) URL")
        return url

    @field_validator("trusted_proxy_cidrs")
    @classmethod
    def parse_trusted_proxy_cidrs(cls, value: str) -> str:
        networks = []
        for entry in value.split(","):
            if not entry.strip():
                continue
            try:
                networks.append(str(ipaddress.ip_network(entry.strip(), strict=False)))
            except ValueError as exc:
                raise ValueError(f"TRUSTED_PROXY_CIDRS entry is not a CIDR: {entry!r}") from exc
        return ",".join(networks)

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
            if self.connector_encryption_key is None:
                raise ValueError("CONNECTOR_ENCRYPTION_KEY is required outside development")
            if self.mailpit_api_url:
                raise ValueError("MAILPIT_API_URL is a development-only setting")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
