"""읍면동 단위: 격자·행정동 겹침 비율과 응답 (PostGIS 없이 순수 파이썬 경로로)."""
import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import dongs


def square(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]


def test_box_area_of_polygons_with_holes_and_parts():
    box = (0.0, 0.0, 500.0, 500.0)
    assert dongs.polygon_box_area([[square(-100, -100, 600, 600)]], box) == 250_000
    assert dongs.polygon_box_area([[square(250, -100, 600, 600)]], box) == 125_000
    # A hole inside the cell is not part of the 행정동.
    assert dongs.polygon_box_area([[square(-100, -100, 600, 600), square(0, 0, 100, 100)]], box) == 240_000
    # Two parts (islands) of one 행정동.
    assert dongs.polygon_box_area([[square(0, 0, 100, 100)], [square(400, 400, 600, 600)]], box) == 20_000
    # A concave (L-shaped) outline.
    l_shape = [(0, 0), (500, 0), (500, 100), (100, 100), (100, 500), (0, 500), (0, 0)]
    assert dongs.polygon_box_area([[l_shape]], box) == 90_000
    assert dongs.polygon_box_area([[square(600, 600, 900, 900)]], box) == 0


def test_cell_shares_split_a_cell_between_two_dongs():
    west = [[square(0, 0, 250, 1000)]]
    east = [[square(250, 0, 1000, 1000)]]
    shares = dongs.cell_shares_py({"cell_0_0": (0, 0), "cell_500_0": (500, 0), "cell_2000_0": (2000, 0)}, [west, east])
    assert shares == {"cell_0_0": [[0, 0.5], [1, 0.5]], "cell_500_0": [[1, 1.0]]}


def test_payload_counts_cells_and_keeps_official_population():
    sc = SimpleNamespace(code="41110")
    rows = [
        {"adm_code": "3101151", "adm_name": "파장동", "parent_code": "31011", "population": 20000, "population_status": "OK",
         "households": 9000, "household_status": "OK", "area_m2": 4_000_000, "outline": json.dumps({"type": "Polygon", "coordinates": [[[127, 37], [127.1, 37], [127.1, 37.1], [127, 37]]]})},
        {"adm_code": "3101152", "adm_name": "경기도 수원시 장안구 정자1동", "parent_code": "31011", "population": None, "population_status": "SUPPRESSED",
         "households": None, "household_status": "SUPPRESSED", "area_m2": 1_000_000, "outline": None},
    ]
    body = dongs.build_payload(sc, 2024, rows, {"a": [[0, 1.0]], "b": [[0, 0.5], [1, 0.5]]})
    first, second = body["dongs"]
    assert first["cells"] == 2 and first["cell_area_km2"] == 0.375 and first["density"] == 5000.0
    # A suppressed statistic stays missing (never 0).
    assert second["population"] is None and second["density"] is None and second["cells"] == 1
    assert second["name"] == "정자1동"
    assert len(body["boundaries"]["features"]) == 1 and body["boundaries"]["features"][0]["properties"]["name"] == "파장동"


def test_route_falls_back_to_python_overlap(monkeypatch):
    sc = SimpleNamespace(code="41110", grid_ids=frozenset({"cell_0_0", "cell_500_0"}), sgis_codes=("31011",))
    metric = {"type": "Polygon", "coordinates": [square(0, 0, 750, 500)]}
    row = {"adm_code": "3101151", "adm_name": "파장동", "parent_code": "31011", "population": 100, "population_status": "OK",
           "households": 40, "household_status": "OK", "area_m2": 375_000, "outline": None, "metric": json.dumps(metric)}

    class Ctx:
        def __enter__(self):
            return SimpleNamespace(rollback=lambda: None)

        def __exit__(self, *_):
            return False

    def no_postgis(*_args, **_kwargs):
        raise RuntimeError("no PostGIS")

    import app.regions as regions
    monkeypatch.setattr(dongs, "Session", Ctx)
    monkeypatch.setattr(regions, "scope", lambda db, code: sc)
    monkeypatch.setattr(dongs, "load_dongs", lambda db, codes: (2024, [row]))
    monkeypatch.setattr(dongs, "cell_shares_sql", no_postgis)
    dongs._CACHE.clear()
    app = FastAPI()
    app.include_router(dongs.router)
    body = TestClient(app).get("/api/map/dongs?region=41110").json()
    assert body["weights"] == {"cell_0_0": [[0, 1.0]], "cell_500_0": [[0, 0.5]]}
    assert body["dongs"][0]["cells"] == 2 and body["dongs"][0]["cell_area_km2"] == 0.375
    dongs._CACHE.clear()
