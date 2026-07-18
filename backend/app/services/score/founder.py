import math
from dataclasses import dataclass
from datetime import UTC, datetime

COMPONENT_WEIGHTS = {
    "execution": 0.26,
    "technical_depth": 0.18,
    "domain_expertise": 0.14,
    "outcomes": 0.14,
    "velocity": 0.12,
    "validation": 0.10,
    "communication": 0.06,
}
HALF_LIFE_DAYS = {
    "execution": 540,
    "technical_depth": 720,
    "domain_expertise": 900,
    "outcomes": 1460,
    "velocity": 120,
    "validation": 720,
    "communication": 365,
}


@dataclass(frozen=True)
class ScoreEvent:
    component: str
    delta: float
    occurred_at: datetime
    weight: float = 1.0
    source_key: str = "unknown"


@dataclass(frozen=True)
class FounderScoreResult:
    score: int
    ci_low: int
    ci_high: int
    confidence: float
    components: dict[str, dict[str, float | int | None]]
    cold_start: bool


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def compute_founder_score(
    events: list[ScoreEvent],
    *,
    now: datetime | None = None,
    cohort_mean: float = 50.0,
    cohort_sd: float = 15.0,
) -> FounderScoreResult:
    now = now or datetime.now(UTC)
    by_component: dict[str, list[ScoreEvent]] = {key: [] for key in COMPONENT_WEIGHTS}
    for event in events:
        if event.component in by_component:
            by_component[event.component].append(event)

    values: dict[str, dict[str, float | int | None]] = {}
    weighted_mean = 0.0
    independent_sources: set[str] = set()
    observation_weight = 0.0
    for component, component_weight in COMPONENT_WEIGHTS.items():
        numerator = 0.0
        denominator = 0.0
        sources: set[str] = set()
        for event in by_component[component]:
            timestamp = event.occurred_at
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=UTC)
            age_days = max(0, (now - timestamp).days)
            recency = 0.5 ** (age_days / HALF_LIFE_DAYS[component])
            effective_weight = max(0.0, event.weight) * recency
            numerator += max(0.0, min(100.0, event.delta)) * effective_weight
            denominator += effective_weight
            sources.add(event.source_key)
        raw = numerator / denominator if denominator else None
        value = raw if raw is not None else cohort_mean
        weighted_mean += value * component_weight
        independent_sources.update(sources)
        observation_weight += min(2.1, len(sources))
        values[component] = {
            "value": round(raw, 2) if raw is not None else None,
            "prior": cohort_mean if raw is None else None,
            "weight": component_weight,
            "evidence_sources": len(sources),
        }

    # Bayesian shrinkage: thin evidence stays close to the cohort mean rather than being penalized.
    prior_weight = 4.0
    posterior = (prior_weight * cohort_mean + observation_weight * weighted_mean) / (
        prior_weight + observation_weight
    )
    z_score = (posterior - cohort_mean) / max(cohort_sd, 1.0)
    score = round(300 + 600 * _normal_cdf(z_score))
    confidence = 1.0 - math.exp(-observation_weight / 6.0)
    width = round(45 + 125 * (1.0 - confidence))
    ci_low = max(300, score - width)
    ci_high = min(900, score + width)
    cold_start = len(independent_sources) < 3
    return FounderScoreResult(
        score=score,
        ci_low=ci_low,
        ci_high=ci_high,
        confidence=round(confidence, 3),
        components=values,
        cold_start=cold_start,
    )
