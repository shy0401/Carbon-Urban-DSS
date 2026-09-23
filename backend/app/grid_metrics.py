"""Per-grid energy intensities from observed parcels only (pure functions).

An intensity is reported only for parcels observed in all 12 months of the year, and its
denominator (floor area, households) comes from the same parcels. Grid totals of partially
observed parcels are never divided by the area of the whole grid.
"""
from __future__ import annotations

from typing import Any, Iterable

MONTHS_PER_YEAR = 12
# Plausible K-apt gross floor area (연면적, incl. common areas and underground parking) per household.
# Outside this range the published value is a data-entry error (e.g. 1,261,967 m² per household).
MIN_GFA_PER_HOUSEHOLD = 20.0
MAX_GFA_PER_HOUSEHOLD = 400.0


def floor_area_status(gross_floor_area: float | None, households: int | None, management_area: float | None = None) -> tuple[str, str | None]:
    """('OK' | 'MISSING' | 'IMPLAUSIBLE', reason) for a complex's published gross floor area."""
    if not gross_floor_area or gross_floor_area <= 0:
        return "MISSING", "연면적 없음(0 또는 공란)"
    if management_area and gross_floor_area < management_area:
        return "IMPLAUSIBLE", f"연면적 {gross_floor_area:,.0f}m²가 관리비부과면적 {management_area:,.0f}m²보다 작음"
    if households and households > 0:
        per = gross_floor_area / households
        if per < MIN_GFA_PER_HOUSEHOLD or per > MAX_GFA_PER_HOUSEHOLD:
            return "IMPLAUSIBLE", f"세대당 연면적 {per:,.0f}m² (허용 {MIN_GFA_PER_HOUSEHOLD:.0f}~{MAX_GFA_PER_HOUSEHOLD:.0f}m²)"
    return "OK", None


def grid_energy_intensity(rows: Iterable[dict[str, Any]], households_by_code: dict[str, int | None] | None = None, area_by_code: dict[str, float | None] | None = None) -> dict[str, dict[str, dict[str, Any]]]:
    """Return {grid_id: {energy_type: intensity}}.

    ``rows``: observations with grid_id, energy_type, use_ym, usage_kwh, kapt_code and
    matched_gross_floor_area_m2 (from the parcel↔K-apt match). ``area_by_code`` (validated with
    ``floor_area_status``; None for an implausible value) overrides the row value when given.
    Result per grid/energy type: complete_parcels, observed_parcels, kwh (12-month sum of complete
    parcels), area_m2, households, kwh_per_m2, kwh_per_household (both per year).
    """
    households_by_code = households_by_code or {}
    parcels: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        grid_id, energy_type, code = row.get("grid_id"), row.get("energy_type"), row.get("kapt_code")
        if not grid_id or not energy_type or not code:
            continue
        area = area_by_code.get(code) if area_by_code is not None else row.get("matched_gross_floor_area_m2")
        item = parcels.setdefault((grid_id, energy_type, code), {"months": {}, "area": area})
        item["months"][row.get("use_ym")] = row.get("usage_kwh")
    result: dict[str, dict[str, dict[str, Any]]] = {}
    for (grid_id, energy_type, code), item in parcels.items():
        target = result.setdefault(grid_id, {}).setdefault(energy_type, {"observed_parcels": 0, "complete_parcels": 0, "kwh": 0.0, "area_m2": 0.0, "area_parcels": 0, "kwh_with_area": 0.0, "households": 0, "household_parcels": 0, "kwh_with_households": 0.0})
        target["observed_parcels"] += 1
        values = item["months"]
        if len(values) < MONTHS_PER_YEAR or any(value is None for value in values.values()):
            continue
        annual = float(sum(values.values()))
        target["complete_parcels"] += 1
        target["kwh"] += annual
        area = item["area"]
        if isinstance(area, (int, float)) and area > 0:
            target["area_m2"] += float(area)
            target["area_parcels"] += 1
            target["kwh_with_area"] += annual
        households = households_by_code.get(code)
        if households and households > 0:
            target["households"] += int(households)
            target["household_parcels"] += 1
            target["kwh_with_households"] += annual
    for by_type in result.values():
        for target in by_type.values():
            complete = target["complete_parcels"]
            # Each ratio uses only the complete parcels that have its denominator, and its numerator
            # is the energy of exactly those parcels (area_parcels / household_parcels say how many).
            target["kwh"] = round(target["kwh"], 1) if complete else None
            target["kwh_per_m2"] = round(target["kwh_with_area"] / target["area_m2"], 2) if target["area_parcels"] else None
            target["kwh_per_household"] = round(target["kwh_with_households"] / target["households"], 1) if target["household_parcels"] else None
            target["area_m2"] = round(target["area_m2"], 1) if target["area_parcels"] else None
            target["households"] = target["households"] if target["household_parcels"] else None
            del target["kwh_with_area"], target["kwh_with_households"]
    return result


def consistent_baseline(rows: Iterable[dict[str, Any]], months: list[str], area_by_code: dict[str, float | None] | None = None) -> dict[str, Any] | None:
    """Monthly baseline and floor area for one fixed set of parcels.

    A scenario scales observed energy by (planned floor area / baseline floor area), so the
    numerator and denominator must describe the same buildings in every month. The set is the
    parcels (K-apt codes) observed in all ``months`` for electricity AND gas; if none has both,
    the parcels complete for electricity alone (gas then stays null). Parcels without a matched
    floor area are left out. Returns None when no parcel qualifies.
    """
    parcels: dict[str, dict[str, Any]] = {}
    for row in rows:
        code = row.get("kapt_code")
        if not code or row.get("usage_kwh") is None or row.get("use_ym") not in months:
            continue
        area = area_by_code.get(code) if area_by_code is not None else row.get("matched_gross_floor_area_m2")
        item = parcels.setdefault(code, {"area": area, "ELECTRICITY": {}, "GAS": {}})
        if row.get("energy_type") in ("ELECTRICITY", "GAS"):
            item[row["energy_type"]][row["use_ym"]] = float(row["usage_kwh"])
    with_area = {code: item for code, item in parcels.items() if isinstance(item["area"], (int, float)) and item["area"] > 0}
    need = len(months)
    both = sorted(code for code, item in with_area.items() if len(item["ELECTRICITY"]) == need and len(item["GAS"]) == need)
    electricity_only = sorted(code for code, item in with_area.items() if len(item["ELECTRICITY"]) == need)
    chosen, types = (both, ("ELECTRICITY", "GAS")) if both else (electricity_only, ("ELECTRICITY",))
    if not chosen:
        return None
    monthly = []
    for month in months:
        record: dict[str, Any] = {"use_ym": month, "electricity_kwh": None, "gas_kwh": None}
        for energy_type in types:
            record["electricity_kwh" if energy_type == "ELECTRICITY" else "gas_kwh"] = sum(with_area[code][energy_type][month] for code in chosen)
        monthly.append(record)
    return {
        "parcels": chosen, "energy_types": list(types), "monthly": monthly,
        "area_m2": round(sum(float(with_area[code]["area"]) for code in chosen), 2),
        "excluded_parcels": sorted(set(parcels) - set(chosen)),
    }


def validated_complex_areas(complexes: Iterable[Any]) -> tuple[dict[str, float | None], dict[str, dict[str, Any]]]:
    """({kapt_code: usable gross floor area or None}, {kapt_code: issue}) for K-apt complexes."""
    areas: dict[str, float | None] = {}
    issues: dict[str, dict[str, Any]] = {}
    for row in complexes:
        status, reason = floor_area_status(row.gross_floor_area_m2, row.households, getattr(row, "management_area_m2", None))
        areas[row.kapt_code] = float(row.gross_floor_area_m2) if status == "OK" else None
        if status != "OK":
            issues[row.kapt_code] = {"name": row.name, "status": status, "reason": reason}
    return areas, issues
