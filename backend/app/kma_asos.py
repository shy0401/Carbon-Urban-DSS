"""KMA ASOS daily observations and provider-preserving monthly aggregates."""
from __future__ import annotations

import calendar
import hashlib
import json
import os
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, Integer, JSON, String, func, select
from sqlalchemy.orm import Mapped, mapped_column

from .cache import CachedClient, ExternalError
from .db import Base
from .models import DataSource, RawDataAsset, WeatherMonthly

KMA_CATALOG_URL = "https://www.data.go.kr/data/15059093/openapi.do"
KMA_ASOS_BASE_URL = "https://apis.data.go.kr/1360000/AsosDalyInfoService"


class WeatherDailyObservation(Base):
    __tablename__ = "weather_daily_observations"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    station_id: Mapped[str] = mapped_column(String, index=True)
    observed_date: Mapped[str] = mapped_column(String, index=True)
    avg_temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    precipitation_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_humidity_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    sunshine_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    solar_radiation_mj_m2: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_wind_speed_m_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String)
    raw_source_id: Mapped[str | None] = mapped_column(String, nullable=True)
    raw_record: Mapped[dict] = mapped_column(JSON, default=dict)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class WeatherMonthlyObservation(Base):
    __tablename__ = "weather_monthly_observations"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    use_ym: Mapped[str] = mapped_column(String, index=True)
    station_id: Mapped[str] = mapped_column(String)
    provider: Mapped[str] = mapped_column(String, index=True)
    source_type: Mapped[str] = mapped_column(String)
    mean_temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    precipitation_sum_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_humidity_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    sunshine_sum_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    solar_radiation_sum_mj_m2: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_wind_speed_m_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    hdd: Mapped[float | None] = mapped_column(Float, nullable=True)
    cdd: Mapped[float | None] = mapped_column(Float, nullable=True)
    valid_day_count: Mapped[int] = mapped_column(Integer)
    expected_day_count: Mapped[int] = mapped_column(Integer)
    completeness_ratio: Mapped[float] = mapped_column(Float)
    official_asos_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


def _number(value: Any) -> float | None:
    if value is None or (isinstance(value, str) and value.strip() in {"", "-"}):
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def parse_asos_response(body: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(body.decode("utf-8-sig"))
        response = payload.get("response", {})
        header, content = response.get("header", {}), response.get("body", {})
        code, message = str(header.get("resultCode", "")), str(header.get("resultMsg", ""))
        container = content.get("items") or {}
        items = container.get("item", []) if isinstance(container, dict) else container
        total = int(content.get("totalCount") or len(items or []))
    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError, TypeError, ValueError):
        try:
            root = ET.fromstring(body)
            code, message = root.findtext(".//resultCode") or "", root.findtext(".//resultMsg") or ""
            items = [{child.tag: child.text for child in node} for node in root.findall(".//item")]
            total = int(root.findtext(".//totalCount") or len(items))
        except (ET.ParseError, ValueError) as exc:
            raise ExternalError("KMA ASOS 응답 파싱 실패") from exc
    if code not in {"0", "00"}:
        if code in {"20", "30", "01", "02"}:
            raise ExternalError("KMA ASOS API 인증 실패: 서비스 활용 승인과 인증키를 확인하세요")
        raise ExternalError(f"KMA ASOS API 오류: provider_code={code or 'UNKNOWN'}")
    if isinstance(items, dict):
        items = [items]
    rows = []
    for item in items or []:
        rows.append({
            "station_id": str(item.get("stnId") or ""), "observed_date": str(item.get("tm") or ""),
            "avg_temperature_c": _number(item.get("avgTa")), "min_temperature_c": _number(item.get("minTa")),
            "max_temperature_c": _number(item.get("maxTa")), "precipitation_mm": _number(item.get("sumRn")),
            "avg_humidity_pct": _number(item.get("avgRhm")), "sunshine_hours": _number(item.get("sumSsHr")),
            "solar_radiation_mj_m2": _number(item.get("sumGsr")), "avg_wind_speed_m_s": _number(item.get("avgWs")),
            "raw_record": dict(item),
        })
    return {"provider_code": code, "provider_message": message, "total_count": total, "rows": rows}


def _average(values: list[float | None]) -> float | None:
    known = [value for value in values if value is not None]
    return mean(known) if known else None


def _sum(values: list[float | None]) -> float | None:
    known = [value for value in values if value is not None]
    return sum(known) if known else None


def aggregate_asos_months(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if len(row.get("observed_date", "")) >= 7:
            grouped[row["observed_date"][:7].replace("-", "")].append(row)
    result = []
    for use_ym, month_rows in sorted(grouped.items()):
        year, month = int(use_ym[:4]), int(use_ym[4:])
        expected = calendar.monthrange(year, month)[1]
        unique_dates = {row["observed_date"] for row in month_rows if row.get("avg_temperature_c") is not None}
        valid = len(unique_dates)
        temperatures = [row.get("avg_temperature_c") for row in month_rows]
        daily_for_degree = [value for value in temperatures if value is not None]
        hdd = sum(max(18 - value, 0) for value in daily_for_degree) if daily_for_degree else None
        cdd = sum(max(value - 18, 0) for value in daily_for_degree) if daily_for_degree else None
        result.append({
            "use_ym": use_ym, "station_id": month_rows[0].get("station_id") or "146",
            "mean_temperature_c": _average(temperatures),
            "min_temperature_c": min((v for v in (row.get("min_temperature_c") for row in month_rows) if v is not None), default=None),
            "max_temperature_c": max((v for v in (row.get("max_temperature_c") for row in month_rows) if v is not None), default=None),
            "precipitation_sum_mm": _sum([row.get("precipitation_mm") for row in month_rows]),
            "avg_humidity_pct": _average([row.get("avg_humidity_pct") for row in month_rows]),
            "sunshine_sum_hours": _sum([row.get("sunshine_hours") for row in month_rows]),
            "solar_radiation_sum_mj_m2": _sum([row.get("solar_radiation_mj_m2") for row in month_rows]),
            "avg_wind_speed_m_s": _average([row.get("avg_wind_speed_m_s") for row in month_rows]),
            "hdd": hdd, "cdd": cdd, "valid_day_count": valid, "expected_day_count": expected,
            "completeness_ratio": valid / expected, "official_asos_complete": valid == expected,
        })
    return result


def backfill_weather_observations(db: Any) -> int:
    count = 0
    for row in db.scalars(select(WeatherMonthly)):
        ident = f"{row.provider}:{row.use_ym}"
        if db.get(WeatherMonthlyObservation, ident):
            continue
        db.add(WeatherMonthlyObservation(
            id=ident, use_ym=row.use_ym, station_id="146" if "KMA" in row.provider else "ERA5-Land-grid",
            provider=row.provider, source_type=row.source_type,
            mean_temperature_c=row.mean_temperature, min_temperature_c=row.min_temperature,
            max_temperature_c=row.max_temperature, precipitation_sum_mm=row.precipitation,
            hdd=row.hdd, cdd=row.cdd, valid_day_count=row.days_observed,
            expected_day_count=row.expected_days, completeness_ratio=row.days_observed / row.expected_days if row.expected_days else 0,
            official_asos_complete=row.source_type == "OFFICIAL" and row.days_observed == row.expected_days,
            collected_at=row.collected_at,
        ))
        count += 1
    db.commit()
    return count


def refresh_effective_weather(db: Any, use_yms: list[str] | None = None) -> int:
    if use_yms is None:
        use_yms = list(db.scalars(select(WeatherMonthlyObservation.use_ym).distinct()))
    changed = 0
    for use_ym in use_yms:
        observations = list(db.scalars(select(WeatherMonthlyObservation).where(WeatherMonthlyObservation.use_ym == use_ym)))
        chosen = next((row for row in observations if row.official_asos_complete), None)
        chosen = chosen or next((row for row in observations if row.source_type == "FALLBACK"), None)
        if not chosen:
            continue
        db.merge(WeatherMonthly(
            use_ym=use_ym, provider=chosen.provider, source_type=chosen.source_type,
            latitude=35.84092 if chosen.source_type == "OFFICIAL" else 35.8242,
            longitude=127.11718 if chosen.source_type == "OFFICIAL" else 127.1480,
            mean_temperature=chosen.mean_temperature_c, min_temperature=chosen.min_temperature_c,
            max_temperature=chosen.max_temperature_c, precipitation=chosen.precipitation_sum_mm,
            hdd=chosen.hdd, cdd=chosen.cdd, days_observed=chosen.valid_day_count,
            expected_days=chosen.expected_day_count, collected_at=chosen.collected_at,
        ))
        changed += 1
    db.commit()
    return changed


def collect_asos(db: Any, year: int, scope: str = "smoke", *, client: CachedClient | None = None, service_key: str | None = None, data_dir: str | Path | None = None) -> dict[str, int]:
    if scope not in {"smoke", "limited", "full"}:
        raise ValueError("scope must be smoke, limited, or full")
    source = db.get(DataSource, "weather_kma") or DataSource(
        id="weather_kma", category="기상", name="KMA ASOS 전주 146 일자료",
        organization="기상청", source_url=KMA_CATALOG_URL, source_type="OFFICIAL",
        status="NOT_COLLECTED", limitation="완전한 월만 유효 기상값으로 선택하며 ERA5-Land 원본은 별도 보존합니다.",
    )
    db.add(source);db.commit()
    key = (service_key or os.getenv("DATA_GO_KR_SERVICE_KEY", "")).strip()
    if not key:
        source.status = "NEEDS_API_APPROVAL";db.commit()
        raise ExternalError("KMA ASOS API 인증 실패: DATA_GO_KR_SERVICE_KEY 미설정")
    root = Path(data_dir or os.getenv("DATA_DIR", "data"))
    raw_root = root / "raw" / "kma" / "asos" / str(year);raw_root.mkdir(parents=True, exist_ok=True)
    session = client or CachedClient(root / "cache" / "kma-asos")
    start, end = (f"{year}0101", f"{year}0131") if scope == "smoke" else (f"{year}0101", f"{year}1231")
    base = os.getenv("KMA_ASOS_BASE_URL", KMA_ASOS_BASE_URL).rstrip("/")
    rows: list[dict[str, Any]] = []
    page, total = 1, None
    while total is None or len(rows) < total:
        params = {"serviceKey": key, "pageNo": page, "numOfRows": 999, "dataType": "JSON", "dataCd": "ASOS", "dateCd": "DAY", "startDt": start, "endDt": end, "stnIds": "146"}
        result = session.get("KMA", f"ASOS-{year}-{scope}-{page}", f"{base}/getWthrDataList", params)
        raw_path = raw_root / f"{scope}-page-{page}.json";raw_path.write_bytes(result["body"])
        parsed = parse_asos_response(result["body"]);total = parsed["total_count"]
        safe_params = {key_: value for key_, value in params.items() if key_.casefold() != "servicekey"}
        digest = hashlib.sha256(result["body"] + f":{page}".encode()).hexdigest()
        asset = db.get(RawDataAsset, digest) or RawDataAsset(id=digest, source_id=source.id, provider=source.organization, source_url=KMA_CATALOG_URL, reference_period=f"{start}~{end}", storage_location=str(raw_path), collection_status="COLLECTED")
        asset.row_count=len(parsed["rows"]);asset.request_parameters={**safe_params,"http_status":result.get("status"),"provider_code":parsed["provider_code"]};db.add(asset)
        for row in parsed["rows"]:
            daily = db.get(WeatherDailyObservation, f"KMA-ASOS:{row['station_id']}:{row['observed_date']}") or WeatherDailyObservation(id=f"KMA-ASOS:{row['station_id']}:{row['observed_date']}", station_id=row["station_id"], observed_date=row["observed_date"], source="KMA ASOS")
            for field in ("avg_temperature_c","min_temperature_c","max_temperature_c","precipitation_mm","avg_humidity_pct","sunshine_hours","solar_radiation_mj_m2","avg_wind_speed_m_s"):
                setattr(daily, field, row[field])
            daily.raw_record=row["raw_record"];daily.raw_source_id=digest;daily.collected_at=datetime.now(timezone.utc);db.add(daily)
        rows.extend(parsed["rows"]);db.commit()
        if not parsed["rows"] or len(rows) >= total:
            break
        page += 1
    monthly = aggregate_asos_months(rows)
    for item in monthly:
        ident=f"KMA-ASOS:146:{item['use_ym']}"
        observation=db.get(WeatherMonthlyObservation,ident) or WeatherMonthlyObservation(id=ident,use_ym=item["use_ym"],station_id="146",provider="KMA ASOS station146",source_type="OFFICIAL")
        for field,value in item.items():
            if field not in {"use_ym","station_id"}:setattr(observation,field,value)
        observation.collected_at=datetime.now(timezone.utc);db.add(observation)
    db.commit();refresh_effective_weather(db,[item["use_ym"] for item in monthly])
    daily_count=db.scalar(select(func.count()).select_from(WeatherDailyObservation).where(WeatherDailyObservation.observed_date.startswith(str(year)))) or 0
    complete=sum(bool(item["official_asos_complete"]) for item in monthly)
    source.status="COLLECTED" if complete==12 else "PARTIAL";source.reference_period=str(year);source.raw_row_count=daily_count;source.normalized_row_count=len(monthly);source.missing_count=sum(item["expected_day_count"]-item["valid_day_count"] for item in monthly);source.quality=f"ASOS 전주146 {daily_count}일 / 완전한 월 {complete}개";source.collected_at=datetime.now(timezone.utc);db.commit()
    return {"daily_rows":daily_count,"monthly_rows":len(monthly),"complete_months":complete}
