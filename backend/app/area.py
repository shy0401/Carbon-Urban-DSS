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
from typing import Any, Iterable

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

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
                  years: list[int]) -> dict[int, dict[str, Any]]:
    """Annual observed energy of the area per year.

    rows: {use_ym 'YYYYMM', energy_type, usage_kwh, grid_id, kapt_code|None, parcel}
    A row belongs to the area through its complex (point in area) or, without a complex,
    through its grid. Only parcels with 12 observed months enter the annual sum.
    """
    grid_ids, codes = set(area["grid_ids"]), set(area["complex_codes"])
    wanted = {str(y) for y in years}
    months: dict[tuple[str, str, int], dict[str, float]] = defaultdict(dict)
    parcel_code: dict[str, str | None] = {}
    for row in rows:
        ym, value = str(row.get("use_ym") or ""), row.get("usage_kwh")
        if len(ym) != 6 or ym[:4] not in wanted or value is None:
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
            complete = {p: m for p, m in parcels.items() if len(m) == 12}
            total = sum(sum(m.values()) for m in complete.values()) if complete else None
            by_cohort: dict[str, float] = defaultdict(float)
            area_m2 = 0.0
            area_kwh = 0.0
            households = 0
            household_kwh = 0.0
            for parcel, m in complete.items():
                code = parcel_code.get(parcel)
                info = complexes.get(code) if code else None
                cohort = str(info["approval_year"]) if info and info.get("approval_year") else "미상"
                by_cohort[cohort] += sum(m.values())
                if info and info.get("floor_area_ok"):
                    area_m2 += info["gfa"]
                    area_kwh += sum(m.values())
                if info and info.get("households"):
                    households += int(info["households"])
                    household_kwh += sum(m.values())
            entry[key] = {
                "kwh": round(total, 1) if total is not None else None,
                "observed_parcels": len(parcels), "complete_parcels": len(complete),
                "partial_parcels": len(parcels) - len(complete),
                "months_max": max((len(m) for m in parcels.values()), default=0),
                "by_cohort": {k: round(v, 1) for k, v in sorted(by_cohort.items())},
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
    result: dict[str, Any] = {"available": True, "event_year": event_year, "window": window,
                              "before_years": before_years, "after_years": after_years,
                              "event": events.get(event_year), "metrics": {}}
    for energy in ("electricity", "gas"):
        before_total = _mean([history["energy"][y][energy]["kwh"] for y in before_years])
        after_total = _mean([history["energy"][y][energy]["kwh"] for y in after_years])
        before_existing = _mean([cohort_sum(y, energy, is_existing) for y in before_years])
        after_existing = _mean([cohort_sum(y, energy, is_existing) for y in after_years])
        after_new = _mean([cohort_sum(y, energy, is_new) for y in after_years])
        result["metrics"][energy] = {
            "before_total_kwh": before_total, "after_total_kwh": after_total,
            "total_change_kwh": round(after_total - before_total, 1) if before_total is not None and after_total is not None else None,
            "total_change_pct": round((after_total - before_total) / before_total * 100, 1) if before_total and after_total is not None else None,
            "existing_before_kwh": before_existing, "existing_after_kwh": after_existing,
            "existing_change_pct": round((after_existing - before_existing) / before_existing * 100, 1) if before_existing and after_existing is not None else None,
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


def effort(history: dict[str, Any], plan: dict[str, Any], target_pct: float, pv_yield_kwh_per_kw: float | None = None) -> dict[str, Any]:
    """How much reduction a future development needs to meet a target.

    baseline = latest year with a complete observed electricity total in the area;
    new load  = planned added floor area × the area's observed electricity intensity;
    target    = baseline carbon × (1 − target %).
    Returns the required efficiency for new buildings only, for all buildings, and the
    electricity that on-site generation would have to offset. Electricity only unless a
    gas factor is registered.
    """
    if not (0 <= target_pct <= 100):
        raise ValueError("목표 감축률은 0~100% 입니다")
    factor = history.get("factor", {}).get("electricity")
    base_year = next((y for y in sorted(history["energy"], reverse=True)
                      if history["energy"][y]["electricity"]["kwh"] is not None and history["energy"][y]["electricity"]["intensity_kwh_per_m2"]), None)
    if not factor:
        return {"available": False, "reason": "전력 배출계수가 등록되어 있지 않습니다"}
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
    added = plan.get("added_floor_area_m2")
    if added is None and plan.get("floors") and plan.get("building_count") and plan.get("footprint_per_building"):
        added = float(plan["floors"]) * float(plan["building_count"]) * float(plan["footprint_per_building"])
    added = float(added or 0)
    removed = float(plan.get("removed_floor_area_m2") or 0)
    if added < 0 or removed < 0:
        raise ValueError("면적은 0 이상이어야 합니다")
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
        "baseline_mode": baseline_mode, "data_class": "SCENARIO",
        "intensity_kwh_per_m2": intensity, "intensity_area_m2": basis_area,
        "added_floor_area_m2": round(added, 1), "removed_floor_area_m2": round(removed, 1),
        "baseline_kwh": round(base_kwh, 1), "baseline_kgco2eq": round(base_c, 1),
        "new_load_kwh": round(new_kwh, 1), "bau_kwh": round(bau_kwh, 1), "bau_kgco2eq": round(bau_c, 1),
        "target_kgco2eq": round(target_c, 1), "required_reduction_kgco2eq": round(need_c, 1),
        "already_met": need_c <= 0, "feasible_with_new_only": feasible_new_only or need_c <= 0,
        "options": options, "curve": curve, "factor_kgco2eq_per_kwh": factor,
        "scope": "전력 운영탄소 기준 (가스는 배출계수 확정 후 추가)",
        "assumptions": [
            (f"신축 부하 = 계획 연면적 × 지역 관측 전력 원단위 {intensity:,.2f} kWh/m²·년 ({base_year}년, 연면적 {basis_area:,.0f}m² 기준)" if baseline_mode == "OBSERVED"
             else f"지역 관측이 없어 기준 부하를 추정했습니다: 단지 연면적 {basis_area:,.0f}m² × 전주 관측 원단위 {intensity:,.2f} kWh/m²·년"),
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
    city = yearly_energy(energy_rows, everything, complexes, years)
    for year in sorted(city, reverse=True):
        item = city[year]["electricity"]
        if item["intensity_kwh_per_m2"]:
            return {"year": year, "kwh_per_m2": item["intensity_kwh_per_m2"], "area_m2": item["intensity_area_m2"], "parcels": item["complete_parcels"]}
    return None


def build_history(area: dict[str, Any], years: list[int], inputs: dict[str, Any]) -> dict[str, Any]:
    complexes = inputs["complexes"]
    history = {
        "years": years, "area": {k: v for k, v in area.items()},
        "energy": yearly_energy(inputs["energy"], area, complexes, years),
        "weather": yearly_weather(inputs["weather"], years),
        "population": yearly_population(inputs["population"], inputs["households"], area, years),
        "events": development_events(area, complexes, years),
        "factor": inputs.get("factor", {}),
        "factor_basis": "최신 등록 전력 계수를 모든 연도에 동일 적용(연도별 계수 미등록). 전후 차이는 사용량 변화만 반영",
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
    city = inputs.get("city_intensity")
    history["city_intensity"] = city
    for year in years:
        gfa = history["stock"][year]["gfa_m2"]
        kwh = round(gfa * city["kwh_per_m2"], 1) if city and gfa else None
        history["energy"][year]["estimated"] = {
            "kwh": kwh, "carbon_kgco2eq": round(kwh * factor, 1) if kwh is not None and factor else None,
            "basis": f"사용승인된 단지 연면적 × 전주 관측 전력 원단위 {city['kwh_per_m2']:,.2f} kWh/m²·년({city['year']}년)" if city else None,
            "data_class": "ESTIMATED",
        }
    years_with_energy = [y for y in years if history["energy"][y]["electricity"]["kwh"] is not None]
    history["coverage"] = {
        "energy_years": years_with_energy,
        "weather_years": [y for y in years if history["weather"][y]["complete"]],
        "population_years": [y for y in years if history["population"][y]["population"] is not None],
        "grid_count": len(area["grid_ids"]), "complex_count": len(area["complex_codes"]),
    }
    return history


def area_facts(history: dict[str, Any], comparison: dict[str, Any] | None = None, effort_result: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Verified sentences with the exact numbers they contain (for the report and the LLM checker)."""
    area = history["area"]
    facts: list[dict[str, Any]] = []

    def add(fid: str, text: str, *numbers: float | int | None) -> None:
        facts.append({"id": fid, "text": text, "numbers": [n for n in numbers if n is not None]})

    y0, y1 = history["years"][0], history["years"][-1]
    add("scope", f"분석 대상은 {area['label']}이고 기간은 {y0}~{y1}년입니다. 격자 {len(area['grid_ids'])}개와 공동주택 단지 {len(area['complex_codes'])}개가 포함됩니다.", y0, y1, len(area["grid_ids"]), len(area["complex_codes"]))
    cov = history["coverage"]
    if cov["energy_years"]:
        add("coverage", f"12개월 전력 관측이 있는 연도는 {len(cov['energy_years'])}개({', '.join(map(str, cov['energy_years']))})입니다.", len(cov["energy_years"]), *cov["energy_years"])
    else:
        add("coverage", "12개월이 모두 관측된 전력 자료가 있는 연도가 없어 연간 에너지와 탄소를 계산하지 않았습니다.")
    built = [(y, e) for y, e in history["events"].items() if e["complexes"]]
    if built:
        total_households = sum(e["households"] for _, e in built)
        add("development", f"분석 기간에 사용승인된 단지는 {sum(e['complexes'] for _, e in built)}개, {total_households:,}세대입니다.", sum(e["complexes"] for _, e in built), total_households)
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
            add("before_after", f"개발 전 {len(comparison['before_years'])}년 평균 전력은 {m['before_total_kwh']:,.0f} kWh, 개발 후 {len(comparison['after_years'])}년 평균은 {m['after_total_kwh']:,.0f} kWh입니다.", len(comparison["before_years"]), m["before_total_kwh"], len(comparison["after_years"]), m["after_total_kwh"])
            if m["total_change_pct"] is not None:
                add("change", f"지역 전력은 {m['total_change_pct']:+,.1f}% 변했습니다.", m["total_change_pct"])
        if m["new_development_kwh"] is not None:
            add("new_share", f"새로 준공된 단지의 연평균 전력은 {m['new_development_kwh']:,.0f} kWh로 개발 후 지역 전력의 {m['new_share_pct']:,.1f}%입니다.", m["new_development_kwh"], m["new_share_pct"])
        est = comparison["metrics"].get("estimated") or {}
        if (m["before_total_kwh"] is None or m["after_total_kwh"] is None) and est.get("event_change_pct") is not None:
            add("estimated_change", f"관측이 부족해 연면적으로 추정하면, 이 개발로 단지 연면적이 {est['added_gfa_m2']:,.0f}m²({est['event_change_pct']:+,.1f}%) 늘어 연간 전력 부하가 약 {est['event_added_kwh']:,.0f} kWh 늘어난 것으로 추정됩니다(추정값).", est["added_gfa_m2"], est["event_change_pct"], est["event_added_kwh"])
        for gap in comparison.get("gaps", []):
            add(f"gap_{len(facts)}", gap)
    if effort_result and effort_result.get("available"):
        o = effort_result["options"]
        if effort_result.get("baseline_mode") == "ESTIMATED":
            city = history.get("city_intensity") or {}
            add("effort_basis", f"이 지역은 관측 전력이 없어 기준 부하를 단지 연면적 {effort_result['intensity_area_m2']:,.0f}m²와 전주 관측 원단위 {effort_result['intensity_kwh_per_m2']:,.2f} kWh/m²·년({city.get('year')}년, 관측 지번 {city.get('parcels')}곳 기준)으로 추정했습니다. 관측 지번이 적을수록 추정 오차가 큽니다.", effort_result["intensity_area_m2"], effort_result["intensity_kwh_per_m2"], city.get("year"), city.get("parcels"))
        add("effort_target", f"{effort_result['baseline_year']}년 대비 {effort_result['target_pct']:,.0f}% 감축을 목표로 하면 계획 반영 후 연간 {effort_result['required_reduction_kgco2eq']:,.0f} kgCO2eq를 줄여야 합니다.", effort_result["baseline_year"], effort_result["target_pct"], effort_result["required_reduction_kgco2eq"])
        if effort_result["already_met"]:
            add("effort_met", "계획을 반영해도 목표 이하이므로 추가 감축이 필요하지 않습니다.")
        else:
            if o["new_only_efficiency_pct"] is not None:
                add("effort_new", f"신축만으로 달성하려면 신축 전력 소비를 {o['new_only_efficiency_pct']:,.1f}% 줄여야 합니다." + (" 100%를 넘어 신축만으로는 달성할 수 없습니다." if o["new_only_efficiency_pct"] > 100 else ""), o["new_only_efficiency_pct"])
            if o["all_buildings_efficiency_pct"] is not None:
                add("effort_all", f"기존 건물까지 함께 줄이면 지역 전체 전력 소비를 {o['all_buildings_efficiency_pct']:,.1f}% 줄여야 합니다.", o["all_buildings_efficiency_pct"])
            add("effort_offset", f"같은 목표를 재생에너지로 상쇄하려면 연간 {o['offset_kwh_per_year']:,.0f} kWh가 필요합니다.", o["offset_kwh_per_year"])
    add("rules", "관측이 없는 연도는 0이 아니라 자료 없음으로 두었고, 행정동 통계는 격자에 배분하지 않았습니다.", 0)
    return facts


# --------------------------------------------------------------------------- DB loaders
def load_inputs(db: Any, years: list[int]) -> dict[str, Any]:
    from sqlalchemy import select
    from .kapt import ApartmentComplex
    from .models import EmissionFactor, EnergyMonthly, Grid, WeatherMonthly
    complexes: dict[str, dict[str, Any]] = {}
    for row in db.scalars(select(ApartmentComplex)):
        complexes[row.kapt_code] = {
            "kapt_code": row.kapt_code, "name": row.name, "approval_date": row.approval_date,
            "approval_year": approval_year(row.approval_date), "households": row.households,
            "gfa": row.gross_floor_area_m2, "floor_area_ok": floor_area_ok(row.gross_floor_area_m2, row.households, row.management_area_m2),
            "lon": row.longitude, "lat": row.latitude, "grid_id": row.grid_id, "heating_type": row.heating_type,
        }
    lo, hi = f"{years[0]}01", f"{years[-1]}12"
    energy = []
    for r in db.scalars(select(EnergyMonthly).where(EnergyMonthly.use_ym.between(lo, hi), EnergyMonthly.usage_kwh.is_not(None))):
        energy.append({"use_ym": r.use_ym, "energy_type": r.energy_type, "usage_kwh": r.usage_kwh, "grid_id": r.grid_id,
                       "kapt_code": (r.raw_record or {}).get("kapt_code"), "parcel": f"{r.sigungu_code}{r.bjdong_code}-{r.lot_type}-{r.bun}-{r.ji}"})
    weather = [{"use_ym": w.use_ym, "hdd": w.hdd, "cdd": w.cdd, "mean_temperature": w.mean_temperature, "source_type": w.source_type}
               for w in db.scalars(select(WeatherMonthly).where(WeatherMonthly.use_ym.between(lo, hi)))]
    population, households = [], []
    try:
        from .sgis import SgisHouseholdAdmin, SgisPopulationAdmin
        population = [{"adm_code": r.adm_code, "adm_name": r.adm_name, "reference_year": r.reference_year, "value": r.population_count if r.value_status == "OBSERVED" else None} for r in db.scalars(select(SgisPopulationAdmin))]
        households = [{"adm_code": r.adm_code, "adm_name": r.adm_name, "reference_year": r.reference_year, "value": r.household_count if r.value_status == "OBSERVED" else None} for r in db.scalars(select(SgisHouseholdAdmin))]
    except Exception:  # noqa: BLE001 - SGIS tables are optional
        db.rollback()
    factors = {}
    for f in db.scalars(select(EmissionFactor).order_by(EmissionFactor.reference_year)):
        if f.factor_unit == "kgCO2eq/kWh":
            factors[f.energy_type.lower()] = f.factor
    grids = [{"id": g.id, "geometry": (g.geojson or {}).get("geometry")} for g in db.scalars(select(Grid))]
    from .overlays import admin_features, grid_zoning_summary
    admin, admin_year = admin_features(db)
    return {"complexes": complexes, "energy": energy, "weather": weather, "population": population, "households": households,
            "factor": factors, "grids": grids, "admin": admin.get("features", []), "admin_year": admin_year, "zoning": grid_zoning_summary(db)}


def prepare_inputs(db: Any, years: list[int]) -> dict[str, Any]:
    """DB rows for ``years`` plus the city-wide observed intensity (reusable across many areas)."""
    inputs = load_inputs(db, years)
    inputs["city_intensity"] = city_intensity(inputs["energy"], inputs["complexes"], years)
    inputs["years"] = list(years)
    return inputs


def analyze(db: Any, spec: dict[str, Any], from_year: int, to_year: int, event_year: int | None = None,
            window: int = 3, plan: dict[str, Any] | None = None, target_pct: float | None = None,
            pv_yield: float | None = None, *, inputs: dict[str, Any] | None = None) -> dict[str, Any]:
    if from_year > to_year or to_year - from_year > 30:
        raise ValueError("분석 기간을 확인하세요 (최대 31년)")
    years = list(range(from_year, to_year + 1))
    if inputs is None or inputs.get("years") != years:
        inputs = prepare_inputs(db, years)
    complex_points = [{"kapt_code": c["kapt_code"], "lon": c["lon"], "lat": c["lat"], "grid_id": c["grid_id"]} for c in inputs["complexes"].values()]
    area = resolve_area(spec, inputs["grids"], complex_points, inputs["admin"], inputs["zoning"])
    history = build_history(area, years, inputs)
    comparison = before_after(history, event_year, window)
    effort_result = effort(history, plan or {}, target_pct, pv_yield) if target_pct is not None else None
    members = set(area["grid_ids"])
    grid_features = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "id": g["id"], "geometry": g["geometry"], "properties": {"id": g["id"]}}
        for g in inputs["grids"] if g["id"] in members and g.get("geometry")]}
    return {"history": history, "before_after": comparison, "effort": effort_result, "grid_features": grid_features,
            "facts": area_facts(history, comparison, effort_result), "admin_year": inputs["admin_year"]}


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


class AnalyzeInput(BaseModel):
    area: AreaSpec
    from_year: int = Field(default=2015, ge=2000, le=2100)
    to_year: int = Field(default=2025, ge=2000, le=2100)
    event_year: int | None = None
    window: int = Field(default=3, ge=1, le=5)
    plan: PlanInput | None = None
    target_pct: float | None = Field(default=None, ge=0, le=100)
    pv_yield_kwh_per_kw: float | None = Field(default=None, gt=0)


@router.get("/options")
def area_options() -> dict[str, Any]:
    from sqlalchemy import select
    from .db import Session
    from .models import EnergyMonthly, TestbedSector
    with Session() as db:
        from .overlays import admin_features, grid_zoning_summary
        admin, year = admin_features(db)
        zoning = grid_zoning_summary(db)
        zone_counts: dict[str, int] = defaultdict(int)
        for z in zoning.values():
            if z.get("dominant_zone"):
                zone_counts[z["dominant_zone"]] += 1
        months = sorted({r for r in db.scalars(select(EnergyMonthly.use_ym).distinct())})
        sector = db.get(TestbedSector, "prototype")
        return {
            "admin": sorted(({"code": f["properties"]["adm_code"], "name": short_admin_name(f["properties"]["adm_name"])} for f in admin.get("features", [])), key=lambda x: x["name"] or ""),
            "admin_geojson": {"type": "FeatureCollection", "features": [
                {"type": "Feature", "geometry": f["geometry"], "properties": {"adm_code": f["properties"]["adm_code"], "name": short_admin_name(f["properties"]["adm_name"]), "population": f["properties"].get("population")}}
                for f in admin.get("features", [])]},
            "admin_year": year,
            "zones": [{"category": k, "label": ZONE_LABEL[k], "grids": v} for k, v in sorted(zone_counts.items(), key=lambda kv: -kv[1]) if k in ZONE_LABEL],
            "energy_years": sorted({int(m[:4]) for m in months if m and len(m) == 6}),
            "default_grid": sector.grid_id if sector else None,
        }


@router.get("/collection")
def area_collection_status() -> dict[str, Any]:
    """Past-year back-fill progress (``scripts\\dss.cmd CollectHistory``) for the area screen."""
    from .history import history_status
    return history_status()


@router.post("/analyze")
def area_analyze(request: AnalyzeInput) -> dict[str, Any]:
    from .db import Session
    with Session() as db:
        try:
            return analyze(db, request.area.model_dump(), request.from_year, request.to_year, request.event_year,
                           request.window, request.plan.model_dump() if request.plan else None, request.target_pct,
                           request.pv_yield_kwh_per_kw)
        except (ValueError, KeyError) as exc:
            raise HTTPException(422, str(exc)) from None
