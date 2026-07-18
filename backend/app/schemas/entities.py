import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.schemas.common import APIModel
from app.types import SignalKind, SourceStatus, SourceTier


class CompanyOut(APIModel):
    id: uuid.UUID
    name: str
    normalized_name: str
    legal_name: str | None
    domain: str | None
    one_liner: str | None
    description: str | None
    sectors: list[str]
    stage: str | None
    hq_country: str | None
    hq_city: str | None
    founded_on: date | None
    founded_precision: str | None
    employee_estimate: int | None
    status: str
    links: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class SignalOut(APIModel):
    id: uuid.UUID
    org_id: uuid.UUID | None
    source_id: uuid.UUID
    kind: SignalKind
    external_id: str | None
    url: str | None
    title: str | None
    body: str | None
    payload: dict[str, Any]
    person_id: uuid.UUID | None
    company_id: uuid.UUID | None
    strength: Decimal | None
    observed_at: datetime
    ingested_at: datetime


class SourceOut(APIModel):
    id: uuid.UUID
    key: str
    display_name: str
    tier: SourceTier
    base_url: str | None
    status: SourceStatus
    reliability: Decimal
    rate_limit: dict[str, Any]
    requires_key: bool
    tos_note: str | None
    last_ok_at: datetime | None
    last_error_at: datetime | None
    last_error: str | None
