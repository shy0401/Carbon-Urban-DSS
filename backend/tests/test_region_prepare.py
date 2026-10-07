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

    class Db:
        def get(self, model, code):
            return Region()

        def rollback(self):
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
