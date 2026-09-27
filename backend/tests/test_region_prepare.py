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
