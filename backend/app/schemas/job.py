import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.schemas.common import APIModel
from app.types import JobStatus


class JobOut(APIModel):
    id: uuid.UUID
    org_id: uuid.UUID | None
    kind: str
    status: JobStatus
    target_type: str | None
    target_id: uuid.UUID | None
    progress: Decimal
    current_step: str | None
    result: dict[str, Any]
    error_code: str | None
    error_message: str | None
    attempts: int
    max_attempts: int
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AgentStepOut(APIModel):
    id: uuid.UUID
    job_id: uuid.UUID
    seq: int
    agent: str
    action: str
    status: str
    progress: Decimal
    message: str | None
    output_summary: dict[str, Any]
    evidence_ids: list[str]
    cost_usd: Decimal
    duration_ms: int | None
    error: str | None
    created_at: datetime
