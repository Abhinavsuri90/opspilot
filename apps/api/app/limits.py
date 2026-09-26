"""Document size limits shared by the API, storage adapter, and worker."""

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
# Multipart boundaries and headers need room beyond the PDF itself.
MAX_UPLOAD_REQUEST_BYTES = MAX_UPLOAD_BYTES + 128 * 1024
