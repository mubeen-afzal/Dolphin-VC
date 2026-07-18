import uuid
from typing import Any

from pydantic import Field

from app.schemas.common import APIModel, StrictRequest
from app.schemas.opportunity import OpportunityCard


class OpportunitySearchRequest(StrictRequest):
    q: str = Field(min_length=2, max_length=1000)
    mode: str = Field(default="hybrid", pattern=r"^(hybrid|keyword|semantic)$")
    limit: int = Field(default=25, ge=1, le=100)
    explain: bool = True


class SearchInterpretation(APIModel):
    filters: dict[str, Any]
    residual_semantic: str
    unresolved: list[str]
    confidence: float


class OpportunityMatch(APIModel):
    score: float
    matched: list[dict[str, Any]]
    unmatched: list[str]


class OpportunitySearchItem(APIModel):
    opportunity: OpportunityCard
    match: OpportunityMatch


class OpportunitySearchResponse(APIModel):
    interpreted: SearchInterpretation
    items: list[OpportunitySearchItem]
    took_ms: int
    used_llm: bool
    degraded: bool


class KBSearchRequest(StrictRequest):
    q: str = Field(min_length=2, max_length=1000)
    company_id: uuid.UUID | None = None
    person_id: uuid.UUID | None = None
    k: int = Field(default=8, ge=1, le=50)
    include_web: bool = False
