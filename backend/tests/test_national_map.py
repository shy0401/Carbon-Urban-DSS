"""전국 지도: 500m 합계 규칙(빠진 블록이면 비움), 묶음 합계, 시·도 → 시·군·구 응답 (DB 없이)."""
from app import national_map
from app.national_map import FIELDS, change_pct, combine, finish, gap_notes, unit_grid500

RECEIVED = {("인구", 2024): {"다마", "다사"}, ("인구", 2015): {"다마", "다사"}, ("주택", 2024): {"다마", "다사"}, ("종사자", 2024): {"다사"}}
SUMS = {("다마", 2024): {"pop": 900.0, "housing": 400.0, "workers": None}, ("다사", 2024): {"pop": 100.0, "housing": 50.0, "workers": 30.0},
        ("다마", 2015): {"pop": 700.0}, ("다사", 2015): {"pop": 100.0}}


def test_unit_totals_are_empty_when_a_touched_block_has_no_file():
    both = unit_grid500(SUMS, {"다마", "다사"}, RECEIVED, 2024, 2015)
    assert both == {"pop500": 1000.0, "pop500_base": 800.0, "housing500": 450.0, "workers500": None}  # 종사자: 다마 파일 없음
    east = unit_grid500(SUMS, {"다사"}, RECEIVED, 2024, 2015)
    assert east["workers500"] == 30.0
    # 제주처럼 어느 파일에도 없는 블록만 걸친 곳: 전부 비움 (0 아님)
    assert unit_grid500({}, {"나나"}, RECEIVED, 2024, 2015) == {"pop500": None, "pop500_base": None, "housing500": None, "workers500": None}
    # 행이 없는 곳(통계 없음)도 0이 아니라 비움
    assert unit_grid500({}, {"다사"}, RECEIVED, 2024, 2015)["pop500"] is None


def test_groups_never_show_partial_sums_and_change_needs_enough_people():
    a = {"population": 100, "households": 40, "area_km2": 2.0, "pop500": 90.0, "pop500_base": 60.0, "housing500": 30.0, "workers500": None, "complexes": 1}
    b = {"population": 300, "households": 120, "area_km2": 2.0, "pop500": 310.0, "pop500_base": 340.0, "housing500": 90.0, "workers500": 12.0, "complexes": 0}
    m = combine([a, b])
    assert m["population"] == 400 and m["density"] == 100.0 and m["workers500"] is None
    assert m["pop_change_pct"] == 0.0  # (400 - 400) / 400
    assert list(m) == FIELDS
    assert change_pct(10, 50) is None and change_pct(100, 90) == -10.0
    assert finish({})["density"] is None and combine([])["population"] is None


def test_gap_notes_name_the_missing_blocks():
    notes = gap_notes({"35011": {"다마"}, "35012": {"다마", "다사"}}, ["35011", "35012"], RECEIVED, 2024)
    assert notes == {"workers500": "다마 블록 2024년 종사자 파일 없음"}
    assert gap_notes({}, [], RECEIVED, 2024) == {}


STATIC = {
    "unit_year": 2024, "year": 2024, "base": 2015, "complex_month": "202609",
    "provinces": [{"code": "52", "name": "전북특별자치도", "kind": "PROVINCE", "excluded": None, "sgis_codes": ["35"], "cells": 10, "regions": 2,
                   "metrics": finish({"population": 400}), "notes": {}},
                  {"code": "50", "name": "제주특별자치도", "kind": "PROVINCE", "excluded": "제외", "sgis_codes": ["39"], "cells": 5, "regions": 2,
                   "metrics": finish({"population": 600}), "notes": {}}],
    "regions": [{"code": "52110", "name": "전북특별자치도 전주시", "short_name": "전주시", "sido": "52", "sgis_codes": ["35011"], "linked": True,
                 "metrics": finish({"population": 300}), "notes": {}},
                {"code": "52710", "name": "전북특별자치도 완주군", "short_name": "완주군", "sido": "52", "sgis_codes": ["35360"], "linked": True,
                 "metrics": finish({"population": 100}), "notes": {}},
                {"code": "sgis:35999", "name": "전북 어딘가", "short_name": "어딘가", "sido": "52", "sgis_codes": ["35999"], "linked": False,
                 "metrics": finish({}), "notes": {}}],
    "geometry": {"52110": {"type": "Point", "coordinates": [127.1, 35.8]}, "sgis:35999": {"type": "Point", "coordinates": [127.0, 35.7]}},
    "labels": {"52110": [127.1, 35.8]},
    "province_geometry": {"52": {"geometry": {"type": "Point", "coordinates": [127.1, 35.7]}, "label": [127.1, 35.7]}},
}
DYNAMIC = {"levels": {"52110": {"level": "DETAILED", "status": "READY", "grids": 916}, "52710": {"level": "BASIC", "status": "PARTIAL", "grids": 3605}},
           "kapt": {"52110": 364}, "building": {"52110": 18601}}


def patched(monkeypatch):
    monkeypatch.setattr(national_map, "static", lambda db: STATIC)
    monkeypatch.setattr(national_map, "dynamic", lambda db: DYNAMIC)
    monkeypatch.setattr("app.sgis_grid500.missing_files", lambda root: [])


def test_national_payload_counts_levels_per_province_and_keeps_the_cache_unchanged(monkeypatch):
    patched(monkeypatch)
    body = national_map.national_payload(None)
    p = {x["code"]: x for x in body["provinces"]}
    assert p["52"]["detailed"] == 1 and p["52"]["basic"] == 1 and p["52"]["energy_regions"] == 1 and p["52"]["label"] == [127.1, 35.7]
    assert p["50"]["excluded"] == "제외" and p["50"]["label"] is None
    assert [f["properties"]["code"] for f in body["boundaries"]["features"]] == ["52"]
    rows = {r["code"]: r for r in body["regions"]}
    assert rows["52110"]["energy"] == {"kapt_complexes": 364, "building_parcels": 18601} and rows["52710"]["level"] == "BASIC"
    assert rows["sgis:35999"]["level"] == "UNLINKED" and "sgis_codes" not in rows["52110"]
    assert "detailed" not in STATIC["provinces"][0]  # static cache is not mutated


def test_province_regions_lists_boundaries_with_metrics(monkeypatch):
    patched(monkeypatch)
    body = national_map.province_regions(None, "52")
    props = [f["properties"] for f in body["boundaries"]["features"]]
    assert [(x["code"], x["level"], x["linked"]) for x in props] == [("52110", "DETAILED", True), ("sgis:35999", "UNLINKED", False)]  # 완주: 경계 없음
    assert props[0]["population"] == 300 and props[0]["label"] == [127.1, 35.8]
    try:
        national_map.province_regions(None, "99")
    except Exception as exc:  # noqa: BLE001
        assert getattr(exc, "status_code", None) == 404
    else:
        raise AssertionError("unknown 시·도 must be 404")
