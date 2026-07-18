import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import Field, model_validator

from app.schemas.common import APIModel, StrictRequest
from app.types import (
    AxisKind,
    DecisionKind,
    MarketStance,
    OpportunityOrigin,
    OpportunityStage,
    TrendKind,
)


class CompanySummary(APIModel):
    id: uuid.UUID
    name: str
    domain: str | None = None
    logo_url: str | None = None
    one_liner: str | None = None
    sectors: list[str] = Field(default_factory=list)
    hq_country: str | None = None
    hq_city: str | None = None


class FounderSummary(APIModel):
    person_id: uuid.UUID
    name: str
    founder_score: int | None = None
    founder_score_ci: list[int] | None = None
    cold_start: bool = True


class AxisScoreOut(APIModel):
    axis: AxisKind | None = None
    score: Decimal
    confidence: Decimal
    trend: TrendKind
    stance: MarketStance | None = None
    rationale: str | None = None
    drivers: list[dict[str, Any]] = Field(default_factory=list)
    version: int | None = None
    model_version: str | None = None
    computed_at: datetime | None = None


class SLAOut(APIModel):
    deadline_at: datetime
    hours_remaining: float
    at_risk: bool
    breached: bool = False


class OpportunityCard(APIModel):
    id: uuid.UUID
    company: CompanySummary
    origin: OpportunityOrigin
    stage: OpportunityStage
    founders: list[FounderSummary] = Field(default_factory=list)
    axes: dict[str, AxisScoreOut | None]
    thesis_fit: Decimal | None = None
    trust_summary: dict[str, int] = Field(default_factory=dict)
    decision: DecisionKind | None = None
    sla: SLAOut
    first_signal_at: datetime
    updated_at: datetime


class OpportunityList(APIModel):
    items: list[OpportunityCard]
    next_cursor: str | None = None
    total_estimate: int
    facets: dict[str, dict[str, int]]


class OpportunityCreate(StrictRequest):
    company_id: uuid.UUID | None = None
    company_name: str | None = Field(default=None, min_length=1, max_length=200)
    origin: OpportunityOrigin = OpportunityOrigin.MANUAL
    thesis_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def exactly_one_company(self) -> "OpportunityCreate":
        if bool(self.company_id) == bool(self.company_name):
            raise ValueError("provide exactly one of company_id or company_name")
        return self


class OpportunityUpdate(StrictRequest):
    assigned_to: uuid.UUID | None = None
    stage: OpportunityStage | None = None
    title: str | None = Field(default=None, max_length=250)


class ScreenRequest(StrictRequest):
    force: bool = False


class DiligenceRequest(StrictRequest):
    focus: list[str] = Field(default_factory=list, max_length=10)


class MemoRequest(StrictRequest):
    regenerate: bool = False


class DecisionRequest(StrictRequest):
    decision: DecisionKind
    rationale: str = Field(min_length=10, max_length=5000)
    override_of: str | None = None

    @model_validator(mode="after")
    def only_human_decisions(self) -> "DecisionRequest":
        if self.decision == DecisionKind.NEEDS_HUMAN:
            raise ValueError("needs_human is a system recommendation, not a final human decision")
        return self


class OpportunityDetail(OpportunityCard):
    title: str | None = None
    thesis_id: uuid.UUID | None = None
    conviction: Decimal | None = None
    priority_rank: Decimal | None = None
    sourced_at: datetime
    screened_at: datetime | None = None
    diligence_started_at: datetime | None = None
    memo_ready_at: datetime | None = None
    decided_at: datetime | None = None
    decision_rationale: str | None = None
    assigned_to: uuid.UUID | None = None
    version: int
    claims: list[dict[str, Any]] = Field(default_factory=list)
    memo: dict[str, Any] | None = None


class ScoreHistory(APIModel):
    current: list[AxisScoreOut]
    history: list[AxisScoreOut]
