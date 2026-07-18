import secrets
import uuid
from typing import Annotated

from fastapi import APIRouter, Cookie, Header, Request, Response, status
from sqlalchemy import select, update

from app.config import Settings
from app.db.models import Org, RefreshToken, User
from app.deps import CurrentPrincipal, DBSession
from app.errors import AppError, UnauthenticatedError
from app.schemas.auth import (
    AuthResponse,
    ForgotPasswordRequest,
    LoginRequest,
    LogoutRequest,
    MeResponse,
    MeUpdateRequest,
    RefreshRequest,
    ResetPasswordRequest,
    SessionOut,
    SignupRequest,
    TokenPair,
    TokenRequest,
    UserOut,
)
from app.services.auth import (
    consume_email_token,
    create_email_token,
    hash_password,
    login,
    revoke_refresh,
    rotate_refresh_token,
    signup,
    validate_password,
    verify_password,
)
from app.services.utils import utcnow
from app.types import ROLE_PERMISSIONS

router = APIRouter(prefix="/auth", tags=["auth"])


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def set_token_cookies(response: Response, settings: Settings, refresh_token: str) -> None:
    secure = settings.env == "prod"
    csrf = secrets.token_urlsafe(24)
    max_age = settings.jwt_refresh_ttl_days * 86400
    response.set_cookie(
        "vcbrain_refresh",
        refresh_token,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/api/v1/auth",
        max_age=max_age,
    )
    response.set_cookie(
        "vcbrain_csrf",
        csrf,
        httponly=False,
        secure=secure,
        samesite="lax",
        path="/api/v1/auth",
        max_age=max_age,
    )


@router.post("/signup", response_model=AuthResponse, status_code=201)
async def signup_endpoint(
    body: SignupRequest,
    request: Request,
    response: Response,
    session: DBSession,
) -> AuthResponse:
    settings: Settings = request.app.state.settings
    user, org, tokens = await signup(
        session,
        settings,
        email=str(body.email),
        password=body.password,
        full_name=body.full_name,
        org_name=body.org_name,
        invite_token=body.invite_token,
        user_agent=request.headers.get("user-agent"),
        ip=client_ip(request),
    )
    await session.commit()
    await session.refresh(user)
    await session.refresh(org)
    set_token_cookies(response, settings, tokens.refresh_token)
    return AuthResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_in=tokens.expires_in,
        user=UserOut.model_validate(user),
        org=org,
    )


@router.post("/login", response_model=AuthResponse)
async def login_endpoint(
    body: LoginRequest,
    request: Request,
    response: Response,
    session: DBSession,
) -> AuthResponse:
    settings: Settings = request.app.state.settings
    user, tokens = await login(
        session,
        settings,
        email=str(body.email),
        password=body.password,
        user_agent=request.headers.get("user-agent"),
        ip=client_ip(request),
    )
    org = await session.get(Org, user.org_id)
    await session.commit()
    await session.refresh(user)

    if org is not None:
        await session.refresh(org)

    set_token_cookies(response, settings, tokens.refresh_token)
    return AuthResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_in=tokens.expires_in,
        user=user,
        org=org,
    )


@router.post("/refresh", response_model=TokenPair)
async def refresh_endpoint(
    body: RefreshRequest,
    request: Request,
    response: Response,
    session: DBSession,
    cookie_token: Annotated[str | None, Cookie(alias="vcbrain_refresh")] = None,
    csrf_cookie: Annotated[str | None, Cookie(alias="vcbrain_csrf")] = None,
    csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> TokenPair:
    raw = body.refresh_token or cookie_token
    if not raw:
        raise UnauthenticatedError("TOKEN_REVOKED", "Refresh token is required.")
    if body.refresh_token is None and (
        not csrf_cookie or not csrf_header or csrf_cookie != csrf_header
    ):
        raise AppError("FORBIDDEN", "CSRF token is missing or invalid.", status_code=403)
    settings: Settings = request.app.state.settings
    _user, tokens = await rotate_refresh_token(
        session,
        settings,
        raw,
        user_agent=request.headers.get("user-agent"),
        ip=client_ip(request),
    )
    await session.commit()
    set_token_cookies(response, settings, tokens.refresh_token)
    return TokenPair(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_in=tokens.expires_in,
    )


@router.post("/logout", status_code=204)
async def logout_endpoint(
    body: LogoutRequest,
    response: Response,
    principal: CurrentPrincipal,
    session: DBSession,
) -> Response:
    if principal.user_id is None:
        raise UnauthenticatedError()
    await revoke_refresh(
        session,
        body.refresh_token,
        user_id=principal.user_id,
        all_devices=body.all_devices,
    )
    await session.commit()
    response.delete_cookie("vcbrain_refresh", path="/api/v1/auth")
    response.delete_cookie("vcbrain_csrf", path="/api/v1/auth")
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=MeResponse)
async def me_endpoint(principal: CurrentPrincipal, session: DBSession) -> MeResponse:
    if principal.user_id is None:
        raise UnauthenticatedError()
    user = await session.get(User, principal.user_id)
    org = await session.get(Org, principal.org_id)
    if user is None or org is None:
        raise UnauthenticatedError()
    permissions = sorted(item.value for item in ROLE_PERMISSIONS[user.role])
    return MeResponse(user=user, org=org, permissions=permissions)


@router.patch("/me", response_model=UserOut)
async def update_me_endpoint(
    body: MeUpdateRequest,
    principal: CurrentPrincipal,
    session: DBSession,
) -> UserOut:
    if principal.user_id is None:
        raise UnauthenticatedError()
    user = await session.get(User, principal.user_id)
    if user is None:
        raise UnauthenticatedError()
    if body.full_name:
        user.full_name = body.full_name
    if body.password:
        if not user.password_hash or not verify_password(
            user.password_hash, body.current_password or ""
        ):
            raise UnauthenticatedError("UNAUTHENTICATED", "Current password is incorrect.")
        validate_password(body.password, user.email)
        user.password_hash = hash_password(body.password)
        await session.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=utcnow(), revoked_reason="password_changed")
        )
    await session.commit()
    await session.refresh(user)
    return UserOut.model_validate(user)


@router.post("/verify-email", status_code=204)
async def verify_email_endpoint(body: TokenRequest, session: DBSession) -> Response:
    user = await consume_email_token(session, body.token, "verify")
    user.email_verified_at = utcnow()
    await session.commit()
    return Response(status_code=204)


@router.post("/password/forgot", status_code=202)
async def forgot_password_endpoint(body: ForgotPasswordRequest, session: DBSession) -> Response:
    user = await session.scalar(select(User).where(User.email == str(body.email).casefold()))
    if user:
        await create_email_token(session, user, "reset")
        await session.commit()
    return Response(status_code=202)


@router.post("/password/reset", status_code=204)
async def reset_password_endpoint(body: ResetPasswordRequest, session: DBSession) -> Response:
    user = await consume_email_token(session, body.token, "reset")
    validate_password(body.password, user.email)
    user.password_hash = hash_password(body.password)
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow(), revoked_reason="password_reset")
    )
    await session.commit()
    return Response(status_code=204)


@router.get("/sessions", response_model=list[SessionOut])
async def sessions_endpoint(principal: CurrentPrincipal, session: DBSession) -> list[SessionOut]:
    if principal.user_id is None:
        raise UnauthenticatedError()
    rows = (
        await session.scalars(
            select(RefreshToken)
            .where(RefreshToken.user_id == principal.user_id, RefreshToken.revoked_at.is_(None))
            .order_by(RefreshToken.created_at.desc())
        )
    ).all()
    seen: set[uuid.UUID] = set()
    output = []
    for row in rows:
        if row.family_id in seen:
            continue
        seen.add(row.family_id)
        output.append(
            SessionOut(
                family_id=row.family_id,
                user_agent=row.user_agent,
                ip=row.ip,
                created_at=row.created_at,
                expires_at=row.expires_at,
            )
        )
    return output


@router.delete("/sessions/{family_id}", status_code=204)
async def delete_session_endpoint(
    family_id: uuid.UUID,
    principal: CurrentPrincipal,
    session: DBSession,
) -> Response:
    if principal.user_id is None:
        raise UnauthenticatedError()
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == principal.user_id, RefreshToken.family_id == family_id)
        .values(revoked_at=utcnow(), revoked_reason="session_revoked")
    )
    await session.commit()
    return Response(status_code=204)
