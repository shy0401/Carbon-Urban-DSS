"""팀 데이터셋(탄소공간지도 500m·국토통계지도 100m·개발 사례) 붙이기: 중복 없이, 빈 값은 결측."""
from pathlib import Path

from app.team_grid import (cell_properties, dataset_dirs, dataset_region, dev_row, num, pair_stats, row100, row500, year_for)

HEAD500 = ("grid_id_500m,x_min_m,y_min_m,is_partial_cell,population_total_persons_sum,floor_area_total_est_m2,elec_tco2e_m01,"
           "elec_tco2e_total,gas_tco2e_total,heat_tco2e_total,buildings_tco2e_total,carbon_zero_status,reg_floor_area_m2,train_usable,elec_drop_status")


def test_values_and_names():
    assert num("") is None and num("nan") is None and num("0") == 0.0 and num("1.5") == 1.5 and num("x") is None
    assert dataset_region("52110_전주시") == "52110" and dataset_region("00_합본_1차") is None and dataset_region("viewer") is None
    assert year_for([2016, 2019, 2022, 2024], 2025) == 2024 and year_for([2016, 2019, 2022, 2024], 2020) == 2019
    assert year_for([2016, 2019], 2015) is None


def test_row500_keeps_missing_as_none_and_flags():
    r = dict(zip(HEAD500.split(","), "다마71b61b,971500,1761500,False,120,30000,1.5,20.5,10,,30.5,positive,25000,True,ok".split(",")))
    row = row500("52110_전주시", 2024, r, "x.csv")
    assert row["id"] == "52110_전주시|다마71b61b|2024" and row["region_code"] == "52110" and (row["x"], row["y"]) == (971500, 1761500)
    assert row["elec_t"] == 20.5 and row["heat_t"] is None and row["total_t"] == 30.5  # empty heat: 결측, not 0
    assert row["monthly"]["elec"][0] == 1.5 and row["monthly"]["elec"][1] is None and "heat" not in row["monthly"]
    assert row["ngii"]["population"] == 120 and row["register"]["floor_area"] == 25000 and row["flags"]["train_usable"] is True


def test_row100_drops_cells_without_any_value():
    empty = {"grid_id_100m": "다마711612", "grid_id_500m": "다마71b61a", "x_min_m": "971100", "y_min_m": "1761200",
             "population_total_persons_status": "empty", "building_count": "", "reg_floor_area_m2": "0.0"}
    assert row100("52110_전주시", 2024, empty) is None
    masked = dict(empty, population_total_persons_status="masked")
    assert row100("52110_전주시", 2024, masked)["population"] is None  # 1~5명 비공개: not 0


def test_cell_properties_hides_restricted_values_on_the_public_gateway():
    now = {"year": 2024, "total_t": 100.0, "elec_t": 60.0, "gas_t": 40.0, "heat_t": 0.0, "ngii": {"floor_area": 20000.0, "population": 300.0},
           "register": {"floor_area": 18000.0}, "flags": {"carbon_zero_status": "positive"}, "partial": False}
    base = {"year": 2016, "total_t": 80.0, "flags": {}}
    local = cell_properties(now, base, public=False, register_known=False)
    assert local["cm_change_pct"] == 25.0 and local["cm_kg_per_m2"] == 5.0 and local["ngii_population"] == 300.0
    assert local["team_reg_floor_area_m2"] == 18000.0
    public = cell_properties(now, base, public=True, register_known=True)
    assert "ngii_population" not in public and public["cm_kg_per_m2"] is None and "team_reg_floor_area_m2" not in public
    zero = cell_properties(dict(now, total_t=0.0, flags={"carbon_zero_status": "zero_with_buildings"}), base, public=False, register_known=False)
    assert zero["cm_total_t"] is None and zero["cm_change_pct"] is None  # 건물이 있는데 0: 원자료 누락으로 보고 비움


def test_pair_stats_and_development_rows():
    s = pair_stats([(80.0, 100.0), (160.0, 200.0), (30.0, 40.0), (0.0, 5.0)])
    assert s["cells"] == 3 and s["sum_ratio"] == 0.794 and s["median_ratio"] == 0.8  # the 0 pair is dropped
    assert s["within_20pct"] == 0.667 and s["log_r"] > 0.99
    assert pair_stats([(1.0, 1.0)]) is None
    d = dev_row("52110_전주시", {"grid_id_500m": "다마59b60b", "x_min_m": "959500", "y_min_m": "1760500", "before_year": "2016",
                                "after_year": "2019", "development_id": "2016_2019_다마59b60b", "buildings_tco2e_change": "2692.9"})
    assert d["id"] == "52110_전주시|2016_2019_다마59b60b|다마59b60b" and d["data"]["buildings_tco2e_change"] == 2692.9


def test_dataset_folders_skip_the_combined_table(tmp_path: Path):
    for name in ("00_합본_1차", "52110_전주시", "36110_세종특별자치시"):
        (tmp_path / "2026-10-01" / name / "2024").mkdir(parents=True)
    assert [d.name for d in dataset_dirs(tmp_path)] == ["36110_세종특별자치시", "52110_전주시"]


def test_import_is_idempotent_and_never_double_counts(tmp_path: Path):
    from sqlalchemy import create_engine, func, select
    from sqlalchemy.orm import sessionmaker

    from app.team_grid import TeamGrid500, TeamGrid100, import_team_grid, map_properties, region_totals
    engine = create_engine("sqlite+pysqlite:///:memory:")
    db = sessionmaker(engine)()
    city = tmp_path / "2026-10-01" / "52110_전주시"
    for year, total in ((2016, "80"), (2024, "100")):
        (city / str(year)).mkdir(parents=True)
        lines = [HEAD500, f"다마71b61b,971500,1761500,False,120,20000,,60,40,0,{total},positive,,True,ok",
                 f"다마71b61b,971500,1761500,False,120,20000,,60,40,0,{total},positive,,True,ok",  # the same cell twice
                 "다마71b62a,971500,1762000,False,,,,0,0,0,0,zero_with_buildings,,False,ok"]
        (city / str(year) / "grid_500m.csv").write_text("\n".join(lines), encoding="utf-8")
        (city / str(year) / "grid_100m.csv").write_text(
            "grid_id_100m,grid_id_500m,x_min_m,y_min_m,population_total_persons,population_total_persons_status,building_count,reg_floor_area_m2\n"
            "다마715615,다마71b61b,971500,1761500,40,observed,3,900\n다마715616,다마71b61b,971500,1761600,,empty,,0\n", encoding="utf-8")
    (tmp_path / "2026-10-01" / "00_합본_1차" / "2024").mkdir(parents=True)
    (tmp_path / "2026-10-01" / "00_합본_1차" / "2024" / "grid_500m.csv").write_text(HEAD500 + "\n다마71b61b,971500,1761500,False,1,1,,1,1,1,999,positive,,True,ok", encoding="utf-8")
    first = import_team_grid(db, tmp_path, log=lambda m: None)
    assert first["datasets"] == ["52110_전주시"] and first["grid500"] == 4 and first["grid100"] == 2
    again = import_team_grid(db, tmp_path, log=lambda m: None)
    assert again["grid500"] == 0 and again["skipped_files"] == 4
    assert db.scalar(select(func.count()).select_from(TeamGrid500)) == 4 and db.scalar(select(func.count()).select_from(TeamGrid100)) == 2
    assert region_totals(db, "52110")[2024]["total_t"] == 100.0  # 합본 and the repeated row are not added again
    props = map_properties(db, "52110", 2025, ["cell_971500_1761500", "cell_971500_1762000"])
    assert props["cell_971500_1761500"]["cm_year"] == 2024 and props["cell_971500_1761500"]["cm_change_pct"] == 25.0
    assert props["cell_971500_1762000"]["cm_total_t"] is None
