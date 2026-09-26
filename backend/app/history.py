"""Collect everything that is still missing: past years and never-collected layers.

``collect_history`` (also ``collect_missing``) loops the existing, verified collectors. It
never invents rows: a year the provider does not publish stays empty, and every
(dataset, year) outcome is written to ``data/ops/history-progress.json`` so a run that stops
(daily quota, network, closed window) resumes where it left off.

Per year: SGIS 행정통계 → KMA ASOS (ERA5-Land only if ASOS fails) → K-apt monthly energy
(smoke, then full, skipping months before each complex's 사용승인일) → 건축HUB 지번 에너지.
Once per run (current snapshot): VWorld 용도지역 → 도로명주소 건물 → 연속지적 → 건축물대장 표제부.

Before calling a provider it checks, without any request:
- the DB already holds the item (e.g. 12 official ASOS months for that year) → DONE;
- the credential is missing, malformed or recently rejected → BLOCKED with the reason.
Datasets that need a file from the provider (SGIS 500m grid, gas factors …) are listed as MANUAL.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

YEARLY = ("sgis", "kma_asos", "kapt_energy", "energy")
ONCE = ("vworld_zoning", "vworld_buildings", "vworld_cadastral", "building_register")
SLOW = ("kapt_energy",)
KAPT_RETRY_ROUNDS = int(os.getenv("KAPT_RETRY_ROUNDS", "2"))
KAPT_RETRY_WAIT_S = float(os.getenv("KAPT_RETRY_WAIT_S", "600"))
KAPT_OUTAGE_PAUSE_S = float(os.getenv("KAPT_OUTAGE_PAUSE_S", "180"))
ENERGY_SCOPE = "all_parcels"  # 건축HUB by 법정동 (every parcel); earlier per-apartment-parcel runs are redone once  # one request per complex-month: collected after everything else
ALL_DATASETS = YEARLY + ONCE

LABELS = {
    "sgis": "SGIS 행정동 인구·가구·경계",
    "kma_asos": "기상청 ASOS 전주 (없으면 ERA5-Land)",
    "kapt_energy": "K-apt 단지 월별 에너지",
    "energy": "건축HUB 전 지번 월별 전력·가스",
    "vworld_zoning": "VWorld 용도지역",
    "vworld_buildings": "VWorld 도로명주소 건물",
    "vworld_cadastral": "VWorld 연속지적 (전체 필지)",
    "building_register": "건축물대장 표제부 (연면적·구조·사용승인일·에너지등급)",
}
SOURCE_ID = {"sgis": "sgis_admin", "kma_asos": "weather_kma", "building_register": "building_official"}

# Things no API call can fetch: the provider hands out a file after an application.
MANUAL_SOURCES = (
    {"id": "sgis_grid", "label": "SGIS 공식 500m 격자 (경계·인구·비밀보호 표식)",
     "why": "1km 격자 통계(2024)는 공공데이터포털 파일로 적용되어 있습니다. 500m 격자 값이 필요하면 SGIS에 따로 신청해야 합니다(500m는 총괄 항목만 제공).",
     "how": "SGIS 자료제공 → 격자 통계(500m) 신청 → 받은 SHP/CSV를 '파일 업로드'로 가져오기",
     "link": "https://sgis.kostat.go.kr/view/pss/openDataIntrcn"},
    {"id": "factors_gas", "label": "가스 배출계수·열량 기준 (CO₂·CH₄·N₂O, GWP)",
     "why": "가스 탄소를 계산에 넣으려면 공식 계수와 kWh 환산 기준이 필요합니다.",
     "how": "온실가스종합정보센터 국가 고유 배출계수 확인 → 값·단위·적용연도를 근거와 함께 등록",
     "link": "https://www.gir.go.kr/"},
    {"id": "factors_yearly", "label": "연도별 전력 배출계수 (2015~2024)",
     "why": "지금은 최신 계수 하나를 모든 연도에 씁니다. 연도별로 비교하려면 해마다의 공식 계수가 필요합니다.",
     "how": "온실가스종합정보센터 공표 전력 배출계수(연도별) 확인 → 등록",
     "link": "https://www.gir.go.kr/"},
    {"id": "grid_100m", "label": "선도소프트 100m 탄소격자",
     "why": "기업 격자와 500m 분석 결과를 비교하려면 원본·산정식·이용조건이 필요합니다.",
     "how": "선도소프트에 원본(CRS·단위·포함 부문 포함) 요청 → '파일 업로드'",
     "link": None},
)

AUTH_MARKERS = ("인증 실패", "미설정", "형식 오류", "INCORRECT_KEY", "활용 승인", "활용신청", "거절")
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


def next_quota_reset(now: datetime | None = None) -> datetime:
    """data.go.kr counts per KST day. Resume 20 minutes after the next KST midnight (returned in UTC)."""
    kst = timezone(timedelta(hours=9))
    local = (now or datetime.now(timezone.utc)).astimezone(kst)
    reset = (local + timedelta(days=1)).replace(hour=0, minute=20, second=0, microsecond=0)
    return reset.astimezone(timezone.utc)


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

    def status(self, dataset: str, year: int | None) -> str | None:
        return self.state["items"].get(self.key(dataset, year), {}).get("status")

    def done(self, dataset: str, year: int | None) -> bool:
        return self.status(dataset, year) in {"DONE", "NOT_PUBLISHED"}

    def set(self, dataset: str, year: int | None, status: str, **detail: Any) -> None:
        self.state["items"][self.key(dataset, year)] = {"status": status, "at": _now(), **detail}
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)


def _progress_path(data_dir: str | Path | None) -> Path:
    return Path(data_dir or os.getenv("DATA_DIR", "data")) / "ops" / "history-progress.json"


def _default_runners(db: Any, hooks: dict[str, Any] | None = None) -> dict[str, Callable[..., dict[str, Any]]]:
    """Adapters around the production collectors (imported lazily so tests can inject fakes).

    ``hooks['progress']`` (set per item by collect_history) receives (fraction, message) from inside a
    long item, so the web page shows e.g. which parcel of a year is being requested.
    """
    hooks = hooks if hooks is not None else {}

    def report(fraction: float, message: str) -> None:
        callback = hooks.get("progress")
        if callback:
            try:
                callback(fraction, message)
            except Exception:  # noqa: BLE001 - progress display must never stop a collection
                pass

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
        # The gateway's "04 HTTP_ERROR" comes in bursts: pause on a run of failures and ask again for
        # the months still failing after the pass (the waits keep the daily quota for real answers).
        full = collect_kapt_energy(db, year, "full", history=True, progress=report,
                                   retry_rounds=KAPT_RETRY_ROUNDS, retry_wait_s=KAPT_RETRY_WAIT_S, outage_pause_s=KAPT_OUTAGE_PAUSE_S)
        # Months still answering "04" after the retries are left FAILED (a later run asks again).
        # Only other failures (network, 5xx) leave the year PARTIAL.
        other_failures = full.get("failed", 0) - full.get("provider_gaps", 0) - full.get("skipped_after_errors", 0)
        status = "DONE" if other_failures <= 0 else "PARTIAL"
        return {"status": status, **full}

    def energy(year: int) -> dict[str, Any]:
        from sqlalchemy import func, select
        from .collectors import update_source
        from .energy_parcels import HUB, ParcelGrid, build_parcel_grid, collect_energy_all, probe_year
        from .kapt import merge_energy_coordinates
        from .models import EnergyMonthly

        def rows(ym_from: str, ym_to: str) -> int:
            return db.scalar(select(func.count()).select_from(EnergyMonthly).where(
                EnergyMonthly.source == HUB, EnergyMonthly.use_ym.between(ym_from, ym_to))) or 0

        if rows(f"{year}01", f"{year}12") < 1000 and not probe_year(db, year):
            # 2 requests (one busy 법정동, July): 건축HUB has no data before 2024.
            return {"status": "NOT_PUBLISHED", "scope": ENERGY_SCOPE, "probe": "건축HUB 법정동 7월 응답 없음"}
        stats = collect_energy_all(db, year, report)
        merged = merge_energy_coordinates(db, year)
        linked = db.scalar(select(func.count()).select_from(ParcelGrid)) or build_parcel_grid(db)
        total = db.scalar(select(func.count()).select_from(EnergyMonthly)) or 0
        parcels = db.scalar(select(func.count(func.distinct(EnergyMonthly.sigungu_code + EnergyMonthly.bjdong_code + EnergyMonthly.lot_type + EnergyMonthly.bun + EnergyMonthly.ji))).where(EnergyMonthly.source == HUB)) or 0
        update_source(db, "energy", total, status="COLLECTED",
                      quality=f"{total:,} 관측 / 건축HUB 전 지번 {parcels:,}곳(법정동 단위 수집) / 공동주택 K-apt 매칭 {merged.get('matched', 0):,}행")
        return {"status": "DONE", "scope": ENERGY_SCOPE, **stats, "merged": merged, "parcel_grid": linked, "rows": rows(f"{year}01", f"{year}12")}

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
            return {"status": "DONE", **(result if isinstance(result, dict) else {})}
        return run

    def building_register() -> dict[str, Any]:
        from .official import collect_register
        collect_register(db, "smoke")
        result = collect_register(db, "full", report)
        return {"status": "PARTIAL" if result.get("failed") else "DONE", **result}

    return {
        "sgis": sgis, "kma_asos": kma_asos, "kapt_energy": kapt_energy, "energy": energy,
        "vworld_zoning": vworld("zoning"), "vworld_buildings": vworld("buildings"),
        "vworld_cadastral": vworld("cadastral"), "building_register": building_register,
    }


def db_satisfied(db: Any, dataset: str, year: int | None) -> str | None:
    """Reason the DB already holds this item (no request needed), or None. Never raises."""
    try:
        from sqlalchemy import func, select
        from .models import DataSource, WeatherMonthly
        if dataset == "sgis" and year is not None:
            from .sgis import SgisPopulationAdmin
            n = db.scalar(select(func.count()).select_from(SgisPopulationAdmin).where(SgisPopulationAdmin.reference_year == year)) or 0
            return f"{year}년 행정동 인구 {n}행 보유" if n else None
        if dataset == "kma_asos" and year is not None:
            rows = db.scalars(select(WeatherMonthly).where(WeatherMonthly.use_ym.like(f"{year}%"), WeatherMonthly.source_type == "OFFICIAL")).all()
            full = [r for r in rows if (r.days_observed or 0) >= (r.expected_days or 99)]
            return f"{year}년 ASOS 완전월 12개 보유" if len(full) >= 12 else None
        if dataset in ONCE:
            source = db.get(DataSource, SOURCE_ID.get(dataset, dataset))
            if source and source.status == "COLLECTED" and (source.normalized_row_count or 0) > 0:
                return f"전체 범위 수집 완료 ({source.normalized_row_count:,}행)"
        return None
    except Exception:  # noqa: BLE001 - a missing optional table simply means "not collected yet"
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        return None


def credential_blockers(datasets: list[str], data_dir: str | Path | None = None) -> dict[str, str]:
    """dataset → value-free reason when its key is missing, malformed or recently rejected."""
    from .collection_preflight import collection_blockers
    return {item["dataset"]: item["message"] for item in collection_blockers(datasets, data_dir=data_dir)}


LOCK_NAME = "carbon:collect-missing"
LOCK_TTL = 20 * 60  # the guard lives only while a run keeps renewing it (see _keep_lock)


def _lock(name: str = LOCK_NAME):
    """Cross-process guard so the web button and the PC command never run at the same time.

    The lock expires LOCK_TTL seconds after the last renewal, so a run killed with its worker
    (rebuild, restart) frees it by itself; ``lock_held`` then tells the job is gone.
    """
    try:
        import redis
        connection = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"))
        # thread_local=False: the keep-alive thread must be able to renew this token.
        lock = connection.lock(name, timeout=LOCK_TTL, blocking_timeout=1, thread_local=False)
        if not lock.acquire(blocking=True):
            raise RuntimeError("다른 '빠진 자료 수집'이 이미 실행 중입니다")
        return lock
    except RuntimeError:
        raise
    except Exception:  # noqa: BLE001 - no Redis (tests, single process): no cross-process guard needed
        return None


def _keep_lock(lock: Any, stop: threading.Event, every: float = LOCK_TTL / 4) -> None:
    """Renew the guard while the run is alive (one provider call can take many minutes)."""
    while not stop.wait(every):
        try:
            lock.reacquire()
        except Exception:  # noqa: BLE001 - lost to expiry; the run keeps going
            pass


def lock_held(name: str = LOCK_NAME) -> bool | None:
    """Whether a 'collect everything missing' run is alive; None when Redis is unavailable."""
    try:
        import redis
        return bool(redis.Redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0")).exists(name))
    except Exception:  # noqa: BLE001
        return None


def collect_history(
    db: Any, start_year: int, end_year: int, *, datasets: list[str] | None = None,
    data_dir: str | Path | None = None, force: bool = False,
    runners: dict[str, Callable[..., dict[str, Any]]] | None = None,
    log: Callable[[str], None] = print, progress: Callable[[float, str], None] | None = None,
    check_db: bool | None = None, blockers: dict[str, str] | None = None, use_lock: bool | None = None,
) -> dict[str, Any]:
    """Collect ``start_year..end_year`` (inclusive) plus the snapshot layers; return the per-item outcome.

    With injected ``runners`` (tests) the DB check, credential check and lock are off unless asked for.
    """
    if start_year > end_year:
        raise ValueError("start_year must not be after end_year")
    unknown = sorted(set(datasets or []) - set(ALL_DATASETS))
    if unknown:
        raise ValueError(f"지원하지 않는 데이터셋: {', '.join(unknown)}")
    hooks: dict[str, Any] = {}
    runner = runners or _default_runners(db, hooks)
    chosen = [d for d in ALL_DATASETS if (datasets is None or d in datasets) and d in runner]
    live = runners is None
    check_db = live if check_db is None else check_db
    lock = _lock() if (live if use_lock is None else use_lock) else None
    stop_keeper = threading.Event()
    if lock is not None:
        threading.Thread(target=_keep_lock, args=(lock, stop_keeper), daemon=True).start()
    if blockers is None:
        try:
            blockers = credential_blockers(chosen, data_dir) if live else {}
        except Exception:
            stop_keeper.set()
            if lock is not None:
                try:
                    lock.release()
                except Exception:  # noqa: BLE001
                    pass
            raise
    progress_file = Progress(_progress_path(data_dir))
    run = {"started_at": _now(), "from": start_year, "to": end_year, "datasets": chosen}
    progress_file.state["runs"] = (progress_file.state["runs"] + [run])[-20:]
    progress_file.save()
    blocked: dict[str, str] = dict(blockers)
    quota: dict[str, str] = {}
    years = list(range(start_year, end_year + 1))
    # Newest year first (most useful, most likely published). K-apt runs last: it needs one call per
    # complex-month and a small daily quota, so it must not hold back the cheaper sources.
    newest = sorted(years, reverse=True)
    plan = ([(d, y) for y in newest for d in chosen if d in YEARLY and d not in SLOW]
            + [(d, None) for d in chosen if d in ONCE]
            + [(d, y) for d in chosen if d in SLOW for y in newest])
    try:
        for step, (dataset, year) in enumerate(plan):
            key = progress_file.key(dataset, year)
            if lock is not None:
                try:
                    lock.reacquire()  # keep the guard alive for the whole (possibly many-hour) run
                except Exception:  # noqa: BLE001
                    pass
            if progress:
                progress(step / max(1, len(plan)), f"{LABELS.get(dataset, dataset)}{f' {year}년' if year else ''} ({step + 1}/{len(plan)})")
            if dataset in blocked:
                kind = "QUOTA" if dataset in quota else "AUTH"
                progress_file.set(dataset, year, "BLOCKED", kind=kind, reason=blocked[dataset][:200])
                continue
            redo_energy = dataset == "energy" and progress_file.state["items"].get(key, {}).get("scope") != ENERGY_SCOPE
            if not force and progress_file.done(dataset, year) and not redo_energy:
                log(f"skip {key} (이미 완료)")
                continue
            reason = db_satisfied(db, dataset, year) if (check_db and not force) else None
            if reason:
                progress_file.set(dataset, year, "DONE", reason=reason, requests=0)
                log(f"skip {key} ({reason})")
                continue
            log(f"start {key}")
            if progress:
                label = f"{LABELS.get(dataset, dataset)}{f' {year}년' if year else ''} ({step + 1}/{len(plan)})"
                hooks["progress"] = lambda fraction, message, step=step, label=label: progress(
                    (step + max(0.0, min(1.0, fraction))) / max(1, len(plan)), f"{label} · {message}")
            try:
                outcome = runner[dataset](year) if year is not None else runner[dataset]()
                status = outcome.pop("status", "DONE")
                progress_file.set(dataset, year, status, **_safe(outcome))
                log(f"{status} {key}")
            except Exception as exc:  # noqa: BLE001 - every provider failure is recorded, never raised past the loop
                try:
                    db.rollback()
                except Exception:  # noqa: BLE001
                    pass
                message = str(exc)[:300] if type(exc).__name__ in {"ExternalError", "ValueError", "TransientProviderError", "CollectionBlockedError"} else f"처리 실패: {type(exc).__name__}"
                kind = classify_error(message)
                progress_file.set(dataset, year, "FAILED", kind=kind, reason=message)
                log(f"FAILED {key} {kind}: {message}")
                if kind in {"AUTH", "QUOTA"}:
                    blocked[dataset] = message
                    if kind == "QUOTA":
                        quota[dataset] = message
    finally:
        stop_keeper.set()
        if lock is not None:
            try:
                lock.release()
            except Exception:  # noqa: BLE001
                pass
    run["finished_at"] = _now()
    run["blocked"] = blocked
    progress_file.save()
    if progress:
        progress(1.0, "완료")
    return {"items": progress_file.state["items"], "blocked": blocked, "quota": quota,
            "resume_at": next_quota_reset().isoformat() if quota else None}


collect_missing = collect_history


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
    path = _progress_path(data_dir)
    if not path.exists():
        return {"items": {}, "runs": [], "summary": {}}
    state = Progress(path).state
    summary: dict[str, dict[str, int]] = {}
    for key, item in state["items"].items():
        dataset = key.split(":")[0]
        bucket = summary.setdefault(dataset, {})
        bucket[item.get("status", "UNKNOWN")] = bucket.get(item.get("status", "UNKNOWN"), 0) + 1
    return {"items": state["items"], "runs": state["runs"][-5:], "summary": summary}


def plan_missing(db: Any, start_year: int, end_year: int, *, data_dir: str | Path | None = None,
                 blockers: dict[str, str] | None = None, check_db: bool = True) -> dict[str, Any]:
    """What a run would do now, without any provider request (for the collection screen)."""
    progress_file = Progress(_progress_path(data_dir))
    if blockers is None:
        blockers = credential_blockers(list(ALL_DATASETS), data_dir)
    years = list(range(start_year, end_year + 1))
    rows: list[dict[str, Any]] = []
    for dataset in ALL_DATASETS:
        cells = []
        for year in (years if dataset in YEARLY else [None]):
            recorded = progress_file.state["items"].get(progress_file.key(dataset, year), {})
            status = recorded.get("status")
            reason = recorded.get("reason")
            have = None if status in {"DONE", "NOT_PUBLISHED"} or not check_db else db_satisfied(db, dataset, year)
            if status in {"DONE", "NOT_PUBLISHED"}:
                state = status
            elif have:
                state, reason = "DONE", have
            elif dataset in blockers:
                state, reason = "BLOCKED", blockers[dataset]
            elif status in {"FAILED", "PARTIAL"}:
                state = "RETRY"
            else:
                state = "TODO"
            cells.append({"year": year, "state": state, "reason": (reason or "")[:200] or None, "at": recorded.get("at")})
        rows.append({"dataset": dataset, "label": LABELS[dataset], "yearly": dataset in YEARLY, "cells": cells,
                     "blocked": blockers.get(dataset)})
    counts: dict[str, int] = {}
    for row in rows:
        for cell in row["cells"]:
            counts[cell["state"]] = counts.get(cell["state"], 0) + 1
    return {
        "years": years, "rows": rows, "manual": list(MANUAL_SOURCES),
        "summary": {"todo": counts.get("TODO", 0) + counts.get("RETRY", 0), "done": counts.get("DONE", 0) + counts.get("NOT_PUBLISHED", 0),
                    "blocked": counts.get("BLOCKED", 0), "manual": len(MANUAL_SOURCES), "states": counts},
        "last_run": (progress_file.state.get("runs") or [None])[-1],
    }
