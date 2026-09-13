"""K-apt public-data adapter for Jeonju apartment metadata and energy use.

The apartment list and detail endpoints are public K-apt web endpoints. Monthly
energy quantities use the separate, official data.go.kr API and therefore need a
registered service key. Cost fields are deliberately excluded: won is never
converted to kWh, m3, Mcal, or tonnes.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote

import httpx
from pyproj import Transformer
from sqlalchemy import JSON, Boolean, Float, Integer, String, Text, select
from sqlalchemy.orm import Mapped, mapped_column

from .cache import CachedClient, ExternalError
from .db import Base
from .settings import offline_mode


KAPT_BASE = "https://www.k-apt.go.kr"
KAPT_MAIN_URL = f"{KAPT_BASE}/web/main/index.do"
KAPT_LIST_URL = f"{KAPT_BASE}/kaptinfo/getKaptList.do"
KAPT_DETAIL_URL = f"{KAPT_BASE}/kaptinfo/getKaptInfo_detail.do"
KAPT_ENERGY_URL = (
    "https://apis.data.go.kr/1613000/ApHusEnergyUseInfoOfferServiceV2/"
    "getHsmpApHusUsgQtyInfoSearchV2"
)
KAPT_ENERGY_CATALOG_URL = "https://www.data.go.kr/data/15012964/openapi.do"
KAPT_BASIC_CATALOG_URL = "https://www.data.go.kr/data/15096285/standard.do"
KAPT_MAP_JS_URL = f"{KAPT_BASE}/knew/js/knew_map.js?v=2"

# This is the exact proj4 definition published in K-apt's knew_map.js.  The
# comment in that file identifies the old NGII modified central-origin system
# (EPSG:5175 family); retaining the literal definition avoids datum ambiguity.
KAPT_SOURCE_CRS = (
    "+proj=tmerc +lat_0=38 +lon_0=127.0028902777778 +k=1 "
    "+x_0=200000 +y_0=500000 +ellps=bessel +units=m +no_defs "
    "+towgs84=-115.80,474.99,674.11,1.16,-2.31,-1.63,6.43"
)
_TO_WGS84 = Transformer.from_crs(KAPT_SOURCE_CRS, "EPSG:4326", always_xy=True)
_TO_GRID = Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)

JEONJU_DISTRICTS = {
    "52111": "완산구",
    "52113": "덕진구",
}
PROTOTYPE_KAPT_CODE = "A56121109"  # 호성동 엘지동아
ENERGY_QUANTITY_UNITS = {
    "helect": "kWh",
    "hgas": "m3",
    "hheat": "Mcal",
    "hwaterHot": "tonne",
}


class ApartmentComplex(Base):
    __tablename__ = "apartment_complexes"

    kapt_code: Mapped[str] = mapped_column(String, primary_key=True)
    snapshot_month: Mapped[str] = mapped_column(String, index=True)
    name: Mapped[str] = mapped_column(String)
    bjd_code: Mapped[str | None] = mapped_column(String, index=True)
    bun: Mapped[str | None] = mapped_column(String)
    ji: Mapped[str | None] = mapped_column(String)
    parcel_address: Mapped[str | None] = mapped_column(Text)
    road_address: Mapped[str | None] = mapped_column(Text)
    approval_date: Mapped[str | None] = mapped_column(String)
    first_occupancy_month: Mapped[str | None] = mapped_column(String)
    gross_floor_area_m2: Mapped[float | None] = mapped_column(Float)
    management_area_m2: Mapped[float | None] = mapped_column(Float)
    households: Mapped[int | None] = mapped_column(Integer)
    building_count: Mapped[int | None] = mapped_column(Integer)
    heating_type: Mapped[str | None] = mapped_column(String)
    source_x: Mapped[float | None] = mapped_column(Float)
    source_y: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float, index=True)
    latitude: Mapped[float | None] = mapped_column(Float, index=True)
    grid_id: Mapped[str | None] = mapped_column(String, index=True)
    detail_collected: Mapped[bool] = mapped_column(Boolean, default=False)
    summary_json: Mapped[dict] = mapped_column(JSON)
    detail_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class MunicipalApartment(Base):
    __tablename__ = "municipal_apartments"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    serial_number: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String)
    housing_use: Mapped[str | None] = mapped_column(String)
    district: Mapped[str | None] = mapped_column(String)
    administrative_dong: Mapped[str | None] = mapped_column(String)
    parcel_location: Mapped[str | None] = mapped_column(Text)
    site_area_m2: Mapped[float | None] = mapped_column(Float)
    gross_floor_area_m2: Mapped[float | None] = mapped_column(Float)
    building_count: Mapped[int | None] = mapped_column(Integer)
    max_floors: Mapped[int | None] = mapped_column(Integer)
    households: Mapped[int | None] = mapped_column(Integer)
    raw_record: Mapped[dict] = mapped_column(JSON)


class MunicipalApartmentUnderConstruction(Base):
    __tablename__ = "municipal_apartments_under_construction"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    serial_number: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String)
    district: Mapped[str | None] = mapped_column(String)
    administrative_dong: Mapped[str | None] = mapped_column(String)
    parcel_location: Mapped[str | None] = mapped_column(Text)
    site_area_m2: Mapped[float | None] = mapped_column(Float)
    gross_floor_area_m2: Mapped[float | None] = mapped_column(Float)
    households: Mapped[int | None] = mapped_column(Integer)
    raw_record: Mapped[dict] = mapped_column(JSON)


def _raw_dir(path: str | Path | None = None) -> Path:
    target = Path(path) if path else Path(os.getenv("DATA_DIR", "data")) / "raw" / "research"
    target.mkdir(parents=True, exist_ok=True)
    return target


def _client(raw_dir: Path | None = None) -> CachedClient:
    root = (raw_dir or _raw_dir()).parents[1] / "cache" / "kapt"
    transport = httpx.Client(
        timeout=30,
        follow_redirects=True,
        headers={"User-Agent": "Carbon-Urban-DSS/1.0 public-data-research", "Accept-Language": "ko-KR,ko;q=0.9"},
    )
    return CachedClient(root, client=transport, min_interval=0.3)


def fetch_complex_lists(client: CachedClient, search_month: str = "202512") -> dict[str, list[dict[str, Any]]]:
    """Fetch both Jeonju district lists using K-apt's CSRF-protected public form."""
    landing = client.get("kapt", "main", KAPT_MAIN_URL)
    text = landing["body"].decode("utf-8", "replace")
    match = re.search(r'<meta\s+name="_csrf"\s+content="([^"]+)"', text)
    if not match:
        raise RuntimeError("K-apt main page did not contain a CSRF token")
    token = match.group(1)
    headers = {"X-CSRF-TOKEN": token, "X-Requested-With": "XMLHttpRequest"}
    if offline_mode():
        raise ExternalError("오프라인 모드: 로컬 K-apt 목록 파일이 없어 외부 호출을 차단했습니다.")
    result: dict[str, list[dict[str, Any]]] = {}
    for district_code in JEONJU_DISTRICTS:
        response = client.client.post(
            KAPT_LIST_URL,
            data={
                "bjdCode": district_code,
                "kaptName": "",
                "searchDate": search_month,
                "kaptDuty": "ALL",
                "_csrf": token,
            },
            headers=headers,
        )
        response.raise_for_status()
        payload = response.json()
        result[district_code] = payload.get("resultList", [])
    return result


def fetch_complex_detail(client: CachedClient, kapt_code: str) -> dict[str, Any]:
    result = client.get("kapt", f"detail-{kapt_code}", KAPT_DETAIL_URL, {"kaptCode": kapt_code})
    payload = json.loads(result["body"].decode("utf-8"))
    if not payload.get("resultMap_kapt"):
        raise RuntimeError(f"K-apt returned no detail for {kapt_code}")
    return payload


def _coordinates(record: dict[str, Any]) -> tuple[float | None, float | None]:
    x, y = record.get("x"), record.get("y")
    if x is None or y is None:
        x, y = record.get("coordX"), record.get("coordY")
    if x is None or y is None:
        return None, None
    lon, lat = _TO_WGS84.transform(float(x), float(y))
    return round(lon, 10), round(lat, 10)


def normalize_summary(record: dict[str, Any], district_code: str, search_month: str) -> dict[str, Any]:
    lon, lat = _coordinates(record)
    return {
        "source_system": "K-apt",
        "snapshot_query_month": search_month,
        "district_code": district_code,
        "district_name": JEONJU_DISTRICTS[district_code],
        "kapt_code": record.get("kaptCode"),
        "kapt_name": record.get("kaptName"),
        "bjd_code": record.get("bjdCode"),
        "bjd_name": record.get("bjdName"),
        "bun": record.get("bun1"),
        "ji": record.get("bun2"),
        "parcel_address": (record.get("addr") or "").strip(),
        "approval_month": record.get("kaptUsedate"),
        "first_occupancy_month": record.get("occuFirstDate"),
        "source_x": record.get("x"),
        "source_y": record.get("y"),
        "longitude": lon,
        "latitude": lat,
        "detail_url": f"{KAPT_DETAIL_URL}?kaptCode={record.get('kaptCode')}",
    }


def normalize_detail(payload: dict[str, Any]) -> dict[str, Any]:
    apartment = payload["resultMap_kapt"]
    location = payload.get("evacInfo") or {}
    lon, lat = _coordinates(location)
    addresses = {row.get("addrGbn"): row.get("addr") for row in payload.get("resultMap_kapt_addrList", [])}
    return {
        "source_system": "K-apt",
        "kapt_code": apartment.get("kaptCode"),
        "kapt_name": apartment.get("kaptName"),
        "bjd_code": location.get("bjdCode"),
        "parcel_address": addresses.get("B"),
        "road_address": addresses.get("R"),
        # K-apt's data.go.kr schema defines kaptTarea as building-register gross area.
        "building_register_gross_floor_area_m2": apartment.get("kaptTarea"),
        "kapt_management_area_m2": apartment.get("kaptMarea"),
        "management_fee_area_m2": apartment.get("mngKaptMarea"),
        "households": apartment.get("kaptdaTCnt"),
        "building_count": apartment.get("kaptDongCnt"),
        "approval_date": apartment.get("kaptUsedate"),
        "heating_type": apartment.get("codeHeat"),
        "sale_type": apartment.get("codeSale"),
        "housing_type": apartment.get("codeApt"),
        "source_x": location.get("x"),
        "source_y": location.get("y"),
        "longitude": lon,
        "latitude": lat,
        "source_crs": KAPT_SOURCE_CRS,
        "detail_url": f"{KAPT_DETAIL_URL}?kaptCode={apartment.get('kaptCode')}",
    }


def fetch_monthly_energy(
    kapt_code: str,
    request_month: str,
    service_key: str | None = None,
    client: CachedClient | None = None,
) -> list[dict[str, Any]]:
    """Return official monthly physical quantities with their declared units.

    ``request_month`` is YYYYMM. The function omits monetary fields even though
    the upstream response contains them.
    """
    key = unquote((service_key or os.getenv("DATA_GO_KR_SERVICE_KEY", "")).strip())
    if not key:
        raise RuntimeError("K-apt monthly energy API requires DATA_GO_KR_SERVICE_KEY")
    session = client or _client()
    result = session.get(
        "kapt-energy", f"monthly-{kapt_code}-{request_month}", KAPT_ENERGY_URL,
        {"serviceKey": key, "kaptCode": kapt_code, "reqDate": request_month, "pageNo": 1, "numOfRows": 100, "_type": "json"},
    )
    body_bytes = result["body"]
    try:
        payload = json.loads(body_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = None
    if payload and isinstance(payload, dict) and payload.get("response"):
        header = payload.get("response", {}).get("header", {})
        result_code = str(header.get("resultCode", ""))
        if result_code not in {"00", "0"}:
            raise RuntimeError(f"K-apt monthly energy API rejected the request: resultCode={result_code}")
        body = payload.get("response", {}).get("body", {})
        item_container = body.get("items") or {}
        items = item_container.get("item", []) if isinstance(item_container, dict) else []
        if isinstance(items, dict):
            items = [items]
    else:
        try:
            root = ET.fromstring(body_bytes)
        except ET.ParseError as exc:
            raise RuntimeError("K-apt monthly energy response was neither valid JSON nor XML") from exc
        result_code = root.findtext(".//resultCode") or ""
        if result_code not in {"00", "0"}:
            raise RuntimeError(f"K-apt monthly energy API rejected the request: resultCode={result_code}")
        items = [{child.tag: child.text for child in node} for node in root.findall(".//item")]
    rows = []
    for item in items:
        row = {"kapt_code": item.get("kaptCode", kapt_code), "request_month": item.get("reqDate", request_month)}
        for field, unit in ENERGY_QUANTITY_UNITS.items():
            row[field] = item.get(field)
            row[f"{field}_unit"] = unit
        rows.append(row)
    return rows


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _has_decoding_damage(path: Path) -> bool:
    try:
        return "�" in path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return True


def _grid_id(longitude: float | None, latitude: float | None) -> str | None:
    if longitude is None or latitude is None:
        return None
    x, y = _TO_GRID.transform(longitude, latitude)
    return f"cell_{math.floor(x / 500) * 500}_{math.floor(y / 500) * 500}"


def _parcel(value: Any) -> str | None:
    digits = re.sub(r"\D", "", str(value or ""))
    return digits.zfill(4) if digits else None


def _file_time(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)


def _record_asset(db: Any, source_id: str, path: Path, rows: int, url: str, period: str) -> None:
    from .models import DataSource, RawDataAsset
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    asset = db.get(RawDataAsset, digest) or RawDataAsset(
        id=digest, source_id=source_id, provider=db.get(DataSource, source_id).organization,
        source_url=url, reference_period=period, storage_location=str(path), collection_status="COLLECTED",
    )
    asset.row_count = rows
    asset.collected_at = _file_time(path)
    asset.request_parameters = {}
    db.add(asset)


def _register_kapt(db: Any, raw_dir: Path, summaries: list[dict[str, Any]], details: list[tuple[dict[str, Any], dict[str, Any]]], search_month: str) -> None:
    from .models import DataSource
    detail_map = {row["kapt_code"]: (row, raw) for row, raw in details}
    for row in summaries:
        detail_pair = detail_map.get(row["kapt_code"])
        detail, raw_detail = detail_pair if detail_pair else ({}, None)
        item = db.get(ApartmentComplex, row["kapt_code"]) or ApartmentComplex(kapt_code=row["kapt_code"])
        item.snapshot_month = search_month
        item.name = row["kapt_name"]
        item.bjd_code = row.get("bjd_code")
        item.bun = _parcel(row.get("bun"))
        item.ji = _parcel(row.get("ji")) or "0000"
        item.parcel_address = detail.get("parcel_address") or row.get("parcel_address")
        item.road_address = detail.get("road_address")
        item.approval_date = detail.get("approval_date") or row.get("approval_month")
        item.first_occupancy_month = row.get("first_occupancy_month")
        item.gross_floor_area_m2 = detail.get("building_register_gross_floor_area_m2")
        item.management_area_m2 = detail.get("kapt_management_area_m2")
        item.households = detail.get("households")
        item.building_count = detail.get("building_count")
        item.heating_type = detail.get("heating_type")
        item.source_x = detail.get("source_x") or row.get("source_x")
        item.source_y = detail.get("source_y") or row.get("source_y")
        item.longitude = detail.get("longitude") or row.get("longitude")
        item.latitude = detail.get("latitude") or row.get("latitude")
        item.grid_id = _grid_id(item.longitude, item.latitude)
        item.detail_collected = bool(detail_pair)
        item.summary_json = row
        item.detail_json = raw_detail
        db.add(item)
    source = db.get(DataSource, "kapt") or DataSource(
        id="kapt", category="건축물 정보", name="K-apt 공동주택 단지 정보",
        organization="국토교통부 / 한국부동산원", source_url=KAPT_BASIC_CATALOG_URL, source_type="OFFICIAL",
    )
    source.status = "COLLECTED" if len(details) == len(summaries) else "PARTIAL"
    source.reference_period = search_month
    source.geographic_coverage = "전북특별자치도 전주시"
    source.raw_row_count = len(summaries)
    source.normalized_row_count = len(summaries)
    source.missing_count = len(summaries) - len(details)
    source.quality = f"전주시 단지 {len(summaries)}건 DB 정규화 / 상세 {len(details)}건"
    source.limitation = "목록은 조회 기준월, 상세는 수집 시점 현황입니다. 과거 연도 건축 상태와 동일하다고 단정하지 않습니다. 일부 단지는 연면적·세대수가 누락될 수 있습니다."
    evidence_paths = [raw_dir / f"kapt_jeonju_{code}_{search_month}.json" for code in JEONJU_DISTRICTS]
    evidence_paths += [raw_dir / f"kapt_detail_{row['kapt_code']}.json" for row, _ in details]
    source.collected_at = max(_file_time(path) for path in evidence_paths)
    db.add(source)
    db.flush()
    _record_asset(db, "kapt", raw_dir / "kapt_jeonju_summary.csv", len(summaries), KAPT_LIST_URL, search_month)
    _record_asset(db, "kapt", raw_dir / "kapt_jeonju_detail_candidates.csv", len(details), KAPT_DETAIL_URL, search_month)
    db.commit()


def _detail_codes(summaries: list[dict[str, Any]], raw_dir: Path, limit: int = 8) -> list[str]:
    anchor = next((row for row in summaries if row["kapt_code"] == PROTOTYPE_KAPT_CODE), summaries[0])
    same_dong = [row for row in summaries if row.get("bjd_code") == anchor.get("bjd_code") and row.get("longitude") and row.get("latitude")]
    ranked = sorted(same_dong, key=lambda row: (float(row["longitude"]) - float(anchor["longitude"])) ** 2 + (float(row["latitude"]) - float(anchor["latitude"])) ** 2)
    cached = {p.stem.removeprefix("kapt_detail_") for p in raw_dir.glob("kapt_detail_*.json")}
    cached_near = [row["kapt_code"] for row in ranked if row["kapt_code"] in cached]
    return (cached_near if len(cached_near) >= limit else [row["kapt_code"] for row in ranked])[:limit]


def collect_kapt(db: Any | None = None, raw_dir: str | Path | None = None, search_month: str = "202512", detail_codes: Iterable[str] | None = None, refresh: bool = False, max_details: int = 8) -> dict[str, Any]:
    """Materialize and, when ``db`` is supplied, upsert 364 complexes."""
    if not 1 <= max_details <= 500:
        raise ValueError('max_details must be between 1 and 500')
    target = _raw_dir(raw_dir)
    list_paths = {code: target / f"kapt_jeonju_{code}_{search_month}.json" for code in JEONJU_DISTRICTS}
    client = _client(target)
    try:
        if refresh or any(not path.exists() or _has_decoding_damage(path) for path in list_paths.values()):
            districts = fetch_complex_lists(client, search_month)
            for code, rows in districts.items():
                list_paths[code].write_text(json.dumps({"resultList": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            districts = {code: json.loads(path.read_text(encoding="utf-8"))["resultList"] for code, path in list_paths.items()}
        summaries = [normalize_summary(row, code, search_month) for code, rows in districts.items() for row in rows]
        selected = list(detail_codes) if detail_codes is not None else _detail_codes(summaries, target)
        known = {row['kapt_code'] for row in summaries}
        cached = [p.stem.removeprefix('kapt_detail_') for p in target.glob('kapt_detail_*.json') if p.stem.removeprefix('kapt_detail_') in known]
        selected = list(dict.fromkeys([code for code in selected[:max_details] if code in known] + sorted(cached)))
        details = []
        for kapt_code in selected:
            path = target / f"kapt_detail_{kapt_code}.json"
            if refresh or not path.exists() or _has_decoding_damage(path):
                payload = fetch_complex_detail(client, kapt_code)
                path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            else:
                payload = json.loads(path.read_text(encoding="utf-8"))
            details.append((normalize_detail(payload), payload))
    finally:
        client.client.close()
    normalized_details = [row for row, _ in details]
    _write_csv(target / "kapt_jeonju_summary.csv", summaries)
    _write_csv(target / "kapt_jeonju_detail_candidates.csv", normalized_details)
    provenance = {
        "provider": "국토교통부 / 한국부동산원 K-apt", "collected_at": max(_file_time(path) for path in list_paths.values()).isoformat(),
        "snapshot_query_month": search_month, "summary_rows": len(summaries), "detail_rows": len(details), "detail_codes": selected,
        "districts": JEONJU_DISTRICTS, "list_endpoint": KAPT_LIST_URL,
        "detail_endpoint_template": f"{KAPT_DETAIL_URL}?kaptCode={{kaptCode}}", "monthly_energy_endpoint": KAPT_ENERGY_URL,
        "monthly_energy_units": ENERGY_QUANTITY_UNITS, "monthly_energy_requires_registered_data_go_kr_key": True,
        "source_crs": KAPT_SOURCE_CRS, "coordinate_reference": KAPT_MAP_JS_URL,
    }
    (target / "kapt_provenance.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2), encoding="utf-8")
    if db is not None:
        _register_kapt(db, target, summaries, details, search_month)
    return {"summary_rows": len(summaries), "detail_rows": len(details), "raw_dir": str(target), "detail_codes": selected}


def _number(value: Any, integer: bool = False) -> float | int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value)) if integer else float(value)
    except (TypeError, ValueError):
        return None


def collect_municipal(db: Any, raw_dir: str | Path | None = None) -> dict[str, int]:
    """Normalize Jeonju's original 2025-12 XLS into separate status tables."""
    import xlrd
    from .models import DataSource
    target = _raw_dir(raw_dir)
    workbook_path = target / "jeonju_apartment_status_2025_12.xls"
    workbook = xlrd.open_workbook(str(workbook_path))
    completed_sheet, construction_sheet = workbook.sheet_by_index(0), workbook.sheet_by_index(1)
    completed = []
    for values in (completed_sheet.row_values(index) for index in range(3, completed_sheet.nrows)):
        serial = _number(values[0], True)
        if serial is None:
            continue
        raw = {f"column_{index + 1}": value for index, value in enumerate(values)}
        row = db.get(MunicipalApartment, f"jeonju-completed-{serial}") or MunicipalApartment(id=f"jeonju-completed-{serial}", serial_number=serial)
        row.name, row.housing_use, row.district, row.administrative_dong, row.parcel_location = values[1:6]
        row.site_area_m2, row.gross_floor_area_m2 = _number(values[6]), _number(values[7])
        row.building_count, row.max_floors, row.households = _number(values[10], True), _number(values[11], True), _number(values[13], True)
        row.raw_record = raw
        db.add(row)
        completed.append(row)
    construction = []
    for values in (construction_sheet.row_values(index) for index in range(2, construction_sheet.nrows)):
        serial = _number(values[0], True)
        if serial is None:
            continue
        raw = {f"column_{index + 1}": value for index, value in enumerate(values)}
        row = db.get(MunicipalApartmentUnderConstruction, f"jeonju-construction-{serial}") or MunicipalApartmentUnderConstruction(id=f"jeonju-construction-{serial}", serial_number=serial)
        row.name, row.district, row.administrative_dong, row.parcel_location = values[1], values[3], values[4], values[5]
        row.site_area_m2, row.gross_floor_area_m2 = _number(values[6]), _number(values[7])
        row.households = _number(values[13], True) if len(values) > 13 else None
        row.raw_record = raw
        db.add(row)
        construction.append(row)
    source = db.get(DataSource, "jeonju_apartments") or DataSource(
        id="jeonju_apartments", category="건축물 정보", name="전주시 공동주택 현황(2025.12월)",
        organization="전주시 재개발재건축과",
        source_url="https://www.jeonju.go.kr/planweb/board/view.9is?dataUid=9be517a89b212afa019b734df7f35e34&boardUid=ff8080818bad9295018bb25702581197",
        source_type="OFFICIAL",
    )
    source.status, source.reference_period = "COLLECTED", "2025-12-31"
    source.raw_row_count = source.normalized_row_count = len(completed) + len(construction)
    source.missing_count = 0
    source.quality = f"준공 {len(completed)}건 / 시공중 {len(construction)}건, 상태별 별도 테이블"
    source.limitation = "행정동·지번 제공, 좌표 및 법정동 코드는 미제공"
    source.collected_at = _file_time(workbook_path)
    db.add(source)
    db.flush()
    _record_asset(db, "jeonju_apartments", workbook_path, len(completed) + len(construction), source.source_url, "2025-12-31")
    db.commit()
    return {"completed_rows": len(completed), "under_construction_rows": len(construction)}


def candidate_energy_parcels(db: Any, limit: int = 3) -> list[dict[str, Any]]:
    """Return unambiguous, exact K-apt parcel keys for bounded MOLIT probes."""
    rows = list(db.scalars(select(ApartmentComplex).where(ApartmentComplex.bjd_code.is_not(None), ApartmentComplex.bun.is_not(None))))
    counts: dict[tuple[str, str, str], int] = {}
    for row in rows:
        key = (row.bjd_code, _parcel(row.bun), _parcel(row.ji) or "0000")
        counts[key] = counts.get(key, 0) + 1
    anchor = next((row for row in rows if row.kapt_code == PROTOTYPE_KAPT_CODE), None)
    rows.sort(key=lambda row: (
        row.kapt_code != PROTOTYPE_KAPT_CODE,
        row.grid_id != (anchor.grid_id if anchor else None),
        (row.longitude - anchor.longitude) ** 2 + (row.latitude - anchor.latitude) ** 2
        if anchor and anchor.longitude is not None and anchor.latitude is not None and row.longitude is not None and row.latitude is not None else float("inf"),
        row.kapt_code,
    ))
    result = []
    for row in rows:
        key = (row.bjd_code, _parcel(row.bun), _parcel(row.ji) or "0000")
        if counts[key] != 1 or "외" in (row.parcel_address or ""):
            continue
        result.append({
            "sigunguCd": row.bjd_code[:5], "bjdongCd": row.bjd_code[5:], "bun": key[1], "ji": key[2],
            "kapt_code": row.kapt_code, "kapt_name": row.name, "grid_id": row.grid_id,
            "longitude": row.longitude, "latitude": row.latitude,
            "gross_floor_area_m2": row.gross_floor_area_m2,
            "parcel_match_status": "EXACT_SINGLE_COMPLEX",
        })
        if len(result) >= limit:
            break
    return result


def merge_energy_coordinates(db: Any, year: int = 2025) -> dict[str, int]:
    """Attach coordinates/grid only for unique ordinary-land parcel matches."""
    from .models import EnergyMonthly, TestbedSector
    complexes = list(db.scalars(select(ApartmentComplex)))
    index: dict[tuple[str, str, str], list[ApartmentComplex]] = {}
    for complex_row in complexes:
        if complex_row.bjd_code and complex_row.bun:
            key = (complex_row.bjd_code, _parcel(complex_row.bun), _parcel(complex_row.ji) or "0000")
            index.setdefault(key, []).append(complex_row)
    matched = ambiguous = unmatched = 0
    sector = db.get(TestbedSector, "prototype")
    observed_sets: dict[tuple[str, str], set[str]] = {}
    baseline_area_complete = True
    for energy in db.scalars(select(EnergyMonthly)):
        if str(energy.lot_type or "0") not in {"", "0"}:
            energy.grid_id = None
            energy.match_method = "UNMATCHED_KAPT_MOUNTAIN_PARCEL"
            raw = dict(energy.raw_record or {})
            raw["parcel_match_status"] = "MOUNTAIN_PARCEL_NOT_MATCHED"
            energy.raw_record = raw
            unmatched += 1
            continue
        bjd_code = f"{energy.sigungu_code}{energy.bjdong_code}"
        candidates = index.get((bjd_code, _parcel(energy.bun), _parcel(energy.ji) or "0000"), [])
        if len(candidates) == 1 and "외" not in (candidates[0].parcel_address or ""):
            complex_row = candidates[0]
            energy.grid_id = complex_row.grid_id
            energy.match_method = "KAPT_COMPLEX_CENTROID"
            raw = dict(energy.raw_record or {})
            raw["kapt_code"] = complex_row.kapt_code
            raw["parcel_match_status"] = "EXACT_SINGLE_COMPLEX"
            raw["matched_gross_floor_area_m2"] = complex_row.gross_floor_area_m2
            energy.raw_record = raw
            matched += 1
            if energy.use_ym.startswith(str(year)) and energy.usage_kwh is not None and sector and complex_row.grid_id == sector.grid_id:
                observed_sets.setdefault((energy.energy_type, energy.use_ym), set()).add(complex_row.kapt_code)
                if complex_row.gross_floor_area_m2 is None:
                    baseline_area_complete = False
        elif len(candidates) > 1:
            energy.grid_id = None
            energy.match_method = "AMBIGUOUS_KAPT_PARCEL"
            raw = dict(energy.raw_record or {})
            raw["parcel_match_status"] = "AMBIGUOUS_MULTIPLE_COMPLEXES"
            energy.raw_record = raw
            ambiguous += 1
        else:
            energy.grid_id = None
            energy.match_method = None
            unmatched += 1
    parcel_sets = {frozenset(codes) for codes in observed_sets.values()}
    stable_codes = set(next(iter(parcel_sets))) if len(parcel_sets) == 1 else set()
    if sector and stable_codes and baseline_area_complete:
        area = sum(row.gross_floor_area_m2 for row in complexes if row.kapt_code in stable_codes)
        metadata = dict(sector.metadata_json or {})
        metadata.update({"baseline_floor_area_m2": area, "baseline_floor_area_source": f"K-apt kaptTarea / {year} exact stable parcel set", "baseline_kapt_codes": sorted(stable_codes), "baseline_year": year})
        sector.metadata_json = metadata
    elif sector:
        metadata = dict(sector.metadata_json or {})
        for key in ("baseline_floor_area_m2", "baseline_floor_area_source", "baseline_kapt_codes", "baseline_year"):
            metadata.pop(key, None)
        sector.metadata_json = metadata
    db.commit()
    return {"matched": matched, "ambiguous": ambiguous, "unmatched": unmatched, "baseline_complexes": len(stable_codes) if baseline_area_complete else 0}
