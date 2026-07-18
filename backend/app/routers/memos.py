import uuid
from typing import Annotated

from fastapi import APIRouter, Header, Request, Response
from sqlalchemy import select

from app.db.models import Claim, Evidence, Job, Memo
from app.deps import DBSession, ReadPrincipal, ScreenPrincipal
from app.errors import AppError, ConflictError, NotFoundError
from app.schemas.common import JobAccepted
from app.schemas.memo import MemoExportRequest, MemoOut, MemoPatch
from app.services.jobs import create_job, dispatch_job
from app.services.opportunities import get_opportunity
from app.services.utils import utcnow
from app.types import JobStatus

router = APIRouter(tags=["memos"])


async def _memo(session: DBSession, org_id: uuid.UUID, memo_id: uuid.UUID) -> Memo:
    memo = await session.scalar(select(Memo).where(Memo.id == memo_id, Memo.org_id == org_id))
    if memo is None:
        raise NotFoundError("Memo")
    return memo


@router.get("/memos/{memo_id}", response_model=MemoOut)
async def get_memo(memo_id: uuid.UUID, principal: ReadPrincipal, session: DBSession) -> MemoOut:
    return MemoOut.model_validate(await _memo(session, principal.org_id, memo_id))


@router.get("/opportunities/{opportunity_id}/memo", response_model=MemoOut)
async def get_opportunity_memo(
    opportunity_id: uuid.UUID,
    principal: ReadPrincipal,
    session: DBSession,
    version: str = "latest",
) -> MemoOut:
    await get_opportunity(session, principal.org_id, opportunity_id)
    query = select(Memo).where(
        Memo.opportunity_id == opportunity_id, Memo.org_id == principal.org_id
    )
    if version != "latest":
        try:
            query = query.where(Memo.version == int(version))
        except ValueError as exc:
            raise AppError("VALIDATION_ERROR", "version must be 'latest' or an integer") from exc
    else:
        query = query.order_by(Memo.version.desc())
    memo = await session.scalar(query.limit(1))
    if memo is None:
        raise NotFoundError("Memo")
    return MemoOut.model_validate(memo)


@router.post(
    "/memos/{memo_id}/sections/{key}/regenerate", response_model=JobAccepted, status_code=202
)
async def regenerate_section(
    memo_id: uuid.UUID,
    key: str,
    request: Request,
    response: Response,
    principal: ScreenPrincipal,
    session: DBSession,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JobAccepted:
    memo = await _memo(session, principal.org_id, memo_id)
    if not idempotency_key:
        raise AppError("VALIDATION_ERROR", "Idempotency-Key header is required.")
    job, replayed = await create_job(
        session,
        org_id=principal.org_id,
        kind="memo",
        target_type="opportunity",
        target_id=memo.opportunity_id,
        idempotency_key=idempotency_key,
        input_data={"memo_id": str(memo.id), "section": key},
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


@router.patch("/memos/{memo_id}", response_model=MemoOut)
async def patch_memo(
    memo_id: uuid.UUID,
    body: MemoPatch,
    principal: ScreenPrincipal,
    session: DBSession,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> MemoOut:
    memo = await _memo(session, principal.org_id, memo_id)
    if if_match is None or if_match.strip('"') != str(memo.version):
        raise ConflictError("Memo version is stale or If-Match is missing.", "STALE_VERSION")
    sections = []
    for section in body.sections:
        sections.append(
            {**section, "edited_by": str(principal.user_id), "edited_at": utcnow().isoformat()}
        )
    memo.sections = sections
    memo.version += 1
    await session.commit()
    await session.refresh(memo)
    return MemoOut.model_validate(memo)


@router.post("/memos/{memo_id}/export", response_model=JobAccepted, status_code=202)
async def export_memo(
    memo_id: uuid.UUID,
    body: MemoExportRequest,
    principal: ScreenPrincipal,
    session: DBSession,
) -> JobAccepted:
    memo = await _memo(session, principal.org_id, memo_id)
    job = Job(
        org_id=principal.org_id,
        kind="memo.export",
        status=JobStatus.SUCCEEDED,
        target_type="memo",
        target_id=memo.id,
        progress=100,
        input={"format": body.format},
        result={
            "download_url": None,
            "expires_at": None,
            "degraded": True,
            "degradation_reasons": ["Binary memo export adapter is not configured."],
        },
        started_at=utcnow(),
        finished_at=utcnow(),
    )
    session.add(job)
    await session.commit()
    return JobAccepted(job_id=job.id)


@router.get("/memos/{memo_id}/citations")
async def memo_citations(
    memo_id: uuid.UUID,
    principal: ReadPrincipal,
    session: DBSession,
) -> list[dict[str, object]]:
    memo = await _memo(session, principal.org_id, memo_id)
    claims = (
        await session.scalars(select(Claim).where(Claim.opportunity_id == memo.opportunity_id))
    ).all()
    output = []
    for claim in claims:
        evidence = (
            await session.scalars(select(Evidence).where(Evidence.claim_id == claim.id))
        ).all()
        output.append(
            {
                "claim_id": str(claim.id),
                "text": claim.text,
                "trust_score": float(claim.trust_score),
                "status": claim.status.value,
                "evidence": [
                    {
                        "id": str(item.id),
                        "locator": item.locator,
                        "snippet": item.snippet,
                        "supports": item.supports,
                    }
                    for item in evidence
                ],
            }
        )
    return output
