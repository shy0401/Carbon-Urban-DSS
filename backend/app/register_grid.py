"""Per-grid building stock from the 건축물대장 표제부 (official, one row per building).

The VWorld road-address building layer has outlines and floor counts but no use code, so use
mix and floor area come from the register once it is collected and linked to grids:

* gross floor area (연면적) and FAR floor area (용적률산정연면적) sums per grid;
* grid FAR approximation = Σ 용적률산정연면적 ÷ 250,000 m² (grid area, not the legal site area);
* use mix by 연면적 over the buildings whose main use is known;
* share of floor area approved before 2000 (older stock, retrofit candidates);
* energy-efficiency grade coverage.

Buildings without a linked grid are not guessed into one. A blank value stays missing (never 0).
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

GRID_AREA_M2 = 250_000.0
_CACHE: dict[int, dict[str, dict[str, Any]]] = {}


def summarize(rows: list[dict[str, Any]], grid_area_m2: float = GRID_AREA_M2) -> dict[str, dict[str, Any]]:
    """rows: {grid_id, use, gfa, far_gfa, approval_year, energy_grade}."""
    from .area import register_use_group
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        grid_id = row.get("grid_id")
        if not grid_id:
            continue
        item = out.setdefault(grid_id, {"buildings": 0, "gfa_m2": 0.0, "gfa_known": 0, "far_gfa_m2": 0.0, "far_known": 0,
                                        "use_gfa_m2": {}, "old_gfa_m2": 0.0, "dated_gfa_m2": 0.0, "graded": 0})
        item["buildings"] += 1
        gfa = row.get("gfa")
        if isinstance(gfa, (int, float)) and gfa > 0:
            item["gfa_m2"] += gfa
            item["gfa_known"] += 1
            if row.get("use"):
                group = register_use_group(row["use"])
                item["use_gfa_m2"][group] = item["use_gfa_m2"].get(group, 0.0) + gfa
            year = row.get("approval_year")
            if year:
                item["dated_gfa_m2"] += gfa
                if year < 2000:
                    item["old_gfa_m2"] += gfa
        far = row.get("far_gfa")
        if isinstance(far, (int, float)) and far > 0:
            item["far_gfa_m2"] += far
            item["far_known"] += 1
        if row.get("energy_grade"):
            item["graded"] += 1
    for item in out.values():
        use = item["use_gfa_m2"]
        known = sum(use.values())
        item["residential_gfa_pct"] = round(use.get("주거", 0.0) / known * 100, 1) if known else None
        item["use_gfa_pct"] = {k: round(v / known * 100, 1) for k, v in sorted(use.items(), key=lambda kv: -kv[1])} if known else {}
        item["dominant_use"] = max(use, key=use.get) if use else None
        item["far_pct"] = round(item["far_gfa_m2"] / grid_area_m2 * 100, 1) if item["far_known"] else None
        item["old_gfa_pct"] = round(item["old_gfa_m2"] / item["dated_gfa_m2"] * 100, 1) if item["dated_gfa_m2"] else None
        item["gfa_m2"] = round(item["gfa_m2"], 1) if item["gfa_known"] else None
        item["far_gfa_m2"] = round(item["far_gfa_m2"], 1) if item["far_known"] else None
        item["use_gfa_m2"] = {k: round(v, 1) for k, v in use.items()}
        del item["old_gfa_m2"], item["dated_gfa_m2"]
    return out


def grid_register_summary(db: Any) -> dict[str, dict[str, Any]]:
    """Cached per row count (the register changes only when it is collected again)."""
    try:
        from .official import BuildingRegister
        count = db.scalar(select(func.count()).select_from(BuildingRegister).where(BuildingRegister.grid_id.is_not(None))) or 0
    except Exception:  # noqa: BLE001 - table not migrated yet
        db.rollback()
        return {}
    if not count:
        return {}
    if count not in _CACHE:
        rows = []
        for grid_id, attrs, year in db.execute(select(BuildingRegister.grid_id, BuildingRegister.attributes, BuildingRegister.approval_year).where(BuildingRegister.grid_id.is_not(None))):
            attrs = attrs or {}
            rows.append({"grid_id": grid_id, "use": attrs.get("building_use"), "gfa": attrs.get("gross_floor_area_m2"),
                         "far_gfa": attrs.get("far_assessment_floor_area_m2"), "approval_year": year, "energy_grade": attrs.get("energy_grade")})
        _CACHE.clear()
        _CACHE[count] = summarize(rows)
    return _CACHE[count]


def map_properties(summary: dict[str, Any] | None) -> dict[str, Any]:
    if not summary:
        return {"reg_buildings": None, "reg_gfa_m2": None, "reg_far_pct": None, "reg_residential_gfa_pct": None,
                "reg_old_gfa_pct": None, "reg_dominant_use": None, "reg_use_gfa_pct": None}
    return {"reg_buildings": summary["buildings"], "reg_gfa_m2": summary["gfa_m2"], "reg_far_pct": summary["far_pct"],
            "reg_residential_gfa_pct": summary["residential_gfa_pct"], "reg_old_gfa_pct": summary["old_gfa_pct"],
            "reg_dominant_use": summary["dominant_use"], "reg_use_gfa_pct": summary["use_gfa_pct"]}
