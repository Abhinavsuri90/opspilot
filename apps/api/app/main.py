import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Cookie, Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session, set_org_context
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

settings = get_settings()
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


@app.exception_handler(HTTPException)
async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
    code = {
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
    }.get(exc.status_code, "request_failed")
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": code, "message": str(exc.detail), "details": None}},
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


@app.middleware("http")
async def add_request_id(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.headers.get("X-Request-ID", str(uuid.uuid4()))
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
    session.execute(text("SELECT 1"))
    return {"status": "ready"}


@app.post("/v1/auth/login", response_model=SessionResponse)
def login(
    body: LoginRequest, response: Response, session: Annotated[Session, Depends(get_session)]
) -> SessionResponse:
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
