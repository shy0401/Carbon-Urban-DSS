"""Controlled two-step imports for tabular and spatial user uploads."""

from __future__ import annotations

import csv
import io
import json
import math
import os
import re
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Literal

import geopandas as gpd
import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from geoalchemy2.shape import to_shape
from pydantic import BaseModel, Field, HttpUrl, field_validator
from pyproj import CRS, Transformer
from shapely.geometry import mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform
from shapely.wkt import loads as load_wkt
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base, Session
from .models import (
    Building,
    DataSource,
    EnergyMonthly,
    Grid,
    PopulationGrid,
    RawDataAsset,
    ZoningArea,
)


MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_ZIP_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
MAX_ZIP_MEMBERS = 100
MAX_ZIP_RATIO = 200
PREVIEW_ROWS = 8
UPLOAD_ROOT = Path(os.getenv("UPLOAD_ROOT", "/data/uploads"))
DATASET_TYPES = {"buildings", "zoning", "population", "grid", "energy"}
SPATIAL_TYPES = {"buildings", "zoning", "grid"}
OPTIONAL_SPATIAL_TYPES = {"population"}
ALLOWED_ZIP_SUFFIXES = {
    ".shp",
    ".shx",
    ".dbf",
    ".prj",
    ".cpg",
    ".qix",
    ".sbn",
    ".sbx",
    ".xml",
}

REQUIRED_FIELDS = {
    "buildings": ["id", "geometry"],
    "zoning": ["id", "geometry"],
    "population": ["source_grid_id", "population", "year"],
    "grid": ["id", "geometry"],
    "energy": [
        "sigungu_code",
        "bjdong_code",
        "bun",
        "ji",
        "use_ym",
        "energy_type",
        "usage_kwh",
    ],
}

FIELD_ALIASES = {
    "id": [
        "id",
        "building_id",
        "zone_id",
        "grid_id",
        "gid",
        "objectid",
        "official_id",
        "격자id",
        "아이디",
    ],
    "geometry": ["geometry", "geom", "wkt", "the_geom", "도형"],
    "name": ["name", "명칭", "이름", "건물명"],
    "grid_id": ["grid_id", "gridid", "격자id", "격자코드"],
    "source_grid_id": ["source_grid_id", "source_id", "official_grid_id", "원본격자id"],
    "population": ["population", "pop", "인구", "총인구"],
    "reference_period": ["reference_period", "year", "기준연도", "기준시점"],
    "year": ["year", "reference_year", "기준연도", "연도"],
    "sigungu_code": ["sigungu_code", "sigungu_cd", "시군구코드"],
    "bjdong_code": ["bjdong_code", "bjdong_cd", "법정동코드"],
    "lot_type": ["lot_type", "산여부", "대지구분"],
    "bun": ["bun", "본번", "번"],
    "ji": ["ji", "부번", "지"],
    "use_ym": ["use_ym", "사용년월", "기준년월"],
    "energy_type": ["energy_type", "에너지원", "에너지구분"],
    "usage_kwh": ["usage_kwh", "usage", "사용량", "사용량kwh"],
    "levels": ["levels", "building:levels", "층수"],
    "footprint_m2": ["footprint_m2", "건축면적"],
    "floor_area_m2": ["floor_area_m2", "연면적"],
}


class UnsafeUpload(ValueError):
    """Raised before an unsafe or unsupported upload is persisted/extracted."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UploadBatch(Base):
    __tablename__ = "upload_batches"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    dataset_type: Mapped[str] = mapped_column(String)
    filename: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str | None] = mapped_column(String, nullable=True)
    stored_path: Mapped[str] = mapped_column(Text)
    file_size: Mapped[int] = mapped_column(Integer)
    encoding: Mapped[str | None] = mapped_column(String, nullable=True)
    detected_crs: Mapped[str | None] = mapped_column(String, nullable=True)
    source_crs: Mapped[str | None] = mapped_column(String, nullable=True)
    columns: Mapped[list] = mapped_column(JSON)
    preview_rows: Mapped[list] = mapped_column(JSON)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    row_count: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String, default="PREVIEWED")
    mapping_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    target_crs: Mapped[str | None] = mapped_column(String, nullable=True)
    source_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    imported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ImportedRecord(Base):
    __tablename__ = "imported_records"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey("upload_batches.id"), index=True)
    row_index: Mapped[int] = mapped_column(Integer)
    dataset_type: Mapped[str] = mapped_column(String)
    source_record_id: Mapped[str | None] = mapped_column(String, nullable=True)
    original_properties: Mapped[dict] = mapped_column(JSON)
    normalized_properties: Mapped[dict] = mapped_column(JSON)
    original_geom: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    normalized_geom: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    source_crs: Mapped[str | None] = mapped_column(String, nullable=True)
    target_crs: Mapped[str | None] = mapped_column(String, nullable=True)
    geometry_valid: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


class GridIdMapping(Base):
    __tablename__ = "grid_id_mappings"

    batch_id: Mapped[str] = mapped_column(ForeignKey("upload_batches.id"), primary_key=True)
    old_grid_id: Mapped[str] = mapped_column(String, primary_key=True)
    new_grid_id: Mapped[str] = mapped_column(String, index=True)


def _clean_value(value: Any) -> Any:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.isoformat()
    return value


def _normalise_crs(value: str | CRS | None) -> str | None:
    if value is None or not str(value).strip():
        return None
    try:
        crs = CRS.from_user_input(value)
    except Exception as exc:
        raise ValueError(f"invalid CRS: {value}") from exc
    authority = crs.to_authority()
    return f"{authority[0]}:{authority[1]}" if authority else crs.to_string()


def _detect_csv_encoding(content: bytes) -> tuple[str, str]:
    for encoding in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
        try:
            return content.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise UnsafeUpload("CSV encoding is not UTF-8, CP949, or EUC-KR")


def _safe_zip_members(content: bytes) -> list[zipfile.ZipInfo]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise UnsafeUpload("invalid ZIP archive") from exc
    members = archive.infolist()
    if not members or len(members) > MAX_ZIP_MEMBERS:
        raise UnsafeUpload("ZIP member count exceeds safe limit")
    total_size = 0
    shapefiles = 0
    for member in members:
        path = PurePosixPath(member.filename.replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts:
            raise UnsafeUpload(f"unsafe ZIP path: {member.filename}")
        if member.is_dir():
            continue
        if path.suffix.lower() not in ALLOWED_ZIP_SUFFIXES:
            raise UnsafeUpload(f"unsupported file in shapefile ZIP: {member.filename}")
        shapefiles += path.suffix.lower() == ".shp"
        total_size += member.file_size
        if member.file_size and member.compress_size == 0:
            raise UnsafeUpload("unsafe ZIP compression metadata")
        if member.compress_size and member.file_size / member.compress_size > MAX_ZIP_RATIO:
            raise UnsafeUpload("ZIP compression ratio exceeds safe limit")
    if total_size > MAX_ZIP_UNCOMPRESSED_BYTES:
        raise UnsafeUpload("ZIP expanded size exceeds safe limit")
    if shapefiles != 1:
        raise UnsafeUpload("ZIP must contain exactly one .shp layer")
    return members


@dataclass
class ParsedUpload:
    filename: str
    dataset_type: str
    columns: list[str]
    records: list[dict[str, Any]]
    encoding: str | None
    detected_crs: str | None
    source_crs: str | None
    warnings: list[str]

    def preview(self) -> dict[str, Any]:
        rows = []
        for record in self.records[:PREVIEW_ROWS]:
            preview_row = {}
            for column in self.columns:
                value = record.get(column)
                if column == "geometry" and isinstance(value, BaseGeometry):
                    preview_row[column] = {
                        "type": value.geom_type,
                        "valid": value.is_valid,
                        "bounds": [round(number, 8) for number in value.bounds],
                    }
                else:
                    preview_row[column] = _clean_value(value)
            rows.append(preview_row)
        return {
            "columns": self.columns,
            "rows": rows,
            "detected_crs": self.source_crs,
            "encoding": self.encoding,
            "required_fields": REQUIRED_FIELDS[self.dataset_type],
            "suggested_mapping": _suggest_mapping(self.columns, self.dataset_type),
            "warnings": self.warnings,
            "row_count": len(self.records),
        }


def _records_from_frame(frame: pd.DataFrame) -> tuple[list[str], list[dict[str, Any]]]:
    columns = [str(column) for column in frame.columns]
    records = [
        {str(key): _clean_value(value) for key, value in row.items()}
        for row in frame.to_dict(orient="records")
    ]
    return columns, records


def _parse_geojson(content: bytes) -> tuple[list[str], list[dict[str, Any]], str | None]:
    try:
        payload = json.loads(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UnsafeUpload("invalid UTF-8 GeoJSON") from exc
    if payload.get("type") != "FeatureCollection" or not isinstance(payload.get("features"), list):
        raise UnsafeUpload("GeoJSON must be a FeatureCollection")
    detected_crs = "EPSG:4326"
    crs_payload = payload.get("crs")
    if isinstance(crs_payload, dict):
        detected_crs = _normalise_crs((crs_payload.get("properties") or {}).get("name"))
    records: list[dict[str, Any]] = []
    property_columns: list[str] = []
    for feature in payload["features"]:
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            raise UnsafeUpload("GeoJSON contains a non-Feature item")
        properties = feature.get("properties") or {}
        if not isinstance(properties, dict):
            raise UnsafeUpload("GeoJSON feature properties must be an object")
        for key in properties:
            if key not in property_columns:
                property_columns.append(str(key))
        geometry = feature.get("geometry")
        try:
            parsed_geometry = shape(geometry) if geometry else None
        except Exception as exc:
            raise UnsafeUpload("GeoJSON contains unreadable geometry") from exc
        records.append({**properties, "geometry": parsed_geometry})
    return [*property_columns, "geometry"], records, detected_crs


def _parse_shapefile_zip(
    content: bytes,
) -> tuple[list[str], list[dict[str, Any]], str | None]:
    members = _safe_zip_members(content)
    with tempfile.TemporaryDirectory(prefix="carbon-upload-") as temporary:
        root = Path(temporary).resolve()
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            for member in members:
                destination = (root / member.filename).resolve()
                if not destination.is_relative_to(root):
                    raise UnsafeUpload(f"unsafe ZIP path: {member.filename}")
            archive.extractall(root)
        shp_path = next(root.rglob("*.shp"))
        try:
            frame = gpd.read_file(shp_path)
        except Exception as exc:
            raise UnsafeUpload("unable to read shapefile") from exc
        detected_crs = _normalise_crs(frame.crs) if frame.crs else None
        geometry_column = frame.geometry.name
        columns = [str(column) for column in frame.columns if column != geometry_column]
        records = []
        for _, row in frame.iterrows():
            record = {
                str(column): _clean_value(row[column])
                for column in frame.columns
                if column != geometry_column
            }
            record["geometry"] = row[geometry_column]
            records.append(record)
        return [*columns, "geometry"], records, detected_crs


def _suggest_mapping(columns: list[str], dataset_type: str) -> dict[str, str]:
    lowered = {column.strip().lower().replace(" ", ""): column for column in columns}
    targets = list(dict.fromkeys([*REQUIRED_FIELDS[dataset_type], *FIELD_ALIASES]))
    result: dict[str, str] = {}
    for target in targets:
        for alias in FIELD_ALIASES.get(target, [target]):
            match = lowered.get(alias.strip().lower().replace(" ", ""))
            if match is not None:
                result[target] = match
                break
    return result


def inspect_upload(
    filename: str,
    content: bytes,
    dataset_type: str,
    source_crs: str | None = None,
) -> ParsedUpload:
    """Parse an upload without persisting or mutating any source geometry."""

    if dataset_type not in DATASET_TYPES:
        raise UnsafeUpload(f"unsupported dataset type: {dataset_type}")
    if not content:
        raise UnsafeUpload("empty upload")
    if len(content) > MAX_UPLOAD_BYTES:
        raise UnsafeUpload(f"upload exceeds {MAX_UPLOAD_BYTES} byte limit")
    suffix = Path(filename or "").suffix.lower()
    encoding: str | None = None
    detected_crs: str | None = None
    if suffix == ".csv":
        decoded, encoding = _detect_csv_encoding(content)
        reader = csv.DictReader(io.StringIO(decoded, newline=""))
        if not reader.fieldnames:
            raise UnsafeUpload("CSV has no header")
        columns = [str(name) for name in reader.fieldnames]
        records = [{str(key): value for key, value in row.items()} for row in reader]
    elif suffix == ".xlsx":
        try:
            frame = pd.read_excel(io.BytesIO(content), dtype=object)
        except Exception as exc:
            raise UnsafeUpload("unable to read XLSX") from exc
        columns, records = _records_from_frame(frame)
    elif suffix in {".geojson", ".json"}:
        columns, records, detected_crs = _parse_geojson(content)
        encoding = "utf-8-sig"
    elif suffix == ".zip":
        columns, records, detected_crs = _parse_shapefile_zip(content)
    else:
        raise UnsafeUpload("supported extensions: .csv, .xlsx, .geojson, .json, .zip")
    if not records:
        raise UnsafeUpload("upload contains no data rows")

    explicit_crs = _normalise_crs(source_crs)
    effective_crs = explicit_crs or detected_crs
    warnings: list[str] = []
    if dataset_type in SPATIAL_TYPES and effective_crs is None:
        warnings.append("공간자료 CRS를 감지하지 못했습니다. source_crs를 지정해야 가져올 수 있습니다.")
    invalid_count = sum(
        1
        for record in records
        if isinstance(record.get("geometry"), BaseGeometry)
        and not record["geometry"].is_valid
    )
    if invalid_count:
        warnings.append(
            f"유효하지 않은 도형 {invalid_count}개가 있습니다. 자동 보정하지 않으며 가져오기를 거부합니다."
        )
    mapping_suggestion = _suggest_mapping(columns, dataset_type)
    missing = [field for field in REQUIRED_FIELDS[dataset_type] if field not in mapping_suggestion]
    if missing:
        warnings.append("필수 필드 매핑 확인 필요: " + ", ".join(missing))
    return ParsedUpload(
        filename=filename,
        dataset_type=dataset_type,
        columns=columns,
        records=records,
        encoding=encoding,
        detected_crs=detected_crs,
        source_crs=effective_crs,
        warnings=warnings,
    )


def _mapped_values(
    record: dict[str, Any], mapping_json: dict[str, str], row_index: int
) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for target, source_column in mapping_json.items():
        if source_column not in record:
            raise ValueError(f"row {row_index}: mapped column not found: {source_column}")
        if target == "geometry":
            continue
        values[target] = _clean_value(record[source_column])
    return values


def _canonical_digits(value: Any, field: str, row_index: int, length: int) -> str:
    text = str(_clean_value(value) if value is not None else "").strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    if not text.isdigit() or len(text) != length:
        raise ValueError(f"row {row_index}: {field} must be exactly {length} digits")
    return text


def _canonical_lot_number(value: Any, field: str, row_index: int) -> str:
    text = str(_clean_value(value) if value is not None else "").strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    if not text.isdigit() or len(text) > 4:
        raise ValueError(f"row {row_index}: {field} must contain 1 to 4 digits")
    return text.zfill(4)


def _validate_values(dataset_type: str, values: dict[str, Any], row_index: int) -> None:
    if dataset_type == "energy":
        values["sigungu_code"] = _canonical_digits(
            values["sigungu_code"], "sigungu_code", row_index, 5
        )
        values["bjdong_code"] = _canonical_digits(
            values["bjdong_code"], "bjdong_code", row_index, 5
        )
        values["bun"] = _canonical_lot_number(values["bun"], "bun", row_index)
        values["ji"] = _canonical_lot_number(values["ji"], "ji", row_index)
        month = str(values["use_ym"]).strip().replace("-", "")
        if month.endswith(".0"):
            month = month[:-2]
        if not re.fullmatch(r"20\d{2}(0[1-9]|1[0-2])", month):
            raise ValueError(f"row {row_index}: use_ym must be YYYYMM")
        values["use_ym"] = month
        energy_type = str(values["energy_type"]).strip().upper()
        if energy_type not in {"ELECTRICITY", "GAS"}:
            raise ValueError(f"row {row_index}: energy_type must be ELECTRICITY or GAS")
        values["energy_type"] = energy_type
        usage = _float(values["usage_kwh"], "usage_kwh", row_index, True)
        if usage is not None and usage < 0:
            raise ValueError(f"row {row_index}: usage_kwh must be nonnegative")
        values["usage_kwh"] = usage
    elif dataset_type == "population":
        source_grid_id = str(values["source_grid_id"]).strip()
        if not source_grid_id:
            raise ValueError(f"row {row_index}: source_grid_id is required")
        population = _float(values["population"], "population", row_index)
        if population is None or population < 0:
            raise ValueError(f"row {row_index}: population must be nonnegative")
        year = str(values["year"]).strip()
        if year.endswith(".0"):
            year = year[:-2]
        if not re.fullmatch(r"20\d{2}", year):
            raise ValueError(f"row {row_index}: year must be YYYY")
        values.update(source_grid_id=source_grid_id, population=population, year=year)


def _validate_grid(geometry_5179: BaseGeometry, row_index: int) -> None:
    if geometry_5179.geom_type != "Polygon":
        raise ValueError(f"row {row_index}: grid geometry must be Polygon")
    min_x, min_y, max_x, max_y = geometry_5179.bounds
    width, height = max_x - min_x, max_y - min_y
    rectangle = geometry_5179.envelope
    exact_rectangle = geometry_5179.symmetric_difference(rectangle).area <= 0.01
    if (
        abs(width - 500) > 0.01
        or abs(height - 500) > 0.01
        or abs(geometry_5179.area - 250_000) > 0.1
        or not exact_rectangle
    ):
        raise ValueError(f"row {row_index}: grid must be an exact 500m x 500m polygon")
    return None


def _source_grid_size(geometry: BaseGeometry) -> int | None:
    min_x, min_y, max_x, max_y = geometry.bounds
    width, height = max_x - min_x, max_y - min_y
    for size in (100, 500):
        if (
            abs(width - size) <= 0.01
            and abs(height - size) <= 0.01
            and abs(geometry.area - size * size) <= 0.1
            and geometry.symmetric_difference(geometry.envelope).area <= 0.01
        ):
            return size
    return None


def allocate_population_geometry(
    source_geometry_5179: BaseGeometry,
    population: float,
    app_grids: list[tuple[str, BaseGeometry]],
) -> list[dict[str, Any]]:
    """Allocate an exact 100/500 m source grid to overlapping app grids."""

    size = _source_grid_size(source_geometry_5179)
    if size is None:
        raise ValueError("population source geometry must be an exact 100m or 500m square")
    overlaps: list[tuple[str, float]] = []
    for grid_id, grid_geometry in app_grids:
        area = source_geometry_5179.intersection(grid_geometry).area
        if area > 0.01:
            overlaps.append((grid_id, area))
    if not overlaps:
        return []
    source_area = source_geometry_5179.area
    contained = len(overlaps) == 1 and abs(overlaps[0][1] - source_area) <= 0.01
    allocations = []
    for grid_id, overlap_area in sorted(overlaps):
        weight = overlap_area / source_area
        allocations.append(
            {
                "grid_id": grid_id,
                "population": round(float(population) * weight, 8),
                "weight": round(weight, 8),
                "method": f"CONTAINED_{size}M" if contained else "AREA_WEIGHTED_ESTIMATE",
            }
        )
    return allocations


def normalise_import_records(
    parsed: ParsedUpload,
    dataset_type: str,
    mapping_json: dict[str, str],
    target_crs: str = "EPSG:5179",
) -> list[dict[str, Any]]:
    """Validate all rows and return normalized records without database writes."""

    if dataset_type != parsed.dataset_type:
        raise ValueError("dataset type differs from preview")
    missing_mapping = [field for field in REQUIRED_FIELDS[dataset_type] if field not in mapping_json]
    if missing_mapping:
        raise ValueError("missing required mapping: " + ", ".join(missing_mapping))
    unknown_columns = sorted(set(mapping_json.values()) - set(parsed.columns))
    if unknown_columns:
        raise ValueError("mapped columns not in upload: " + ", ".join(unknown_columns))

    normalized_target = _normalise_crs(target_crs)
    if normalized_target != "EPSG:5179":
        raise ValueError("target_crs must be EPSG:5179")
    source_crs = parsed.source_crs
    has_geometry = "geometry" in mapping_json or any(
        isinstance(record.get("geometry"), BaseGeometry) for record in parsed.records
    )
    transformer = None
    if dataset_type in SPATIAL_TYPES or (dataset_type in OPTIONAL_SPATIAL_TYPES and has_geometry):
        if source_crs is None:
            raise ValueError("source CRS is required for spatial import")
        transformer = Transformer.from_crs(source_crs, normalized_target, always_xy=True)
    normalized: list[dict[str, Any]] = []
    seen_grid_ids: set[str] = set()
    for row_index, original in enumerate(parsed.records, start=1):
        values = _mapped_values(original, mapping_json, row_index)
        _validate_values(dataset_type, values, row_index)
        geometry_column = mapping_json.get("geometry", "geometry")
        original_geometry = original.get(geometry_column) if has_geometry else None
        if isinstance(original_geometry, str) and original_geometry.strip():
            try:
                original_geometry = load_wkt(original_geometry)
            except Exception as exc:
                raise ValueError(f"row {row_index}: invalid WKT geometry") from exc
        normalized_geometry = None
        geometry_valid: bool | None = None
        old_grid_id = None
        new_grid_id = None
        if dataset_type in SPATIAL_TYPES or original_geometry is not None:
            if not isinstance(original_geometry, BaseGeometry) or original_geometry.is_empty:
                raise ValueError(f"row {row_index}: missing geometry")
            if not original_geometry.is_valid:
                raise ValueError(f"row {row_index}: invalid geometry; no automatic repair applied")
            if original_geometry.geom_type not in {"Polygon", "MultiPolygon"}:
                raise ValueError(f"row {row_index}: polygon geometry required")
            normalized_geometry = transform(transformer.transform, original_geometry)
            if normalized_geometry.is_empty or not normalized_geometry.is_valid:
                raise ValueError(f"row {row_index}: invalid geometry after CRS transformation")
            geometry_valid = True
            if dataset_type == "grid":
                _validate_grid(normalized_geometry, row_index)
                old_grid_id = str(values["id"])
                if old_grid_id in seen_grid_ids:
                    raise ValueError(f"row {row_index}: duplicate source grid id: {old_grid_id}")
                seen_grid_ids.add(old_grid_id)
        properties = {
            str(key): _clean_value(value)
            for key, value in original.items()
            if not isinstance(value, BaseGeometry)
        }
        normalized.append(
            {
                "row_index": row_index,
                "values": values,
                "original_properties": properties,
                "original_geometry": original_geometry,
                "normalized_geometry": normalized_geometry,
                "source_crs": source_crs,
                "target_crs": normalized_target if normalized_geometry is not None else None,
                "geometry_valid": geometry_valid,
                "old_grid_id": old_grid_id,
                "new_grid_id": new_grid_id,
            }
        )
    return normalized


class ImportRequest(BaseModel):
    mapping: dict[str, str]
    target_crs: str = "EPSG:5179"
    source_url: HttpUrl
    provider: str = Field(min_length=1, max_length=200)
    reference_period: str = Field(min_length=1, max_length=100)

    @field_validator("provider", "reference_period")
    @classmethod
    def reject_blank_metadata(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("provenance field must not be blank")
        return value


def _db_session():
    with Session() as db:
        yield db


async def _read_limited(upload: UploadFile) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while chunk := await upload.read(1024 * 1024):
        total += len(chunk)
        if total > MAX_UPLOAD_BYTES:
            raise HTTPException(413, f"업로드는 {MAX_UPLOAD_BYTES}바이트를 초과할 수 없습니다")
        chunks.append(chunk)
    return b"".join(chunks)


router = APIRouter(prefix="/api/uploads", tags=["uploads"])


@router.post("/preview")
async def preview_upload(
    file: UploadFile = File(...),
    dataset_type: Literal["buildings", "zoning", "population", "grid", "energy"] = Form(...),
    source_crs: str | None = Form(None),
    db: Any = Depends(_db_session),
):
    content = await _read_limited(file)
    try:
        parsed = inspect_upload(file.filename or "upload", content, dataset_type, source_crs)
    except (UnsafeUpload, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
    upload_id = str(uuid.uuid4())
    suffix = Path(file.filename or "upload").suffix.lower()
    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    stored_path = (UPLOAD_ROOT / f"{upload_id}{suffix}").resolve()
    if not stored_path.is_relative_to(UPLOAD_ROOT.resolve()):
        raise HTTPException(400, "invalid upload path")
    stored_path.write_bytes(content)
    preview = parsed.preview()
    batch = UploadBatch(
        id=upload_id,
        dataset_type=dataset_type,
        filename=file.filename or "upload",
        content_type=file.content_type,
        stored_path=str(stored_path),
        file_size=len(content),
        encoding=parsed.encoding,
        detected_crs=parsed.detected_crs,
        source_crs=parsed.source_crs,
        columns=parsed.columns,
        preview_rows=preview["rows"],
        warnings=parsed.warnings,
        row_count=len(parsed.records),
    )
    db.add(batch)
    db.commit()
    return {"id": upload_id, **preview}


def _float(value: Any, field: str, row_index: int, nullable: bool = False) -> float | None:
    if value in (None, "") and nullable:
        return None
    try:
        number = float(str(value).replace(",", ""))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"row {row_index}: {field} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"row {row_index}: {field} must be finite")
    return number


def _feature_wgs84(geometry: BaseGeometry, source_crs: str, properties: dict[str, Any]) -> dict:
    transformer = Transformer.from_crs(source_crs, "EPSG:4326", always_xy=True)
    return {
        "type": "Feature",
        "properties": properties,
        "geometry": mapping(transform(transformer.transform, geometry)),
    }


def _resolve_grid_id(db: Any, value: Any) -> str | None:
    if value in (None, ""):
        return None
    grid_id = str(value)
    mapped = db.scalar(
        select(GridIdMapping.new_grid_id)
        .where(GridIdMapping.old_grid_id == grid_id)
        .limit(1)
    )
    candidate = mapped or grid_id
    if db.get(Grid, candidate) is None:
        raise ValueError(f"unknown grid id: {grid_id}")
    return candidate


def _app_grid_geometries(db: Any) -> list[tuple[str, BaseGeometry]]:
    return [(grid.id, to_shape(grid.geom)) for grid in db.scalars(select(Grid))]


def _centroid_grid_id(
    geometry_5179: BaseGeometry, app_grids: list[tuple[str, BaseGeometry]]
) -> str | None:
    centroid = geometry_5179.centroid
    candidates = [
        (grid_id, geometry_5179.intersection(grid_geometry).area)
        for grid_id, grid_geometry in app_grids
        if grid_geometry.covers(centroid)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item[1], item[0]))[0]


def _grid_correspondence(
    source_geometry_5179: BaseGeometry, app_grids: list[tuple[str, BaseGeometry]]
) -> dict[str, Any] | None:
    overlaps = [
        (grid_id, source_geometry_5179.intersection(grid_geometry).area)
        for grid_id, grid_geometry in app_grids
        if source_geometry_5179.intersects(grid_geometry)
    ]
    overlaps = [item for item in overlaps if item[1] > 0.01]
    if not overlaps:
        return None
    grid_id, overlap_area = max(overlaps, key=lambda item: (item[1], item[0]))
    ratio = overlap_area / source_geometry_5179.area
    return {
        "grid_id": grid_id,
        "overlap_ratio": round(ratio, 8),
        "method": (
            "EXACT_GEOMETRY_CORRESPONDENCE"
            if abs(ratio - 1) <= 1e-8
            else "MAX_OVERLAP_CORRESPONDENCE"
        ),
    }


def _store_target_row(
    db: Any,
    batch: UploadBatch,
    source_id: str,
    record: dict[str, Any],
) -> None:
    values = record["values"]
    row_index = record["row_index"]
    original = record["original_properties"]
    record_id = str(values.get("id") or row_index)
    if batch.dataset_type == "buildings":
        if values.get("grid_id"):
            grid_id = _resolve_grid_id(db, values["grid_id"])
        else:
            grid_id = _centroid_grid_id(
                record["normalized_geometry"], _app_grid_geometries(db)
            )
        building_id = f"{source_id}:{record_id}"
        name = str(values.get("name") or record_id)
        properties = dict(
            original,
            id=building_id,
            name=name,
            grid_id=grid_id,
            source_type="UNVERIFIED",
            upload_source_id=source_id,
        )
        db.add(
            Building(
                id=building_id,
                grid_id=grid_id,
                name=name,
                source=source_id,
                source_type="UNVERIFIED",
                footprint_m2=_float(values.get("footprint_m2"), "footprint_m2", row_index, True),
                floor_area_m2=_float(values.get("floor_area_m2"), "floor_area_m2", row_index, True),
                properties=properties,
                geojson=_feature_wgs84(
                    record["normalized_geometry"], record["target_crs"], properties
                ),
            )
        )
    elif batch.dataset_type == "zoning":
        properties = dict(original, upload_source_id=source_id)
        db.add(
            ZoningArea(
                id=f"{source_id}:{record_id}",
                source=source_id,
                properties=properties,
                geojson=_feature_wgs84(
                    record["normalized_geometry"], record["target_crs"], properties
                ),
            )
        )
    elif batch.dataset_type == "grid":
        geometry = record["normalized_geometry"]
        correspondence = _grid_correspondence(geometry, _app_grid_geometries(db))
        values["official_source_id"] = record["old_grid_id"]
        values["app_grid_correspondence"] = correspondence
        record["new_grid_id"] = correspondence["grid_id"] if correspondence else None
        if correspondence:
            db.add(
                GridIdMapping(
                    batch_id=batch.id,
                    old_grid_id=record["old_grid_id"],
                    new_grid_id=correspondence["grid_id"],
                )
            )
    elif batch.dataset_type == "energy":
        db.add(
            EnergyMonthly(
                source=source_id,
                sigungu_code=values["sigungu_code"],
                bjdong_code=values["bjdong_code"],
                lot_type=str(values.get("lot_type") or "0"),
                bun=values["bun"],
                ji=values["ji"],
                use_ym=values["use_ym"],
                energy_type=values["energy_type"],
                usage_kwh=values["usage_kwh"],
                grid_id=_resolve_grid_id(db, values.get("grid_id")),
                match_method="USER_CONFIRMED_MAPPING" if values.get("grid_id") else None,
                raw_record=original,
            )
        )


def _mapped_source_grid_id(db: Any, source_grid_id: str) -> str:
    mapped = db.scalar(
        select(GridIdMapping.new_grid_id)
        .where(GridIdMapping.old_grid_id == source_grid_id)
        .limit(1)
    )
    if mapped is None or db.get(Grid, mapped) is None:
        raise ValueError(f"unknown source_grid_id mapping: {source_grid_id}")
    return mapped


def _prepare_population_aggregates(
    db: Any, records: list[dict[str, Any]]
) -> dict[tuple[str, str], float]:
    app_grids = _app_grid_geometries(db)
    aggregates: dict[tuple[str, str], float] = {}
    for record in records:
        values = record["values"]
        source_grid_id = values["source_grid_id"]
        population = values["population"]
        year = values["year"]
        geometry = record["normalized_geometry"]
        if geometry is None:
            grid_id = _mapped_source_grid_id(db, source_grid_id)
            allocations = [
                {
                    "grid_id": grid_id,
                    "population": population,
                    "weight": 1.0,
                    "method": "SOURCE_GRID_ID_MAPPING",
                }
            ]
        else:
            allocations = allocate_population_geometry(geometry, population, app_grids)
            if not allocations:
                raise ValueError(
                    f"row {record['row_index']}: population geometry does not overlap an app grid"
                )
        values["grid_allocations"] = [
            dict(allocation, source_grid_id=source_grid_id, year=year)
            for allocation in allocations
        ]
        for allocation in allocations:
            key = (allocation["grid_id"], year)
            aggregates[key] = aggregates.get(key, 0.0) + allocation["population"]
    return aggregates


def _store_population_aggregates(
    db: Any,
    source_id: str,
    aggregates: dict[tuple[str, str], float],
) -> None:
    for (grid_id, year), population in sorted(aggregates.items()):
        db.add(
            PopulationGrid(
                id=f"{source_id}:{year}:{grid_id}",
                grid_id=grid_id,
                population=round(population, 8),
                reference_period=year,
                source=source_id,
            )
        )


@router.post("/{upload_id}/import")
def import_upload(upload_id: str, request: ImportRequest, db: Any = Depends(_db_session)):
    batch = db.get(UploadBatch, upload_id)
    if batch is None:
        raise HTTPException(404, "업로드 미리보기를 찾을 수 없습니다")
    if batch.status != "PREVIEWED":
        raise HTTPException(409, "이미 처리된 업로드입니다")
    stored_path = Path(batch.stored_path).resolve()
    if not stored_path.is_relative_to(UPLOAD_ROOT.resolve()) or not stored_path.is_file():
        raise HTTPException(410, "업로드 원본 파일을 찾을 수 없습니다")
    try:
        parsed = inspect_upload(
            batch.filename,
            stored_path.read_bytes(),
            batch.dataset_type,
            batch.source_crs,
        )
        records = normalise_import_records(
            parsed,
            batch.dataset_type,
            request.mapping,
            request.target_crs,
        )
    except (UnsafeUpload, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc

    source_id = f"upload:{batch.id}"
    source = DataSource(
        id=source_id,
        category={
            "buildings": "건축물 정보",
            "zoning": "용도지역",
            "population": "인구",
            "grid": "격자",
            "energy": "건물 에너지",
        }[batch.dataset_type],
        name=batch.filename,
        organization=request.provider,
        source_url=str(request.source_url),
        source_type="UNVERIFIED",
        status="IMPORTED",
        collected_at=_utcnow(),
        reference_period=request.reference_period,
        geographic_coverage="사용자 제공 파일; 범위 검증 필요",
        raw_row_count=len(parsed.records),
        normalized_row_count=len(records),
        missing_count=sum(
            value in (None, "")
            for record in records
            for value in record["values"].values()
        ),
        quality="미검증 사용자 업로드",
        limitation="URL과 제공자 메타데이터는 저장했으나 공식성은 외부 검증하지 않았습니다.",
    )
    try:
        population_aggregates = (
            _prepare_population_aggregates(db, records)
            if batch.dataset_type == "population"
            else {}
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    try:
        db.add(source)
        db.add(
            RawDataAsset(
                id=str(uuid.uuid4()),
                source_id=source_id,
                provider=request.provider,
                source_url=str(request.source_url),
                reference_period=request.reference_period,
                row_count=len(parsed.records),
                collection_status="USER_UPLOADED_UNVERIFIED",
                storage_location=str(stored_path),
                request_parameters={
                    "mapping": request.mapping,
                    "source_crs": batch.source_crs,
                    "target_crs": request.target_crs,
                },
            )
        )
        for record in records:
            if batch.dataset_type != "population":
                _store_target_row(db, batch, source_id, record)
            source_record_id = record["values"].get("id") or record["values"].get(
                "source_grid_id"
            )
            db.add(
                ImportedRecord(
                    id=str(uuid.uuid4()),
                    batch_id=batch.id,
                    row_index=record["row_index"],
                    dataset_type=batch.dataset_type,
                    source_record_id=str(source_record_id) if source_record_id is not None else None,
                    original_properties=record["original_properties"],
                    normalized_properties=record["values"],
                    original_geom=(
                        mapping(record["original_geometry"])
                        if record["original_geometry"] is not None
                        else None
                    ),
                    normalized_geom=(
                        mapping(record["normalized_geometry"])
                        if record["normalized_geometry"] is not None
                        else None
                    ),
                    source_crs=record["source_crs"],
                    target_crs=record["target_crs"],
                    geometry_valid=record["geometry_valid"],
                )
            )
        if population_aggregates:
            _store_population_aggregates(db, source_id, population_aggregates)
        batch.status = "IMPORTED"
        batch.mapping_json = request.mapping
        batch.target_crs = _normalise_crs(request.target_crs)
        batch.source_id = source_id
        batch.imported_at = _utcnow()
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        detail = str(exc.orig)
        raise HTTPException(409, f"가져오기 충돌: {detail}") from exc
    return {
        "id": batch.id,
        "status": batch.status,
        "dataset_type": batch.dataset_type,
        "source_id": source_id,
        "source_type": "UNVERIFIED",
        "raw_row_count": len(parsed.records),
        "normalized_row_count": len(records),
        "target_crs": batch.target_crs,
        "warnings": batch.warnings,
    }
