from app.services.score.recommendation import AxisValue, TrustSummary, recommend
from app.types import DecisionKind


def test_axes_are_not_averaged_when_they_disagree() -> None:
    result = recommend(
        [AxisValue(92, 0.8), AxisValue(58, 0.7), AxisValue(76, 0.7)],
        80,
        TrustSummary(False),
        cold_start=False,
    )
    assert result.decision == DecisionKind.WATCHLIST


def test_critical_contradiction_escalates() -> None:
    result = recommend(
        [AxisValue(90, 0.8), AxisValue(90, 0.8), AxisValue(90, 0.8)],
        90,
        TrustSummary(True),
        cold_start=False,
    )
    assert result.decision == DecisionKind.NEEDS_HUMAN
