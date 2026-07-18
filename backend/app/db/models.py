import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.types import (
    ApplicationStatus,
    AxisKind,
    ClaimCategory,
    ClaimStatus,
    DecisionKind,
    JobStatus,
    MarketStance,
    OpportunityOrigin,
    OpportunityStage,
    OrgPlan,
    OutreachStatus,
    SignalKind,
    SourceStatus,
    SourceTier,
    TrendKind,
    UserRole,
)


def new_uuid() -> uuid.UUID:
    return uuid.uuid4()


def enum_type(enum_class: type[Any]) -> Enum:
    return Enum(
        enum_class,
        native_enum=False,
        values_callable=lambda values: [item.value for item in values],
    )


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class UpdatedAtMixin(CreatedAtMixin):
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Org(UpdatedAtMixin, Base):
    __tablename__ = "orgs"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    plan: Mapped[OrgPlan] = mapped_column(enum_type(OrgPlan), default=OrgPlan.STANDARD)
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class User(UpdatedAtMixin, Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    password_hash: Mapped[str | None] = mapped_column(Text)
    full_name: Mapped[str] = mapped_column(String(200))
    role: Mapped[UserRole] = mapped_column(enum_type(UserRole), default=UserRole.ANALYST)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mfa_secret: Mapped[str | None] = mapped_column(Text)


class RefreshToken(CreatedAtMixin, Base):
    __tablename__ = "refresh_tokens"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    family_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("refresh_tokens.id"))
    user_agent: Mapped[str | None] = mapped_column(Text)
    ip: Mapped[str | None] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_reason: Mapped[str | None] = mapped_column(String(100))


class ApiKey(CreatedAtMixin, Base):
    __tablename__ = "api_keys"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    key_prefix: Mapped[str] = mapped_column(String(32))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(CreatedAtMixin, Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    org_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    actor_kind: Mapped[str] = mapped_column(String(30), default="user")
    action: Mapped[str] = mapped_column(String(100), index=True)
    target_type: Mapped[str | None] = mapped_column(String(50))
    target_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    ip: Mapped[str | None] = mapped_column(String(64))
    request_id: Mapped[str | None] = mapped_column(String(64))


class Source(UpdatedAtMixin, Base):
    __tablename__ = "sources"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    tier: Mapped[SourceTier] = mapped_column(enum_type(SourceTier))
    base_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[SourceStatus] = mapped_column(
        enum_type(SourceStatus), default=SourceStatus.ACTIVE
    )
    reliability: Mapped[Decimal] = mapped_column(Numeric(4, 3), default=Decimal("0.700"))
    rate_limit: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    requires_key: Mapped[bool] = mapped_column(Boolean, default=False)
    tos_note: Mapped[str | None] = mapped_column(Text)
    last_ok_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


class Person(UpdatedAtMixin, Base):
    __tablename__ = "persons"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    display_name: Mapped[str] = mapped_column(String(200), index=True)
    normalized_name: Mapped[str] = mapped_column(String(200), index=True)
    headline: Mapped[str | None] = mapped_column(Text)
    bio: Mapped[str | None] = mapped_column(Text)
    location_text: Mapped[str | None] = mapped_column(String(200))
    country_code: Mapped[str | None] = mapped_column(String(2))
    city: Mapped[str | None] = mapped_column(String(100))
    emails: Mapped[list[str]] = mapped_column(JSON, default=list)
    links: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    education: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    employment: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    skills: Mapped[list[str]] = mapped_column(JSON, default=list)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_signal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    signal_count: Mapped[int] = mapped_column(Integer, default=0)
    source_count: Mapped[int] = mapped_column(Integer, default=0)
    is_stub: Mapped[bool] = mapped_column(Boolean, default=False)
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("persons.id"))


class Company(UpdatedAtMixin, Base):
    __tablename__ = "companies"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(200), index=True)
    normalized_name: Mapped[str] = mapped_column(String(200), index=True)
    legal_name: Mapped[str | None] = mapped_column(String(250))
    domain: Mapped[str | None] = mapped_column(String(255), index=True)
    one_liner: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    sectors: Mapped[list[str]] = mapped_column(JSON, default=list)
    stage: Mapped[str | None] = mapped_column(String(50))
    hq_country: Mapped[str | None] = mapped_column(String(2))
    hq_city: Mapped[str | None] = mapped_column(String(100))
    founded_on: Mapped[date | None] = mapped_column(Date)
    founded_precision: Mapped[str | None] = mapped_column(String(20))
    employee_estimate: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default="active")
    links: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_signal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_stub: Mapped[bool] = mapped_column(Boolean, default=False)
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("companies.id"))


Index(
    "uq_companies_live_domain",
    Company.domain,
    unique=True,
    sqlite_where=Company.merged_into_id.is_(None),
)


class Affiliation(CreatedAtMixin, Base):
    __tablename__ = "affiliations"
    __table_args__ = (UniqueConstraint("person_id", "company_id", "role"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    person_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("persons.id", ondelete="CASCADE"), index=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(80))
    is_founder: Mapped[bool] = mapped_column(Boolean, default=False)
    started_on: Mapped[date | None] = mapped_column(Date)
    ended_on: Mapped[date | None] = mapped_column(Date)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), default=Decimal("0.700"))


class Signal(CreatedAtMixin, Base):
    __tablename__ = "signals"
    __table_args__ = (UniqueConstraint("source_id", "content_hash", "observed_at"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    org_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("orgs.id"), index=True)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id"), index=True)
    kind: Mapped[SignalKind] = mapped_column(enum_type(SignalKind))
    external_id: Mapped[str | None] = mapped_column(String(255))
    url: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    body: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    raw_ref: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    person_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("persons.id"), index=True)
    company_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("companies.id"), index=True)
    strength: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Thesis(UpdatedAtMixin, Base):
    __tablename__ = "theses"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    sectors: Mapped[list[str]] = mapped_column(JSON, default=list)
    anti_sectors: Mapped[list[str]] = mapped_column(JSON, default=list)
    stages: Mapped[list[str]] = mapped_column(JSON, default=list)
    geos: Mapped[list[str]] = mapped_column(JSON, default=list)
    check_size_min: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    check_size_max: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    ownership_target_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    risk_appetite: Mapped[Decimal] = mapped_column(Numeric(3, 2), default=Decimal("0.50"))
    weights: Mapped[dict[str, float]] = mapped_column(
        JSON, default=lambda: {"founder": 0.45, "market": 0.30, "idea_vs_market": 0.25}
    )
    must_haves: Mapped[list[str]] = mapped_column(JSON, default=list)
    deal_breakers: Mapped[list[str]] = mapped_column(JSON, default=list)
    notes: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FounderScore(UpdatedAtMixin, Base):
    __tablename__ = "founder_scores"
    person_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("persons.id", ondelete="CASCADE"), primary_key=True
    )
    score: Mapped[int] = mapped_column(Integer)
    ci_low: Mapped[int] = mapped_column(Integer)
    ci_high: Mapped[int] = mapped_column(Integer)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    components: Mapped[dict[str, Any]] = mapped_column(JSON)
    cold_start: Mapped[bool] = mapped_column(Boolean, default=True)
    percentile: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    trend_30d: Mapped[int] = mapped_column(Integer, default=0)
    trend: Mapped[TrendKind] = mapped_column(
        enum_type(TrendKind), default=TrendKind.INSUFFICIENT_DATA
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class FounderScoreEvent(CreatedAtMixin, Base):
    __tablename__ = "founder_score_events"
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    person_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("persons.id", ondelete="CASCADE"), index=True
    )
    component: Mapped[str] = mapped_column(String(50))
    delta: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    reason: Mapped[str] = mapped_column(Text)
    signal_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("signals.id"))
    evidence_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    weight: Mapped[Decimal] = mapped_column(Numeric(4, 3), default=Decimal("1.0"))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    supersedes_id: Mapped[int | None] = mapped_column(ForeignKey("founder_score_events.id"))


class FounderScoreSnapshot(Base):
    __tablename__ = "founder_score_snapshots"
    person_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("persons.id", ondelete="CASCADE"), primary_key=True
    )
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    score: Mapped[int] = mapped_column(Integer)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3))


class Document(CreatedAtMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("org_id", "sha256"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("orgs.id", ondelete="CASCADE"), index=True
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("companies.id"))
    kind: Mapped[str] = mapped_column(String(40))
    filename: Mapped[str | None] = mapped_column(String(255))
    mime: Mapped[str | None] = mapped_column(String(120))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    s3_key: Mapped[str] = mapped_column(Text)
    page_count: Mapped[int | None] = mapped_column(Integer)
    parse_status: Mapped[str] = mapped_column(String(30), default="pending")
    parse_error: Mapped[str | None] = mapped_column(Text)
    parser: Mapped[str | None] = mapped_column(String(80))
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class DocumentPage(Base):
    __tablename__ = "document_pages"
    __table_args__ = (UniqueConstraint("document_id", "page_no"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    page_no: Mapped[int] = mapped_column(Integer)
    text: Mapped[str | None] = mapped_column(Text)
    ocr_used: Mapped[bool] = mapped_column(Boolean, default=False)
    image_s3_key: Mapped[str | None] = mapped_column(Text)
    layout: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class Application(UpdatedAtMixin, Base):
    __tablename__ = "applications"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    company_name: Mapped[str] = mapped_column(String(200))
    deck_document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id"))
    contact_email: Mapped[str | None] = mapped_column(String(320))
    contact_name: Mapped[str | None] = mapped_column(String(200))
    website: Mapped[str | None] = mapped_column(Text)
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[ApplicationStatus] = mapped_column(
        enum_type(ApplicationStatus), default=ApplicationStatus.RECEIVED
    )
    submitted_ip: Mapped[str | None] = mapped_column(String(64))
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("opportunities.id", use_alter=True)
    )
    source_channel: Mapped[str | None] = mapped_column(String(50))
    outreach_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tracking_token_hash: Mapped[str | None] = mapped_column(String(64), unique=True)


class Opportunity(UpdatedAtMixin, Base):
    __tablename__ = "opportunities"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    thesis_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("theses.id"))
    origin: Mapped[OpportunityOrigin] = mapped_column(enum_type(OpportunityOrigin))
    stage: Mapped[OpportunityStage] = mapped_column(
        enum_type(OpportunityStage), default=OpportunityStage.SOURCED
    )
    title: Mapped[str | None] = mapped_column(String(250))
    thesis_fit: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    conviction: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    priority_rank: Mapped[Decimal | None] = mapped_column(Numeric(8, 3))
    first_signal_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sourced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    screened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    diligence_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    memo_ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sla_deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    decision: Mapped[DecisionKind | None] = mapped_column(enum_type(DecisionKind))
    decision_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    decision_rationale: Mapped[str | None] = mapped_column(Text)
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    dedupe_key: Mapped[str | None] = mapped_column(String(200), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class OpportunityScore(CreatedAtMixin, Base):
    __tablename__ = "opportunity_scores"
    __table_args__ = (UniqueConstraint("opportunity_id", "axis", "version"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"), index=True
    )
    axis: Mapped[AxisKind] = mapped_column(enum_type(AxisKind))
    score: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    trend: Mapped[TrendKind] = mapped_column(
        enum_type(TrendKind), default=TrendKind.INSUFFICIENT_DATA
    )
    stance: Mapped[MarketStance | None] = mapped_column(enum_type(MarketStance))
    rationale: Mapped[str] = mapped_column(Text)
    drivers: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    model_version: Mapped[str] = mapped_column(String(80))
    version: Mapped[int] = mapped_column(Integer, default=1)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PrescreenResult(CreatedAtMixin, Base):
    __tablename__ = "prescreen_results"
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"), primary_key=True
    )
    passed: Mapped[bool] = mapped_column(Boolean)
    rules_fired: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    latency_ms: Mapped[int] = mapped_column(Integer)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=Decimal("0"))


class Claim(UpdatedAtMixin, Base):
    __tablename__ = "claims"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"), index=True
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("companies.id"))
    person_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("persons.id"))
    category: Mapped[ClaimCategory] = mapped_column(enum_type(ClaimCategory))
    predicate: Mapped[str] = mapped_column(String(100))
    text: Mapped[str] = mapped_column(Text)
    value_num: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    value_unit: Mapped[str | None] = mapped_column(String(40))
    value_text: Mapped[str | None] = mapped_column(Text)
    as_of: Mapped[date | None] = mapped_column(Date)
    status: Mapped[ClaimStatus] = mapped_column(enum_type(ClaimStatus), default=ClaimStatus.CLAIMED)
    trust_score: Mapped[Decimal] = mapped_column(Numeric(4, 3), default=Decimal("0.300"))
    trust_inputs: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    contradiction_of: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("claims.id"))
    verification_note: Mapped[str | None] = mapped_column(Text)
    extracted_by: Mapped[str | None] = mapped_column(String(120))


class Evidence(CreatedAtMixin, Base):
    __tablename__ = "evidence"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    claim_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("claims.id", ondelete="CASCADE"), index=True
    )
    signal_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("signals.id"))
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id"))
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id"))
    locator: Mapped[dict[str, Any]] = mapped_column(JSON)
    snippet: Mapped[str] = mapped_column(String(400))
    supports: Mapped[bool] = mapped_column(Boolean, default=True)
    independence_group: Mapped[str | None] = mapped_column(String(120))
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Memo(UpdatedAtMixin, Base):
    __tablename__ = "memos"
    __table_args__ = (UniqueConstraint("opportunity_id", "version"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(30), default="draft")
    sections: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    recommendation: Mapped[DecisionKind | None] = mapped_column(enum_type(DecisionKind))
    recommendation_rationale: Mapped[str | None] = mapped_column(Text)
    adversarial: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    gaps: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    trust_summary: Mapped[dict[str, int]] = mapped_column(JSON, default=dict)
    word_count: Mapped[int | None] = mapped_column(Integer)
    generated_ms: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    model_version: Mapped[str | None] = mapped_column(String(80))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class KBChunk(CreatedAtMixin, Base):
    __tablename__ = "kb_chunks"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    org_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("orgs.id"), index=True)
    scope: Mapped[str] = mapped_column(String(30))
    person_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("persons.id"))
    company_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("companies.id"))
    signal_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("signals.id"))
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id"))
    page_no: Mapped[int | None] = mapped_column(Integer)
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    token_count: Mapped[int] = mapped_column(Integer)
    source_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sources.id"))
    source_url: Mapped[str | None] = mapped_column(Text)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    embedding: Mapped[list[float] | None] = mapped_column(JSON)
    embedding_model: Mapped[str | None] = mapped_column(String(100))


class Job(UpdatedAtMixin, Base):
    __tablename__ = "jobs"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("orgs.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(100), index=True)
    status: Mapped[JobStatus] = mapped_column(enum_type(JobStatus), default=JobStatus.QUEUED)
    target_type: Mapped[str | None] = mapped_column(String(60))
    target_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(200), index=True)
    progress: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))
    current_step: Mapped[str | None] = mapped_column(String(100))
    input: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=2)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgentStep(CreatedAtMixin, Base):
    __tablename__ = "agent_steps"
    __table_args__ = (UniqueConstraint("job_id", "seq"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    agent: Mapped[str] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(30))
    progress: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    message: Mapped[str | None] = mapped_column(Text)
    input_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=Decimal("0"))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)


class LLMCall(CreatedAtMixin, Base):
    __tablename__ = "llm_calls"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    org_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("orgs.id"), index=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jobs.id"))
    provider: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(120))
    purpose: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(30))
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 5), default=Decimal("0"))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    cached: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text)


class SourcingChannel(UpdatedAtMixin, Base):
    __tablename__ = "sourcing_channels"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    key: Mapped[str] = mapped_column(String(100), unique=True)
    label: Mapped[str] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(50))
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sourcing_channels.id"))
    discovered_count: Mapped[int] = mapped_column(Integer, default=0)
    advanced_count: Mapped[int] = mapped_column(Integer, default=0)


class ChannelEdge(CreatedAtMixin, Base):
    __tablename__ = "channel_edges"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    channel_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sourcing_channels.id"), index=True)
    person_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("persons.id"))
    company_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("companies.id"))
    weight: Mapped[Decimal] = mapped_column(Numeric(5, 3), default=Decimal("1"))
    outcome: Mapped[str | None] = mapped_column(String(50))


class Outreach(UpdatedAtMixin, Base):
    __tablename__ = "outreach"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    person_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("persons.id"))
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("opportunities.id"))
    status: Mapped[OutreachStatus] = mapped_column(
        enum_type(OutreachStatus), default=OutreachStatus.SUGGESTED
    )
    subject: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    cited_signal_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[str | None] = mapped_column(Text)


class IdempotencyRecord(CreatedAtMixin, Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (UniqueConstraint("org_id", "route", "key"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    route: Mapped[str] = mapped_column(String(160))
    key: Mapped[str] = mapped_column(String(200))
    request_hash: Mapped[str] = mapped_column(String(64))
    status_code: Mapped[int] = mapped_column(Integer)
    response: Mapped[dict[str, Any]] = mapped_column(JSON)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EmailToken(CreatedAtMixin, Base):
    __tablename__ = "email_tokens"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    purpose: Mapped[str] = mapped_column(String(20))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OrgInvite(CreatedAtMixin, Base):
    __tablename__ = "org_invites"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    role: Mapped[UserRole] = mapped_column(enum_type(UserRole), default=UserRole.ANALYST)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
