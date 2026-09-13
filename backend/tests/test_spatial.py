from __future__ import annotations

from pyproj import Transformer
from shapely.geometry import Polygon, mapping, shape
from shapely.ops import transform

from app.spatial import build_spatial, metric_cell


TO_WGS84 = Transformer.from_crs("EPSG:5179", "EPSG:4326", always_xy=True)
TO_METRIC = Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)


def _ring_wgs84(coords: list[tuple[float, float]]) -> list[dict[str, float]]:
    return [
        {"lon": lon, "lat": lat}
        for lon, lat in (TO_WGS84.transform(x, y) for x, y in coords)
    ]


def _polygon_geojson(coords: list[tuple[float, float]]) -> dict:
    transformed = [TO_WGS84.transform(x, y) for x, y in coords]
    return mapping(Polygon(transformed))


def test_metric_cell_is_a_stable_aligned_500_metre_square() -> None:
    lon, lat = TO_WGS84.transform(200_125, 350_275)

    cell_id, cell = metric_cell(lon, lat)

    assert cell_id == "cell_200000_350000"
    assert cell.bounds == (200_000.0, 350_000.0, 200_500.0, 350_500.0)
    assert cell.area == 250_000.0


def test_build_spatial_preserves_full_cells_and_building_missingness() -> None:
    boundary_ring = [
        (200_000, 350_000),
        (201_000, 350_000),
        (201_000, 350_500),
        (200_000, 350_500),
        (200_000, 350_000),
    ]
    first_building = [
        (200_100, 350_100),
        (200_110, 350_100),
        (200_110, 350_110),
        (200_100, 350_110),
        (200_100, 350_100),
    ]
    second_building = [
        (200_600, 350_100),
        (200_620, 350_100),
        (200_620, 350_110),
        (200_600, 350_110),
        (200_600, 350_100),
    ]
    residential = [
        (200_050, 350_050),
        (200_950, 350_050),
        (200_950, 350_250),
        (200_050, 350_250),
        (200_050, 350_050),
    ]
    osm = {
        "elements": [
            {
                "type": "way",
                "id": 1,
                "geometry": _ring_wgs84(first_building),
                "tags": {
                    "building": "apartments",
                    "building:levels": "3",
                    "name": "101동",
                    "addr:subdistrict": "효자동",
                },
            },
            {
                "type": "way",
                "id": 2,
                "geometry": _ring_wgs84(second_building),
                "tags": {"building": "apartments", "name": "102동"},
            },
            {
                "type": "way",
                "id": 3,
                "geometry": _ring_wgs84(residential),
                "tags": {
                    "landuse": "residential",
                    "residential": "apartments",
                    "name": "참여우리아파트",
                    "addr:street": "전주천동로",
                    "addr:housenumber": "42",
                },
            },
        ]
    }
    boundary = {
        "type": "FeatureCollection",
        "licence": "Data © OpenStreetMap contributors, ODbL 1.0",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": "전주시 시험 경계"},
                "geometry": _polygon_geojson(boundary_ring),
            }
        ],
    }

    result = build_spatial(osm, boundary)

    assert result["boundary"]["licence"] == boundary["licence"]
    grids = result["grids"]["features"]
    assert [feature["properties"]["id"] for feature in grids] == [
        "cell_200000_350000",
        "cell_200500_350000",
    ]
    for feature in grids:
        metric_geometry = transform(TO_METRIC.transform, shape(feature["geometry"]))
        assert feature["properties"]["area_m2"] == 250_000
        assert feature["properties"]["x"] % 500 == 0
        assert feature["properties"]["y"] % 500 == 0
        assert metric_geometry.is_valid
        min_x, min_y, max_x, max_y = metric_geometry.bounds
        assert round(max_x - min_x, 5) == 500.0
        assert round(max_y - min_y, 5) == 500.0
        assert round(metric_geometry.area, 2) == 250_000.0

    buildings = result["buildings"]["features"]
    assert len(buildings) == 2
    first, second = buildings
    assert first["properties"]["id"] == "way/1"
    assert first["properties"]["levels"] == 3
    assert first["properties"]["footprint_m2"] == 100.0
    assert first["properties"]["floor_area_m2"] == 300.0
    assert first["properties"]["source_type"] == "FALLBACK"
    assert first["properties"]["grid_id"] == "cell_200000_350000"
    assert second["properties"]["levels"] is None
    assert second["properties"]["floor_area_m2"] is None
    assert second["properties"]["grid_id"] == "cell_200500_350000"

    assert result["residential_landuse"]["features"][0]["properties"] == {
        "id": "way/3",
        "name": "참여우리아파트",
        "area_m2": 180_000.0,
        "residential": "apartments",
        "source_type": "FALLBACK",
        "tags": {
            "landuse": "residential",
            "residential": "apartments",
            "name": "참여우리아파트",
            "addr:street": "전주천동로",
            "addr:housenumber": "42",
        },
    }

    assert result["candidates"][0] == {
        "grid_id": "cell_200000_350000",
        "name": "참여우리아파트",
        "reason": (
            "OSM 아파트 건물 1개, 알려진 층수 기반 추정 연면적 300m², "
            "OSM 도로명주소 전주천동로 42"
        ),
        "building_count": 1,
        "floor_area_m2": 300.0,
    }


def test_build_spatial_labels_inferred_bbox_and_ignores_unusable_relations() -> None:
    building = [
        (200_100, 350_100),
        (200_110, 350_100),
        (200_110, 350_110),
        (200_100, 350_110),
        (200_100, 350_100),
    ]
    osm = {
        "elements": [
            {
                "type": "way",
                "id": 9,
                "geometry": _ring_wgs84(building),
                "tags": {"building": "apartments", "building:levels": "2"},
            },
            {
                "type": "relation",
                "id": 10,
                "tags": {"building": "apartments", "type": "multipolygon"},
            },
        ]
    }

    result = build_spatial(osm)

    assert len(result["buildings"]["features"]) == 1
    boundary_properties = result["boundary"]["features"][0]["properties"]
    assert boundary_properties["boundary_type"] == "study_extent_bbox"
    assert boundary_properties["source_type"] == "FALLBACK"
    assert "OSM input geometry bounds" in boundary_properties["limitation"]
