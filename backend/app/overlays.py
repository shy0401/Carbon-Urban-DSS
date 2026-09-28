"""Map overlays built only from collected official data.

* VWorld 용도지역 polygons (LT_C_UQ111) and per-grid zoning shares.
* SGIS 행정동 boundaries joined with SGIS administrative population/households.

Administrative statistics are displayed on their own official boundaries. They are
never distributed to the project 500m grid.
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import case, func, select, text

from .db import Session
from .settings import DEFAULT_YEAR

router = APIRouter(prefix="/api/map", tags=["map"])

EMPTY = {"type": "FeatureCollection", "features": []}


def _table_exists(db: Any, name: str) -> bool:
    return bool(db.execute(text("SELECT to_regclass(:name)"), {"name": name}).scalar())


def summarize_zoning(coverage: list[tuple[str, str]], stats: list[tuple[str, str | None, float]]) -> dict[str, dict[str, Any]]:
    """Pure per-grid zoning shares (0–100 %).

    ``coverage``: (grid_id, status) for grids actually requested from VWorld.
    ``stats``: (grid_id, zone_name, grid_area_ratio) intersections.
    Unrequested grids are absent (missing); a requested grid without features is 0 %.
    """
    from .vworld import zone_category

    summary: dict[str, dict[str, Any]] = {grid_id: {"zoning_status": status, "shares": {}} for grid_id, status in coverage}
    for grid_id, zone_name, ratio in stats:
        item = summary.get(grid_id)
        if item is None:
            continue
        category = zone_category(zone_name)
        item["shares"][category] = item["shares"].get(category, 0.0) + float(ratio or 0)
    for item in summary.values():
        shares = {key: min(value, 1.0) for key, value in item["shares"].items()}
        item["residential_zone_ratio"] = round(shares.get("RESIDENTIAL", 0.0) * 100, 2)
        item["urban_zone_ratio"] = round(min(sum(shares.values()), 1.0) * 100, 2)
        item["dominant_zone"] = max(shares, key=shares.get) if shares else None
        item["shares"] = {key: round(value * 100, 2) for key, value in shares.items()}
    return summary


def grid_zoning_summary(db: Any) -> dict[str, dict[str, Any]]:
    from .vworld import GridZoningStat, VworldGridCoverage

    if not _table_exists(db, "vworld_grid_coverage"):
        return {}
    coverage = [(row.grid_id, row.status) for row in db.scalars(select(VworldGridCoverage).where(VworldGridCoverage.dataset == "zoning"))]
    stats = [(row.grid_id, row.zone_name, row.grid_area_ratio) for row in db.scalars(select(GridZoningStat))]
    return summarize_zoning(coverage, stats)


def grid_building_summary(db: Any, grid_ids: Any = None) -> dict[str, dict[str, Any]]:
    """Per-grid official building indicators (VWorld LT_C_SPBD), aggregated in SQL (``grid_ids``: one region)."""
    from .building_use import summarize_grid_aggregates
    from .vworld import VworldBuilding, VworldGridCoverage

    if not _table_exists(db, "vworld_buildings"):
        return {}
    requested = {row.grid_id: row.status for row in db.scalars(select(VworldGridCoverage).where(VworldGridCoverage.dataset == "buildings"))
                 if grid_ids is None or row.grid_id in grid_ids}
    known = VworldBuilding.above_floors.is_not(None)
    rows = db.execute(select(
        VworldBuilding.grid_id, VworldBuilding.use_category, func.count(),
        func.coalesce(func.sum(VworldBuilding.footprint_m2), 0.0),
        func.count(VworldBuilding.above_floors),
        func.coalesce(func.sum(case((known, VworldBuilding.footprint_m2), else_=0.0)), 0.0),
        func.coalesce(func.sum(VworldBuilding.footprint_m2 * VworldBuilding.above_floors), 0.0),
        func.coalesce(func.sum(VworldBuilding.above_floors), 0),
        func.max(VworldBuilding.above_floors),
    ).where(VworldBuilding.grid_id.is_not(None)).group_by(VworldBuilding.grid_id, VworldBuilding.use_category)).all()
    if grid_ids is not None:
        rows = [row for row in rows if row[0] in grid_ids]
    if not rows and not requested:
        return {}
    aggregates = [
        {"grid_id": grid_id, "use_category": category, "count": count, "footprint_m2": footprint,
         "floors_known_count": known_count, "floors_known_footprint_m2": known_footprint,
         "floor_area_est_m2": floor_area, "floor_sum": floor_sum, "max_floors": max_floors}
        for grid_id, category, count, footprint, known_count, known_footprint, floor_area, floor_sum, max_floors in rows
    ]
    return summarize_grid_aggregates(aggregates, requested)


def parse_bbox(value: str) -> tuple[float, float, float, float]:
    """Validate "minLon,minLat,maxLon,maxLat" (EPSG:4326) for viewport queries."""
    try:
        west, south, east, north = (float(part) for part in value.split(","))
    except ValueError:
        raise ValueError("bbox는 minLon,minLat,maxLon,maxLat 형식이어야 합니다") from None
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise ValueError("bbox 범위가 올바르지 않습니다")
    if (east - west) > 0.2 or (north - south) > 0.2:
        raise ValueError("건물 도형은 약 20km 이내 화면에서만 조회합니다. 지도를 확대하세요")
    return west, south, east, north


def buildings_in_bbox(db: Any, bbox: tuple[float, float, float, float], limit: int = 6000) -> dict[str, Any]:
    """Official building footprints whose representative point lies in the viewport."""
    from .building_use import CATEGORY_LABEL

    if not _table_exists(db, "vworld_buildings"):
        return dict(EMPTY, total=0, truncated=False, source=None)
    west, south, east, north = bbox
    where = "centroid_lon BETWEEN :west AND :east AND centroid_lat BETWEEN :south AND :north"
    params = {"west": west, "east": east, "south": south, "north": north}
    total = db.execute(text(f"SELECT count(*) FROM vworld_buildings WHERE {where}"), params).scalar() or 0
    rows = db.execute(text(
        "SELECT id, name, use_label, use_category, above_floors, below_floors, footprint_m2, grid_id, "
        "ST_AsGeoJSON(ST_Transform(geom, 4326), 6) AS geometry "
        f"FROM vworld_buildings WHERE {where} ORDER BY footprint_m2 DESC NULLS LAST LIMIT :limit"
    ), dict(params, limit=limit)).mappings()
    features = []
    for row in rows:
        if not row["geometry"]:
            continue
        features.append({"type": "Feature", "id": row["id"], "geometry": json.loads(row["geometry"]), "properties": {
            "id": row["id"], "name": row["name"], "use_label": row["use_label"], "use_category": row["use_category"],
            "use_category_label": CATEGORY_LABEL.get(row["use_category"], row["use_category"]),
            "above_floors": row["above_floors"], "below_floors": row["below_floors"],
            "footprint_m2": row["footprint_m2"], "grid_id": row["grid_id"], "quality": "OBSERVED",
        }})
    return {"type": "FeatureCollection", "features": features, "total": int(total), "truncated": int(total) > len(features),
            "source": "VWorld LT_C_SPBD 도로명주소 건물"}


def _admin_filter(sc: Any) -> tuple[str, dict[str, Any]]:
    """SQL condition limiting sgis_admin_boundaries to a region's SGIS 시군구 (its 행정동 carry them as parent_code)."""
    if sc is None or not getattr(sc, "sgis_codes", None):
        return "", {}
    return " AND parent_code = ANY(:parents)", {"parents": list(sc.sgis_codes)}


def city_boundary(db: Any, sc: Any = None) -> dict[str, Any] | None:
    """Region outline dissolved from the official SGIS 행정동 boundaries (latest year of that region), if collected."""
    if not _table_exists(db, "sgis_admin_boundaries"):
        return None
    where, params = _admin_filter(sc)
    row = db.execute(text(
        "SELECT reference_year, count(*) AS dongs, "
        "ST_AsGeoJSON(ST_Transform(ST_SimplifyPreserveTopology(ST_Union(geom), 5.0), 4326), 6) AS geometry, "
        "ST_Area(ST_Union(geom)) AS area_m2 "
        f"FROM sgis_admin_boundaries WHERE reference_year = (SELECT max(reference_year) FROM sgis_admin_boundaries WHERE TRUE{where}){where} "
        "GROUP BY reference_year"
    ), params).mappings().first()
    if not row or not row["geometry"]:
        return None
    name = getattr(sc, "short", None) or "전주시"
    return {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": json.loads(row["geometry"]), "properties": {
        "name": name, "source": f"SGIS {row['reference_year']} 행정동 경계 {row['dongs']}개 병합",
        "area_km2": round(float(row["area_m2"] or 0) / 1_000_000, 2), "quality": "OBSERVED",
    }}]}


def complex_features(db: Any, sc: Any = None) -> dict[str, Any]:
    """K-apt apartment complexes as points (official 공동주택 기본정보), with a floor-area plausibility flag.
    ``sc``: only the complexes of one study region (by its 법정 시·군·구 codes)."""
    from .grid_metrics import floor_area_status
    from .kapt import ApartmentComplex

    features = []
    for row in db.scalars(select(ApartmentComplex).where(ApartmentComplex.longitude.is_not(None), ApartmentComplex.latitude.is_not(None)).order_by(ApartmentComplex.kapt_code)):
        if sc is not None and not sc.owns_complex(row.bjd_code, row.grid_id):
            continue
        status, reason = floor_area_status(row.gross_floor_area_m2, row.households, row.management_area_m2)
        features.append({"type": "Feature", "id": row.kapt_code, "geometry": {"type": "Point", "coordinates": [row.longitude, row.latitude]}, "properties": {
            "kapt_code": row.kapt_code, "name": row.name, "households": row.households,
            "gross_floor_area_m2": row.gross_floor_area_m2, "floor_area_status": status, "floor_area_issue": reason,
            "building_count": row.building_count,
            "approval_date": row.approval_date, "heating_type": row.heating_type, "grid_id": row.grid_id,
        }})
    if not features and sc is not None and not getattr(sc, "is_default", True):
        listed = national_complex_features(db, sc)
        if listed["features"]:
            return listed
    return {"type": "FeatureCollection", "features": features, "source": "K-apt 공동주택 기본정보 (단지 상세)"}


def national_complex_features(db: Any, sc: Any) -> dict[str, Any]:
    """Before a region's own K-apt step: the national complex list (name, approval month, position; no households or
    floor area). The complex is placed in the analysis cell under its point."""
    from .national import NationalComplex

    try:
        from pyproj import Transformer
        to5179 = Transformer.from_crs(4326, 5179, always_xy=True).transform
        rows = list(db.scalars(select(NationalComplex).where(NationalComplex.longitude.is_not(None), NationalComplex.latitude.is_not(None),
                                                             NationalComplex.sigungu_code.in_(list(sc.legal_codes))).order_by(NationalComplex.kapt_code)))
    except Exception:  # noqa: BLE001 - national layer not collected or no projection library
        db.rollback()
        return {"type": "FeatureCollection", "features": []}
    features = []
    for row in rows:
        x, y = to5179(row.longitude, row.latitude)
        cell = f"cell_{int(x // 500 * 500)}_{int(y // 500 * 500)}"
        month = row.approval_month or ""
        features.append({"type": "Feature", "id": row.kapt_code, "geometry": {"type": "Point", "coordinates": [row.longitude, row.latitude]}, "properties": {
            "kapt_code": row.kapt_code, "name": row.name, "households": None, "gross_floor_area_m2": None, "floor_area_status": None,
            "floor_area_issue": None, "building_count": None,
            "approval_date": f"{month[:4]}-{month[4:6]}" if len(month) >= 6 else (month or None), "heating_type": None,
            "grid_id": cell if cell in sc.grid_ids else None, "listed_only": True,
        }})
    return {"type": "FeatureCollection", "features": features, "source": f"K-apt 전국 단지 목록 {rows[0].snapshot_month if rows else ''} (좌표·사용승인월만, 세대수는 상세 자료 수집 후)"}


def zoning_area_by_category(db: Any, grid_ids: Any = None) -> tuple[dict[str, float], int]:
    """Official zoning area inside the requested analysis grids (km², CALCULATED)."""
    from .vworld import GridZoningStat, VworldGridCoverage, zone_category

    if not _table_exists(db, "vworld_grid_coverage"):
        return {}, 0
    covered = len([g for g in db.scalars(select(VworldGridCoverage.grid_id).where(VworldGridCoverage.dataset == "zoning")) if grid_ids is None or g in grid_ids])
    totals: dict[str, float] = {}
    for row in db.scalars(select(GridZoningStat)):
        if grid_ids is not None and row.grid_id not in grid_ids:
            continue
        category = zone_category(row.zone_name)
        totals[category] = totals.get(category, 0.0) + float(row.intersection_area_m2 or 0)
    return {key: round(value / 1_000_000, 3) for key, value in sorted(totals.items())}, covered


def zoning_features(db: Any, tolerance_m: float = 2.0, sc: Any = None) -> dict[str, Any]:
    """Zoning polygons (``sc``: those touching the region's bounding box)."""
    from .vworld import zone_category

    if not _table_exists(db, "vworld_zoning_areas"):
        return EMPTY
    where, params = "", {"tol": tolerance_m}
    if sc is not None and getattr(sc, "bbox", None):
        west, south, east, north = sc.bbox
        where = " WHERE geom && ST_Transform(ST_MakeEnvelope(:w, :s, :e, :n, 4326), 5179)"
        params.update(w=west, s=south, e=east, n=north)
    rows = db.execute(text(
        "SELECT id, zone_code, zone_name, source, "
        "ST_AsGeoJSON(ST_Transform(ST_SimplifyPreserveTopology(geom, :tol), 4326), 6) AS geometry "
        f"FROM vworld_zoning_areas{where} ORDER BY id"
    ), params).mappings()
    features = []
    for row in rows:
        if not row["geometry"]:
            continue
        features.append({
            "type": "Feature", "id": row["id"], "geometry": json.loads(row["geometry"]),
            "properties": {"id": row["id"], "zone_code": row["zone_code"], "zone_name": row["zone_name"],
                           "category": zone_category(row["zone_name"]), "source": row["source"], "quality": "OBSERVED"},
        })
    return {"type": "FeatureCollection", "features": features}


def admin_features(db: Any, year: int | None = None, sc: Any = None) -> tuple[dict[str, Any], int | None]:
    """SGIS 행정동 boundaries with population/households (``sc``: the 행정동 of one study region)."""
    from .sgis import SgisAdminBoundary, SgisHouseholdAdmin, SgisPopulationAdmin

    if not _table_exists(db, "sgis_admin_boundaries"):
        return EMPTY, None
    query = select(SgisAdminBoundary.reference_year).distinct().order_by(SgisAdminBoundary.reference_year.desc())
    if sc is not None and getattr(sc, "sgis_codes", None):
        query = query.where(SgisAdminBoundary.parent_code.in_(list(sc.sgis_codes)))
    years = [value for value in db.scalars(query)]
    if not years:
        return EMPTY, None
    chosen = year if year in years else years[0]
    where, params = _admin_filter(sc)
    population = {row.adm_code: row for row in db.scalars(select(SgisPopulationAdmin).where(SgisPopulationAdmin.reference_year == chosen))}
    households = {row.adm_code: row for row in db.scalars(select(SgisHouseholdAdmin).where(SgisHouseholdAdmin.reference_year == chosen))}
    rows = db.execute(text(
        "SELECT id, adm_code, adm_name, parent_code, area_m2, "
        "ST_AsGeoJSON(ST_Transform(ST_SimplifyPreserveTopology(geom, 2.0), 4326), 6) AS geometry "
        f"FROM sgis_admin_boundaries WHERE reference_year = :year{where} ORDER BY adm_code"
    ), dict(params, year=chosen)).mappings()
    features = []
    for row in rows:
        pop = population.get(row["adm_code"])
        house = households.get(row["adm_code"])
        area_km2 = (row["area_m2"] or 0) / 1_000_000
        count = pop.population_count if pop else None
        features.append({
            "type": "Feature", "id": row["id"], "geometry": json.loads(row["geometry"]),
            "properties": {
                "adm_code": row["adm_code"], "adm_name": row["adm_name"], "parent_code": row["parent_code"],
                "reference_year": chosen, "area_km2": round(area_km2, 4) if area_km2 else None,
                "population": count, "population_status": pop.value_status if pop else "NOT_COLLECTED",
                "households": house.household_count if house else None,
                "household_status": house.value_status if house else "NOT_COLLECTED",
                # CALCULATED from the official boundary area; missing/suppressed stays null.
                "population_density": round(count / area_km2, 1) if count is not None and area_km2 else None,
            },
        })
    return {"type": "FeatureCollection", "features": features}, chosen


@router.get("/buildings")
def map_buildings(bbox: str = Query(..., description="minLon,minLat,maxLon,maxLat (EPSG:4326)"), limit: int = Query(6000, ge=1, le=12000)) -> dict[str, Any]:
    try:
        box = parse_bbox(bbox)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    with Session() as db:
        return buildings_in_bbox(db, box, limit)


@router.get("/overlays")
def overlays(year: int = Query(DEFAULT_YEAR, ge=2000, le=2100), region: str | None = Query(None, max_length=10)) -> dict[str, Any]:
    from .regions import RegionNotReady, scope
    with Session() as db:
        try:
            sc = scope(db, region)
        except RegionNotReady as exc:
            raise HTTPException(404, str(exc)) from None
        zoning = zoning_features(db, sc=None if sc.is_default else sc)
        admin, admin_year = admin_features(db, sc=sc)
        zoning_area, zoning_grids = zoning_area_by_category(db, sc.grid_ids)
        return {
            "zoning": zoning,
            "admin": admin,
            "meta": {
                "zoning_features": len(zoning["features"]),
                "admin_features": len(admin["features"]),
                "admin_reference_year": admin_year,
                "zoning_area_km2_by_category": zoning_area,
                "zoning_grids_covered": zoning_grids,
                "analysis_year": year,
                "crs": "EPSG:4326 (저장 EPSG:5179)",
                "sources": {
                    "zoning": "VWorld LT_C_UQ111 도시지역 용도지역",
                    "admin": "SGIS 행정동 경계·인구·가구 (행정구역 통계, 500m 격자 배분 없음)",
                },
                "truth_rules": [
                    "행정동 인구는 공식 행정동 경계에만 표시하며 500m 격자에 배분하지 않습니다.",
                    "용도지역 비율은 VWorld에 실제 요청한 격자만 계산하며 미요청 격자는 결측입니다.",
                    "비공개(*)·결측 통계는 0으로 바꾸지 않습니다.",
                ],
            },
        }


def grid_context(db: Any, grid_id: str | None) -> dict[str, Any]:
    """Official context for one analysis grid, kept separate from observed energy.

    * zoning: VWorld zoning shares inside the grid (CALCULATED from official polygons)
    * admin: SGIS 행정동 that overlap the grid, with the overlap share of the grid.
      Their population/households are administrative totals, never grid values.
    * complexes: K-apt complexes whose point lies in the grid (households, floor area)
    * sgis_grid: the SGIS 1km grid cell that contains the 500m grid (official, noisy, not divided)
    """
    context: dict[str, Any] = {"grid_id": grid_id, "zoning": None, "admin": [], "complexes": None, "buildings": None, "sgis_grid": None}
    if not grid_id:
        return context
    from .sgis_grid import grid_context_block
    # Parent SGIS 1km cell: official grid statistics (with disclosure noise), never divided into 500m.
    context["sgis_grid"] = grid_context_block(db, grid_id)
    zoning = grid_zoning_summary(db).get(grid_id)
    if zoning:
        context["zoning"] = {"status": zoning["zoning_status"], "shares_pct": zoning["shares"], "residential_pct": zoning["residential_zone_ratio"], "dominant": zoning["dominant_zone"], "source": "VWorld LT_C_UQ111"}
    if _table_exists(db, "sgis_admin_boundaries"):
        rows = db.execute(text(
            "SELECT b.adm_code, b.adm_name, b.reference_year, "
            "ST_Area(ST_Intersection(b.geom, g.geom)) / NULLIF(ST_Area(g.geom), 0) AS grid_share "
            "FROM sgis_admin_boundaries b JOIN grid_500m g ON g.id = :grid "
            # one boundary vintage: past years collected by 과거 수집 would list the same 행정동 again
            "WHERE b.reference_year = (SELECT max(reference_year) FROM sgis_admin_boundaries) AND ST_Intersects(b.geom, g.geom) ORDER BY grid_share DESC"
        ), {"grid": grid_id}).mappings()
        from .sgis import SgisHouseholdAdmin, SgisPopulationAdmin
        for row in rows:
            key = f"{row['reference_year']}:{row['adm_code']}"
            pop = db.get(SgisPopulationAdmin, key)
            house = db.get(SgisHouseholdAdmin, key)
            context["admin"].append({
                "adm_code": row["adm_code"], "adm_name": row["adm_name"], "reference_year": row["reference_year"],
                "grid_share_pct": round(float(row["grid_share"] or 0) * 100, 1),
                "population": pop.population_count if pop else None, "population_status": pop.value_status if pop else "NOT_COLLECTED",
                "households": house.household_count if house else None,
            })
    buildings = grid_building_summary(db).get(grid_id)
    if buildings:
        context["buildings"] = dict(buildings, source="VWorld LT_C_SPBD 도로명주소 건물")
    from .kapt import ApartmentComplex
    complexes = list(db.scalars(select(ApartmentComplex).where(ApartmentComplex.grid_id == grid_id)))
    if complexes:
        from .grid_metrics import floor_area_status
        def total(field: str) -> float | None:
            values = [getattr(row, field) for row in complexes if getattr(row, field) is not None]
            return float(sum(values)) if values else None
        # Published floor areas outside the plausible range are excluded, not summed.
        usable = [row for row in complexes if floor_area_status(row.gross_floor_area_m2, row.households, row.management_area_m2)[0] == "OK"]
        context["complexes"] = {
            "count": len(complexes), "households": total("households"),
            "gross_floor_area_m2": float(sum(row.gross_floor_area_m2 for row in usable)) if usable else None,
            "with_floor_area": len(usable),
            "floor_area_excluded": [row.name for row in complexes if row not in usable],
            "names": [row.name for row in complexes][:10], "source": "K-apt 공동주택 기본정보",
        }
    return context


ZONE_LABEL = {"RESIDENTIAL": "주거", "COMMERCIAL": "상업", "INDUSTRIAL": "공업", "GREEN": "녹지", "OTHER": "기타", "UNKNOWN": "이름 없음"}


def context_facts(context: dict[str, Any]) -> list[dict[str, str]]:
    """Deterministic Korean sentences for the report (numbers come from the DB, not from AI)."""
    facts: list[dict[str, str]] = []
    zoning = context.get("zoning")
    if zoning and zoning.get("shares_pct"):
        parts = ", ".join(f"{ZONE_LABEL.get(k, k)} {v:.1f}%" for k, v in sorted(zoning["shares_pct"].items(), key=lambda item: -item[1]))
        facts.append({"id": "context_zoning", "text": f"대상 격자의 공식 용도지역 면적 구성은 {parts}입니다(VWorld LT_C_UQ111, 법적 허용 상한 판정 아님)."})
    elif zoning:
        facts.append({"id": "context_zoning", "text": "대상 격자는 VWorld에 조회했으나 도시지역 용도지역 도형이 없습니다."})
    else:
        facts.append({"id": "context_zoning", "text": "대상 격자의 용도지역은 아직 수집되지 않았습니다."})
    admin = [row for row in context.get("admin") or [] if row["grid_share_pct"] >= 1]
    if admin:
        parts = ", ".join(
            f"{row['adm_name'].split()[-1]}(격자의 {row['grid_share_pct']:.0f}%, 인구 {row['population']:,.0f}명)" if row["population"] is not None
            else f"{row['adm_name'].split()[-1]}(격자의 {row['grid_share_pct']:.0f}%, 인구 {'비공개' if row['population_status'] == 'SUPPRESSED' else '자료 없음'})"
            for row in admin[:4])
        facts.append({"id": "context_admin", "text": f"대상 격자는 행정동 {parts}에 걸쳐 있습니다. SGIS {admin[0]['reference_year']} 행정동 전체 통계이며 격자 인구가 아닙니다."})
    from .sgis_grid import context_fact
    sgis_fact = context_fact(context.get("sgis_grid"))
    if sgis_fact:
        facts.append(sgis_fact)
    buildings = context.get("buildings")
    if buildings and buildings.get("building_count"):
        floors = f", 지상층수 확인 {buildings['floors_known_pct']:.0f}% 기준 평균 {buildings['avg_floors']:.1f}층" if buildings.get("avg_floors") is not None else ""
        facts.append({"id": "context_buildings", "text": f"격자 안 공식 건물(도로명주소 건물)은 {buildings['building_count']:,}동, 건축면적 합계 {buildings['footprint_m2']:,.0f}m²로 격자 면적의 {buildings['coverage_pct']:.1f}%입니다{floors}."})
    complexes = context.get("complexes")
    if complexes:
        households = f"{complexes['households']:,.0f}세대" if complexes["households"] is not None else "세대수 자료 없음"
        area = f"연면적 {complexes['gross_floor_area_m2']:,.0f}m²({complexes['with_floor_area']}/{complexes['count']}개 단지 기준)" if complexes["gross_floor_area_m2"] is not None else "연면적 자료 없음"
        facts.append({"id": "context_complexes", "text": f"격자 안 K-apt 공동주택은 {complexes['count']}개 단지, {households}, {area}입니다."})
    return facts
