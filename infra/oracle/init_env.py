#!/usr/bin/env python3
"""Create the VM's private configuration without printing credentials."""

import base64
import getpass
import os
from pathlib import Path
import re
import secrets
from urllib.parse import urlparse


def required(prompt: str, *, hidden: bool = False) -> str:
    while True:
        value = (getpass.getpass(prompt) if hidden else input(prompt)).strip()
        # Single quotes keep dollar signs literal in Compose dotenv files.
        if value and not any(char in value for char in "\r\n'\\"):
            return value
        print("Enter a nonempty single-line value without quotes or backslashes.")


def main() -> None:
    destination = Path(__file__).resolve().with_name(".env")
    if destination.exists():
        raise SystemExit(
            "Configuration already exists; edit it instead of replacing passwords."
        )

    domain = required(
        "Public hostname, e.g. your-name.duckdns.org (no https://): "
    ).lower()
    if (
        len(domain) > 253
        or "." not in domain
        or not all(
            re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
            for label in domain.split(".")
        )
    ):
        raise SystemExit("Use a DNS hostname without a scheme, path or port.")
    region = required("OCI bucket region identifier, e.g. ap-mumbai-1: ")
    endpoint = required("OCI S3 compatibility HTTPS endpoint: ").rstrip("/")
    parsed = urlparse(endpoint)
    host = parsed.hostname or ""
    if (
        parsed.scheme != "https"
        or ".compat.objectstorage." not in host
        or not host.endswith((".oraclecloud.com", ".oci.customer-oci.com"))
        or parsed.username
        or parsed.password
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.port
    ):
        raise SystemExit(
            "Use the OCI S3 compatibility endpoint, without the bucket name."
        )
    bucket = required("Private bucket name: ")
    access_key = required("Customer Secret Key ACCESS KEY (hidden): ", hidden=True)
    secret_key = required("Customer Secret Key SECRET KEY (hidden): ", hidden=True)

    values = {
        "OPSPILOT_DOMAIN": domain,
        "POSTGRES_PASSWORD": secrets.token_hex(32),
        "APP_DB_PASSWORD": secrets.token_hex(32),
        "JWT_SECRET": secrets.token_hex(48),
        # Fernet key: 32 random bytes, URL-safe base64. Rotating it makes stored
        # connector credentials unreadable until they are re-entered.
        "CONNECTOR_ENCRYPTION_KEY": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii"),
        "S3_REGION": region,
        "S3_ENDPOINT_URL": endpoint,
        "S3_BUCKET": bucket,
        "S3_ACCESS_KEY_ID": access_key,
        "S3_SECRET_ACCESS_KEY": secret_key,
        "LLM_PROVIDER": "rules",
        "EXTRACTION_TIMEOUT_SECONDS": "60",
        "UPLOAD_PARSE_TIMEOUT_SECONDS": "15",
        "MAX_CONCURRENT_PARSES": "4",
        "ACTION_EXECUTE_TIMEOUT_SECONDS": "30",
        "MAX_DOCUMENTS_PER_ORG": "1000",
        "OPENROUTER_API_KEY": "",
        "OPENROUTER_MODEL": "",
    }
    # Exclusive creation prevents overwriting an existing database's passwords.
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        stream.write("# Private VM configuration. Keep an encrypted off-server copy.\n")
        for key, value in values.items():
            stream.write(f"{key}='{value}'\n")
    print(f"Created {destination} with permissions 600. No credentials were printed.")


if __name__ == "__main__":
    main()
