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
