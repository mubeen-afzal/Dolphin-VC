import uuid
from datetime import datetime

from pydantic import EmailStr, Field, field_validator, model_validator

from app.schemas.common import APIModel, StrictRequest
from app.types import OrgPlan, UserRole


class SignupRequest(StrictRequest):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    full_name: str = Field(min_length=2, max_length=200)
    org_name: str | None = Field(default=None, min_length=2, max_length=200)
    invite_token: str | None = None

    @field_validator("password")
    @classmethod
    def password_not_email(cls, password: str, info: object) -> str:
        data = getattr(info, "data", {})
        email = str(data.get("email", ""))
        local_part = email.split("@", 1)[0].lower()
        if local_part and len(local_part) >= 4 and local_part in password.lower():
            raise ValueError("password must not contain the email local-part")
        return password


class LoginRequest(StrictRequest):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    mfa_code: str | None = Field(default=None, pattern=r"^\d{6}$")


class RefreshRequest(StrictRequest):
    refresh_token: str | None = None


class LogoutRequest(StrictRequest):
    refresh_token: str | None = None
    all_devices: bool = False


class TokenRequest(StrictRequest):
    token: str = Field(min_length=16, max_length=256)


class ForgotPasswordRequest(StrictRequest):
    email: EmailStr


class ResetPasswordRequest(TokenRequest):
    password: str = Field(min_length=12, max_length=128)


class MeUpdateRequest(StrictRequest):
    full_name: str | None = Field(default=None, min_length=2, max_length=200)
    password: str | None = Field(default=None, min_length=12, max_length=128)
    current_password: str | None = None

    @model_validator(mode="after")
    def current_password_required(self) -> "MeUpdateRequest":
        if self.password and not self.current_password:
            raise ValueError("current_password is required when changing password")
        return self


class UserOut(APIModel):
    id: uuid.UUID
    org_id: uuid.UUID
    email: EmailStr
    full_name: str
    role: UserRole
    is_active: bool
    email_verified_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class OrgOut(APIModel):
    id: uuid.UUID
    name: str
    slug: str
    plan: OrgPlan
    settings: dict[str, object]
    created_at: datetime
    updated_at: datetime


class TokenPair(APIModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class AuthResponse(TokenPair):
    user: UserOut
    org: OrgOut | None = None


class MeResponse(APIModel):
    user: UserOut
    org: OrgOut
    permissions: list[str]


class SessionOut(APIModel):
    family_id: uuid.UUID
    user_agent: str | None
    ip: str | None
    created_at: datetime
    expires_at: datetime
