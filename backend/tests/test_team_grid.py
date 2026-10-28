"""팀 데이터셋(탄소공간지도 500m·국토통계지도 100m·개발 사례) 붙이기: 중복 없이, 빈 값은 결측."""
from pathlib import Path

from app.team_grid import (cell_properties, dataset_dirs, dataset_region, dev_row, num, pair_stats, row100, row500, score_summary, year_for)

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
    assert d["id"] == "52110_전주시|2016_2019_다마59b60b|다마59b60b|2016-2019" and d["data"]["buildings_tco2e_change"] == 2692.9


def test_dataset_folders_skip_the_combined_table(tmp_path: Path):
    for name in ("00_합본_1차", "52110_전주시", "36110_세종특별자치시"):
        (tmp_path / "2026-10-01" / name / "2024").mkdir(parents=True)
    assert [d.name for d in dataset_dirs(tmp_path)] == ["36110_세종특별자치시", "52110_전주시"]
    # 7차 인계 묶음은 code/data/processed 아래에 도시 폴더가 있고, 같은 이름이면 새 묶음이 앞선다
    for name in ("00_합본_7차", "52110_전주시", "41117_경기도_수원시_영통구"):
        (tmp_path / "2026-10-20" / "code" / "data" / "processed" / name).mkdir(parents=True)
    (tmp_path / "_incoming").mkdir()
    dirs = {d.name: d for d in dataset_dirs(tmp_path)}
    assert sorted(dirs) == ["36110_세종특별자치시", "41117_경기도_수원시_영통구", "52110_전주시"]
    assert "2026-10-20" in str(dirs["52110_전주시"])


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


def _grid100_db(rows):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.team_grid import _GRID100, TeamGrid100
    _GRID100.clear()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    TeamGrid100.__table__.create(engine)
    db = sessionmaker(engine)()
    for x, y, year, pop, status, bldg in rows:
        db.add(TeamGrid100(id=f"52110_전주시|g{x}_{y}|{year}", dataset="52110_전주시", region_code="52110", grid_code=f"g{x}_{y}",
                           grid500_code="다마71b61b", x=x, y=y, year=year, population=pop, population_status=status, building_count=bldg,
                           floor_area_est=bldg * 1000.0 if bldg else None, approval_year=2001.4 if bldg else None, zone_class="residential"))
    db.commit()
    return db


GRID100_ROWS = [(971500, 1761500, 2024, 40.0, "observed", 3.0), (971600, 1761500, 2024, None, "masked", 1.0),
                (971700, 1761600, 2024, None, "empty", 2.0), (972000, 1761500, 2024, 7.0, "observed", None),   # next 500m cell
                (971500, 1761500, 2022, 30.0, "observed", 3.0)]


def test_grid100_cells_of_one_500m_cell_keep_masked_and_empty_population_missing():
    """국토통계지도 100m on the map: the cells of one 500m cell, the nearest earlier team year, never a 0 for 비공개/빈 칸."""
    from app.team_grid import grid100_features
    db = _grid100_db(GRID100_ROWS)
    out = grid100_features(db, "52110", 2025, grid500="cell_971500_1761500")
    assert out["meta"]["year"] == 2024 and out["meta"]["years"] == [2022, 2024] and out["meta"]["cells"] == 4
    feats = {f["properties"]["x"]: f["properties"] for f in out["features"]}
    assert set(feats) == {971500, 971600, 971700}   # 972000 is in the next 500m cell
    assert feats[971500]["population"] == 40.0 and feats[971500]["population_status"] == "observed"
    assert feats[971600]["population"] is None and feats[971600]["population_status"] == "masked"
    assert feats[971700]["population"] is None and feats[971700]["population_status"] == "empty"
    assert feats[971500]["approval_year"] == 2001 and feats[971500]["floor_area_m2"] == 3000.0 and feats[971500]["zone_class"] == "residential"
    ring = out["features"][0]["geometry"]["coordinates"][0]
    assert len(ring) == 5 and ring[0] == ring[-1] and 126.5 < ring[0][0] < 127.5 and 35.5 < ring[0][1] < 36.2   # EPSG:5179 → lon/lat
    summary = out["summary"]
    assert summary == {"cells_with_data": 3, "population_sum": 40.0, "population_cells": 1, "masked_cells": 1, "buildings_sum": 6.0, "floor_area_sum": 6000.0}


def test_grid100_viewport_years_and_regions_without_data():
    from app.team_grid import grid100_features
    from pyproj import Transformer
    db = _grid100_db(GRID100_ROWS)
    to_ll = Transformer.from_crs(5179, 4326, always_xy=True).transform
    (w, s), (e, n) = to_ll(971950, 1761450), to_ll(972150, 1761650)
    view = grid100_features(db, "52110", 2024, bbox=(w, s, e, n))
    assert [f["properties"]["x"] for f in view["features"]] == [972000]
    capped = grid100_features(db, "52110", 2024, bbox=(126.0, 35.0, 128.0, 37.0), limit=2)
    assert len(capped["features"]) == 2 and capped["meta"]["truncated"] is True and capped["meta"]["returned"] == 2
    early = grid100_features(db, "52110", 2015, grid500="cell_971500_1761500")
    assert early["features"] == [] and early["meta"]["year"] is None and "2016" not in early["meta"]["reason"] and early["meta"]["years"] == [2022, 2024]
    none = grid100_features(db, "41110", 2024, grid500="cell_971500_1761500")
    assert none["features"] == [] and none["meta"]["years"] == [] and none["meta"]["reason"]
    meta = grid100_features(db, "52110", 2025, meta_only=True)
    assert meta["features"] == [] and meta["meta"]["cells"] == 4 and meta["meta"]["year"] == 2024


TRAIN_HEAD = ("grid_id_500m,year,x_min_m,y_min_m,is_partial_cell,population_total_persons_sum,floor_area_total_est_m2,"
              "elec_tco2e_total,gas_tco2e_total,heat_tco2e_total,buildings_tco2e_total,carbon_zero_status,reg_floor_area_m2,train_usable,train_issues")
DEV_HEAD = "grid_id_500m,x_min_m,y_min_m,before_year,after_year,development_id,buildings_tco2e_change,pair_usable,site_kind,use_kind"


def _seven(tmp_path: Path, elec_2024: str = "60") -> None:
    """A 10-01 shared bundle (months, 100m) and a 7차 인계 bundle (training.csv for every year, no months, no 100m)."""
    old = tmp_path / "2026-10-01" / "52110_전주시"
    for year, total in ((2016, "80"), (2024, "100")):
        (old / str(year)).mkdir(parents=True)
        (old / str(year) / "grid_500m.csv").write_text("\n".join([HEAD500, f"다마71b61b,971500,1761500,False,120,20000,5,60,40,0,{total},positive,,True,ok"]), encoding="utf-8")
        (old / str(year) / "grid_100m.csv").write_text(
            "grid_id_100m,grid_id_500m,x_min_m,y_min_m,population_total_persons,population_total_persons_status,building_count,reg_floor_area_m2\n"
            "다마715615,다마71b61b,971500,1761500,40,observed,3,900\n", encoding="utf-8")
    (old / "developments.csv").write_text(DEV_HEAD + "\n다마71b61b,971500,1761500,2016,2024,d1,20,True,built_up,residential\n", encoding="utf-8")
    new = tmp_path / "2026-10-20" / "code" / "data" / "processed" / "52110_전주시"
    new.mkdir(parents=True)
    rows = [TRAIN_HEAD, "다마71b61b,2014,971500,1761500,False,110,19000,50,35,0,85,positive,,True,none",
            "다마71b61b,2016,971500,1761500,False,120,20000,60,40,0,80,positive,,True,none",  # same totals as 10-01 → months kept
            f"다마71b61b,2024,971500,1761500,False,120,20000,{elec_2024},40,0,100,positive,,False,suspect_region_drop"]
    (new / "training.csv").write_text("\n".join(rows), encoding="utf-8")
    (new / "developments.csv").write_text(DEV_HEAD + "\n다마71b61b,971500,1761500,2014,2024,d1,15,True,built_up,residential"
                                          "\n다마71b61b,971500,1761500,2016,2024,d1,20,True,built_up,residential\n", encoding="utf-8")
    cv = tmp_path / "2026-10-20" / "code" / "data" / "processed" / "00_합본_7차" / "baseline"
    cv.mkdir(parents=True)
    (cv / "development_cases.csv").write_text("region,grid_id_500m,before_year,after_year,years_from,actual_change_tco2e,"
                                              "pred_change_model_all_regions_cv_tco2e,pred_change_model_other_regions_tco2e\n"
                                              "52110_전주시,다마71b61b,2016,2024,dated,1200,1500,900\n", encoding="utf-8")
    test = tmp_path / "2026-10-20" / "code" / "docs" / "results" / "data" / "r011-split-a"
    test.mkdir(parents=True)
    (test / "holdout_cases_join7_42_w10.csv").write_text("region,grid_id_500m,before_year,after_year,site_kind,use_kind,years_from,"
                                                         "actual_change_tco2e,pred_change_model_frozen\n"
                                                         "52110_전주시,다마71b61b,2018,2024,built_up,residential,dated,-400,-100\n", encoding="utf-8")


def test_seventh_bundle_replaces_years_keeps_months_and_100m(tmp_path: Path):
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    from app.team_grid import TeamGrid100, TeamGrid500, development_summary, developments, import_team_grid, map_properties
    db = sessionmaker(create_engine("sqlite+pysqlite:///:memory:"))()
    old_only = tmp_path / "only-old"
    _seven(tmp_path)
    # first the 10-01 bundle alone (as it was in the DB before the 7차 bundle came)
    old_only.mkdir()
    (tmp_path / "2026-10-01").rename(old_only / "2026-10-01")
    import_team_grid(db, old_only, log=lambda m: None)
    (old_only / "2026-10-01").rename(tmp_path / "2026-10-01")
    stats = import_team_grid(db, tmp_path, log=lambda m: None)
    assert stats["grid500"] == 3 and stats["months_kept"] == 2 and stats["months_dropped"] == 0
    rows = {r.year: r for r in db.scalars(select(TeamGrid500))}
    assert sorted(rows) == [2014, 2016, 2024]
    assert rows[2016].monthly["elec"][0] == 5.0 and rows[2016].flags["monthly_from"].startswith("2026-10-01")
    assert rows[2024].monthly["elec"][0] == 5.0  # 2024 totals are the same too
    assert rows[2014].monthly == {} and "training.csv" in rows[2014].source_file
    assert rows[2024].flags["train_issues"] == "suspect_region_drop" and rows[2024].flags["train_usable"] is False
    assert db.query(TeamGrid100).count() == 2  # 100m stays from the 10-01 bundle (the 7차 bundle has none)
    devs = developments(db, "52110")
    assert {(d["before_year"], d["after_year"]) for d in devs} == {(2014, 2024), (2016, 2024), (2018, 2024)}  # 10-01 cases replaced, no double
    scored = developments(db, "52110", scored_only=True)
    assert [(d["before_year"], d["model"]["set"], d["model"]["pred_tco2e"]) for d in scored] == [(2016, "train_cv", 1500), (2018, "test", -100)]
    # 2018 → 2024 is not a listed pair of the cell: the score line becomes its own row at the cell's corner (not dropped)
    assert scored[1]["grid_id"] == "cell_971500_1761500" and scored[1]["pair_usable"] is True
    summary = development_summary(db, "52110")
    assert summary["cases"] == 1 and summary["pairs"] == 3 and summary["scored"] == 2 and summary["model"]["set"] == "mixed"
    assert summary["model"]["all"]["median_relative_error"] == 0.5 and summary["model"]["all"]["sum_ratio"] == round(1400 / 800, 3)
    props = map_properties(db, "52110", 2025, ["cell_971500_1761500"])["cell_971500_1761500"]
    assert props["cm_year"] == 2024 and props["cm_change_base_year"] == 2014
    again = import_team_grid(db, tmp_path, log=lambda m: None)
    assert again["grid500"] == 0 and again["scored_cases"] is None
    assert db.query(TeamGrid500).count() == 3
    forced = import_team_grid(db, tmp_path, force=True, log=lambda m: None)
    assert forced["scored_cases"] == 2 and len(developments(db, "52110")) == 3  # no second score-only row


def test_seventh_bundle_drops_months_when_totals_differ(tmp_path: Path):
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    from app.team_grid import TeamGrid500, import_team_grid
    db = sessionmaker(create_engine("sqlite+pysqlite:///:memory:"))()
    _seven(tmp_path, elec_2024="70")
    old_only = tmp_path / "only-old"
    old_only.mkdir()
    (tmp_path / "2026-10-01").rename(old_only / "2026-10-01")
    import_team_grid(db, old_only, log=lambda m: None)
    (old_only / "2026-10-01").rename(tmp_path / "2026-10-01")
    stats = import_team_grid(db, tmp_path, log=lambda m: None)
    assert stats["months_kept"] == 1 and stats["months_dropped"] == 1
    assert next(r for r in db.scalars(select(TeamGrid500)) if r.year == 2024).monthly == {}


def test_score_summary_uses_the_team_definitions():
    cases = [{"actual_tco2e": 1000, "pred_tco2e": 1300}, {"actual_tco2e": 2000, "pred_tco2e": 1000}, {"actual_tco2e": -500, "pred_tco2e": 200},
             {"actual_tco2e": 50, "pred_tco2e": 400}]  # below 100 tCO2e: only the direction and the sum count
    s = score_summary(cases)
    assert s["cases"] == 4 and s["measured"] == 3 and s["median_relative_error"] == 0.5
    assert s["within_50pct"] == 0.667 and s["same_direction"] == 0.75 and s["big_cases"] == 2
    assert s["sum_ratio"] == round(2900 / 2550, 3)
    assert score_summary([]) is None


def test_a_city_with_districts_reads_its_district_tables_and_adds_a_shared_cell():
    """수원시(41110)는 이 도구에서 한 지역이고 팀 표는 구(권선 41113·영통 41117)마다 있다: 두 구에 걸친 칸은 몫을 더한다."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.regions import StudyRegion
    from app.team_grid import _CACHE, _DATASETS, TeamGrid500, combine_parts, map_properties, region_datasets, region_totals
    _CACHE.clear()
    _DATASETS.clear()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    TeamGrid500.__table__.create(engine)
    StudyRegion.__table__.create(engine)
    db = sessionmaker(engine)()
    db.add(StudyRegion(code="41110", name="경기도 수원시", sido_name="경기도", legal_codes=["41111", "41113", "41115", "41117"]))
    def row(ds, x, total, floor, usable=True, issues="none", year=2024):
        return TeamGrid500(id=f"{ds}|g{x}|{year}", dataset=ds, region_code=ds[:5], grid_code=f"g{x}", x=x, y=1000, year=year, elec_t=total / 2,
                           gas_t=total / 2, heat_t=None, total_t=total, monthly={}, ngii={"floor_area": floor, "approval_year": 2000.0 + floor / 1000},
                           register={"floor_area": floor}, flags={"train_usable": usable, "train_issues": issues}, partial=True, source_file="t")
    db.add_all([row("41113_경기도_수원시_권선구", 500, 100.0, 10000.0), row("41117_경기도_수원시_영통구", 500, 300.0, 30000.0, usable=False, issues="suspect_drop"),
                row("41117_경기도_수원시_영통구", 1000, 50.0, 5000.0), row("41117_경기도_수원시_영통구", 500, 200.0, 20000.0, year=2014),
                row("41117_경기도_수원시_영통구", 1000, 40.0, 4000.0, year=2014)])
    db.commit()
    assert region_datasets(db, "41110") == ["41113_경기도_수원시_권선구", "41117_경기도_수원시_영통구"]
    assert region_datasets(db, "52110") == []
    props = map_properties(db, "41110", 2025, ["cell_500_1000", "cell_1000_1000"])
    shared = props["cell_500_1000"]
    assert shared["cm_total_t"] == 400.0 and shared["cm_change_base_year"] == 2014 and shared["cm_change_pct"] == 100.0
    assert shared["ngii_floor_area_m2"] == 40000.0 and shared["ngii_approval_year"] == 2030.0  # a mean: the larger part's value
    assert shared["cm_flags"]["train_issues"] == "suspect_drop" and shared["cm_flags"]["train_usable"] is False and shared["cm_partial"] is None
    totals = region_totals(db, "41110")
    assert totals[2024]["total_t"] == 450.0 and totals[2024]["cells"] == 2  # the shared cell counted once
    one = {"year": 2024, "total_t": 1.0, "flags": {}, "ngii": {}, "register": {}, "partial": True}
    assert combine_parts([one]) is one


def test_repository_copy_adds_same_bundle_months_held_years_and_100m(tmp_path: Path):
    """2026-10-29 팀 저장소 사본: 7차와 같은 training.csv에 그해 grid_500m.csv의 월별을(연간 합계가 같을 때만) 붙이고,
    학습에서 뺀 해(_held_year_2020)도 그 도시의 해로 넣는다. 100m는 가장 새 묶음의 해마다 표."""
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    from app.team_grid import TeamGrid100, TeamGrid500, dataset_dirs, import_team_grid
    db = sessionmaker(create_engine("sqlite+pysqlite:///:memory:"))()
    head = TRAIN_HEAD
    train = [head, "다마71b61b,2016,971500,1761500,False,120,20000,60,40,0,100,positive,,True,none",
             "다마71b61b,2024,971500,1761500,False,120,20000,60,40,0,100,positive,,True,none"]
    month_head = "grid_id_500m,x_min_m,y_min_m,elec_tco2e_m01,elec_tco2e_m02,gas_tco2e_m01,elec_tco2e_total,gas_tco2e_total,heat_tco2e_total,buildings_tco2e_total"
    g100 = ("grid_id_100m,grid_id_500m,x_min_m,y_min_m,population_total_persons,population_total_persons_status,building_count,reg_floor_area_m2\n"
            "다마715615,다마71b61b,971500,1761500,40,observed,3,900\n")
    for snap in ("2026-10-20", "2026-10-29"):
        city = tmp_path / snap / "code" / "data" / "processed" / "52110_전주시"
        city.mkdir(parents=True)
        (city / "training.csv").write_text("\n".join(train), encoding="utf-8")
    new = tmp_path / "2026-10-29" / "code" / "data" / "processed"
    (new / "52110_전주시" / "2016").mkdir()
    (new / "52110_전주시" / "2016" / "grid_500m.csv").write_text(month_head + "\n다마71b61b,971500,1761500,5,4,3,60,40,0,100\n", encoding="utf-8")
    (new / "52110_전주시" / "2016" / "grid_100m.csv").write_text(g100, encoding="utf-8")
    (new / "52110_전주시" / "2024").mkdir()
    (new / "52110_전주시" / "2024" / "grid_500m.csv").write_text(month_head + "\n다마71b61b,971500,1761500,5,4,3,70,40,0,110\n", encoding="utf-8")
    held = new / "_held_year_2020" / "52110_전주시" / "2020"
    held.mkdir(parents=True)
    (held / "grid_500m.csv").write_text(month_head + "\n다마71b61b,971500,1761500,6,5,4,65,45,0,110\n", encoding="utf-8")
    (held / "grid_100m.csv").write_text(g100, encoding="utf-8")
    assert "_held_year_" not in str(dataset_dirs(tmp_path)[0]) and "2026-10-29" in str(dataset_dirs(tmp_path)[0])
    stats = import_team_grid(db, tmp_path, log=lambda m: None)
    assert stats["datasets"] == ["52110_전주시"] and stats["grid500"] == 3 and stats["grid100"] == 2
    assert stats["months_same_bundle"] == 1 and stats["months_same_bundle_dropped"] == 1
    rows = {r.year: r for r in db.scalars(select(TeamGrid500))}
    assert sorted(rows) == [2016, 2020, 2024]
    assert rows[2016].monthly["elec"][:2] == [5.0, 4.0] and rows[2016].flags["monthly_from"] == "2026-10-29 2016/grid_500m.csv"
    assert rows[2016].flags["train_issues"] == "none" and "2026-10-29" in rows[2016].source_file   # the training table stays the base
    assert rows[2024].monthly == {}                                    # totals differ (60 vs 70): no months, not a guess
    assert "_held_year_2020" in rows[2020].source_file and rows[2020].monthly["gas"][0] == 4.0 and rows[2020].total_t == 110.0
    assert sorted(r.year for r in db.scalars(select(TeamGrid100))) == [2016, 2020]
    again = import_team_grid(db, tmp_path, log=lambda m: None)
    assert again["grid500"] == 0 and again["grid100"] == 0
