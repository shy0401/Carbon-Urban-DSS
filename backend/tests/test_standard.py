"""The shared data standard (docs/DATA_STANDARD.md): degree-day rule, factor schedule, and the CSV check."""
from pathlib import Path

from app import emissions
from app.degree_days import CDD_BASE_C, HDD_BASE_C, degree_days
from app.kma_asos import aggregate_asos_months
from app.standard import check_csv, summary


def test_degree_days_use_18_and_24_and_need_every_day():
    assert (HDD_BASE_C, CDD_BASE_C) == (18.0, 24.0)
    assert degree_days([10.0, 26.0, 18.0], 3) == (8.0, 2.0)
    assert degree_days([10.0, None, 26.0], 3) == (None, None)       # a missing day: no value, not a partial sum
    assert degree_days([], 30) == (None, None)


def test_asos_month_counts_each_date_once_and_skips_incomplete_months():
    rows = [{"observed_date": f"2025-06-{d:02d}", "station_id": "146", "avg_temperature_c": 25.0} for d in range(1, 31)]
    rows.append(dict(rows[0]))  # the same date twice (re-collected page)
    june = aggregate_asos_months(rows)[0]
    assert june["valid_day_count"] == 30 and june["cdd"] == 30.0 and june["hdd"] == 0.0
    july = aggregate_asos_months([{"observed_date": "2025-07-01", "station_id": "146", "avg_temperature_c": 28.0}])[0]
    assert july["hdd"] is None and july["cdd"] is None


def test_electricity_factor_schedule_is_the_registered_one():
    f = emissions.electricity_factor_for_year
    assert [f(y) for y in (2018, 2019, 2021, 2022, 2024, 2025)] == [None, 0.4594, 0.4594, 0.4781, 0.4781, 0.4330]
    registered = {i["effective_from"]: i["factor"] for i in emissions.HISTORIC_ELECTRICITY} | {"2025-03-31": 0.4541}
    assert dict(emissions.ELECTRICITY_SCHEDULE) == registered
    rules = summary()
    assert rules["degree_days"]["cdd_base_c"] == 24.0 and rules["electricity_factors"][-1] == {"published": "2025-12-18", "factor": 0.4330}


def _write(tmp_path: Path, name: str, text: str, encoding: str = "utf-8") -> Path:
    path = tmp_path / name
    path.write_bytes(text.encode(encoding))
    return path


def test_csv_check_finds_null_markers_missing_units_duplicates_and_bad_ids(tmp_path):
    good = _write(tmp_path, "grid.csv", "grid_id,year,electricity_kwh,floor_area_m2\ncell_964000_1757500,2024,100.5,\ncell_964500_1757500,2024,,2000\n")
    assert {i["id"]: i["status"] for i in check_csv(good)} == {
        "csv_encoding": "OK", "csv_header": "OK", "csv_nulls": "OK", "csv_units": "OK", "csv_negative": "OK", "csv_keys": "OK", "csv_grid_id": "OK"}
    bad = _write(tmp_path, "bad.csv", "grid_id,year,usage,electricity_kwh\ncell_1_2,2024,5,-3\ncell_1_2,2024,N/A,-\n다마71b61b,2024,7,1\n")
    items = {i["id"]: i for i in check_csv(bad)}
    assert items["csv_nulls"]["status"] == "WARN" and items["csv_nulls"]["count"] == 2
    assert items["csv_units"]["status"] == "WARN" and "usage" in items["csv_units"]["detail"]
    assert items["csv_negative"]["status"] == "FAIL"
    assert items["csv_keys"]["status"] == "FAIL" and items["csv_keys"]["count"] == 1
    assert items["csv_grid_id"]["status"] == "FAIL" and items["csv_grid_id"]["count"] == 1


def test_csv_check_rejects_cp949_and_reads_bom_copies(tmp_path):
    cp949 = _write(tmp_path, "cp.csv", "지역,값_kwh\n전주,1\n", "cp949")
    assert check_csv(cp949)[0]["status"] == "FAIL"
    bom = _write(tmp_path, "bom.csv", "﻿complex_code,year_month,electricity_kwh\nA1,202501,10\nA1,202502,\n")
    items = {i["id"]: i for i in check_csv(bom)}
    assert items["csv_encoding"]["status"] == "OK" and "BOM" in items["csv_encoding"]["detail"] and items["csv_keys"]["status"] == "OK"
