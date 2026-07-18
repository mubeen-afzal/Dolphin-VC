import uuid

from app.services.jobs import reap_stale_jobs
from app.services.pipeline import process_job


async def run_job(ctx: dict[str, object], job_id: str) -> None:
    await process_job(ctx["database"], ctx["settings"], ctx["object_store"], uuid.UUID(job_id))  # type: ignore[arg-type]


async def reaper(ctx: dict[str, object]) -> int:
    database = ctx["database"]
    async with database.session_factory() as session:  # type: ignore[attr-defined]
        return await reap_stale_jobs(session)


async def source_health(_ctx: dict[str, object]) -> None:
    return None
