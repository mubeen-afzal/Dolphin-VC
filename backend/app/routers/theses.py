import uuid

from fastapi import APIRouter, Header, Response
from sqlalchemy import select, update

from app.db.models import Thesis
from app.deps import DBSession, ReadPrincipal, ThesisPrincipal
from app.errors import ConflictError, NotFoundError
from app.schemas.thesis import ThesisCreate, ThesisOut, ThesisPreview, ThesisUpdate
from app.services.utils import utcnow

router = APIRouter(prefix="/theses", tags=["theses"])


async def _get(session: DBSession, org_id: uuid.UUID, thesis_id: uuid.UUID) -> Thesis:
    thesis = await session.scalar(
        select(Thesis).where(Thesis.id == thesis_id, Thesis.org_id == org_id)
    )
    if thesis is None:
        raise NotFoundError("Thesis")
    return thesis


@router.get("", response_model=list[ThesisOut])
async def list_theses(
    principal: ReadPrincipal,
    session: DBSession,
    include_deleted: bool = False,
) -> list[ThesisOut]:
    query = select(Thesis).where(Thesis.org_id == principal.org_id)
    if not include_deleted:
        query = query.where(Thesis.deleted_at.is_(None))
    rows = (
        await session.scalars(query.order_by(Thesis.is_default.desc(), Thesis.created_at))
    ).all()
    return [ThesisOut.model_validate(row) for row in rows]


@router.post("", response_model=ThesisOut, status_code=201)
async def create_thesis(
    body: ThesisCreate, principal: ThesisPrincipal, session: DBSession
) -> ThesisOut:
    if body.is_default:
        await session.execute(
            update(Thesis).where(Thesis.org_id == principal.org_id).values(is_default=False)
        )
    thesis = Thesis(org_id=principal.org_id, **body.model_dump())
    session.add(thesis)
    await session.commit()
    await session.refresh(thesis)
    return ThesisOut.model_validate(thesis)


@router.get("/{thesis_id}", response_model=ThesisOut)
async def get_thesis(
    thesis_id: uuid.UUID, principal: ReadPrincipal, session: DBSession
) -> ThesisOut:
    return ThesisOut.model_validate(await _get(session, principal.org_id, thesis_id))


@router.patch("/{thesis_id}", response_model=ThesisOut)
async def update_thesis(
    thesis_id: uuid.UUID,
    body: ThesisUpdate,
    principal: ThesisPrincipal,
    session: DBSession,
    if_match: str | None = Header(default=None, alias="If-Match"),
) -> ThesisOut:
    thesis = await _get(session, principal.org_id, thesis_id)
    if if_match is None or if_match.strip('"') != str(thesis.version):
        raise ConflictError("Thesis version is stale or If-Match is missing.", "STALE_VERSION")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(thesis, key, value)
    thesis.version += 1
    await session.commit()
    await session.refresh(thesis)
    return ThesisOut.model_validate(thesis)


@router.delete("/{thesis_id}", status_code=204)
async def delete_thesis(
    thesis_id: uuid.UUID,
    principal: ThesisPrincipal,
    session: DBSession,
) -> Response:
    thesis = await _get(session, principal.org_id, thesis_id)
    thesis.deleted_at = utcnow()
    thesis.is_default = False
    await session.commit()
    return Response(status_code=204)


@router.post("/{thesis_id}/default", response_model=ThesisOut)
async def set_default(
    thesis_id: uuid.UUID,
    principal: ThesisPrincipal,
    session: DBSession,
) -> ThesisOut:
    thesis = await _get(session, principal.org_id, thesis_id)
    await session.execute(
        update(Thesis).where(Thesis.org_id == principal.org_id).values(is_default=False)
    )
    thesis.is_default = True
    await session.commit()
    await session.refresh(thesis)
    return ThesisOut.model_validate(thesis)


@router.post("/{thesis_id}/preview", response_model=ThesisPreview)
async def preview_thesis(
    thesis_id: uuid.UUID,
    principal: ReadPrincipal,
    session: DBSession,
) -> ThesisPreview:
    await _get(session, principal.org_id, thesis_id)
    # A zero-LLM read-only preview. Detailed cards are available from /opportunities.
    from app.db.models import Opportunity

    count = len(
        (
            await session.scalars(
                select(Opportunity.id).where(Opportunity.org_id == principal.org_id).limit(200)
            )
        ).all()
    )
    return ThesisPreview(matched_count=count, sample=[], excluded_by_gate={"sector": 0, "geo": 0})
