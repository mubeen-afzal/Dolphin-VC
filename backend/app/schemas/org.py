import uuid
from datetime import datetime

from pydantic import EmailStr, Field

from app.schemas.common import APIModel, StrictRequest
from app.types import UserRole


class OrgUpdate(StrictRequest):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    settings: dict[str, object] | None = None


class InviteCreate(StrictRequest):
    email: EmailStr
    role: UserRole = UserRole.ANALYST


class InviteOut(APIModel):
    id: uuid.UUID
    email: EmailStr
    role: UserRole
    expires_at: datetime
    invite_token: str | None = None
