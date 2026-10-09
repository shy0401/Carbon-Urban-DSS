"""Area analysis: pick any place → yearly history, development events, before/after, effort.

An *area* is a 행정동 (SGIS boundary), one 500m grid, a circle around a clicked point,
every grid whose dominant 용도지역 is a category (e.g. 상업지역), or a drawn polygon.

Rules (same as the rest of the DSS):
* Observed energy only. An annual value uses parcels with all 12 months observed; a
  partial year is reported as coverage, never scaled up. Missing stays null, never 0.
* 행정동 통계는 격자·반경으로 배분하지 않는다: for a non-행정동 area the overlapping
  dongs are listed as reference values, not allocated.
* Development events come from 사용승인일 (K-apt; 건축물대장 when collected).
* Carbon for past years uses one fixed factor (the latest registered one) so that a
  before/after difference reflects energy use, not grid decarbonisation. The factor and
  that choice are returned with every result.
* The core functions are pure (plain dicts in, dicts out) so they are tested without a DB.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Iterable, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .grid_metrics import annual_complete, electricity_plausibility

ZONE_LABEL = {"RESIDENTIAL": "주거지역", "COMMERCIAL": "상업지역", "INDUSTRIAL": "공업지역", "GREEN": "녹지지역", "OTHER": "관리·농림·기타"}
EARTH_RADIUS_M = 6_371_008.8


# --------------------------------------------------------------------------- geometry
def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def _polygons(geometry: dict[str, Any] | None) -> list[list[list[list[float]]]]:
    """Polygon / MultiPolygon GeoJSON → list of polygons, each a list of rings (outer first)."""
    if not geometry:
        return []
    kind, coords = geometry.get("type"), geometry.get("coordinates") or []
    if kind == "Polygon":
        return [coords] if coords else []
    if kind == "MultiPolygon":
        return [poly for poly in coords if poly]
    return []


def _in_ring(x: float, y: float, ring: list[list[float]]) -> bool:
    inside = False
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
        if (y1 > y) != (y2 > y):
            cross = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < cross:
                inside = not inside
    return inside


def point_in_geometry(x: float, y: float, geometry: dict[str, Any] | None) -> bool:
    """Ray casting with holes. Pure Python so the engine runs without GEOS."""
    for polygon in _polygons(geometry):
        if _in_ring(x, y, polygon[0]) and not any(_in_ring(x, y, hole) for hole in polygon[1:]):
            return True
    return False


def _centroid(geometry: dict[str, Any] | None) -> tuple[float, float] | None:
    """Area-weighted centroid of the outer rings (shoelace formula)."""
    sx = sy = total = 0.0
    for polygon in _polygons(geometry):
        ring = polygon[0]
        a = cx = cy = 0.0
        for i in range(len(ring) - 1):
            x1, y1, x2, y2 = ring[i][0], ring[i][1], ring[i + 1][0], ring[i + 1][1]
            cross = x1 * y2 - x2 * y1
            a += cross
            cx += (x1 + x2) * cross
            cy += (y1 + y2) * cross
        if a:
            sx += cx / 3
            sy += cy / 3
            total += a
    if not total:
        return None
    return (sx / total, sy / total)


def geometries_overlap(a: dict[str, Any] | None, b: dict[str, Any] | None) -> bool:
    """Approximate intersection test (a vertex of one inside the other, or centroids inside)."""
    for first, second in ((a, b), (b, a)):
        for polygon in _polygons(first):
            if any(point_in_geometry(p[0], p[1], second) for p in polygon[0]):
                return True
        c = _centroid(first)
        if c and point_in_geometry(c[0], c[1], second):
            return True
    return False


def circle_geometry(lon: float, lat: float, radius_m: float, steps: int = 64) -> dict[str, Any]:
    """Polygon approximating a circle on the sphere (for display and the report)."""
    coords = []
    for i in range(steps + 1):
        bearing = 2 * math.pi * i / steps
        d = radius_m / EARTH_RADIUS_M
        p1, l1 = math.radians(lat), math.radians(lon)
        p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(bearing))
        l2 = l1 + math.atan2(math.sin(bearing) * math.sin(d) * math.cos(p1), math.cos(d) - math.sin(p1) * math.sin(p2))
        coords.append([round(math.degrees(l2), 6), round(math.degrees(p2), 6)])
    return {"type": "Polygon", "coordinates": [coords]}


def region_label(region: dict[str, Any] | None) -> str:
    """Name used in sentences for the region-wide intensity: '전주' for the original region, else the short name."""
    if not region or region.get("is_default", True):
        return "전주"
    return region.get("short_name") or region.get("name") or "지역"


def short_admin_name(name: str | None) -> str:
    """'전북특별자치도 전주시 덕진구 송천1동' → '덕진구 송천1동'."""
    parts = str(name or "").split()
    return " ".join(parts[-2:]) if len(parts) >= 2 else str(name or "")


def resolve_area(spec: dict[str, Any], grids: list[dict[str, Any]], complexes: list[dict[str, Any]],
                 admin: list[dict[str, Any]], zoning: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Members of an area.

    grids: {id, geometry (EPSG:4326 GeoJSON)}; complexes: {kapt_code, lon, lat, grid_id};
    admin: GeoJSON features with adm_code/adm_name; zoning: {grid_id: {dominant_zone, ...}}.
    Grids join an area by centroid, complexes by their published point.
    """
    kind = spec.get("type")
    centroids = {g["id"]: _centroid(g.get("geometry")) for g in grids}
    geometry: dict[str, Any] | None = None
    grid_ids: set[str] = set()
    codes: set[str] = set()
    admin_codes: list[str] = []
    method = ""
    if kind == "admin":
        feature = next((f for f in admin if f["properties"].get("adm_code") == str(spec.get("code"))), None)
        if feature is None:
            raise ValueError("행정동을 찾을 수 없습니다")
        geometry = feature["geometry"]
        if not _polygons(geometry):
            raise ValueError("행정동 경계가 올바르지 않습니다")
        grid_ids = {gid for gid, c in centroids.items() if c and point_in_geometry(c[0], c[1], geometry)}
        codes = {c["kapt_code"] for c in complexes if c.get("lon") is not None and point_in_geometry(c["lon"], c["lat"], geometry)}
        label = f'{short_admin_name(feature["properties"].get("adm_name"))} (행정동)'
        admin_codes = [feature["properties"]["adm_code"]]
        method = "행정동 경계 안에 중심점이 있는 격자, 공개 좌표가 경계 안인 단지"
    elif kind == "grid":
        gid = str(spec.get("grid_id") or "")
        grid = next((g for g in grids if g["id"] == gid), None)
        if grid is None:
            raise ValueError("격자를 찾을 수 없습니다")
        grid_ids = {gid}
        codes = {c["kapt_code"] for c in complexes if c.get("grid_id") == gid}
        geometry = grid.get("geometry")
        label = f"500m 격자 {gid}"
        method = "선택한 격자와 그 안에 공개 좌표가 있는 단지"
    elif kind == "circle":
        lon, lat, radius = float(spec["lon"]), float(spec["lat"]), float(spec.get("radius_m") or 1000)
        if not (100 <= radius <= 5000):
            raise ValueError("반경은 100~5,000m로 입력하세요")
        grid_ids = {gid for gid, c in centroids.items() if c and haversine_m(lon, lat, c[0], c[1]) <= radius}
        codes = {c["kapt_code"] for c in complexes if c.get("lon") is not None and haversine_m(lon, lat, c["lon"], c["lat"]) <= radius}
        geometry = circle_geometry(lon, lat, radius)
        label = f"반경 {radius:,.0f}m ({lat:.5f}, {lon:.5f})"
        method = "중심점 거리 기준 (격자는 중심점, 단지는 공개 좌표)"
    elif kind == "zone":
        category = str(spec.get("category") or "").upper()
        if category not in ZONE_LABEL:
            raise ValueError("용도지역 구분을 확인하세요")
        grid_ids = {gid for gid, z in zoning.items() if z.get("dominant_zone") == category}
        codes = {c["kapt_code"] for c in complexes if c.get("grid_id") in grid_ids}
        label = f"{ZONE_LABEL[category]}이 가장 넓은 격자 {len(grid_ids)}개"
        method = "VWorld 용도지역 면적이 가장 큰 구분이 선택한 용도지역인 격자"
    elif kind == "polygon":
        geometry = spec.get("geometry")
        if not _polygons(geometry):
            raise ValueError("다각형이 올바르지 않습니다")
        grid_ids = {gid for gid, c in centroids.items() if c and point_in_geometry(c[0], c[1], geometry)}
        codes = {c["kapt_code"] for c in complexes if c.get("lon") is not None and point_in_geometry(c["lon"], c["lat"], geometry)}
        label = str(spec.get("label") or "직접 그린 영역")
        method = "다각형 안에 중심점이 있는 격자, 공개 좌표가 안에 있는 단지"
    else:
        raise ValueError("지역 유형은 admin, grid, circle, zone, polygon 중 하나입니다")
    if kind == "admin":
        overlapping = [f for f in admin if f["properties"].get("adm_code") == str(spec.get("code"))]
    elif geometry is not None and kind != "grid":
        overlapping = [f for f in admin if geometries_overlap(f["geometry"], geometry)]
    else:
        member_points = [c for gid, c in centroids.items() if gid in grid_ids and c]
        overlapping = [f for f in admin if any(point_in_geometry(p[0], p[1], f["geometry"]) for p in member_points)]
    if kind != "admin":
        admin_codes = [f["properties"]["adm_code"] for f in overlapping]
    return {
        "type": kind, "label": label, "method": method, "geometry": geometry,
        "grid_ids": sorted(grid_ids), "complex_codes": sorted(codes),
        "admin_codes": admin_codes, "admin_exact": kind == "admin",
        "admin_names": {f["properties"]["adm_code"]: f["properties"].get("adm_name") for f in overlapping},
        "admin_labels": [short_admin_name(f["properties"].get("adm_name")) for f in overlapping],
    }


# --------------------------------------------------------------------------- history
def approval_year(value: Any) -> int | None:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if len(digits) >= 4 and 1900 < int(digits[:4]) < 2100:
        return int(digits[:4])
    return None


def floor_area_ok(gfa: float | None, households: int | None, management_area: float | None = None) -> bool:
    """Same plausibility rule as the grid intensity denominators (grid_metrics.floor_area_status)."""
    from .grid_metrics import floor_area_status
    return floor_area_status(gfa, households, management_area)[0] == "OK"


def yearly_energy(rows: Iterable[dict[str, Any]], area: dict[str, Any], complexes: dict[str, dict[str, Any]],
                  years: list[int], source: str | None = None) -> dict[int, dict[str, Any]]:
    """Annual observed energy of the area per year.

    rows: {use_ym 'YYYYMM', energy_type, usage_kwh, grid_id, kapt_code|None, parcel, source?}
    A row belongs to the area through its complex (point in area) or, without a complex,
    through its grid. Only parcels whose rows cover the whole year enter the annual sum (12 months, or
    for gas a summer month billed with the next one: ``grid_metrics.annual_complete``).
    ``source`` ('KAPT' | 'HUB') keeps one provider only (rows without a source always count).
    """
    grid_ids, codes = set(area["grid_ids"]), set(area["complex_codes"])
    wanted = {str(y) for y in years}
    months: dict[tuple[str, str, int], dict[str, float]] = defaultdict(dict)
    parcel_code: dict[str, str | None] = {}
    for row in rows:
        ym, value = str(row.get("use_ym") or ""), row.get("usage_kwh")
        if len(ym) != 6 or ym[:4] not in wanted or value is None:
            continue
        if source and row.get("source") not in (None, source):
            continue
        code = row.get("kapt_code")
        inside = code in codes if code else row.get("grid_id") in grid_ids
        if not inside:
            continue
        parcel = str(row.get("parcel") or code or row.get("grid_id"))
        parcel_code[parcel] = code
        months[(parcel, str(row["energy_type"]), int(ym[:4]))][ym] = float(value)
    result: dict[int, dict[str, Any]] = {}
    for year in years:
        entry: dict[str, Any] = {"year": year}
        for etype, key in (("ELECTRICITY", "electricity"), ("GAS", "gas")):
            parcels = {p: m for (p, t, y), m in months.items() if t == etype and y == year}
            complete = {p: m for p, m in parcels.items() if annual_complete(etype, m)}
            suspect = []
            if etype == "ELECTRICITY":
                # Partial meters (common areas only) or meters with other buildings: kept out of totals.
                for parcel, m in list(complete.items()):
                    info = complexes.get(parcel_code.get(parcel) or "")
                    if info and electricity_plausibility(sum(m.values()), info.get("households"))[0] == "SUSPECT":
                        suspect.append(parcel)
                        del complete[parcel]
            total = sum(sum(m.values()) for m in complete.values()) if complete else None
            by_cohort: dict[str, float] = defaultdict(float)
            by_complex: dict[str, float] = {}
            area_m2 = 0.0
            area_kwh = 0.0
            households = 0
            household_kwh = 0.0
            for parcel, m in complete.items():
                code = parcel_code.get(parcel)
                info = complexes.get(code) if code else None
                cohort = str(info["approval_year"]) if info and info.get("approval_year") else "미상"
                by_cohort[cohort] += sum(m.values())
                if code:
                    by_complex[code] = by_complex.get(code, 0.0) + sum(m.values())
                if info and info.get("floor_area_ok"):
                    area_m2 += info["gfa"]
                    area_kwh += sum(m.values())
                if info and info.get("households"):
                    households += int(info["households"])
                    household_kwh += sum(m.values())
            entry[key] = {
                "kwh": round(total, 1) if total is not None else None,
                "observed_parcels": len(parcels), "complete_parcels": len(complete),
                "partial_parcels": len(parcels) - len(complete) - len(suspect),
                "suspect_parcels": len(suspect),
                "months_max": max((len(m) for m in parcels.values()), default=0),
                "by_cohort": {k: round(v, 1) for k, v in sorted(by_cohort.items())},
                "by_complex": {k: round(v, 1) for k, v in sorted(by_complex.items())},
                "intensity_kwh_per_m2": round(area_kwh / area_m2, 6) if area_m2 else None,
                "intensity_area_m2": round(area_m2, 1) if area_m2 else None,
                "kwh_per_household": round(household_kwh / households, 1) if households else None,
                "households": households or None,
            }
        result[year] = entry
    return result


def yearly_weather(rows: Iterable[dict[str, Any]], years: list[int]) -> dict[int, dict[str, Any]]:
    by_year: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        ym = str(row.get("use_ym") or "")
        if len(ym) == 6:
            by_year[int(ym[:4])].append(row)
    out = {}
    for year in years:
        months = by_year.get(year, [])
        valid = [m for m in months if m.get("hdd") is not None and m.get("cdd") is not None]
        complete = len(valid) == 12
        out[year] = {
            "year": year, "months": len(valid), "complete": complete,
            "hdd": round(sum(m["hdd"] for m in valid), 1) if complete else None,
            "cdd": round(sum(m["cdd"] for m in valid), 1) if complete else None,
            "mean_temperature": round(sum(m["mean_temperature"] for m in valid if m.get("mean_temperature") is not None) / len(valid), 2) if complete else None,
            "sources": sorted({str(m.get("source_type")) for m in months if m.get("source_type")}),
        }
    return out


def yearly_population(pop: Iterable[dict[str, Any]], households: Iterable[dict[str, Any]], area: dict[str, Any],
                      years: list[int]) -> dict[int, dict[str, Any]]:
    """행정동 population/households per year. Matched by code, then by name (codes change over years)."""
    codes = set(area["admin_codes"])
    names = {n for c, n in (area.get("admin_names") or {}).items() if c in codes and n}
    def pick(rows: Iterable[dict[str, Any]]) -> dict[int, dict[str, Any]]:
        by_year: dict[int, dict[str, Any]] = {}
        for row in rows:
            if str(row.get("adm_code")) not in codes and row.get("adm_name") not in names:
                continue
            if len(str(row.get("adm_code"))) <= 5:  # 구 합계 행 제외
                continue
            year = int(row["reference_year"])
            bucket = by_year.setdefault(year, {"value": 0, "dongs": 0, "suppressed": 0})
            if row.get("value") is None:
                bucket["suppressed"] += 1
            else:
                bucket["value"] += int(row["value"])
                bucket["dongs"] += 1
        return by_year
    p, h = pick(pop), pick(households)
    out = {}
    for year in years:
        pe, he = p.get(year), h.get(year)
        out[year] = {
            "year": year,
            "population": pe["value"] if pe and pe["dongs"] and not pe["suppressed"] else None,
            "households": he["value"] if he and he["dongs"] and not he["suppressed"] else None,
            "dongs": pe["dongs"] if pe else 0,
            "basis": "행정동 값" if area.get("admin_exact") else "겹치는 행정동 합계(참고, 배분 아님)",
        }
    return out


def development_events(area: dict[str, Any], complexes: dict[str, dict[str, Any]], years: list[int]) -> dict[int, dict[str, Any]]:
    codes = set(area["complex_codes"])
    out = {y: {"year": y, "complexes": 0, "households": 0, "gfa_m2": 0.0, "names": []} for y in years}
    for code in codes:
        info = complexes.get(code)
        year = info.get("approval_year") if info else None
        if year in out:
            item = out[year]
            item["complexes"] += 1
            item["households"] += int(info.get("households") or 0)
            item["gfa_m2"] += float(info["gfa"]) if info.get("floor_area_ok") else 0.0
            item["names"].append(info.get("name"))
    for item in out.values():
        item["gfa_m2"] = round(item["gfa_m2"], 1)
        item["names"] = sorted(n for n in item["names"] if n)
    return out


def _mean(values: list[float | None]) -> float | None:
    vals = [v for v in values if v is not None]
    return round(sum(vals) / len(vals), 1) if vals else None


def before_after(history: dict[str, Any], event_year: int | None = None, window: int = 3) -> dict[str, Any]:
    """Compare the area before and after one development year.

    existing = complexes approved before the event year; new = approved in the event year.
    before = event−window … event−1, after = event+1 … event+window (the event year itself is a
    transition year and is left out). Every mean uses only years with a complete value.
    """
    events = history["events"]
    candidates = [y for y, e in events.items() if e["complexes"]]
    if event_year is None:
        # Default: the year that added most households and still has a year on each side.
        years = history["years"]
        scored = [(events[y]["households"], y) for y in candidates if years[0] < y < years[-1]]
        event_year = max(scored)[1] if scored else (max(candidates) if candidates else None)
    if event_year is None:
        return {"available": False, "reason": "선택한 지역·기간에 사용승인(준공) 기록이 없습니다"}
    before_years = [y for y in range(event_year - window, event_year) if y in history["energy"]]
    after_years = [y for y in range(event_year + 1, event_year + window + 1) if y in history["energy"]]

    def cohort_sum(year: int, energy: str, pred) -> float | None:
        item = history["energy"][year][energy]
        if item["kwh"] is None:
            return None
        values = [v for k, v in item["by_cohort"].items() if pred(k)]
        return round(sum(values), 1) if values else None

    is_existing = lambda k: k.isdigit() and int(k) < event_year  # noqa: E731
    is_new = lambda k: k == str(event_year)  # noqa: E731
    approved = {c["kapt_code"]: c.get("approval_year") for c in history.get("complexes", [])}

    def same_complexes(energy: str) -> tuple[set[str], float | None, float | None]:
        """Existing complexes reported in every before and after year: the change of the same buildings only
        (a complex that starts or stops reporting K-apt would otherwise look like a change in use)."""
        # years without any observation are skipped (as in the totals); the complexes must be in every other year
        before = [y for y in before_years if history["energy"][y][energy].get("by_complex")]
        after = [y for y in after_years if history["energy"][y][energy].get("by_complex")]
        if not before or not after:
            return set(), None, None
        sets = [set(history["energy"][y][energy]["by_complex"]) for y in before + after]
        common = {c for c in set.intersection(*sets) if approved.get(c) and approved[c] < event_year}
        if not common:
            return set(), None, None
        mean_of = lambda ys: _mean([sum(history["energy"][y][energy]["by_complex"][c] for c in common) for y in ys])  # noqa: E731
        return common, mean_of(before), mean_of(after)
    result: dict[str, Any] = {"available": True, "event_year": event_year, "window": window,
                              "before_years": before_years, "after_years": after_years,
                              "event": events.get(event_year), "metrics": {}}
    # Which of those years actually have a 12-month total, and how many parcels stand behind each side:
    # a before-period with only a few complexes collected (e.g. 2018 K-apt partly collected) is not the same
    # population as the after-period, so the total change is then labelled as mixed with the coverage gap.
    elec_years = lambda ys: [y for y in ys if history["energy"][y]["electricity"]["kwh"] is not None]  # noqa: E731
    observed_before, observed_after = elec_years(before_years), elec_years(after_years)
    before_parcels = _mean([history["energy"][y]["electricity"]["complete_parcels"] for y in observed_before])
    after_existing = _mean([sum(1 for c in history["energy"][y]["electricity"].get("by_complex") or {} if approved.get(c) and approved[c] < event_year)
                            for y in observed_after]) if any(history["energy"][y]["electricity"].get("by_complex") for y in observed_after) else None
    result["coverage"] = {
        "observed_before_years": observed_before, "observed_after_years": observed_after,
        "before_parcels_mean": before_parcels, "after_existing_parcels_mean": after_existing,
        # comparable unless the before side observed clearly fewer parcels than the existing ones observed after
        "comparable": not (before_parcels is not None and after_existing and before_parcels < 0.8 * after_existing),
    }
    for energy in ("electricity", "gas"):
        before_total = _mean([history["energy"][y][energy]["kwh"] for y in before_years])
        after_total = _mean([history["energy"][y][energy]["kwh"] for y in after_years])
        common, before_existing, after_existing = same_complexes(energy)
        if not common and not any(history["energy"][y][energy].get("by_complex") for y in before_years + after_years):
            # rows without complex codes (older inputs): fall back to the approval cohorts
            before_existing = _mean([cohort_sum(y, energy, is_existing) for y in before_years])
            after_existing = _mean([cohort_sum(y, energy, is_existing) for y in after_years])
        after_new = _mean([cohort_sum(y, energy, is_new) for y in after_years])
        result["metrics"][energy] = {
            "before_total_kwh": before_total, "after_total_kwh": after_total,
            "total_change_kwh": round(after_total - before_total, 1) if before_total is not None and after_total is not None else None,
            "total_change_pct": round((after_total - before_total) / before_total * 100, 1) if before_total and after_total is not None else None,
            "existing_before_kwh": before_existing, "existing_after_kwh": after_existing,
            "existing_change_pct": round((after_existing - before_existing) / before_existing * 100, 1) if before_existing and after_existing is not None else None,
            "existing_complexes": len(common),
            "new_development_kwh": after_new,
            "new_share_pct": round(after_new / after_total * 100, 1) if after_new is not None and after_total else None,
        }
    factor = history.get("factor", {}).get("electricity")
    elec = result["metrics"]["electricity"]
    result["metrics"]["electricity_carbon"] = {
        k.replace("_kwh", "_kgco2eq"): (round(v * factor, 1) if v is not None and factor else None)
        for k, v in elec.items() if k.endswith("_kwh")
    }
    est = lambda y: history["energy"][y].get("estimated", {}).get("kwh")  # noqa: E731
    before_est = _mean([est(y) for y in before_years])
    after_est = _mean([est(y) for y in after_years])
    stock_before = history.get("stock", {}).get(event_year - 1, {})
    stock_after = history.get("stock", {}).get(event_year, {})
    result["metrics"]["estimated"] = {
        "before_kwh": before_est, "after_kwh": after_est,
        "change_kwh": round(after_est - before_est, 1) if before_est is not None and after_est is not None else None,
        "change_pct": round((after_est - before_est) / before_est * 100, 1) if before_est and after_est is not None else None,
        "added_gfa_m2": round(stock_after.get("gfa_m2", 0) - stock_before.get("gfa_m2", 0), 1) if stock_after else None,
        "data_class": "ESTIMATED",
    }
    # The event alone (other years' developments excluded): stock at the end of the previous year vs. + this year's floor area.
    city = history.get("city_intensity")
    prior_gfa = stock_before.get("gfa_m2") if stock_before else None
    added = result["metrics"]["estimated"]["added_gfa_m2"]
    if city and prior_gfa and added is not None:
        result["metrics"]["estimated"].update({
            "event_added_kwh": round(added * city["kwh_per_m2"], 1),
            "event_change_pct": round(added / prior_gfa * 100, 1),
            "prior_gfa_m2": prior_gfa,
        })
    result["weather"] = {
        "before_hdd": _mean([history["weather"][y]["hdd"] for y in before_years if y in history["weather"]]),
        "after_hdd": _mean([history["weather"][y]["hdd"] for y in after_years if y in history["weather"]]),
        "before_cdd": _mean([history["weather"][y]["cdd"] for y in before_years if y in history["weather"]]),
        "after_cdd": _mean([history["weather"][y]["cdd"] for y in after_years if y in history["weather"]]),
    }
    result["population"] = {
        "before": _mean([history["population"][y]["population"] for y in before_years if y in history["population"]]),
        "after": _mean([history["population"][y]["population"] for y in after_years if y in history["population"]]),
        "basis": next(iter(history["population"].values()), {}).get("basis"),
    }
    gaps = []
    if not before_years:
        gaps.append("개발 이전 연도가 분석 기간에 없습니다")
    if not after_years:
        gaps.append("개발 이후 연도가 분석 기간에 없습니다")
    if elec["before_total_kwh"] is None or elec["after_total_kwh"] is None:
        gaps.append("전후 기간에 12개월이 모두 관측된 전력 자료가 부족합니다 (과거 수집 필요)")
    result["gaps"] = gaps
    return result


EFFORT_BASIS = {"apartments": "공동주택(K-apt 관리비 전력)", "buildings": "건물 전체(건축HUB 계측 지번, 상가·업무 포함)"}


def effort(history: dict[str, Any], plan: dict[str, Any], target_pct: float, pv_yield_kwh_per_kw: float | None = None,
           basis: str = "apartments", measures: dict[str, Any] | None = None) -> dict[str, Any]:
    """The reduction effort on the requested basis; when that basis has nothing to stand on, the other one.

    A 면 without any K-apt complex (완주 7 of 13, 2026-10-10 audit) still has metered buildings, so the screen
    answers on the building-wide basis instead of "no basis" and says so (``fallback_from``, fact ``effort_fallback``).
    ``measures`` (new-building / existing-building efficiency %, PV kW) adds the combined reduction of those measures
    against the requirement (``mix``): the way a 도시·군기본계획 checks a target by summing each measure's reduction.
    """
    if basis not in EFFORT_BASIS:
        raise ValueError("기준 건물은 apartments 또는 buildings 입니다")
    result = _effort_on(history, plan, target_pct, pv_yield_kwh_per_kw, basis)
    if not result.get("available"):
        other = "buildings" if basis == "apartments" else "apartments"
        alternative = _effort_on(history, plan, target_pct, pv_yield_kwh_per_kw, other)
        if alternative.get("available"):
            alternative["fallback_from"] = basis
            alternative["fallback_reason"] = result.get("reason")
            result = alternative
    if result.get("available") and measures:
        result["mix"] = measure_mix(result, measures)
    return result


def measure_mix(result: dict[str, Any], measures: dict[str, Any]) -> dict[str, Any]:
    """Reduction of a set of measures together, against the requirement (all in the result's own kWh and factor).

    new buildings:      planned new load × new_efficiency_pct
    existing buildings: (baseline − demolished load) × existing_efficiency_pct
    solar:              pv_kw × kWh per kW (the user's yield or the regional estimate; none → not counted)
    """
    n = float(measures.get("new_efficiency_pct") or 0)
    x = float(measures.get("existing_efficiency_pct") or 0)
    k = float(measures.get("pv_kw") or 0)
    if not (0 <= n <= 100 and 0 <= x <= 100):
        raise ValueError("감축 수단의 효율 개선율은 0~100% 입니다")
    if k < 0:
        raise ValueError("태양광 용량은 0 이상입니다")
    factor = float(result["factor_kgco2eq_per_kwh"])
    removed_kwh = float(result["intensity_kwh_per_m2"]) * float(result.get("removed_floor_area_m2") or 0)
    existing = max(float(result["baseline_kwh"]) - removed_kwh, 0.0)
    pv_yield = (result.get("pv_yield") or {}).get("kwh_per_kw")
    new_kwh = float(result["new_load_kwh"]) * n / 100
    existing_kwh = existing * x / 100
    pv_kwh = k * float(pv_yield) if k and pv_yield else (0.0 if not k else None)
    total_kwh = new_kwh + existing_kwh + (pv_kwh or 0.0)
    total_c = total_kwh * factor
    need_c = float(result["required_reduction_kgco2eq"])
    return {
        "new_efficiency_pct": round(n, 1), "existing_efficiency_pct": round(x, 1), "pv_kw": round(k, 1),
        "new_kwh": round(new_kwh, 1), "existing_kwh": round(existing_kwh, 1), "pv_kwh": round(pv_kwh, 1) if pv_kwh is not None else None,
        "pv_counted": pv_kwh is not None, "total_kwh": round(total_kwh, 1), "total_kgco2eq": round(total_c, 1),
        "required_kgco2eq": round(need_c, 1), "gap_kgco2eq": round(need_c - total_c, 1), "met": need_c - total_c <= 0,
        "share_pct": round(total_c / need_c * 100, 1) if need_c > 0 else None,
        "basis": "신축 부하 × 신축 절감률 + (기준 부하 − 철거 부하) × 기존 절감률 + 태양광 kW × kW당 연 발전량, 모두 전력 배출계수로 환산",
    }


def _effort_on(history: dict[str, Any], plan: dict[str, Any], target_pct: float, pv_yield_kwh_per_kw: float | None = None,
               basis: str = "apartments") -> dict[str, Any]:
    """How much reduction a future development needs to meet a target.

    baseline = latest year with a complete observed electricity total in the area;
    new load  = planned added floor area × the area's observed electricity intensity;
    target    = baseline carbon × (1 − target %).
    Returns the required efficiency for new buildings only, for all buildings, and the
    electricity that on-site generation would have to offset. Electricity only unless a
    gas factor is registered.

    basis "apartments": the K-apt apartment series (one source across years).
    basis "buildings":  every metered parcel of the area's grids (건축HUB, 2020~ where collected) — shops, offices and schools
    included, so a commercial area is measured against the buildings that are actually there.
    """
    if not (0 <= target_pct <= 100):
        raise ValueError("목표 감축률은 0~100% 입니다")
    pv = pv_basis(history, pv_yield_kwh_per_kw)
    pv_yield_kwh_per_kw = pv["kwh_per_kw"] if pv else None
    if basis not in EFFORT_BASIS:
        raise ValueError("기준 건물은 apartments 또는 buildings 입니다")
    factor = history.get("factor", {}).get("electricity")
    if not factor:
        return {"available": False, "reason": "전력 배출계수가 등록되어 있지 않습니다", "basis": basis, "basis_label": EFFORT_BASIS[basis]}
    if basis == "buildings":
        years = (history.get("building_energy") or {}).get("years") or {}
        base_year = next((y for y in sorted(years, reverse=True)
                          if years[y].get("complete") and years[y].get("electricity_kwh") and years[y].get("kwh_per_m2") and years[y].get("area_m2")), None)
        if base_year is None:
            return {"available": False, "basis": basis, "basis_label": EFFORT_BASIS[basis],
                    "reason": "구역 안에 12개월 계측된 건축HUB 지번(연면적 확인)이 없어 건물 전체 기준으로 계산할 수 없습니다"}
        item = years[base_year]
        return _with_pv(pv, _effort_result(history, plan, target_pct, pv_yield_kwh_per_kw, factor, base_year, "OBSERVED",
                              float(item["kwh_per_m2"]), float(item["electricity_kwh"]), float(item["area_m2"]), basis,
                              f"신축 부하 = 계획 연면적 × 구역 건물 전체 관측 전력 원단위 {float(item['kwh_per_m2']):,.2f} kWh/m²·년 "
                              f"({base_year}년 건축HUB, 12개월 계측 지번 {item.get('electricity_complete') or 0:,}곳, 연면적 확인 {float(item['area_m2']):,.0f}m²)"))
    base_year = next((y for y in sorted(history["energy"], reverse=True)
                      if history["energy"][y]["electricity"]["kwh"] is not None and history["energy"][y]["electricity"]["intensity_kwh_per_m2"]), None)
    baseline_mode = "OBSERVED"
    if base_year is not None:
        elec = history["energy"][base_year]["electricity"]
        intensity = elec["intensity_kwh_per_m2"]
        base_kwh = elec["kwh"]
        basis_area = elec["intensity_area_m2"]
    else:
        # No observed year in the area: estimate the stock's load from the Jeonju observed intensity.
        city = history.get("city_intensity")
        base_year = history["years"][-1]
        stock = history.get("stock", {}).get(base_year, {})
        if not city or not stock.get("gfa_m2"):
            return {"available": False, "reason": "지역 관측이 없고 연면적이 확인된 단지도 없어 기준 부하를 정할 수 없습니다"}
        baseline_mode = "ESTIMATED"
        intensity = city["kwh_per_m2"]
        base_kwh = stock["gfa_m2"] * intensity
        basis_area = stock["gfa_m2"]
    load_text = (f"신축 부하 = 계획 연면적 × 지역 관측 전력 원단위 {intensity:,.2f} kWh/m²·년 ({base_year}년, 연면적 {basis_area:,.0f}m² 기준)" if baseline_mode == "OBSERVED"
                 else f"지역 관측이 없어 기준 부하를 추정했습니다: 단지 연면적 {basis_area:,.0f}m² × {history.get('region_label') or '전주'} 관측 원단위 {intensity:,.2f} kWh/m²·년")
    return _with_pv(pv, _effort_result(history, plan, target_pct, pv_yield_kwh_per_kw, factor, base_year, baseline_mode, intensity, base_kwh, basis_area, basis, load_text))


def observed_baseline(history: dict[str, Any], basis: str) -> dict[str, Any] | None:
    """The observed baseline year and intensity ``effort`` would use on ``basis`` (None: no observed year)."""
    if basis == "buildings":
        years = (history.get("building_energy") or {}).get("years") or {}
        year = next((y for y in sorted(years, reverse=True)
                     if years[y].get("complete") and years[y].get("electricity_kwh") and years[y].get("kwh_per_m2") and years[y].get("area_m2")), None)
        if year is None:
            return None
        item = years[year]
        return {"year": year, "kwh_per_m2": float(item["kwh_per_m2"]), "kwh": float(item["electricity_kwh"]), "area_m2": float(item["area_m2"])}
    year = next((y for y in sorted(history["energy"], reverse=True)
                 if history["energy"][y]["electricity"]["kwh"] is not None and history["energy"][y]["electricity"]["intensity_kwh_per_m2"]), None)
    if year is None:
        return None
    elec = history["energy"][year]["electricity"]
    return {"year": year, "kwh_per_m2": elec["intensity_kwh_per_m2"], "kwh": elec["kwh"], "area_m2": elec["intensity_area_m2"]}


def benchmark(db: Any, years: list[int], region: str | None, basis: str, *, inputs: dict[str, Any] | None = None) -> dict[str, Any]:
    """Observed electricity intensity of every 행정동 of the region on one basis: where an area stands among its peers.

    Like a benchmarking score (ENERGY STAR 1~100, 서울 건물에너지 등급 by kWh/m²) but only among the 행정동 of the same
    시·군·구, on the same source and year; 행정동 differ in building mix, so it is a position, not a grade.
    Only 행정동 whose baseline falls in the most common year are compared (``reference_year``).
    """
    if basis not in EFFORT_BASIS:
        raise ValueError("기준 건물은 apartments 또는 buildings 입니다")
    import statistics
    import time
    inputs = inputs or cached_inputs(db, years, region)
    key = (_key(years, region), basis, id(inputs))
    hit = _BENCH.get(key)
    if hit and time.monotonic() - hit[0] < INPUTS_TTL:
        return hit[1]
    complex_points = [{"kapt_code": c["kapt_code"], "lon": c["lon"], "lat": c["lat"], "grid_id": c["grid_id"]} for c in inputs["complexes"].values()]
    items = []
    for feature in inputs["admin"]:
        code = feature["properties"].get("adm_code")
        try:
            area = resolve_area({"type": "admin", "code": code}, inputs["grids"], complex_points, inputs["admin"], inputs["zoning"])
        except ValueError:
            continue
        base = observed_baseline(build_history(area, years, inputs), basis)
        items.append({"code": code, "name": short_admin_name(feature["properties"].get("adm_name")),
                      **({"year": base["year"], "kwh_per_m2": round(base["kwh_per_m2"], 2), "area_m2": round(base["area_m2"], 1)} if base else
                         {"year": None, "kwh_per_m2": None, "area_m2": None})})
    counted = [i["year"] for i in items if i["year"] is not None]
    reference = max(set(counted), key=lambda y: (counted.count(y), y)) if counted else None
    values = sorted(i["kwh_per_m2"] for i in items if i["year"] == reference and i["kwh_per_m2"] is not None)
    quintiles = [round(v, 2) for v in statistics.quantiles(values, n=5)] if len(values) >= 5 else None
    result = {"basis": basis, "basis_label": EFFORT_BASIS[basis], "years": [years[0], years[-1]], "region": inputs.get("region"),
              "reference_year": reference, "count": len(values), "admin_total": len(items),
              "median": round(statistics.median(values), 2) if values else None, "quintiles": quintiles,
              "min": values[0] if values else None, "max": values[-1] if values else None,
              "items": sorted(items, key=lambda i: (i["kwh_per_m2"] is None, i["kwh_per_m2"] or 0)),
              "note": "같은 시·군·구 행정동끼리, 같은 출처·같은 연도의 관측 전력 원단위(kWh/m²·년)만 비교합니다. 건물 구성(용도·연식)이 달라 등급이 아니라 위치입니다."}
    if len(_BENCH) >= 6:
        _BENCH.pop(min(_BENCH, key=lambda k: _BENCH[k][0]), None)
    _BENCH[key] = (time.monotonic(), result)
    return result


_BENCH: dict[tuple[Any, ...], tuple[float, dict[str, Any]]] = {}


def benchmark_position(bench: dict[str, Any], year: int | None, value: float | None) -> dict[str, Any] | None:
    """Rank of one intensity among the benchmark values (1 = lowest kWh/m²), its quintile (1~5) and percentile."""
    if value is None or year is None or year != bench.get("reference_year") or not bench.get("count"):
        return None
    values = sorted(i["kwh_per_m2"] for i in bench["items"] if i["year"] == bench["reference_year"] and i["kwh_per_m2"] is not None)
    lower = sum(1 for v in values if v < round(value, 2))
    pct = round(lower / len(values) * 100, 1)
    quintile = 1 + sum(1 for q in (bench.get("quintiles") or []) if round(value, 2) > q) if bench.get("quintiles") else None
    return {"rank": lower + 1, "count": len(values), "lower_pct": pct, "quintile": quintile}


def pv_basis(history: dict[str, Any], user_kwh_per_kw: float | None) -> dict[str, Any] | None:
    """kWh a 1 kW array makes per year: the user's number when given, otherwise the region's irradiation estimate."""
    if user_kwh_per_kw and user_kwh_per_kw > 0:
        return {"kwh_per_kw": float(user_kwh_per_kw), "basis": "USER", "label": "사용자 입력"}
    solar = history.get("solar")
    if solar and solar.get("yield_kwh_per_kw"):
        return {"kwh_per_kw": solar["yield_kwh_per_kw"], "basis": "ESTIMATED", "year": solar["year"], "source": solar["source"],
                "source_type": solar["source_type"], "irradiation_kwh_m2": solar["irradiation_kwh_m2"],
                "performance_ratio": solar["performance_ratio"],
                "label": f"{solar['year']}년 {solar['source']} 수평면 일사량 {solar['irradiation_kwh_m2']:,.0f} kWh/m² × 성능비 {solar['performance_ratio']:.2f}"}
    return None


def _with_pv(pv: dict[str, Any] | None, result: dict[str, Any]) -> dict[str, Any]:
    result["pv_yield"] = pv
    if pv and result.get("assumptions"):
        result["assumptions"] = [a for a in result["assumptions"] if not a.startswith("태양광")] + [
            "태양광 설비 용량은 사용자가 입력한 kW당 연 발전량으로 환산합니다" if pv["basis"] == "USER"
            else f"태양광 설비 용량은 지역 일사량 추정 발전량 {pv['kwh_per_kw']:,.0f} kWh/kW·년({pv['label']}, 경사 보정 없음)으로 환산한 추정값입니다"]
    return result


def _effort_result(history: dict[str, Any], plan: dict[str, Any], target_pct: float, pv_yield_kwh_per_kw: float | None, factor: float,
                   base_year: int, baseline_mode: str, intensity: float, base_kwh: float, basis_area: float, basis: str, load_text: str) -> dict[str, Any]:
    added = plan.get("added_floor_area_m2")
    if added is None and plan.get("floors") and plan.get("building_count") and plan.get("footprint_per_building"):
        added = float(plan["floors"]) * float(plan["building_count"]) * float(plan["footprint_per_building"])
    added = float(added or 0)
    removed = float(plan.get("removed_floor_area_m2") or 0)
    if added < 0 or removed < 0:
        raise ValueError("면적은 0 이상이어야 합니다")
    if removed and intensity > 0 and intensity * removed > base_kwh:
        # more demolished than there is: the BAU would go below zero and every option would turn negative
        raise ValueError(f"철거 연면적 {removed:,.0f}m²가 기준 건물 규모(약 {base_kwh / intensity:,.0f}m², {base_year}년 기준 부하 ÷ 원단위)보다 큽니다. "
                         "철거 면적을 줄이거나 구역을 넓히세요")
    base_c = base_kwh * factor
    new_kwh = intensity * added
    removed_kwh = intensity * removed
    bau_kwh = base_kwh + new_kwh - removed_kwh
    bau_c = bau_kwh * factor
    target_c = base_c * (1 - target_pct / 100)
    need_c = bau_c - target_c
    need_kwh = need_c / factor
    new_c = new_kwh * factor
    options = {
        "new_only_efficiency_pct": round(need_c / new_c * 100, 1) if new_c > 0 else None,
        "all_buildings_efficiency_pct": round(need_c / bau_c * 100, 1) if bau_c > 0 else None,
        "offset_kwh_per_year": round(max(need_kwh, 0), 1),
        "pv_capacity_kw": round(max(need_kwh, 0) / pv_yield_kwh_per_kw, 1) if pv_yield_kwh_per_kw and pv_yield_kwh_per_kw > 0 else None,
        "new_building_intensity_target": round(intensity * (1 - need_c / new_c), 3) if new_c > 0 and need_c <= new_c else None,
    }
    feasible_new_only = options["new_only_efficiency_pct"] is not None and options["new_only_efficiency_pct"] <= 100
    curve = []
    for t in range(0, 101, 10):
        tc = base_c * (1 - t / 100)
        nc = bau_c - tc
        curve.append({"target_pct": t,
                      "all_buildings_efficiency_pct": round(nc / bau_c * 100, 1) if bau_c > 0 else None,
                      "new_only_efficiency_pct": round(nc / new_c * 100, 1) if new_c > 0 else None})
    return {
        "available": True, "baseline_year": base_year, "target_pct": target_pct,
        "baseline_mode": baseline_mode, "data_class": "SCENARIO", "basis": basis, "basis_label": EFFORT_BASIS[basis],
        "intensity_kwh_per_m2": intensity, "intensity_area_m2": basis_area,
        "added_floor_area_m2": round(added, 1), "removed_floor_area_m2": round(removed, 1),
        "baseline_kwh": round(base_kwh, 1), "baseline_kgco2eq": round(base_c, 1),
        "new_load_kwh": round(new_kwh, 1), "bau_kwh": round(bau_kwh, 1), "bau_kgco2eq": round(bau_c, 1),
        "target_kgco2eq": round(target_c, 1), "required_reduction_kgco2eq": round(need_c, 1),
        "already_met": need_c <= 0, "feasible_with_new_only": feasible_new_only or need_c <= 0,
        "options": options, "curve": curve, "factor_kgco2eq_per_kwh": factor,
        "scope": "전력 운영탄소 기준 (가스는 배출계수 확정 후 추가)",
        "assumptions": [
            load_text,
            *(["기준 부하는 구역 격자에 배치된 건축HUB 12개월 계측 지번 전체의 전력입니다(단독주택·200세대 미만 공동주택 등 제공 범위 밖 제외)"] if basis == "buildings" else []),
            "기상은 기준 연도와 같다고 가정합니다 (별도 기상 보정 없음)",
            "가스는 이 계산에 넣지 않았습니다 (가스 배출계수 기준 확정 후 추가)",
            "태양광 설비 용량은 사용자가 입력한 kW당 연 발전량 가정으로만 환산합니다" if pv_yield_kwh_per_kw else "태양광은 연간 상쇄 전력량(kWh)으로만 표시합니다 (설비 용량 환산에는 지역 발전량 근거 필요)",
        ],
    }


def building_stock(area: dict[str, Any], complexes: dict[str, dict[str, Any]], years: list[int]) -> dict[int, dict[str, Any]]:
    """Apartment stock in the area at the end of each year (by 사용승인일). Only plausible floor areas count."""
    members = [complexes[c] for c in area["complex_codes"] if c in complexes]
    unknown = sum(1 for m in members if not m.get("approval_year"))
    out = {}
    for year in years:
        built = [m for m in members if m.get("approval_year") and m["approval_year"] <= year]
        out[year] = {
            "year": year, "complexes": len(built), "households": sum(int(m.get("households") or 0) for m in built),
            "gfa_m2": round(sum(float(m["gfa"]) for m in built if m.get("floor_area_ok")), 1),
            "gfa_excluded": sum(1 for m in built if not m.get("floor_area_ok")), "unknown_approval": unknown,
        }
    return out


def city_intensity(energy_rows: list[dict[str, Any]], complexes: dict[str, dict[str, Any]], years: list[int]) -> dict[str, Any] | None:
    """Jeonju-wide observed electricity intensity (latest year with a floor-area-matched 12-month total)."""
    everything = {"grid_ids": sorted({r.get("grid_id") for r in energy_rows if r.get("grid_id")}), "complex_codes": sorted(complexes)}
    city = yearly_energy(energy_rows, everything, complexes, years, ENERGY_SOURCES["electricity"][0])
    for year in sorted(city, reverse=True):
        item = city[year]["electricity"]
        if item["intensity_kwh_per_m2"]:
            return {"year": year, "kwh_per_m2": item["intensity_kwh_per_m2"], "area_m2": item["intensity_area_m2"], "parcels": item["complete_parcels"]}
    return None


REGISTER_USE_GROUPS = (
    ("주거", ("공동주택", "단독주택")),
    ("상업·업무", ("근린생활", "판매", "업무", "숙박", "위락")),
    ("공공·교육·의료", ("교육", "연구", "노유자", "의료", "문화", "집회", "종교", "운동", "공공", "교정", "방송", "발전", "묘지", "장례", "관광")),
    ("공업·창고·물류", ("공장", "창고", "위험물", "자동차", "동물", "식물", "자원순환", "분뇨")),
)


def register_use_group(use: str | None) -> str:
    text = use or ""
    for group, keywords in REGISTER_USE_GROUPS:
        if any(k in text for k in keywords):
            return group
    return "기타·미상"


def register_events(area: dict[str, Any], rows: list[dict[str, Any]], years: list[int]) -> dict[str, Any]:
    """건축물대장 사용승인 per year inside the area (all building types, by 500m grid membership).

    Buildings without a linked grid or a readable 사용승인일 are counted separately, never guessed.
    """
    members = set(area["grid_ids"])
    inside = [r for r in rows if r.get("grid_id") in members]
    out: dict[int, dict[str, Any]] = {}
    for year in years:
        built = [r for r in inside if r.get("approval_year") == year]
        by_use: dict[str, float] = {}
        for r in built:
            group = register_use_group(r.get("use"))
            by_use[group] = round(by_use.get(group, 0.0) + float(r.get("gfa") or 0), 1)
        out[year] = {"year": year, "buildings": len(built), "gfa_m2": round(sum(float(r.get("gfa") or 0) for r in built), 1),
                     "gfa_missing": sum(1 for r in built if not r.get("gfa")), "by_use": by_use}
    return {"available": bool(rows), "linked_in_area": len(inside),
            "unknown_year": sum(1 for r in inside if not r.get("approval_year")), "years": out,
            "basis": "건축물대장 표제부 사용승인일 · 격자(500m) 기준 포함, 연면적은 대장 연면적"}


def building_energy_block(grid_ids: list[str], by_year: dict[int, dict[str, dict[str, Any]]], factor: float | None,
                          complete: dict[int, bool] | None = None) -> dict[str, Any]:
    """Every metered building of the area's grids (건축HUB by 법정동), per year with data (2020-; 전주 2020~, 수원·완주 2024~).

    Complements the apartment series: offices, shops, schools and large apartment blocks together.
    Parcels are placed on grids through the cadastral point, so a grid-based area gets whole parcels.
    """
    from .energy_parcels import HUB_PROVIDER_GAPS, year_complete
    members = set(grid_ids)
    years: dict[int, dict[str, Any]] = {}
    for year, grids in sorted(by_year.items()):
        inside = [grids[g] for g in members if g in grids]
        if not inside:
            continue
        kwh = [g["electricity_kwh"] for g in inside if g["electricity_kwh"] is not None]
        gas = [g["gas_kwh"] for g in inside if g["gas_kwh"] is not None]
        area_m2 = sum(g["area_m2"] or 0 for g in inside if g["area_parcels"])
        area_kwh = sum((g["kwh_per_m2"] or 0) * (g["area_m2"] or 0) for g in inside if g["area_parcels"])
        electricity = round(sum(kwh), 1) if kwh else None
        years[year] = {
            "year": year, "parcels": sum(g["parcels"] for g in inside),
            "electricity_complete": sum(g["electricity_complete"] for g in inside), "electricity_kwh": electricity,
            "gas_complete": sum(g["gas_complete"] for g in inside), "gas_kwh": round(sum(gas), 1) if gas else None,
            "area_m2": round(area_m2, 1) if area_m2 else None, "kwh_per_m2": round(area_kwh / area_m2, 2) if area_m2 else None,
            "electricity_carbon_kgco2eq": round(electricity * factor, 1) if electricity is not None and factor else None,
            # the region's own collection state when given (energy_parcels.region_year_complete), else the city-wide file
            "complete": bool(complete.get(year)) if complete is not None else year_complete(year),
            "provider_gap": HUB_PROVIDER_GAPS.get(year),
        }
    return {"years": years, "available": bool(years), "trend": same_parcel_trend(members, by_year, years),
            "basis": "건축HUB 건물에너지 법정동 단위 전 지번(단독주택·200세대 미만 공동주택·산업용 등 제외), 12개월 계측 지번 합계, 연속지적 대표점으로 격자 배치"}


def same_parcel_trend(members: set[str], by_year: dict[int, dict[str, dict[str, Any]]], years: dict[int, dict[str, Any]]) -> dict[str, Any] | None:
    """Electricity of the first comparable year against the latest one, split into the parcels metered for 12 months in
    both years (a change in use of the same buildings) and the parcels metered in only one of them (new or gone meters,
    new buildings, or a meter recorded under another parcel). Years with a provider gap or still being collected are skipped."""
    comparable = sorted(y for y, v in years.items() if v.get("electricity_kwh") and v.get("complete") and not v.get("provider_gap"))
    if len(comparable) < 2:
        return None
    first, last = comparable[0], comparable[-1]

    def parcels(year: int) -> dict[str, float]:
        merged: dict[str, float] = {}
        for g in members:
            merged.update((by_year.get(year, {}).get(g) or {}).get("electricity_by_parcel") or {})
        return merged

    a, b = parcels(first), parcels(last)
    if not a or not b:
        return None
    same = a.keys() & b.keys()
    same_a, same_b = sum(a[p] for p in same), sum(b[p] for p in same)
    return {"from": first, "to": last, "same_parcels": len(same), "same_from_kwh": round(same_a, 1), "same_to_kwh": round(same_b, 1),
            "same_change_pct": round((same_b - same_a) / same_a * 100, 1) if same_a else None,
            "new_parcels": len(b.keys() - a.keys()), "new_kwh": round(sum(b[p] for p in b.keys() - a.keys()), 1),
            "gone_parcels": len(a.keys() - b.keys()), "gone_kwh": round(sum(a[p] for p in a.keys() - b.keys()), 1)}


ENERGY_SOURCES = {"electricity": ("KAPT", "K-apt 관리비 전력 (2015~, 같은 출처로 연도 비교)"),
                  "gas": ("HUB", "건축HUB 지번 가스 (전주 2020~, 수원·완주 2024~)")}


def consistent_energy(rows: list[dict[str, Any]], area: dict[str, Any], complexes: dict[str, dict[str, Any]],
                      years: list[int]) -> dict[int, dict[str, Any]]:
    """Yearly energy with one provider per energy type across all years.

    K-apt reports a complex's electricity from its management fees (2015~); 건축HUB meters the parcel (2020~). For the
    same complex-year the two differ (K-apt median 77% of 건축HUB, 803 pairs in 전주·수원, 2026-09-30), so a series
    that switches provider in 2024 would show a jump that is not a change in use. Electricity therefore comes from
    K-apt in every year and gas from 건축HUB (K-apt gas is mostly the common part only)."""
    electricity = yearly_energy(rows, area, complexes, years, ENERGY_SOURCES["electricity"][0])
    gas = yearly_energy(rows, area, complexes, years, ENERGY_SOURCES["gas"][0])
    out = {}
    for year in years:
        entry = dict(electricity[year])
        entry["gas"] = gas[year]["gas"]
        entry["sources"] = {k: label for k, (_, label) in ENERGY_SOURCES.items()}
        out[year] = entry
    return out


def build_history(area: dict[str, Any], years: list[int], inputs: dict[str, Any]) -> dict[str, Any]:
    complexes = inputs["complexes"]
    history = {
        "years": years, "area": {k: v for k, v in area.items()},
        "energy": consistent_energy(inputs["energy"], area, complexes, years),
        "weather": yearly_weather(inputs["weather"], years),
        "population": yearly_population(inputs["population"], inputs["households"], area, years),
        "events": development_events(area, complexes, years),
        "factor": inputs.get("factor", {}),
        "factor_basis": "연도별 공표 계수가 있지만 전후 비교가 사용량 변화만 반영하도록 최신 전력 계수를 모든 연도에 동일 적용",
        "region_label": region_label(inputs.get("region")),
    }
    factor = history["factor"].get("electricity")
    for item in history["energy"].values():
        kwh = item["electricity"]["kwh"]
        item["electricity_carbon_kgco2eq"] = round(kwh * factor, 1) if kwh is not None and factor else None
    history["complexes"] = [
        {k: complexes[c].get(k) for k in ("kapt_code", "name", "approval_year", "approval_date", "households", "gfa", "floor_area_ok", "lon", "lat", "grid_id", "heating_type")}
        for c in area["complex_codes"] if c in complexes
    ]
    history["stock"] = building_stock(area, complexes, years)
    history["register"] = register_events(area, inputs.get("register", []), years)
    from .sgis_grid import area_block
    sgis_year, sgis_values = inputs.get("sgis_grid") or (None, {})
    history["sgis_grid"] = area_block(area["grid_ids"], sgis_year, sgis_values)
    history["building_energy"] = building_energy_block(area["grid_ids"], inputs.get("building_energy") or {}, factor,
                                                       inputs.get("building_energy_complete"))
    city = inputs.get("city_intensity")
    history["city_intensity"] = city
    history["solar"] = inputs.get("solar")  # 태양광 연 발전량 추정 (solar.py, DATA_STANDARD 5.13), None when no complete year
    for year in years:
        gfa = history["stock"][year]["gfa_m2"]
        kwh = round(gfa * city["kwh_per_m2"], 1) if city and gfa else None
        history["energy"][year]["estimated"] = {
            "kwh": kwh, "carbon_kgco2eq": round(kwh * factor, 1) if kwh is not None and factor else None,
            "basis": f"사용승인된 단지 연면적 × {history['region_label']} 관측 전력 원단위 {city['kwh_per_m2']:,.2f} kWh/m²·년({city['year']}년)" if city else None,
            "data_class": "ESTIMATED",
        }
    years_with_energy = [y for y in years if history["energy"][y]["electricity"]["kwh"] is not None]
    history["coverage"] = {
        "energy_years": years_with_energy,
        "weather_years": [y for y in years if history["weather"][y]["complete"]],
        "population_years": [y for y in years if history["population"][y]["population"] is not None],
        "grid_count": len(area["grid_ids"]), "complex_count": len(area["complex_codes"]),
        "register_buildings": history["register"]["linked_in_area"],
    }
    return history


def only_in(year: int | str, parcels: int, kwh: float) -> str:
    """'2025년 3곳(5,836,169 kWh)', or '2021년 없음' — an empty set has no usage to report, not 0 kWh."""
    return f"{year}년 {parcels:,}곳({kwh:,.0f} kWh)" if parcels else f"{year}년 없음"


def area_facts(history: dict[str, Any], comparison: dict[str, Any] | None = None, effort_result: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Verified sentences with the exact numbers they contain (for the report and the LLM checker)."""
    area = history["area"]
    facts: list[dict[str, Any]] = []

    def add(fid: str, text: str, *numbers: float | int | None, signed_pct: float | None = None) -> None:
        fact: dict[str, Any] = {"id": fid, "text": text, "numbers": [n for n in numbers if n is not None]}
        if signed_pct is not None:  # the report checker makes 증가/감소 words agree with this sign
            fact["signed_pct"] = signed_pct
        facts.append(fact)

    y0, y1 = history["years"][0], history["years"][-1]
    add("scope", f"분석 대상은 {area['label']}이고 기간은 {y0}~{y1}년입니다. 격자 {len(area['grid_ids'])}개와 공동주택 단지 {len(area['complex_codes'])}개가 포함됩니다.", y0, y1, len(area["grid_ids"]), len(area["complex_codes"]))
    cov = history["coverage"]
    if cov["energy_years"]:
        add("coverage", f"12개월 전력 관측이 있는 연도는 {len(cov['energy_years'])}개({', '.join(map(str, cov['energy_years']))})입니다.", len(cov["energy_years"]), *cov["energy_years"])
    elif any(v.get("electricity_kwh") is not None for v in ((history.get("building_energy") or {}).get("years") or {}).values()):
        # no apartment series here (e.g. a 면 without K-apt complexes), but metered buildings: say which series is missing
        add("coverage", "공동주택(K-apt) 12개월 전력 관측이 있는 연도가 없어 공동주택 기준 연간 에너지는 계산하지 않았습니다. 건물 전체(건축HUB) 계측값은 따로 씁니다.")
    else:
        add("coverage", "12개월이 모두 관측된 전력 자료가 있는 연도가 없어 연간 에너지와 탄소를 계산하지 않았습니다.")
    built = [(y, e) for y, e in history["events"].items() if e["complexes"]]
    if built:
        total_households = sum(e["households"] for _, e in built)
        add("development", f"분석 기간에 사용승인된 단지는 {sum(e['complexes'] for _, e in built)}개, {total_households:,}세대입니다.", sum(e["complexes"] for _, e in built), total_households)
    reg = history.get("register") or {}
    if reg.get("linked_in_area"):
        reg_years = [v for v in reg["years"].values() if v["buildings"]]
        n_reg = sum(v["buildings"] for v in reg_years)
        gfa_reg = round(sum(v["gfa_m2"] for v in reg_years))
        add("register", f"건축물대장 기준으로 분석 기간에 사용승인된 건물은 {n_reg:,}동, 연면적 {gfa_reg:,}m²입니다(모든 용도).", n_reg, gfa_reg)
    be = (history.get("building_energy") or {}).get("years") or {}
    latest_be = max((y for y, v in be.items() if v.get("electricity_kwh") is not None and v.get("complete", True)), default=None)
    if latest_be is not None:
        v = be[latest_be]
        carbon = f", 전력 탄소 {v['electricity_carbon_kgco2eq']:,.0f} kgCO2eq" if v.get("electricity_carbon_kgco2eq") is not None else ""
        add("building_energy", f"건축HUB가 계측하는 구역 안 건물 전체(상가·업무·학교·대형 공동주택 등, 12개월 계측 지번 {v['electricity_complete']:,}곳)의 {latest_be}년 전력은 {v['electricity_kwh']:,.0f} kWh{carbon}입니다. 단독주택과 200세대 미만 공동주택은 제공 범위 밖입니다.",
            latest_be, v["electricity_complete"], v["electricity_kwh"], v.get("electricity_carbon_kgco2eq"))
        trend = (history.get("building_energy") or {}).get("trend")
        if trend and trend.get("to") == latest_be and trend.get("same_change_pct") is not None:
            t = trend
            add("building_energy_trend", f"{t['from']}년과 {t['to']}년 모두 12개월 계측된 같은 지번 {t['same_parcels']:,}곳의 전력은 {t['same_from_kwh']:,.0f} kWh에서 "
                f"{t['same_to_kwh']:,.0f} kWh로 {t['same_change_pct']:+,.1f}% 변했습니다. 한 해에만 계측된 지번은 {only_in(t['to'], t['new_parcels'], t['new_kwh'])}, "
                f"{only_in(t['from'], t['gone_parcels'], t['gone_kwh'])}입니다(신축·계량 변경·다른 지번으로의 기록 이동이 섞일 수 있음).",
                t["from"], t["to"], t["same_parcels"], t["same_from_kwh"], t["same_to_kwh"], t["same_change_pct"],
                *([t["new_parcels"], t["new_kwh"]] if t["new_parcels"] else []), *([t["gone_parcels"], t["gone_kwh"]] if t["gone_parcels"] else []),
                signed_pct=t["same_change_pct"])
        gaps = sorted(y for y, w in be.items() if w.get("provider_gap"))
        for y in gaps:
            add("building_energy_gap", f"{y}년 건축HUB 값은 쓰되 비교하지 않습니다: {be[y]['provider_gap']}.", y)
    sg = history.get("sgis_grid") or {}
    if sg.get("overlap"):
        o = sg["overlap"]
        parts = [f"인구 {o['population']:,.0f}명" if o.get("population") is not None else None,
                 f"가구 {o['households']:,.0f}" if o.get("households") is not None else None,
                 f"주택 {o['housing']:,.0f}호" if o.get("housing") is not None else None,
                 f"사업체 종사자 {o['workers']:,.0f}명" if o.get("workers") is not None else None]
        text = ", ".join(p for p in parts if p)
        scope = ("구역이 이 격자들과 같은 범위이며" if sg["coverage_pct"] >= 99.9
                 else f"구역은 이 격자 면적의 {sg['coverage_pct']:,.1f}%라 합계는 구역보다 넓은 범위이며")
        add("sgis_grid", f"SGIS {sg['year']}년 1km 격자 기준으로 이 구역이 걸친 1km 격자 {sg['cells']}개(통계 있는 격자 {sg['cells_with_stats']}개)의 합계는 {text}입니다. "
            f"{scope}, 공식 통계의 비밀보호 잡음이 들어 있습니다.",
            sg["year"], sg["cells"], sg["cells_with_stats"], o.get("population"), o.get("households"), o.get("housing"), o.get("workers"), sg["coverage_pct"])
        shares = [(label, o.get(key)) for label, key in (("65세 이상 인구", "elderly_pct"), ("1인가구", "single_household_pct"),
                                                          ("2000년 이전 준공 주택", "old_housing_pct"), ("아파트", "apartment_pct"))]
        shares = [(label, v) for label, v in shares if v is not None]
        if shares:
            add("sgis_grid_shares", "같은 1km 격자들에서 " + ", ".join(f"{label} 비율은 {v:,.1f}%" for label, v in shares) + "입니다.", *[v for _, v in shares])
    latest = cov["energy_years"][-1] if cov["energy_years"] else None
    if latest is not None:
        e = history["energy"][latest]["electricity"]
        add("latest_energy", f"{latest}년 관측 전력은 {e['kwh']:,.0f} kWh(12개월 관측 지번 {e['complete_parcels']}곳)입니다.", latest, e["kwh"], e["complete_parcels"])
        carbon = history["energy"][latest].get("electricity_carbon_kgco2eq")
        if carbon is not None:
            add("latest_carbon", f"같은 해 전력 운영탄소는 {carbon:,.0f} kgCO2eq입니다.", carbon)
        if e["intensity_kwh_per_m2"] is not None:
            add("latest_intensity", f"연면적이 확인된 단지 기준 전력 원단위는 {e['intensity_kwh_per_m2']:,.2f} kWh/m²·년입니다.", e["intensity_kwh_per_m2"])
    if comparison and comparison.get("available"):
        m = comparison["metrics"]["electricity"]
        ev = comparison["event"] or {}
        add("event", f"{comparison['event_year']}년에 단지 {ev.get('complexes', 0)}개({ev.get('households', 0):,}세대)가 사용승인되었습니다.", comparison["event_year"], ev.get("complexes", 0), ev.get("households", 0))
        if m["before_total_kwh"] is not None and m["after_total_kwh"] is not None:
            cov = comparison.get("coverage") or {}
            ob = cov.get("observed_before_years") or [y for y in comparison["before_years"] if history["energy"][y]["electricity"]["kwh"] is not None]
            oa = cov.get("observed_after_years") or [y for y in comparison["after_years"] if history["energy"][y]["electricity"]["kwh"] is not None]
            # the mean is over the years with a 12-month total only: name them (a '3년 평균' of one observed year misleads)
            add("before_after", f"개발 전 관측 {len(ob)}개 연도({', '.join(map(str, ob))}) 평균 전력은 {m['before_total_kwh']:,.0f} kWh, "
                f"개발 후 관측 {len(oa)}개 연도({', '.join(map(str, oa))}) 평균은 {m['after_total_kwh']:,.0f} kWh입니다.",
                len(ob), m["before_total_kwh"], len(oa), m["after_total_kwh"], *ob, *oa)
            if m["total_change_pct"] is not None:
                same = (f" 전후 모든 관측 연도에 있는 같은 기존 단지 {m['existing_complexes']}곳끼리는 {m['existing_change_pct']:+,.1f}% 변했습니다."
                        if m.get("existing_change_pct") is not None and m.get("existing_complexes") else "")
                if cov.get("comparable", True):
                    text = f"지역 전력은 {m['total_change_pct']:+,.1f}% 변했습니다." + same
                else:
                    text = (f"지역 전력 합계는 {m['total_change_pct']:+,.1f}% 변했지만, 개발 전 관측 단지가 평균 {cov['before_parcels_mean']:,.1f}곳으로 "
                            f"개발 후 기존 단지 평균 {cov['after_existing_parcels_mean']:,.1f}곳보다 적어 이 차이에는 관측 범위 차이가 섞여 있습니다." + same)
                numbers = [m["total_change_pct"]]
                if not cov.get("comparable", True):
                    numbers += [cov["before_parcels_mean"], cov["after_existing_parcels_mean"]]
                if same:
                    numbers += [m["existing_complexes"], m["existing_change_pct"]]
                add("change", text, *numbers, signed_pct=m["total_change_pct"])
        if m["new_development_kwh"] is not None:
            add("new_share", f"새로 준공된 단지의 연평균 전력은 {m['new_development_kwh']:,.0f} kWh로 개발 후 지역 전력의 {m['new_share_pct']:,.1f}%입니다.", m["new_development_kwh"], m["new_share_pct"])
        est = comparison["metrics"].get("estimated") or {}
        if (m["before_total_kwh"] is None or m["after_total_kwh"] is None) and est.get("event_change_pct") is not None:
            add("estimated_change", f"관측이 부족해 연면적으로 추정하면, 이 개발로 단지 연면적이 {est['added_gfa_m2']:,.0f}m²({est['event_change_pct']:+,.1f}%) 늘어 연간 전력 부하가 약 {est['event_added_kwh']:,.0f} kWh 늘어난 것으로 추정됩니다(추정값).", est["added_gfa_m2"], est["event_change_pct"], est["event_added_kwh"])
        for gap in comparison.get("gaps", []):
            add(f"gap_{len(facts)}", gap)
    if effort_result and effort_result.get("available"):
        o = effort_result["options"]
        if effort_result.get("fallback_from"):
            asked = "공동주택(K-apt)" if effort_result["fallback_from"] == "apartments" else "건물 전체(건축HUB)"
            used = "건물 전체(건축HUB)" if effort_result["basis"] == "buildings" else "공동주택(K-apt)"
            add("effort_fallback", f"이 구역은 {asked} 기준으로 계산할 근거가 없어 {used} 기준으로 바꿔 계산했습니다.")
        if effort_result.get("baseline_mode") == "ESTIMATED":
            city = history.get("city_intensity") or {}
            add("effort_basis", f"이 지역은 관측 전력이 없어 기준 부하를 단지 연면적 {effort_result['intensity_area_m2']:,.0f}m²와 {history.get('region_label') or '전주'} 관측 원단위 {effort_result['intensity_kwh_per_m2']:,.2f} kWh/m²·년({city.get('year')}년, 관측 지번 {city.get('parcels')}곳 기준)으로 추정했습니다. 관측 지번이 적을수록 추정 오차가 큽니다.", effort_result["intensity_area_m2"], effort_result["intensity_kwh_per_m2"], city.get("year"), city.get("parcels"))
        elif effort_result.get("basis") == "apartments":
            add("effort_basis", f"감축 노력은 공동주택 단지(K-apt 관리비 전력) 기준입니다: {effort_result['baseline_year']}년 전력 {effort_result['baseline_kwh']:,.0f} kWh, "
                f"원단위 {effort_result['intensity_kwh_per_m2']:,.2f} kWh/m²·년(연면적 확인 {effort_result['intensity_area_m2']:,.0f}m²).",
                effort_result["baseline_year"], effort_result["baseline_kwh"], effort_result["intensity_kwh_per_m2"], effort_result["intensity_area_m2"])
        if effort_result.get("basis") == "buildings":
            add("effort_basis", f"감축 노력은 구역 건물 전체(건축HUB 계측 지번, 상가·업무 포함) 기준입니다: {effort_result['baseline_year']}년 전력 {effort_result['baseline_kwh']:,.0f} kWh, 원단위 {effort_result['intensity_kwh_per_m2']:,.2f} kWh/m²·년.", effort_result["baseline_year"], effort_result["baseline_kwh"], effort_result["intensity_kwh_per_m2"])
        add("effort_target", f"{effort_result['baseline_year']}년 대비 {effort_result['target_pct']:,.0f}% 감축을 목표로 하면 계획 반영 후 연간 {effort_result['required_reduction_kgco2eq']:,.0f} kgCO2eq를 줄여야 합니다.", effort_result["baseline_year"], effort_result["target_pct"], effort_result["required_reduction_kgco2eq"])
        if effort_result["already_met"]:
            add("effort_met", "계획을 반영해도 목표 이하이므로 추가 감축이 필요하지 않습니다.")
        else:
            if o["new_only_efficiency_pct"] is not None:
                add("effort_new", f"신축만으로 달성하려면 신축 전력 소비를 {o['new_only_efficiency_pct']:,.1f}% 줄여야 합니다." + (" 100%를 넘어 신축만으로는 달성할 수 없습니다." if o["new_only_efficiency_pct"] > 100 else ""), o["new_only_efficiency_pct"])
            if o["all_buildings_efficiency_pct"] is not None:
                add("effort_all", f"기존 건물까지 함께 줄이면 지역 전체 전력 소비를 {o['all_buildings_efficiency_pct']:,.1f}% 줄여야 합니다.", o["all_buildings_efficiency_pct"])
            add("effort_offset", f"같은 목표를 재생에너지로 상쇄하려면 연간 {o['offset_kwh_per_year']:,.0f} kWh가 필요합니다.", o["offset_kwh_per_year"])
            pv = effort_result.get("pv_yield")
            if pv and o.get("pv_capacity_kw"):
                how = ("사용자가 입력한 발전량" if pv["basis"] == "USER"
                       else f"{pv['year']}년 지역 일사량 {pv['irradiation_kwh_m2']:,.0f} kWh/m²와 성능비 {pv['performance_ratio']:.2f}로 추정한 발전량")
                add("effort_pv", f"태양광으로 상쇄하면 {how} {pv['kwh_per_kw']:,.0f} kWh/kW·년 기준 약 {o['pv_capacity_kw']:,.1f} kW가 필요합니다"
                    + ("(추정값)." if pv["basis"] == "ESTIMATED" else "."),
                    pv["kwh_per_kw"], o["pv_capacity_kw"], *([pv["year"], pv["irradiation_kwh_m2"], pv["performance_ratio"]] if pv["basis"] == "ESTIMATED" else []))
        mix = effort_result.get("mix")
        if mix and not effort_result["already_met"]:
            parts = [f"신축 전력 {mix['new_efficiency_pct']:,.1f}% 절감", f"기존 건물 {mix['existing_efficiency_pct']:,.1f}% 절감"]
            numbers: list[float] = [mix["new_efficiency_pct"], mix["existing_efficiency_pct"]]
            if mix["pv_kw"]:
                parts.append(f"태양광 {mix['pv_kw']:,.1f} kW" + ("" if mix["pv_counted"] else "(발전량 근거 없음, 합계에서 제외)"))
                numbers.append(mix["pv_kw"])
            add("effort_mix", f"감축 수단 조합({', '.join(parts)})으로 연간 {mix['total_kgco2eq']:,.0f} kgCO2eq를 줄입니다.", *numbers, mix["total_kgco2eq"])
            if mix["met"]:
                add("effort_mix_gap", f"필요 감축량 {mix['required_kgco2eq']:,.0f} kgCO2eq를 채웁니다(여유 {-mix['gap_kgco2eq']:,.0f} kgCO2eq).",
                    mix["required_kgco2eq"], -mix["gap_kgco2eq"])
            else:
                add("effort_mix_gap", f"필요 감축량 {mix['required_kgco2eq']:,.0f} kgCO2eq의 {mix['share_pct']:,.1f}%로, 목표까지 연간 {mix['gap_kgco2eq']:,.0f} kgCO2eq가 남습니다.",
                    mix["required_kgco2eq"], mix["share_pct"], mix["gap_kgco2eq"])
    add("rules", "관측이 없는 연도는 0이 아니라 자료 없음으로 두었고, 행정동 통계는 격자에 배분하지 않았습니다.", 0)
    return facts


# --------------------------------------------------------------------------- DB loaders
def load_inputs(db: Any, years: list[int], region: str | None = None) -> dict[str, Any]:
    """Everything the area analysis reads for one study region (the original region by default)."""
    from sqlalchemy import select
    from .kapt import ApartmentComplex
    from .models import EmissionFactor, EnergyMonthly, Grid
    from .regions import scope, weather_rows
    sc = scope(db, region)
    region_ids = sc.grid_ids
    complexes: dict[str, dict[str, Any]] = {}
    for row in db.scalars(select(ApartmentComplex)):
        if not sc.owns_complex(row.bjd_code, row.grid_id):
            continue
        complexes[row.kapt_code] = {
            "kapt_code": row.kapt_code, "name": row.name, "approval_date": row.approval_date,
            "approval_year": approval_year(row.approval_date), "households": row.households,
            "gfa": row.gross_floor_area_m2, "floor_area_ok": floor_area_ok(row.gross_floor_area_m2, row.households, row.management_area_m2),
            "lon": row.longitude, "lat": row.latitude, "grid_id": row.grid_id, "heating_type": row.heating_type,
        }
    lo, hi = f"{years[0]}01", f"{years[-1]}12"
    energy = []
    # Rows without a grid (city-wide 건축HUB parcels that are not K-apt complexes) never belong to an area here.
    energy_query = select(EnergyMonthly).where(EnergyMonthly.use_ym.between(lo, hi), EnergyMonthly.usage_kwh.is_not(None), EnergyMonthly.grid_id.is_not(None))
    clause = sc.legal_clause(EnergyMonthly.sigungu_code)
    if clause is not None:
        energy_query = energy_query.where(clause)
    for r in db.scalars(energy_query):
        if r.source == "K-apt":
            continue  # the same K-apt months are read below from apartment_energy_monthly (every year, one parcel key)
        energy.append({"use_ym": r.use_ym, "energy_type": r.energy_type, "usage_kwh": r.usage_kwh, "grid_id": r.grid_id, "source": "HUB",
                       "kapt_code": (r.raw_record or {}).get("kapt_code"), "parcel": f"{r.sigungu_code}{r.bjdong_code}-{r.lot_type}-{r.bun}-{r.ji}"})
    try:
        from .kapt_energy import ApartmentEnergyMonthly
        kapt_query = select(ApartmentEnergyMonthly.complex_code, ApartmentEnergyMonthly.year_month, ApartmentEnergyMonthly.electricity_quantity).where(
            ApartmentEnergyMonthly.year_month.between(lo, hi), ApartmentEnergyMonthly.quality_status == "SUCCESS",
            ApartmentEnergyMonthly.electricity_quantity.is_not(None))
        seen: set[tuple[str, str]] = set()
        for code, ym, kwh in db.execute(kapt_query):
            info = complexes.get(code)
            if info is None or (code, ym) in seen:
                continue
            seen.add((code, ym))
            energy.append({"use_ym": ym, "energy_type": "ELECTRICITY", "usage_kwh": float(kwh), "grid_id": info.get("grid_id"), "source": "KAPT",
                           "kapt_code": code, "parcel": f"kapt:{code}"})
    except Exception:  # noqa: BLE001 - K-apt energy table not created yet
        db.rollback()
    weather = [{"use_ym": w.use_ym, "hdd": w.hdd, "cdd": w.cdd, "mean_temperature": w.mean_temperature, "source_type": w.source_type}
               for w in weather_rows(db, sc.code, lo, hi)]
    population, households = [], []
    try:
        from .sgis import SgisHouseholdAdmin, SgisPopulationAdmin
        mine = (lambda code: sc.owns_sgis(code)) if sc.sgis_codes else (lambda code: True)
        population = [{"adm_code": r.adm_code, "adm_name": r.adm_name, "reference_year": r.reference_year, "value": r.population_count if r.value_status == "OBSERVED" else None} for r in db.scalars(select(SgisPopulationAdmin)) if mine(r.adm_code)]
        households = [{"adm_code": r.adm_code, "adm_name": r.adm_name, "reference_year": r.reference_year, "value": r.household_count if r.value_status == "OBSERVED" else None} for r in db.scalars(select(SgisHouseholdAdmin)) if mine(r.adm_code)]
    except Exception:  # noqa: BLE001 - SGIS tables are optional
        db.rollback()
    factors = {}
    for f in db.scalars(select(EmissionFactor).order_by(EmissionFactor.reference_year)):
        if f.factor_unit == "kgCO2eq/kWh":
            factors[f.energy_type.lower()] = f.factor
    ids = sorted(region_ids)
    grids = [{"id": g.id, "geometry": (g.geojson or {}).get("geometry")}
             for start in range(0, len(ids), 2000) for g in db.scalars(select(Grid).where(Grid.id.in_(ids[start:start + 2000])))]
    register = []
    try:
        from .official import BuildingRegister, register_areas
        for r in db.scalars(select(BuildingRegister).where(BuildingRegister.grid_id.is_not(None))):
            if r.grid_id not in region_ids:
                continue
            attrs = r.attributes or {}
            register.append({"grid_id": r.grid_id, "approval_year": r.approval_year, "gfa": register_areas(attrs)[0], "use": attrs.get("building_use")})
    except Exception:  # noqa: BLE001 - register not collected yet (or columns not migrated)
        db.rollback()
    from .overlays import admin_features, grid_zoning_summary
    from .sgis_grid import grid_values
    from .energy_parcels import HUB_FIRST_YEAR, grid_building_energy, region_year_complete
    admin, admin_year = admin_features(db, sc=sc)
    building_energy = {}
    for year in years:
        if year >= HUB_FIRST_YEAR:  # 건축HUB answers from 2020-01 (전북 up to 2023-10 with the old 45xxx code)
            try:
                by_grid = grid_building_energy(db, year)
            except Exception:  # noqa: BLE001 - parcel_grid not built yet
                db.rollback()
                by_grid = {}
            by_grid = {g: v for g, v in by_grid.items() if g in region_ids}
            if by_grid:
                building_energy[year] = by_grid
    from .sgis_grid import parents
    zoning = {g: v for g, v in grid_zoning_summary(db).items() if g in region_ids}
    building_energy_complete = {year: region_year_complete(db, sc.code, year) for year in building_energy}
    return {"building_energy": building_energy, "building_energy_complete": building_energy_complete, "sgis_grid": grid_values(db, codes=parents(ids)), "register": register, "complexes": complexes, "energy": energy, "weather": weather, "population": population, "households": households,
            "factor": factors, "grids": grids, "admin": admin.get("features", []), "admin_year": admin_year, "zoning": zoning,
            "region": {"code": sc.code, "name": sc.name, "short_name": sc.short, "is_default": sc.is_default}}


_INPUTS: dict[tuple[Any, ...], tuple[float, dict[str, Any]]] = {}
INPUTS_TTL = 300.0  # seconds: new collections show up within five minutes


_REFRESHING: set[tuple[Any, ...]] = set()


def _key(years: list[int], region: str | None) -> tuple[Any, ...]:
    from .regions import DEFAULT_REGION
    return (region or DEFAULT_REGION, *years)


def forget_inputs() -> None:
    """Drop cached inputs (a region was prepared or re-collected)."""
    _INPUTS.clear()


def cached_inputs(db: Any, years: list[int], region: str | None = None) -> dict[str, Any]:
    """DB inputs for ``years`` of one region reused for a few minutes (changing the target or the plan re-analyses often).

    After the TTL the stale inputs are still answered at once while a background thread reloads them
    (a cold load takes ~10 s on the PC), so only the very first request of a year range waits.
    A narrower year range of a cached wider one (e.g. 2020~2025 inside 2015~2025) is cut from it instead of
    reloaded (18~30 s in the 2026-10-10 audit): ``subset_inputs`` keeps every row of the narrower load.
    """
    import time
    key = _key(years, region)
    hit = _INPUTS.get(key)
    if hit and time.monotonic() - hit[0] < INPUTS_TTL:
        return hit[1]
    if hit:
        _refresh_in_background(key)
        return hit[1]
    wider = next((k for k, (at, _) in sorted(_INPUTS.items(), key=lambda kv: -kv[1][0])
                  if k[0] == key[0] and time.monotonic() - at < INPUTS_TTL and k[1] <= years[0] and k[-1] >= years[-1]), None)
    if wider is not None:
        inputs = subset_inputs(db, _INPUTS[wider][1], years)
        _store_inputs(key, inputs)
        return inputs
    inputs = prepare_inputs(db, years, region)
    _store_inputs(key, inputs)
    return inputs


def subset_inputs(db: Any, wide: dict[str, Any], years: list[int]) -> dict[str, Any]:
    """The inputs ``load_inputs`` would give for ``years`` (a contiguous range inside ``wide['years']``).

    Year-bound rows (energy, weather, 건축HUB by year) are filtered by month; the rest (complexes, grids, boundaries,
    register, SGIS, factors) do not depend on the range. The region-wide intensity is recomputed for the range and
    the solar yield read again when the last year differs (both depend on the range)."""
    lo, hi = f"{years[0]}01", f"{years[-1]}12"
    inside = lambda ym: lo <= str(ym or "") <= hi  # noqa: E731
    out = dict(wide)
    out["energy"] = [r for r in wide["energy"] if inside(r.get("use_ym"))]
    out["weather"] = [w for w in wide["weather"] if inside(w.get("use_ym"))]
    wanted = set(years)
    out["building_energy"] = {y: v for y, v in (wide.get("building_energy") or {}).items() if y in wanted}
    out["building_energy_complete"] = {y: v for y, v in (wide.get("building_energy_complete") or {}).items() if y in wanted}
    out["city_intensity"] = city_intensity(out["energy"], out["complexes"], years)
    if years[-1] != wide["years"][-1]:
        from .solar import regional_pv_yield
        out["solar"] = regional_pv_yield(db, (wide.get("region") or {}).get("code"), up_to=years[-1])
    out["years"] = list(years)
    return out


def _store_inputs(key: tuple[Any, ...], inputs: dict[str, Any]) -> None:
    import time
    if len(_INPUTS) >= 3 and key not in _INPUTS:  # keep memory bounded: three region/year ranges at most
        _INPUTS.pop(min(_INPUTS, key=lambda k: _INPUTS[k][0]), None)
    _INPUTS[key] = (time.monotonic(), inputs)


def _refresh_in_background(key: tuple[Any, ...]) -> None:
    import threading
    if key in _REFRESHING:
        return
    _REFRESHING.add(key)

    def reload() -> None:
        try:
            from .db import Session
            with Session() as session:
                _store_inputs(key, prepare_inputs(session, list(key[1:]), key[0]))
        except Exception as exc:  # noqa: BLE001 - the stale inputs stay in use
            print("지역 분석 입력 갱신 실패:", type(exc).__name__, exc)
        finally:
            _REFRESHING.discard(key)
    threading.Thread(target=reload, name="area-inputs", daemon=True).start()


def warm_inputs(from_year: int = 2015, to_year: int = 2025) -> None:
    """Load the default year range once (called from the API start-up warm-up)."""
    from .db import Session
    with Session() as session:
        years = list(range(from_year, to_year + 1))
        key = _key(years, None)
        if key not in _INPUTS:
            _store_inputs(key, prepare_inputs(session, years))


def prepare_inputs(db: Any, years: list[int], region: str | None = None) -> dict[str, Any]:
    """DB rows for ``years`` plus the region-wide observed intensity (reusable across many areas)."""
    inputs = load_inputs(db, years, region)
    inputs["city_intensity"] = city_intensity(inputs["energy"], inputs["complexes"], years)
    from .solar import regional_pv_yield
    inputs["solar"] = regional_pv_yield(db, (inputs.get("region") or {}).get("code"), up_to=years[-1])
    inputs["years"] = list(years)
    return inputs


def analyze(db: Any, spec: dict[str, Any], from_year: int, to_year: int, event_year: int | None = None,
            window: int = 3, plan: dict[str, Any] | None = None, target_pct: float | None = None,
            pv_yield: float | None = None, *, inputs: dict[str, Any] | None = None, region: str | None = None,
            effort_basis: str = "apartments", measures: dict[str, Any] | None = None) -> dict[str, Any]:
    if from_year > to_year or to_year - from_year > 30:
        raise ValueError("분석 기간을 확인하세요 (최대 31년)")
    years = list(range(from_year, to_year + 1))
    if inputs is None or inputs.get("years") != years:
        inputs = cached_inputs(db, years, region)
    complex_points = [{"kapt_code": c["kapt_code"], "lon": c["lon"], "lat": c["lat"], "grid_id": c["grid_id"]} for c in inputs["complexes"].values()]
    area = resolve_area(spec, inputs["grids"], complex_points, inputs["admin"], inputs["zoning"])
    history = build_history(area, years, inputs)
    comparison = before_after(history, event_year, window)
    effort_result = effort(history, plan or {}, target_pct, pv_yield, effort_basis, measures) if target_pct is not None else None
    members = set(area["grid_ids"])
    grid_features = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "id": g["id"], "geometry": g["geometry"], "properties": {"id": g["id"]}}
        for g in inputs["grids"] if g["id"] in members and g.get("geometry")]}
    return {"history": history, "before_after": comparison, "effort": effort_result, "grid_features": grid_features,
            "facts": area_facts(history, comparison, effort_result), "admin_year": inputs["admin_year"],
            "region": inputs.get("region")}


# --------------------------------------------------------------------------- API
router = APIRouter(prefix="/api/areas", tags=["areas"])


class AreaSpec(BaseModel):
    type: str
    code: str | None = None
    grid_id: str | None = None
    lon: float | None = None
    lat: float | None = None
    radius_m: float | None = None
    category: str | None = None
    geometry: dict[str, Any] | None = None
    label: str | None = None


class PlanInput(BaseModel):
    added_floor_area_m2: float | None = Field(default=None, ge=0)
    removed_floor_area_m2: float | None = Field(default=None, ge=0)
    floors: float | None = Field(default=None, ge=0)
    building_count: float | None = Field(default=None, ge=0)
    footprint_per_building: float | None = Field(default=None, ge=0)


class MeasuresInput(BaseModel):
    """감축 수단 조합: 신축·기존 건물 전력 절감률과 태양광 용량 (도시·군기본계획의 수단별 감축량 합산 방식)."""
    new_efficiency_pct: float = Field(default=0, ge=0, le=100)
    existing_efficiency_pct: float = Field(default=0, ge=0, le=100)
    pv_kw: float = Field(default=0, ge=0, le=1_000_000)


class AnalyzeInput(BaseModel):
    area: AreaSpec
    region: str | None = Field(default=None, max_length=10)
    from_year: int = Field(default=2015, ge=2000, le=2100)
    to_year: int = Field(default=2025, ge=2000, le=2100)
    event_year: int | None = None
    window: int = Field(default=3, ge=1, le=5)
    plan: PlanInput | None = None
    target_pct: float | None = Field(default=None, ge=0, le=100)
    pv_yield_kwh_per_kw: float | None = Field(default=None, gt=0)
    # 감축 노력의 기준 건물: 공동주택(K-apt) 또는 건물 전체(건축HUB, 상가·업무 포함)
    effort_basis: Literal["apartments", "buildings"] = "apartments"
    measures: MeasuresInput | None = None


@router.get("/options")
def area_options(region: str | None = Query(None, max_length=10)) -> dict[str, Any]:
    from sqlalchemy import select
    from .db import Session
    from .models import EnergyMonthly
    from .regions import RegionNotReady, scope
    from .service import region_sector
    with Session() as db:
        try:
            sc = scope(db, region)
        except RegionNotReady as exc:
            raise HTTPException(404, str(exc)) from None
        from .overlays import admin_features, grid_zoning_summary
        admin, year = admin_features(db, sc=sc)
        zoning = {g: v for g, v in grid_zoning_summary(db).items() if g in sc.grid_ids}
        zone_counts: dict[str, int] = defaultdict(int)
        for z in zoning.values():
            if z.get("dominant_zone"):
                zone_counts[z["dominant_zone"]] += 1
        month_query = select(EnergyMonthly.use_ym).distinct()
        clause = sc.legal_clause(EnergyMonthly.sigungu_code)
        if clause is not None:
            month_query = month_query.where(clause)
        months = sorted({r for r in db.scalars(month_query)})
        sector = region_sector(db, sc)
        return {
            "admin": sorted(({"code": f["properties"]["adm_code"], "name": short_admin_name(f["properties"]["adm_name"])} for f in admin.get("features", [])), key=lambda x: x["name"] or ""),
            "admin_geojson": {"type": "FeatureCollection", "features": [
                {"type": "Feature", "geometry": f["geometry"], "properties": {"adm_code": f["properties"]["adm_code"], "name": short_admin_name(f["properties"]["adm_name"]), "population": f["properties"].get("population")}}
                for f in admin.get("features", [])]},
            "admin_year": year,
            "zones": [{"category": k, "label": ZONE_LABEL[k], "grids": v} for k, v in sorted(zone_counts.items(), key=lambda kv: -kv[1]) if k in ZONE_LABEL],
            "energy_years": sorted({int(m[:4]) for m in months if m and len(m) == 6}),
            "default_grid": sector.grid_id if sector else None,
            "region": {"code": sc.code, "name": sc.name, "short_name": sc.short, "center": list(sc.center) if sc.center else None, "bbox": list(sc.bbox) if sc.bbox else None},
        }


@router.get("/benchmark")
def area_benchmark(region: str | None = Query(None, max_length=10), from_year: int = Query(2015, ge=2000, le=2100),
                   to_year: int = Query(2025, ge=2000, le=2100), basis: Literal["apartments", "buildings"] = "apartments") -> dict[str, Any]:
    """같은 시·군·구 행정동의 관측 전력 원단위 분포 (구역이 그 가운데 어디쯤인지 보는 비교 기준)."""
    from .db import Session
    from .regions import RegionNotReady
    if from_year > to_year or to_year - from_year > 30:
        raise HTTPException(422, "분석 기간을 확인하세요 (최대 31년)")
    with Session() as db:
        try:
            return benchmark(db, list(range(from_year, to_year + 1)), region, basis)
        except RegionNotReady as exc:
            raise HTTPException(404, str(exc)) from None


@router.get("/collection")
def area_collection_status() -> dict[str, Any]:
    """Past-year back-fill progress (``scripts\\dss.cmd CollectHistory``) for the area screen."""
    from .history import history_status
    return history_status()


@router.post("/analyze")
def area_analyze(request: AnalyzeInput) -> dict[str, Any]:
    from .db import Session
    from .regions import RegionNotReady
    with Session() as db:
        try:
            return analyze(db, request.area.model_dump(), request.from_year, request.to_year, request.event_year,
                           request.window, request.plan.model_dump() if request.plan else None, request.target_pct,
                           request.pv_yield_kwh_per_kw, region=request.region, effort_basis=request.effort_basis,
                           measures=request.measures.model_dump() if request.measures else None)
        except RegionNotReady as exc:
            raise HTTPException(404, str(exc)) from None
        except (ValueError, KeyError) as exc:
            raise HTTPException(422, str(exc)) from None
