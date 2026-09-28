"""VWorld 2D Data API collectors for zoning and continuous cadastral parcels."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from geoalchemy2 import Geometry
from geoalchemy2.shape import from_shape, to_shape
from pyproj import Transformer
from shapely.geometry import shape
from shapely.validation import make_valid
from sqlalchemy import DateTime, Float, JSON, String, delete, func, select, text
from sqlalchemy.orm import Mapped, mapped_column

from .cache import CachedClient, ExternalError, parse_cached_response
from .db import Base
from .models import DataSource, Grid, RawDataAsset

VWORLD_API_URL = "https://api.vworld.kr/req/data"
VWORLD_GUIDE_URL = "https://www.vworld.kr/dev/v4dv_2ddataguide2_s001.do"
_TO_5179 = Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)
_TO_4326 = Transformer.from_crs("EPSG:5179", "EPSG:4326", always_xy=True)
# 용도지역 layers (all stored in vworld_zoning_areas, id "<dataset>:<feature id>"): 도시지역 세분 and the three
# non-urban 용도지역. The layer name is the zone when a feature carries no ``uname``.
ZONING_LAYERS = {"zoning": "도시지역", "zoning_management": "관리지역", "zoning_agriculture": "농림지역",
                 "zoning_conservation": "자연환경보전지역"}
# 용도구역·지구단위계획: stored in vworld_special_areas.
SPECIAL_LAYERS = {"greenbelt": "GREENBELT", "district_plan": "DISTRICT_PLAN"}
DATASETS = {"cadastral", "buildings", *ZONING_LAYERS, *SPECIAL_LAYERS}
GRID_SIZE_M = 500


class VworldZoningArea(Base):
    __tablename__ = "vworld_zoning_areas"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    source_feature_id: Mapped[str] = mapped_column(String, index=True)
    zone_code: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    zone_name: Mapped[str | None] = mapped_column(String, nullable=True)
    source_crs: Mapped[str] = mapped_column(String)
    geom: Mapped[object] = mapped_column(Geometry("GEOMETRY", srid=5179, spatial_index=True))
    properties: Mapped[dict] = mapped_column(JSON)
    geometry_repaired: Mapped[bool] = mapped_column(default=False)
    source: Mapped[str] = mapped_column(String)
    raw_source_id: Mapped[str | None] = mapped_column(String, nullable=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class VworldSpecialArea(Base):
    """개발제한구역 (LT_C_UD801) and 지구단위계획구역 (LT_C_UPISUQ161): areas whose own rules override the 용도지역 limits."""
    __tablename__ = "vworld_special_areas"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    kind: Mapped[str] = mapped_column(String, index=True)              # GREENBELT | DISTRICT_PLAN
    name: Mapped[str | None] = mapped_column(String, nullable=True)    # 지구단위계획 이름 (dgm_nm) / "개발제한구역"
    declared_area_m2: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_feature_id: Mapped[str] = mapped_column(String, index=True)
    source_crs: Mapped[str] = mapped_column(String)
    geom: Mapped[object] = mapped_column(Geometry("GEOMETRY", srid=5179, spatial_index=True))
    properties: Mapped[dict] = mapped_column(JSON)
    geometry_repaired: Mapped[bool] = mapped_column(default=False)
    source: Mapped[str] = mapped_column(String)
    raw_source_id: Mapped[str | None] = mapped_column(String, nullable=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class CadastralParcel(Base):
    __tablename__ = "cadastral_parcels"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    source_feature_id: Mapped[str] = mapped_column(String, index=True)
    pnu: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    legal_dong_code: Mapped[str | None] = mapped_column(String, nullable=True)
    lot_main_no: Mapped[str | None] = mapped_column(String, nullable=True)
    lot_sub_no: Mapped[str | None] = mapped_column(String, nullable=True)
    source_crs: Mapped[str] = mapped_column(String)
    geom: Mapped[object] = mapped_column(Geometry("GEOMETRY", srid=5179, spatial_index=True))
    properties: Mapped[dict] = mapped_column(JSON)
    geometry_repaired: Mapped[bool] = mapped_column(default=False)
    source: Mapped[str] = mapped_column(String)
    raw_source_id: Mapped[str | None] = mapped_column(String, nullable=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class VworldBuilding(Base):
    """Official 도로명주소 건물 footprint (VWorld LT_C_SPBD) with floors and use code.

    ``grid_id`` is the project 500m cell containing the building's representative point;
    ``centroid_lon/lat`` (EPSG:4326) serve viewport queries for the map.
    """
    __tablename__ = "vworld_buildings"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    source_feature_id: Mapped[str] = mapped_column(String, index=True)
    building_mgmt_no: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    use_code: Mapped[str | None] = mapped_column(String, nullable=True)
    use_label: Mapped[str | None] = mapped_column(String, nullable=True)
    use_category: Mapped[str] = mapped_column(String, index=True, default="UNKNOWN")
    above_floors: Mapped[int | None] = mapped_column(nullable=True)
    below_floors: Mapped[int | None] = mapped_column(nullable=True)
    footprint_m2: Mapped[float | None] = mapped_column(Float, nullable=True)
    centroid_lon: Mapped[float] = mapped_column(Float, index=True)
    centroid_lat: Mapped[float] = mapped_column(Float, index=True)
    grid_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    source_crs: Mapped[str] = mapped_column(String)
    geom: Mapped[object] = mapped_column(Geometry("GEOMETRY", srid=5179, spatial_index=True))
    properties: Mapped[dict] = mapped_column(JSON)
    geometry_repaired: Mapped[bool] = mapped_column(default=False)
    source: Mapped[str] = mapped_column(String)
    raw_source_id: Mapped[str | None] = mapped_column(String, nullable=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


def grid_cell_id(x: float, y: float) -> str:
    """Project 500m cell id (EPSG:5179 lower-left corner) containing a metric point."""
    return f"cell_{int(x // GRID_SIZE_M) * GRID_SIZE_M}_{int(y // GRID_SIZE_M) * GRID_SIZE_M}"


def building_values(properties: dict[str, Any], geometry: Any, grid_ids: set[str] | None = None) -> dict[str, Any]:
    """Normalized columns for one LT_C_SPBD feature (geometry in EPSG:5179)."""
    from .building_use import classify_use, floors
    point = geometry.representative_point()
    lon, lat = _TO_4326.transform(point.x, point.y)
    cell = grid_cell_id(point.x, point.y)
    code = properties.get("bdtyp_cd")
    label, category = classify_use(code)
    name = str(properties.get("buld_nm") or "").strip() or None
    return {
        "building_mgmt_no": str(properties.get("bd_mgt_sn") or "").strip() or None,
        "name": name, "use_code": str(code).strip() if code not in (None, "") else None,
        "use_label": label, "use_category": category,
        "above_floors": floors(properties.get("gro_flo_co")), "below_floors": floors(properties.get("und_flo_co")),
        "footprint_m2": round(float(geometry.area), 2),
        "centroid_lon": round(float(lon), 7), "centroid_lat": round(float(lat), 7),
        "grid_id": cell if grid_ids is None or cell in grid_ids else None,
    }


class GridZoningStat(Base):
    __tablename__ = "grid_zoning_stats"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    grid_id: Mapped[str] = mapped_column(String, index=True)
    zoning_feature_id: Mapped[str] = mapped_column(String, index=True)
    zone_code: Mapped[str | None] = mapped_column(String, nullable=True)
    zone_name: Mapped[str | None] = mapped_column(String, nullable=True)
    intersection_area_m2: Mapped[float] = mapped_column(Float)
    grid_area_ratio: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String)


class VworldGridCoverage(Base):
    """Which analysis grids were actually requested from VWorld.

    Distinguishes "not collected" (no row) from "collected, no feature" (row with
    feature_count 0) so an empty grid is never shown as missing data or vice versa.
    """
    __tablename__ = "vworld_grid_coverage"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    dataset: Mapped[str] = mapped_column(String, index=True)
    grid_id: Mapped[str] = mapped_column(String, index=True)
    pages: Mapped[int] = mapped_column(default=0)
    feature_count: Mapped[int] = mapped_column(default=0)
    status: Mapped[str] = mapped_column(String)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


ZONE_CATEGORIES = (("주거", "RESIDENTIAL"), ("상업", "COMMERCIAL"), ("공업", "INDUSTRIAL"), ("녹지", "GREEN"))


def zone_category(zone_name: str | None) -> str:
    """Map an official 용도지역 name to a display category without inventing values."""
    name = str(zone_name or "")
    for keyword, category in ZONE_CATEGORIES:
        if keyword in name:
            return category
    return "OTHER" if name else "UNKNOWN"


def load_layer_config(path: str | Path | None = None) -> dict[str, Any]:
    config_path = Path(path) if path else Path(__file__).parents[1] / "config" / "vworld_layers.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    for name in DATASETS:
        if not config.get(name, {}).get("dataset_id") or not config[name].get("source_crs"):
            raise ValueError(f"VWorld {name} layer configuration is incomplete")
    return config


def bbox_filter(bounds: tuple[float, float, float, float]) -> str:
    minx, miny, maxx, maxy = bounds
    if maxx <= minx or maxy <= miny or (maxx - minx) * (maxy - miny) > 2_000_000:
        raise ValueError("VWorld bbox must be positive and at most 2km²")
    # VWorld expects BOX(minx,miny,maxx,maxy) with plain decimals; ':g' produced
    # scientific notation (1.765e+06) that the provider rejects as INVALID_RANGE.
    return "BOX(" + ",".join(_plain(value) for value in (minx, miny, maxx, maxy)) + ")"


def _plain(value: float) -> str:
    text = f"{float(value):.6f}".rstrip("0").rstrip(".")
    return text if text not in {"", "-0"} else "0"


def parse_vworld_response(body: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(body.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExternalError("VWorld 응답 파싱 실패") from exc
    response = payload.get("response", payload)
    status = str(response.get("status", "OK")).upper()
    if status == "NOT_FOUND":
        return {"status": "EMPTY_VALID", "features": [], "total_records": 0, "total_pages": 0, "current_page": 1}
    if status != "OK":
        error = response.get("error") or {}
        code = error.get("code") if isinstance(error, dict) else "UNKNOWN"
        if code in {"INVALID_KEY", "INCORRECT_KEY", "UNAVAILABLE_KEY"}:
            raise ExternalError(f"VWorld 인증 실패: provider_code={code}")
        if code == "OVER_REQUEST_LIMIT":
            raise ExternalError("VWorld 호출 제한 초과")
        raise ExternalError(f"VWorld API 오류: provider_code={code}")
    result = response.get("result") or response
    collection = result.get("featureCollection", result)
    features = []
    for raw in collection.get("features") or []:
        try:
            geometry = shape(raw.get("geometry"))
        except (TypeError, ValueError) as exc:
            raise ExternalError("VWorld geometry 파싱 실패") from exc
        repaired = not geometry.is_valid
        if repaired:
            geometry = make_valid(geometry)
        if geometry.is_empty or not geometry.is_valid:
            raise ExternalError("VWorld geometry 유효성 검사 실패")
        properties = dict(raw.get("properties") or {})
        feature_id = str(raw.get("id") or properties.get("gml_id") or "")
        if not feature_id:
            feature_id = hashlib.sha256((geometry.wkb + json.dumps(properties, sort_keys=True, ensure_ascii=False).encode())).hexdigest()
        features.append({"id": feature_id, "properties": properties, "geometry": geometry, "geometry_repaired": repaired})
    record, page = response.get("record") or {}, response.get("page") or {}
    return {
        "status": "SUCCESS", "features": features,
        "total_records": int(record.get("total") or len(features)),
        "total_pages": int(page.get("total") or 1), "current_page": int(page.get("current") or 1),
    }


def zoning_intersections(grids: list[dict[str, Any]], zones: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for grid in grids:
        grid_area = grid["geometry"].area
        for zone in zones:
            if not grid["geometry"].intersects(zone["geometry"]):
                continue
            area = grid["geometry"].intersection(zone["geometry"]).area
            if area <= 0:
                continue
            rows.append({
                "grid_id": grid["id"], "zoning_feature_id": zone["id"],
                "zone_code": zone.get("zone_code"), "zone_name": zone.get("zone_name"),
                "intersection_area_m2": float(area), "grid_area_ratio": float(area / grid_area) if grid_area else 0,
            })
    return sorted(rows, key=lambda row: (row["grid_id"], row.get("zone_code") or "", row["zoning_feature_id"]))


def _grid_shapes(db: Any, scope: str) -> list[dict[str, Any]]:
    """Cells of the original study region (this whole-city collection predates the per-region steps; other regions use
    ``collect_vworld_cells`` over their own cells, so opening regions nationwide never widens this request)."""
    limit = 1 if scope == "smoke" else 25 if scope == "limited" else None
    query = select(Grid).order_by(Grid.id)
    try:
        from .regions import DEFAULT_REGION, region_grid_ids
        own = region_grid_ids(db, DEFAULT_REGION)
    except Exception:  # noqa: BLE001
        own = frozenset()
    if own and scope == "full":
        query = query.where(Grid.id.in_(sorted(own)))
    if limit:
        query = query.limit(limit)
    rows = []
    for grid in db.scalars(query):
        try:
            geometry = to_shape(grid.geom)
        except Exception:
            source_shape = shape(grid.geojson["geometry"])
            from shapely.ops import transform
            geometry = transform(_TO_5179.transform, source_shape)
        rows.append({"id": grid.id, "geometry": geometry})
    return rows


def _source(db: Any, dataset: str) -> DataSource:
    source_id = f"vworld_{dataset}"
    names = {"zoning": "VWorld 도시지역 용도지역", "cadastral": "VWorld 연속지적도", "buildings": "VWorld 도로명주소 건물",
             "zoning_management": "VWorld 관리지역 (보전·생산·계획관리)", "zoning_agriculture": "VWorld 농림지역",
             "zoning_conservation": "VWorld 자연환경보전지역", "greenbelt": "VWorld 개발제한구역", "district_plan": "VWorld 지구단위계획구역"}
    categories = {"cadastral": "지적", "buildings": "건축물 정보", "greenbelt": "용도구역", "district_plan": "지구단위계획"}
    source = db.get(DataSource, source_id) or DataSource(
        id=source_id, category=categories.get(dataset, "용도지역"),
        name=names[dataset], organization="국토교통부 / VWorld", source_url=VWORLD_GUIDE_URL,
        source_type="OFFICIAL", status="NOT_COLLECTED",
        limitation="VWorld 2D Data API의 전주시 분석격자 bbox 조회 결과입니다.",
    )
    db.add(source);db.flush();return source


ZONING_STATS_SQL = (
    "INSERT INTO grid_zoning_stats (id, grid_id, zoning_feature_id, zone_code, zone_name, intersection_area_m2, grid_area_ratio, source) "
    "SELECT g.id || ':' || z.id, g.id, z.id, z.zone_code, z.zone_name, a.area, a.area / NULLIF(ST_Area(g.geom), 0), 'VWorld' "
    "FROM grid_500m g JOIN vworld_zoning_areas z ON ST_Intersects(g.geom, z.geom) "
    "CROSS JOIN LATERAL (SELECT ST_Area(ST_Intersection(g.geom, ST_MakeValid(z.geom))) AS area) a "
    "WHERE a.area > 0 {where}"
)


def rebuild_grid_zoning_stats(db: Any, grid_ids: list[str] | None = None) -> int:
    """Zoning share of every analysis cell (or of ``grid_ids`` only). PostGIS does the overlay; without
    PostGIS (tests) the same numbers come from shapely."""
    try:
        with db.begin_nested():
            if grid_ids is None:
                db.execute(delete(GridZoningStat))
                db.execute(text(ZONING_STATS_SQL.format(where="")))
            else:
                ids = sorted(set(grid_ids))
                for start in range(0, len(ids), 2000):
                    chunk = ids[start:start + 2000]
                    db.execute(delete(GridZoningStat).where(GridZoningStat.grid_id.in_(chunk)))
                    db.execute(text(ZONING_STATS_SQL.format(where="AND g.id = ANY(:ids)")), {"ids": chunk})
        db.commit()
        query = select(func.count()).select_from(GridZoningStat)
        return db.scalar(query if grid_ids is None else query.where(GridZoningStat.grid_id.in_(list(grid_ids)))) or 0
    except Exception:  # noqa: BLE001 - no PostGIS: shapely fallback
        db.rollback()
    grids = [g for g in _grid_shapes(db, "full") if grid_ids is None or g["id"] in set(grid_ids)]
    zones = [{"id": row.id, "zone_code": row.zone_code, "zone_name": row.zone_name, "geometry": to_shape(row.geom)} for row in db.scalars(select(VworldZoningArea))]
    rows = zoning_intersections(grids, zones)
    if grid_ids is None:
        db.execute(delete(GridZoningStat))
    else:
        db.execute(delete(GridZoningStat).where(GridZoningStat.grid_id.in_(list(grid_ids))))
    for row in rows:
        db.add(GridZoningStat(id=f"{row['grid_id']}:{row['zoning_feature_id']}", source="VWorld", **row))
    db.commit();return len(rows)


def _store_feature(db: Any, dataset: str, feature: dict[str, Any], layer: dict[str, Any], digest: str, grid_ids: set[str] | None) -> Any:
    """Upsert one parsed VWorld feature into its table (id ``<dataset>:<feature id>``)."""
    model = _model(dataset)
    props = feature["properties"]
    ident = f"{dataset}:{feature['id']}"
    row = db.get(model, ident)
    if dataset in ZONING_LAYERS:
        row = row or VworldZoningArea(id=ident, source_feature_id=feature["id"], source_crs=layer["source_crs"], source="VWorld")
        row.zone_name = (props.get("uname") or "").strip() or ZONING_LAYERS[dataset]
        row.zone_code = props.get("ucode") or props.get("zone_code") or feature["id"]
    elif dataset in SPECIAL_LAYERS:
        row = row or VworldSpecialArea(id=ident, kind=SPECIAL_LAYERS[dataset], source_feature_id=feature["id"], source_crs=layer["source_crs"], source="VWorld")
        row.name = (props.get("dgm_nm") or props.get("uname") or "").strip() or None
        try:
            row.declared_area_m2 = float(props.get("dgm_ar")) if props.get("dgm_ar") not in (None, "") else None
        except (TypeError, ValueError):
            row.declared_area_m2 = None
    elif dataset == "buildings":
        row = row or VworldBuilding(id=ident, source_feature_id=feature["id"], source_crs=layer["source_crs"], source="VWorld")
        for column, value in building_values(props, feature["geometry"], grid_ids).items():
            setattr(row, column, value)
    else:
        row = row or CadastralParcel(id=ident, source_feature_id=feature["id"], source_crs=layer["source_crs"], source="VWorld")
        row.pnu = str(props.get("pnu") or "") or None
        row.legal_dong_code = row.pnu[:10] if row.pnu else None
        row.lot_main_no = row.pnu[-8:-4] if row.pnu else None
        row.lot_sub_no = row.pnu[-4:] if row.pnu else None
    row.geom = from_shape(feature["geometry"], srid=5179)
    row.properties = props
    row.geometry_repaired = feature["geometry_repaired"]
    row.raw_source_id = digest
    row.collected_at = datetime.now(timezone.utc)
    db.add(row)
    return row


def _model(dataset: str) -> Any:
    if dataset in ZONING_LAYERS:
        return VworldZoningArea
    if dataset in SPECIAL_LAYERS:
        return VworldSpecialArea
    return {"cadastral": CadastralParcel, "buildings": VworldBuilding}[dataset]


def tiles_for(grid_ids: list[str], tile_m: int = 1000) -> dict[tuple[int, int], list[str]]:
    """Analysis cells grouped by the ``tile_m`` square (EPSG:5179 multiples) that holds them."""
    tiles: dict[tuple[int, int], list[str]] = {}
    for grid_id in sorted(set(grid_ids)):
        try:
            _, x, y = grid_id.split("_")
            key = (int(float(x)) // tile_m * tile_m, int(float(y)) // tile_m * tile_m)
        except ValueError:
            continue
        tiles.setdefault(key, []).append(grid_id)
    return tiles


def collect_vworld_cells(db: Any, dataset: str, grid_ids: list[str], *, tile_m: int = 1000, progress: Any = None,
                         client: CachedClient | None = None, api_key: str | None = None, domain: str | None = None,
                         data_dir: str | Path | None = None) -> dict[str, int]:
    """One study region's VWorld layer, asked per 1km tile (4 analysis cells per request instead of 1).

    Used by the region preparation. It records the coverage of every member cell (so an empty cell is
    "collected, nothing there", not missing) and leaves the source's overall status alone (that one
    describes the original region's full collection)."""
    if dataset not in DATASETS:
        raise ValueError("invalid VWorld dataset")
    source = _source(db, dataset);db.commit()
    key = (api_key or os.getenv("VWORLD_API_KEY", "")).strip()
    if not key:
        raise ExternalError("VWorld 인증 실패: VWORLD_API_KEY 미설정")
    layer = load_layer_config()[dataset]
    root = Path(data_dir or os.getenv("DATA_DIR", "data"))
    raw_root = root / "raw" / "vworld" / dataset / "tiles"
    raw_root.mkdir(parents=True, exist_ok=True)
    session = client or CachedClient(root / "cache" / "vworld", min_interval=0.3)
    url = os.getenv("VWORLD_DATA_URL", VWORLD_API_URL)
    domain_value = domain or os.getenv("VWORLD_DOMAIN", "http://localhost")
    member = set(grid_ids)
    tiles = tiles_for(grid_ids, tile_m)
    stats = {"requests": 0, "features": 0, "tiles": len(tiles), "cells": len(member), "geometry_repaired": 0}
    for index, ((x0, y0), cells) in enumerate(sorted(tiles.items()), 1):
        xs = [int(c.split("_")[1]) for c in cells]
        ys = [int(c.split("_")[2]) for c in cells]
        bounds = (min(xs), min(ys), max(xs) + GRID_SIZE_M, max(ys) + GRID_SIZE_M)
        page, found, per_cell = 1, 0, {c: 0 for c in cells}
        while True:
            params = {"service": "data", "version": "2.0", "request": "GetFeature", "key": key, "format": "json", "size": 1000, "page": page,
                      "data": layer["dataset_id"], "geomFilter": bbox_filter(bounds), "geometry": "true", "attribute": "true",
                      "crs": layer["source_crs"], "domain": domain_value}
            if str(domain_value).strip().lower() in {"none", "-"}:
                params.pop("domain")
            result = session.get("VWorld", f"{dataset}-tile{tile_m}-{x0}-{y0}-{page}", url, params)
            stats["requests"] += 1
            raw_path = raw_root / f"{x0}_{y0}-page-{page}.json"
            raw_path.write_bytes(result["body"])
            parsed = parse_cached_response(session, result, parse_vworld_response)
            digest = hashlib.sha256(result["body"] + f"{dataset}:tile:{x0}:{y0}:{page}".encode()).hexdigest()
            asset = db.get(RawDataAsset, digest) or RawDataAsset(id=digest, source_id=source.id, provider=source.organization, source_url=layer["verified_reference"],
                                                                 reference_period="수집 시점", storage_location=str(raw_path), collection_status=parsed["status"])
            asset.row_count = len(parsed["features"])
            asset.request_parameters = {k: v for k, v in params.items() if k not in {"key", "domain"}}
            db.add(asset)
            for feature in parsed["features"]:
                row = _store_feature(db, dataset, feature, layer, digest, member)
                stats["geometry_repaired"] += feature["geometry_repaired"]
                cell = getattr(row, "grid_id", None)
                if cell in per_cell:
                    per_cell[cell] += 1
            found += len(parsed["features"])
            db.commit()
            if page >= parsed["total_pages"]:
                break
            page += 1
        stats["features"] += found
        for cell in cells:
            count = per_cell[cell] if dataset == "buildings" else found
            coverage = db.get(VworldGridCoverage, f"{dataset}:{cell}") or VworldGridCoverage(id=f"{dataset}:{cell}", dataset=dataset, grid_id=cell)
            coverage.pages = page
            coverage.feature_count = count
            coverage.status = "EMPTY_VALID" if count == 0 else "SUCCESS"
            coverage.collected_at = datetime.now(timezone.utc)
            db.add(coverage)
        db.commit()
        if progress:
            progress(index / max(1, len(tiles)), f"VWorld {dataset} {index}/{len(tiles)} 타일")
    if dataset in ZONING_LAYERS:
        stats["grid_intersections"] = rebuild_grid_zoning_stats(db, sorted(member))
    model = _model(dataset)
    query = select(func.count()).select_from(model)
    if model is VworldZoningArea or model is VworldSpecialArea:
        query = query.where(model.id.like(f"{dataset}:%"))
    stored = db.scalar(query) or 0
    source.normalized_row_count = stored
    source.collected_at = datetime.now(timezone.utc)
    db.commit()
    return stats


def collect_vworld(db: Any, dataset: str, scope: str = "smoke", *, client: CachedClient | None = None, api_key: str | None = None, domain: str | None = None, data_dir: str | Path | None = None) -> dict[str, int]:
    if dataset not in DATASETS or scope not in {"smoke", "limited", "full"}:
        raise ValueError("invalid VWorld dataset or scope")
    source = _source(db, dataset);db.commit()
    key = (api_key or os.getenv("VWORLD_API_KEY", "")).strip()
    if not key:
        source.status="NEEDS_API_KEY";db.commit();raise ExternalError("VWorld 인증 실패: VWORLD_API_KEY 미설정")
    if dataset == "cadastral" and scope == "full" and os.getenv("VWORLD_CADASTRAL_FULL", "").lower() not in {"1", "true", "yes"}:
        raise ValueError("연속지적 전체 수집은 필지 수가 많아 VWORLD_CADASTRAL_FULL=true 설정 시에만 실행합니다")
    if scope == "full" and not db.scalar(select(RawDataAsset.id).where(RawDataAsset.source_id == source.id, RawDataAsset.collection_status.in_(["SUCCESS", "EMPTY_VALID", "COLLECTED"])).limit(1)):
        raise ValueError("VWorld full 수집 전에 smoke 성공이 필요합니다")
    layer=load_layer_config()[dataset];grids=_grid_shapes(db,scope)
    if not grids:raise ValueError("프로젝트 분석격자가 없습니다")
    root=Path(data_dir or os.getenv("DATA_DIR","data"));raw_root=root/"raw"/"vworld"/dataset;raw_root.mkdir(parents=True,exist_ok=True)
    session=client or CachedClient(root/"cache"/"vworld",min_interval=0.3)
    url=os.getenv("VWORLD_DATA_URL",VWORLD_API_URL);domain_value=domain or os.getenv("VWORLD_DOMAIN","http://localhost")
    requested=normalized=repaired=empty=0
    model=_model(dataset)
    grid_ids=set(db.scalars(select(Grid.id))) if dataset=="buildings" else set()
    for grid in grids:
        page=1;grid_features=0
        while True:
            params={"service":"data","version":"2.0","request":"GetFeature","key":key,"format":"json","size":1000,"page":page,"data":layer["dataset_id"],"geomFilter":bbox_filter(grid["geometry"].bounds),"geometry":"true","attribute":"true","crs":layer["source_crs"],"domain":domain_value}
            if str(domain_value).strip().lower() in {"none","-"}:params.pop("domain")
            result=session.get("VWorld",f"{dataset}-{grid['id']}-{page}",url,params);requested+=1
            raw_path=raw_root/f"{grid['id']}-page-{page}.json";raw_path.write_bytes(result["body"])
            parsed=parse_cached_response(session,result,parse_vworld_response);empty+=parsed["status"]=="EMPTY_VALID"
            digest=hashlib.sha256(result["body"]+f"{dataset}:{grid['id']}:{page}".encode()).hexdigest()
            asset=db.get(RawDataAsset,digest) or RawDataAsset(id=digest,source_id=source.id,provider=source.organization,source_url=layer["verified_reference"],reference_period="수집 시점",storage_location=str(raw_path),collection_status=parsed["status"])
            asset.row_count=len(parsed["features"]);asset.request_parameters={key_:value for key_,value in params.items() if key_ not in {"key","domain"}};db.add(asset)
            for feature in parsed["features"]:
                _store_feature(db,dataset,feature,layer,digest,grid_ids);normalized+=1;repaired+=feature["geometry_repaired"]
            grid_features+=len(parsed["features"])
            db.commit()
            if page>=parsed["total_pages"]:break
            page+=1
        coverage=db.get(VworldGridCoverage,f"{dataset}:{grid['id']}") or VworldGridCoverage(id=f"{dataset}:{grid['id']}",dataset=dataset,grid_id=grid["id"])
        coverage.pages=page;coverage.feature_count=grid_features;coverage.status="EMPTY_VALID" if grid_features==0 else "SUCCESS";coverage.collected_at=datetime.now(timezone.utc);db.add(coverage);db.commit()
    stored=db.scalar(select(func.count()).select_from(model)) or 0
    intersections=rebuild_grid_zoning_stats(db) if dataset in ZONING_LAYERS else 0
    quality=f"{layer['dataset_id']} feature {stored}개 / geometry 보정 {repaired}개"
    if dataset=="buildings":
        with_floors=db.scalar(select(func.count()).select_from(VworldBuilding).where(VworldBuilding.above_floors.is_not(None))) or 0
        with_use=db.scalar(select(func.count()).select_from(VworldBuilding).where(VworldBuilding.use_category!="UNKNOWN")) or 0
        covered=db.scalar(select(func.count()).select_from(VworldGridCoverage).where(VworldGridCoverage.dataset=="buildings")) or 0
        quality=f"건물 {stored:,}동 / 지상층수 확인 {with_floors:,}동 / 용도코드 확인 {with_use:,}동 / 요청 격자 {covered}개"
    source.status="COLLECTED" if scope == "full" else "PARTIAL";source.raw_row_count=requested;source.normalized_row_count=stored;source.missing_count=0;source.reference_period="수집 시점";source.quality=quality;source.collected_at=datetime.now(timezone.utc);db.commit()
    return {"requests":requested,"normalized":stored,"geometry_repaired":repaired,"empty_requests":empty,"grid_intersections":intersections}
