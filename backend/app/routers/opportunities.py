import uuid
from typing import Annotated

from fastapi import APIRouter, Header, Query, Request, Response
from sqlalchemy import func, select

from app.db.models import (
    AgentStep,
    Application,
    AuditLog,
    Claim,
    Evidence,
    Job,
    OpportunityScore,
)
from app.deps import DBSession, DecidePrincipal, ReadPrincipal, ScreenPrincipal
from app.errors import AppError, ConflictError
from app.schemas.common import JobAccepted
from app.schemas.job import AgentStepOut
from app.schemas.memo import ClaimOut, EvidenceOut
from app.schemas.opportunity import (
    DecisionRequest,
    DiligenceRequest,
    MemoRequest,
    OpportunityCreate,
    OpportunityDetail,
    OpportunityList,
    OpportunityUpdate,
    ScoreHistory,
    ScreenRequest,
)
from app.services.jobs import create_job, dispatch_job
from app.services.opportunities import (
    build_detail,
    create_manual_opportunity,
    get_opportunity,
    list_opportunities,
)
from app.services.utils import utcnow
from app.types import ClaimCategory, ClaimStatus, DecisionKind, OpportunityOrigin, OpportunityStage

router = APIRouter(prefix="/opportunities", tags=["opportunities"])


@router.get("", response_model=OpportunityList)
async def opportunity_list(
    request: Request,
    principal: ReadPrincipal,
    session: DBSession,
    stage: OpportunityStage | None = None,
    origin: OpportunityOrigin | None = None,
    q: str | None = None,
    sla_risk: bool = False,
    cursor: str | None = None,
    limit: int = Query(default=25, ge=1, le=100),
) -> OpportunityList:
    return await list_opportunities(
        session,
        request.app.state.settings,
        principal.org_id,
        stage=stage,
        origin=origin,
        q=q,
        sla_risk=sla_risk,
        cursor=cursor,
        limit=limit,
    )


@router.post("", response_model=OpportunityDetail, status_code=201)
async def create_opportunity(
    body: OpportunityCreate,
    request: Request,
    principal: ScreenPrincipal,
    session: DBSession,
) -> OpportunityDetail:
    opportunity = await create_manual_opportunity(
        session,
        request.app.state.settings,
        principal.org_id,
        company_id=body.company_id,
        company_name=body.company_name,
        origin=body.origin,
        thesis_id=body.thesis_id,
    )
    await session.commit()
    await session.refresh(opportunity)
    return await build_detail(session, request.app.state.settings, opportunity)


@router.get("/{opportunity_id}", response_model=OpportunityDetail)
async def opportunity_detail(
    opportunity_id: uuid.UUID,
    request: Request,
    principal: ReadPrincipal,
    session: DBSession,
) -> OpportunityDetail:
    opportunity = await get_opportunity(session, principal.org_id, opportunity_id)
    return await build_detail(session, request.app.state.settings, opportunity)


@router.patch("/{opportunity_id}", response_model=OpportunityDetail)
async def update_opportunity(
    opportunity_id: uuid.UUID,
    body: OpportunityUpdate,
    request: Request,
    principal: ScreenPrincipal,
    session: DBSession,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> OpportunityDetail:
    opportunity = await get_opportunity(session, principal.org_id, opportunity_id)
    if if_match is None or if_match.strip('"') != str(opportunity.version):
        raise ConflictError("Opportunity version is stale or If-Match is missing.", "STALE_VERSION")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(opportunity, key, value)
    opportunity.version += 1
    await session.commit()
    await session.refresh(opportunity)
    return await build_detail(session, request.app.state.settings, opportunity)


async def _start_job(
    *,
    kind: str,
    opportunity_id: uuid.UUID,
    input_data: dict[str, object],
    idempotency_key: str | None,
    response: Response,
    request: Request,
    org_id: uuid.UUID,
    session: DBSession,
) -> JobAccepted:
    if not idempotency_key:
        raise AppError("VALIDATION_ERROR", "Idempotency-Key header is required.")
    await get_opportunity(session, org_id, opportunity_id)
    if kind == "screen":
        application = await session.scalar(
            select(Application)
            .where(Application.opportunity_id == opportunity_id)
            .order_by(Application.received_at.desc())
            .limit(1)
        )
        if application and application.deck_document_id:
            input_data["document_id"] = str(application.deck_document_id)
            input_data["application_id"] = str(application.id)
    job, replayed = await create_job(
        session,
        org_id=org_id,
        kind=kind,
        target_type="opportunity",
        target_id=opportunity_id,
        idempotency_key=idempotency_key,
        input_data=input_data,
    )
    await session.commit()
    if replayed:
        response.headers["Idempotent-Replay"] = "true"
    else:
        await dispatch_job(
            database=request.app.state.database,
            settings=request.app.state.settings,
            store=request.app.state.object_store,
            job_id=job.id,
        )
    return JobAccepted(job_id=job.id)


@router.post("/{opportunity_id}/screen", response_model=JobAccepted, status_code=202)
async def screen_opportunity(
    opportunity_id: uuid.UUID,
    body: ScreenRequest,
    response: Response,
    request: Request,
    principal: ScreenPrincipal,
    session: DBSession,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JobAccepted:
    return await _start_job(
        kind="screen",
        opportunity_id=opportunity_id,
        input_data=body.model_dump(),
        idempotency_key=idempotency_key,
        response=response,
        request=request,
        org_id=principal.org_id,
        session=session,
    )


@router.post("/{opportunity_id}/diligence", response_model=JobAccepted, status_code=202)
async def diligence_opportunity(
    opportunity_id: uuid.UUID,
    body: DiligenceRequest,
    response: Response,
    request: Request,
    principal: ScreenPrincipal,
    session: DBSession,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JobAccepted:
    return await _start_job(
        kind="diligence",
        opportunity_id=opportunity_id,
        input_data=body.model_dump(),
        idempotency_key=idempotency_key,
        response=response,
        request=request,
        org_id=principal.org_id,
        session=session,
    )


@router.post("/{opportunity_id}/memo", response_model=JobAccepted, status_code=202)
async def memo_opportunity(
    opportunity_id: uuid.UUID,
    body: MemoRequest,
    response: Response,
    request: Request,
    principal: ScreenPrincipal,
    session: DBSession,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JobAccepted:
    return await _start_job(
        kind="memo",
        opportunity_id=opportunity_id,
        input_data=body.model_dump(),
        idempotency_key=idempotency_key,
        response=response,
        request=request,
        org_id=principal.org_id,
        session=session,
    )


@router.post("/{opportunity_id}/decide", response_model=OpportunityDetail)
async def decide_opportunity(
    opportunity_id: uuid.UUID,
    body: DecisionRequest,
    request: Request,
    principal: DecidePrincipal,
    session: DBSession,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> OpportunityDetail:
    if not idempotency_key:
        raise AppError("VALIDATION_ERROR", "Idempotency-Key header is required.")
    opportunity = await get_opportunity(session, principal.org_id, opportunity_id)
    if opportunity.stage == OpportunityStage.ARCHIVED:
        raise AppError(
            "UNPROCESSABLE", "Archived opportunities cannot be decided.", status_code=422
        )
    existing_audit = await session.scalar(
        select(AuditLog).where(
            AuditLog.org_id == principal.org_id,
            AuditLog.action == "opportunity.decide",
            AuditLog.target_id == opportunity.id,
            AuditLog.meta["idempotency_key"].as_string() == idempotency_key,
        )
    )
    if existing_audit and opportunity.decision:
        return await build_detail(session, request.app.state.settings, opportunity)
    evidence_count = await session.scalar(
        select(func.count(Evidence.id)).join(Claim).where(Claim.opportunity_id == opportunity.id)
    )
    if body.decision == DecisionKind.PASS and not evidence_count:
        raise AppError(
            "COLD_START_INSUFFICIENT_EVIDENCE",
            "A pass decision must cite evidence rather than missing data.",
            status_code=422,
        )
    now = utcnow()
    opportunity.decision = body.decision
    opportunity.decision_rationale = body.rationale
    opportunity.decision_by = principal.user_id
    opportunity.decided_at = now
    opportunity.stage = OpportunityStage.DECIDED
    opportunity.version += 1
    session.add(
        AuditLog(
            org_id=principal.org_id,
            actor_user_id=principal.user_id,
            actor_kind=principal.kind,
            action="opportunity.decide",
            target_type="opportunity",
            target_id=opportunity.id,
            meta={"decision": body.decision.value, "idempotency_key": idempotency_key},
            request_id=getattr(request.state, "request_id", None),
        )
    )
    application = await session.scalar(
        select(Application).where(Application.opportunity_id == opportunity.id)
    )
    if application:
        from app.types import ApplicationStatus

        application.status = ApplicationStatus.DECIDED
    await session.commit()
    await session.refresh(opportunity)
    return await build_detail(session, request.app.state.settings, opportunity)


@router.post("/{opportunity_id}/archive", response_model=OpportunityDetail)
async def archive_opportunity(
    opportunity_id: uuid.UUID,
    request: Request,
    principal: ScreenPrincipal,
    session: DBSession,
) -> OpportunityDetail:
    opportunity = await get_opportunity(session, principal.org_id, opportunity_id)
    opportunity.stage = OpportunityStage.ARCHIVED
    opportunity.version += 1
    await session.commit()
    return await build_detail(session, request.app.state.settings, opportunity)


@router.get("/{opportunity_id}/timeline")
async def opportunity_timeline(
    opportunity_id: uuid.UUID,
    principal: ReadPrincipal,
    session: DBSession,
) -> list[dict[str, object]]:
    opportunity = await get_opportunity(session, principal.org_id, opportunity_id)
    values = [
        ("first_signal", opportunity.first_signal_at),
        ("sourced", opportunity.sourced_at),
        ("screened", opportunity.screened_at),
        ("diligence_started", opportunity.diligence_started_at),
        ("memo_ready", opportunity.memo_ready_at),
        ("decided", opportunity.decided_at),
    ]
    return [{"event": name, "at": at} for name, at in values if at is not None]


@router.get("/{opportunity_id}/scores", response_model=ScoreHistory)
async def opportunity_scores(
    opportunity_id: uuid.UUID,
    principal: ReadPrincipal,
    session: DBSession,
    history: bool = False,
) -> ScoreHistory:
    await get_opportunity(session, principal.org_id, opportunity_id)
    rows = (
        await session.scalars(
            select(OpportunityScore)
            .where(OpportunityScore.opportunity_id == opportunity_id)
            .order_by(OpportunityScore.axis, OpportunityScore.version.desc())
        )
    ).all()
    from app.schemas.opportunity import AxisScoreOut

    current = []
    seen = set()
    for row in rows:
        if row.axis not in seen:
            current.append(AxisScoreOut.model_validate(row))
            seen.add(row.axis)
    return ScoreHistory(
        current=current,
        history=[AxisScoreOut.model_validate(row) for row in rows] if history else [],
    )


@router.get("/{opportunity_id}/claims", response_model=list[ClaimOut])
async def opportunity_claims(
    opportunity_id: uuid.UUID,
    principal: ReadPrincipal,
    session: DBSession,
    category: ClaimCategory | None = None,
    status: ClaimStatus | None = None,
    min_trust: float = Query(default=0, ge=0, le=1),
) -> list[ClaimOut]:
    await get_opportunity(session, principal.org_id, opportunity_id)
    query = select(Claim).where(
        Claim.opportunity_id == opportunity_id,
        Claim.trust_score >= min_trust,
    )
    if category:
        query = query.where(Claim.category == category)
    if status:
        query = query.where(Claim.status == status)
    rows = (await session.scalars(query.order_by(Claim.created_at.desc()))).all()
    return [ClaimOut.model_validate(row) for row in rows]


@router.get("/{opportunity_id}/evidence/{claim_id}", response_model=list[EvidenceOut])
async def claim_evidence(
    opportunity_id: uuid.UUID,
    claim_id: uuid.UUID,
    principal: ReadPrincipal,
    session: DBSession,
) -> list[EvidenceOut]:
    await get_opportunity(session, principal.org_id, opportunity_id)
    claim = await session.scalar(
        select(Claim).where(Claim.id == claim_id, Claim.opportunity_id == opportunity_id)
    )
    if claim is None:
        from app.errors import NotFoundError

        raise NotFoundError("Claim")
    rows = (await session.scalars(select(Evidence).where(Evidence.claim_id == claim_id))).all()
    return [EvidenceOut.model_validate(row) for row in rows]


@router.get("/{opportunity_id}/trace", response_model=list[AgentStepOut])
async def opportunity_trace(
    opportunity_id: uuid.UUID,
    principal: ReadPrincipal,
    session: DBSession,
    job_id: uuid.UUID | None = None,
) -> list[AgentStepOut]:
    await get_opportunity(session, principal.org_id, opportunity_id)
    query = (
        select(AgentStep)
        .join(Job)
        .where(Job.target_id == opportunity_id, Job.org_id == principal.org_id)
    )
    if job_id:
        query = query.where(AgentStep.job_id == job_id)
    rows = (await session.scalars(query.order_by(AgentStep.created_at, AgentStep.seq))).all()
    return [AgentStepOut.model_validate(row) for row in rows]
