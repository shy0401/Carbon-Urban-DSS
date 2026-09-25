"""Past-year back-fill for area history and before/after development analysis.

``collect_history`` loops the existing, verified collectors over several years.
It never invents rows: a year the provider does not publish stays empty, and every
(dataset, year) outcome is written to ``data/ops/history-progress.json`` so a run
that stops (daily quota, network, closed window) resumes where it left off.

Order per year: SGIS 행정통계 → KMA ASOS (ERA5-Land only if ASOS fails) → K-apt
monthly energy (smoke, then full, skipping months before each complex's 사용승인일)
→ 건축HUB 지번 에너지. Once per run: VWorld 공식 건물·연속지적 (current snapshot).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

YEARLY = ("sgis", "kma_asos", "kapt_energy", "energy")
ONCE = ("vworld_buildings", "vworld_cadastral")
ALL_DATASETS = YEARLY + ONCE

AUTH_MARKERS = ("인증 실패", "미설정", "형식 오류", "INCORRECT_KEY", "활용 승인")
QUOTA_MARKERS = ("한도 초과", "호출 제한", "(22)", "LIMITED_NUMBER")


def classify_error(message: str) -> str:
    """AUTH stops the dataset for the whole run, QUOTA stops it until tomorrow, anything else is per-year."""
    if any(marker in message for marker in QUOTA_MARKERS):
        return "QUOTA"
    if any(marker in message for marker in AUTH_MARKERS):
        return "AUTH"
    return "ERROR"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Progress:
    """Resumable per (dataset, year) status file. Values never contain credentials."""

    def __init__(self, path: Path):
        self.path = path
        self.state: dict[str, Any] = {"runs": [], "items": {}}
        if path.exists():
            try:
                self.state = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
        self.state.setdefault("items", {})
        self.state.setdefault("runs", [])

    def key(self, dataset: str, year: int | None) -> str:
        return f"{dataset}:{year}" if year is not None else dataset

    def done(self, dataset: str, year: int | None) -> bool:
        return self.state["items"].get(self.key(dataset, year), {}).get("status") in {"DONE", "NOT_PUBLISHED"}

    def set(self, dataset: str, year: int | None, status: str, **detail: Any) -> None:
        self.state["items"][self.key(dataset, year)] = {"status": status, "at": _now(), **detail}
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)


def _default_runners(db: Any) -> dict[str, Callable[..., dict[str, Any]]]:
    """Adapters around the production collectors (imported lazily so tests can inject fakes)."""

    def sgis(year: int) -> dict[str, Any]:
        from .sgis import collect_sgis_admin
        result = collect_sgis_admin(db, year, "full")
        # SGIS falls back to an older published year when the requested one is not out yet.
        if result.get("reference_year") != year:
            return {"status": "NOT_PUBLISHED", "reference_year": result.get("reference_year")}
        return {"status": "DONE", **{k: result.get(k) for k in ("dong_population_rows", "dong_household_rows", "boundaries")}}

    def kma_asos(year: int) -> dict[str, Any]:
        from .kma_asos import collect_asos
        try:
            return {"status": "DONE", **collect_asos(db, year, "full")}
        except Exception as exc:
            if classify_error(str(exc)) != "ERROR":
                raise
            # Official observation unavailable for this year: keep the reanalysis fallback, labelled FALLBACK.
            from .collectors import collect_weather
            collect_weather(db, f"{year}-01", f"{year}-12")
            return {"status": "DONE", "fallback": "ERA5-Land", "reason": str(exc)[:160]}

    def kapt_energy(year: int) -> dict[str, Any]:
        from .kapt_energy import collect_kapt_energy
        smoke = collect_kapt_energy(db, year, "smoke", history=True)
        if smoke.get("empty") and not (smoke.get("normalized") or smoke.get("not_reported") or smoke.get("suspect")):
            # The reference complex answered with no data for January: treat the year as not published
            # instead of spending thousands of calls on empty answers. A later run can still retry with --force.
            return {"status": "NOT_PUBLISHED", "probe": smoke}
        full = collect_kapt_energy(db, year, "full", history=True)
        status = "DONE" if not full.get("failed") else "PARTIAL"
        return {"status": status, **full}

    def energy(year: int) -> dict[str, Any]:
        from .collectors import collect_energy
        from .kapt import merge_energy_coordinates
        errors = collect_energy(db, f"{year}-01", f"{year}-12", None, "full")
        merged = merge_energy_coordinates(db, year)
        return {"status": "PARTIAL" if errors else "DONE", "errors": len(errors or []), "merged": merged}

    def vworld(dataset: str) -> Callable[[], dict[str, Any]]:
        def run() -> dict[str, Any]:
            from .vworld import collect_vworld
            collect_vworld(db, dataset, "smoke")
            previous = os.environ.get("VWORLD_CADASTRAL_FULL")
            if dataset == "cadastral":
                os.environ["VWORLD_CADASTRAL_FULL"] = "true"
            try:
                result = collect_vworld(db, dataset, "full")
            finally:
                if dataset == "cadastral":
                    if previous is None:
                        os.environ.pop("VWORLD_CADASTRAL_FULL", None)
                    else:
                        os.environ["VWORLD_CADASTRAL_FULL"] = previous
            return {"status": "DONE", **(result or {})}
        return run

    return {
        "sgis": sgis, "kma_asos": kma_asos, "kapt_energy": kapt_energy, "energy": energy,
        "vworld_buildings": vworld("buildings"), "vworld_cadastral": vworld("cadastral"),
    }


def collect_history(
    db: Any, start_year: int, end_year: int, *, datasets: list[str] | None = None,
    data_dir: str | Path | None = None, force: bool = False,
    runners: dict[str, Callable[..., dict[str, Any]]] | None = None,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Back-fill ``start_year..end_year`` (inclusive) and return the per-item outcome."""
    if start_year > end_year:
        raise ValueError("start_year must not be after end_year")
    chosen = [d for d in ALL_DATASETS if datasets is None or d in datasets]
    unknown = sorted(set(datasets or []) - set(ALL_DATASETS))
    if unknown:
        raise ValueError(f"지원하지 않는 데이터셋: {', '.join(unknown)}")
    root = Path(data_dir or os.getenv("DATA_DIR", "data"))
    progress = Progress(root / "ops" / "history-progress.json")
    run = {"started_at": _now(), "from": start_year, "to": end_year, "datasets": chosen}
    progress.state["runs"] = (progress.state["runs"] + [run])[-20:]
    progress.save()
    runner = runners or _default_runners(db)
    blocked: dict[str, str] = {}

    def attempt(dataset: str, year: int | None) -> None:
        if dataset in blocked:
            progress.set(dataset, year, "BLOCKED", reason=blocked[dataset])
            return
        if not force and progress.done(dataset, year):
            log(f"skip {progress.key(dataset, year)} (이미 완료)")
            return
        log(f"start {progress.key(dataset, year)}")
        try:
            outcome = runner[dataset](year) if year is not None else runner[dataset]()
            status = outcome.pop("status", "DONE")
            progress.set(dataset, year, status, **_safe(outcome))
            log(f"{status} {progress.key(dataset, year)}")
        except Exception as exc:  # noqa: BLE001 - every provider failure is recorded, never raised past the loop
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass
            message = str(exc)[:300] if type(exc).__name__ in {"ExternalError", "ValueError", "TransientProviderError"} else f"처리 실패: {type(exc).__name__}"
            kind = classify_error(message)
            progress.set(dataset, year, "FAILED", kind=kind, reason=message)
            log(f"FAILED {progress.key(dataset, year)} {kind}: {message}")
            if kind in {"AUTH", "QUOTA"}:
                blocked[dataset] = message

    # Oldest first so the newest year is written last (sources keep the latest reference period).
    for year in range(start_year, end_year + 1):
        for dataset in chosen:
            if dataset in YEARLY:
                attempt(dataset, year)
    for dataset in chosen:
        if dataset in ONCE:
            attempt(dataset, None)
    run["finished_at"] = _now()
    run["blocked"] = blocked
    progress.save()
    return {"items": progress.state["items"], "blocked": blocked}


def _safe(detail: dict[str, Any]) -> dict[str, Any]:
    """Keep only JSON-friendly scalar or small values in the progress file."""
    out: dict[str, Any] = {}
    for key, value in detail.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            out[key] = value if not isinstance(value, str) else value[:200]
        elif isinstance(value, dict):
            out[key] = {k: v for k, v in value.items() if isinstance(v, (str, int, float, bool)) or v is None}
    return out


def history_status(data_dir: str | Path | None = None) -> dict[str, Any]:
    """Read-only view of the back-fill progress for the collection screen."""
    root = Path(data_dir or os.getenv("DATA_DIR", "data"))
    path = root / "ops" / "history-progress.json"
    if not path.exists():
        return {"items": {}, "runs": [], "summary": {}}
    state = Progress(path).state
    summary: dict[str, dict[str, int]] = {}
    for key, item in state["items"].items():
        dataset = key.split(":")[0]
        bucket = summary.setdefault(dataset, {})
        bucket[item.get("status", "UNKNOWN")] = bucket.get(item.get("status", "UNKNOWN"), 0) + 1
    return {"items": state["items"], "runs": state["runs"][-5:], "summary": summary}
