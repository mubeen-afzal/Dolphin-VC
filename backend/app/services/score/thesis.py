from dataclasses import dataclass


@dataclass(frozen=True)
class ThesisFitResult:
    score: float
    gate_reason: str | None
    must_have_coverage: list[dict[str, object]]


def compute_thesis_fit(
    *,
    company_sectors: list[str],
    company_stage: str | None,
    company_country: str | None,
    thesis_sectors: list[str],
    anti_sectors: list[str],
    stages: list[str],
    geos: list[str],
    must_haves: list[str],
    company_text: str,
) -> ThesisFitResult:
    sector_set = {item.casefold() for item in company_sectors}
    if sector_set & {item.casefold() for item in anti_sectors}:
        return ThesisFitResult(0.0, "Company matches an excluded sector.", [])
    if (
        thesis_sectors
        and sector_set
        and not sector_set & {item.casefold() for item in thesis_sectors}
    ):
        return ThesisFitResult(0.0, "Company is outside the thesis sectors.", [])
    if (
        stages
        and company_stage
        and company_stage.casefold() not in {item.casefold() for item in stages}
    ):
        return ThesisFitResult(0.0, "Company stage is outside the thesis.", [])
    if geos and company_country:
        allowed = {item.casefold() for item in geos}
        if company_country.casefold() not in allowed and "remote" not in allowed:
            return ThesisFitResult(0.0, "Company geography is outside the thesis.", [])
    folded = company_text.casefold()
    coverage = [
        {"rule": rule, "satisfied": all(token in folded for token in rule.casefold().split()[:3])}
        for rule in must_haves
    ]
    ratio = sum(bool(item["satisfied"]) for item in coverage) / len(coverage) if coverage else 1.0
    sector_match = (
        1.0
        if not thesis_sectors or sector_set & {item.casefold() for item in thesis_sectors}
        else 0.5
    )
    stage_match = (
        1.0
        if not stages
        or not company_stage
        or company_stage.casefold() in {item.casefold() for item in stages}
        else 0.5
    )
    geo_match = (
        1.0
        if not geos
        or not company_country
        or company_country.casefold() in {item.casefold() for item in geos}
        else 0.5
    )
    score = 100 * (0.4 * sector_match + 0.25 * stage_match + 0.15 * geo_match + 0.2 * ratio)
    return ThesisFitResult(round(score, 2), None, coverage)
