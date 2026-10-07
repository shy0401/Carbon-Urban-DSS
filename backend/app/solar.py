"""Regional solar PV yield from observed irradiation (docs/DATA_STANDARD.md 5.13).

The reduction planner can turn the electricity a target still needs into a PV capacity. That needs how much one kW of
panels produces in a year *in that region*. Until now the user had to type it; this module estimates it from the
irradiation the tool already collects, with one fixed rule for every region:

    yield (kWh/kW·yr) = global horizontal irradiation (kWh/m²·yr) × performance ratio 0.80

- Irradiation: KMA ASOS 146 daily 합계 일사량 (MJ/m², Jeonju) when every day of the year is there; otherwise ERA5-Land
  daily ``shortwave_radiation_sum`` (Open-Meteo, MJ/m²) at the region centre, a reanalysis (FALLBACK) value.
- 1 kWh = 3.6 MJ. 1 kW of panels is rated at 1 kW/m² (STC), so kWh/m² of irradiation × PR = kWh per kW.
- Horizontal irradiation, no tilt gain: a tilted array gets more, so the capacity is on the safe (larger) side.
- A year counts only when every day is present; a missing day leaves the year out (never a partial sum).
"""
from __future__ import annotations

import calendar
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from sqlalchemy import DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base

PERFORMANCE_RATIO = 0.80
MJ_PER_KWH = 3.6
RULE = "연 발전량 = 수평면 일사량(kWh/m²·년) × 성능비 0.80, 경사 보정 없음"


OPEN_METEO = "https://archive-api.open-meteo.com/v1/archive"


class SolarMonthly(Base):
    """Monthly global horizontal irradiation of a study region (MJ/m²), stored only for complete months."""
    __tablename__ = "solar_monthly"
    region_code: Mapped[str] = mapped_column(String, primary_key=True)
    use_ym: Mapped[str] = mapped_column(String, primary_key=True)
    provider: Mapped[str] = mapped_column(String, primary_key=True)
    source_type: Mapped[str] = mapped_column(String)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    irradiation_mj_m2: Mapped[float | None] = mapped_column(Float, nullable=True)
    days_observed: Mapped[int] = mapped_column(Integer)
    expected_days: Mapped[int] = mapped_column(Integer)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


def year_days(year: int) -> int:
    return 366 if calendar.isleap(year) else 365


def daily_years(rows: Iterable[tuple[str, float | None]]) -> dict[int, float]:
    """``(YYYY-MM-DD, MJ/m²)`` daily values → {year: kWh/m²} for years where every day has a value (one value per date)."""
    by_date: dict[str, float] = {}
    for date, value in rows:
        if value is not None and value >= 0 and len(str(date)) >= 10:
            by_date.setdefault(str(date)[:10], float(value))
    by_year: dict[int, list[float]] = defaultdict(list)
    for date, value in by_date.items():
        by_year[int(date[:4])].append(value)
    return {y: round(sum(v) / MJ_PER_KWH, 1) for y, v in by_year.items() if len(v) == year_days(y)}


def monthly_years(rows: Iterable[tuple[str, float | None]]) -> dict[int, float]:
    """``(YYYYMM, MJ/m²)`` monthly sums that are stored only for complete months → {year: kWh/m²} with all 12 months."""
    by_year: dict[int, dict[str, float]] = defaultdict(dict)
    for ym, value in rows:
        if value is not None and value >= 0 and len(str(ym)) == 6:
            by_year[int(str(ym)[:4])][str(ym)] = float(value)
    return {y: round(sum(m.values()) / MJ_PER_KWH, 1) for y, m in by_year.items() if len(m) == 12}


def monthly_solar(daily: dict[str, list[Any]], indexes: list[int]) -> float | None:
    """Month sum of Open-Meteo ``shortwave_radiation_sum`` (MJ/m²), only when every day of the month has a value."""
    values = daily.get("shortwave_radiation_sum")
    if not values or not indexes:
        return None
    month = [values[i] for i in indexes]
    if any(v is None for v in month):
        return None
    ym = daily["time"][indexes[0]][:7]
    if len(month) != calendar.monthrange(int(ym[:4]), int(ym[5:7]))[1]:
        return None
    return round(sum(month), 2)


def choose(candidates: list[dict[str, Any]], up_to: int | None = None) -> dict[str, Any] | None:
    """Latest complete year (≤ up_to); for the same year an observation beats a reanalysis value."""
    rank = {"OFFICIAL": 0, "FALLBACK": 1}
    usable = [c for c in candidates if up_to is None or c["year"] <= up_to]
    if not usable:
        return None
    best = sorted(usable, key=lambda c: (-c["year"], rank.get(c["source_type"], 9)))[0]
    return estimate(best["year"], best["irradiation_kwh_m2"], best["source"], best["source_type"])


def estimate(year: int, irradiation_kwh_m2: float, source: str, source_type: str) -> dict[str, Any]:
    return {"year": year, "irradiation_kwh_m2": irradiation_kwh_m2, "performance_ratio": PERFORMANCE_RATIO,
            "yield_kwh_per_kw": round(irradiation_kwh_m2 * PERFORMANCE_RATIO, 1), "source": source, "source_type": source_type,
            "data_class": "ESTIMATED", "rule": RULE}


def candidates(db: Any, region_code: str | None) -> list[dict[str, Any]]:
    """Every complete year of irradiation the DB holds for a study region (no provider request)."""
    from sqlalchemy import select
    from .regions import DEFAULT_REGION
    code = region_code or DEFAULT_REGION
    out: list[dict[str, Any]] = []
    if code == DEFAULT_REGION:
        try:
            from .kma_asos import WeatherDailyObservation
            daily = db.execute(select(WeatherDailyObservation.observed_date, WeatherDailyObservation.solar_radiation_mj_m2)
                               .where(WeatherDailyObservation.station_id == "146"))
            out += [{"year": y, "irradiation_kwh_m2": v, "source": "기상청 ASOS 146 전주 합계 일사량", "source_type": "OFFICIAL"}
                    for y, v in daily_years(daily).items()]
        except Exception:  # noqa: BLE001 - ASOS tables not created yet
            db.rollback()
    try:
        rows = db.execute(select(SolarMonthly.use_ym, SolarMonthly.irradiation_mj_m2).where(SolarMonthly.region_code == code))
        out += [{"year": y, "irradiation_kwh_m2": v, "source": "ERA5-Land 일사량 (Open-Meteo, 재분석)", "source_type": "FALLBACK"}
                for y, v in monthly_years(rows).items()]
    except Exception:  # noqa: BLE001 - table not created yet
        db.rollback()
    return out


def store_months(db: Any, region_code: str, payload: dict[str, Any], latitude: float, longitude: float) -> int:
    """Write the months of an Open-Meteo daily payload that carries ``shortwave_radiation_sum``. Incomplete months get NULL."""
    daily = payload.get("daily") or {}
    if "shortwave_radiation_sum" not in daily:
        return 0
    groups: dict[str, list[int]] = defaultdict(list)
    for i, date in enumerate(daily.get("time") or []):
        groups[date[:7]].append(i)
    provider = "Open-Meteo / ERA5-Land"
    count = 0
    for ym, indexes in sorted(groups.items()):
        key = (region_code, ym.replace("-", ""), provider)
        row = db.get(SolarMonthly, key) or SolarMonthly(region_code=key[0], use_ym=key[1], provider=provider)
        row.source_type, row.latitude, row.longitude = "FALLBACK", latitude, longitude
        row.irradiation_mj_m2 = monthly_solar(daily, indexes)
        row.days_observed = sum(1 for i in indexes if daily["shortwave_radiation_sum"][i] is not None)
        row.expected_days = calendar.monthrange(int(ym[:4]), int(ym[5:7]))[1]
        row.collected_at = datetime.now(timezone.utc)
        db.add(row)
        count += 1
    return count


def backfill(db: Any, *, first_year: int = 2015, last_year: int | None = None, regions: list[str] | None = None,
             data_dir: str | Path | None = None, log: Callable[[str], None] = print) -> dict[str, Any]:
    """Fetch ERA5-Land daily irradiation (Open-Meteo, no key) at each study region's centre and store the months.

    One request per region for the whole period; the raw answer is kept in data/raw/weather-solar/<code>.json."""
    import os
    from sqlalchemy import select
    from .collectors import client
    from .region_prepare import analysis_year
    from .regions import DEFAULT_REGION, StudyRegion
    last = last_year or analysis_year()
    root = Path(data_dir or os.getenv("DATA_DIR", "data")) / "raw" / "weather-solar"
    root.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {}
    targets = list(db.scalars(select(StudyRegion).order_by(StudyRegion.code)))
    for region in targets:
        if regions and region.code not in regions:
            continue
        if region.code == DEFAULT_REGION:
            lat, lon = 35.8242, 127.1480  # the ERA5 point the original region already uses (collectors.collect_weather)
        elif region.center_lat is None or region.center_lon is None:
            result[region.code] = {"status": "SKIPPED", "message": "지역 중심 없음 (격자 단계 전)"}
            continue
        else:
            lat, lon = round(region.center_lat, 4), round(region.center_lon, 4)
        params = dict(latitude=lat, longitude=lon, start_date=f"{first_year}-01-01", end_date=f"{last}-12-31",
                      daily="shortwave_radiation_sum", timezone="Asia/Seoul", models="era5_land")
        try:
            answer = client.get("weather", f"solar-{region.code}", OPEN_METEO, params)
            (root / f"{region.code}.json").write_bytes(answer["body"])
            months = store_months(db, region.code, json.loads(answer["body"]), lat, lon)
            db.commit()
        except Exception as exc:  # noqa: BLE001 - one region failing does not stop the others
            db.rollback()
            result[region.code] = {"status": "FAILED", "message": f"{type(exc).__name__}: {str(exc)[:120]}"}
            log(f"{region.code} 일사량 실패: {type(exc).__name__}")
            continue
        estimate_ = regional_pv_yield(db, region.code)
        result[region.code] = {"status": "DONE", "months": months, "estimate": estimate_}
        log(f"{region.code} {region.name}: {months}개월, " + (f"{estimate_['year']}년 {estimate_['irradiation_kwh_m2']:,.0f} kWh/m² → {estimate_['yield_kwh_per_kw']:,.0f} kWh/kW ({estimate_['source']})" if estimate_ else "완비 연도 없음"))
    return result


def regional_pv_yield(db: Any, region_code: str | None, up_to: int | None = None) -> dict[str, Any] | None:
    return choose(candidates(db, region_code), up_to)
