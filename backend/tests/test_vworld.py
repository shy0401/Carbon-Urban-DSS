import json
from pathlib import Path

from shapely.geometry import Polygon

from app.vworld import bbox_filter, load_layer_config, parse_vworld_response, zoning_intersections


def test_config_uses_current_official_reference_layer_ids():
    config = load_layer_config()
    assert config['zoning']['dataset_id'] == 'LT_C_UQ111'
    assert config['cadastral']['dataset_id'] == 'LP_PA_CBND_BUBUN'
    assert config['zoning']['source_crs'] == 'EPSG:5179'


def test_parser_repairs_invalid_geometry_and_keeps_provider_pagination():
    bowtie = [[0, 0], [10, 10], [0, 10], [10, 0], [0, 0]]
    body = json.dumps({'response': {
        'status': 'OK', 'record': {'total': '3', 'current': '1'},
        'page': {'total': '3', 'current': '1', 'size': '1'},
        'result': {'featureCollection': {'type': 'FeatureCollection', 'features': [{
            'type': 'Feature', 'id': 'zone.1', 'properties': {'uname': '제1종일반주거지역'},
            'geometry': {'type': 'Polygon', 'coordinates': [bowtie]},
        }]}}
    }}).encode()
    parsed = parse_vworld_response(body)
    assert parsed['total_records'] == 3
    assert parsed['total_pages'] == 3
    assert parsed['features'][0]['geometry'].is_valid
    assert parsed['features'][0]['geometry_repaired'] is True
    assert parsed['features'][0]['properties']['uname'] == '제1종일반주거지역'


def test_bbox_and_intersections_preserve_multiple_zones_per_grid():
    grid = Polygon([(0, 0), (500, 0), (500, 500), (0, 500), (0, 0)])
    assert bbox_filter(grid.bounds) == 'BOX(0 0,500 500)'
    zones = [
        {'id': 'a', 'zone_code': 'A', 'zone_name': '주거', 'geometry': Polygon([(0, 0), (250, 0), (250, 500), (0, 500)])},
        {'id': 'b', 'zone_code': 'B', 'zone_name': '상업', 'geometry': Polygon([(250, 0), (500, 0), (500, 500), (250, 500)])},
    ]
    rows = zoning_intersections([{'id': 'g1', 'geometry': grid}], zones)
    assert [(row['zone_code'], row['intersection_area_m2'], row['grid_area_ratio']) for row in rows] == [
        ('A', 125000.0, 0.5), ('B', 125000.0, 0.5),
    ]
