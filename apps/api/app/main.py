import logging
import re
import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import (
    Cookie,
    Depends,
    FastAPI,
    File,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import document_service
from app.config import get_settings
from app.db import get_session, set_org_context
from app.document_service import (
    DocumentDetail,
    DocumentLimitReached,
    DocumentNotRetryable,
    DocumentRetryLimitReached,
    DocumentSummary,
    InvalidDocument,
    MissingWorkflowConfig,
    UploadResponse,
)
from app.limits import MAX_UPLOAD_BYTES, MAX_UPLOAD_REQUEST_BYTES
from app.login_throttle import clear_attempts, reserve_attempt
from app.models import Membership, Organization, User
from app.repositories import (
    get_membership,
    get_organization_by_id,
    get_organization_by_slug,
    get_user_by_email,
    get_user_by_id,
    list_members,
)
from app.security import (
    DUMMY_PASSWORD_HASH,
    make_session_token,
    read_session_token,
    verify_password,
)
from app.storage import ObjectStore, StorageError, get_store

settings = get_settings()
logger = logging.getLogger(__name__)
app = FastAPI(title="OpsPilot API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.web_origin],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Request-ID"],
)


class LoginRequest(BaseModel):
    org_slug: str
    email: EmailStr
    password: str

    @field_validator("org_slug", "email", mode="before")
    @classmethod
    def normalize_identifier(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value


class SessionResponse(BaseModel):
    user_id: uuid.UUID
    email: str
    org_id: uuid.UUID
    org_name: str
    role: str


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: object | None = None


class ErrorEnvelope(BaseModel):
    error: ErrorDetail


class MemberResponse(BaseModel):
    user_id: uuid.UUID
    email: str
    role: str


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = {
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
    }.get(exc.status_code, "request_failed")
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": code, "message": str(exc.detail), "details": None}},
    )


@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled API error", exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "internal_error",
                "message": "An unexpected error occurred",
                "details": None,
            }
        },
        headers={"X-Request-ID": getattr(request.state, "request_id", str(uuid.uuid4()))},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    details = [
        {"field": ".".join(str(part) for part in error["loc"]), "message": error["msg"]}
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={
            "error": {"code": "validation_error", "message": "Invalid request", "details": details}
        },
    )


@app.exception_handler(DocumentRetryLimitReached)
async def retry_limit_error_handler(
    request: Request, exc: DocumentRetryLimitReached
) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={
            "error": {
                "code": "retry_limit_reached",
                "message": str(exc),
                "details": None,
            }
        },
    )


@app.middleware("http")
async def add_request_id(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    supplied_id = request.headers.get("X-Request-ID", "")
    request_id = (
        supplied_id if re.fullmatch(r"[A-Za-z0-9._-]{1,128}", supplied_id) else str(uuid.uuid4())
    )
    request.state.request_id = request_id
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        origin = request.headers.get("Origin")
        origin_mismatch = origin is not None and origin != settings.web_origin.rstrip("/")
        if origin_mismatch or request.headers.get("Sec-Fetch-Site") == "cross-site":
            denial = JSONResponse(
                status_code=403,
                content={
                    "error": {
                        "code": "forbidden",
                        "message": "Request origin is not allowed",
                        "details": None,
                    }
                },
            )
            denial.headers["X-Request-ID"] = request_id
            return denial
    if request.method == "POST" and request.url.path == "/v1/documents":
        declared_size = request.headers.get("content-length")
        if declared_size is not None:
            try:
                too_large = int(declared_size) > MAX_UPLOAD_REQUEST_BYTES
            except ValueError:
                too_large = True
            if too_large:
                denial = JSONResponse(
                    status_code=413,
                    content={
                        "error": {
                            "code": "upload_too_large",
                            "message": "Upload request exceeds the 10 MB PDF limit",
                            "details": None,
                        }
                    },
                )
                denial.headers["X-Request-ID"] = request_id
                return denial
        # FastAPI parses multipart uploads before the endpoint executes. Cap
        # the raw stream first, including requests without Content-Length.
        chunks: list[bytes] = []
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_UPLOAD_REQUEST_BYTES:
                denial = JSONResponse(
                    status_code=413,
                    content={
                        "error": {
                            "code": "upload_too_large",
                            "message": "Upload request exceeds the 10 MB PDF limit",
                            "details": None,
                        }
                    },
                )
                denial.headers["X-Request-ID"] = request_id
                return denial
            chunks.append(chunk)
        request._body = b"".join(chunks)
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


def current_session(
    session: Annotated[Session, Depends(get_session)],
    opspilot_session: Annotated[str | None, Cookie()] = None,
) -> tuple[Session, User, Organization, Membership]:
    claims = read_session_token(opspilot_session or "")
    if claims is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    user_id, org_id = claims
    set_org_context(session, org_id)
    user = get_user_by_id(session, user_id)
    org = get_organization_by_id(session, org_id)
    membership = get_membership(session, org_id, user_id)
    if user is None or org is None or membership is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return session, user, org, membership


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
                "login_attempts AS l LIMIT 0"
            )
        )
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database schema is not ready") from exc
    return {"status": "ready"}


@app.post("/v1/auth/login", response_model=SessionResponse)
def login(
    body: LoginRequest, response: Response, session: Annotated[Session, Depends(get_session)]
) -> SessionResponse:
    if not reserve_attempt(session, body.org_slug, body.email):
        raise HTTPException(
            status_code=429, detail="Too many login attempts; try again in 15 minutes"
        )
    org = get_organization_by_slug(session, body.org_slug)
    user = get_user_by_email(session, body.email)
    # Keep the same public error for all credential failures.
    password_hash = user.password_hash if user is not None else DUMMY_PASSWORD_HASH
    password_valid = verify_password(password_hash, body.password)
    if org is None or user is None or not password_valid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    set_org_context(session, org.id)
    membership = get_membership(session, org.id, user.id)
    if membership is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    clear_attempts(session, body.org_slug, body.email)
    response.set_cookie(
        key="opspilot_session",
        value=make_session_token(user.id, org.id),
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=8 * 60 * 60,
        path="/",
    )
    return SessionResponse(
        user_id=user.id, email=user.email, org_id=org.id, org_name=org.name, role=membership.role
    )


@app.post("/v1/auth/logout", status_code=204)
def logout(response: Response) -> None:
    response.delete_cookie("opspilot_session", path="/")


@app.get("/v1/auth/me", response_model=SessionResponse)
def me(
    identity: Annotated[tuple[Session, User, Organization, Membership], Depends(current_session)],
) -> SessionResponse:
    _, user, org, membership = identity
    return SessionResponse(
        user_id=user.id, email=user.email, org_id=org.id, org_name=org.name, role=membership.role
    )


@app.get("/v1/organization/members", response_model=list[MemberResponse])
def organization_members(
    identity: Annotated[tuple[Session, User, Organization, Membership], Depends(current_session)],
) -> list[MemberResponse]:
    session, _, org, membership = identity
    if membership.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    return [
        MemberResponse(user_id=user.id, email=user.email, role=member.role)
        for member, user in list_members(session, org.id)
    ]


@app.post("/v1/documents", response_model=UploadResponse, status_code=202)
def upload_document(
    file: Annotated[UploadFile, File()],
    identity: Annotated[tuple[Session, User, Organization, Membership], Depends(current_session)],
    store: Annotated[ObjectStore, Depends(get_store)],
) -> UploadResponse:
    session, user, org, membership = identity
    if membership.role not in ("admin", "reviewer"):
        raise HTTPException(status_code=403, detail="Uploader role required")
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    try:
        return document_service.upload(session, store, org.id, user.id, file.filename or "", data)
    except InvalidDocument as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except MissingWorkflowConfig as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except DocumentLimitReached as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except StorageError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/v1/documents", response_model=list[DocumentSummary])
def documents(
    identity: Annotated[tuple[Session, User, Organization, Membership], Depends(current_session)],
) -> list[DocumentSummary]:
    session, _, org, _ = identity
    return document_service.browse(session, org.id)


@app.get("/v1/documents/{document_id}", response_model=DocumentDetail)
def document_detail(
    document_id: uuid.UUID,
    identity: Annotated[tuple[Session, User, Organization, Membership], Depends(current_session)],
) -> DocumentDetail:
    session, _, org, _ = identity
    result = document_service.read(session, org.id, document_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return result


@app.post("/v1/documents/{document_id}/retry", response_model=DocumentSummary, status_code=202)
def retry_document(
    document_id: uuid.UUID,
    identity: Annotated[tuple[Session, User, Organization, Membership], Depends(current_session)],
) -> DocumentSummary:
    session, user, org, membership = identity
    if membership.role not in ("admin", "reviewer"):
        raise HTTPException(status_code=403, detail="Uploader role required")
    try:
        result = document_service.retry(session, org.id, user.id, document_id)
    except DocumentNotRetryable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return result
