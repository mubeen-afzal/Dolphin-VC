from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.db.models import FounderScoreEvent, Person
from app.services.founders import recompute_founder_score
from app.services.utils import normalize_name


@pytest.mark.integration
async def test_founder_score_never_resets(app) -> None:
    async with app.state.database.session_factory() as session:
        person = Person(
            display_name="Returning Founder", normalized_name=normalize_name("Returning Founder")
        )
        session.add(person)
        await session.flush()
        session.add(
            FounderScoreEvent(
                person_id=person.id,
                component="execution",
                delta=Decimal("65"),
                reason="First product shipped.",
                occurred_at=datetime.now(UTC),
            )
        )
        await session.flush()
        first = await recompute_founder_score(session, person.id)
        first_version = first.version
        session.add(
            FounderScoreEvent(
                person_id=person.id,
                component="technical_depth",
                delta=Decimal("85"),
                reason="Second company adds a verified technical artifact.",
                occurred_at=datetime.now(UTC),
            )
        )
        await session.flush()
        second = await recompute_founder_score(session, person.id)
        event_count = await session.scalar(
            select(func.count(FounderScoreEvent.id)).where(FounderScoreEvent.person_id == person.id)
        )
        assert second.version == first_version + 1
        assert event_count == 2
        assert second.score >= first.score
