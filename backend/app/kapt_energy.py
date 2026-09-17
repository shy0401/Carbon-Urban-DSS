"""Official K-apt monthly energy collection with resumable scopes."""
from __future__ import annotations

import hashlib
import json
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import JSON, DateTime, Float, String, Text, UniqueConstraint, func, select
from sqlalchemy.orm import Mapped, mapped_column

from .cache import CachedClient, ExternalError
from .db import Base
from .models import DataSource, EnergyMonthly, RawDataAsset

KAPT_ENERGY_CATALOG_URL = "https://www.data.go.kr/data/15012964/openapi.do"
KAPT_ENERGY_BASE_URL = "https://apis.data.go.kr/1613000/ApHusEnergyUseInfoOfferServiceV2"
KAPT_ENERGY_OPERATION = "getHsmpApHusUsgQtyInfoSearchV2"
ELECTRICITY_FACTOR = 0.4541

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
        code = root.findtext(".//resultCode") or ""
        message = root.findtext(".//resultMsg") or ""
        return code, message, [{child.tag: child.text for child in item} for item in root.findall(".//item")]
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
    if code not in {"0", "00"}:
        if code in {"20", "30"}:
            raise ExternalError("K-apt API 인증 실패: 서비스 활용 승인과 인증키를 확인하세요")
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
    if scope == "full":
        smoke = db.scalar(select(ApartmentEnergyMonthly.id).where(
            ApartmentEnergyMonthly.year_month == f"{year}01",
            ApartmentEnergyMonthly.quality_status.in_(["SUCCESS", "EMPTY_VALID"]),
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
    stats = {"requested": 0, "normalized": 0, "skipped": 0, "empty": 0, "failed": 0}
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
            if existing and existing.quality_status in {"SUCCESS", "EMPTY_VALID"}:
                stats["skipped"] += 1
                continue
            stats["requested"] += 1
            result = session.get(
                "kapt-energy", f"monthly-{complex_row.kapt_code}-{month}",
                f"{base_url}/{KAPT_ENERGY_OPERATION}",
                {"serviceKey": key, "kaptCode": complex_row.kapt_code, "reqDate": month},
            )
            raw_dir = raw_root / complex_row.kapt_code
            raw_dir.mkdir(parents=True, exist_ok=True)
            raw_path = raw_dir / f"{month}.json"
            raw_path.write_bytes(result["body"])
            parsed = parse_kapt_energy_response(result["body"])
            row_data = next((row for row in parsed["rows"] if not row["complex_code"] or row["complex_code"] == complex_row.kapt_code), None)
            asset_id = _record_raw(db, source, raw_path, result, complex_row.kapt_code, month, len(parsed["rows"]), "COLLECTED")
            row = existing or ApartmentEnergyMonthly(id=ident, complex_code=complex_row.kapt_code, year_month=month, source="K-apt")
            if row_data is None:
                row.quality_status = "EMPTY_VALID"
                row.units = dict(UNITS)
                row.raw_record = {}
                stats["empty"] += 1
            else:
                for field in FIELD_MAP.values():
                    setattr(row, field, row_data[field])
                row.units = row_data["units"]
                row.raw_record = row_data["raw_record"]
                row.quality_status = "SUCCESS"
                stats["normalized"] += 1
            row.grid_id = complex_row.grid_id
            row.provider_code = parsed["provider_code"]
            row.raw_source_id = asset_id
            row.electricity_carbon_kg = row.electricity_quantity * ELECTRICITY_FACTOR if row.electricity_quantity is not None else None
            row.collected_at = datetime.now(timezone.utc)
            db.add(row)
            db.flush()
            _sync_electricity_observation(db, complex_row, row)
            db.commit()
    total = db.scalar(select(func.count()).select_from(ApartmentEnergyMonthly)) or 0
    complexes = db.scalar(select(func.count(func.distinct(ApartmentEnergyMonthly.complex_code)))) or 0
    source.normalized_row_count = total
    source.raw_row_count = db.scalar(select(func.count()).select_from(RawDataAsset).where(RawDataAsset.source_id == source.id)) or 0
    source.missing_count = stats["empty"]
    source.reference_period = f"{year}-01 ~ {year}-12" if scope != "smoke" else f"{year}-01"
    source.status = "COLLECTED" if scope == "full" and stats["failed"] == 0 else "PARTIAL"
    source.quality = f"단지 {complexes}개 / 월별 {total}행 / {scope} 수집"
    source.collected_at = datetime.now(timezone.utc)
    db.commit()
    return stats
