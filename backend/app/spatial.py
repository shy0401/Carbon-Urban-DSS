"""Pure spatial processing for OSM apartment fallback data.

All measurements and grid construction use EPSG:5179.  Returned GeoJSON is
EPSG:4326 so it can be rendered directly by MapLibre.  ``metric_cell`` returns
``(stable_id, polygon_in_epsg_5179)``.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any

from pyproj import Transformer
from shapely.geometry import Polygon, box, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform, unary_union


GRID_SIZE_METRES = 500
GRID_AREA_M2 = GRID_SIZE_METRES * GRID_SIZE_METRES
_TO_METRIC = Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)
_TO_WGS84 = Transformer.from_crs("EPSG:5179", "EPSG:4326", always_xy=True)


def _aligned_floor(value: float) -> int:
    quotient = value / GRID_SIZE_METRES
    nearest = round(quotient)
    if math.isclose(quotient, nearest, abs_tol=1e-8):
        return int(nearest * GRID_SIZE_METRES)
    return math.floor(quotient) * GRID_SIZE_METRES


def _aligned_ceil(value: float) -> int:
    quotient = value / GRID_SIZE_METRES
    nearest = round(quotient)
    if math.isclose(quotient, nearest, abs_tol=1e-8):
        return int(nearest * GRID_SIZE_METRES)
    return math.ceil(quotient) * GRID_SIZE_METRES


def _cell_id(x: int, y: int) -> str:
    return f"cell_{x}_{y}"


def metric_cell(lon: float, lat: float) -> tuple[str, Polygon]:
    """Return the aligned 500 m EPSG:5179 cell containing a WGS84 point."""

    metric_x, metric_y = _TO_METRIC.transform(lon, lat)
    x = _aligned_floor(metric_x)
    y = _aligned_floor(metric_y)
    return _cell_id(x, y), box(
        x,
        y,
        x + GRID_SIZE_METRES,
        y + GRID_SIZE_METRES,
    )


def _feature_collection(features: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "FeatureCollection", "features": features}


def _to_wgs84(geometry: BaseGeometry) -> dict[str, Any]:
    return mapping(transform(_TO_WGS84.transform, geometry))


def _to_metric(geometry: BaseGeometry) -> BaseGeometry:
    return transform(_TO_METRIC.transform, geometry)


def _polygon_from_osm(element: dict[str, Any]) -> BaseGeometry | None:
    points = element.get("geometry")
    if not isinstance(points, list) or len(points) < 3:
        return None

    try:
        coordinates = [(float(point["lon"]), float(point["lat"])) for point in points]
    except (KeyError, TypeError, ValueError):
        return None

    polygon: BaseGeometry = Polygon(coordinates)
    if not polygon.is_valid:
        polygon = polygon.buffer(0)
    if polygon.is_empty or polygon.area == 0:
        return None
    return polygon


def _parse_levels(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        numeric = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    if not numeric.is_integer() or numeric <= 0:
        return None
    return int(numeric)


def _osm_id(element: dict[str, Any]) -> str:
    return f"{element.get('type', 'element')}/{element.get('id')}"


def _normalise_boundary(
    boundary_geojson: dict[str, Any],
) -> tuple[dict[str, Any], BaseGeometry]:
    geojson_type = boundary_geojson.get("type")
    if geojson_type == "FeatureCollection":
        features = boundary_geojson.get("features", [])
        geometries = [
            shape(feature["geometry"])
            for feature in features
            if isinstance(feature, dict) and feature.get("geometry")
        ]
        collection = dict(boundary_geojson)
        collection["features"] = list(features)
    elif geojson_type == "Feature":
        geometries = [shape(boundary_geojson["geometry"])]
        collection = _feature_collection([boundary_geojson])
    else:
        geometries = [shape(boundary_geojson)]
        collection = _feature_collection(
            [
                {
                    "type": "Feature",
                    "properties": {},
                    "geometry": boundary_geojson,
                }
            ]
        )

    valid = [geometry for geometry in geometries if not geometry.is_empty]
    if not valid:
        raise ValueError("boundary_geojson contains no usable geometry")
    boundary_metric = unary_union([_to_metric(geometry) for geometry in valid])
    return collection, boundary_metric


def _inferred_boundary(
    geometries_metric: Iterable[BaseGeometry],
) -> tuple[dict[str, Any], BaseGeometry | None]:
    geometries = [geometry for geometry in geometries_metric if not geometry.is_empty]
    if not geometries:
        return _feature_collection([]), None

    extent = unary_union(geometries).envelope
    feature = {
        "type": "Feature",
        "properties": {
            "name": "OSM input study extent",
            "boundary_type": "study_extent_bbox",
            "source_type": "FALLBACK",
            "limitation": "Rectangle inferred from OSM input geometry bounds; not an administrative boundary.",
        },
        "geometry": _to_wgs84(extent),
    }
    return _feature_collection([feature]), extent


def _iter_grid_cells(boundary_metric: BaseGeometry) -> Iterable[tuple[str, int, int, Polygon]]:
    min_x, min_y, max_x, max_y = boundary_metric.bounds
    start_x = _aligned_floor(min_x)
    start_y = _aligned_floor(min_y)
    stop_x = _aligned_ceil(max_x)
    stop_y = _aligned_ceil(max_y)

    for y in range(start_y, stop_y, GRID_SIZE_METRES):
        for x in range(start_x, stop_x, GRID_SIZE_METRES):
            cell = box(x, y, x + GRID_SIZE_METRES, y + GRID_SIZE_METRES)
            if cell.intersection(boundary_metric).area > 0.01:
                yield _cell_id(x, y), x, y, cell


def _candidate_name(
    grid_id: str,
    residential_matches: list[tuple[float, dict[str, Any]]],
    building_tags: list[dict[str, Any]],
) -> str:
    named_landuse = [
        (area, tags.get("name") or tags.get("name:ko"))
        for area, tags in residential_matches
        if tags.get("name") or tags.get("name:ko")
    ]
    if named_landuse:
        return str(max(named_landuse, key=lambda item: item[0])[1])

    for tags in building_tags:
        apartment_name = tags.get("addr:housename")
        if apartment_name:
            return str(apartment_name)
    for tags in building_tags:
        district = tags.get("addr:subdistrict") or tags.get("addr:district")
        if district:
            return f"{district} 아파트 밀집 격자"
    return f"OSM 아파트 후보 {grid_id}"


def _candidate_road_address(
    residential_matches: list[tuple[float, dict[str, Any]]],
    building_tags: list[dict[str, Any]],
) -> str | None:
    landuse_by_overlap = [
        tags for _, tags in sorted(residential_matches, key=lambda item: -item[0])
    ]
    for tags in [*landuse_by_overlap, *building_tags]:
        street = tags.get("addr:street")
        number = tags.get("addr:housenumber")
        if street and number:
            return f"{street} {number}"
    return None


def build_spatial(
    osm: dict[str, Any],
    boundary_geojson: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build full 500 m grid cells and fallback apartment spatial metadata.

    OSM elements without usable polygon coordinates are skipped.  In particular,
    an Overpass relation containing only bounds/tags cannot yield a footprint
    without inventing geometry.  Missing ``building:levels`` remains null, as
    does that building's estimated floor area.
    """

    buildings: list[dict[str, Any]] = []
    residential: list[dict[str, Any]] = []
    all_metric_geometries: list[BaseGeometry] = []

    for element in osm.get("elements", []):
        if not isinstance(element, dict):
            continue
        tags = element.get("tags") or {}
        if not isinstance(tags, dict):
            continue
        is_apartment = tags.get("building") == "apartments"
        is_residential = tags.get("landuse") == "residential"
        if not (is_apartment or is_residential):
            continue

        geometry_wgs84 = _polygon_from_osm(element)
        if geometry_wgs84 is None:
            continue
        geometry_metric = _to_metric(geometry_wgs84)
        all_metric_geometries.append(geometry_metric)

        record = {
            "element": element,
            "tags": dict(tags),
            "wgs84": geometry_wgs84,
            "metric": geometry_metric,
        }
        if is_apartment:
            buildings.append(record)
        if is_residential:
            residential.append(record)

    if boundary_geojson is None:
        boundary, boundary_metric = _inferred_boundary(all_metric_geometries)
    else:
        boundary, boundary_metric = _normalise_boundary(boundary_geojson)

    if boundary_metric is None:
        return {
            "grids": _feature_collection([]),
            "buildings": _feature_collection([]),
            "residential_landuse": _feature_collection([]),
            "candidates": [],
            "boundary": boundary,
        }

    grid_records: dict[str, dict[str, Any]] = {}
    for grid_id, x, y, geometry in _iter_grid_cells(boundary_metric):
        grid_records[grid_id] = {
            "id": grid_id,
            "x": x,
            "y": y,
            "metric": geometry,
            "building_count": 0,
            "estimated_floor_area_m2": 0.0,
            "known_floor_area_count": 0,
            "building_tags": [],
            "residential_landuse_count": 0,
            "residential_landuse_area_m2": 0.0,
            "residential_matches": [],
        }

    building_features: list[dict[str, Any]] = []
    for record in buildings:
        representative = record["metric"].representative_point()
        lon, lat = _TO_WGS84.transform(representative.x, representative.y)
        grid_id, _ = metric_cell(lon, lat)
        if grid_id not in grid_records:
            continue

        tags = record["tags"]
        levels = _parse_levels(tags.get("building:levels"))
        footprint = round(record["metric"].area, 2)
        floor_area = round(footprint * levels, 2) if levels is not None else None
        properties = {
            "id": _osm_id(record["element"]),
            "name": tags.get("name"),
            "levels": levels,
            "footprint_m2": footprint,
            "floor_area_m2": floor_area,
            "grid_id": grid_id,
            "source_type": "FALLBACK",
            "tags": tags,
        }
        building_features.append(
            {"type": "Feature", "properties": properties, "geometry": mapping(record["wgs84"])}
        )
        grid = grid_records[grid_id]
        grid["building_count"] += 1
        grid["building_tags"].append(tags)
        if floor_area is not None:
            grid["estimated_floor_area_m2"] += floor_area
            grid["known_floor_area_count"] += 1

    residential_features: list[dict[str, Any]] = []
    for record in residential:
        tags = record["tags"]
        residential_features.append(
            {
                "type": "Feature",
                "properties": {
                    "id": _osm_id(record["element"]),
                    "name": tags.get("name") or tags.get("name:ko"),
                    "area_m2": round(record["metric"].area, 2),
                    "residential": tags.get("residential"),
                    "source_type": "FALLBACK",
                    "tags": tags,
                },
                "geometry": mapping(record["wgs84"]),
            }
        )
        for grid in grid_records.values():
            overlap_area = grid["metric"].intersection(record["metric"]).area
            if overlap_area <= 0.01:
                continue
            grid["residential_landuse_count"] += 1
            grid["residential_landuse_area_m2"] += overlap_area
            grid["residential_matches"].append((overlap_area, tags))

    grid_features: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    candidate_scores: dict[str, tuple[float, ...]] = {}
    for grid in grid_records.values():
        known_floor_area = (
            round(grid["estimated_floor_area_m2"], 2)
            if grid["known_floor_area_count"]
            else None
        )
        residential_area = round(grid["residential_landuse_area_m2"], 2)
        residential_names = sorted(
            {
                str(tags.get("name") or tags.get("name:ko"))
                for _, tags in grid["residential_matches"]
                if tags.get("name") or tags.get("name:ko")
            }
        )
        properties = {
            "id": grid["id"],
            "area_m2": GRID_AREA_M2,
            "x": grid["x"],
            "y": grid["y"],
            "building_count": grid["building_count"],
            "estimated_floor_area_m2": known_floor_area,
            "residential_landuse_count": grid["residential_landuse_count"],
            "residential_landuse_area_m2": residential_area,
            "residential_names": residential_names,
        }
        grid_features.append(
            {"type": "Feature", "properties": properties, "geometry": _to_wgs84(grid["metric"])}
        )

        if not grid["building_count"]:
            continue
        if known_floor_area is None:
            reason = f"OSM 아파트 건물 {grid['building_count']}개, 층수 정보 없음"
        else:
            reason = (
                f"OSM 아파트 건물 {grid['building_count']}개, "
                f"알려진 층수 기반 추정 연면적 {known_floor_area:g}m²"
            )
        road_address = _candidate_road_address(
            grid["residential_matches"], grid["building_tags"]
        )
        if road_address:
            reason = f"{reason}, OSM 도로명주소 {road_address}"
        candidate = {
            "grid_id": grid["id"],
            "name": _candidate_name(
                grid["id"], grid["residential_matches"], grid["building_tags"]
            ),
            "reason": reason,
            "building_count": grid["building_count"],
            "floor_area_m2": known_floor_area,
        }
        candidates.append(candidate)
        candidate_scores[grid["id"]] = (
            float(grid["building_count"]),
            float(residential_area),
            float(known_floor_area or 0),
        )

    candidates.sort(
        key=lambda candidate: (
            -candidate_scores[candidate["grid_id"]][0],
            -candidate_scores[candidate["grid_id"]][1],
            -candidate_scores[candidate["grid_id"]][2],
            candidate["grid_id"],
        )
    )
    return {
        "grids": _feature_collection(grid_features),
        "buildings": _feature_collection(building_features),
        "residential_landuse": _feature_collection(residential_features),
        "candidates": candidates,
        "boundary": boundary,
    }
