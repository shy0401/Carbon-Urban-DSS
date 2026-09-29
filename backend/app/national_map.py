"""전국 지도: 시·도와 시·군·구를 전국 공통 자료로 비교하고, 지도나 메뉴에서 골라 들어가는 첫 단계.

지도 분석의 순서는 전국(시·도 → 그 시·도의 시·군·구) → 시·도 500m 격자 → 시·군·구 · 읍면동이다.
이 모듈은 앞 단계(전국)를 맡는다.

* 단위
  - 시·도 17곳(법정 2자리 코드). 전남광주통합특별시처럼 SGIS 시도 코드가 둘인 곳은 합친다.
  - 시·군·구: 법정 분석 단위(수원시처럼 일반구를 묶은 시) + SGIS에만 있고 법정 단위에 연결하지 못한 곳(연결 안 됨).
* 지표 (모두 전국에 있는 자료만, 없으면 0이 아니라 비움)
  - 인구·가구·면적·인구밀도: SGIS 행정구역 통계(시군구 합, 최근 연도).
  - 500m 인구와 2015년 대비 증감률, 500m 주택·종사자: SGIS 500m 격자 통계(자료제공 신청분)를 공식 500m 격자의
    시군구 코드로 모은 값. 그 지역 격자가 걸친 100km 블록 중 하나라도 그해·그 주제 파일이 없으면 합을 비운다
    (일부 블록만 더한 값은 실제보다 작으므로 보여 주지 않는다).
  - K-apt 공동주택 단지 수: 전국 단지 목록.
  - 에너지·탄소: 전국 자료가 없다(지역마다 수집). 칠하지 않고, 어느 시·군·구에 K-apt 월별 에너지·건축HUB 건물 에너지가
    있는지만 적는다.
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

PAYLOAD_VERSION = 1
MIN_BASE = 20  # 증감률: 두 해 모두 이만큼은 있어야 한다
FIELDS = ["population", "households", "area_km2", "density", "pop500", "pop500_base", "pop_change_pct", "housing500", "workers500", "complexes"]
SUM_FIELDS = ("population", "households", "area_km2", "pop500", "pop500_base", "housing500", "workers500", "complexes")
THEME_OF = {"pop500": "인구", "pop500_base": "인구", "housing500": "주택", "workers500": "종사자"}
_MEMORY: dict[str, Any] = {}
_DYNAMIC: dict[str, Any] = {}

UNITS_SQL = """
SELECT adm_code, adm_name, region_code, population, households, area_m2
FROM national_units WHERE year = :y AND level = 'SIGUNGU' ORDER BY adm_code
"""
GRID500_SQL = """
SELECT split_part(c.adm_cd, ',', 1) AS sgis, left(v.grid_cd, 2) AS block, v.year, count(*) AS cells,
       sum(v.population) AS pop, sum(v.households) AS hh, sum(v.housing) AS housing, sum(v.workers) AS workers
FROM sgis_grid500_values v JOIN sgis_official_grid_cells c ON c.grid_cd = v.grid_cd
WHERE v.year = ANY(:years) AND c.size_m = 500
GROUP BY 1, 2, 3
"""
BLOCKS_SQL = """
SELECT split_part(adm_cd, ',', 1) AS sgis, left(grid_cd, 2) AS block, count(*) AS cells
FROM sgis_official_grid_cells WHERE size_m = 500 GROUP BY 1, 2
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
def _num(value: Any) -> float | int | None:
    if value is None:
        return None
    value = float(value)
    return int(value) if value.is_integer() else round(value, 1)


def change_pct(before: float | None, after: float | None) -> float | None:
    if before is None or after is None or before < MIN_BASE or after < MIN_BASE:
        return None
    return round((after - before) / before * 100, 1)


def unit_grid500(sums: dict[tuple[str, int], dict[str, float]], blocks: Iterable[str], received: dict[tuple[str, int], set[str]],
                 year: int | None, base: int | None) -> dict[str, float | None]:
    """500m totals of one SGIS 시군구 from its per-(block, year) sums.

    A total is left empty when any block the unit's cells touch has no file for that theme and year (partial sums
    would look like real, smaller totals)."""
    blocks = set(blocks)
    out: dict[str, float | None] = {}

    def total(column: str, theme: str, y: int | None) -> float | None:
        if not y or not blocks:
            return None
        if not blocks <= received.get((theme, y), set()):
            return None
        values = [sums.get((block, y), {}).get(column) for block in blocks]
        present = [v for v in values if v is not None]
        return float(sum(present)) if present else None

    out["pop500"] = total("pop", "인구", year)
    out["pop500_base"] = total("pop", "인구", base) if base and base != year else None
    out["housing500"] = total("housing", "주택", year)
    out["workers500"] = total("workers", "종사자", year)
    return out


def combine(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Metrics of a group of units: sums stay empty when any member is empty for that field (never a partial sum)."""
    out: dict[str, Any] = {}
    for field in SUM_FIELDS:
        values = [item.get(field) for item in items]
        out[field] = None if not items or any(v is None for v in values) else _num(sum(values))
    return finish(out)


def finish(metrics: dict[str, Any]) -> dict[str, Any]:
    area = metrics.get("area_km2")
    pop = metrics.get("population")
    metrics["density"] = round(pop / area, 1) if pop is not None and area else None
    metrics["pop_change_pct"] = change_pct(metrics.get("pop500_base"), metrics.get("pop500"))
    return {field: metrics.get(field) for field in FIELDS}


def gap_notes(blocks_by_unit: dict[str, set[str]], units: Iterable[str], received: dict[tuple[str, int], set[str]], year: int | None) -> dict[str, str]:
    """Why a 500m total is empty: {'housing500': '다마 블록 2024년 주택 파일 없음', ...}."""
    touched = set().union(*(blocks_by_unit.get(u, set()) for u in units)) if units else set()
    notes = {}
    for field, theme in (("pop500", "인구"), ("housing500", "주택"), ("workers500", "종사자")):
        missing = sorted(touched - received.get((theme, year), set())) if year else []
        if missing:
            notes[field] = f"{'·'.join(missing[:4])}{' 등' if len(missing) > 4 else ''} 블록 {year}년 {theme} 파일 없음"
    return notes


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
    blocks: dict[str, set[str]] = {}
    try:
        for sgis, block, _n in db.execute(text(BLOCKS_SQL)):
            blocks.setdefault(sgis, set()).add(block)
    except Exception:  # noqa: BLE001
        db.rollback()
    unit_metrics: dict[str, dict[str, Any]] = {}
    for u in units:
        m = {"population": u["population"], "households": u["households"], "area_km2": (u["area_m2"] / 1e6) if u["area_m2"] else None}
        m.update(unit_grid500(sums.get(u["adm_code"], {}), blocks.get(u["adm_code"], set()), received, year, base))
        unit_metrics[u["adm_code"]] = m
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
        metrics = combine([unit_metrics[c] for c in members]) if members else finish({})
        metrics["complexes"] = int(complexes_region.get(code, 0))
        regions[code] = {"code": code, "name": entry["name"], "short_name": short_name(entry["name"]), "sido": code[:2],
                         "sgis_codes": members, "linked": True, "metrics": metrics,
                         "notes": gap_notes(blocks, members, received, year)}
    provinces_meta = province_list(db)
    sgis_to_legal = {s: p["code"] for p in provinces_meta for s in p["sgis_codes"]}
    unlinked = []
    for u in units:
        if u["region_code"]:
            continue
        legal = sgis_to_legal.get(u["adm_code"][:2])
        metrics = combine([unit_metrics[u["adm_code"]]])
        metrics["complexes"] = None
        unlinked.append({"code": f"sgis:{u['adm_code']}", "name": u["adm_name"], "short_name": short_name(u["adm_name"] or ""), "sido": legal,
                         "sgis_codes": [u["adm_code"]], "linked": False, "metrics": metrics, "notes": gap_notes(blocks, [u["adm_code"]], received, year)})
    provinces = []
    for p in provinces_meta:
        members = [u["adm_code"] for u in units if u["adm_code"][:2] in p["sgis_codes"]]
        metrics = combine([unit_metrics[c] for c in members]) if members else finish({})
        metrics["complexes"] = int(complexes_sido.get(p["code"], 0))
        provinces.append({"code": p["code"], "name": p["name"], "kind": p["kind"], "excluded": p.get("excluded"), "sgis_codes": p["sgis_codes"],
                          "cells": p["cells"], "regions": p["regions"], "metrics": metrics, "notes": gap_notes(blocks, members, received, year)})

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
        "unit_year": unit_year, "year": year, "base": base, "complex_month": snapshot,
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
    gaps = missing_files(data_root())
    return {
        "provinces": provinces, "boundaries": {"type": "FeatureCollection", "features": features}, "regions": rows, "fields": FIELDS,
        "meta": {
            "sgis_year": st["unit_year"], "grid500_year": st["year"], "grid500_base_year": st["base"], "complex_month": st["complex_month"],
            "gaps": missing_text(gaps) if gaps else None,
            "sources": {
                "admin": f"SGIS {st['unit_year'] or ''} 행정구역 통계 (시군구 합, 비공개 값은 합에서 빠짐)",
                "grid500": f"{SOURCE_TEXT} {st['year'] or ''}년 (공식 500m 격자의 시군구로 모음)",
                "complexes": f"K-apt 공동주택 단지 목록 {st['complex_month'] or ''}",
                "boundaries": "SGIS 시군구 경계 (표시용 단순화)",
            },
            "energy_note": "에너지·탄소는 전국 자료가 없어 지역마다 수집합니다. 칠하지 않고 수집된 시·군·구만 표시합니다.",
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
