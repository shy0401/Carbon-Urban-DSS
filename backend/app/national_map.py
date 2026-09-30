"""전국 지도: 시·도와 시·군·구를 전국 공통 자료로 비교하고, 지도나 메뉴에서 골라 들어가는 첫 단계.

지도 분석의 순서는 전국(시·도 → 그 시·도의 시·군·구) → 시·도 500m 격자 → 시·군·구 · 읍면동이다.
이 모듈은 앞 단계(전국)를 맡는다.

* 단위
  - 시·도 17곳(법정 2자리 코드). 전남광주통합특별시처럼 SGIS 시도 코드가 둘인 곳은 합친다.
  - 시·군·구: 법정 분석 단위(수원시처럼 일반구를 묶은 시) + SGIS에만 있고 법정 단위에 연결하지 못한 곳(연결 안 됨).
* 지표 (모두 전국에 있는 자료만, 없으면 0이 아니라 비움)
  - 인구·가구·면적·인구밀도: SGIS 행정구역 통계(시군구 합, 최근 연도).
  - 500m 인구와 2015년 대비 증감률, 500m 주택·종사자: SGIS 500m 격자 통계(자료제공 신청분)를 공식 500m 격자의
    시군구 코드로 모은 값(경계에 걸친 격자는 걸친 시군구에 똑같이 나눔). 받은 묶음에 없는 100km 블록이 있으므로, 그 지역 격자 중 파일이 있는 블록에 사는 사람의
    비중(2024 1km 격자 인구 기준)을 함께 센다. 합계는 그 비중이 99% 이상일 때만 보여 주고 빠진 몫을 적으며,
    그보다 낮으면 비운다(일부 합을 실제 합처럼 보여 주지 않음). 증감률은 두 해 모두 파일이 있는 같은 블록끼리
    비교하고 비중이 95% 이상일 때만 낸다.
  - K-apt 공동주택 단지 수: 전국 단지 목록.
  - 온실가스: 온실가스종합정보센터 지역 온실가스 인벤토리(시·군·구, 최근 2023년, ``regional_stats``). 총배출량(VKT 기준),
    건물 등(가정·상업·공공·농림어업의 연료 + 전력·열 간접), 2018년 대비 건물 등 증감률. 개편 전 이름이라 2026년에 새로
    생긴 인천 네 구는 비우고, 개편 전 자치구(중구·동구·서구, 연결 안 됨)에 값을 둔다.
  - 전력: 한전 시군구별 전력판매량(최근 12개월이 모두 있는 해). 합계, 건물 전력(주택용+일반용+교육용), 2018년 대비
    건물 전력 증감률, 가구당 주택용 전력(SGIS 가구와 같은 해).
  - 도시가스 판매량: 한국가스공사 시·도 월별(시·도 요약에만, 시·군·구 단위 자료 없음).
  - 에너지 사용량(전력·가스 관측): 전국 자료가 없다(지역마다 수집). 칠하지 않고, 어느 시·군·구에 K-apt 월별 에너지·
    건축HUB 건물 에너지가 있는지만 적는다.
* 경계: SGIS 시군구 경계(10m 단순화 원본)를 시·도는 400m, 시·군·구는 150m로 다시 단순화(표시용).
* 무거운 부분(경계·500m 합계)은 자료 행 수가 바뀔 때만 다시 만들고 ``data/cache/national-map/``에 둔다.
  지역 수준(상세·기본)과 에너지 유무는 요청 때마다 붙인다.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Iterable

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from sqlalchemy import func, select, text

from .db import Session

router = APIRouter(prefix="/api/map", tags=["map"])

PAYLOAD_VERSION = 5
MIN_BASE = 20  # 증감률: 두 해 모두 이만큼은 있어야 한다
FIELDS = ["population", "households", "area_km2", "density", "pop500", "pop500_base", "pop_change_pct", "housing500", "workers500", "complexes",
          "ghg_total", "ghg_building", "ghg_building_change_pct",
          "elec_total", "elec_building", "elec_building_change_pct", "elec_home_per_household"]
GHG_FIELDS = ("ghg_total", "ghg_building", "ghg_building_change_pct")
ELEC_FIELDS = ("elec_total", "elec_building", "elec_building_change_pct", "elec_home_per_household")
_MEMORY: dict[str, Any] = {}
_DYNAMIC: dict[str, Any] = {}

UNITS_SQL = """
SELECT adm_code, adm_name, region_code, population, households, area_m2
FROM national_units WHERE year = :y AND level = 'SIGUNGU' ORDER BY adm_code
"""
# A 500m cell on a 시군구 boundary lists every 시군구 it touches (adm_cd "24050,36630", 6.6% of cells). Its values are
# split equally among them. Measured against SGIS 행정구역 인구 2024 (238 시군구): giving the whole cell to the first
# code matched within ±3% for 45% of 시군구 (±10%: 76%), the equal split for 71% (±10%: 98%).
CELL_SHARES = """
SELECT grid_cd, left(grid_cd, 2) AS block, x_min, y_min, unnest(codes) AS sgis, 1.0 / cardinality(codes) AS share
FROM (SELECT grid_cd, x_min, y_min, string_to_array(adm_cd, ',') AS codes FROM sgis_official_grid_cells WHERE size_m = 500) c
"""
GRID500_SQL = f"""
WITH u AS ({CELL_SHARES})
SELECT u.sgis, u.block, v.year, count(*) AS cells,
       sum(v.population * u.share) AS pop, sum(v.households * u.share) AS hh, sum(v.housing * u.share) AS housing, sum(v.workers * u.share) AS workers
FROM sgis_grid500_values v JOIN u ON u.grid_cd = v.grid_cd
WHERE v.year = ANY(:years)
GROUP BY 1, 2, 3
"""
WEIGHTS_SQL = f"""
WITH k AS (
  SELECT c.x_min::bigint AS x, c.y_min::bigint AS y, s.value AS pop
  FROM sgis_grid_cells c JOIN sgis_grid_stats s ON s.grid_cd = c.grid_cd AND s.year = c.year
  WHERE c.year = :y1k AND c.size_m = 1000 AND s.item = 'to_in_001'
), u AS ({CELL_SHARES})
SELECT u.sgis, u.block, sum(u.share) AS cells, coalesce(sum(k.pop * u.share), 0) / 4.0 AS people
FROM u
LEFT JOIN k ON k.x = (floor(u.x_min / 1000) * 1000)::bigint AND k.y = (floor(u.y_min / 1000) * 1000)::bigint
GROUP BY 1, 2
"""
REGION_GEOM_SQL = """
WITH g AS (
  SELECT region_code AS code, ST_Union(geom) AS geom FROM national_units
  WHERE year = :y AND level = 'SIGUNGU' AND region_code IS NOT NULL AND geom IS NOT NULL GROUP BY region_code
  UNION ALL
  SELECT 'sgis:' || adm_code, geom FROM national_units WHERE year = :y AND level = 'SIGUNGU' AND region_code IS NULL AND geom IS NOT NULL
)
SELECT code, ST_AsGeoJSON(ST_Transform(ST_SimplifyPreserveTopology(geom, 150), 4326), 5) AS g,
       ST_X(ST_Transform(ST_PointOnSurface(geom), 4326)) AS lon, ST_Y(ST_Transform(ST_PointOnSurface(geom), 4326)) AS lat
FROM g
"""
PROVINCE_GEOM_SQL = """
WITH m AS (SELECT * FROM unnest(CAST(:sgis AS text[]), CAST(:legal AS text[])) AS t(sgis, legal)),
g AS (
  SELECT m.legal AS code, ST_Union(ST_CollectionExtract(ST_MakeValid(ST_SnapToGrid(u.geom, 25)), 3)) AS geom
  FROM national_units u JOIN m ON m.sgis = left(u.adm_code, 2)
  WHERE u.year = :y AND u.level = 'SIGUNGU' AND u.geom IS NOT NULL GROUP BY 1
)
SELECT code, ST_AsGeoJSON(ST_Transform(ST_SimplifyPreserveTopology(geom, 400), 4326), 4) AS g,
       ST_X(ST_Transform(ST_PointOnSurface(geom), 4326)) AS lon, ST_Y(ST_Transform(ST_PointOnSurface(geom), 4326)) AS lat
FROM g
"""


# --------------------------------------------------------------------------- pure aggregation (tested without a database)
GRID_FIELDS = {"pop500": ("pop", "인구", "year"), "pop500_base": ("pop", "인구", "base"), "housing500": ("housing", "주택", "year"), "workers500": ("workers", "종사자", "year")}
TOTAL_MIN = 0.99   # 합계는 빠진 블록에 사는 인구가 1% 미만일 때만 보여 준다 (그 비율을 함께 적음)
CHANGE_MIN = 0.95  # 증감률은 두 해 모두 있는 블록이 인구의 95% 이상일 때만 (같은 블록끼리 비교)


def _num(value: Any) -> float | int | None:
    if value is None:
        return None
    value = float(value)
    return int(value) if value.is_integer() else round(value, 1)


def change_pct(before: float | None, after: float | None) -> float | None:
    if before is None or after is None or before < MIN_BASE or after < MIN_BASE:
        return None
    return round((after - before) / before * 100, 1)


def _pct(share: float) -> str:
    """'0.5%', '0.1% 미만', '99.4%'."""
    value = share * 100
    return "0.1% 미만" if 0 < value < 0.1 else f"{value:.1f}".rstrip("0").rstrip(".") + "%"


def _names(blocks: Iterable[str]) -> str:
    blocks = sorted(blocks)
    return f"{'·'.join(blocks[:4])}{' 등' if len(blocks) > 4 else ''}"


def unit_grid500(sums: dict[tuple[str, int], dict[str, float | None]], weights: dict[str, float], received: dict[tuple[str, int], set[str]],
                 year: int | None, base: int | None) -> dict[str, dict[str, Any]]:
    """500m sums of one SGIS 시군구 over the blocks that have a file, with how much of the unit they cover.

    ``weights``: {100km block: weight of the unit's cells in it} (the 1km grid population, so a block counts by the people
    living in it). A total covers ``covered / total`` of the unit; the change compares the same blocks in both years."""
    total = float(sum(weights.values()))
    out: dict[str, dict[str, Any]] = {}
    for field, (column, theme, which) in GRID_FIELDS.items():
        y = year if which == "year" else (base if base and base != year else None)
        have = received.get((theme, y), set()) if y else set()
        inside = [b for b in weights if b in have]
        values = [v for v in (sums.get((b, y), {}).get(column) for b in inside) if v is not None] if y else []
        out[field] = {"sum": float(sum(values)) if values else None, "covered": float(sum(weights[b] for b in inside)), "total": total,
                      "missing": sorted(set(weights) - set(inside)), "theme": theme, "year": y}
    both = [b for b in weights if year and base and base != year and b in received.get(("인구", year), set()) and b in received.get(("인구", base), set())]
    now = [v for v in (sums.get((b, year), {}).get("pop") for b in both) if v is not None]
    then = [v for v in (sums.get((b, base), {}).get("pop") for b in both) if v is not None]
    out["change"] = {"now": float(sum(now)) if now else None, "base": float(sum(then)) if then else None, "covered": float(sum(weights[b] for b in both)),
                     "total": total, "missing": sorted(set(weights) - set(both)), "theme": "인구", "year": year}
    return out


def merge_grid(parts: list[dict[str, dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    """Group of units: partial sums and coverage weights add up; missing blocks are pooled."""
    out: dict[str, dict[str, Any]] = {}
    for field in (*GRID_FIELDS, "change"):
        rows = [p[field] for p in parts if field in p]
        merged: dict[str, Any] = {"covered": sum(r["covered"] for r in rows), "total": sum(r["total"] for r in rows),
                                  "missing": sorted(set().union(*(r["missing"] for r in rows))) if rows else [],
                                  "theme": rows[0]["theme"] if rows else None, "year": rows[0]["year"] if rows else None}
        for key in (("now", "base") if field == "change" else ("sum",)):
            values = [r[key] for r in rows if r.get(key) is not None]
            merged[key] = float(sum(values)) if values else None
        out[field] = merged
    return out


def grid_values(grid: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], dict[str, str]]:
    """Display values and notes: a total only when the blocks with files hold ≥99% of the people (the rest is named)."""
    values: dict[str, Any] = {}
    notes: dict[str, str] = {}
    for field in GRID_FIELDS:
        g = grid.get(field) or {}
        share = g["covered"] / g["total"] if g.get("total") else 0.0
        if g.get("sum") is not None and share >= TOTAL_MIN:
            values[field] = _num(g["sum"])
            if share < 0.9999 and g["missing"]:
                notes[field] = f"빠진 블록({_names(g['missing'])}) 인구 약 {_pct(1 - share)} 제외"
        else:
            values[field] = None
            if g.get("missing") and g.get("year"):
                notes[field] = f"{_names(g['missing'])} 블록 {g['year']}년 {g['theme']} 파일 없음 (인구의 약 {_pct(1 - share)})"
    c = grid.get("change") or {}
    share = c["covered"] / c["total"] if c.get("total") else 0.0
    values["pop_change_pct"] = change_pct(c.get("base"), c.get("now")) if share >= CHANGE_MIN else None
    if c.get("missing") and c.get("year"):
        if values["pop_change_pct"] is not None and share < 0.9999:
            notes["pop_change_pct"] = f"빠진 블록({_names(c['missing'])}) 제외, 인구 약 {_pct(share)} 기준"
        elif values["pop_change_pct"] is None:
            notes["pop_change_pct"] = f"{_names(c['missing'])} 블록 인구 파일 없음 (인구의 약 {_pct(1 - share)})"
    return values, notes


def summarize(units: list[dict[str, Any]], complexes: int | None) -> tuple[dict[str, Any], dict[str, str]]:
    """Metrics of a group of SGIS units: 행정 statistics add up (empty if any member is empty), 500m sums by coverage."""
    metrics: dict[str, Any] = {}
    for field in ("population", "households", "area_km2"):
        values = [u.get(field) for u in units]
        metrics[field] = None if not units or any(v is None for v in values) else _num(sum(values))
    grid, notes = grid_values(merge_grid([u["grid"] for u in units if u.get("grid")])) if units else ({}, {})
    metrics.update(grid)
    metrics["complexes"] = complexes
    area, pop = metrics.get("area_km2"), metrics.get("population")
    metrics["density"] = round(pop / area, 1) if pop is not None and area else None
    return {field: metrics.get(field) for field in FIELDS}, notes


def attach_ghg(regions: list[dict[str, Any]], provinces: list[dict[str, Any]], gir: dict[tuple[str, str], dict[tuple[str, int], float | None]],
               year: int | None) -> None:
    """GIR 지역 인벤토리 값을 시·군·구·시·도 지표에 붙인다 (없는 곳은 비우고 까닭을 적음). In place."""
    from collections import Counter
    from .regional_stats import GIR_SIDO, REORGANIZED_NOTE, add_values, ghg_metrics, match_region, region_index
    def empty(row: dict[str, Any], why: str) -> None:
        for f in GHG_FIELDS:
            row["metrics"][f] = None
            row["notes"][f] = why
    if not gir or not year:
        for row in (*regions, *provinces):
            empty(row, "GIR 지역 온실가스 통계를 아직 가져오지 않음")
        return
    index = region_index(gir)
    linked = Counter(r["sido"] for r in regions if r.get("linked"))
    for row in regions:
        hit = match_region(index, row.get("sido"), row.get("short_name") or "", linked[row.get("sido")] == 1)
        if hit is None:
            empty(row, REORGANIZED_NOTE if row.get("sido") == "28" and row.get("linked") else "GIR 지역 인벤토리에 이 시·군·구가 없음")
            continue
        row["metrics"].update(ghg_metrics(gir[hit], year))
        if not row.get("linked") and row.get("sido") == "28":
            row["notes"]["ghg_total"] = "2026년 개편 전 자치구 기준 (GIR)"
        if row["metrics"]["ghg_building_change_pct"] is None and row["metrics"]["ghg_building"] is not None:
            row["notes"]["ghg_building_change_pct"] = "2018년 건물 등 배출이 0이거나 없음"
    for p in provinces:
        names = [s for s, code in GIR_SIDO.items() if code == p["code"] and (s, "광역") in gir]
        if not names:
            empty(p, "GIR 지역 인벤토리에 이 시·도가 없음")
            continue
        p["metrics"].update(ghg_metrics(add_values([gir[(s, "광역")] for s in names]), year))
        if len(names) > 1:
            p["notes"]["ghg_total"] = f"{'·'.join(names)} 합 (GIR은 개편 전 광역 단위)"


def attach_kepco(regions: list[dict[str, Any]], provinces: list[dict[str, Any]], kepco: dict[tuple[str, str], dict[tuple[str, int], float | None]],
                 year: int | None, household_year: int | None) -> None:
    """한전 시군구별 전력판매량을 시·군·구·시·도 지표에 붙인다 (없는 곳은 비우고 까닭을 적음). In place."""
    from collections import Counter
    from .regional_stats import REORGANIZED_NOTE, add_values, kepco_metrics, match_region
    def empty(row: dict[str, Any], why: str) -> None:
        for f in ELEC_FIELDS:
            row["metrics"][f] = None
            row["notes"][f] = why
    if not kepco or not year:
        for row in (*regions, *provinces):
            empty(row, "한전 시군구별 전력판매량을 아직 가져오지 않음")
        return
    current = {k: v for k, v in kepco.items() if ("합계", year) in v}  # places of the latest full year
    index = {k: k for k in current}
    linked = Counter(r["sido"] for r in regions if r.get("linked"))
    def fill(row: dict[str, Any], values: dict[tuple[str, int], float | None]) -> None:
        row["metrics"].update(kepco_metrics(values, year, households=row["metrics"].get("households"), household_year=household_year))
        if row["metrics"]["elec_building_change_pct"] is None and row["metrics"]["elec_building"] is not None:
            row["notes"]["elec_building_change_pct"] = "2018년 값이 없음"
        if row["metrics"]["elec_home_per_household"] is None and row["metrics"]["elec_building"] is not None:
            row["notes"]["elec_home_per_household"] = f"{household_year}년 주택용 전력 또는 가구 수가 없음"
    for row in regions:
        hit = match_region(index, row.get("sido"), row.get("short_name") or "", linked[row.get("sido")] == 1)
        if hit is None:
            empty(row, REORGANIZED_NOTE.replace("GIR 2023", f"한전 {year}") if row.get("sido") == "28" and row.get("linked")
                  else "한전 시군구별 전력판매량에 이 시·군·구가 없음")
            continue
        fill(row, current[hit])
        if not row.get("linked") and row.get("sido") == "28":
            row["notes"]["elec_total"] = f"2026년 개편 전 자치구 기준 (한전 {year})"
    for p in provinces:
        parts = [v for k, v in current.items() if k[0] == p["code"]]
        if not parts:
            empty(p, "한전 시군구별 전력판매량에 이 시·도가 없음")
            continue
        fill(p, add_values(parts))


# --------------------------------------------------------------------------- database (static part, cached)
def _years(db: Any) -> tuple[int | None, int | None]:
    from .sgis_grid500 import coverage
    info = coverage(db)
    return info.get("last_year"), info.get("base_year")


def _cache_key(db: Any) -> str:
    from .national import NationalUnit
    from .sgis_grid500 import coverage
    parts = [str(PAYLOAD_VERSION)]
    try:
        parts.append(str(db.scalar(select(func.max(NationalUnit.year)))))
        parts.append(str(db.scalar(select(func.count()).select_from(NationalUnit))))
        parts.append(str(db.scalar(text("SELECT count(*) FROM national_complexes"))))
        parts.append(str(db.scalar(text("SELECT count(*) FROM admin_units"))))
    except Exception:  # noqa: BLE001
        db.rollback()
        parts.append("-")
    info = coverage(db)
    parts.append(f"{info.get('last_year')}:{info.get('base_year')}:{info.get('rows')}")
    from .province_map import _cell_counts
    parts.append(str(sum(_cell_counts(db).values())))
    from .regional_stats import row_counts
    parts.append(":".join(str(n) for n in row_counts(db)))
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


def _disk(key: str) -> Path:
    root = Path(os.getenv("DATA_DIR", "data")) / "cache" / "national-map"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"static-{key}.json"


def build_static(db: Any) -> dict[str, Any]:
    """Units, 500m totals, complexes and boundaries (heavy; cached by ``static``)."""
    from .national import NationalUnit
    from .province_map import province_list
    from .regions import catalog, short_name
    from .sgis_grid500 import data_root, received_blocks
    unit_year = db.scalar(select(func.max(NationalUnit.year)))
    year, base = _years(db)
    received = received_blocks(data_root())
    units = [dict(r) for r in db.execute(text(UNITS_SQL), {"y": unit_year}).mappings()]
    sums: dict[str, dict[tuple[str, int], dict[str, float]]] = {}
    try:
        for r in db.execute(text(GRID500_SQL), {"years": [y for y in (year, base) if y]}).mappings():
            sums.setdefault(r["sgis"], {})[(r["block"], int(r["year"]))] = {k: (float(r[k]) if r[k] is not None else None) for k in ("pop", "hh", "housing", "workers")}
    except Exception:  # noqa: BLE001 - no 500m statistics yet
        db.rollback()
    weights: dict[str, dict[str, float]] = {}
    try:
        from .sgis_grid import latest_year as latest_1k
        for sgis, block, cells, people in db.execute(text(WEIGHTS_SQL), {"y1k": latest_1k(db) or 0}):
            # people decide the coverage; a tiny share per cell keeps uninhabited blocks from dividing by zero
            weights.setdefault(sgis, {})[block] = float(people or 0) + 0.001 * float(cells)
    except Exception:  # noqa: BLE001
        db.rollback()
    unit_rows: dict[str, dict[str, Any]] = {}
    for u in units:
        unit_rows[u["adm_code"]] = {"population": u["population"], "households": u["households"], "area_km2": (u["area_m2"] / 1e6) if u["area_m2"] else None,
                                    "grid": unit_grid500(sums.get(u["adm_code"], {}), weights.get(u["adm_code"], {}), received, year, base)}
    complexes_region = dict(db.execute(text("SELECT region_code, count(*) FROM national_complexes WHERE region_code IS NOT NULL GROUP BY 1")).all())
    complexes_sido = dict(db.execute(text("SELECT left(coalesce(sigungu_code, bjd_code, region_code), 2), count(*) FROM national_complexes GROUP BY 1")).all())
    snapshot = db.scalar(text("SELECT max(snapshot_month) FROM national_complexes"))

    cat = {r["code"]: r for r in catalog(db)}
    by_region: dict[str, list[str]] = {}
    for u in units:
        if u["region_code"]:
            by_region.setdefault(u["region_code"], []).append(u["adm_code"])
    regions: dict[str, dict[str, Any]] = {}
    for code, entry in cat.items():
        members = by_region.get(code, [])
        metrics, notes = summarize([unit_rows[c] for c in members], int(complexes_region.get(code, 0)))
        regions[code] = {"code": code, "name": entry["name"], "short_name": short_name(entry["name"]), "sido": code[:2],
                         "sgis_codes": members, "linked": True, "metrics": metrics, "notes": notes}
    provinces_meta = province_list(db)
    sgis_to_legal = {s: p["code"] for p in provinces_meta for s in p["sgis_codes"]}
    unlinked = []
    for u in units:
        if u["region_code"]:
            continue
        metrics, notes = summarize([unit_rows[u["adm_code"]]], None)
        unlinked.append({"code": f"sgis:{u['adm_code']}", "name": u["adm_name"], "short_name": short_name(u["adm_name"] or ""), "sido": sgis_to_legal.get(u["adm_code"][:2]),
                         "sgis_codes": [u["adm_code"]], "linked": False, "metrics": metrics, "notes": notes})
    provinces = []
    for p in provinces_meta:
        members = [u["adm_code"] for u in units if u["adm_code"][:2] in p["sgis_codes"]]
        metrics, notes = summarize([unit_rows[c] for c in members], int(complexes_sido.get(p["code"], 0)))
        provinces.append({"code": p["code"], "name": p["name"], "kind": p["kind"], "excluded": p.get("excluded"), "sgis_codes": p["sgis_codes"],
                          "cells": p["cells"], "regions": p["regions"], "metrics": metrics, "notes": notes})
    from .regional_stats import BASE_YEAR, gas_by_province, gir_latest_year, gir_values
    ghg_year = gir_latest_year(db)
    attach_ghg([*regions.values(), *unlinked], provinces, gir_values(db, [y for y in (ghg_year, BASE_YEAR) if y]) if ghg_year else {}, ghg_year)
    from .regional_stats import kepco_values
    kepco, kepco_year = kepco_values(db)
    attach_kepco([*regions.values(), *unlinked], provinces, kepco, kepco_year, unit_year)
    gas = gas_by_province(db)
    for p in provinces:
        p["gas"] = gas.get(p["code"])
    gas_year = next((g["year"] for g in gas.values()), None)
    # 받은 파일이 없는 블록: 그 블록에 사는 사람(1km 격자 기준)과 걸친 시·도
    missing_blocks: dict[str, dict[str, Any]] = {}
    have = received.get(("인구", year), set()) if year else set()
    for sgis, blocks in weights.items():
        for block, weight in blocks.items():
            if block in have:
                continue
            item = missing_blocks.setdefault(block, {"block": block, "people": 0.0, "provinces": set()})
            item["people"] += weight
            if sgis_to_legal.get(sgis[:2]):
                item["provinces"].add(sgis_to_legal[sgis[:2]])
    names = {p["code"]: p["name"] for p in provinces_meta}
    gaps = sorted(({"block": b["block"], "people": int(round(b["people"])), "provinces": sorted(names.get(c, c) for c in b["provinces"])} for b in missing_blocks.values()),
                  key=lambda b: -b["people"])

    geometry: dict[str, Any] = {}
    labels: dict[str, list[float]] = {}
    province_geometry: dict[str, Any] = {}
    try:
        for code, g, lon, lat in db.execute(text(REGION_GEOM_SQL), {"y": unit_year}):
            if g:
                geometry[code] = json.loads(g)
                labels[code] = [round(lon, 4), round(lat, 4)]
        pairs = [(s, p["code"]) for p in provinces_meta for s in p["sgis_codes"]]
        for code, g, lon, lat in db.execute(text(PROVINCE_GEOM_SQL), {"y": unit_year, "sgis": [s for s, _ in pairs], "legal": [l for _, l in pairs]}):
            if g:
                province_geometry[code] = {"geometry": json.loads(g), "label": [round(lon, 4), round(lat, 4)]}
    except Exception:  # noqa: BLE001 - no PostGIS (tests): lists still work
        db.rollback()
    return {
        "unit_year": unit_year, "year": year, "base": base, "complex_month": snapshot, "missing_blocks": gaps, "ghg_year": ghg_year, "gas_year": gas_year, "kepco_year": kepco_year,
        "provinces": provinces, "regions": list(regions.values()) + unlinked,
        "geometry": geometry, "labels": labels, "province_geometry": province_geometry,
    }


def static(db: Any) -> dict[str, Any]:
    key = _cache_key(db)
    if _MEMORY.get("key") == key:
        return _MEMORY["value"]
    path = _disk(key)
    value = None
    if path.exists():
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            value = None
    if value is None:
        value = build_static(db)
        try:
            for old in path.parent.glob("static-*.json"):
                old.unlink(missing_ok=True)
            path.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        except OSError:
            pass
    _MEMORY.update(key=key, value=value)
    return value


# --------------------------------------------------------------------------- dynamic part (every request, cheap)
def dynamic(db: Any) -> dict[str, Any]:
    """Region levels and where energy observations exist (cached one minute)."""
    if _DYNAMIC.get("at", 0) > time.monotonic() - 60:
        return _DYNAMIC["value"]
    from .regions import StudyRegion, catalog, detail_level
    levels: dict[str, dict[str, Any]] = {}
    try:
        for r in db.scalars(select(StudyRegion)):
            levels[r.code] = {"level": detail_level(r), "status": r.status, "grids": r.grid_count or 0}
    except Exception:  # noqa: BLE001
        db.rollback()
    legal_to_region = {legal: r["code"] for r in catalog(db) for legal in r["legal_codes"]}
    kapt: dict[str, int] = {}
    building: dict[str, int] = {}
    try:
        for legal, n in db.execute(text(
                "SELECT left(c.bjd_code, 5), count(DISTINCT e.complex_code) FROM apartment_energy_monthly e "
                "JOIN apartment_complexes c ON c.kapt_code = e.complex_code WHERE e.quality_status = 'SUCCESS' GROUP BY 1")):
            region = legal_to_region.get(legal)
            if region:
                kapt[region] = kapt.get(region, 0) + int(n)
        for legal, n in db.execute(text("SELECT sigungu_code, count(DISTINCT bjdong_code || '-' || coalesce(bun, '') || '-' || coalesce(ji, '')) FROM energy_monthly GROUP BY 1")):
            region = legal_to_region.get(legal)
            if region:
                building[region] = building.get(region, 0) + int(n)
    except Exception:  # noqa: BLE001 - tables missing (tests)
        db.rollback()
    value = {"levels": levels, "kapt": kapt, "building": building}
    _DYNAMIC.update(at=time.monotonic(), value=value)
    return value


def _region_row(region: dict[str, Any], dyn: dict[str, Any]) -> dict[str, Any]:
    state = dyn["levels"].get(region["code"], {})
    return dict({k: v for k, v in region.items() if k != "sgis_codes"}, level=state.get("level", "NONE") if region["linked"] else "UNLINKED",
                status=state.get("status"), energy={"kapt_complexes": dyn["kapt"].get(region["code"], 0), "building_parcels": dyn["building"].get(region["code"], 0)})


def national_payload(db: Any) -> dict[str, Any]:
    st = static(db)
    dyn = dynamic(db)
    rows = [_region_row(r, dyn) for r in st["regions"]]
    features = []
    provinces = []
    for i, base in enumerate(st["provinces"]):
        p = dict(base)
        provinces.append(p)
        g = st["province_geometry"].get(p["code"])
        members = [r for r in rows if r["sido"] == p["code"]]
        p.update(detailed=sum(1 for r in members if r["level"] == "DETAILED"), basic=sum(1 for r in members if r["level"] == "BASIC"),
                 energy_regions=sum(1 for r in members if r["energy"]["kapt_complexes"] or r["energy"]["building_parcels"]),
                 label=g["label"] if g else None)
        if g:
            features.append({"type": "Feature", "id": i, "geometry": g["geometry"], "properties": {"i": i, "code": p["code"], "name": p["name"]}})
    from .sgis_grid500 import SOURCE_TEXT, data_root, missing_files, missing_text
    from .regional_stats import BASE_YEAR, GAS_SOURCE_TEXT, GIR_SOURCE_TEXT, KEPCO_SOURCE_TEXT
    gaps = missing_files(data_root())
    return {
        "provinces": provinces, "boundaries": {"type": "FeatureCollection", "features": features}, "regions": rows, "fields": FIELDS,
        "meta": {
            "sgis_year": st["unit_year"], "grid500_year": st["year"], "grid500_base_year": st["base"], "complex_month": st["complex_month"],
            "ghg_year": st.get("ghg_year"), "ghg_base_year": BASE_YEAR, "gas_year": st.get("gas_year"), "kepco_year": st.get("kepco_year"),
            "gaps": missing_text(gaps) if gaps else None,
            "missing_blocks": st.get("missing_blocks", []),
            "sources": {
                "admin": f"SGIS {st['unit_year'] or ''} 행정구역 통계 (시군구 합, 비공개 값은 합에서 빠짐)",
                "grid500": f"{SOURCE_TEXT} {st['year'] or ''}년 (공식 500m 격자의 시군구로 모음)",
                "complexes": f"K-apt 공동주택 단지 목록 {st['complex_month'] or ''}",
                "boundaries": "SGIS 시군구 경계 (표시용 단순화)",
                "ghg": f"{GIR_SOURCE_TEXT} {st.get('ghg_year') or ''}년, 총배출량은 수송 VKT 기준 (단위 천 tCO₂eq = Gg)",
                "gas": GAS_SOURCE_TEXT,
                "kepco": f"{KEPCO_SOURCE_TEXT} {st.get('kepco_year') or ''}년, 건물 전력 = 주택용+일반용+교육용 (가구당은 {st['unit_year'] or ''}년 주택용 ÷ SGIS 가구)",
            },
            "energy_note": "전력은 한전 시군구별 판매량, 온실가스는 온실가스종합정보센터 지역 인벤토리로 시·군·구까지 칠합니다. 건물·격자 단위 에너지(건축HUB·K-apt)는 지역마다 수집합니다.",
        },
    }


def province_regions(db: Any, code: str) -> dict[str, Any]:
    """시·군·구 of one 시·도 with boundaries (for the drill-down)."""
    st = static(db)
    dyn = dynamic(db)
    if not any(p["code"] == code for p in st["provinces"]):
        raise HTTPException(404, "시·도 코드가 없습니다")
    features = []
    for r in st["regions"]:
        if r["sido"] != code:
            continue
        row = _region_row(r, dyn)
        g = st["geometry"].get(r["code"])
        if g is None:
            continue
        features.append({"type": "Feature", "id": len(features), "geometry": g,
                         "properties": {"i": len(features), "code": r["code"], "name": r["short_name"], "linked": r["linked"], "level": row["level"],
                                        "label": st["labels"].get(r["code"]), **{f: r["metrics"].get(f) for f in FIELDS}}})
    return {"code": code, "boundaries": {"type": "FeatureCollection", "features": features}}


@router.get("/national")
def national() -> Response:
    """전국 시·도와 시·군·구의 전국 공통 지표, 시·도 경계 (지도 첫 단계)."""
    with Session() as db:
        body = json.dumps(national_payload(db), ensure_ascii=False, separators=(",", ":")).encode()
        return Response(body, media_type="application/json")


@router.get("/national/{code}")
def national_province(code: str) -> Response:
    """한 시·도의 시·군·구 경계와 지표 (전국 지도에서 시·도를 골랐을 때)."""
    if not code.isdigit() or len(code) != 2:
        raise HTTPException(422, "시·도 코드는 두 자리 숫자입니다")
    with Session() as db:
        body = json.dumps(province_regions(db, code), ensure_ascii=False, separators=(",", ":")).encode()
        return Response(body, media_type="application/json")
