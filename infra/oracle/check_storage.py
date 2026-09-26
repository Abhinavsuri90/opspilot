"""Run inside the configured API container; creates one tiny synthetic PDF."""

from io import BytesIO
from uuid import uuid4

from pypdf import PdfWriter

from app.storage import StorageError, get_store

buffer = BytesIO()
writer = PdfWriter()
writer.add_blank_page(width=72, height=72)
writer.write(buffer)
payload = buffer.getvalue()
key = f"_deployment-checks/{uuid4()}.pdf"

try:
    store = get_store()
    store.put(key, payload)
    if store.get(key) != payload:
        raise SystemExit("Storage check failed: uploaded and downloaded bytes differ.")
except StorageError:
    raise SystemExit(
        "Storage check failed. Verify bucket, namespace, region, permissions and keys."
    ) from None

print("Storage PUT/GET passed.")
print(f"Synthetic check object: {key}")
print("Delete this specific object in Oracle Console after the check.")
