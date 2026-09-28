"""시·도 500m 격자 지도 API: 목록 묶기, 비율 규칙, 경로 검증과 캐시 (DB 없이 가짜 세션으로)."""
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import province_map, regions


class FakeDb:
    """Answers province_list's reads in order: max year, SIDO units, 500m counts, prepared study regions."""

    def __init__(self, units, counts, prepared):
        self.units, self.counts, self.prepared = units, counts, prepared
        self.scalars_calls = 0

    def scalar(self, _stmt):
        return 2024

    def scalars(self, _stmt):
        self.scalars_calls += 1
        return iter(self.units if self.scalars_calls == 1 else self.prepared)

    def execute(self, _stmt, *_args):
        return iter(self.counts.items())

    def rollback(self):
        pass


CATALOG = [
    {"code": "41110", "sido_name": "경기도", "name": "경기도 수원시"}, {"code": "41820", "sido_name": "경기도", "name": "경기도 가평군"},
    {"code": "52110", "sido_name": "전북특별자치도", "name": "전북특별자치도 전주시"},
    {"code": "11110", "sido_name": "서울특별시", "name": "서울특별시 종로구"},
    {"code": "12110", "sido_name": "전남광주통합특별시", "name": "전남광주통합특별시 동구"},
    {"code": "50110", "sido_name": "제주특별자치도", "name": "제주특별자치도 제주시"},
]
UNITS = [SimpleNamespace(adm_code=c, adm_name=n) for c, n in [
    ("11", "서울특별시"), ("24", "광주광역시"), ("31", "경기도"), ("35", "전북특별자치도"), ("36", "전라남도"), ("39", "제주특별자치도")]]
COUNTS = {"11": 2500, "24": 2100, "31": 42119, "35": 33306, "36": 51000, "39": 8000}
PREPARED = [SimpleNamespace(code="41110", name="경기도 수원시", status="PARTIAL", grid_count=559, datasets={"buildings": {"status": "DONE"}}),
            # Opened from the map with the national layers only: listed as a unit, not outlined as a detailed region.
            SimpleNamespace(code="41820", name="경기도 가평군", status="PARTIAL", grid_count=3500, datasets={"grid": {"status": "DONE"}}),
            SimpleNamespace(code="52110", name="전북특별자치도 전주시", status="READY", grid_count=916, datasets={})]


def listing(monkeypatch):
    monkeypatch.setattr(regions, "catalog", lambda db: CATALOG)
    province_map._COUNTS.clear()  # the 10-minute cell-count cache is module state
    try:
        return province_map.province_list(FakeDb(UNITS, COUNTS, PREPARED))
    finally:
        province_map._COUNTS.clear()


def test_provinces_are_grouped_with_sgis_codes_and_prepared_regions(monkeypatch):
    items = {p["code"]: p for p in listing(monkeypatch)}
    assert items["41"]["sgis_codes"] == ["31"] and items["41"]["cells"] == 42119 and items["41"]["regions"] == 2
    assert [r["short_name"] for r in items["41"]["prepared"]] == ["수원시"]
    assert {u["short_name"]: u["level"] for u in items["41"]["units"]} == {"수원시": "DETAILED", "가평군": "BASIC"}
    assert items["11"]["units"] == [{"code": "11110", "name": "서울특별시 종로구", "short_name": "종로구", "level": "NONE"}]
    assert items["52"]["sgis_codes"] == ["35"] and items["52"]["prepared"][0]["grid_count"] == 916
    # 통합특별시 covers the two old SGIS 시도 (광주 24 + 전남 36) and counts as a 도-level menu item.
    assert items["12"]["sgis_codes"] == ["24", "36"] and items["12"]["cells"] == 53100 and items["12"]["kind"] == "PROVINCE"
    assert items["11"]["kind"] == "METRO"
    assert items["50"]["excluded"]


def test_provinces_list_도_before_metropolitan(monkeypatch):
    kinds = [p["kind"] for p in listing(monkeypatch)]
    assert kinds == sorted(kinds, key=lambda k: k != "PROVINCE")


def test_share_needs_a_base_of_twenty():
    assert province_map._share(5, 19) is None
    assert province_map._share(None, 100) is None
    assert province_map._share(25, 100) == 25.0


def test_first_view_leaves_out_small_far_islands_only():
    mainland = list(range(2200, 2320)) * 50  # 6,000 cells over 60 km
    ulleung = [2560] * 120  # 2% of the cells, 120 km of sea away
    assert province_map._core_range(mainland + ulleung) == (2200, 2319)
    assert province_map._core_range(ulleung + mainland, gap=20) == (2200, 2319)
    # A big detached part (more than 4% of the cells) stays in view.
    assert province_map._core_range(mainland + [2560] * 600) == (2200, 2560)
    # Near islands (gap under 10 km) stay too.
    assert province_map._core_range(mainland + [2335] * 50) == (2200, 2335)


def test_cache_key_ignores_preparation_status(monkeypatch):
    class Db:
        def scalar(self, _stmt):
            return 7

        def rollback(self):
            pass

    base = {"code": "52", "sgis_codes": ["35"], "cells": 33306, "prepared": [{"code": "52110", "status": "READY", "grid_count": 916}]}
    other = dict(base, prepared=[{"code": "52110", "status": "PREPARING", "grid_count": 916}])
    grown = dict(base, prepared=[{"code": "52110", "status": "READY", "grid_count": 917}])
    key = province_map._cache_key(Db(), base)
    assert province_map._cache_key(Db(), other) == key
    assert province_map._cache_key(Db(), grown) != key


def client(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    items = [
        {"code": "52", "name": "전북특별자치도", "kind": "PROVINCE", "sgis_codes": ["35"], "cells": 2, "regions": 1,
         "prepared": [{"code": "52110", "name": "전주시", "short_name": "전주시", "status": "READY", "grid_count": 916}], "excluded": None},
        {"code": "43", "name": "충청북도", "kind": "PROVINCE", "sgis_codes": [], "cells": 0, "regions": 1, "prepared": [], "excluded": None},
        {"code": "50", "name": "제주특별자치도", "kind": "PROVINCE", "sgis_codes": ["39"], "cells": 8000, "regions": 1, "prepared": [],
         "excluded": province_map.EXCLUDED["50"]},
    ]
    builds = []

    class Ctx:
        def __enter__(self):
            return object()

        def __exit__(self, *_):
            return False

    monkeypatch.setattr(province_map, "Session", Ctx)
    monkeypatch.setattr(province_map, "province_list", lambda db: items)
    monkeypatch.setattr(province_map, "_cache_key", lambda db, p: "k1")
    monkeypatch.setattr(province_map, "build_province", lambda db, p: builds.append(p["code"]) or {"code": p["code"], "fields": province_map.FIELDS, "cells": []})
    province_map._MEMORY.clear()
    app = FastAPI()
    app.include_router(province_map.router)
    return TestClient(app), builds


def test_province_list_route_leaves_out_jeju(monkeypatch, tmp_path):
    http, _ = client(monkeypatch, tmp_path)
    body = http.get("/api/map/provinces").json()
    assert [p["code"] for p in body["provinces"]] == ["52", "43"]
    assert body["excluded"][0]["code"] == "50"


def test_province_route_validates_and_explains_missing_data(monkeypatch, tmp_path):
    http, _ = client(monkeypatch, tmp_path)
    assert http.get("/api/map/province/ab").status_code == 422
    assert http.get("/api/map/province/123").status_code == 422
    assert http.get("/api/map/province/99").status_code == 404
    jeju = http.get("/api/map/province/50")
    assert jeju.status_code == 404 and "제외" in jeju.json()["detail"]
    empty = http.get("/api/map/province/43")
    assert empty.status_code == 404 and "500m 격자" in empty.json()["detail"]


def test_province_grid_is_built_once_then_cached(monkeypatch, tmp_path):
    http, builds = client(monkeypatch, tmp_path)
    first = http.get("/api/map/province/52")
    assert first.status_code == 200 and first.json()["code"] == "52"
    assert http.get("/api/map/province/52").json() == first.json()
    assert builds == ["52"]
    assert (tmp_path / "cache" / "province-map" / "52-k1.json").exists()
    # A fresh process (empty memory) reads the disk copy instead of rebuilding.
    province_map._MEMORY.clear()
    assert http.get("/api/map/province/52").status_code == 200
    assert builds == ["52"]
    province_map._MEMORY.clear()
