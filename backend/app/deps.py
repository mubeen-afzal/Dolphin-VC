import hashlib
import hmac
import uuid
from collections.abc import AsyncIterator, Callable
from typing import Annotated

from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import ApiKey, Org, User
from app.errors import ForbiddenError, UnauthenticatedError
from app.services.auth import Principal, decode_access_token
from app.types import Permission, UserRole

bearer = HTTPBearer(auto_error=False)


def get_settings_from_app(request: Request) -> Settings:
    return request.app.state.settings


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.database.session_factory() as session:
        yield session


async def get_current_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    session: Annotated[AsyncSession, Depends(get_db)],
    x_org_id: Annotated[str | None, Header()] = None,
) -> Principal:
    if credentials is None or credentials.scheme.casefold() != "bearer":
        raise UnauthenticatedError()
    token = credentials.credentials
    settings: Settings = request.app.state.settings

    if settings.service_token and hmac.compare_digest(token, settings.service_token):
        try:
            org_id = uuid.UUID(x_org_id or "")
        except ValueError as exc:
            raise UnauthenticatedError(
                "UNAUTHENTICATED", "Service token requests require a valid X-Org-Id header."
            ) from exc
        if await session.get(Org, org_id) is None:
            raise UnauthenticatedError()
        return Principal(
            org_id=org_id,
            user_id=None,
            role=UserRole.SERVICE,
            scopes=frozenset(
                {Permission.READ.value, Permission.SCREEN.value, Permission.ADMIN.value}
            ),
            kind="service",
        )

    if token.startswith("vcb_live_"):
        key_hash = hashlib.sha256(token.encode()).hexdigest()
        key = await session.scalar(
            select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.revoked_at.is_(None))
        )
        if key is None:
            raise UnauthenticatedError()
        return Principal(
            org_id=key.org_id,
            user_id=None,
            role=UserRole.SERVICE,
            scopes=frozenset(key.scopes),
            kind="api_key",
        )

    payload = decode_access_token(token, settings)
    try:
        user_id = uuid.UUID(str(payload["sub"]))
        org_id = uuid.UUID(str(payload["org"]))
    except (ValueError, KeyError) as exc:
        raise UnauthenticatedError() from exc
    user = await session.scalar(select(User).where(User.id == user_id, User.org_id == org_id))
    if user is None or not user.is_active:
        raise UnauthenticatedError("TOKEN_REVOKED", "Account is unavailable.")
    return Principal(
        org_id=user.org_id,
        user_id=user.id,
        role=user.role,
        scopes=frozenset(str(value) for value in payload.get("scopes", [])),
        token_jti=str(payload.get("jti")),
    )


def require(permission: Permission) -> Callable[..., Principal]:
    async def dependency(
        principal: Annotated[Principal, Depends(get_current_principal)],
    ) -> Principal:
        if not principal.has(permission):
            raise ForbiddenError()
        return principal

    return dependency


CurrentPrincipal = Annotated[Principal, Depends(get_current_principal)]
ReadPrincipal = Annotated[Principal, Depends(require(Permission.READ))]
ScreenPrincipal = Annotated[Principal, Depends(require(Permission.SCREEN))]
DecidePrincipal = Annotated[Principal, Depends(require(Permission.DECIDE))]
ThesisPrincipal = Annotated[Principal, Depends(require(Permission.THESIS_WRITE))]
AdminPrincipal = Annotated[Principal, Depends(require(Permission.ADMIN))]
OrgAdminPrincipal = Annotated[Principal, Depends(require(Permission.ORG_ADMIN))]
DBSession = Annotated[AsyncSession, Depends(get_db)]
