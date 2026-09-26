from functools import lru_cache
from typing import Any, Protocol

import boto3  # type: ignore[import-untyped]
from botocore.config import Config  # type: ignore[import-untyped]
from botocore.exceptions import BotoCoreError, ClientError  # type: ignore[import-untyped]

from app.config import get_settings
from app.limits import MAX_UPLOAD_BYTES


class StorageError(Exception):
    pass


class StoredDocumentTooLarge(StorageError):
    pass


class ObjectStore(Protocol):
    def put(self, key: str, data: bytes) -> None: ...

    def get(self, key: str) -> bytes: ...


class S3ObjectStore:
    def __init__(self) -> None:
        settings = get_settings()
        self.bucket = settings.s3_bucket
        client_options: dict[str, Any] = {
            "endpoint_url": settings.s3_endpoint_url,
            "region_name": settings.s3_region,
            "config": Config(
                s3={"addressing_style": settings.s3_addressing_style},
                retries={"max_attempts": 2},
                connect_timeout=5,
                read_timeout=30,
            ),
        }
        if settings.s3_access_key_id and settings.s3_secret_access_key:
            client_options["aws_access_key_id"] = settings.s3_access_key_id
            client_options["aws_secret_access_key"] = settings.s3_secret_access_key
        self.client = boto3.client("s3", **client_options)

    def put(self, key: str, data: bytes) -> None:
        try:
            self.client.put_object(
                Bucket=self.bucket, Key=key, Body=data, ContentType="application/pdf"
            )
        except (BotoCoreError, ClientError) as exc:
            raise StorageError("Object storage is unavailable") from exc

    def get(self, key: str) -> bytes:
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
            body = response["Body"]
            try:
                if response.get("ContentLength", 0) > MAX_UPLOAD_BYTES:
                    raise StoredDocumentTooLarge("Stored document exceeds the 10 MB PDF limit")
                data = bytes(body.read(MAX_UPLOAD_BYTES + 1))
                if len(data) > MAX_UPLOAD_BYTES:
                    raise StoredDocumentTooLarge("Stored document exceeds the 10 MB PDF limit")
                return data
            finally:
                body.close()
        except (BotoCoreError, ClientError) as exc:
            raise StorageError("Object storage is unavailable") from exc


@lru_cache
def get_store() -> ObjectStore:
    return S3ObjectStore()
