"""선도소프트 탄소공간지도 100m 건물 전기 배출: 가져오기·칸 합치기·급감 표시·지역 시뮬레이션 기준 (합성 자료만 씀)."""
import pytest

from app.area import area_facts, build_history, effort, resolve_area
from app.kcsm100 import (
    aggregate, area_block, drop_flag, grid100_origin, import_kcsm100, read_csv_text, region_of,
)

HEADER = "grid_cd,emd_cd," + ",".join(f"e{m}" for m in range(1, 13)) + ",e_sum"


def line(code, emd, monthly):
    return f"{code},{emd}," + ",".join(str(v) for v in monthly) + f",{round(sum(monthly), 6)}"


def test_grid_code_is_the_epsg5179_lower_left_corner_and_region_follows_the_city():
    assert grid100_origin("다마555632") == (955500, 1763200)   # checked against the delivered SHP polygon
    assert grid100_origin("다마71b61b") is None and grid100_origin("") is None
    assert region_of("52113137") == "52110" and region_of("52111101") == "52110" and region_of("11740101") == "11740"


def test_rows_of_one_cell_split_by_legal_dong_are_added_and_both_column_names_are_read():
    text = "\n".join([HEADER, line("다마555632", "52113137", [1.0] * 12), line("다마555632", "52113110", [0.5] * 12),
                      line("다마556632", "52113137", [0.0] * 12)])
    rows = read_csv_text(text.encode("cp949"))
    cells, stats = aggregate(rows, 2024, "a.csv")
    assert stats == {"rows": 3, "bad_code": 0, "sum_mismatch": 0}
    cell = cells["다마555632"]
    assert cell["annual_t"] == pytest.approx(18.0) and cell["monthly"][0] == pytest.approx(1.5)
    assert cell["grid500"] == "cell_955500_1763000" and [p["emd"] for p in cell["parts"]] == ["52113137", "52113110"]
    assert cells["다마556632"]["annual_t"] == 0.0   # a provider 0 stays 0 (never None, never removed)
    # the 데이터정의서 names (e_01…e_12, e_tot) are read the same way; a total that disagrees with its months is counted, not fixed
    alt = "grid_cd," + ",".join(f"e_{m:02d}" for m in range(1, 13)) + ",e_tot\n다마555632," + ",".join(["2"] * 12) + ",30"
    cells2, stats2 = aggregate(read_csv_text(alt.encode("utf-8-sig")), 2023, "b.csv")
    assert cells2["다마555632"]["annual_t"] == 30.0 and stats2["sum_mismatch"] == 1


def test_drop_flag_follows_the_team_rule():
    assert drop_flag(200.0, 0.0, 2023) == {"from_year": 2023, "from_t": 200.0}
    assert drop_flag(200.0, 99.9, 2023) is not None
    assert drop_flag(200.0, 100.0, 2023) is None       # exactly half is not a drop
    assert drop_flag(99.0, 0.0, 2023) is None          # small cells are not judged
    assert drop_flag(None, 0.0, 2023) is None


def _db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    return sessionmaker(create_engine("sqlite+pysqlite:///:memory:"))()


def test_import_merges_both_gu_files_flags_drops_and_skips_unchanged_files(tmp_path):
    from app.kcsm100 import KcsmGrid100
    root = tmp_path / "sundosoft_kcsm100" / "2026-10-17"
    root.mkdir(parents=True)
    name = "탄소배출_건물_전기_격자_100m_전북특별자치도_전주시_{gu}_{year}.csv"
    files = {
        ("덕진구", 2023): [line("다마555632", "52113137", [20.0] * 12), line("다마600600", "52113109", [30.0] * 12)],
        ("완산구", 2023): [line("다마555632", "52111101", [1.0] * 12)],
        ("덕진구", 2024): [line("다마555632", "52113137", [21.0] * 12), line("다마600600", "52113109", [0.0] * 12)],
        ("완산구", 2024): [line("다마555632", "52111101", [1.0] * 12)],
    }
    for (gu, year), lines in files.items():
        (root / name.format(gu=gu, year=year)).write_bytes("\n".join([HEADER, *lines]).encode("cp949"))
    db = _db()
    stats = import_kcsm100(db, tmp_path / "sundosoft_kcsm100", log=lambda _: None)
    assert stats["years"] == [2023, 2024] and stats["cells"] == 4 and stats["flagged"] == 1
    both = db.get(KcsmGrid100, "다마555632|2024")
    assert both.annual_t == pytest.approx(264.0) and len(both.parts) == 2 and both.region_code == "52110"
    factory = db.get(KcsmGrid100, "다마600600|2024")
    assert factory.annual_t == 0.0 and factory.flags == {"drop": {"from_year": 2023, "from_t": 360.0}}
    assert db.get(KcsmGrid100, "다마600600|2023").flags == {}
    again = import_kcsm100(db, tmp_path / "sundosoft_kcsm100", log=lambda _: None)
    assert again["skipped_years"] == [2023, 2024] and again["cells"] == 0


def square(x, y, d):
    return {"type": "Polygon", "coordinates": [[[x, y], [x + d, y], [x + d, y + d], [x, y + d], [x, y]]]}


def kcsm_inputs():
    # cells: (grid100, grid500, lon, lat, annual_t, monthly, drop)
    def c(code, g500, lon, lat, t, drop=None):
        return (code, g500, lon, lat, t, [t / 12] * 12 if t is not None else [None] * 12, drop)
    year23 = [c("a", "g1", 127.101, 35.801, 100.0), c("b", "g1", 127.103, 35.803, 50.0), c("c", "g2", 127.106, 35.801, 400.0),
              c("d", "g2", 127.115, 35.801, 30.0)]
    year24 = [c("a", "g1", 127.101, 35.801, 110.0), c("b", "g1", 127.103, 35.803, 0.0), c("c", "g2", 127.106, 35.801, 10.0, {"from_year": 2023, "from_t": 400.0}),
              c("d", "g2", 127.115, 35.801, 40.0)]
    return {"years": [2023, 2024], "cells": {2023: year23, 2024: year24}, "source": "test"}


def test_area_block_counts_cells_inside_the_outline_and_inside_the_grids_and_compares_without_adding():
    area = {"type": "admin", "geometry": square(127.099, 35.799, 0.012), "grid_ids": ["g1", "g2"]}
    be = {2024: {"electricity_kwh": 200000.0, "electricity_complete": 7, "complete": True}}
    register = [{"grid_id": "g1", "gfa": 1000.0, "approval_year": 2010}, {"grid_id": "g2", "gfa": 2000.0, "approval_year": None},
                {"grid_id": "g2", "gfa": 5000.0, "approval_year": 2025}]   # built after the data year: not in the 2024 stock
    block = area_block(area, kcsm_inputs(), be, register, lambda y: 0.5)
    y24 = block["years"][2024]
    assert y24["boundary_t"] == pytest.approx(120.0) and y24["cells"] == 3       # 'd' lies outside the 행정동 outline
    assert y24["grid_t"] == pytest.approx(160.0) and y24["grid_cells"] == 4      # but inside its 500m grid
    assert y24["zero_cells"] == 1 and y24["value_cells"] == 2 and y24["drop_cells"] == 1 and y24["drop_from_t"] == 400.0
    assert y24["tool"] == {"kwh": 200000.0, "factor": 0.5, "t": 100.0, "parcels": 7, "complete": True, "share_pct": 62.5}
    assert y24["register_gfa_m2"] == 3000.0 and y24["register_buildings"] == 2
    assert y24["change_pct"] == pytest.approx(-78.2) and y24["change_from"] == 2023
    assert block["years"][2023].get("tool") is None   # no 건축HUB value that year: nothing to compare (not 0)
    assert area_block(area, None) is None


GRIDS = [{"id": "g1", "geometry": square(127.100, 35.800, 0.005)}, {"id": "g2", "geometry": square(127.105, 35.800, 0.005)}]
ADMIN = [{"type": "Feature", "geometry": square(127.099, 35.799, 0.012), "properties": {"adm_code": "35012650", "adm_name": "전북특별자치도 전주시 덕진구 송천1동"}}]


def history_with_kcsm(kcsm=True):
    area = resolve_area({"type": "admin", "code": "35012650"}, GRIDS, [], ADMIN, {})
    inputs = {"complexes": {}, "energy": [], "weather": [], "population": [], "households": [], "factor": {"electricity": 0.5},
              "city_intensity": None, "register": [{"grid_id": "g1", "gfa": 1000.0, "approval_year": 2010}, {"grid_id": "g2", "gfa": 1000.0, "approval_year": 2012}],
              "building_energy": {2024: {"g1": {"electricity_kwh": 200000.0, "gas_kwh": None, "area_m2": 1500.0, "kwh_per_m2": 133.3, "area_parcels": 2,
                                                 "parcels": 3, "electricity_complete": 3, "gas_complete": 0}}},
              "building_energy_complete": {2024: True}, "kcsm": kcsm_inputs() if kcsm else None}
    return build_history(area, list(range(2020, 2025)), inputs)


def test_effort_on_the_provider_basis_uses_its_carbon_and_its_own_intensity():
    history = history_with_kcsm()
    result = effort(history, {"added_floor_area_m2": 1000}, 20, 1000, basis="kcsm")
    assert result["available"] and result["basis"] == "kcsm" and result["baseline_mode"] == "PROVIDED" and result["baseline_year"] == 2024
    assert result["baseline_kgco2eq"] == pytest.approx(120000.0)          # 100m cells inside the 행정동 outline
    assert result["intensity_kgco2eq_per_m2"] == pytest.approx(80.0)      # 160 t over the area grids ÷ 2,000 m² register floor area
    bau = 120000.0 + 80.0 * 1000
    need = bau - 120000.0 * 0.8
    assert result["bau_kgco2eq"] == pytest.approx(bau) and result["required_reduction_kgco2eq"] == pytest.approx(need)
    assert result["options"]["offset_kwh_per_year"] == pytest.approx(need / 0.5, abs=0.2)   # kWh only as a conversion with this tool's factor
    assert any("환산값" in a for a in result["assumptions"]) and any("급감" in a for a in result["assumptions"])
    facts = {f["id"]: f for f in area_facts(history, None, result)}
    assert {"kcsm_total", "kcsm_grid", "kcsm_tool", "kcsm_change", "kcsm_drop", "effort_basis"} <= set(facts)
    assert facts["kcsm_change"]["signed_pct"] < 0
    # no provider data in the area: the building-wide (건축HUB) basis answers and says so
    plain = history_with_kcsm(kcsm=False)
    assert plain["kcsm"] is None
    fallback = effort(plain, {"added_floor_area_m2": 1000}, 20, basis="kcsm")
    assert fallback["available"] and fallback["basis"] == "buildings" and fallback["fallback_from"] == "kcsm"


def test_the_public_gateway_never_gets_the_provider_data():
    from fastapi.testclient import TestClient

    from app.area import analyze
    from app.area_report import public_view
    from app.main import app
    with pytest.raises(ValueError, match="공개 시연 주소"):
        analyze(None, {"type": "admin", "code": "x"}, 2020, 2024, effort_basis="kcsm", public=True)
    r = TestClient(app).get("/api/map/kcsm100", params={"grid": "cell_971500_1761500"}, headers={"X-Public-Gateway": "1"})
    assert r.status_code == 403 and "공개 시연 주소" in r.json()["detail"]
    stored = {"history": {"kcsm": {"available": True}, "years": [2024]}, "effort": {"basis": "kcsm", "available": True},
              "facts": [{"id": "scope", "text": "a"}, {"id": "kcsm_total", "text": "b"}, {"id": "effort_target", "text": "c"}],
              "summary": {"mode": "TEMPLATE", "paragraphs": ["a", "b", "c"]}}
    view = public_view(stored)
    assert "kcsm" not in view["history"] and [f["id"] for f in view["facts"]] == ["scope"] and view["summary"]["paragraphs"] == ["a"]
    assert view["effort"]["available"] is False
