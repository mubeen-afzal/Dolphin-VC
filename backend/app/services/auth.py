import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import AuditLog, EmailToken, Org, OrgInvite, RefreshToken, Thesis, User
from app.errors import AppError, ConflictError, UnauthenticatedError
from app.services.utils import aware, slugify, utcnow
from app.types import ROLE_PERMISSIONS, Permission, UserRole

PASSWORD_HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)
COMMON_PASSWORDS = {"password1234", "123456789012", "qwertyuiop12", "letmeinplease"}
DUMMY_HASH = PASSWORD_HASHER.hash("not-a-real-user-password")


@dataclass(frozen=True)
class Principal:
    org_id: uuid.UUID
    user_id: uuid.UUID | None
    role: UserRole
    scopes: frozenset[str]
    token_jti: str | None = None
    kind: str = "user"

    def has(self, permission: Permission) -> bool:
        return permission in ROLE_PERMISSIONS[self.role] or permission.value in self.scopes


@dataclass(frozen=True)
class IssuedTokens:
    access_token: str
    refresh_token: str
    expires_in: int


def validate_password(password: str, email: str) -> None:
    if len(password) < 12:
        raise AppError("VALIDATION_ERROR", "Password must contain at least 12 characters.")
    local_part = email.split("@", 1)[0].casefold()
    if len(local_part) >= 4 and local_part in password.casefold():
        raise AppError("VALIDATION_ERROR", "Password must not contain the email local-part.")
    if password.casefold() in COMMON_PASSWORDS:
        raise AppError("VALIDATION_ERROR", "Choose a less common password.")


def hash_password(password: str) -> str:
    return PASSWORD_HASHER.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return PASSWORD_HASHER.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def build_access_token(user: User, settings: Settings) -> tuple[str, str]:
    now = utcnow()
    expires = now + timedelta(minutes=settings.jwt_access_ttl_min)
    jti = str(uuid.uuid4())
    permissions = sorted(item.value for item in ROLE_PERMISSIONS[user.role])
    payload = {
        "sub": str(user.id),
        "org": str(user.org_id),
        "role": user.role.value,
        "scopes": permissions,
        "jti": jti,
        "typ": "access",
        "iat": now,
        "exp": expires,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm), jti


def decode_access_token(token: str, settings: Settings) -> dict[str, object]:
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm],
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
            leeway=30,
        )
    except jwt.ExpiredSignatureError as exc:
        raise UnauthenticatedError("TOKEN_EXPIRED", "The access token has expired.") from exc
    except jwt.PyJWTError as exc:
        raise UnauthenticatedError() from exc
    if payload.get("typ") != "access":
        raise UnauthenticatedError()
    return payload


async def issue_tokens(
    session: AsyncSession,
    user: User,
    settings: Settings,
    *,
    family_id: uuid.UUID | None = None,
    parent_id: uuid.UUID | None = None,
    user_agent: str | None = None,
    ip: str | None = None,
) -> IssuedTokens:
    access, _jti = build_access_token(user, settings)
    raw_refresh = secrets.token_urlsafe(32)
    refresh = RefreshToken(
        user_id=user.id,
        token_hash=hash_token(raw_refresh),
        family_id=family_id or uuid.uuid4(),
        parent_id=parent_id,
        user_agent=user_agent,
        ip=ip,
        expires_at=utcnow() + timedelta(days=settings.jwt_refresh_ttl_days),
    )
    session.add(refresh)
    await session.flush()
    return IssuedTokens(
        access_token=access,
        refresh_token=raw_refresh,
        expires_in=settings.jwt_access_ttl_min * 60,
    )


async def signup(
    session: AsyncSession,
    settings: Settings,
    *,
    email: str,
    password: str,
    full_name: str,
    org_name: str | None,
    invite_token: str | None,
    user_agent: str | None,
    ip: str | None,
) -> tuple[User, Org, IssuedTokens]:
    email = email.casefold()
    validate_password(password, email)
    if await session.scalar(select(User.id).where(User.email == email)):
        raise ConflictError("An account with this email already exists.")
    invite = None
    if invite_token:
        invite = await session.scalar(
            select(OrgInvite).where(
                OrgInvite.token_hash == hash_token(invite_token),
                OrgInvite.accepted_at.is_(None),
            )
        )
        if (
            invite is None
            or aware(invite.expires_at) <= utcnow()
            or invite.email.casefold() != email
        ):
            raise AppError("TOKEN_EXPIRED", "Invitation is invalid or expired.", status_code=401)
        org = await session.get(Org, invite.org_id)
        if org is None:
            raise AppError(
                "TOKEN_REVOKED", "Invitation organization is unavailable.", status_code=401
            )
        role = invite.role
    else:
        base_slug = slugify(org_name or f"{full_name}'s fund")
        slug = base_slug
        suffix = 1
        while await session.scalar(select(Org.id).where(Org.slug == slug)):
            suffix += 1
            slug = f"{base_slug[:70]}-{suffix}"
        org = Org(name=org_name or f"{full_name}'s fund", slug=slug)
        session.add(org)
        await session.flush()
        role = UserRole.OWNER
    user = User(
        org_id=org.id,
        email=email,
        password_hash=hash_password(password),
        full_name=full_name,
        role=role,
    )
    session.add(user)
    await session.flush()
    if invite is None:
        session.add(
            Thesis(
                org_id=org.id,
                name="Default early-stage thesis",
                is_default=True,
                sectors=[],
                stages=["pre_seed", "seed"],
                geos=["remote"],
                must_haves=[],
                deal_breakers=[],
            )
        )
    else:
        invite.accepted_at = utcnow()
    tokens = await issue_tokens(session, user, settings, user_agent=user_agent, ip=ip)
    return user, org, tokens


async def login(
    session: AsyncSession,
    settings: Settings,
    *,
    email: str,
    password: str,
    user_agent: str | None,
    ip: str | None,
) -> tuple[User, IssuedTokens]:
    user = await session.scalar(select(User).where(User.email == email.casefold()))
    if user is None:
        verify_password(DUMMY_HASH, password)
        raise UnauthenticatedError("UNAUTHENTICATED", "Invalid email or password.")
    now = utcnow()
    if user.locked_until and aware(user.locked_until) > now:
        raise AppError(
            "RATE_LIMITED", "Account is temporarily locked.", status_code=429, retry_after_s=300
        )
    if not user.password_hash or not verify_password(user.password_hash, password):
        user.failed_logins += 1
        if user.failed_logins >= 5:
            user.locked_until = now + timedelta(minutes=15)
        await session.flush()
        raise UnauthenticatedError("UNAUTHENTICATED", "Invalid email or password.")
    if not user.is_active:
        raise UnauthenticatedError("TOKEN_REVOKED", "This account is disabled.")
    user.failed_logins = 0
    user.locked_until = None
    user.last_login_at = now
    tokens = await issue_tokens(session, user, settings, user_agent=user_agent, ip=ip)
    return user, tokens


async def rotate_refresh_token(
    session: AsyncSession,
    settings: Settings,
    raw_token: str,
    *,
    user_agent: str | None,
    ip: str | None,
) -> tuple[User, IssuedTokens]:
    record = await session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw_token))
    )
    if record is None:
        raise UnauthenticatedError("TOKEN_REVOKED", "Refresh token is invalid.")
    if record.revoked_at is not None:
        await session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == record.family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=utcnow(), revoked_reason="reuse_detected")
        )
        session.add(
            AuditLog(
                org_id=None,
                actor_user_id=record.user_id,
                actor_kind="token",
                action="auth.refresh_reuse",
                target_type="refresh_family",
                target_id=record.family_id,
            )
        )
        await session.commit()
        raise UnauthenticatedError("TOKEN_REVOKED", "Refresh token reuse was detected.")
    if aware(record.expires_at) <= utcnow():
        record.revoked_at = utcnow()
        record.revoked_reason = "expired"
        raise UnauthenticatedError("TOKEN_EXPIRED", "Refresh token has expired.")
    record.revoked_at = utcnow()
    record.revoked_reason = "rotated"
    user = await session.get(User, record.user_id)
    if user is None or not user.is_active:
        raise UnauthenticatedError("TOKEN_REVOKED", "Account is unavailable.")
    tokens = await issue_tokens(
        session,
        user,
        settings,
        family_id=record.family_id,
        parent_id=record.id,
        user_agent=user_agent,
        ip=ip,
    )
    return user, tokens


async def revoke_refresh(
    session: AsyncSession, raw_token: str | None, *, user_id: uuid.UUID, all_devices: bool
) -> None:
    if all_devices:
        await session.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=utcnow(), revoked_reason="logout_all")
        )
        return
    if raw_token:
        record = await session.scalar(
            select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw_token))
        )
        if record and hmac.compare_digest(str(record.user_id), str(user_id)):
            record.revoked_at = utcnow()
            record.revoked_reason = "logout"


async def create_email_token(session: AsyncSession, user: User, purpose: str) -> str:
    raw = secrets.token_urlsafe(32)
    session.add(
        EmailToken(
            user_id=user.id,
            purpose=purpose,
            token_hash=hash_token(raw),
            expires_at=utcnow() + timedelta(hours=1 if purpose == "reset" else 24),
        )
    )
    await session.flush()
    return raw


async def consume_email_token(session: AsyncSession, raw: str, purpose: str) -> User:
    record = await session.scalar(
        select(EmailToken).where(
            EmailToken.token_hash == hash_token(raw),
            EmailToken.purpose == purpose,
            EmailToken.used_at.is_(None),
        )
    )
    if record is None or aware(record.expires_at) <= utcnow():
        raise AppError("TOKEN_EXPIRED", "The token is invalid or expired.", status_code=401)
    user = await session.get(User, record.user_id)
    if user is None:
        raise UnauthenticatedError()
    record.used_at = utcnow()
    return user
