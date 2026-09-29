"""전국 지도: 500m 합계의 블록 덮음 규칙, 묶음 합계, 시·도 → 시·군·구 응답 (DB 없이)."""
from app import national_map
from app.national_map import FIELDS, change_pct, grid_values, merge_grid, summarize, unit_grid500

RECEIVED = {("인구", 2024): {"다마", "다사"}, ("인구", 2015): {"다마", "다사"}, ("주택", 2024): {"다마", "다사"}, ("종사자", 2024): {"다사"}}
SUMS = {("다마", 2024): {"pop": 900.0, "housing": 400.0, "workers": None}, ("다사", 2024): {"pop": 100.0, "housing": 50.0, "workers": 30.0},
        ("다마", 2015): {"pop": 700.0}, ("다사", 2015): {"pop": 100.0}, ("나마", 2024): {"pop": 5.0}}


def test_totals_need_the_blocks_with_files_to_hold_99_percent_of_people():
    whole = grid_values(unit_grid500(SUMS, {"다마": 900.0, "다사": 100.0}, RECEIVED, 2024, 2015))
    assert whole[0] == {"pop500": 1000, "pop500_base": 800, "housing500": 450, "workers500": None, "pop_change_pct": 25.0}
    assert whole[1]["workers500"].startswith("다마 블록 2024년 종사자 파일 없음 (인구의 약 90%")
    # 섬 하나(나마)가 파일 없이 빠진 곳: 빠진 몫이 1% 미만이면 합을 보이고 그 몫을 적는다
    island = grid_values(unit_grid500(SUMS, {"다마": 990.0, "나마": 5.0}, RECEIVED, 2024, 2015))
    assert island[0]["pop500"] == 900 and island[1]["pop500"] == "빠진 블록(나마) 인구 약 0.5% 제외"
    assert island[0]["pop_change_pct"] == 28.6 and "인구 약 99.5% 기준" in island[1]["pop_change_pct"]
    # 제주처럼 파일이 하나도 없는 곳: 전부 비움 (0 아님)
    jeju = grid_values(unit_grid500({}, {"나나": 600.0, "다나": 70.0}, RECEIVED, 2024, 2015))
    assert all(jeju[0][k] is None for k in ("pop500", "pop500_base", "housing500", "workers500", "pop_change_pct"))
    assert jeju[1]["pop500"].startswith("나나·다나 블록 2024년 인구 파일 없음 (인구의 약 100%")


def test_groups_add_partial_sums_and_coverage():
    a = {"population": 100, "households": 40, "area_km2": 2.0, "grid": unit_grid500(SUMS, {"다마": 900.0}, RECEIVED, 2024, 2015)}
    b = {"population": 300, "households": 120, "area_km2": 2.0, "grid": unit_grid500(SUMS, {"다사": 100.0}, RECEIVED, 2024, 2015)}
    metrics, notes = summarize([a, b], 3)
    assert list(metrics) == FIELDS
    assert metrics["population"] == 400 and metrics["density"] == 100.0 and metrics["complexes"] == 3
    assert metrics["pop500"] == 1000 and metrics["workers500"] is None and "workers500" in notes
    merged = merge_grid([a["grid"], b["grid"]])
    assert merged["workers500"]["covered"] == 100.0 and merged["workers500"]["total"] == 1000.0
    assert change_pct(10, 50) is None and change_pct(100, 90) == -10.0
    assert summarize([], None)[0]["population"] is None


STATIC = {
    "unit_year": 2024, "year": 2024, "base": 2015, "complex_month": "202609", "missing_blocks": [{"block": "나나", "people": 670000, "provinces": ["제주특별자치도"]}],
    "provinces": [{"code": "52", "name": "전북특별자치도", "kind": "PROVINCE", "excluded": None, "sgis_codes": ["35"], "cells": 10, "regions": 2,
                   "metrics": summarize([{"population": 400, "households": 1, "area_km2": 1}], 0)[0], "notes": {}},
                  {"code": "50", "name": "제주특별자치도", "kind": "PROVINCE", "excluded": "제외", "sgis_codes": ["39"], "cells": 5, "regions": 2,
                   "metrics": summarize([], 0)[0], "notes": {}}],
    "regions": [{"code": "52110", "name": "전북특별자치도 전주시", "short_name": "전주시", "sido": "52", "sgis_codes": ["35011"], "linked": True,
                 "metrics": summarize([{"population": 300, "households": 1, "area_km2": 1}], 364)[0], "notes": {}},
                {"code": "52710", "name": "전북특별자치도 완주군", "short_name": "완주군", "sido": "52", "sgis_codes": ["35360"], "linked": True,
                 "metrics": summarize([{"population": 100, "households": 1, "area_km2": 1}], 10)[0], "notes": {}},
                {"code": "sgis:35999", "name": "전북 어딘가", "short_name": "어딘가", "sido": "52", "sgis_codes": ["35999"], "linked": False,
                 "metrics": summarize([], None)[0], "notes": {}}],
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
    assert body["meta"]["missing_blocks"][0]["block"] == "나나"
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
