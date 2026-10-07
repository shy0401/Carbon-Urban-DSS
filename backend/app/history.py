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
ONCE = ("vworld_zoning", "vworld_buildings", "vworld_cadastral", "building_register", "sgis_grid_500m")
SLOW = ("kapt_energy",)
KAPT_RETRY_ROUNDS = int(os.getenv("KAPT_RETRY_ROUNDS", "2"))
KAPT_RETRY_WAIT_S = float(os.getenv("KAPT_RETRY_WAIT_S", "600"))
KAPT_OUTAGE_PAUSE_S = float(os.getenv("KAPT_OUTAGE_PAUSE_S", "180"))
# A year with more than this share of months still failing goes back in the queue (at most
# KAPT_MAX_PASSES passes in all); the job then waits KAPT_PROVIDER_RETRY_H hours and resumes.
KAPT_GAP_TOLERANCE = float(os.getenv("KAPT_GAP_TOLERANCE", "0.05"))
KAPT_MAX_PASSES = int(os.getenv("KAPT_MAX_PASSES", "3"))
KAPT_PROVIDER_RETRY_H = float(os.getenv("KAPT_PROVIDER_RETRY_H", "2"))
ENERGY_SCOPE = "all_parcels"  # 건축HUB by 법정동 (every parcel); earlier per-apartment-parcel runs are redone once  # one request per complex-month: collected after everything else
ENERGY_PROBE_VERSION = 2  # 2: 전북 months up to 2023-10 are asked with the old 45xxx code (energy_parcels.request_sigungu)
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
    "sgis_grid_500m": "SGIS 공식 500m 격자 경계·코드 (API)",
}
SOURCE_ID = {"sgis": "sgis_admin", "kma_asos": "weather_kma", "building_register": "building_official", "sgis_grid_500m": "sgis_grid"}

# Things no API call can fetch: the provider hands out a file after an application.
SGIS_REQUEST_URL = "https://sgis.mods.go.kr/view/pss/dataProvdIntrcn"

MANUAL_SOURCES = (
    {"id": "sgis_grid", "label": "SGIS 공식 500m 격자 통계값 (인구·가구 총괄)",
     "why": "500m 격자의 경계·코드는 SGIS API로 자동 수집합니다(위 표). 1km 격자 통계(2024)는 공공데이터포털 파일로 적용되어 있습니다. 500m 격자의 통계값은 공개 API·파일에 없어 SGIS에 자료제공을 신청해야 합니다(500m는 총괄 항목만 제공).",
     "how": "SGIS 자료제공 → 격자 통계(500m) 신청 (항목: 인구·가구·주택·사업체·종사자 총괄, 연도: 2015~2024) → 받은 CSV를 data/raw/sgis_grid_500m에 풀기 → 'python -m app.cli import-sgis-grid500' (API 시작 때도 자동으로 읽음)",
     "link": SGIS_REQUEST_URL},
    {"id": "factors_gas", "label": "가스 배출계수·열량 기준 (CO₂·CH₄·N₂O, GWP)",
     "why": "건축HUB 가스 사용량은 kWh로 오지만(공공데이터포털 15135963) 총발열량·순발열량 중 어느 기준으로 환산했는지 공개 페이지에 없습니다. 온실가스 지침은 순발열량 × 56,100 kgCO₂/TJ를 쓰므로, 기준에 따라 kWh당 계수가 약 0.182(총발열량 환산) 또는 0.202(순발열량 환산) kgCO₂로 10.9% 달라집니다. K-apt 가스는 단지 공용분(㎥)만 보고되는 경우가 많아 두 자료를 맞대어 기준을 추정할 수도 없었습니다(2026-09-27, 대조 가능 56쌍, 비율 불안정).",
     "how": "건축HUB 'OpenAPI활용가이드_건축HUB_건물에너지_1.0.hwp'의 환산 기준 확인 또는 한국부동산원 문의 → 온실가스종합정보센터 최신 국가 고유 배출계수(도시가스 LNG, CH₄·N₂O 포함)와 함께 값·단위·기준을 등록",
     "link": "https://www.data.go.kr/data/15135963/openapi.do"},
    {"id": "factors_yearly", "label": "연도별 전력 배출계수 (2015~2024)",
     "why": "지금은 최신 계수 하나를 모든 연도에 씁니다. 연도별로 비교하려면 해마다의 공식 계수가 필요합니다.",
     "how": "온실가스종합정보센터 공표 전력 배출계수(연도별) 확인 → 등록",
     "link": "https://www.gir.go.kr/"},
    # 전국·시·군·구 분석으로 넓히는 데 필요한 자료 (2026-09-29 검토, docs/NATIONWIDE_DATA.md)
    {"id": "kepco_sigungu", "label": "한전 시군구별 전력사용량 (전국 시·군·구)",
     "why": "지금 전력 관측은 상세 자료를 모은 시·군·구(전주·수원의 건축HUB·K-apt)에만 있어, 전국 시·군·구의 전력·전력 탄소를 비교할 수 없습니다. 한전 파일은 전국 시·군·구 단위라 전국 지도에 전력·탄소 지표를 더할 수 있습니다.",
     "how": "한전 홈페이지 '전력판매량(시군구별)' 게시판에서 월별 엑셀 내려받기(내려받기 전 이용 목적 설문을 한 번 답해야 함) → data/raw/kepco/에 두기 (받은 파일의 열 구성에 맞춰 가져오기를 추가)",
     "link": "https://www.kepco.co.kr/home/customer/library/electricity-statistics/sales-volume/boardList.do"},
    {"id": "gas_sido", "label": "시·도별 도시가스 판매량 (한국가스공사, 월별)",
     "why": "도시가스 사용량은 전국 시·군·구 단위 공개 통계를 찾지 못했습니다(서울시만 구별 통계). 시·도 단위 판매량으로 가스 탄소의 시·도 총량을 비교할 수 있습니다.",
     "how": "공공데이터포털 '한국가스공사_월별 시도별 도시가스 판매현황' 파일 내려받기 → data/raw/gas/",
     "link": "https://www.data.go.kr/data/15040819/fileData.do"},
    {"id": "building_energy_bulk", "label": "건물에너지 전국 파일 (전기·가스, 국토교통부)",
     "why": "건축HUB 건물에너지 API는 법정동마다 호출해야 하고 일일 한도가 있어, 시·군·구 하나에 몇 시간~며칠 걸립니다. 전국 파일(또는 건축데이터 민간개방 대용량 제공)을 받으면 한도 없이 어느 시·군·구든 건물 에너지를 붙일 수 있습니다.",
     "how": "공공데이터포털 '국토교통부_건물에너지 전기에너지'·'가스에너지' 파일 또는 건축데이터 민간개방 시스템 대용량 제공 신청 → data/raw/building_energy/",
     "link": "https://www.data.go.kr/data/15054214/fileData.do"},
    {"id": "building_gis_bulk", "label": "GIS건물통합정보·연속지적·용도지역 전국 파일",
     "why": "건물 윤곽·층수, 필지, 용도지역은 지금 VWorld API를 1km 타일마다 불러 시·군·구 하나씩 모읍니다(수원 157개 타일, 요청 수백 회). 시·도별 파일을 받으면 전국 어디든 상세 지도를 호출 없이 만들 수 있습니다.",
     "how": "공공데이터포털 '국토교통부_GIS건물통합정보'(15083092), '국토교통부_연속지적_전국'(15125044), 국가공간정보포털 오픈마켓 '(연속주제)_국토/용도지역' SHP → data/raw/gis/",
     "link": "https://www.data.go.kr/data/15083092/fileData.do"},
    {"id": "gir_regional", "label": "지역 온실가스 배출량 (온실가스종합정보센터)",
     "why": "격자 합계로 추정한 탄소를 공식 지역 인벤토리와 맞대어 검증할 기준입니다. 시·도(광역) 배출량은 공표되고, 시·군·구(기초) 단위 공개 범위는 확인이 필요합니다.",
     "how": "온실가스종합정보센터 '국가·지역 온실가스 통계'에서 지역별 배출량 파일 내려받기 → data/raw/research/",
     "link": "https://www.gir.go.kr/home/index.do?menuId=36"},
    {"id": "kapt_quota", "label": "K-apt 에너지 API 호출 한도 상향 (운영계정)",
     "why": "K-apt 월별 에너지는 단지·월마다 한 번씩 불러 일일 한도에 자주 걸립니다(전국 단지 약 2.25만 곳). 한도를 올리면 여러 시·군·구의 공동주택 에너지를 며칠 안에 모을 수 있습니다.",
     "how": "공공데이터포털 마이페이지 → 해당 API 활용신청 → 운영계정(트래픽 증가) 신청 (활용 사례 필요)",
     "link": "https://www.data.go.kr/data/15012964/openapi.do"},
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
                self.state = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError):
                pass
        self.state.setdefault("items", {})
        self.state.setdefault("runs", [])

    def key(self, dataset: str, year: int | None) -> str:
        return f"{dataset}:{year}" if year is not None else dataset

    def status(self, dataset: str, year: int | None) -> str | None:
        return self.state["items"].get(self.key(dataset, year), {}).get("status")

    def done(self, dataset: str, year: int | None) -> bool:
        item = self.state["items"].get(self.key(dataset, year), {})
        if dataset == "energy" and item.get("status") == "NOT_PUBLISHED" and (item.get("probe_version") or 1) < ENERGY_PROBE_VERSION:
            return False  # probed with the new 시·군·구 code only (before request_sigungu): ask again
        return item.get("status") in {"DONE", "NOT_PUBLISHED"}

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
        passes = int((hooks.get("previous") or {}).get("passes") or 0) + 1
        months = sum(full.get(k, 0) for k in ("skipped", "normalized", "empty", "not_reported", "suspect", "failed"))
        gap_share = full.get("failed", 0) / months if months else 0.0
        if other_failures > 0:
            status = "PARTIAL"
        elif gap_share > KAPT_GAP_TOLERANCE and passes < KAPT_MAX_PASSES:
            # A long gateway burst outlasted the pauses and retries: come back later (the job waits
            # and resumes by itself) instead of recording the year as finished.
            status = "PARTIAL"
            full["kind"] = "PROVIDER"
            full["reason"] = f"제공기관 04 오류로 {full.get('failed', 0):,}개 월이 남음 ({gap_share:.0%}) — {KAPT_PROVIDER_RETRY_H:g}시간 뒤 다시 요청 ({passes}/{KAPT_MAX_PASSES}회차)"
        else:
            status = "DONE"
            if full.get("failed"):
                full["reason"] = f"{KAPT_MAX_PASSES}회 시도 후에도 제공기관 오류로 남은 {full['failed']:,}개 월은 FAILED(0 아님)" if passes >= KAPT_MAX_PASSES else f"제공기관 오류로 남은 {full['failed']:,}개 월은 FAILED(0 아님)"
        return {"status": status, "retry_rounds": KAPT_RETRY_ROUNDS, "passes": passes, **full}

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
            return {"status": "NOT_PUBLISHED", "scope": ENERGY_SCOPE, "probe": "건축HUB 법정동 7월 응답 없음", "probe_version": ENERGY_PROBE_VERSION}
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

    def sgis_grid_500m() -> dict[str, Any]:
        from .sgis_grid_official import collect_sgis_grid_official
        result = collect_sgis_grid_official(db)
        return {"status": "DONE" if result.get("cells") else "PARTIAL", **result}

    return {
        "sgis": sgis, "kma_asos": kma_asos, "kapt_energy": kapt_energy, "energy": energy,
        "vworld_zoning": vworld("zoning"), "vworld_buildings": vworld("buildings"),
        "vworld_cadastral": vworld("cadastral"), "building_register": building_register,
        "sgis_grid_500m": sgis_grid_500m,
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
        if dataset == "sgis_grid_500m":
            from .sgis_grid_official import SgisOfficialGridCell
            n = db.scalar(select(func.count()).select_from(SgisOfficialGridCell)) or 0
            return f"공식 500m 격자 {n:,}개 보유 (통계값은 신청 필요)" if n else None
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
    outage: dict[str, str] = {}
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
                kind = "QUOTA" if dataset in quota else ("PROVIDER" if dataset in outage else "AUTH")
                progress_file.set(dataset, year, "BLOCKED", kind=kind, reason=blocked[dataset][:200])
                continue
            item = progress_file.state["items"].get(key, {})
            redo_energy = dataset == "energy" and item.get("scope") != ENERGY_SCOPE
            # A K-apt year finished before the retry rounds existed still has months that failed
            # during a gateway burst; asking for those again costs only the failed months.
            redo_kapt = dataset == "kapt_energy" and item.get("status") == "DONE" and (item.get("failed") or 0) > 0 and "retry_rounds" not in item
            if not force and progress_file.done(dataset, year) and not (redo_energy or redo_kapt):
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
            hooks["previous"] = progress_file.state["items"].get(key, {})
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
                if type(exc).__name__ == "ProviderOutageError":
                    # A provider-wide outage: keep what was received, skip this dataset for the rest of
                    # the run and let the job come back later (not counted as one of the passes).
                    previous = hooks.get("previous") or {}
                    progress_file.set(dataset, year, "PARTIAL", kind="PROVIDER", reason=str(exc)[:200], passes=previous.get("passes", 0),
                                      retry_rounds=previous.get("retry_rounds", 0))
                    blocked[dataset] = outage[dataset] = str(exc)[:200]
                    log(f"PARTIAL {key} PROVIDER: {exc}")
                    continue
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
    provider = sorted(k for k, item in progress_file.state["items"].items() if item.get("status") in {"PARTIAL", "BLOCKED"} and item.get("kind") == "PROVIDER")
    return {"items": progress_file.state["items"], "blocked": blocked, "quota": quota,
            "resume_at": next_quota_reset().isoformat() if quota else None,
            "provider_retry": provider,
            "provider_retry_at": (datetime.now(timezone.utc) + timedelta(hours=KAPT_PROVIDER_RETRY_H)).isoformat() if provider else None}


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




def manual_sources(data_dir: str | Path | None = None) -> list[dict[str, Any]]:
    """MANUAL_SOURCES, adjusted to what is already in DATA_DIR/raw:

    * SGIS 500m: gone when every theme × block is there, otherwise a re-request of exactly the missing files.
    * GIR 지역 인벤토리(raw/research/gir/regional_*), 가스공사 판매량(raw/gas), 한전 시군구 전력(raw/kepco): gone once the files are there.
    * 연도별 전력 배출계수: gone once the GIR 원문(raw/research/gir/b44·b56·b86) is there (2025 uses the 2025 approval, DATA_STANDARD 5.4)."""
    from .regional_stats import gas_files, gir_files, kepco_files
    from .sgis_grid500 import missing_files, missing_text, scan
    raw = Path(data_dir or os.getenv("DATA_DIR", "data")) / "raw"
    root = raw / "sgis_grid_500m"
    out = list(MANUAL_SOURCES)
    if scan(root)[0]:
        gaps = missing_files(root)
        out = [item for item in out if item["id"] != "sgis_grid"]
        if gaps:
            out.insert(0, {
                "id": "sgis_grid", "label": "SGIS 500m 격자 통계: 빠진 파일 재신청",
                "why": f"받은 500m 격자 통계는 적용했지만 일부 주제·블록 파일이 받은 묶음에 없습니다: {missing_text(gaps)}. 이 칸의 격자는 지도에 '통계 없음'으로 나오며 0으로 채우지 않습니다.",
                "how": "SGIS 자료제공에서 같은 조건으로 빠진 주제·블록만 다시 신청 → 받은 CSV를 data/raw/sgis_grid_500m에 추가 → API 재시작 또는 'python -m app.cli import-sgis-grid500'",
                "link": SGIS_REQUEST_URL, "missing": gaps})
    if gir_files(raw):
        out = [item for item in out if item["id"] != "gir_regional"]
    if gas_files(raw):
        out = [item for item in out if item["id"] != "gas_sido"]
    if kepco_files(raw):
        out = [item for item in out if item["id"] != "kepco_sigungu"]
    gir = raw / "research" / "gir"
    if all(any(gir.glob(f"b{board}_*.pdf")) for board in (44, 56, 86)):
        out = [item for item in out if item["id"] != "factors_yearly"]
    return out


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
    manual = manual_sources(data_dir)
    return {
        "years": years, "rows": rows, "manual": manual,
        "summary": {"todo": counts.get("TODO", 0) + counts.get("RETRY", 0), "done": counts.get("DONE", 0) + counts.get("NOT_PUBLISHED", 0),
                    "blocked": counts.get("BLOCKED", 0), "manual": len(manual), "states": counts},
        "last_run": (progress_file.state.get("runs") or [None])[-1],
    }
