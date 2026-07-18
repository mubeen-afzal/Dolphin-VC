from fastapi import APIRouter, Request
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from redis.asyncio import Redis
from sqlalchemy import text

router = APIRouter(tags=["system"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(request: Request) -> tuple[dict[str, object], int] | dict[str, object]:
    result: dict[str, object] = {"db": False, "redis": False, "s3": False, "sources": {}}
    try:
        async with request.app.state.database.session_factory() as session:
            await session.execute(text("SELECT 1"))
        result["db"] = True
    except Exception as exc:
        result["db_error"] = type(exc).__name__
    redis = Redis.from_url(request.app.state.settings.redis_url)
    try:
        result["redis"] = bool(await redis.ping())
    except Exception as exc:
        result["redis_error"] = type(exc).__name__
    finally:
        await redis.aclose()
    result["s3"] = await request.app.state.object_store.ready()
    result["status"] = "ok" if all(result[key] for key in ("db", "redis", "s3")) else "degraded"
    if result["status"] != "ok":
        from fastapi.responses import JSONResponse

        return JSONResponse(result, status_code=503, headers={"Retry-After": "2"})
    return result


@router.get("/metrics")
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@router.get("/version")
async def version(request: Request) -> dict[str, object]:
    settings = request.app.state.settings
    return {
        "version": settings.app_version,
        "git_sha": settings.git_sha,
        "built_at": settings.built_at,
        "model_versions": {
            "founder": "founder-v1",
            "axes": "axes-deterministic-v1",
            "trust": "trust-v1",
            "memo": "memo-deterministic-v1",
        },
    }


@router.get("/api/v1/public/privacy")
async def privacy() -> dict[str, object]:
    return {
        "purpose": "Professional information is processed for investment assessment and decision support.",
        "sources": ["founder submissions", "public professional APIs", "public company records"],
        "excluded": ["special-category data", "home addresses", "personal phone numbers"],
        "human_review": "The system recommends; a human makes final adverse decisions.",
    }
