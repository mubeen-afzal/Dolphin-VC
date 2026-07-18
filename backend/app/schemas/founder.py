import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.schemas.common import APIModel, StrictRequest
from app.types import TrendKind


class FounderScoreOut(APIModel):
    score: int
    ci: list[int]
    confidence: Decimal
    components: dict[str, Any]
    cold_start: bool
    percentile: Decimal | None
    trend_30d: int
    trend: TrendKind
    version: int
    computed_at: datetime


class FounderCard(APIModel):
    id: uuid.UUID
    display_name: str
    headline: str | None
    country_code: str | None
    city: str | None
    skills: list[str]
    score: FounderScoreOut | None


class FounderProfile(FounderCard):
    bio: str | None
    location_text: str | None
    links: dict[str, Any]
    education: list[dict[str, Any]]
    employment: list[dict[str, Any]]
    signal_count: int
    source_count: int
    is_stub: bool
    first_seen_at: datetime
    last_signal_at: datetime | None


class FounderHistoryPoint(APIModel):
    day: date
    score: int
    confidence: Decimal


class FounderMergeRequest(StrictRequest):
    loser_id: uuid.UUID


class UpliftAction(APIModel):
    action: str
    expected_delta: int
    why: str


class UpliftPlan(APIModel):
    actions: list[UpliftAction]
