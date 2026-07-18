import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import FounderScore, FounderScoreEvent, FounderScoreSnapshot
from app.services.score.founder import ScoreEvent, compute_founder_score
from app.services.utils import utcnow
from app.types import TrendKind


async def recompute_founder_score(session: AsyncSession, person_id: uuid.UUID) -> FounderScore:
    events = (
        await session.scalars(
            select(FounderScoreEvent)
            .where(FounderScoreEvent.person_id == person_id)
            .order_by(FounderScoreEvent.occurred_at)
        )
    ).all()
    result = compute_founder_score(
        [
            ScoreEvent(
                component=row.component,
                delta=float(row.delta),
                occurred_at=row.occurred_at,
                weight=float(row.weight),
                source_key=str(row.signal_id or f"event:{row.id}"),
            )
            for row in events
        ]
    )
    current = await session.get(FounderScore, person_id)
    if current is None:
        current = FounderScore(
            person_id=person_id,
            score=result.score,
            ci_low=result.ci_low,
            ci_high=result.ci_high,
            confidence=Decimal(str(result.confidence)),
            components=result.components,
            cold_start=result.cold_start,
            trend=TrendKind.INSUFFICIENT_DATA,
            version=1,
        )
        session.add(current)
    else:
        delta = result.score - current.score
        current.score = result.score
        current.ci_low = result.ci_low
        current.ci_high = result.ci_high
        current.confidence = Decimal(str(result.confidence))
        current.components = result.components
        current.cold_start = result.cold_start
        current.trend_30d = delta
        current.trend = (
            TrendKind.STABLE
            if abs(delta) < 3
            else TrendKind.IMPROVING
            if delta > 0
            else TrendKind.DECLINING
        )
        current.version += 1
        current.computed_at = utcnow()
    snapshot = await session.get(FounderScoreSnapshot, (person_id, utcnow().date()))
    if snapshot is None:
        session.add(
            FounderScoreSnapshot(
                person_id=person_id,
                day=utcnow().date(),
                score=result.score,
                confidence=Decimal(str(result.confidence)),
            )
        )
    else:
        snapshot.score = result.score
        snapshot.confidence = Decimal(str(result.confidence))
    await session.flush()
    return current
