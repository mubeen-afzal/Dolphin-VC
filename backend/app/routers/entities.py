import uuid
from datetime import timedelta

from fastapi import APIRouter, Query
from sqlalchemy import or_, select

from app.db.models import (
    Company,
    FounderScore,
    FounderScoreSnapshot,
    Job,
    Person,
    Signal,
    Source,
)
from app.deps import AdminPrincipal, DBSession, ReadPrincipal, ScreenPrincipal
from app.errors import NotFoundError
from app.schemas.common import CursorPage, JobAccepted
from app.schemas.entities import CompanyOut, SignalOut, SourceOut
from app.schemas.founder import (
    FounderCard,
    FounderHistoryPoint,
    FounderMergeRequest,
    FounderProfile,
    FounderScoreOut,
    UpliftAction,
    UpliftPlan,
)
from app.services.founders import recompute_founder_score
from app.services.utils import normalize_name, utcnow
from app.types import JobStatus, SignalKind, SourceStatus

router = APIRouter(tags=["entities"])


def score_out(score: FounderScore | None) -> FounderScoreOut | None:
    if score is None:
        return None
    return FounderScoreOut(
        score=score.score,
        ci=[score.ci_low, score.ci_high],
        confidence=score.confidence,
        components=score.components,
        cold_start=score.cold_start,
        percentile=score.percentile,
        trend_30d=score.trend_30d,
        trend=score.trend,
        version=score.version,
        computed_at=score.computed_at,
    )


@router.get("/founders", response_model=CursorPage[FounderCard])
async def founders(
    principal: ReadPrincipal,
    session: DBSession,
    q: str | None = None,
    min_score: int | None = Query(default=None, ge=300, le=900),
    max_score: int | None = Query(default=None, ge=300, le=900),
    cold_start: bool | None = None,
    country: str | None = None,
    limit: int = Query(default=25, ge=1, le=100),
) -> CursorPage[FounderCard]:
    query = select(Person, FounderScore).outerjoin(
        FounderScore, FounderScore.person_id == Person.id
    )
    if q:
        query = query.where(Person.normalized_name.like(f"%{normalize_name(q)}%"))
    if min_score is not None:
        query = query.where(FounderScore.score >= min_score)
    if max_score is not None:
        query = query.where(FounderScore.score <= max_score)
    if cold_start is not None:
        query = query.where(FounderScore.cold_start == cold_start)
    if country:
        query = query.where(Person.country_code == country.upper())
    rows = (
        await session.execute(query.order_by(FounderScore.score.desc().nullslast()).limit(limit))
    ).all()
    items = [
        FounderCard(
            id=person.id,
            display_name=person.display_name,
            headline=person.headline,
            country_code=person.country_code,
            city=person.city,
            skills=person.skills,
            score=score_out(score),
        )
        for person, score in rows
    ]
    return CursorPage(items=items, total_estimate=len(items))


async def _person(session: DBSession, person_id: uuid.UUID) -> Person:
    person = await session.scalar(
        select(Person).where(Person.id == person_id, Person.merged_into_id.is_(None))
    )
    if person is None:
        raise NotFoundError("Founder")
    return person


@router.get("/founders/{person_id}", response_model=FounderProfile)
async def founder_profile(
    person_id: uuid.UUID,
    principal: ReadPrincipal,
    session: DBSession,
) -> FounderProfile:
    person = await _person(session, person_id)
    score = await session.get(FounderScore, person.id)
    return FounderProfile(
        id=person.id,
        display_name=person.display_name,
        headline=person.headline,
        country_code=person.country_code,
        city=person.city,
        skills=person.skills,
        score=score_out(score),
        bio=person.bio,
        location_text=person.location_text,
        links=person.links,
        education=person.education,
        employment=person.employment,
        signal_count=person.signal_count,
        source_count=person.source_count,
        is_stub=person.is_stub,
        first_seen_at=person.first_seen_at,
        last_signal_at=person.last_signal_at,
    )


@router.get("/founders/{person_id}/score/history", response_model=list[FounderHistoryPoint])
async def founder_history(
    person_id: uuid.UUID,
    principal: ReadPrincipal,
    session: DBSession,
    days: int = Query(default=180, ge=1, le=730),
) -> list[FounderHistoryPoint]:
    await _person(session, person_id)
    rows = (
        await session.scalars(
            select(FounderScoreSnapshot)
            .where(
                FounderScoreSnapshot.person_id == person_id,
                FounderScoreSnapshot.day >= (utcnow() - timedelta(days=days)).date(),
            )
            .order_by(FounderScoreSnapshot.day)
        )
    ).all()
    return [FounderHistoryPoint.model_validate(row) for row in rows]


@router.get("/founders/{person_id}/score/explain")
async def founder_score_explain(
    person_id: uuid.UUID,
    principal: ReadPrincipal,
    session: DBSession,
) -> dict[str, object]:
    await _person(session, person_id)
    score = await session.get(FounderScore, person_id)
    if score is None:
        score = await recompute_founder_score(session, person_id)
        await session.commit()
    components = []
    for key, value in score.components.items():
        components.append(
            {
                "key": key,
                "value": value.get("value"),
                "weight": value.get("weight"),
                "contribution": None
                if value.get("value") is None
                else value["value"] * value["weight"],
                "evidence": [],
                "reason": "no_evidence" if value.get("value") is None else None,
            }
        )
    return {
        "components": components,
        "cohort": {"key": "generic", "n": 0, "mean": 550},
        "cold_start": score.cold_start,
        "confidence": float(score.confidence),
        "ci": [score.ci_low, score.ci_high],
        "missing": [item["key"] for item in components if item["value"] is None],
    }


@router.post("/founders/{person_id}/rescore", response_model=JobAccepted, status_code=202)
async def rescore_founder(
    person_id: uuid.UUID,
    principal: ScreenPrincipal,
    session: DBSession,
) -> JobAccepted:
    await _person(session, person_id)
    score = await recompute_founder_score(session, person_id)
    job = Job(
        org_id=principal.org_id,
        kind="score.founder",
        status=JobStatus.SUCCEEDED,
        target_type="person",
        target_id=person_id,
        progress=100,
        result={"person_id": str(person_id), "score": score.score},
        started_at=utcnow(),
        finished_at=utcnow(),
    )
    session.add(job)
    await session.commit()
    return JobAccepted(job_id=job.id)


@router.get("/founders/{person_id}/uplift-plan", response_model=UpliftPlan)
async def uplift_plan(
    person_id: uuid.UUID,
    principal: ReadPrincipal,
    session: DBSession,
) -> UpliftPlan:
    await _person(session, person_id)
    score = await session.get(FounderScore, person_id)
    components = score.components if score else {}
    candidates = {
        "execution": UpliftAction(
            action="Link a live proof-of-work artifact",
            expected_delta=24,
            why="Adds primary execution evidence.",
        ),
        "technical_depth": UpliftAction(
            action="Link a repository, paper, dataset, or technical demo",
            expected_delta=18,
            why="Adds verifiable technical depth.",
        ),
        "domain_expertise": UpliftAction(
            action="Answer a falsifiable domain interview question",
            expected_delta=12,
            why="Makes domain insight legible without requiring a network.",
        ),
        "communication": UpliftAction(
            action="Publish a concise product explanation",
            expected_delta=8,
            why="Provides communication evidence.",
        ),
    }
    missing = [
        key for key in candidates if not components or components.get(key, {}).get("value") is None
    ]
    return UpliftPlan(actions=[candidates[key] for key in missing[:3]])


@router.post("/founders/{person_id}/merge")
async def merge_founder(
    person_id: uuid.UUID,
    body: FounderMergeRequest,
    principal: AdminPrincipal,
    session: DBSession,
) -> dict[str, str]:
    winner = await _person(session, person_id)
    loser = await _person(session, body.loser_id)
    loser.merged_into_id = winner.id
    await session.commit()
    return {"winner_id": str(winner.id), "loser_id": str(loser.id), "status": "merged"}


@router.get("/companies/{company_id}", response_model=CompanyOut)
async def company_profile(
    company_id: uuid.UUID,
    principal: ReadPrincipal,
    session: DBSession,
) -> CompanyOut:
    # Access is allowed only when this tenant has an opportunity for the company.
    from app.db.models import Opportunity

    tenant_link = await session.scalar(
        select(Opportunity.id).where(
            Opportunity.org_id == principal.org_id, Opportunity.company_id == company_id
        )
    )
    if tenant_link is None:
        raise NotFoundError("Company")
    company = await session.get(Company, company_id)
    if company is None:
        raise NotFoundError("Company")
    return CompanyOut.model_validate(company)


@router.get("/signals", response_model=CursorPage[SignalOut])
async def signals(
    principal: ReadPrincipal,
    session: DBSession,
    person_id: uuid.UUID | None = None,
    company_id: uuid.UUID | None = None,
    kind: SignalKind | None = None,
    limit: int = Query(default=25, ge=1, le=100),
) -> CursorPage[SignalOut]:
    query = select(Signal).where(or_(Signal.org_id == principal.org_id, Signal.org_id.is_(None)))
    if person_id:
        query = query.where(Signal.person_id == person_id)
    if company_id:
        query = query.where(Signal.company_id == company_id)
    if kind:
        query = query.where(Signal.kind == kind)
    rows = (await session.scalars(query.order_by(Signal.observed_at.desc()).limit(limit))).all()
    return CursorPage(
        items=[SignalOut.model_validate(row) for row in rows], total_estimate=len(rows)
    )


@router.get("/sources", response_model=list[SourceOut])
async def sources(principal: ReadPrincipal, session: DBSession) -> list[SourceOut]:
    rows = (await session.scalars(select(Source).order_by(Source.display_name))).all()
    return [SourceOut.model_validate(row) for row in rows]


@router.post("/sources/{key}/test")
async def test_source(
    key: str,
    principal: ScreenPrincipal,
    session: DBSession,
) -> dict[str, object]:
    source = await session.scalar(select(Source).where(Source.key == key))
    if source is None:
        raise NotFoundError("Source")
    # This endpoint checks configuration without turning a settings screen into an expensive harvest.
    configured = source.status != SourceStatus.NO_CREDENTIALS
    return {"ok": configured, "latency_ms": 0, "sample": None, "status": source.status.value}
