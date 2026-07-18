import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class StrictRequest(BaseModel):
    # JSON enum strings and numeric literals remain accepted; unknown fields and lossy extras do not.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class FieldError(APIModel):
    field: str
    code: str
    message: str


class ErrorBody(APIModel):
    code: str
    message: str
    field_errors: list[FieldError] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)
    retryable: bool = False
    retry_after_s: int | None = None
    request_id: str
    docs: str | None = None


class ErrorResponse(APIModel):
    error: ErrorBody


class CursorPage[T](APIModel):
    items: list[T]
    next_cursor: str | None = None
    total_estimate: int | None = None


class JobAccepted(APIModel):
    job_id: uuid.UUID


class Versioned(APIModel):
    version: int
    updated_at: datetime


class HealthResponse(APIModel):
    status: str
