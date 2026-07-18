from arq import cron
from arq.connections import RedisSettings

from app.config import get_settings
from app.db.session import Database
from app.services.object_store import ObjectStore
from app.workers.tasks import reaper, run_job, source_health


async def startup(ctx: dict[str, object]) -> None:
    settings = get_settings()
    ctx["settings"] = settings
    ctx["database"] = Database(settings)
    ctx["object_store"] = ObjectStore(settings)


async def shutdown(ctx: dict[str, object]) -> None:
    await ctx["database"].dispose()  # type: ignore[attr-defined]


class WorkerSettings:
    functions = [run_job]
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = 8
    job_timeout = 900
    keep_result = 3600
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)


class SchedulerSettings:
    functions = [reaper, source_health]
    cron_jobs = [
        cron(reaper, second={0}),
        cron(source_health, minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55}),
    ]
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = 2
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
