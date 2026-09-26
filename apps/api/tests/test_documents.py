import json
import os
import uuid
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.llm.provider import ExtractionError, MockInvoiceProvider, OpenRouterInvoiceProvider
from app.main import app
from app.storage import get_store
from app.worker import process_one

SAMPLE = Path(__file__).parents[3] / "examples" / "northwind-invoice.pdf"


class MemoryStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, key: str, data: bytes) -> None:
        self.objects[key] = data

    def get(self, key: str) -> bytes:
        return self.objects[key]


def test_mock_provider_returns_grounded_invoice_fields() -> None:
    fields = MockInvoiceProvider().extract(SAMPLE.read_bytes())
    assert {field.name: field.value for field in fields} == {
        "vendor": "Northwind Traders",
        "invoice_number": "NW-2026-001",
        "invoice_date": "2026-09-26",
        "total": "$123.45",
    }
    assert all(field.evidence.endswith(field.value) and field.page_number == 1 for field in fields)


def test_openrouter_provider_uses_schema_and_rejects_ungrounded_values() -> None:
    def response(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["model"] == "google/gemini-3.8-flash"
        assert payload["response_format"]["type"] == "json_schema"
        assert payload["provider"]["require_parameters"] is True
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "fields": [
                                        {
                                            "name": "total",
                                            "value": "$123.45",
                                            "evidence": "Total: $123.45",
                                            "page_number": 1,
                                        }
                                    ]
                                }
                            )
                        }
                    }
                ]
            },
        )

    with httpx.Client(transport=httpx.MockTransport(response)) as client:
        provider = OpenRouterInvoiceProvider("test-only-key", "google/gemini-3.8-flash", client)
        assert provider.extract(SAMPLE.read_bytes())[0].value == "$123.45"

    def ungrounded(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "fields": [
                                        {
                                            "name": "total",
                                            "value": "$999.99",
                                            "evidence": "Total: $999.99",
                                            "page_number": 1,
                                        }
                                    ]
                                }
                            )
                        }
                    }
                ]
            },
        )

    with httpx.Client(transport=httpx.MockTransport(ungrounded)) as client:
        provider = OpenRouterInvoiceProvider("test-only-key", "google/gemini-3.8-flash", client)
        with pytest.raises(ExtractionError):
            provider.extract(SAMPLE.read_bytes())


@pytest.mark.skipif("DATABASE_OWNER_URL" not in os.environ, reason="Postgres integration test")
def test_upload_dedup_extraction_and_tenant_visibility() -> None:
    store = MemoryStore()
    app.dependency_overrides[get_store] = lambda: store
    invoice_number = uuid.uuid4().hex[:11].upper()
    data = SAMPLE.read_bytes().replace(b"NW-2026-001", invoice_number.encode("ascii"))
    try:
        with TestClient(app) as client:
            login = client.post(
                "/v1/auth/login",
                json={
                    "org_slug": "northwind",
                    "email": "northwind@example.com",
                    "password": os.environ["DEMO_PASSWORD"],
                },
            )
            assert login.status_code == 200

            invalid = client.post(
                "/v1/documents", files={"file": ("fake.pdf", b"not a PDF", "application/pdf")}
            )
            assert invalid.status_code == 400
            assert store.objects == {}

            uploaded = client.post(
                "/v1/documents", files={"file": ("invoice.pdf", data, "application/pdf")}
            )
            assert uploaded.status_code == 202, uploaded.text
            assert uploaded.json()["status"] == "queued"
            assert uploaded.json()["duplicate"] is False
            document_id = uploaded.json()["id"]
            assert len(store.objects) == 1

            duplicate = client.post(
                "/v1/documents", files={"file": ("renamed.pdf", data, "application/pdf")}
            )
            assert duplicate.status_code == 202
            assert duplicate.json()["id"] == document_id
            assert duplicate.json()["duplicate"] is True

            assert process_one(store, uuid.UUID(document_id)) is True
            detail = client.get(f"/v1/documents/{document_id}")
            assert detail.status_code == 200
            assert detail.json()["status"] == "needs_review"
            fields = {field["name"]: field for field in detail.json()["fields"]}
            assert fields["invoice_number"]["value"] == invoice_number
            assert fields["invoice_number"]["evidence"].endswith(invoice_number)
            assert any(row["id"] == document_id for row in client.get("/v1/documents").json())

            other_login = client.post(
                "/v1/auth/login",
                json={
                    "org_slug": "contoso",
                    "email": "contoso@example.com",
                    "password": os.environ["DEMO_PASSWORD"],
                },
            )
            assert other_login.status_code == 200
            assert client.get(f"/v1/documents/{document_id}").status_code == 404
            assert all(row["id"] != document_id for row in client.get("/v1/documents").json())
    finally:
        del app.dependency_overrides[get_store]
