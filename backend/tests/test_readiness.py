from fastapi.testclient import TestClient

from app.main import app


def test_readiness_describes_every_operational_source_without_secret_values(monkeypatch):
    monkeypatch.setenv("DATA_GO_KR_SERVICE_KEY", "never-return-this-service-key")
    monkeypatch.setenv("SGIS_CONSUMER_KEY", "never-return-this-consumer-key")
    monkeypatch.setenv("SGIS_CONSUMER_SECRET", "never-return-this-consumer-secret")
    monkeypatch.setenv("VWORLD_API_KEY", "never-return-this-vworld-key")
    response = TestClient(app).get("/api/readiness")
    assert response.status_code == 200
    body = response.json()
    ids = {item["id"] for item in body["sources"]}
    assert {"kapt_energy", "weather_kma", "sgis_admin", "sgis_grid", "vworld_zoning", "vworld_cadastral", "energy", "building_official"} <= ids
    assert body["summary"]["total_sources"] == len(body["sources"])
    assert body["pipeline"][0]["id"] == "acquire"
    assert body["pipeline"][-1]["id"] == "decision"
    serialized = response.text
    assert "never-return-this" not in serialized


def test_readiness_explains_collection_scope_and_uses():
    body = TestClient(app).get("/api/readiness").json()
    sources = {item["id"]: item for item in body["sources"]}
    kapt = sources["kapt_energy"]
    assert kapt["collection_dataset"] == "kapt_energy"
    assert kapt["scopes"]["smoke"] == "1단지 × 1개월"
    assert "운영탄소" in " ".join(kapt["uses"])
    assert sources["sgis_grid"]["acquisition"] == "MANUAL_DOWNLOAD"
    assert sources["vworld_zoning"]["scopes"]["smoke"] == "분석격자 1개 bbox"


def test_local_engine_status_exposes_safe_operating_role(monkeypatch):
    class FailedClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, *args, **kwargs):
            raise RuntimeError("offline")

    monkeypatch.setattr("app.reporting.httpx.Client", FailedClient)
    body = TestClient(app).get("/api/reports/engine").json()
    assert body["provider"] == "Ollama local container"
    assert body["privacy"] == "로컬 Docker 네트워크 내부 처리"
    assert body["allowed_tasks"] == ["검증된 근거 ID 선택", "한국어 보고서 요약"]
    assert "수치 계산" in body["prohibited_tasks"]
