"""Official K-apt monthly energy collection with resumable scopes."""
from __future__ import annotations

import hashlib
import json
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import JSON, DateTime, Float, String, UniqueConstraint, func, select
from sqlalchemy.orm import Mapped, mapped_column

from .cache import CachedClient, ExternalError, parse_cached_response
from .db import Base
from .models import DataSource, EnergyMonthly, RawDataAsset

KAPT_ENERGY_CATALOG_URL = "https://www.data.go.kr/data/15012964/openapi.do"
KAPT_ENERGY_BASE_URL = "https://apis.data.go.kr/1613000/ApHusEnergyUseInfoOfferServiceV2"
KAPT_ENERGY_OPERATION = "getHsmpApHusUsgQtyInfoSearchV2"
ELECTRICITY_FACTOR = 0.4541
# data.go.kr gateway/provider codes that mean the key or its approval is not valid.
AUTH_CODES = {"20", "21", "30", "31", "32"}
# Gateway codes for a temporary provider failure (01 APPLICATION, 02 DB, 04 HTTP, 05 TIMEOUT, 99 UNKNOWN).
# The request is retried; a month that still fails stays FAILED and is re-requested on the next run.
TRANSIENT_CODES = {"01", "02", "04", "05", "99"}
QUANTITY_FIELDS = ("electricity_quantity", "gas_quantity", "heating_quantity", "hot_water_quantity", "water_quantity")
# Statuses that are a valid provider answer (never re-requested). FAILED rows are retried.
ANSWERED = {"SUCCESS", "EMPTY_VALID", "NOT_REPORTED", "SUSPECT"}
# K-apt fills items a complex did not enter with 0. A month in which every quantity is 0 is
# "not reported", not zero use. A reported electricity value below this monthly amount per
# household is physically implausible for an occupied complex and is kept only for audit.
MIN_PLAUSIBLE_KWH_PER_HOUSEHOLD = 20.0


class TransientProviderError(ExternalError):
    """Temporary provider failure; safe to retry."""

FIELD_MAP = {
    "helect": "electricity_quantity", "elect": "electricity_amount_krw",
    "hgas": "gas_quantity", "gas": "gas_amount_krw",
    "hheat": "heating_quantity", "heat": "heating_amount_krw",
    "hwaterHot": "hot_water_quantity", "waterHot": "hot_water_amount_krw",
    "hwaterCool": "water_quantity", "waterCool": "water_amount_krw",
}
UNITS = {
    "electricity_quantity": "kWh", "gas_quantity": "m3",
    "heating_quantity": "Mcal", "hot_water_quantity": "tonne",
    "water_quantity": "m3", "amounts": "KRW",
}


class ApartmentEnergyMonthly(Base):
    __tablename__ = "apartment_energy_monthly"
    __table_args__ = (UniqueConstraint("complex_code", "year_month", "source"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    complex_code: Mapped[str] = mapped_column(String, index=True)
    year_month: Mapped[str] = mapped_column(String, index=True)
    electricity_quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    electricity_amount_krw: Mapped[float | None] = mapped_column(Float, nullable=True)
    gas_quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    gas_amount_krw: Mapped[float | None] = mapped_column(Float, nullable=True)
    heating_quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    heating_amount_krw: Mapped[float | None] = mapped_column(Float, nullable=True)
    hot_water_quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    hot_water_amount_krw: Mapped[float | None] = mapped_column(Float, nullable=True)
    water_quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    water_amount_krw: Mapped[float | None] = mapped_column(Float, nullable=True)
    units: Mapped[dict] = mapped_column(JSON, default=dict)
    electricity_carbon_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    grid_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    source: Mapped[str] = mapped_column(String, default="K-apt")
    raw_source_id: Mapped[str | None] = mapped_column(String, nullable=True)
    quality_status: Mapped[str] = mapped_column(String)
    provider_code: Mapped[str | None] = mapped_column(String, nullable=True)
    raw_record: Mapped[dict] = mapped_column(JSON, default=dict)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class ComplexGridMapping(Base):
    __tablename__ = "complex_grid_mapping"

    complex_code: Mapped[str] = mapped_column(String, primary_key=True)
    grid_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    method: Mapped[str] = mapped_column(String)
    distance_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    overlap_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    match_status: Mapped[str] = mapped_column(String)
    matched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


def _number(value: Any) -> float | None:
    if value is None or (isinstance(value, str) and value.strip() in {"", "-"}):
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _json_or_xml(body: bytes) -> tuple[str, str, list[dict[str, Any]]]:
    try:
        payload = json.loads(body.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        root = ET.fromstring(body)
        # Gateway errors use <OpenAPI_ServiceResponse><cmmMsgHeader><returnReasonCode>.
        code = root.findtext(".//resultCode") or root.findtext(".//returnReasonCode") or ""
        message = root.findtext(".//resultMsg") or root.findtext(".//errMsg") or ""
        return code, message, [{child.tag: child.text for child in item} for item in root.findall(".//item")]
    if isinstance(payload, dict) and "OpenAPI_ServiceResponse" in payload:
        header = (payload.get("OpenAPI_ServiceResponse") or {}).get("cmmMsgHeader") or {}
        return str(header.get("returnReasonCode", "")), str(header.get("errMsg", "")), []
    response = payload.get("response", payload) if isinstance(payload, dict) else {}
    header = response.get("header") or {}
    code = str(header.get("resultCode", response.get("resultCode", "")))
    message = str(header.get("resultMsg", response.get("resultMsg", "")))
    response_body = response.get("body") or {}
    items: Any = response_body.get("item")
    if items is None:
        container = response_body.get("items") or {}
        items = container.get("item") if isinstance(container, dict) else container
    if items is None:
        items = []
    if isinstance(items, dict):
        items = [items]
    return code, message, list(items)


def parse_kapt_energy_response(body: bytes) -> dict[str, Any]:
    try:
        code, message, items = _json_or_xml(body)
    except (ET.ParseError, TypeError, ValueError) as exc:
        raise ExternalError("K-apt 응답 파싱 실패") from exc
    code = code.strip()
    if code == "03":
        # NODATA_ERROR: the provider has no record for this complex and month. Valid empty result.
        return {"provider_code": code, "provider_message": message, "rows": []}
    if not code or code.strip("0") != "":
        if code in AUTH_CODES:
            raise ExternalError("K-apt API 인증 실패: 서비스 활용 승인과 인증키를 확인하세요")
        if code == "22":
            raise ExternalError("K-apt API 일일 호출 한도 초과(22): 성공한 월은 건너뛰므로 다음 날 다시 실행하세요")
        if code in TRANSIENT_CODES:
            raise TransientProviderError(f"K-apt 제공기관 일시 오류: provider_code={code} {message}".strip())
        raise ExternalError(f"K-apt API 오류: provider_code={code or 'UNKNOWN'}")
    rows = []
    for item in items:
        row = {
            "complex_code": str(item.get("kaptCode") or ""),
            "year_month": str(item.get("reqDate") or ""),
            "units": dict(UNITS),
            "raw_record": dict(item),
        }
        for upstream, normalized in FIELD_MAP.items():
            row[normalized] = _number(item.get(upstream))
        rows.append(row)
    return {"provider_code": code, "provider_message": message, "rows": rows}


def classify_month(values: dict[str, float | None], households: int | None) -> tuple[str, dict[str, float | None], str | None]:
    """Classify one complex-month and return (status, cleaned quantities, reason).

    * every quantity 0/None -> NOT_REPORTED (all quantities null; not zero use)
    * individual 0 -> null (K-apt uses 0 for an item that was not entered)
    * electricity below MIN_PLAUSIBLE_KWH_PER_HOUSEHOLD per household -> SUSPECT
    """
    cleaned = {field: (None if values.get(field) in (None, 0, 0.0) else values.get(field)) for field in QUANTITY_FIELDS}
    if all(value is None for value in cleaned.values()):
        return "NOT_REPORTED", {field: None for field in QUANTITY_FIELDS}, "모든 사용량 항목이 0 또는 공란(미보고)"
    electricity = cleaned["electricity_quantity"]
    if electricity is not None and households and households > 0 and electricity / households < MIN_PLAUSIBLE_KWH_PER_HOUSEHOLD:
        return "SUSPECT", cleaned, f"세대당 전기 {electricity / households:.2f}kWh/월 < {MIN_PLAUSIBLE_KWH_PER_HOUSEHOLD:.0f}kWh (비현실적 값)"
    return "SUCCESS", cleaned, None


def _is_transient(message: str) -> bool:
    return any(marker in message for marker in ("일시 오류", "provider_code=UNKNOWN", "외부 데이터 HTTP 5", "외부 서비스 연결 실패"))


def _fetch_month(session: Any, url: str, key: str, code: str, month: str, attempts: int = 3, sleep: Any = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Request one complex-month, retrying temporary provider failures without reusing a cached failure."""
    import time
    pause = sleep or time.sleep
    forget = getattr(session, "forget", None)
    for attempt in range(attempts):
        result = None
        try:
            result = session.get("kapt-energy", f"monthly-{code}-{month}", url, {"serviceKey": key, "kaptCode": code, "reqDate": month})
            return result, parse_cached_response(session, result, parse_kapt_energy_response)
        except ExternalError as exc:
            if not (isinstance(exc, TransientProviderError) or _is_transient(str(exc))):
                raise
            cached = result or exc.asset
            if forget and isinstance(cached, dict):
                forget(cached)
            if attempt == attempts - 1:
                raise TransientProviderError(str(exc)) from None
            pause(2 * (attempt + 1))
    raise TransientProviderError("K-apt 제공기관 일시 오류")


def _unsync_observation(db: Any, complex_row: Any, month: str) -> None:
    """Remove a K-apt electricity observation that is no longer a valid SUCCESS value."""
    if not complex_row.bjd_code or not complex_row.bun:
        return
    observation = db.scalar(select(EnergyMonthly).filter_by(
        sigungu_code=complex_row.bjd_code[:5], bjdong_code=complex_row.bjd_code[5:], lot_type="0",
        bun=str(complex_row.bun).zfill(4), ji=str(complex_row.ji or "0").zfill(4), use_ym=month, energy_type="ELECTRICITY"))
    if observation is not None and observation.source == "K-apt":
        db.delete(observation)


def _apply_month(db: Any, complex_row: Any, row: "ApartmentEnergyMonthly", row_data: dict[str, Any] | None) -> str:
    """Store one complex-month with its classification and keep energy_monthly in sync."""
    if row_data is None:
        row.quality_status = "EMPTY_VALID"
        for field in FIELD_MAP.values():
            setattr(row, field, None)
        row.units = dict(UNITS)
        row.raw_record = {}
    else:
        values = {field: row_data.get(field) for field in QUANTITY_FIELDS}
        status, cleaned, reason = classify_month(values, complex_row.households)
        for field in FIELD_MAP.values():
            value = row_data.get(field)
            setattr(row, field, None if value in (0, 0.0) else value)
        for field, value in cleaned.items():
            setattr(row, field, value)
        row.units = row_data.get("units") or dict(UNITS)
        row.raw_record = dict(row_data.get("raw_record") or {}, **({"quality_reason": reason} if reason else {}))
        row.quality_status = status
    row.grid_id = complex_row.grid_id
    row.electricity_carbon_kg = row.electricity_quantity * ELECTRICITY_FACTOR if row.quality_status == "SUCCESS" and row.electricity_quantity is not None else None
    db.add(row)
    db.flush()
    if row.quality_status == "SUCCESS" and row.electricity_quantity is not None:
        _sync_electricity_observation(db, complex_row, row)
    else:
        _unsync_observation(db, complex_row, row.year_month)
    return row.quality_status


def reclassify_existing(db: Any) -> dict[str, int]:
    """Re-apply the no-report/plausibility rules to rows stored by earlier versions (idempotent)."""
    from .kapt import ApartmentComplex
    complexes = {row.kapt_code: row for row in db.scalars(select(ApartmentComplex))}
    counts: dict[str, int] = {}
    for row in db.scalars(select(ApartmentEnergyMonthly).where(ApartmentEnergyMonthly.source == "K-apt")):
        complex_row = complexes.get(row.complex_code)
        if complex_row is None or row.quality_status not in {"SUCCESS", "SUSPECT", "NOT_REPORTED"} or not row.raw_record:
            continue
        raw = {key: value for key, value in row.raw_record.items() if key != "quality_reason"}
        data = {"raw_record": raw, "units": row.units}
        for upstream, normalized in FIELD_MAP.items():
            data[normalized] = _number(raw.get(upstream))
        status = _apply_month(db, complex_row, row, data)
        counts[status] = counts.get(status, 0) + 1
    db.commit()
    return counts


def _source(db: Any) -> DataSource:
    source = db.get(DataSource, "kapt_energy") or DataSource(
        id="kapt_energy", category="건물 에너지", name="K-apt 공동주택 월별 에너지",
        organization="국토교통부 / 한국부동산원", source_url=KAPT_ENERGY_CATALOG_URL,
        source_type="OFFICIAL", status="NOT_COLLECTED",
        limitation="단지 공용 관리정보 기준입니다. 전기만 kWh이며 가스·난방·급탕은 단위가 달라 합산하지 않습니다.",
    )
    db.add(source)
    db.flush()
    return source


def _targets(db: Any, scope: str) -> list[Any]:
    from .kapt import ApartmentComplex, PROTOTYPE_KAPT_CODE
    rows = list(db.scalars(select(ApartmentComplex).order_by(ApartmentComplex.kapt_code)))
    rows.sort(key=lambda row: (row.kapt_code != PROTOTYPE_KAPT_CODE, row.kapt_code))
    return rows[:1] if scope == "smoke" else rows[:3] if scope == "limited" else rows


def _record_raw(db: Any, source: DataSource, raw_path: Path, result: dict[str, Any], code: str, month: str, rows: int, status: str) -> str:
    body = raw_path.read_bytes()
    digest = hashlib.sha256(body + f"{code}:{month}".encode()).hexdigest()
    asset = db.get(RawDataAsset, digest) or RawDataAsset(
        id=digest, source_id=source.id, provider=source.organization, source_url=KAPT_ENERGY_CATALOG_URL,
        reference_period=month, storage_location=str(raw_path), collection_status=status,
    )
    asset.row_count = rows
    asset.request_parameters = {"complex_code": code, "year_month": month, "http_status": result.get("status")}
    asset.error = None if status == "COLLECTED" else status
    db.add(asset)
    db.flush()
    return digest


def _sync_electricity_observation(db: Any, complex_row: Any, row: ApartmentEnergyMonthly) -> None:
    if row.quality_status != "SUCCESS" or row.electricity_quantity is None or not complex_row.bjd_code or not complex_row.bun:
        return
    identity = {
        "sigungu_code": complex_row.bjd_code[:5], "bjdong_code": complex_row.bjd_code[5:],
        "lot_type": "0", "bun": str(complex_row.bun).zfill(4), "ji": str(complex_row.ji or "0").zfill(4),
        "use_ym": row.year_month, "energy_type": "ELECTRICITY",
    }
    observation = db.scalar(select(EnergyMonthly).filter_by(**identity))
    if observation and observation.source != "K-apt":
        return
    if observation is None:
        observation = EnergyMonthly(source="K-apt", **identity)
    observation.usage_kwh = row.electricity_quantity
    observation.grid_id = complex_row.grid_id
    observation.match_method = "KAPT_COMPLEX_CENTROID" if complex_row.grid_id else "UNMATCHED_KAPT_POINT"
    observation.raw_record = {
        "kapt_code": complex_row.kapt_code, "quantity_unit": "kWh",
        "matched_gross_floor_area_m2": complex_row.gross_floor_area_m2,
        "raw_source_id": row.raw_source_id,
    }
    db.add(observation)


def collect_kapt_energy(
    db: Any, year: int, scope: str = "smoke", *, client: CachedClient | None = None,
    service_key: str | None = None, data_dir: str | Path | None = None,
) -> dict[str, int]:
    if scope not in {"smoke", "limited", "full"}:
        raise ValueError("scope must be smoke, limited, or full")
    key = (service_key or os.getenv("DATA_GO_KR_SERVICE_KEY", "")).strip()
    if not key:
        raise ExternalError("K-apt API 인증 실패: DATA_GO_KR_SERVICE_KEY 미설정")
    source = _source(db)
    reclassify_existing(db)
    if scope == "full":
        smoke = db.scalar(select(ApartmentEnergyMonthly.id).where(
            ApartmentEnergyMonthly.year_month == f"{year}01",
            ApartmentEnergyMonthly.quality_status.in_(sorted(ANSWERED)),
        ).limit(1))
        if not smoke:
            raise ValueError("K-apt full 수집 전에 같은 연도의 smoke 성공이 필요합니다")
    targets = _targets(db, scope)
    if not targets:
        raise ValueError("K-apt 단지 기본정보가 없습니다")
    months = [f"{year}01"] if scope == "smoke" else [f"{year}{month:02d}" for month in range(1, 13)]
    root = Path(data_dir or os.getenv("DATA_DIR", "data"))
    raw_root = root / "raw" / "kapt-energy" / str(year)
    raw_root.mkdir(parents=True, exist_ok=True)
    delay = max(float(os.getenv("KAPT_ENERGY_REQUEST_DELAY_MS", "250")) / 1000, 0)
    session = client or CachedClient(root / "cache" / "kapt-energy", min_interval=delay)
    base_url = os.getenv("KAPT_ENERGY_BASE_URL", KAPT_ENERGY_BASE_URL).rstrip("/")
    stats = {"requested": 0, "normalized": 0, "skipped": 0, "empty": 0, "not_reported": 0, "suspect": 0, "failed": 0}
    url = f"{base_url}/{KAPT_ENERGY_OPERATION}"
    for complex_row in targets:
        mapping = db.get(ComplexGridMapping, complex_row.kapt_code) or ComplexGridMapping(complex_code=complex_row.kapt_code)
        mapping.grid_id = complex_row.grid_id
        mapping.method = "KAPT_POINT_PROJECT_GRID" if complex_row.grid_id else "UNMATCHED"
        mapping.confidence = 1.0 if complex_row.grid_id else None
        mapping.match_status = "MATCHED" if complex_row.grid_id else "UNMATCHED"
        mapping.matched_at = datetime.now(timezone.utc)
        db.add(mapping)
        for month in months:
            ident = f"{complex_row.kapt_code}:{month}:K-apt"
            existing = db.get(ApartmentEnergyMonthly, ident)
            if existing and existing.quality_status in ANSWERED:
                stats["skipped"] += 1
                continue
            stats["requested"] += 1
            row = existing or ApartmentEnergyMonthly(id=ident, complex_code=complex_row.kapt_code, year_month=month, source="K-apt")
            try:
                result, parsed = _fetch_month(session, url, key, complex_row.kapt_code, month)
            except TransientProviderError as exc:
                # Keep going: one provider hiccup must not discard the rest of the run.
                row.quality_status = "FAILED"
                row.provider_code = str(exc)[:120]
                row.units = row.units or dict(UNITS)
                row.raw_record = row.raw_record or {}
                row.collected_at = datetime.now(timezone.utc)
                db.add(row)
                db.commit()
                stats["failed"] += 1
                continue
            raw_dir = raw_root / complex_row.kapt_code
            raw_dir.mkdir(parents=True, exist_ok=True)
            raw_path = raw_dir / f"{month}.json"
            raw_path.write_bytes(result["body"])
            row_data = next((item for item in parsed["rows"] if not item["complex_code"] or item["complex_code"] == complex_row.kapt_code), None)
            asset_id = _record_raw(db, source, raw_path, result, complex_row.kapt_code, month, len(parsed["rows"]), "COLLECTED")
            row.provider_code = parsed["provider_code"]
            row.raw_source_id = asset_id
            status = _apply_month(db, complex_row, row, row_data)
            stats[{"SUCCESS": "normalized", "EMPTY_VALID": "empty", "NOT_REPORTED": "not_reported", "SUSPECT": "suspect"}[status]] += 1
            row.collected_at = datetime.now(timezone.utc)
            db.add(row)
            db.commit()
    total = db.scalar(select(func.count()).select_from(ApartmentEnergyMonthly)) or 0
    complexes = db.scalar(select(func.count(func.distinct(ApartmentEnergyMonthly.complex_code)))) or 0
    by_status = dict(db.execute(select(ApartmentEnergyMonthly.quality_status, func.count()).group_by(ApartmentEnergyMonthly.quality_status)).all())
    reporting = db.scalar(select(func.count(func.distinct(ApartmentEnergyMonthly.complex_code))).where(ApartmentEnergyMonthly.quality_status == "SUCCESS")) or 0
    source.normalized_row_count = int(by_status.get("SUCCESS", 0))
    source.raw_row_count = db.scalar(select(func.count()).select_from(RawDataAsset).where(RawDataAsset.source_id == source.id)) or 0
    source.missing_count = int(by_status.get("NOT_REPORTED", 0) + by_status.get("EMPTY_VALID", 0) + by_status.get("FAILED", 0))
    source.reference_period = f"{year}-01 ~ {year}-12" if scope != "smoke" else f"{year}-01"
    source.status = "COLLECTED" if scope == "full" and stats["failed"] == 0 else "PARTIAL"
    source.quality = (
        f"요청 단지 {complexes}개 중 사용량 보고 {reporting}개 / 유효 {by_status.get('SUCCESS', 0)}행 · "
        f"미보고 {by_status.get('NOT_REPORTED', 0)}행 · 이상값 {by_status.get('SUSPECT', 0)}행 · "
        f"일시 오류 {by_status.get('FAILED', 0)}행 / {scope} 수집"
    )
    stats["total_rows"] = int(total)
    source.collected_at = datetime.now(timezone.utc)
    db.commit()
    return stats
