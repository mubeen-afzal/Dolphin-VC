from dataclasses import dataclass
from statistics import mean

from app.types import DecisionKind


@dataclass(frozen=True)
class AxisValue:
    score: float
    confidence: float
    rationale: str = ""


@dataclass(frozen=True)
class TrustSummary:
    contradicted_critical: bool = False


@dataclass(frozen=True)
class Recommendation:
    decision: DecisionKind
    rationale: str


def recommend(
    axes: list[AxisValue],
    thesis_fit: float,
    trust_summary: TrustSummary,
    cold_start: bool,
    gate_reason: str | None = None,
) -> Recommendation:
    if len(axes) != 3:
        return Recommendation(DecisionKind.NEEDS_HUMAN, "One or more axes could not be scored.")
    if trust_summary.contradicted_critical:
        return Recommendation(
            DecisionKind.NEEDS_HUMAN, "A decision-critical claim is contradicted."
        )
    if thesis_fit == 0:
        return Recommendation(DecisionKind.PASS, gate_reason or "A hard thesis gate failed.")
    if min(axis.score for axis in axes) < 25:
        weakest = min(axes, key=lambda item: item.score)
        return Recommendation(
            DecisionKind.PASS, weakest.rationale or "One independent axis is below 25."
        )
    mean_confidence = mean(axis.confidence for axis in axes)
    if all(axis.score >= 70 for axis in axes) and thesis_fit >= 65 and mean_confidence >= 0.55:
        return Recommendation(
            DecisionKind.INVEST, "All three axes and thesis fit clear the investment bar."
        )
    if max(axis.score for axis in axes) - min(axis.score for axis in axes) > 30:
        return Recommendation(DecisionKind.WATCHLIST, "The independent axes disagree materially.")
    if mean_confidence < 0.40 or cold_start:
        return Recommendation(
            DecisionKind.NEEDS_HUMAN,
            "Evidence is too thin for a confident automated recommendation.",
        )
    return Recommendation(
        DecisionKind.WATCHLIST,
        "Evidence is credible but does not clear every investment threshold.",
    )
