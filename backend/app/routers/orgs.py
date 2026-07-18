import secrets
import uuid
from datetime import timedelta

from fastapi import APIRouter, Response
from sqlalchemy import select

from app.db.models import Org, OrgInvite, User
from app.deps import DBSession, OrgAdminPrincipal, ReadPrincipal
from app.errors import AppError, NotFoundError
from app.schemas.auth import OrgOut, UserOut
from app.schemas.org import InviteCreate, InviteOut, OrgUpdate
from app.services.auth import hash_token
from app.services.utils import utcnow
from app.types import UserRole

router = APIRouter(prefix="/orgs/current", tags=["organizations"])


@router.get("", response_model=OrgOut)
async def current_org(principal: ReadPrincipal, session: DBSession) -> OrgOut:
    org = await session.get(Org, principal.org_id)
    if org is None:
        raise NotFoundError("Organization")
    return OrgOut.model_validate(org)


@router.patch("", response_model=OrgOut)
async def update_org(body: OrgUpdate, principal: OrgAdminPrincipal, session: DBSession) -> OrgOut:
    org = await session.get(Org, principal.org_id)
    if org is None:
        raise NotFoundError("Organization")
    if body.name is not None:
        org.name = body.name
    if body.settings is not None:
        org.settings = body.settings
    await session.commit()
    await session.refresh(org)
    return OrgOut.model_validate(org)


@router.get("/users", response_model=list[UserOut])
async def list_users(principal: ReadPrincipal, session: DBSession) -> list[UserOut]:
    users = (await session.scalars(select(User).where(User.org_id == principal.org_id))).all()
    return [UserOut.model_validate(user) for user in users]


@router.post("/invites", response_model=InviteOut, status_code=201)
async def create_invite(
    body: InviteCreate,
    principal: OrgAdminPrincipal,
    session: DBSession,
) -> InviteOut:
    if body.role in {UserRole.OWNER, UserRole.SERVICE}:
        raise AppError("VALIDATION_ERROR", "Invitations cannot grant owner or service roles.")
    if await session.scalar(select(User.id).where(User.email == str(body.email).casefold())):
        raise AppError("CONFLICT", "A user with this email already exists.", status_code=409)
    raw = secrets.token_urlsafe(32)
    invite = OrgInvite(
        org_id=principal.org_id,
        email=str(body.email).casefold(),
        role=body.role,
        token_hash=hash_token(raw),
        created_by=principal.user_id,
        expires_at=utcnow() + timedelta(days=7),
    )
    session.add(invite)
    await session.commit()
    await session.refresh(invite)
    # The token is returned once so any email provider can be integrated externally.
    return InviteOut(
        id=invite.id,
        email=invite.email,
        role=invite.role,
        expires_at=invite.expires_at,
        invite_token=raw,
    )


@router.delete("/users/{user_id}", status_code=204)
async def deactivate_user(
    user_id: uuid.UUID,
    principal: OrgAdminPrincipal,
    session: DBSession,
) -> Response:
    if user_id == principal.user_id:
        raise AppError("UNPROCESSABLE", "Owners cannot deactivate themselves.", status_code=422)
    user = await session.scalar(
        select(User).where(User.id == user_id, User.org_id == principal.org_id)
    )
    if user is None:
        raise NotFoundError("User")
    user.is_active = False
    await session.commit()
    return Response(status_code=204)
