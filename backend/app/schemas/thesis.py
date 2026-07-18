import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import Field, model_validator

from app.schemas.common import APIModel, StrictRequest


class ThesisCreate(StrictRequest):
    name: str = Field(min_length=2, max_length=160)
    is_default: bool = False
    sectors: list[str] = Field(default_factory=list)
    anti_sectors: list[str] = Field(default_factory=list)
    stages: list[str] = Field(default_factory=list)
    geos: list[str] = Field(default_factory=list)
    check_size_min: Decimal | None = Field(default=None, ge=0)
    check_size_max: Decimal | None = Field(default=None, ge=0)
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    ownership_target_pct: Decimal | None = Field(default=None, ge=0, le=100)
    risk_appetite: Decimal = Field(default=Decimal("0.5"), ge=0, le=1)
    weights: dict[str, float] = Field(
        default_factory=lambda: {"founder": 0.45, "market": 0.30, "idea_vs_market": 0.25}
    )
    must_haves: list[str] = Field(default_factory=list)
    deal_breakers: list[str] = Field(default_factory=list)
    notes: str | None = None

    @model_validator(mode="after")
    def validate_ranges(self) -> "ThesisCreate":
        if self.check_size_min is not None and self.check_size_max is not None:
            if self.check_size_min > self.check_size_max:
                raise ValueError("check_size_min cannot exceed check_size_max")
        if set(self.sectors) & set(self.anti_sectors):
            raise ValueError("a sector cannot be both included and excluded")
        if set(self.weights) != {"founder", "market", "idea_vs_market"}:
            raise ValueError("weights must contain founder, market, and idea_vs_market")
        return self


class ThesisUpdate(StrictRequest):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    sectors: list[str] | None = None
    anti_sectors: list[str] | None = None
    stages: list[str] | None = None
    geos: list[str] | None = None
    check_size_min: Decimal | None = Field(default=None, ge=0)
    check_size_max: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    ownership_target_pct: Decimal | None = Field(default=None, ge=0, le=100)
    risk_appetite: Decimal | None = Field(default=None, ge=0, le=1)
    weights: dict[str, float] | None = None
    must_haves: list[str] | None = None
    deal_breakers: list[str] | None = None
    notes: str | None = None


class ThesisOut(APIModel):
    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    is_default: bool
    sectors: list[str]
    anti_sectors: list[str]
    stages: list[str]
    geos: list[str]
    check_size_min: Decimal | None
    check_size_max: Decimal | None
    currency: str
    ownership_target_pct: Decimal | None
    risk_appetite: Decimal
    weights: dict[str, float]
    must_haves: list[str]
    deal_breakers: list[str]
    notes: str | None
    version: int
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ThesisPreview(APIModel):
    matched_count: int
    sample: list[dict[str, object]]
    excluded_by_gate: dict[str, int]
