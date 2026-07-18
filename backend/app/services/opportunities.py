import uuid
from collections import Counter
from datetime import timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import (
    Affiliation,
    Claim,
    Company,
    FounderScore,
    Memo,
    Opportunity,
    OpportunityScore,
    Person,
)
from app.errors import AppError, ConflictError, NotFoundError
from app.schemas.opportunity import (
    AxisScoreOut,
    CompanySummary,
    FounderSummary,
    OpportunityCard,
    OpportunityDetail,
    OpportunityList,
    SLAOut,
)
from app.services.utils import aware, decode_cursor, encode_cursor, normalize_name, utcnow
from app.types import ClaimStatus, OpportunityOrigin, OpportunityStage


async def get_opportunity(
    session: AsyncSession, org_id: uuid.UUID, opportunity_id: uuid.UUID
) -> Opportunity:
    opportunity = await session.scalar(
        select(Opportunity).where(Opportunity.id == opportunity_id, Opportunity.org_id == org_id)
    )
    if opportunity is None:
        raise NotFoundError("Opportunity")
    return opportunity


async def _founders(session: AsyncSession, company_id: uuid.UUID) -> list[FounderSummary]:
    rows = (
        await session.execute(
            select(Person, FounderScore)
            .join(Affiliation, Affiliation.person_id == Person.id)
            .outerjoin(FounderScore, FounderScore.person_id == Person.id)
            .where(Affiliation.company_id == company_id, Affiliation.is_founder.is_(True))
        )
    ).all()
    return [
        FounderSummary(
            person_id=person.id,
            name=person.display_name,
            founder_score=score.score if score else None,
            founder_score_ci=[score.ci_low, score.ci_high] if score else None,
            cold_start=score.cold_start if score else True,
        )
        for person, score in rows
    ]


async def _axes(session: AsyncSession, opportunity_id: uuid.UUID) -> dict[str, AxisScoreOut | None]:
    rows = (
        await session.scalars(
            select(OpportunityScore)
            .where(OpportunityScore.opportunity_id == opportunity_id)
            .order_by(OpportunityScore.version.desc())
        )
    ).all()
    latest: dict[str, AxisScoreOut | None] = {
        "founder": None,
        "market": None,
        "idea_vs_market": None,
    }
    for row in rows:
        if latest[row.axis.value] is None:
            latest[row.axis.value] = AxisScoreOut.model_validate(row)
    return latest


async def _trust_summary(session: AsyncSession, opportunity_id: uuid.UUID) -> dict[str, int]:
    rows = (
        await session.execute(
            select(Claim.status, func.count(Claim.id))
            .where(Claim.opportunity_id == opportunity_id)
            .group_by(Claim.status)
        )
    ).all()
    counter = Counter({status.value: int(count) for status, count in rows})
    return {status.value: counter[status.value] for status in ClaimStatus}


def _sla(opportunity: Opportunity, settings: Settings) -> SLAOut:
    now = utcnow()
    deadline = aware(opportunity.sla_deadline_at)
    hours = (deadline - now).total_seconds() / 3600
    return SLAOut(
        deadline_at=deadline,
        hours_remaining=round(hours, 2),
        at_risk=opportunity.decided_at is None and 0 < hours < 4,
        breached=opportunity.decided_at is None and hours <= 0,
    )


async def build_card(
    session: AsyncSession, settings: Settings, opportunity: Opportunity
) -> OpportunityCard:
    company = await session.get(Company, opportunity.company_id)
    if company is None:
        raise NotFoundError("Company")
    return OpportunityCard(
        id=opportunity.id,
        company=CompanySummary(
            id=company.id,
            name=company.name,
            domain=company.domain,
            one_liner=company.one_liner,
            sectors=company.sectors,
            hq_country=company.hq_country,
            hq_city=company.hq_city,
        ),
        origin=opportunity.origin,
        stage=opportunity.stage,
        founders=await _founders(session, company.id),
        axes=await _axes(session, opportunity.id),
        thesis_fit=opportunity.thesis_fit,
        trust_summary=await _trust_summary(session, opportunity.id),
        decision=opportunity.decision,
        sla=_sla(opportunity, settings),
        first_signal_at=opportunity.first_signal_at,
        updated_at=opportunity.updated_at,
    )


async def build_detail(
    session: AsyncSession, settings: Settings, opportunity: Opportunity
) -> OpportunityDetail:
    card = await build_card(session, settings, opportunity)
    memo = await session.scalar(
        select(Memo)
        .where(Memo.opportunity_id == opportunity.id)
        .order_by(Memo.version.desc())
        .limit(1)
    )
    claims = (
        await session.scalars(
            select(Claim).where(Claim.opportunity_id == opportunity.id).limit(200)
        )
    ).all()
    return OpportunityDetail(
        **card.model_dump(),
        title=opportunity.title,
        thesis_id=opportunity.thesis_id,
        conviction=opportunity.conviction,
        priority_rank=opportunity.priority_rank,
        sourced_at=opportunity.sourced_at,
        screened_at=opportunity.screened_at,
        diligence_started_at=opportunity.diligence_started_at,
        memo_ready_at=opportunity.memo_ready_at,
        decided_at=opportunity.decided_at,
        decision_rationale=opportunity.decision_rationale,
        assigned_to=opportunity.assigned_to,
        version=opportunity.version,
        claims=[
            {
                "id": str(item.id),
                "category": item.category.value,
                "text": item.text,
                "status": item.status.value,
                "trust_score": float(item.trust_score),
            }
            for item in claims
        ],
        memo={
            "id": str(memo.id),
            "version": memo.version,
            "status": memo.status,
            "recommendation": memo.recommendation.value if memo.recommendation else None,
        }
        if memo
        else None,
    )


async def list_opportunities(
    session: AsyncSession,
    settings: Settings,
    org_id: uuid.UUID,
    *,
    stage: OpportunityStage | None = None,
    origin: OpportunityOrigin | None = None,
    q: str | None = None,
    sla_risk: bool = False,
    cursor: str | None = None,
    limit: int = 25,
) -> OpportunityList:
    query = select(Opportunity).join(Company).where(Opportunity.org_id == org_id)
    if stage:
        query = query.where(Opportunity.stage == stage)
    if origin:
        query = query.where(Opportunity.origin == origin)
    if q:
        pattern = f"%{normalize_name(q)}%"
        query = query.where(
            or_(
                func.lower(Company.name).like(pattern),
                func.lower(Company.description).like(pattern),
            )
        )
    if sla_risk:
        now = utcnow()
        query = query.where(
            Opportunity.decided_at.is_(None),
            Opportunity.sla_deadline_at > now,
            Opportunity.sla_deadline_at < now + timedelta(hours=4),
        )
    if cursor:
        try:
            timestamp, row_id = decode_cursor(cursor)
            parsed_id = uuid.UUID(row_id)
        except ValueError as exc:
            raise AppError("VALIDATION_ERROR", "Invalid pagination cursor.") from exc
        query = query.where(
            or_(
                Opportunity.updated_at < timestamp,
                and_(Opportunity.updated_at == timestamp, Opportunity.id < parsed_id),
            )
        )
    rows = (
        await session.scalars(
            query.order_by(Opportunity.updated_at.desc(), Opportunity.id.desc()).limit(limit + 1)
        )
    ).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    cards = [await build_card(session, settings, row) for row in rows]
    next_cursor = encode_cursor(rows[-1].updated_at, rows[-1].id) if has_more and rows else None
    counts_stage = Counter(item.stage.value for item in rows)
    counts_origin = Counter(item.origin.value for item in rows)
    counts_decision = Counter(
        item.decision.value if item.decision else "undecided" for item in rows
    )
    total = await session.scalar(
        select(func.count()).select_from(Opportunity).where(Opportunity.org_id == org_id)
    )
    return OpportunityList(
        items=cards,
        next_cursor=next_cursor,
        total_estimate=int(total or 0),
        facets={
            "stage": dict(counts_stage),
            "origin": dict(counts_origin),
            "decision": dict(counts_decision),
        },
    )


async def create_manual_opportunity(
    session: AsyncSession,
    settings: Settings,
    org_id: uuid.UUID,
    *,
    company_id: uuid.UUID | None,
    company_name: str | None,
    origin: OpportunityOrigin,
    thesis_id: uuid.UUID | None,
) -> Opportunity:
    if company_id:
        company = await session.get(Company, company_id)
        if company is None:
            raise NotFoundError("Company")
    else:
        assert company_name is not None
        normalized = normalize_name(company_name)
        company = await session.scalar(select(Company).where(Company.normalized_name == normalized))
        if company is None:
            company = Company(name=company_name, normalized_name=normalized, is_stub=True)
            session.add(company)
            await session.flush()
    existing = await session.scalar(
        select(Opportunity).where(
            Opportunity.org_id == org_id,
            Opportunity.company_id == company.id,
            Opportunity.stage != OpportunityStage.ARCHIVED,
        )
    )
    if existing:
        raise ConflictError(
            "A live opportunity already exists for this company.", "DUPLICATE_OPPORTUNITY"
        )
    now = utcnow()
    opportunity = Opportunity(
        org_id=org_id,
        company_id=company.id,
        thesis_id=thesis_id,
        origin=origin,
        title=company.name,
        first_signal_at=now,
        sla_deadline_at=now + timedelta(hours=settings.decision_sla_hours),
        dedupe_key=f"{org_id}:{company.id}",
    )
    session.add(opportunity)
    await session.flush()
    return opportunity
