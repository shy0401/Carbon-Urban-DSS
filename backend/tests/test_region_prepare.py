from app.region_prepare import STEPS, _classify, overall_status
from app.vworld import tiles_for


def test_tiles_group_four_cells_per_km():
    tiles = tiles_for(["cell_968500_1762000", "cell_968000_1762000", "cell_968000_1762500", "cell_969000_1762000", "bad"])
    assert tiles == {(968000, 1762000): ["cell_968000_1762000", "cell_968000_1762500", "cell_968500_1762000"],
                     (969000, 1762000): ["cell_969000_1762000"]}


def test_overall_status_needs_every_step():
    done = {step: {"status": "DONE"} for step in STEPS}
    assert overall_status(done) == "READY"
    assert overall_status(dict(done, weather={"status": "SKIPPED"})) == "READY"
    assert overall_status(dict(done, kapt_energy={"status": "WAITING"})) == "PARTIAL"
    assert overall_status(dict(done, zoning={"status": "RUNNING"})) == "PREPARING"
    assert overall_status({"grid": {"status": "FAILED"}}) == "NOT_PREPARED"


def test_quota_and_credentials_are_told_apart():
    from app.cache import ExternalError
    assert _classify(ExternalError("건축HUB 일일 호출 한도 초과(22): 받은 페이지는 저장되므로 다음 날 이어서 받습니다"))[0] == "WAITING"
    assert _classify(ExternalError("공공데이터 호출 제한"))[0] == "WAITING"
    assert _classify(ExternalError("API 인증 실패: DATA_GO_KR_SERVICE_KEY 미설정"))[0] == "BLOCKED"
    assert _classify(ExternalError("SGIS 격자 API 오류: provider_code=-200"))[0] == "FAILED"
    status, message = _classify(KeyError("x"))
    assert status == "FAILED" and message == "처리 실패: KeyError"


def test_collect_energy_years_runs_newest_first_and_stops_at_the_daily_quota(monkeypatch):
    from app import energy_parcels, region_prepare
    from app.cache import ExternalError

    class Region:
        legal_codes = ["1174010100"]
        datasets = {"building_energy": {"status": "DONE", "year": 2025}}

    region = Region()

    class Db:
        def get(self, model, code):
            return region

        def rollback(self):
            pass

        def refresh(self, obj, **kw):
            pass

        def commit(self):
            pass

    calls = []

    def collect(db, year, progress, regions):
        calls.append(year)
        if year == 2022:
            raise ExternalError("공공데이터 호출 제한 (22)")
        return {"requests": 10, "inserted": 5, "updated": 0}

    monkeypatch.setattr(region_prepare, "legal_leaves", lambda db, codes: [{"sigunguCd": "11740", "bjdongCd": "10100"}])
    monkeypatch.setattr(energy_parcels, "collect_energy_all", collect)
    monkeypatch.setattr(energy_parcels, "build_parcel_grid", lambda db: 0)
    result = region_prepare.collect_energy_years(Db(), "11740", [2019, 2022, 2024, 2023, 2021], log=lambda m: None)
    assert calls == [2024, 2023, 2022]                      # newest first; 2021 not asked after the quota answer
    assert sorted(result["done"]) == [2023, 2024] and result["left"] == [2021, 2022]
    assert result["years_before_hub"] == [2019]              # 건축HUB starts 2020: never requested
    # each year's own state: the quota-cut year is not DONE, so it reads as 잠정값 (energy_parcels.region_year_complete)
    assert region.datasets["energy_years"] == {"2024": "DONE", "2023": "DONE", "2022": "WAITING"}
    assert region.datasets["building_energy"] == {"status": "DONE", "year": 2025}


def test_region_year_complete_uses_the_region_record_not_the_city_wide_file(tmp_path, monkeypatch):
    """The progress file speaks for 전주 only. A prepared region counts its analysis year (지역 준비) and the
    years region-energy-history finished; a year the daily quota cut half way stays 잠정값."""
    import json
    from app.energy_parcels import region_year_complete
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    (tmp_path / "ops").mkdir()
    (tmp_path / "ops" / "history-progress.json").write_text(
        json.dumps({"items": {f"energy:{y}": {"status": "DONE", "scope": "all_parcels"} for y in range(2020, 2026)}}), encoding="utf-8")

    class Study:
        def __init__(self, datasets):
            self.datasets = datasets

    regions = {
        "26440": Study({"building_energy": {"status": "DONE", "year": 2025},
                        "energy_years": {"2024": "DONE", "2021": "DONE", "2020": "WAITING"}}),
        "41110": Study({"building_energy": {"status": "DONE", "message": "2025년 법정동·리 4곳, 요청 1회, 새 행 1"}}),  # older record: no year key
        "36110": Study({"building_energy": {"status": "WAITING", "year": 2025}}),
    }

    class Db:
        def get(self, model, code):
            return regions.get(code)

        def rollback(self):
            pass

    db = Db()
    assert region_year_complete(db, "52110", 2020) and region_year_complete(db, None, 2023)   # 전주: the city-wide file
    assert region_year_complete(db, "26440", 2025) and region_year_complete(db, "26440", 2024)
    assert not region_year_complete(db, "26440", 2020)      # quota stopped it half way
    assert not region_year_complete(db, "26440", 2022)      # never collected for this region
    assert region_year_complete(db, "41110", 2025) and not region_year_complete(db, "41110", 2024)
    assert not region_year_complete(db, "36110", 2025)      # the step itself is still waiting
    assert not region_year_complete(db, "99999", 2025)      # not a prepared region


def test_weather_moves_to_where_people_live_when_the_region_centre_is_at_sea(monkeypatch, tmp_path):
    """군산 (2026-10-10): the bbox centre (35.904, 126.4445) lies at sea because of 고군산군도; ERA5-Land has no cell there and
    answered null for every day (0 complete months). The step then asks at the median position of the region's K-apt complexes."""
    import json as _json
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app import collectors, region_prepare, solar
    from app.kapt import ApartmentComplex
    from app.regions import RegionWeatherMonthly

    engine = create_engine("sqlite+pysqlite:///:memory:")
    ApartmentComplex.__table__.create(engine)
    RegionWeatherMonthly.__table__.create(engine)
    db = sessionmaker(engine)()
    for code, bjd, lat, lon in (("A1", "5213010100", 35.97, 126.70), ("A2", "5213010200", 35.96, 126.72),
                                ("A3", "5213010300", 35.98, 126.74), ("X9", "5211110100", 35.82, 127.10)):
        db.add(ApartmentComplex(kapt_code=code, snapshot_month="202609", name=code, bjd_code=bjd, latitude=lat, longitude=lon, summary_json={}))
    db.commit()

    def payload(value):
        days = ["2025-01-%02d" % d for d in range(1, 32)]
        return _json.dumps({"daily": {"time": days, "temperature_2m_mean": [value] * 31, "temperature_2m_min": [value] * 31,
                                      "temperature_2m_max": [value] * 31, "precipitation_sum": [0.0 if value is not None else None] * 31}}).encode()

    asked = []

    class Client:
        def get(self, provider, operation, url, params):
            asked.append((params["latitude"], params["longitude"]))
            at_sea = params["longitude"] < 126.6
            return {"body": payload(None if at_sea else 1.5)}

    monkeypatch.setattr(collectors, "client", Client())
    monkeypatch.setattr(solar, "fetch_region", lambda *a, **k: 0)
    monkeypatch.setattr(region_prepare, "analysis_year", lambda: 2025)
    monkeypatch.setattr(region_prepare, "_root", lambda: tmp_path)

    class Region:
        code, legal_codes, center_lat, center_lon = "52130", ["52130"], 35.904, 126.4445

    result = region_prepare.step_weather(db, Region(), print)
    assert asked == [(35.904, 126.4445), (35.97, 126.72)]  # centre first, then the median complex position (X9 is another city)
    row = db.get(RegionWeatherMonthly, ("52130", "202501"))
    assert row.days_observed == 31 and row.mean_temperature == 1.5 and (row.latitude, row.longitude) == (35.97, 126.72)
    assert "완전월 1개월" in result["message"] and "바다" in result["message"]


def test_collect_kapt_years_records_each_year_skips_done_ones_and_stops_at_the_daily_quota(monkeypatch):
    """K-apt past years of a prepared region (지역 준비 takes only the analysis year). Daily quota 5,000 calls: a year cut by the
    quota is WAITING (asked again next night, answered months are not asked again), and no further year is asked."""
    from app import kapt_energy, region_prepare
    from app.cache import ExternalError

    class Region:
        code = "52710"
        legal_codes = ["52710"]
        datasets = {"complexes": {"status": "DONE"}, "kapt_energy": {"status": "DONE", "year": 2025}, "kapt_years": {"2024": "DONE"}}

    region = Region()

    class Db:
        def get(self, model, code):
            return region

        def rollback(self):
            pass

        def refresh(self, obj, **kw):
            pass

        def commit(self):
            pass

    calls = []

    def collect(db, year, scope, **kw):
        calls.append((year, scope, kw["history"], kw["region"]))
        if year == 2022:
            raise ExternalError("공공데이터 호출 제한")
        return {"requested": 500, "normalized": 480, "failed": 0}

    monkeypatch.setattr(kapt_energy, "collect_kapt_energy", collect)
    monkeypatch.setattr(region_prepare, "_kapt_failed_months", lambda db, legal, year: 3 if year == 2023 else 0)
    result = region_prepare.collect_kapt_years(Db(), "52710", [2021, 2022, 2023, 2024], log=lambda m: None)
    assert calls == [(2023, "full", True, "52710"), (2022, "full", True, "52710")]   # 2024 already DONE; newest first
    assert result["stopped"] == "WAITING" and result["left"] == [2021, 2022, 2023]
    # 2023 has 3 months still failing at the gateway for this region: PARTIAL (asked again), never 0
    assert region.datasets["kapt_years"] == {"2024": "DONE", "2023": "PARTIAL", "2022": "WAITING"}
    assert region.datasets["kapt_energy"] == {"status": "DONE", "year": 2025}


def test_kapt_step_of_region_prepare_rides_out_a_gateway_burst_and_counts_only_its_own_region(monkeypatch):
    """10/13: two short "04" bursts left 1,086 군산 complex-months FAILED with no pause and no retry.
    The step now pauses and retries like the back-fill, and another region's failures do not fail it."""
    import pytest
    from app import kapt_energy, region_prepare
    from app.cache import ExternalError

    class Region:
        code = "52130"
        legal_codes = ["52130"]

    seen = {}

    def collect(db, year, scope, **kw):
        seen.update(kw)
        return {"requested": 1896, "normalized": 1500, "failed": 199, "not_reported": 300, "suspect": 10}  # 199 = 가평's, not this region's

    monkeypatch.setattr(kapt_energy, "collect_kapt_energy", collect)
    monkeypatch.setattr(region_prepare, "_kapt_failed_months", lambda db, legal, year: 0 if legal == ["52130"] else 199)
    result = region_prepare.step_kapt_energy(None, Region(), print)
    assert seen["region"] == "52130" and seen["retry_rounds"] == 1 and seen["outage_pause_s"] == 300 and seen["max_outage_pauses"] == 6
    assert result["rows"] == 1500

    monkeypatch.setattr(region_prepare, "_kapt_failed_months", lambda db, legal, year: 12)
    with pytest.raises(ExternalError, match="12개 단지·월"):
        region_prepare.step_kapt_energy(None, Region(), print)


def test_collect_kapt_years_needs_the_region_complexes_first():
    from app import region_prepare

    class Region:
        code = "41820"
        legal_codes = ["41820"]
        datasets = {"grid": {"status": "DONE"}}

    class Db:
        def get(self, model, code):
            return Region()

    result = region_prepare.collect_kapt_years(Db(), "41820", [2024], log=lambda m: None)
    assert result["stopped"] == "NO_COMPLEXES" and result["left"] == [2024]
