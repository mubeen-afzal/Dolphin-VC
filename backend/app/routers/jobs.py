import asyncio
import json
import uuid

from fastapi import APIRouter, Header, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.db.models import AgentStep, Job
from app.deps import DBSession, ReadPrincipal, ScreenPrincipal
from app.errors import AppError, NotFoundError
from app.schemas.common import CursorPage, JobAccepted
from app.schemas.job import JobOut
from app.services.jobs import create_job, dispatch_job
from app.services.utils import utcnow
from app.types import JobStatus

router = APIRouter(prefix="/jobs", tags=["jobs"])


async def _job(session: DBSession, org_id: uuid.UUID, job_id: uuid.UUID) -> Job:
    job = await session.scalar(select(Job).where(Job.id == job_id, Job.org_id == org_id))
    if job is None:
        raise NotFoundError("Job")
    return job


@router.get("/{job_id}", response_model=JobOut)
async def get_job(job_id: uuid.UUID, principal: ReadPrincipal, session: DBSession) -> JobOut:
    return JobOut.model_validate(await _job(session, principal.org_id, job_id))


@router.get("", response_model=CursorPage[JobOut])
async def list_jobs(
    principal: ReadPrincipal,
    session: DBSession,
    target_type: str | None = None,
    target_id: uuid.UUID | None = None,
    status: JobStatus | None = None,
) -> CursorPage[JobOut]:
    query = select(Job).where(Job.org_id == principal.org_id)
    if target_type:
        query = query.where(Job.target_type == target_type)
    if target_id:
        query = query.where(Job.target_id == target_id)
    if status:
        query = query.where(Job.status == status)
    rows = (await session.scalars(query.order_by(Job.created_at.desc()).limit(100))).all()
    return CursorPage(items=[JobOut.model_validate(row) for row in rows], total_estimate=len(rows))


@router.get("/{job_id}/events")
async def job_events(
    job_id: uuid.UUID,
    request: Request,
    principal: ReadPrincipal,
    session: DBSession,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    await _job(session, principal.org_id, job_id)
    start_seq = int(last_event_id or 0)
    database = request.app.state.database

    async def stream():
        seq = start_seq
        heartbeat_ticks = 0
        while True:
            if await request.is_disconnected():
                break
            async with database.session_factory() as poll_session:
                steps = (
                    await poll_session.scalars(
                        select(AgentStep)
                        .where(AgentStep.job_id == job_id, AgentStep.seq > seq)
                        .order_by(AgentStep.seq)
                    )
                ).all()
                for step in steps:
                    seq = step.seq
                    payload = {
                        "job_id": str(job_id),
                        "seq": step.seq,
                        "agent": step.agent,
                        "action": step.action,
                        "status": step.status,
                        "progress": float(step.progress),
                        "message": step.message,
                        "cost_usd": float(step.cost_usd),
                        "at": step.created_at.isoformat(),
                    }
                    yield f"id: {step.seq}\nevent: step\ndata: {json.dumps(payload)}\n\n"
                current = await poll_session.get(Job, job_id)
                if current and current.status in {
                    JobStatus.SUCCEEDED,
                    JobStatus.FAILED,
                    JobStatus.CANCELLED,
                    JobStatus.PARTIAL,
                }:
                    payload = {
                        "status": current.status.value,
                        "result": current.result,
                        "error_code": current.error_code,
                    }
                    yield f"event: done\ndata: {json.dumps(payload)}\n\n"
                    break
            heartbeat_ticks += 1
            if heartbeat_ticks >= 15:
                heartbeat_ticks = 0
                yield ": heartbeat\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{job_id}/cancel", status_code=202)
async def cancel_job(
    job_id: uuid.UUID, principal: ScreenPrincipal, session: DBSession
) -> dict[str, str]:
    job = await _job(session, principal.org_id, job_id)
    if job.status in {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED}:
        raise AppError("UNPROCESSABLE", "Completed jobs cannot be cancelled.", status_code=422)
    job.status = JobStatus.CANCELLED
    job.finished_at = utcnow()
    await session.commit()
    return {"status": "cancelled"}


@router.post("/{job_id}/retry", response_model=JobAccepted, status_code=202)
async def retry_job(
    job_id: uuid.UUID,
    request: Request,
    principal: ScreenPrincipal,
    session: DBSession,
) -> JobAccepted:
    old = await _job(session, principal.org_id, job_id)
    if old.status not in {JobStatus.FAILED, JobStatus.PARTIAL}:
        raise AppError(
            "UNPROCESSABLE", "Only failed or partial jobs can be retried.", status_code=422
        )
    new, _ = await create_job(
        session,
        org_id=principal.org_id,
        kind=old.kind,
        target_type=old.target_type or "unknown",
        target_id=old.target_id or uuid.uuid4(),
        idempotency_key=f"retry:{old.id}:{old.attempts}",
        input_data={**old.input, "retry_of": str(old.id)},
    )
    await session.commit()
    await dispatch_job(
        database=request.app.state.database,
        settings=request.app.state.settings,
        store=request.app.state.object_store,
        job_id=new.id,
    )
    return JobAccepted(job_id=new.id)
