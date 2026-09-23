"""Official building-use groups and per-grid building indicators (pure functions).

Use codes follow the 건축물 용도 분류 of 건축법 시행령 별표 1, as used by the 도로명주소 건물
layer (``bdtyp_cd``, 5 digits; the first two digits are the major group, e.g. 02001 아파트 → 02
공동주택). Only groups 01–22 are mapped by name; any other code is kept as "기타(코드)" rather
than guessed.
"""
from __future__ import annotations

from typing import Any, Iterable

USE_GROUPS: dict[str, tuple[str, str]] = {
    "01": ("단독주택", "RESIDENTIAL"), "02": ("공동주택", "RESIDENTIAL"),
    "03": ("제1종 근린생활시설", "COMMERCIAL"), "04": ("제2종 근린생활시설", "COMMERCIAL"),
    "05": ("문화 및 집회시설", "PUBLIC"), "06": ("종교시설", "PUBLIC"), "07": ("판매시설", "COMMERCIAL"),
    "08": ("운수시설", "OTHER"), "09": ("의료시설", "PUBLIC"), "10": ("교육연구시설", "PUBLIC"),
    "11": ("노유자시설", "PUBLIC"), "12": ("수련시설", "PUBLIC"), "13": ("운동시설", "PUBLIC"),
    "14": ("업무시설", "COMMERCIAL"), "15": ("숙박시설", "COMMERCIAL"), "16": ("위락시설", "COMMERCIAL"),
    "17": ("공장", "INDUSTRIAL"), "18": ("창고시설", "INDUSTRIAL"), "19": ("위험물 저장 및 처리 시설", "INDUSTRIAL"),
    "20": ("자동차 관련 시설", "OTHER"), "21": ("동물 및 식물 관련 시설", "OTHER"), "22": ("자원순환 관련 시설", "OTHER"),
}
CATEGORY_LABEL = {
    "RESIDENTIAL": "주거", "COMMERCIAL": "상업·업무", "INDUSTRIAL": "공업·창고",
    "PUBLIC": "공공·교육·의료", "OTHER": "기타", "UNKNOWN": "용도 미상",
}
CATEGORIES = tuple(CATEGORY_LABEL)
GRID_AREA_M2 = 250_000.0


def classify_use(code: Any) -> tuple[str | None, str]:
    """Return (use label, category) for a building-use code; unknown codes are not guessed."""
    text = str(code or "").strip()
    if len(text) >= 2 and text[:2].isdigit():
        group = USE_GROUPS.get(text[:2])
        if group:
            return group
        return f"기타 용도(코드 {text})", "OTHER"
    return None, "UNKNOWN"


def floors(value: Any) -> int | None:
    """Positive integer floor count, or None when missing/invalid (0 is not a building height)."""
    try:
        number = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def aggregate_buildings(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group per-building rows into (grid, category) aggregates, the same shape SQL returns."""
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        grid_id = row.get("grid_id")
        if not grid_id:
            continue
        category = row.get("use_category") or "UNKNOWN"
        item = groups.setdefault((grid_id, category), {"grid_id": grid_id, "use_category": category, "count": 0, "footprint_m2": 0.0, "floors_known_count": 0, "floors_known_footprint_m2": 0.0, "floor_area_est_m2": 0.0, "floor_sum": 0, "max_floors": None})
        footprint = float(row.get("footprint_m2") or 0)
        levels = floors(row.get("above_floors"))
        item["count"] += 1
        item["footprint_m2"] += footprint
        if levels:
            item["floors_known_count"] += 1
            item["floors_known_footprint_m2"] += footprint
            item["floor_area_est_m2"] += footprint * levels
            item["floor_sum"] += levels
            item["max_floors"] = max(item["max_floors"] or 0, levels)
    return list(groups.values())


def summarize_grid_buildings(rows: Iterable[dict[str, Any]], requested: dict[str, str] | None = None, grid_area_m2: float = GRID_AREA_M2) -> dict[str, dict[str, Any]]:
    """Per-grid indicators from per-building rows (see ``summarize_grid_aggregates``)."""
    return summarize_grid_aggregates(aggregate_buildings(rows), requested, grid_area_m2)


def summarize_grid_aggregates(aggregates: Iterable[dict[str, Any]], requested: dict[str, str] | None = None, grid_area_m2: float = GRID_AREA_M2) -> dict[str, dict[str, Any]]:
    """Per-grid building indicators.

    ``aggregates``: per (grid_id, use_category) sums — count, footprint_m2, floors_known_count,
    floors_known_footprint_m2, floor_area_est_m2 (footprint × above-ground floors), floor_sum, max_floors.
    ``requested``: grid_id -> coverage status for grids actually requested from the provider. A
    requested grid without buildings gets zeros; a grid that was never requested is absent (missing).

    Buildings are assigned to the grid containing their representative point. Every ratio keeps its
    numerator and denominator so the UI can state them explicitly.
    """
    summary: dict[str, dict[str, Any]] = {grid_id: _empty(status) for grid_id, status in (requested or {}).items()}
    for row in aggregates:
        grid_id = row.get("grid_id")
        if not grid_id:
            continue
        item = summary.setdefault(grid_id, _empty("SUCCESS"))
        category = row.get("use_category") or "UNKNOWN"
        footprint = float(row.get("footprint_m2") or 0)
        item["building_count"] += int(row.get("count") or 0)
        item["footprint_m2"] += footprint
        item["category_count"][category] = item["category_count"].get(category, 0) + int(row.get("count") or 0)
        item["category_footprint_m2"][category] = item["category_footprint_m2"].get(category, 0.0) + footprint
        item["floors_known_count"] += int(row.get("floors_known_count") or 0)
        item["floors_known_footprint_m2"] += float(row.get("floors_known_footprint_m2") or 0)
        item["floor_area_est_m2"] += float(row.get("floor_area_est_m2") or 0)
        item["_floor_sum"] += int(row.get("floor_sum") or 0)
        if row.get("max_floors"):
            item["max_floors"] = max(item["max_floors"] or 0, int(row["max_floors"]))
    for item in summary.values():
        count, footprint = item["building_count"], item["footprint_m2"]
        item["grid_area_m2"] = grid_area_m2
        item["coverage_pct"] = round(footprint / grid_area_m2 * 100, 2)
        item["density_per_km2"] = round(count / (grid_area_m2 / 1_000_000), 1)
        item["floors_known_pct"] = round(item["floors_known_count"] / count * 100, 1) if count else None
        item["avg_floors"] = round(item["_floor_sum"] / item["floors_known_count"], 1) if item["floors_known_count"] else None
        # Gross floor area estimate = footprint × above-ground floors, only for buildings with a floor count.
        item["floor_area_est_m2"] = round(item["floor_area_est_m2"], 1) if item["floors_known_count"] else None
        item["far_est_pct"] = round(item["floor_area_est_m2"] / grid_area_m2 * 100, 2) if item["floor_area_est_m2"] is not None else None
        item["category_share_pct"] = {key: round(value / footprint * 100, 1) for key, value in item["category_footprint_m2"].items()} if footprint else {}
        item["residential_share_pct"] = item["category_share_pct"].get("RESIDENTIAL", 0.0) if footprint else None
        item["dominant_use"] = max(item["category_footprint_m2"], key=item["category_footprint_m2"].get) if item["category_footprint_m2"] else None
        item["footprint_m2"] = round(footprint, 1)
        item["floors_known_footprint_m2"] = round(item["floors_known_footprint_m2"], 1)
        item["category_footprint_m2"] = {key: round(value, 1) for key, value in item["category_footprint_m2"].items()}
        del item["_floor_sum"]
    return summary


def _empty(status: str) -> dict[str, Any]:
    return {
        "status": status, "building_count": 0, "footprint_m2": 0.0, "floors_known_count": 0,
        "floors_known_footprint_m2": 0.0, "floor_area_est_m2": 0.0, "max_floors": None, "_floor_sum": 0,
        "category_count": {}, "category_footprint_m2": {},
    }
