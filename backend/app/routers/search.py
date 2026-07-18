from fastapi import APIRouter, Query, Request
from sqlalchemy import select

from app.db.models import Company, Opportunity, Person
from app.deps import DBSession, ReadPrincipal
from app.schemas.search import KBSearchRequest, OpportunitySearchRequest, OpportunitySearchResponse
from app.services.search import search_kb, search_opportunities

router = APIRouter(prefix="/search", tags=["search"])


@router.post("/opportunities", response_model=OpportunitySearchResponse)
async def opportunity_search(
    body: OpportunitySearchRequest,
    request: Request,
    principal: ReadPrincipal,
    session: DBSession,
) -> OpportunitySearchResponse:
    return await search_opportunities(
        session,
        request.app.state.settings,
        principal.org_id,
        q=body.q,
        limit=body.limit,
    )


@router.post("/kb")
async def kb_search(
    body: KBSearchRequest,
    principal: ReadPrincipal,
    session: DBSession,
) -> dict[str, object]:
    chunks = await search_kb(
        session,
        principal.org_id,
        q=body.q,
        company_id=body.company_id,
        person_id=body.person_id,
        k=body.k,
    )
    return {
        "chunks": chunks,
        "used_web": False,
        "cost_usd": 0,
        "degraded": body.include_web,
        "degradation_reasons": ["web_search_runs_as_a_background_research_job"]
        if body.include_web
        else [],
    }


@router.get("/suggest")
async def suggest(
    principal: ReadPrincipal,
    session: DBSession,
    q: str = Query(min_length=1, max_length=100),
) -> list[dict[str, str]]:
    pattern = f"%{q.casefold()}%"
    companies = (
        await session.execute(
            select(Company.id, Company.name)
            .join(Opportunity, Opportunity.company_id == Company.id)
            .where(Opportunity.org_id == principal.org_id, Company.name.ilike(pattern))
            .limit(8)
        )
    ).all()
    people = (
        await session.execute(
            select(Person.id, Person.display_name)
            .where(Person.display_name.ilike(pattern))
            .limit(8)
        )
    ).all()
    return [
        *({"type": "company", "id": str(item_id), "label": label} for item_id, label in companies),
        *({"type": "person", "id": str(item_id), "label": label} for item_id, label in people),
    ][:10]
