from datetime import UTC, datetime

from app.services.score.founder import ScoreEvent, compute_founder_score


def test_cold_start_widens_interval_not_lowers_mean() -> None:
    empty = compute_founder_score([])
    neutral = compute_founder_score(
        [ScoreEvent("execution", 50, datetime.now(UTC), source_key="artifact")]
    )
    assert empty.cold_start is True
    assert empty.score == neutral.score
    assert empty.ci_high - empty.ci_low > neutral.ci_high - neutral.ci_low


def test_distinct_sources_raise_confidence() -> None:
    now = datetime.now(UTC)
    one_source = compute_founder_score(
        [ScoreEvent("execution", 80, now, source_key="github") for _ in range(20)]
    )
    three_sources = compute_founder_score(
        [
            ScoreEvent("execution", 80, now, source_key="github"),
            ScoreEvent("technical_depth", 80, now, source_key="arxiv"),
            ScoreEvent("validation", 80, now, source_key="hackathon"),
        ]
    )
    assert three_sources.confidence > one_source.confidence
    assert three_sources.cold_start is False
