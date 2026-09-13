"""Evidence-backed dataset quality scores.

Unknown dimensions remain ``None`` and never lower or inflate the overall
score.  The overall score is the unweighted mean of dimensions supported by
evidence from stored rows.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import distinct, func, select

from .models import Building, DataSource, EnergyMonthly, Grid, PopulationGrid, WeatherMonthly


DIMENSIONS = ("coverage", "completeness", "temporal", "spatial_match")


def _dimension(value: Any) -> dict[str, Any]:
    if value is None:
        return {"score": None, "evidence": "available evidence 없음"}
    if isinstance(value, dict):
        score = value.get("score")
        evidence = value.get("evidence") or "근거 설명 없음"
    else:
        score = value
        evidence = "caller-provided score"
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        raise ValueError("quality score must be numeric or null")
    if not 0 <= float(score) <= 1:
        raise ValueError("quality score must be between 0 and 1")
    return {"score": float(score), "evidence": str(evidence)}


def calculate_quality(
    coverage: float | dict[str, Any] | None,
    completeness: float | dict[str, Any] | None,
    temporal: float | dict[str, Any] | None,
    spatial_match: float | dict[str, Any] | None,
) -> dict[str, Any]:
    """Calculate a transparent [0, 1] score from known dimensions only."""

    dimensions = {
        name: _dimension(value)
        for name, value in zip(
            DIMENSIONS,
            (coverage, completeness, temporal, spatial_match),
            strict=True,
        )
    }
    known = [item["score"] for item in dimensions.values() if item["score"] is not None]
    if known:
        overall = sum(known) / len(known)
        explanation = (
            f"{len(known)}/4 dimensions supported by available evidence; "
            "overall is the mean of known dimensions only."
        )
    else:
        overall = None
        explanation = "0/4 dimensions supported; available evidence 없음."
    return {
        "overall": overall,
        "known_dimensions": len(known),
        "dimensions": dimensions,
        "explanation": explanation,
    }


def _ratio(numerator: int, denominator: int, evidence: str) -> dict[str, Any] | None:
    if denominator <= 0:
        return None
    return {"score": min(max(numerator / denominator, 0.0), 1.0), "evidence": evidence}


def dataset_quality(db: Any, source_id: str, year: int = 2025) -> dict[str, Any]:
    """Calculate quality from the source catalogue and its stored normalized rows."""

    source = db.get(DataSource, source_id)
    if source is None:
        raise LookupError(f"data source not found: {source_id}")

    raw_count = int(source.raw_row_count or 0)
    normalized_count = int(source.normalized_row_count or 0)
    coverage = _ratio(
        normalized_count,
        raw_count,
        f"{normalized_count} normalized rows / {raw_count} raw rows",
    )
    missing_count = source.missing_count
    completeness = None
    if normalized_count > 0 and missing_count is not None:
        present = max(normalized_count - int(missing_count), 0)
        completeness = _ratio(
            present,
            normalized_count,
            f"{present} complete rows / {normalized_count} normalized rows",
        )

    temporal = None
    spatial_match = None
    year_prefix = str(year)
    if source_id == "energy" or "에너지" in source.category:
        base = EnergyMonthly.use_ym.startswith(year_prefix)
        if source_id != "energy":
            base = (EnergyMonthly.source == source_id) & base
        total = int(db.scalar(select(func.count()).select_from(EnergyMonthly).where(base)) or 0)
        energy_type_months = len(
            db.execute(
                select(EnergyMonthly.use_ym, EnergyMonthly.energy_type)
                .where(base)
                .distinct()
            ).all()
        )
        matched = int(
            db.scalar(
                select(func.count())
                .select_from(EnergyMonthly)
                .where(base, EnergyMonthly.grid_id.is_not(None))
            )
            or 0
        )
        temporal = _ratio(
            energy_type_months,
            24,
            f"{energy_type_months} observed energy-type months in {year} / 24 expected (12 x electricity/gas)",
        )
        spatial_match = _ratio(matched, total, f"{matched} grid-matched rows / {total} rows")
    elif source_id == "weather" or "기상" in source.category:
        base = WeatherMonthly.use_ym.startswith(year_prefix)
        months = int(
            db.scalar(select(func.count(distinct(WeatherMonthly.use_ym))).where(base)) or 0
        )
        observed_days, expected_days = db.execute(
            select(
                func.coalesce(func.sum(WeatherMonthly.days_observed), 0),
                func.coalesce(func.sum(WeatherMonthly.expected_days), 0),
            ).where(base)
        ).one()
        coverage = _ratio(
            months,
            12,
            f"{months} normalized months / 12 expected in {year}",
        )
        completeness = _ratio(
            int(observed_days),
            int(expected_days),
            f"{int(observed_days)} observed days / {int(expected_days)} expected days",
        )
        temporal = _ratio(months, 12, f"{months} distinct months in {year} / 12 expected")
    elif source_id == "buildings" or "건축물" in source.category:
        base = Building.id.is_not(None) if source_id == "buildings" else Building.source == source_id
        total = int(db.scalar(select(func.count()).select_from(Building).where(base)) or 0)
        matched = int(
            db.scalar(
                select(func.count()).select_from(Building).where(base, Building.grid_id.is_not(None))
            )
            or 0
        )
        spatial_match = _ratio(matched, total, f"{matched} grid-matched buildings / {total} buildings")
    elif source_id == "population" or "인구" in source.category:
        base = PopulationGrid.source == source_id
        total = int(db.scalar(select(func.count()).select_from(PopulationGrid).where(base)) or 0)
        matched = int(
            db.scalar(
                select(func.count())
                .select_from(PopulationGrid)
                .where(base, PopulationGrid.grid_id.is_not(None))
            )
            or 0
        )
        spatial_match = _ratio(matched, total, f"{matched} grid-referenced rows / {total} rows")
    elif source_id == "grid" or "격자" in source.category:
        total = int(db.scalar(select(func.count()).select_from(Grid)) or 0)
        spatial_match = (
            {"score": 1.0, "evidence": f"{total} stored grid geometries validated at import"}
            if total
            else None
        )

    result = calculate_quality(coverage, completeness, temporal, spatial_match)
    result.update({"source_id": source_id, "year": year})
    return result
