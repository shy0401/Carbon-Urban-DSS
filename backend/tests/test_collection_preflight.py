import hashlib
import json
import time

from app.cache import record_credential_error
from app.collection_preflight import available_collection_datasets, collection_blockers


def _cached_error(path, credential, *, age_seconds=0):
    path.mkdir(parents=True, exist_ok=True)
    (path / "failed.json").write_text(
        json.dumps(
            {
                "timestamp": time.time() - age_seconds,
                "error": "API 인증 실패: 서비스 승인 및 DATA_GO_KR_SERVICE_KEY 확인 필요 (30/20)",
                "auth_hash": hashlib.sha256(credential.encode()).hexdigest(),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_preflight_blocks_missing_credentials_without_exposing_values(monkeypatch, tmp_path):
    monkeypatch.delenv("SGIS_CONSUMER_KEY", raising=False)
    monkeypatch.delenv("SGIS_CONSUMER_SECRET", raising=False)
    monkeypatch.delenv("VWORLD_API_KEY", raising=False)
    monkeypatch.delenv("VWORLD_DOMAIN", raising=False)

    blocked = collection_blockers(["sgis", "vworld_zoning"], data_dir=tmp_path)

    assert {item["dataset"] for item in blocked} == {"sgis", "vworld_zoning"}
    assert "SGIS_CONSUMER_KEY" in blocked[0]["message"]
    assert "VWORLD_API_KEY" in blocked[1]["message"]


def test_preflight_blocks_recent_rejection_for_same_key_and_allows_replacement(monkeypatch, tmp_path):
    rejected_key = "rejected-service-key"
    monkeypatch.setenv("DATA_GO_KR_SERVICE_KEY", rejected_key)
    _cached_error(tmp_path / "cache" / "kapt-energy", rejected_key)

    blocked = collection_blockers(["kapt_energy"], data_dir=tmp_path)
    assert blocked == [
        {
            "dataset": "kapt_energy",
            "message": "현재 공공데이터포털 키가 공급자에게 거절되었습니다. 활용신청 승인 또는 키 교체 후 다시 시도하세요.",
        }
    ]
    assert rejected_key not in json.dumps(blocked, ensure_ascii=False)

    monkeypatch.setenv("DATA_GO_KR_SERVICE_KEY", "replacement-service-key")
    assert collection_blockers(["kapt_energy"], data_dir=tmp_path) == []


def test_preflight_allows_retry_after_rejection_cache_expires(monkeypatch, tmp_path):
    key = "approved-later-service-key"
    monkeypatch.setenv("DATA_GO_KR_SERVICE_KEY", key)
    _cached_error(tmp_path / "cache" / "kma-asos", key, age_seconds=3601)

    assert collection_blockers(["kma_asos"], data_dir=tmp_path) == []


def test_available_datasets_preserve_open_sources_when_a_keyed_source_is_blocked(monkeypatch, tmp_path):
    monkeypatch.delenv("DATA_GO_KR_SERVICE_KEY", raising=False)

    assert available_collection_datasets(["energy", "weather"], data_dir=tmp_path) == ["weather"]


def test_sgis_rejection_is_bound_to_both_credentials(monkeypatch, tmp_path):
    monkeypatch.setenv("SGIS_CONSUMER_KEY", "consumer-key")
    monkeypatch.setenv("SGIS_CONSUMER_SECRET", "rejected-secret")
    record_credential_error(
        tmp_path / "cache" / "sgis-auth",
        "consumer-key|rejected-secret",
        "SGIS 인증 실패: provider_code=-401",
    )

    assert collection_blockers(["sgis"], data_dir=tmp_path)[0]["dataset"] == "sgis"
    monkeypatch.setenv("SGIS_CONSUMER_SECRET", "replacement-secret")
    assert collection_blockers(["sgis"], data_dir=tmp_path) == []
