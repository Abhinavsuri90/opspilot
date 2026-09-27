import hashlib
import logging
import re
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from time import perf_counter
from typing import Annotated
from urllib.parse import quote

from fastapi import (
    Depends,
    FastAPI,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from psycopg.errors import DeadlockDetected, SerializationFailure
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import document_service, review_service
from app.access import can_access_document
from app.auth import (
    Identity,
    SessionResponse,
    describe_session,
    membership_denial,
    set_session_cookie,
)
from app.auth import (
    current_session as current_session,
)
from app.client_ip import client_ip, describe_strategy
from app.config import get_settings
from app.db import get_session, set_org_context
from app.document_service import (
    DocumentAccessDenied,
    DocumentLimitReached,
    DocumentNotRetryable,
    DocumentRetryLimitReached,
    DocumentSummary,
    InvalidDocument,
    MissingWorkflowConfig,
    UploadResponse,
)
from app.governance_api import router as governance_router
from app.intake_api import router as intake_router
from app.intake_models import ApiKey
from app.invoice_workflows import router as invoice_router
from app.limits import MAX_UPLOAD_BYTES, MAX_UPLOAD_REQUEST_BYTES
from app.login_throttle import (
    clear_attempts,
    client_blocked,
    record_client_failure,
    reserve_attempt,
)
from app.onboarding import router as onboarding_router
from app.repositories import (
    get_document_by_id,
    get_membership,
    get_organization_by_slug,
    get_user_by_email,
)
from app.review_service import DocumentDetail
from app.security import (
    DUMMY_PASSWORD_HASH,
    verify_password,
)
from app.settings_service import SettingsInvalid
from app.storage import ObjectStore, StorageError, get_store
from app.timeouts import ParserBusy
from app.workflow_config import DOCUMENT_TYPE_PATTERN

settings = get_settings()
logger = logging.getLogger("uvicorn.error.opspilot")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    logger.info("client_ip_strategy %s", describe_strategy())
    yield


app = FastAPI(title="OpsPilot API", version="0.1.0", lifespan=lifespan)
app.include_router(onboarding_router)
app.include_router(invoice_router)
app.include_router(governance_router)
app.include_router(intake_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.web_origin],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Request-ID"],
)


class LoginRequest(BaseModel):
    org_slug: str = Field(min_length=1, max_length=80)
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)

    @field_validator("org_slug", "email", mode="before")
    @classmethod
    def normalize_identifier(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: object | None = None


class ErrorEnvelope(BaseModel):
    error: ErrorDetail


def error_response(
    status_code: int,
    code: str,
    message: str,
    details: object | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    envelope = ErrorEnvelope(error=ErrorDetail(code=code, message=message, details=details))
    return JSONResponse(status_code=status_code, content=envelope.model_dump(), headers=headers)


def request_id_of(request: Request) -> str:
    return str(getattr(request.state, "request_id", "") or uuid.uuid4())


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = {
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
    }.get(exc.status_code, "request_failed")
    return error_response(exc.status_code, code, str(exc.detail))


@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = request_id_of(request)
    logger.exception("Unhandled API error request_id=%s", request_id, exc_info=exc)
    return error_response(
        500,
        "internal_error",
        "An unexpected error occurred",
        headers={"X-Request-ID": request_id},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    details = [
        {"field": ".".join(str(part) for part in error["loc"]), "message": error["msg"]}
        for error in exc.errors()
    ]
    return error_response(422, "validation_error", "Invalid request", details)


@app.exception_handler(DocumentRetryLimitReached)
async def retry_limit_error_handler(
    request: Request, exc: DocumentRetryLimitReached
) -> JSONResponse:
    return error_response(409, "retry_limit_reached", str(exc))


@app.exception_handler(SettingsInvalid)
async def settings_invalid_handler(request: Request, exc: SettingsInvalid) -> JSONResponse:
    return error_response(422, "validation_error", str(exc), exc.details or None)


@app.exception_handler(OperationalError)
async def transient_database_error_handler(request: Request, exc: OperationalError) -> JSONResponse:
    """Two writers on the same rows (a reviewer and the worker, say) lose nothing by retrying."""
    if isinstance(exc.orig, DeadlockDetected | SerializationFailure):
        return error_response(
            409, "conflict", "Try again", headers={"X-Request-ID": request_id_of(request)}
        )
    return await unexpected_error_handler(request, exc)


@app.middleware("http")
async def add_request_id(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    started = perf_counter()
    supplied_id = request.headers.get("X-Request-ID", "")
    request_id = (
        supplied_id if re.fullmatch(r"[A-Za-z0-9._-]{1,128}", supplied_id) else str(uuid.uuid4())
    )
    request.state.request_id = request_id
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        origin = request.headers.get("Origin")
        origin_mismatch = origin is not None and origin != settings.web_origin.rstrip("/")
        if origin_mismatch or request.headers.get("Sec-Fetch-Site") == "cross-site":
            return error_response(
                403,
                "forbidden",
                "Request origin is not allowed",
                headers={"X-Request-ID": request_id},
            )
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        upload = request.url.path == "/v1/documents"
        limit = MAX_UPLOAD_REQUEST_BYTES if upload else 64 * 1024
        message = (
            "Upload request exceeds the 10 MB PDF limit" if upload else "Request body exceeds 64 KB"
        )
        declared_size = request.headers.get("content-length")
        try:
            too_large = declared_size is not None and (
                int(declared_size) < 0 or int(declared_size) > limit
            )
        except ValueError:
            too_large = True
        chunks: list[bytes] = []
        size = 0
        if not too_large:
            async for chunk in request.stream():
                size += len(chunk)
                if size > limit:
                    too_large = True
                    break
                chunks.append(chunk)
        if too_large:
            return error_response(
                413,
                "upload_too_large" if upload else "request_too_large",
                message,
                headers={"X-Request-ID": request_id},
            )
        request._body = b"".join(chunks)
    try:
        response = await call_next(request)
    except Exception:
        # The outer server error handler builds the 500 response; log the
        # completion line here so every request, failed or not, has one.
        _log_request(request, 500, started, request_id)
        raise
    response.headers["X-Request-ID"] = request_id
    duration_ms = _log_request(request, response.status_code, started, request_id)
    response.headers["Server-Timing"] = f"api;dur={duration_ms:.1f}"
    response.headers["Cache-Control"] = "no-store"
    return response


def _log_request(request: Request, status_code: int, started: float, request_id: str) -> float:
    duration_ms = (perf_counter() - started) * 1000
    route = request.scope.get("route")
    logger.info(
        "request_complete method=%s route=%s status=%d duration_ms=%.1f request_id=%s",
        request.method,
        getattr(route, "path", "unmatched"),
        status_code,
        duration_ms,
        request_id,
    )
    return duration_ms


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
def readyz(session: Annotated[Session, Depends(get_session)]) -> dict[str, str]:
    if not settings.s3_bucket.strip():
        raise HTTPException(status_code=503, detail="Object storage is not configured")
    try:
        # These tables are required for the document workflow. A fresh but
        # unmigrated database must not be considered ready by the platform.
        session.execute(
            text(
                "SELECT d.id FROM organizations AS o, users AS u, memberships AS m, "
                "workflow_configs AS w, audit_events AS a, documents AS d, "
                "outbox_events AS e, extraction_runs AS r, extracted_fields AS f, "
                "login_attempts AS l, invoice_metadata AS im, invoice_categories AS ic, "
                "invoice_comments AS co, invoice_reviews AS rv, invoice_grants AS dg, "
                "field_corrections AS fc, review_tasks AS rt, org_settings AS os, "
                "action_policies AS ap, connector_instances AS ci, actions AS ac, "
                "action_attempts AS aa, document_links AS dl, api_keys AS ak, "
                "email_inboxes AS ei, email_messages AS em, llm_calls AS lc, "
                "memory_items AS mi LIMIT 0"
            )
        )
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database schema is not ready") from exc
    return {"status": "ready"}


@app.post("/v1/auth/login", response_model=SessionResponse)
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
) -> SessionResponse:
    address = client_ip(request)
    # The address budget is checked first and only charged on failure, so shared
    # addresses with many correct logins are never blocked and cannot burn an
    # account's budget once the address itself is blocked.
    if client_blocked(session, address) or not reserve_attempt(session, body.org_slug, body.email):
        raise HTTPException(
            status_code=429, detail="Too many login attempts; try again in 15 minutes"
        )
    org = get_organization_by_slug(session, body.org_slug)
    user = get_user_by_email(session, body.email)
    # Keep the same public error for all credential failures.
    password_hash = user.password_hash if user is not None else DUMMY_PASSWORD_HASH
    password_valid = verify_password(password_hash, body.password)
    if org is None or user is None or not password_valid:
        record_client_failure(session, address)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    set_org_context(session, org.id)
    membership = get_membership(session, org.id, user.id)
    if membership is None:
        record_client_failure(session, address)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if membership.status != "active":
        # The credentials were right, so this pending or suspended account only
        # spends the single account reservation made above and is never cleared here.
        raise HTTPException(status_code=403, detail=membership_denial(membership))
    clear_attempts(session, body.org_slug, body.email)
    set_session_cookie(response, user.id, org.id)
    return describe_session(user, org, membership)


@app.post("/v1/auth/logout", status_code=204)
def logout(response: Response) -> None:
    response.delete_cookie("opspilot_session", path="/")


@app.get("/v1/auth/me", response_model=SessionResponse)
def me(
    identity: Annotated[Identity, Depends(current_session)],
) -> SessionResponse:
    _, user, org, membership = identity
    return describe_session(user, org, membership)


@app.post("/v1/documents", response_model=UploadResponse, status_code=202)
def upload_document(
    file: Annotated[UploadFile, File()],
    request: Request,
    identity: Annotated[Identity, Depends(current_session)],
    store: Annotated[ObjectStore, Depends(get_store)],
) -> UploadResponse:
    session, user, org, membership = identity
    if membership.role not in ("admin", "reviewer", "member"):
        raise HTTPException(status_code=403, detail="Uploader role required")
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    # Set by app.auth when the request carried an API key instead of a session cookie.
    state_key = getattr(request.state, "api_key", None)
    key = state_key if isinstance(state_key, ApiKey) else None
    try:
        return document_service.upload(
            session,
            store,
            org.id,
            user.id,
            file.filename or "",
            data,
            membership.role,
            source="api" if key else "upload",
            source_ref=f"API key {key.name}" if key else None,
            audit_detail={"api_key_id": str(key.id)} if key else None,
        )
    except DocumentAccessDenied as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except InvalidDocument as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except MissingWorkflowConfig as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except DocumentLimitReached as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ParserBusy as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except StorageError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/v1/documents", response_model=list[DocumentSummary])
def documents(
    identity: Annotated[Identity, Depends(current_session)],
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    category_id: uuid.UUID | None = None,
    q: Annotated[str | None, Query(min_length=1, max_length=255)] = None,
    status: Annotated[
        str | None,
        Query(
            pattern="^(in_progress|queued|extracting|validating|needs_review|approved|"
            "auto_approved|rejected|failed|actions_pending|completed)$"
        ),
    ] = None,
    document_type: Annotated[str | None, Query(pattern=DOCUMENT_TYPE_PATTERN)] = None,
    source: Annotated[str | None, Query(pattern="^(upload|email|api)$")] = None,
) -> list[DocumentSummary]:
    session, user, org, membership = identity
    return document_service.browse(
        session,
        org.id,
        user.id,
        membership.role,
        offset=offset,
        limit=limit,
        status=status,
        category_id=category_id,
        q=q,
        document_type=document_type,
        source=source,
    )


@app.get("/v1/documents/{document_id}", response_model=DocumentDetail)
def document_detail(
    document_id: uuid.UUID,
    identity: Annotated[Identity, Depends(current_session)],
) -> DocumentDetail:
    session, user, org, membership = identity
    result = review_service.read_document(session, org.id, document_id, user.id, membership.role)
    if result is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return result


@app.post("/v1/documents/{document_id}/retry", response_model=DocumentSummary, status_code=202)
def retry_document(
    document_id: uuid.UUID,
    identity: Annotated[Identity, Depends(current_session)],
) -> DocumentSummary:
    session, user, org, membership = identity
    if membership.role not in ("admin", "reviewer", "member"):
        raise HTTPException(status_code=403, detail="Uploader role required")
    try:
        result = document_service.retry(session, org.id, user.id, document_id, membership.role)
    except DocumentNotRetryable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return result


@app.get("/v1/documents/{document_id}/file", response_class=Response)
def document_file(
    document_id: uuid.UUID,
    identity: Annotated[Identity, Depends(current_session)],
    store: Annotated[ObjectStore, Depends(get_store)],
    download: bool = False,
) -> Response:
    session, user, org, membership = identity
    document = get_document_by_id(session, org.id, document_id)
    if document is None or not can_access_document(
        session, org.id, user.id, membership.role, document
    ):
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        data = store.get(document.storage_key)
    except StorageError as exc:
        raise HTTPException(status_code=503, detail="Document storage is unavailable") from exc
    if (
        len(data) != document.size_bytes
        or hashlib.sha256(data).hexdigest() != document.content_hash
    ):
        raise HTTPException(status_code=503, detail="Stored document failed integrity check")
    disposition = "attachment" if download else "inline"
    encoded_filename = quote(document.filename, safe="")
    return Response(
        content=data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{encoded_filename}",
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox",
        },
    )
