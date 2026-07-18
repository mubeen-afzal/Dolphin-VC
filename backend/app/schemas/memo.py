import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import Field

from app.schemas.common import APIModel, StrictRequest
from app.types import ClaimCategory, ClaimStatus, DecisionKind


class ClaimOut(APIModel):
    id: uuid.UUID
    category: ClaimCategory
    predicate: str
    text: str
    value_num: Decimal | None
    value_unit: str | None
    value_text: str | None
    status: ClaimStatus
    trust_score: Decimal
    trust_inputs: dict[str, Any]
    contradiction_of: uuid.UUID | None
    verification_note: str | None
    created_at: datetime
    updated_at: datetime


class EvidenceOut(APIModel):
    id: uuid.UUID
    claim_id: uuid.UUID
    source_id: uuid.UUID
    locator: dict[str, Any]
    snippet: str
    supports: bool
    independence_group: str | None
    observed_at: datetime | None
    retrieved_at: datetime


class MemoOut(APIModel):
    id: uuid.UUID
    org_id: uuid.UUID
    opportunity_id: uuid.UUID
    version: int
    status: str
    sections: list[dict[str, Any]]
    recommendation: DecisionKind | None
    recommendation_rationale: str | None
    adversarial: dict[str, Any]
    gaps: list[dict[str, Any]]
    trust_summary: dict[str, int]
    word_count: int | None
    generated_ms: int | None
    cost_usd: Decimal | None
    model_version: str | None
    created_at: datetime
    updated_at: datetime


class MemoPatch(StrictRequest):
    sections: list[dict[str, Any]] = Field(min_length=1)


class MemoExportRequest(StrictRequest):
    format: str = Field(pattern=r"^(pdf|md|docx)$")
