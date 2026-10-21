"""팀 변화 모델 연결: 공개 주소 거부, 서비스가 꺼졌을 때의 안내, 칸 좌표 전달과 추정 표시."""
from typing import Any

import pytest


def _client():
    from fastapi.testclient import TestClient

    from app.main import app
    return TestClient(app)


def test_the_public_gateway_never_reaches_the_team_model():
    c = _client()
    public = {"X-Public-Gateway": "1"}
    assert c.get("/api/team-model/status", headers=public).json()["status"] == "restricted"
    r = c.post("/api/team-model/predict", json={"region": "52110", "plans": [{"grid": "cell_959500_1760500", "new": [{"floor_area_m2": 1000}]}]},
               headers=public)
    assert r.status_code == 403 and "공개 시연 주소" in r.json()["detail"]
    assert c.get("/api/team-model/cell", params={"grid": "cell_959500_1760500"}, headers=public).status_code == 403


def test_status_says_the_service_is_off_when_it_does_not_answer(monkeypatch):
    from app import team_model
    monkeypatch.setattr(team_model, "_call", lambda path, body=None, timeout=5.0: (0, None))
    body = _client().get("/api/team-model/status").json()
    assert body["status"] == "off" and "profile team-model" in body["reason"]
    assert body["accuracy"]["test"][1]["band"] == "1천~1만" and body["accuracy"]["test"][1]["median_error"] == 0.27


def test_predict_sends_the_cell_corner_and_marks_the_answer_as_a_scenario(monkeypatch):
    from app import team_model
    sent: dict[str, Any] = {}

    def fake(path, body=None, timeout=5.0):
        sent.update(path=path, body=body)
        return 200, {"dataset": "52110_전주시", "results": [{"change_tco2e": 2500.0, "band": {"q10": 900.0}}], "combined": None}
    monkeypatch.setattr(team_model, "_call", fake)
    r = _client().post("/api/team-model/predict", json={"region": "52110", "plans": [
        {"grid": "cell_959500_1760500", "new": [{"use": "residential", "floor_area_m2": 120000, "dwellings": 1200}], "years_after": 3}]})
    assert r.status_code == 200
    plan = sent["body"]["plans"][0]
    assert sent["path"] == "/predict" and sent["body"]["region"] == "52110" and (plan["x"], plan["y"]) == (959500, 1760500)
    assert plan["new"] == [{"use": "residential", "floor_area_m2": 120000.0, "dwellings": 1200.0}] and plan["removed"] == []
    body = r.json()
    assert body["data_class"] == "SCENARIO" and body["results"][0]["grid"] == "cell_959500_1760500" and "방향만" in body["note"]


@pytest.mark.parametrize("payload,code", [
    ({"region": "52110", "plans": [{"grid": "cell_1_2"}]}, 422),                                               # nothing built or removed
    ({"region": "52110", "plans": [{"grid": "cell_1_2", "new": [{"use": "factory", "floor_area_m2": 10}]}]}, 422),  # unknown use
    ({"region": "52110", "plans": [{"grid": "x", "new": [{"floor_area_m2": 10}]}]}, 422),
])
def test_predict_rejects_plans_the_model_cannot_read(monkeypatch, payload, code):
    from app import team_model
    monkeypatch.setattr(team_model, "_call", lambda *a, **k: pytest.fail("the service must not be asked"))
    assert _client().post("/api/team-model/predict", json=payload).status_code == code


def test_predict_passes_the_reason_when_the_model_is_off_or_still_training(monkeypatch):
    from app import team_model
    plan = {"region": "52110", "plans": [{"grid": "cell_959500_1760500", "new": [{"floor_area_m2": 5000}]}]}
    monkeypatch.setattr(team_model, "_call", lambda *a, **k: (0, None))
    r = _client().post("/api/team-model/predict", json=plan)
    assert r.status_code == 503 and "꺼져" in r.json()["detail"]
    monkeypatch.setattr(team_model, "_call", lambda *a, **k: (503, {"detail": "변화 모델을 학습하는 중입니다(1~3분)", "status": "training"}))
    r = _client().post("/api/team-model/predict", json=plan)
    assert r.status_code == 503 and "학습하는 중" in r.json()["detail"]
