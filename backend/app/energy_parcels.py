"""건축HUB 건물에너지 for every parcel of Jeonju (not only the K-apt complexes).

The 건축HUB API answers one 법정동 × month with every metered parcel when 번/지 are sent empty
(``bun=''&ji=''``), 100 rows per page. That is ~4,000 requests per year for the whole city instead
of ~6,500 for 298 apartment parcels one by one, and it adds offices, shops, schools and large
apartment blocks alike. Excluded by the provider: 단독주택, 200세대 미만 공동주택(2020-), and
industrial/transport/power uses. Data exist from 2020-01; 전북 months up to 2023-10 answer only to the old
시·군·구 code (45xxx, ``request_sigungu``) — asked with the new code they look empty.

* Rows go into ``energy_monthly`` like the per-parcel collector (same keys, same source name), so the
  apartment analysis keeps working unchanged; ``merge_energy_coordinates`` still links only unique
  K-apt parcels for the apartment metrics.
* ``parcel_grid`` maps every cadastral parcel (PNU) to the 500m grid holding its point-on-surface,
  which lets the map show *all-building* energy per grid ("건물 전체 에너지").
* Floor area for intensities comes from the 건축물대장 표제부 of the same parcel (cleaned by
  ``official.register_areas``). A missing month or area is never 0.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote

from sqlalchemy import String, func, insert, select, text
from sqlalchemy.orm import Mapped, mapped_column

from .cache import CachedClient, ExternalError, parse_cached_response
from .db import Base
from .domain import parse_energy
from .grid_metrics import annual_complete, bimonthly_only

URL = "https://apis.data.go.kr/1613000/BldEngyHubService/"
OPERATIONS = {"ELECTRICITY": "getBeElctyUsgInfo", "GAS": "getBeGasUsgInfo"}
HUB = "국토교통부 건축HUB"
PAGE = 100  # the provider caps numOfRows at 100
AUTH_CODES = {"20", "21", "30", "31", "32"}
TRANSIENT_CODES = {"01", "02", "04", "05", "99"}
MIN_KWH_PER_M2, MAX_KWH_PER_M2 = 2.0, 1500.0  # outside: partial meter or area mismatch, kept out of intensities


class ParcelGrid(Base):
    """Cadastral parcel (19-digit PNU, land type 1 일반 / 2 산) → 500m grid of its point-on-surface."""
    __tablename__ = "parcel_grid"
    pnu: Mapped[str] = mapped_column(String, primary_key=True)
    grid_id: Mapped[str] = mapped_column(String, index=True)
    method: Mapped[str] = mapped_column(String, default="CADASTRAL_POINT_ON_SURFACE")


def parcel_pnu(sigungu: str, bjdong: str, lot_type: str | None, bun: str, ji: str) -> str:
    """Energy row key → PNU. 건축HUB 대지구분 0 대지 / 1 산 → PNU 1 일반 / 2 산."""
    land = "2" if str(lot_type or "0").strip() == "1" else "1"
    return f"{sigungu}{bjdong}{land}{str(bun or '0').zfill(4)[-4:]}{str(ji or '0').zfill(4)[-4:]}"


def build_parcel_grid(db: Any) -> int:
    """(Re)build parcel_grid from cadastral_parcels with PostGIS. Returns the row count (0 without PostGIS)."""
    try:
        ParcelGrid.__table__.create(db.get_bind(), checkfirst=True)
        with db.begin_nested():
            db.execute(text("DELETE FROM parcel_grid"))
            db.execute(text(
                "INSERT INTO parcel_grid (pnu, grid_id, method) "
                "SELECT DISTINCT ON (c.pnu) c.pnu, g.id, 'CADASTRAL_POINT_ON_SURFACE' "
                "FROM cadastral_parcels c JOIN grid_500m g ON ST_Contains(g.geom, ST_PointOnSurface(c.geom)) "
                "WHERE c.pnu IS NOT NULL ORDER BY c.pnu"))
        db.commit()
    except Exception:  # noqa: BLE001 - no PostGIS (tests) or no cadastral layer yet
        db.rollback()
        return 0
    _GRID_CACHE.clear()
    return db.scalar(select(func.count()).select_from(ParcelGrid)) or 0


# 전북특별자치도 출범(2024-01)으로 시·군·구 코드가 45xxx → 52xxx로 바뀌었다. 건축HUB는 2023-10 사용분까지 옛 코드로만
# 답한다(팀 데이터셋 urban-carbon의 단지 80곳으로 확인: 새 코드로 물으면 2023년 이전이 모두 빈 응답). 2020-01분부터 있다.
OLD_SIGUNGU = {"52": ("45", "202310")}
HUB_FIRST_YEAR = 2020
# Months the provider answered only in part (city-wide, 2026-10-05: 전주 2020-09·10 전력 112.9·86.9 GWh against 157.9·137.7 GWh
# in 2021; large apartment parcels were missing — 팀 사례 자료 TEAM_CASE_JEONJU_DONGS.md). Such a year is kept but not compared.
HUB_PROVIDER_GAPS = {2020: "2020년 9·10월 제공기관 응답에서 대단지 등 일부 지번이 빠져(전주 전력 9월 112.9, 10월 86.9 GWh로 2021년 같은 달의 72%·63%) 다른 해와 비교하지 않습니다"}


def request_sigungu(sigungu: str, use_ym: str) -> str:
    """The 시·군·구 code 건축HUB expects for that month (old code before the province was renamed)."""
    rule = OLD_SIGUNGU.get(str(sigungu)[:2])
    if rule and str(use_ym) <= rule[1]:
        return rule[0] + str(sigungu)[2:]
    return str(sigungu)


def _request(session: Any, operation: str, params: dict[str, Any], attempts: int = 3) -> tuple[list[dict[str, Any]], int]:
    for attempt in range(attempts):
        response = None
        try:
            response = session.get("molit-dong", operation, URL + operation, params)
            return parse_cached_response(session, response, parse_energy)
        except (ExternalError, ValueError) as exc:
            message = str(exc)
            code = message.split(":", 1)[0].strip()
            if code in AUTH_CODES or "인증 실패" in message:
                raise ExternalError("API 인증 실패: 건축HUB 에너지 활용승인과 DATA_GO_KR_SERVICE_KEY를 확인하세요") from None
            if code == "22" or "호출 제한" in message:
                raise ExternalError("건축HUB 일일 호출 한도 초과(22): 받은 페이지는 저장되므로 다음 날 이어서 받습니다") from None
            cached = response or getattr(exc, "asset", None)
            if code not in TRANSIENT_CODES and "외부 데이터 HTTP 5" not in message and "연결 실패" not in message:
                raise ExternalError(f"건축HUB 응답 오류: {message[:80]}") from None
            if isinstance(cached, dict) and hasattr(session, "forget"):
                session.forget(cached)
            if hasattr(session, "reset_connection"):
                session.reset_connection()  # the gateway pins a kept-alive connection to one backend node
            if attempt == attempts - 1:
                raise ExternalError(f"건축HUB 제공기관 일시 오류: {message[:60]}") from None
            time.sleep(2 * (attempt + 1))
    raise ExternalError("건축HUB 제공기관 일시 오류")


def _session(client: Any | None) -> Any:
    if client is not None:
        return client
    root = Path(os.getenv("DATA_DIR", "data")) / "cache" / "energy-dong"
    return CachedClient(root, min_interval=max(float(os.getenv("BUILDING_ENERGY_REQUEST_DELAY_MS", "200")) / 1000, 0))


def probe_year(db: Any, year: int, *, client: Any | None = None, service_key: str | None = None) -> int:
    """Parcels answered for one busy 법정동 in July of ``year`` (2 requests). 0 means not published."""
    from .official import register_regions
    key = unquote((service_key or os.getenv("DATA_GO_KR_SERVICE_KEY", "")).strip())
    if not key:
        raise ExternalError("API 인증 실패: DATA_GO_KR_SERVICE_KEY 미설정")
    regions = register_regions(db, "full")
    if not regions:
        raise ExternalError("법정동 코드가 없습니다. 지역코드 수집 필요")
    session = _session(client)
    # the 법정동 holding the most K-apt complexes answers for sure when the year is published
    from .kapt import ApartmentComplex
    counts = dict(db.execute(select(ApartmentComplex.bjd_code, func.count()).group_by(ApartmentComplex.bjd_code)).all())
    region = max(regions, key=lambda r: counts.get(f"{r['sigunguCd']}{r['bjdongCd']}", 0))
    total = 0
    for operation in OPERATIONS.values():
        _, found = _request(session, operation, dict(serviceKey=key, sigunguCd=request_sigungu(region["sigunguCd"], f"{year}07"),
                                                      bjdongCd=region["bjdongCd"], bun="", ji="", useYm=f"{year}07", numOfRows=PAGE, pageNo=1, _type="json"))
        total += found
    return total


def collect_energy_all(db: Any, year: int, progress: Callable[[float, str], None] | None = None, *,
                       client: Any | None = None, service_key: str | None = None, regions: list[dict[str, str]] | None = None,
                       months: list[str] | None = None) -> dict[str, Any]:
    """Every metered parcel of every 법정동 for the 12 months of ``year`` (electricity and gas)."""
    from .models import EnergyMonthly
    from .official import register_regions
    key = unquote((service_key or os.getenv("DATA_GO_KR_SERVICE_KEY", "")).strip())
    if not key:
        raise ExternalError("API 인증 실패: DATA_GO_KR_SERVICE_KEY 미설정")
    regions = regions if regions is not None else register_regions(db, "full")
    if not regions:
        raise ExternalError("법정동 코드가 없습니다. 지역코드 수집 필요")
    months = months or [f"{year}{m:02d}" for m in range(1, 13)]
    session = _session(client)
    stats = {"requests": 0, "rows": 0, "inserted": 0, "updated": 0, "regions": len(regions)}
    total_steps = max(1, len(regions) * len(months))
    step = 0
    for region in regions:
        sg, bd = region["sigunguCd"], region["bjdongCd"]
        existing: dict[tuple[str, str, str, str, str], tuple[int, float | None, str]] = {
            (r.lot_type or "0", r.bun, r.ji, r.use_ym, r.energy_type): (r.id, r.usage_kwh, r.source)
            for r in db.execute(select(EnergyMonthly.id, EnergyMonthly.lot_type, EnergyMonthly.bun, EnergyMonthly.ji, EnergyMonthly.use_ym,
                                       EnergyMonthly.energy_type, EnergyMonthly.usage_kwh, EnergyMonthly.source).where(
                EnergyMonthly.sigungu_code == sg, EnergyMonthly.bjdong_code == bd, EnergyMonthly.use_ym.in_(months)))
        }
        for ym in months:
            step += 1
            if progress:
                progress((step - 1) / total_steps, f"{region.get('name') or sg + bd} {ym[:4]}-{ym[4:]} ({step}/{total_steps})")
            answered: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
            for energy_type, operation in OPERATIONS.items():
                page = 1
                while True:
                    params = dict(serviceKey=key, sigunguCd=request_sigungu(sg, ym), bjdongCd=bd, bun="", ji="", useYm=ym, numOfRows=PAGE, pageNo=page, _type="json")
                    rows, total = _request(session, operation, params)
                    stats["requests"] += 1
                    for raw in rows:
                        lot = str(raw.get("platGbCd") or "0").strip() or "0"
                        bun, ji = str(raw.get("bun") or "0").zfill(4)[-4:], str(raw.get("ji") or "0").zfill(4)[-4:]
                        key_ = (lot, bun, ji, str(raw.get("useYm") or ym), energy_type)
                        value = raw.get("usage_kwh")
                        stats["rows"] += 1
                        item = answered.setdefault(key_, {"value": None, "rows": 0, "record": {k: v for k, v in raw.items() if k in ("platPlc", "newPlatPlc", "useQty")}})
                        item["rows"] += 1
                        if value is not None:
                            # the same 지번 listed twice (e.g. two road addresses) is one parcel: add them
                            item["value"] = (item["value"] or 0.0) + value
                    if not rows or page * PAGE >= total:
                        break
                    page += 1
            new_rows: list[dict[str, Any]] = []
            for key_, item in answered.items():
                lot, bun, ji, use_ym, energy_type = key_
                value, record = item["value"], dict(item["record"])
                if item["rows"] > 1:
                    record["merged_rows"] = item["rows"]
                if key_ in existing:
                    row_id, old_value, old_source = existing[key_]
                    if old_value != value or old_source != HUB:
                        row = db.get(EnergyMonthly, row_id)
                        merged = dict(row.raw_record or {}, **record)
                        if old_source != HUB and old_value is not None:
                            merged.update(replaced_source=old_source, replaced_usage_kwh=old_value)
                        row.source, row.usage_kwh, row.raw_record = HUB, value, merged
                        existing[key_] = (row_id, value, HUB)
                        stats["updated"] += 1
                    continue
                new_rows.append(dict(source=HUB, sigungu_code=sg, bjdong_code=bd, lot_type=lot, bun=bun, ji=ji, use_ym=use_ym,
                                     energy_type=energy_type, usage_kwh=value, raw_record=record))
            if new_rows:
                db.execute(insert(EnergyMonthly), new_rows)
                stats["inserted"] += len(new_rows)
            db.commit()
    if progress:
        progress(1.0, f"{year}년 {len(regions)}개 법정동 완료")
    _GRID_CACHE.clear()
    return stats


def year_complete(year: int) -> bool:
    """Whether the city-wide collection of ``year`` has finished (history progress says DONE).

    The progress file is not in the database: a data bundle carries it as ``collection-progress.json`` and
    ImportBundle writes it back, otherwise the same rows would read as 잠정값 on another PC."""
    import json
    path = Path(os.getenv("DATA_DIR", "data")) / "ops" / "history-progress.json"
    try:
        item = json.loads(path.read_text(encoding="utf-8-sig"))["items"].get(f"energy:{year}") or {}
    except (OSError, ValueError, KeyError):
        return False
    return item.get("status") == "DONE" and item.get("scope") == "all_parcels"


# --------------------------------------------------------------------------- grid aggregates
_GRID_CACHE: dict[int, tuple[int, dict[str, dict[str, Any]]]] = {}  # year -> (row count, per-grid values)
_PARCEL_GRID: dict[int, dict[str, str]] = {}


def _parcel_grid(db: Any) -> dict[str, str]:
    try:
        count = db.scalar(select(func.count()).select_from(ParcelGrid)) or 0
    except Exception:  # noqa: BLE001 - table not created yet
        db.rollback()
        return {}
    if count not in _PARCEL_GRID:
        _PARCEL_GRID.clear()
        _PARCEL_GRID[count] = dict(db.execute(select(ParcelGrid.pnu, ParcelGrid.grid_id)).all())
    return _PARCEL_GRID[count]


def _register_area(db: Any) -> dict[str, float]:
    """PNU → cleaned 연면적 sum (건축물대장 표제부)."""
    try:
        from .official import BuildingRegister, register_areas
        area: dict[str, float] = {}
        for pnu, attrs in db.execute(select(BuildingRegister.parcel_code, BuildingRegister.attributes)):
            gfa = register_areas(attrs or {})[0]
            if gfa:
                area[pnu] = area.get(pnu, 0.0) + gfa
        return area
    except Exception:  # noqa: BLE001
        db.rollback()
        return {}


def summarize_parcels(parcels: list[dict[str, Any]], grid_of: dict[str, str], area_of: dict[str, float]) -> dict[str, dict[str, Any]]:
    """parcels: {pnu, energy_type, months, kwh} per parcel-year → per-grid all-building energy.

    Totals use parcels whose rows cover the whole year (all 12 months, or for gas every month but
    summer months billed with the next one: ``annual_complete``; ``month_list`` gives the months, else
    ``months`` must be 12); the intensity uses those of them with a register floor area and a plausible
    2~1,500 kWh/m²·년.
    """
    out: dict[str, dict[str, Any]] = {}
    for p in parcels:
        grid_id = grid_of.get(p["pnu"])
        if not grid_id:
            continue
        item = out.setdefault(grid_id, {"parcels": set(), "ELECTRICITY": {"complete": 0, "kwh": 0.0}, "GAS": {"complete": 0, "kwh": 0.0},
                                        "area_parcels": 0, "area_m2": 0.0, "area_kwh": 0.0, "suspect": 0, "by_parcel": {}})
        item["parcels"].add(p["pnu"])
        target = item[p["energy_type"]]
        month_list = p.get("month_list")
        complete = annual_complete(p["energy_type"], month_list) if month_list is not None else p["months"] >= 12
        if not complete or p["kwh"] is None:
            continue
        target["complete"] += 1
        if month_list is not None and bimonthly_only(p["energy_type"], month_list):
            item["bimonthly"] = item.get("bimonthly", 0) + 1
        target["kwh"] += p["kwh"]
        if p["energy_type"] == "ELECTRICITY":
            item["by_parcel"][p["pnu"]] = p["kwh"]
            area = area_of.get(p["pnu"])
            if area:
                ratio = p["kwh"] / area
                if MIN_KWH_PER_M2 <= ratio <= MAX_KWH_PER_M2:
                    item["area_parcels"] += 1
                    item["area_m2"] += area
                    item["area_kwh"] += p["kwh"]
                else:
                    item["suspect"] += 1
    result: dict[str, dict[str, Any]] = {}
    for grid_id, item in out.items():
        e, g = item["ELECTRICITY"], item["GAS"]
        result[grid_id] = {
            "parcels": len(item["parcels"]),
            "electricity_complete": e["complete"], "electricity_kwh": round(e["kwh"], 1) if e["complete"] else None,
            "gas_complete": g["complete"], "gas_kwh": round(g["kwh"], 1) if g["complete"] else None,
            "gas_bimonthly": item.get("bimonthly", 0),
            "area_parcels": item["area_parcels"], "area_m2": round(item["area_m2"], 1) if item["area_parcels"] else None,
            "kwh_per_m2": round(item["area_kwh"] / item["area_m2"], 2) if item["area_parcels"] else None,
            "suspect": item["suspect"],
            # 12-month electricity per parcel: lets an area compare the same parcels across years (not serialised by map_properties)
            "electricity_by_parcel": item["by_parcel"],
        }
    return result


def grid_building_energy(db: Any, year: int) -> dict[str, dict[str, Any]]:
    """Per-grid all-building energy for ``year`` (cached per row count)."""
    from .models import EnergyMonthly
    lo, hi = f"{year}01", f"{year}12"
    count = db.scalar(select(func.count()).select_from(EnergyMonthly).where(EnergyMonthly.use_ym.between(lo, hi), EnergyMonthly.source == HUB)) or 0
    if not count:
        return {}
    hit = _GRID_CACHE.get(year)
    if hit is None or hit[0] != count:
        grid_of = _parcel_grid(db)
        if not grid_of:
            return {}
        # the months themselves (not only their count): gas billed bi-monthly in summer skips a month
        agg = func.array_agg if db.get_bind().dialect.name == "postgresql" else func.group_concat
        rows = db.execute(
            select(EnergyMonthly.sigungu_code, EnergyMonthly.bjdong_code, EnergyMonthly.lot_type, EnergyMonthly.bun, EnergyMonthly.ji,
                   EnergyMonthly.energy_type, agg(EnergyMonthly.use_ym), func.sum(EnergyMonthly.usage_kwh))
            .where(EnergyMonthly.use_ym.between(lo, hi), EnergyMonthly.source == HUB, EnergyMonthly.usage_kwh.is_not(None))
            .group_by(EnergyMonthly.sigungu_code, EnergyMonthly.bjdong_code, EnergyMonthly.lot_type, EnergyMonthly.bun, EnergyMonthly.ji, EnergyMonthly.energy_type)
        ).all()
        parcels = []
        for sg, bd, lot, bun, ji, et, yms, kwh in rows:
            month_list = sorted(set(yms.split(",") if isinstance(yms, str) else yms))
            parcels.append({"pnu": parcel_pnu(sg, bd, lot, bun, ji), "energy_type": et, "months": len(month_list), "month_list": month_list,
                            "kwh": float(kwh) if kwh is not None else None})
        _GRID_CACHE[year] = (count, summarize_parcels(parcels, grid_of, _register_area(db)))
    return _GRID_CACHE[year][1]


def map_properties(item: dict[str, Any] | None, factor: float | None) -> dict[str, Any]:
    if not item:
        return {"bldg_parcels": None, "bldg_electricity_kwh": None, "bldg_gas_kwh": None, "bldg_electricity_complete": None,
                "bldg_gas_complete": None, "bldg_area_m2": None, "bldg_area_parcels": None, "bldg_kwh_per_m2": None,
                "bldg_carbon_t": None, "bldg_gas_carbon_t": None, "bldg_suspect": None, "bldg_gas_bimonthly": None}
    from .emissions import GAS_FACTOR  # 가정 계수(고정 규칙), docs/DATA_STANDARD.md 5.5
    kwh = item["electricity_kwh"]
    gas = item["gas_kwh"]
    return {"bldg_parcels": item["parcels"], "bldg_electricity_kwh": kwh, "bldg_gas_kwh": item["gas_kwh"],
            "bldg_electricity_complete": item["electricity_complete"], "bldg_gas_complete": item["gas_complete"],
            "bldg_area_m2": item["area_m2"], "bldg_area_parcels": item["area_parcels"], "bldg_kwh_per_m2": item["kwh_per_m2"],
            "bldg_carbon_t": round(kwh * factor / 1000, 1) if kwh is not None and factor else None,
            "bldg_gas_carbon_t": round(gas * GAS_FACTOR / 1000, 1) if gas is not None else None, "bldg_suspect": item["suspect"],
            "bldg_gas_bimonthly": item.get("gas_bimonthly", 0)}
