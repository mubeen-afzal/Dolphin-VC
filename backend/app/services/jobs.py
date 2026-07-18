import asyncio
import uuid
from datetime import timedelta
from typing import Any

from arq import create_pool
from arq.connections import RedisSettings
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import Job
from app.db.session import Database
from app.services.object_store import ObjectStore
from app.services.pipeline import process_job
from app.services.utils import utcnow
from app.types import JobStatus


async def create_job(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    kind: str,
    target_type: str,
    target_id: uuid.UUID,
    idempotency_key: str,
    input_data: dict[str, Any] | None = None,
) -> tuple[Job, bool]:
    existing = await session.scalar(
        select(Job).where(
            Job.org_id == org_id,
            Job.kind == kind,
            Job.target_id == target_id,
            Job.idempotency_key == idempotency_key,
            Job.created_at >= utcnow() - timedelta(hours=24),
        )
    )
    if existing:
        return existing, True
    job = Job(
        org_id=org_id,
        kind=kind,
        target_type=target_type,
        target_id=target_id,
        idempotency_key=idempotency_key,
        input=input_data or {},
    )
    session.add(job)
    await session.flush()
    return job, False


async def dispatch_job(
    *,
    database: Database,
    settings: Settings,
    store: ObjectStore,
    job_id: uuid.UUID,
) -> None:
    if settings.queue_eager:
        task = asyncio.create_task(process_job(database, settings, store, job_id))
        database.background_tasks.add(task)
        task.add_done_callback(database.background_tasks.discard)
        return
    try:
        redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        await redis.enqueue_job("run_job", str(job_id), _job_id=str(job_id))
        await redis.close()
    except Exception:
        # Postgres remains the source of truth. The reaper can enqueue this row later.
        return


async def queue_summary(session: AsyncSession) -> dict[str, int | float]:
    rows = (
        await session.execute(select(Job.status, func.count(Job.id)).group_by(Job.status))
    ).all()
    counts = {status.value: int(count) for status, count in rows}
    oldest = await session.scalar(
        select(func.min(Job.created_at)).where(Job.status == JobStatus.QUEUED)
    )
    oldest_seconds = (utcnow() - oldest).total_seconds() if oldest else 0.0
    return {
        "queued": counts.get("queued", 0),
        "running": counts.get("running", 0),
        "failed_24h": counts.get("failed", 0),
        "oldest_queued_s": round(oldest_seconds, 1),
    }


async def reap_stale_jobs(session: AsyncSession) -> int:
    threshold = utcnow() - timedelta(seconds=90)
    stale = (
        await session.scalars(
            select(Job).where(
                Job.status == JobStatus.RUNNING,
                Job.heartbeat_at.is_not(None),
                Job.heartbeat_at < threshold,
            )
        )
    ).all()
    for job in stale:
        job.status = JobStatus.FAILED
        job.error_code = "WORKER_LOST"
        job.error_message = "Worker heartbeat was lost. The job can be retried."
        job.finished_at = utcnow()
    await session.commit()
    return len(stale)
