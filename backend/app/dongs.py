"""읍면동(행정동) 단위 분석: 시·군·구 분석 격자가 행정동 경계와 얼마나 겹치는지.

* 행정동: SGIS 전국 행정동 경계·인구·가구 (``national_units``, level EMD, 경계는 10m 단순화). 전국 어디나 있다.
* 겹침 비율: 500m 격자(250,000㎡) 중 그 행정동 안에 드는 면적의 비율. PostGIS가 계산하고, 없으면(테스트) 같은 값을
  순수 파이썬(직사각형 자르기)으로 낸다.
* 화면은 이 비율로 격자 지표를 행정동에 모은다: 합계 지표(연간 전력 등)는 값 × 비율의 합, 비율·원단위 지표는 가중 평균.
  값이 없는 격자는 0으로 치지 않고 "값 있는 면적 비율"을 함께 보여 준다. 인구·가구는 격자에서 모으지 않고 SGIS 행정동
  공식 값을 그대로 쓴다.
"""
from __future__ import annotations

import json
from typing import Any, Iterable

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import func, select, text

from .db import Session

router = APIRouter(prefix="/api/map", tags=["map"])

CELL_AREA = 250_000.0
MIN_SHARE = 0.001  # 250㎡ 미만 겹침은 경계 단순화 오차로 보고 버림
_CACHE: dict[tuple[Any, ...], bytes] = {}

Ring = list[tuple[float, float]]


# --------------------------------------------------------------------------- pure geometry (fallback and tests)
def _clip_ring(ring: Ring, box: tuple[float, float, float, float]) -> Ring:
    """Sutherland–Hodgman: the part of a ring inside an axis-aligned box (the box is convex, the ring may not be)."""
    x0, y0, x1, y1 = box
    edges = ((lambda p: p[0] >= x0, lambda a, b: _at_x(a, b, x0)), (lambda p: p[0] <= x1, lambda a, b: _at_x(a, b, x1)),
             (lambda p: p[1] >= y0, lambda a, b: _at_y(a, b, y0)), (lambda p: p[1] <= y1, lambda a, b: _at_y(a, b, y1)))
    points = list(ring[:-1] if len(ring) > 1 and ring[0] == ring[-1] else ring)
    for inside, cross in edges:
        if not points:
            break
        out: Ring = []
        previous = points[-1]
        for point in points:
            if inside(point):
                if not inside(previous):
                    out.append(cross(previous, point))
                out.append(point)
            elif inside(previous):
                out.append(cross(previous, point))
            previous = point
        points = out
    return points


def _at_x(a: tuple[float, float], b: tuple[float, float], x: float) -> tuple[float, float]:
    t = (x - a[0]) / (b[0] - a[0])
    return x, a[1] + t * (b[1] - a[1])


def _at_y(a: tuple[float, float], b: tuple[float, float], y: float) -> tuple[float, float]:
    t = (y - a[1]) / (b[1] - a[1])
    return a[0] + t * (b[0] - a[0]), y


def _area(points: Ring) -> float:
    return abs(sum(points[i][0] * points[i - 1][1] - points[i - 1][0] * points[i][1] for i in range(len(points)))) / 2 if len(points) > 2 else 0.0


def polygon_box_area(polygons: Iterable[list[Ring]], box: tuple[float, float, float, float]) -> float:
    """Area of (multi)polygon ∩ box. ``polygons``: [[exterior, hole, …], …] in metres (EPSG:5179)."""
    total = 0.0
    for rings in polygons:
        if not rings:
            continue
        total += _area(_clip_ring(rings[0], box)) - sum(_area(_clip_ring(hole, box)) for hole in rings[1:])
    return max(total, 0.0)


def _bounds(polygons: list[list[Ring]]) -> tuple[float, float, float, float]:
    xs = [x for rings in polygons for x, _ in rings[0]]
    ys = [y for rings in polygons for _, y in rings[0]]
    return min(xs), min(ys), max(xs), max(ys)


def cell_shares_py(cells: dict[str, tuple[float, float]], dongs: list[list[list[Ring]]]) -> dict[str, list[list[float]]]:
    """{cell id: [[dong index, share], …]} for 500m cells given by their lower-left corners."""
    boxes = [_bounds(polygons) if polygons else None for polygons in dongs]
    out: dict[str, list[list[float]]] = {}
    for cell_id, (x, y) in cells.items():
        box = (x, y, x + 500.0, y + 500.0)
        found = []
        for index, polygons in enumerate(dongs):
            b = boxes[index]
            if b is None or b[2] <= box[0] or b[0] >= box[2] or b[3] <= box[1] or b[1] >= box[3]:
                continue
            share = polygon_box_area(polygons, box) / CELL_AREA
            if share >= MIN_SHARE:
                found.append([index, round(min(share, 1.0), 3)])
        if found:
            out[cell_id] = found
    return out


def _rings(geometry: dict[str, Any]) -> list[list[Ring]]:
    if geometry.get("type") == "Polygon":
        return [[[tuple(p) for p in ring] for ring in geometry["coordinates"]]]
    if geometry.get("type") == "MultiPolygon":
        return [[[tuple(p) for p in ring] for ring in polygon] for polygon in geometry["coordinates"]]
    return []


# --------------------------------------------------------------------------- database
def region_sgis_codes(db: Any, sc: Any) -> list[str]:
    codes = list(getattr(sc, "sgis_codes", ()) or ())
    if not codes:
        try:
            from .national import sgis_codes_for
            codes = sgis_codes_for(db, sc.code)
        except Exception:  # noqa: BLE001
            db.rollback()
    return codes


def load_dongs(db: Any, codes: list[str]) -> tuple[int | None, list[dict[str, Any]]]:
    """행정동 of the given SGIS 시군구 codes (latest SGIS year): statistics, 4326 outline and 5179 geometry."""
    from .national import NationalUnit
    year = db.scalar(select(func.max(NationalUnit.year)))
    if not year or not codes:
        return year, []
    rows = db.execute(text(
        "SELECT adm_code, adm_name, parent_code, population, population_status, households, household_status, area_m2, "
        "ST_AsGeoJSON(ST_Transform(geom, 4326), 5) AS outline, ST_AsGeoJSON(geom, 1) AS metric "
        "FROM national_units WHERE year = :year AND level = 'EMD' AND parent_code = ANY(:codes) AND geom IS NOT NULL ORDER BY adm_code"
    ), {"year": year, "codes": codes}).mappings().all()
    return year, [dict(row) for row in rows]


def cell_shares_sql(db: Any, cells: dict[str, tuple[float, float]], codes: list[str], year: int, order: list[str]) -> dict[str, list[list[float]]]:
    """Same result as ``cell_shares_py``, computed by PostGIS."""
    ids = list(cells)
    index = {code: i for i, code in enumerate(order)}
    out: dict[str, list[list[float]]] = {}
    for start in range(0, len(ids), 4000):
        part = ids[start:start + 4000]
        rows = db.execute(text(
            "WITH c AS (SELECT t.id, ST_MakeEnvelope(t.x, t.y, t.x + 500, t.y + 500, 5179) AS g "
            "FROM unnest(CAST(:ids AS text[]), CAST(:xs AS float8[]), CAST(:ys AS float8[])) AS t(id, x, y)) "
            "SELECT c.id, u.adm_code, CASE WHEN ST_Within(c.g, u.geom) THEN :full ELSE ST_Area(ST_Intersection(c.g, u.geom)) END AS a "
            "FROM c JOIN national_units u ON u.geom && c.g AND ST_Intersects(u.geom, c.g) "
            "WHERE u.year = :year AND u.level = 'EMD' AND u.parent_code = ANY(:codes)"
        ), {"ids": part, "xs": [cells[i][0] for i in part], "ys": [cells[i][1] for i in part], "full": CELL_AREA, "year": year, "codes": codes})
        for cell_id, code, area in rows:
            share = float(area or 0) / CELL_AREA
            if share >= MIN_SHARE and code in index:
                out.setdefault(cell_id, []).append([index[code], round(min(share, 1.0), 3)])
    for value in out.values():
        value.sort()
    return out


def build_payload(sc: Any, year: int | None, rows: list[dict[str, Any]], weights: dict[str, list[list[float]]]) -> dict[str, Any]:
    cells = [0] * len(rows)
    covered = [0.0] * len(rows)
    for pairs in weights.values():
        for index, share in pairs:
            cells[int(index)] += 1
            covered[int(index)] += share
    dongs, features = [], []
    for i, row in enumerate(rows):
        area_km2 = (row.get("area_m2") or 0) / 1_000_000
        population = row.get("population")
        dongs.append({
            "code": row["adm_code"], "name": row.get("adm_name") or row["adm_code"], "sigungu": row.get("parent_code"),
            "population": population, "population_status": row.get("population_status"),
            "households": row.get("households"), "household_status": row.get("household_status"),
            "area_km2": round(area_km2, 3) if area_km2 else None,
            "density": round(population / area_km2, 1) if population is not None and area_km2 else None,
            "cells": cells[i], "cell_area_km2": round(covered[i] * CELL_AREA / 1_000_000, 3),
        })
        outline = row.get("outline")
        if outline:
            features.append({"type": "Feature", "id": i, "geometry": json.loads(outline) if isinstance(outline, str) else outline,
                             "properties": {"i": i, "code": row["adm_code"], "name": row.get("adm_name")}})
    return {
        "region": sc.code, "year": year, "dongs": dongs, "boundaries": {"type": "FeatureCollection", "features": features},
        "weights": weights,
        "source": f"SGIS {year or ''} 행정동 경계·인구·가구 (10m 단순화) · 겹침 비율 = 격자와 행정동의 겹친 면적 ÷ 250,000㎡",
    }


def region_dongs(db: Any, sc: Any) -> bytes:
    from .regions import grid_cell_geometry
    codes = region_sgis_codes(db, sc)
    year, rows = load_dongs(db, codes)
    key = (sc.code, len(sc.grid_ids), year, tuple(codes), len(rows))
    if key in _CACHE:
        return _CACHE[key]
    cells: dict[str, tuple[float, float]] = {}
    for grid_id in sc.grid_ids:
        box = grid_cell_geometry(grid_id)
        if box:
            cells[grid_id] = (box[0], box[1])
    order = [row["adm_code"] for row in rows]
    try:
        weights = cell_shares_sql(db, cells, codes, year, order) if rows else {}
    except Exception:  # noqa: BLE001 - no PostGIS: same numbers in Python
        db.rollback()
        weights = cell_shares_py(cells, [_rings(json.loads(row["metric"])) if row.get("metric") else [] for row in rows])
    body = json.dumps(build_payload(sc, year, rows, weights), ensure_ascii=False, separators=(",", ":")).encode()
    if len(_CACHE) >= 16:
        _CACHE.pop(next(iter(_CACHE)))
    _CACHE[key] = body
    return body


@router.get("/dongs")
def dongs(region: str | None = Query(None, max_length=10)) -> Response:
    """읍면동(행정동) of the region: 공식 인구·가구, 경계, 격자별 겹침 비율."""
    from .regions import RegionNotReady, scope
    with Session() as db:
        try:
            sc = scope(db, region)
        except RegionNotReady as exc:
            raise HTTPException(404, str(exc)) from None
        return Response(region_dongs(db, sc), media_type="application/json")
