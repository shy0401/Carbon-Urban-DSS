"""시·도 단위 500m 격자 지도: 전국 어디서나 같은 지표로 보는 첫 화면.

지역 준비(``region_prepare``)를 한 시·군·구만 에너지·건물·용도지역까지 갖추고 있으므로, 지도 첫 화면은
전국에 이미 있는 자료만으로 시·도 전체를 SGIS 공식 500m 격자로 보여 준다.

* 격자: SGIS 공식 500m 격자 경계·코드 (``sgis_official_grid_cells``, 전국 수집).
* 인구·가구·주택·종사자·65세 이상·노후주택·아파트 비율: 그 500m 격자를 품은 SGIS 1km 격자의 값
  (500m 통계는 자료신청 대상이라 1km 값을 그대로 보여 주고, 그렇다고 표시한다).
* 공동주택 단지 수·평균 사용승인연도: K-apt 전국 단지 목록의 좌표를 500m 격자에 넣은 값.
* 분석 준비 지역: 준비된 시·군·구의 격자는 에너지·탄소 등 상세 지표를 '시·군·구 상세'에서 본다.

응답은 격자마다 숫자 배열(좌하단 좌표 ÷ 500, EPSG:5179)이며, 화면이 격자 네 모서리를 경위도로 바꿔 그린다.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from sqlalchemy import func, select, text

from .db import Session

router = APIRouter(prefix="/api/map", tags=["map"])

EXCLUDED = {"50": "제주특별자치도는 이 화면에서 제외합니다"}
FIELDS = ["x", "y", "sgg", "pop", "hh", "housing", "workers", "elderly_pct", "old_housing_pct", "apartment_pct",
          "complexes", "complex_year", "region"]
MIN_BASE = 20  # 비율의 분모가 이보다 작으면 비움 (sgis_grid와 같은 규칙)
_MEMORY: dict[str, bytes] = {}


def _kind(name: str) -> str:
    return "PROVINCE" if name.endswith("도") or "통합특별시" in name else "METRO"


def province_list(db: Any) -> list[dict[str, Any]]:
    """시·도 (제주 제외) with their SGIS 시도 codes, prepared study regions and 500m cell counts."""
    from .national import NationalUnit
    from .regions import StudyRegion, catalog, short_name, sido_keys
    groups: dict[str, dict[str, Any]] = {}
    for region in catalog(db):
        code = region["code"][:2]
        item = groups.setdefault(code, {"code": code, "name": region["sido_name"], "regions": 0})
        item["regions"] += 1
    try:
        year = db.scalar(select(func.max(NationalUnit.year)))
        sgis = [(u.adm_code, u.adm_name or "") for u in db.scalars(select(NationalUnit).where(NationalUnit.year == year, NationalUnit.level == "SIDO"))]
    except Exception:  # noqa: BLE001 - national layer not collected
        db.rollback()
        sgis = []
    counts = _cell_counts(db)
    prepared: dict[str, list[dict[str, Any]]] = {}
    try:
        for region in db.scalars(select(StudyRegion).where(StudyRegion.grid_count > 0).order_by(StudyRegion.code)):
            prepared.setdefault(region.code[:2], []).append({"code": region.code, "name": region.name, "short_name": short_name(region.name),
                                                             "status": region.status, "grid_count": region.grid_count})
    except Exception:  # noqa: BLE001
        db.rollback()
    out = []
    for code, item in sorted(groups.items()):
        keys = set(sido_keys(item["name"]))
        codes = sorted(c for c, n in sgis if keys & set(sido_keys(n)))
        out.append(dict(item, kind=_kind(item["name"]), sgis_codes=codes, cells=sum(counts.get(c, 0) for c in codes),
                        prepared=prepared.get(code, []), excluded=EXCLUDED.get(code)))
    out.sort(key=lambda p: (p["kind"] != "PROVINCE", p["code"]))
    return out


_COUNTS: dict[str, Any] = {}


def _cell_counts(db: Any) -> dict[str, int]:
    """500m cells per SGIS 시도 code (re-read every 10 minutes; the grid is collected once)."""
    import time
    if _COUNTS.get("at", 0) > time.monotonic() - 600 and _COUNTS.get("value"):
        return _COUNTS["value"]
    try:
        rows = db.execute(text("SELECT left(split_part(adm_cd, ',', 1), 2) AS s, count(*) FROM sgis_official_grid_cells WHERE size_m = 500 GROUP BY 1"))
        value = {code: int(n) for code, n in rows}
    except Exception:  # noqa: BLE001 - table not created (tests)
        db.rollback()
        return {}
    _COUNTS.update(at=time.monotonic(), value=value)
    return value


AGE_65 = [f"in_age_{i:03d}" for i in range(14, 22)]
AGE_ALL = [f"in_age_{i:03d}" for i in range(1, 22)]
OLD_HOUSING = ["ho_yr_001", "ho_yr_002", "ho_yr_003"]
ALL_HOUSING_YEARS = [f"ho_yr_{i:03d}" for i in range(1, 21)]
HOUSING_TYPES = ["ho_gb_001", "ho_gb_002", "ho_gb_003", "ho_gb_004", "ho_gb_005", "ho_gb_006"]
ITEMS = sorted({"to_in_001", "to_ga_001", "to_ho_001", "to_em_020", *AGE_65, *AGE_ALL, *OLD_HOUSING, *ALL_HOUSING_YEARS, *HOUSING_TYPES})

CELLS_SQL = """
WITH cells AS (
  SELECT x_min::bigint AS x, y_min::bigint AS y, split_part(adm_cd, ',', 1) AS sgg, grid_cd
  FROM sgis_official_grid_cells WHERE size_m = 500 AND left(split_part(adm_cd, ',', 1), 2) = ANY(:sidos)
), parents AS (
  SELECT DISTINCT (floor(x / 1000.0) * 1000)::bigint AS px, (floor(y / 1000.0) * 1000)::bigint AS py FROM cells
), k AS (
  SELECT g.grid_cd, p.px, p.py FROM sgis_grid_cells g JOIN parents p ON g.x_min = p.px AND g.y_min = p.py
  WHERE g.year = :year AND g.size_m = 1000
), s AS (
  SELECT st.grid_cd,
    max(st.value) FILTER (WHERE st.item = 'to_in_001') AS pop,
    max(st.value) FILTER (WHERE st.item = 'to_ga_001') AS hh,
    max(st.value) FILTER (WHERE st.item = 'to_ho_001') AS housing,
    max(st.value) FILTER (WHERE st.item = 'to_em_020') AS workers,
    sum(st.value) FILTER (WHERE st.item = ANY(:age65)) AS age65,
    sum(st.value) FILTER (WHERE st.item = ANY(:ageall)) AS ageall,
    sum(st.value) FILTER (WHERE st.item = ANY(:old)) AS old,
    sum(st.value) FILTER (WHERE st.item = ANY(:years)) AS years,
    max(st.value) FILTER (WHERE st.item = 'ho_gb_003') AS apt,
    sum(st.value) FILTER (WHERE st.item = ANY(:types)) AS types
  FROM sgis_grid_stats st JOIN k ON k.grid_cd = st.grid_cd
  WHERE st.year = :year AND st.item = ANY(:items)
  GROUP BY st.grid_cd
)
SELECT c.x, c.y, c.sgg, (k.grid_cd IS NOT NULL) AS has_parent, s.pop, s.hh, s.housing, s.workers, s.age65, s.ageall, s.old, s.years, s.apt, s.types
FROM cells c
LEFT JOIN k ON k.px = (floor(c.x / 1000.0) * 1000)::bigint AND k.py = (floor(c.y / 1000.0) * 1000)::bigint
LEFT JOIN s ON s.grid_cd = k.grid_cd
ORDER BY c.y, c.x
"""

COMPLEX_SQL = """
SELECT (floor(ST_X(p) / 500) * 500)::bigint AS x, (floor(ST_Y(p) / 500) * 500)::bigint AS y, count(*) AS n,
       round(avg(CASE WHEN approval_month ~ '^[0-9]{4}' THEN left(approval_month, 4)::int END)) AS yr
FROM (SELECT ST_Transform(ST_SetSRID(ST_MakePoint(longitude, latitude), 4326), 5179) AS p, approval_month
      FROM national_complexes WHERE longitude IS NOT NULL AND latitude IS NOT NULL AND left(coalesce(sigungu_code, bjd_code, ''), 2) = :code) q
GROUP BY 1, 2
"""

BOUNDARY_SQL = """
SELECT adm_code, adm_name, region_code, ST_AsGeoJSON(ST_Transform(ST_SimplifyPreserveTopology(geom, 80), 4326), 5) AS g
FROM national_units WHERE year = :year AND level = 'SIGUNGU' AND left(adm_code, 2) = ANY(:sidos) AND geom IS NOT NULL
ORDER BY adm_code
"""


def _share(part: float | None, whole: float | None) -> float | None:
    if part is None or whole is None or whole < MIN_BASE:
        return None
    return round(part / whole * 100, 1)


def _num(value: Any) -> float | int | None:
    if value is None:
        return None
    value = float(value)
    return int(value) if value.is_integer() else round(value, 1)


def build_province(db: Any, province: dict[str, Any]) -> dict[str, Any]:
    """The 500m cells of one 시·도 with the national indicators (see module doc)."""
    from .national import NationalUnit
    from .regions import GridRegion, StudyRegion
    from .sgis_grid import latest_year
    sidos = province["sgis_codes"]
    year = latest_year(db)
    params = {"sidos": sidos, "year": year or 0, "age65": AGE_65, "ageall": AGE_ALL, "old": OLD_HOUSING, "years": ALL_HOUSING_YEARS,
              "types": HOUSING_TYPES, "items": ITEMS}
    rows = db.execute(text(CELLS_SQL), params).all()
    complexes = {(int(r.x), int(r.y)): (int(r.n), int(r.yr) if r.yr is not None else None)
                 for r in db.execute(text(COMPLEX_SQL), {"code": province["code"]})}
    # 준비 상태(READY·PREPARING)는 목록 API에서 본다: 캐시한 격자 응답에는 넣지 않는다.
    regions = [{k: v for k, v in r.items() if k != "status"} for r in province.get("prepared", [])]
    index = {r["code"]: i for i, r in enumerate(regions)}
    prepared: dict[tuple[int, int], int] = {}
    if regions:
        for grid_id, region_code in db.execute(select(GridRegion.grid_id, GridRegion.region_code).where(GridRegion.region_code.in_(list(index)))):
            try:
                _, x, y = grid_id.split("_")
                prepared.setdefault((int(float(x)), int(float(y))), index[region_code])
            except (ValueError, KeyError):
                continue
    unit_year = db.scalar(select(func.max(NationalUnit.year)))
    names = {u.adm_code: (u.adm_name, u.region_code) for u in db.scalars(select(NationalUnit).where(NationalUnit.year == unit_year, NationalUnit.level == "SIGUNGU"))}
    sigungu: list[dict[str, Any]] = []
    sgg_index: dict[str, int] = {}
    cells = []
    counts = {"with_stats": 0, "no_stat": 0, "with_complexes": 0, "prepared": 0}
    for r in rows:
        x, y = int(r.x), int(r.y)
        if r.sgg not in sgg_index:
            name, region = names.get(r.sgg, (None, None))
            sgg_index[r.sgg] = len(sigungu)
            sigungu.append({"code": r.sgg, "name": name, "region": region})
        n, yr = complexes.get((x, y), (0, None))
        region_i = prepared.get((x, y), -1)
        if r.pop is not None or r.hh is not None:
            counts["with_stats"] += 1
        elif r.has_parent:
            counts["no_stat"] += 1
        counts["with_complexes"] += n > 0
        counts["prepared"] += region_i >= 0
        cells.append([x // 500, y // 500, sgg_index[r.sgg], _num(r.pop), _num(r.hh), _num(r.housing), _num(r.workers),
                      _share(r.age65, r.ageall), _share(r.old, r.years), _share(r.apt, r.types), n, yr, region_i])
    boundaries = {"type": "FeatureCollection", "features": []}
    try:
        for b in db.execute(text(BOUNDARY_SQL), {"year": unit_year, "sidos": sidos}):
            boundaries["features"].append({"type": "Feature", "geometry": json.loads(b.g),
                                           "properties": {"code": b.adm_code, "name": b.adm_name, "region": b.region_code}})
    except Exception:  # noqa: BLE001 - no PostGIS geometry: the grid alone still draws
        db.rollback()
    snapshot = db.scalar(text("SELECT max(snapshot_month) FROM national_complexes"))
    return {
        "code": province["code"], "name": province["name"], "kind": province["kind"], "sgis_codes": sidos,
        "fields": FIELDS, "cells": cells, "sigungu": sigungu, "regions": regions, "boundaries": boundaries,
        "bbox": _bbox(cells),
        "meta": {"cells": len(cells), "sgis_year": year, "complex_month": snapshot, **counts,
                 "grid_source": "SGIS 공식 500m 격자 (경계·코드)", "stats_source": f"SGIS {year or ''} 1km 격자 통계 (소속 1km 격자 값)",
                 "complex_source": f"K-apt 공동주택 단지 목록 {snapshot or ''} (좌표)"},
    }


def _bbox(cells: list[list[Any]]) -> list[float] | None:
    if not cells:
        return None
    xs = [c[0] * 500 for c in cells]
    ys = [c[1] * 500 for c in cells]
    try:
        from pyproj import Transformer
        to = Transformer.from_crs(5179, 4326, always_xy=True).transform
        corners = [to(x, y) for x in (min(xs), max(xs) + 500) for y in (min(ys), max(ys) + 500)]
    except Exception:  # noqa: BLE001 - no projection library (tests)
        return None
    return [round(min(c[0] for c in corners), 5), round(min(c[1] for c in corners), 5), round(max(c[0] for c in corners), 5), round(max(c[1] for c in corners), 5)]


def _cache_key(db: Any, province: dict[str, Any]) -> str:
    """Changes when the grid, the statistics, the complexes or the prepared regions change (not their status)."""
    prepared = sorted((r["code"], int(r.get("grid_count") or 0)) for r in province.get("prepared", []))
    parts = [province["code"], ",".join(province["sgis_codes"]), str(province["cells"]), json.dumps(prepared)]
    for sql in ("SELECT count(*) FROM national_complexes", "SELECT max(year) FROM sgis_grid_cells",
                "SELECT count(*) FROM grid_regions"):
        try:
            parts.append(str(db.scalar(text(sql))))
        except Exception:  # noqa: BLE001
            db.rollback()
            parts.append("-")
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


def _disk(key: str, code: str) -> Path:
    root = Path(os.getenv("DATA_DIR", "data")) / "cache" / "province-map"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{code}-{key}.json"


def province_payload(db: Any, code: str) -> bytes:
    province = next((p for p in province_list(db) if p["code"] == code), None)
    if province is None:
        raise HTTPException(404, "시·도 코드가 없습니다")
    if province.get("excluded"):
        raise HTTPException(404, province["excluded"])
    if not province["cells"]:
        raise HTTPException(404, "이 시·도의 SGIS 500m 격자를 아직 받지 않았습니다 (전국 기초 자료 수집 필요)")
    key = _cache_key(db, province)
    if key in _MEMORY:
        return _MEMORY[key]
    path = _disk(key, code)
    if path.exists():
        body = path.read_bytes()
    else:
        body = json.dumps(build_province(db, province), ensure_ascii=False, separators=(",", ":")).encode()
        for old in path.parent.glob(f"{code}-*.json"):
            old.unlink(missing_ok=True)
        path.write_bytes(body)
    if len(_MEMORY) >= 4:
        _MEMORY.pop(next(iter(_MEMORY)))
    _MEMORY[key] = body
    return body


@router.get("/provinces")
def provinces() -> dict[str, Any]:
    """시·도 목록 (제주 제외): 500m 격자 수, 준비된 분석 지역."""
    with Session() as db:
        items = [p for p in province_list(db) if not p.get("excluded")]
        return {"provinces": items, "excluded": [{"code": c, "reason": r} for c, r in EXCLUDED.items()]}


@router.get("/province/{code}")
def province(code: str) -> Response:
    """한 시·도의 SGIS 500m 격자 전체와 전국 공통 지표 (격자마다 숫자 배열)."""
    if not code.isdigit() or len(code) != 2:
        raise HTTPException(422, "시·도 코드는 두 자리 숫자입니다")
    with Session() as db:
        return Response(province_payload(db, code), media_type="application/json")
