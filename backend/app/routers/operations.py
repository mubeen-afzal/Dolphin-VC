import math
import uuid

from fastapi import APIRouter, Request
from sqlalchemy import select

from app.db.models import (
    Affiliation,
    Job,
    Opportunity,
    Outreach,
    Person,
    Signal,
    SourcingChannel,
)
from app.deps import AdminPrincipal, DBSession, ReadPrincipal, ScreenPrincipal
from app.errors import AppError, NotFoundError
from app.schemas.admin import HarvestRequest, RejectOutreachRequest
from app.schemas.common import JobAccepted
from app.services.jobs import dispatch_job, queue_summary
from app.services.utils import aware, utcnow
from app.types import JobStatus, OutreachStatus

router = APIRouter(tags=["operations"])


@router.get("/graph/channels")
async def channel_graph(
    principal: ReadPrincipal, session: DBSession, window: str = "90d"
) -> dict[str, object]:
    channels = (await session.scalars(select(SourcingChannel))).all()
    nodes = []
    total_discovered = max(1, sum(item.discovered_count for item in channels))
    suggested = []
    for item in channels:
        alpha = 1 + item.advanced_count
        beta = 1 + max(0, item.discovered_count - item.advanced_count)
        quality = alpha / (alpha + beta)
        variance = alpha * beta / (((alpha + beta) ** 2) * (alpha + beta + 1))
        radius = 1.28 * math.sqrt(variance)
        exploration = quality + 1.2 * math.sqrt(
            math.log(total_discovered + 1) / max(1, item.discovered_count)
        )
        nodes.append(
            {
                "id": str(item.id),
                "label": item.label,
                "kind": item.kind,
                "quality": round(quality, 3),
                "ci": [round(max(0, quality - radius), 3), round(min(1, quality + radius), 3)],
                "discovered": item.discovered_count,
                "advanced": item.advanced_count,
            }
        )
        if item.discovered_count < 5:
            suggested.append(
                {
                    "channel_id": str(item.id),
                    "reason": "Under-explored channel with a wide uncertainty interval.",
                    "expected_yield": round(exploration, 3),
                }
            )
    return {"nodes": nodes, "edges": [], "suggested": suggested[:5], "window": window}


@router.get("/graph/founder/{person_id}")
async def founder_graph(
    person_id: uuid.UUID,
    principal: ReadPrincipal,
    session: DBSession,
) -> dict[str, object]:
    person = await session.get(Person, person_id)
    if person is None:
        raise NotFoundError("Founder")
    affiliations = (
        await session.scalars(select(Affiliation).where(Affiliation.person_id == person_id))
    ).all()
    return {
        "nodes": [{"id": str(person.id), "label": person.display_name, "kind": "person"}],
        "edges": [
            {
                "from": str(person.id),
                "to": str(item.company_id),
                "kind": item.role,
                "weight": float(item.confidence),
            }
            for item in affiliations
        ],
    }


async def _outreach(session: DBSession, org_id: uuid.UUID, outreach_id: uuid.UUID) -> Outreach:
    row = await session.scalar(
        select(Outreach).where(Outreach.id == outreach_id, Outreach.org_id == org_id)
    )
    if row is None:
        raise NotFoundError("Outreach")
    return row


@router.get("/outreach")
async def list_outreach(
    principal: ReadPrincipal,
    session: DBSession,
    status: OutreachStatus | None = None,
) -> list[dict[str, object]]:
    query = select(Outreach).where(Outreach.org_id == principal.org_id)
    if status:
        query = query.where(Outreach.status == status)
    rows = (await session.scalars(query.order_by(Outreach.created_at.desc()))).all()
    return [
        {
            "id": str(row.id),
            "person_id": str(row.person_id),
            "opportunity_id": str(row.opportunity_id) if row.opportunity_id else None,
            "status": row.status.value,
            "subject": row.subject,
            "body": row.body,
            "cited_signal_ids": row.cited_signal_ids,
        }
        for row in rows
    ]


@router.post("/outreach/{outreach_id}/approve")
async def approve_outreach(
    outreach_id: uuid.UUID,
    principal: ScreenPrincipal,
    session: DBSession,
) -> dict[str, object]:
    row = await _outreach(session, principal.org_id, outreach_id)
    row.status = OutreachStatus.APPROVED
    row.approved_by = principal.user_id
    await session.commit()
    return {"id": str(row.id), "status": row.status.value}


@router.post("/outreach/{outreach_id}/send")
async def send_outreach(
    outreach_id: uuid.UUID,
    request: Request,
    principal: ScreenPrincipal,
    session: DBSession,
) -> dict[str, object]:
    row = await _outreach(session, principal.org_id, outreach_id)
    if row.status != OutreachStatus.APPROVED:
        raise AppError(
            "UNPROCESSABLE", "Outreach must be approved before sending.", status_code=422
        )
    row.status = OutreachStatus.SENT
    row.sent_at = utcnow()
    await session.commit()
    return {
        "id": str(row.id),
        "status": row.status.value,
        "delivery": "demo_noop" if request.app.state.settings.demo_mode else "external_adapter",
    }


@router.post("/outreach/{outreach_id}/reject")
async def reject_outreach(
    outreach_id: uuid.UUID,
    body: RejectOutreachRequest,
    principal: ScreenPrincipal,
    session: DBSession,
) -> dict[str, object]:
    row = await _outreach(session, principal.org_id, outreach_id)
    row.status = OutreachStatus.DECLINED
    row.rejection_reason = body.reason
    await session.commit()
    return {"id": str(row.id), "status": row.status.value}


@router.post("/admin/harvest", response_model=JobAccepted, status_code=202)
async def harvest(
    body: HarvestRequest,
    request: Request,
    principal: AdminPrincipal,
    session: DBSession,
) -> JobAccepted:
    job = Job(
        org_id=principal.org_id,
        kind="ingest.harvest",
        status=JobStatus.QUEUED,
        target_type="organization",
        target_id=principal.org_id,
        input=body.model_dump(),
    )
    session.add(job)
    await session.commit()
    await dispatch_job(
        database=request.app.state.database,
        settings=request.app.state.settings,
        store=request.app.state.object_store,
        job_id=job.id,
    )
    return JobAccepted(job_id=job.id)


@router.get("/admin/usage")
async def usage(
    principal: AdminPrincipal,
    session: DBSession,
    days: int = 7,
) -> dict[str, object]:
    opportunities = (
        await session.scalars(select(Opportunity).where(Opportunity.org_id == principal.org_id))
    ).all()
    durations = [
        (aware(item.decided_at) - aware(item.first_signal_at)).total_seconds() / 3600
        for item in opportunities
        if item.decided_at
    ]
    durations.sort()
    median = durations[len(durations) // 2] if durations else None
    breaches = sum(
        1
        for item in opportunities
        if item.decided_at and aware(item.decided_at) > aware(item.sla_deadline_at)
    )
    return {
        "by_day": [],
        "by_purpose": [],
        "per_opportunity_avg_usd": 0,
        "median_time_to_decision_h": round(median, 2) if median is not None else None,
        "sla_breaches": breaches,
        "window_days": days,
    }


@router.get("/admin/queue")
async def admin_queue(principal: AdminPrincipal, session: DBSession) -> dict[str, int | float]:
    return await queue_summary(session)


@router.get("/admin/merges")
async def merges(
    principal: AdminPrincipal, session: DBSession, status: str = "pending"
) -> list[object]:
    return []


@router.post("/admin/merges/{merge_id}/{action}")
async def merge_action(
    merge_id: uuid.UUID,
    action: str,
    principal: AdminPrincipal,
) -> dict[str, str]:
    if action not in {"confirm", "reject", "undo"}:
        raise AppError("VALIDATION_ERROR", "action must be confirm, reject, or undo")
    return {"merge_id": str(merge_id), "status": action}


@router.get("/admin/gdpr/export")
async def gdpr_export(
    person_id: uuid.UUID,
    principal: AdminPrincipal,
    session: DBSession,
) -> dict[str, object]:
    person = await session.get(Person, person_id)
    if person is None:
        raise NotFoundError("Founder")
    signals = (await session.scalars(select(Signal).where(Signal.person_id == person_id))).all()
    return {
        "person": {
            "id": str(person.id),
            "display_name": person.display_name,
            "headline": person.headline,
            "bio": person.bio,
            "links": person.links,
        },
        "signals": [
            {
                "id": str(item.id),
                "kind": item.kind.value,
                "url": item.url,
                "observed_at": item.observed_at,
            }
            for item in signals
        ],
    }


@router.post("/admin/gdpr/erase")
async def gdpr_erase(
    person_id: uuid.UUID,
    principal: AdminPrincipal,
    session: DBSession,
) -> dict[str, object]:
    person = await session.get(Person, person_id)
    if person is None:
        raise NotFoundError("Founder")
    # Minimal irreversible anonymization; production should also write the documented tombstone hash.
    person.display_name = "Erased data subject"
    person.normalized_name = f"erased-{person.id}"
    person.headline = None
    person.bio = None
    person.emails = []
    person.links = {}
    person.education = []
    person.employment = []
    await session.commit()
    return {"person_id": str(person_id), "status": "erased", "recoverable": False}
