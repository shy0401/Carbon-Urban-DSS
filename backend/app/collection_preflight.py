"""Collection admission checks that avoid known-impossible provider calls."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

from .cache import recent_credential_error
from .settings import DATA_DIR


REQUIRED_ENV = {
    "energy": ("DATA_GO_KR_SERVICE_KEY",),
    "kapt_energy": ("DATA_GO_KR_SERVICE_KEY",),
    "kma_asos": ("DATA_GO_KR_SERVICE_KEY",),
    "sgis": ("SGIS_CONSUMER_KEY", "SGIS_CONSUMER_SECRET"),
    "vworld_zoning": ("VWORLD_API_KEY", "VWORLD_DOMAIN"),
    "vworld_cadastral": ("VWORLD_API_KEY", "VWORLD_DOMAIN"),
}

CREDENTIAL_CACHE = {
    "energy": (("DATA_GO_KR_SERVICE_KEY",), "cache"),
    "kapt_energy": (("DATA_GO_KR_SERVICE_KEY",), "cache/kapt-energy"),
    "kma_asos": (("DATA_GO_KR_SERVICE_KEY",), "cache/kma-asos"),
    "sgis": (("SGIS_CONSUMER_KEY", "SGIS_CONSUMER_SECRET"), "cache/sgis-auth"),
    "vworld_zoning": (("VWORLD_API_KEY",), "cache/vworld"),
    "vworld_cadastral": (("VWORLD_API_KEY",), "cache/vworld"),
}


# Values that are clearly not provider-issued keys (for example a Korean
# placeholder copied from a guide). Sending them only produces provider code 30
# and hides the real cause, so they are blocked before any request is made.
_PLACEHOLDER_MARKERS = ("your_", "your-", "_here", "-here", "changeme", "placeholder", "example", "xxxxxxxx", "<", ">")
_FORMAT_CHECKED = {"DATA_GO_KR_SERVICE_KEY", "SGIS_CONSUMER_KEY", "SGIS_CONSUMER_SECRET", "VWORLD_API_KEY"}


def credential_format_problem(name: str, value: str | None) -> str | None:
    """Return a value-free description of an obviously malformed credential."""
    value = (value or "").strip()
    if not value or name not in _FORMAT_CHECKED:
        return None
    if any(ord(char) > 127 for char in value):
        return "발급 키가 아닌 문자(한글 등 비ASCII)가 포함되어 자리표시자로 보입니다"
    if any(char.isspace() for char in value) or value[0] in "\"'" or value[-1] in "\"'":
        return "공백·줄바꿈·따옴표가 포함되어 있습니다"
    lowered = value.lower()
    if any(marker in lowered for marker in _PLACEHOLDER_MARKERS):
        return "예시 문구(자리표시자)로 보입니다"
    return None


def credential_format_problems(names: Iterable[str]) -> dict[str, str]:
    problems = {}
    for name in names:
        problem = credential_format_problem(name, os.getenv(name, ""))
        if problem:
            problems[name] = problem
    return problems


class CollectionBlockedError(RuntimeError):
    def __init__(self, blockers: list[dict[str, str]]):
        self.blockers = blockers
        detail = "수집을 시작할 수 없습니다. " + " / ".join(
            f"{item['dataset']}: {item['message']}" for item in blockers
        )
        super().__init__(detail)


def collection_blockers(datasets: Iterable[str], *, data_dir: str | Path | None = None) -> list[dict[str, str]]:
    root = Path(data_dir) if data_dir is not None else DATA_DIR
    blocked: list[dict[str, str]] = []
    for dataset in dict.fromkeys(datasets):
        required = REQUIRED_ENV.get(dataset, ())
        missing = [name for name in required if not os.getenv(name, "").strip()]
        if missing:
            blocked.append({"dataset": dataset, "message": "환경변수 미설정: " + ", ".join(missing)})
            continue
        malformed = credential_format_problems(required)
        if malformed:
            blocked.append({
                "dataset": dataset,
                "message": "환경변수 형식 오류: " + " / ".join(f"{name} — {problem}" for name, problem in malformed.items())
                + ". 공공데이터포털·기관에서 발급된 실제 키로 교체하세요.",
            })
            continue
        cache_config = CREDENTIAL_CACHE.get(dataset)
        if not cache_config:
            continue
        credential_names, cache_path = cache_config
        credential = "|".join(os.getenv(name, "").strip() for name in credential_names)
        match = None
        if dataset.startswith("vworld_"):
            # A VWorld rejection is tied to the key *and* the registered domain; fixing
            # VWORLD_DOMAIN must allow an immediate retry.
            domain = os.getenv("VWORLD_DOMAIN", "http://localhost").strip()
            match = lambda meta, domain=domain: (meta.get("params") or {}).get("domain", domain) == domain
        error = recent_credential_error(root / cache_path, credential, match=match)
        auth_markers = ("인증 실패", "INVALID_KEY", "SERVICE_KEY", "SERVICE_ACCESS", "30:", "20:")
        if error and any(marker in error for marker in auth_markers):
            credential_name = credential_names[0]
            provider = "공공데이터포털" if credential_name == "DATA_GO_KR_SERVICE_KEY" else ("SGIS" if credential_name == "SGIS_CONSUMER_KEY" else "VWorld")
            blocked.append({
                "dataset": dataset,
                "message": f"현재 {provider} 키가 공급자에게 거절되었습니다. 활용신청 승인 또는 키 교체 후 다시 시도하세요.",
            })
    return blocked


def ensure_collection_ready(datasets: Iterable[str], *, data_dir: str | Path | None = None) -> None:
    blocked = collection_blockers(datasets, data_dir=data_dir)
    if blocked:
        raise CollectionBlockedError(blocked)


def available_collection_datasets(datasets: Iterable[str], *, data_dir: str | Path | None = None) -> list[str]:
    requested = list(dict.fromkeys(datasets))
    blocked = {item["dataset"] for item in collection_blockers(requested, data_dir=data_dir)}
    return [dataset for dataset in requested if dataset not in blocked]
