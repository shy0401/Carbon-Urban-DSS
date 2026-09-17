"""VWorld 2D Data API collectors for zoning and continuous cadastral parcels."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from geoalchemy2 import Geometry
from geoalchemy2.shape import from_shape, to_shape
from pyproj import Transformer
from shapely.geometry import shape
from shapely.validation import make_valid
from sqlalchemy import DateTime, Float, JSON, String, delete, func, select
from sqlalchemy.orm import Mapped, mapped_column

from .cache import CachedClient, ExternalError
from .db import Base
from .models import DataSource, Grid, RawDataAsset

VWORLD_API_URL = "https://api.vworld.kr/req/data"
VWORLD_GUIDE_URL = "https://www.vworld.kr/dev/v4dv_2ddataguide2_s001.do"
_TO_5179 = Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)


class VworldZoningArea(Base):
    __tablename__ = "vworld_zoning_areas"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    source_feature_id: Mapped[str] = mapped_column(String, index=True)
    zone_code: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    zone_name: Mapped[str | None] = mapped_column(String, nullable=True)
    source_crs: Mapped[str] = mapped_column(String)
    geom: Mapped[object] = mapped_column(Geometry("GEOMETRY", srid=5179, spatial_index=True))
    properties: Mapped[dict] = mapped_column(JSON)
    geometry_repaired: Mapped[bool] = mapped_column(default=False)
    source: Mapped[str] = mapped_column(String)
    raw_source_id: Mapped[str | None] = mapped_column(String, nullable=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class CadastralParcel(Base):
    __tablename__ = "cadastral_parcels"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    source_feature_id: Mapped[str] = mapped_column(String, index=True)
    pnu: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    legal_dong_code: Mapped[str | None] = mapped_column(String, nullable=True)
    lot_main_no: Mapped[str | None] = mapped_column(String, nullable=True)
    lot_sub_no: Mapped[str | None] = mapped_column(String, nullable=True)
    source_crs: Mapped[str] = mapped_column(String)
    geom: Mapped[object] = mapped_column(Geometry("GEOMETRY", srid=5179, spatial_index=True))
    properties: Mapped[dict] = mapped_column(JSON)
    geometry_repaired: Mapped[bool] = mapped_column(default=False)
    source: Mapped[str] = mapped_column(String)
    raw_source_id: Mapped[str | None] = mapped_column(String, nullable=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class GridZoningStat(Base):
    __tablename__ = "grid_zoning_stats"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    grid_id: Mapped[str] = mapped_column(String, index=True)
    zoning_feature_id: Mapped[str] = mapped_column(String, index=True)
    zone_code: Mapped[str | None] = mapped_column(String, nullable=True)
    zone_name: Mapped[str | None] = mapped_column(String, nullable=True)
    intersection_area_m2: Mapped[float] = mapped_column(Float)
    grid_area_ratio: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String)


def load_layer_config(path: str | Path | None = None) -> dict[str, Any]:
    config_path = Path(path) if path else Path(__file__).parents[1] / "config" / "vworld_layers.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    for name in ("zoning", "cadastral"):
        if not config.get(name, {}).get("dataset_id") or not config[name].get("source_crs"):
            raise ValueError(f"VWorld {name} layer configuration is incomplete")
    return config


def bbox_filter(bounds: tuple[float, float, float, float]) -> str:
    minx, miny, maxx, maxy = bounds
    if maxx <= minx or maxy <= miny or (maxx - minx) * (maxy - miny) > 2_000_000:
        raise ValueError("VWorld bbox must be positive and at most 2km²")
    return f"BOX({minx:g} {miny:g},{maxx:g} {maxy:g})"


def parse_vworld_response(body: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(body.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExternalError("VWorld 응답 파싱 실패") from exc
    response = payload.get("response", payload)
    status = str(response.get("status", "OK")).upper()
    if status == "NOT_FOUND":
        return {"status": "EMPTY_VALID", "features": [], "total_records": 0, "total_pages": 0, "current_page": 1}
    if status != "OK":
        error = response.get("error") or {}
        code = error.get("code") if isinstance(error, dict) else "UNKNOWN"
        if code in {"INVALID_KEY", "INCORRECT_KEY", "UNAVAILABLE_KEY"}:
            raise ExternalError(f"VWorld 인증 실패: provider_code={code}")
        if code == "OVER_REQUEST_LIMIT":
            raise ExternalError("VWorld 호출 제한 초과")
        raise ExternalError(f"VWorld API 오류: provider_code={code}")
    result = response.get("result") or response
    collection = result.get("featureCollection", result)
    features = []
    for raw in collection.get("features") or []:
        try:
            geometry = shape(raw.get("geometry"))
        except (TypeError, ValueError) as exc:
            raise ExternalError("VWorld geometry 파싱 실패") from exc
        repaired = not geometry.is_valid
        if repaired:
            geometry = make_valid(geometry)
        if geometry.is_empty or not geometry.is_valid:
            raise ExternalError("VWorld geometry 유효성 검사 실패")
        properties = dict(raw.get("properties") or {})
        feature_id = str(raw.get("id") or properties.get("gml_id") or "")
        if not feature_id:
            feature_id = hashlib.sha256((geometry.wkb + json.dumps(properties, sort_keys=True, ensure_ascii=False).encode())).hexdigest()
        features.append({"id": feature_id, "properties": properties, "geometry": geometry, "geometry_repaired": repaired})
    record, page = response.get("record") or {}, response.get("page") or {}
    return {
        "status": "SUCCESS", "features": features,
        "total_records": int(record.get("total") or len(features)),
        "total_pages": int(page.get("total") or 1), "current_page": int(page.get("current") or 1),
    }


def zoning_intersections(grids: list[dict[str, Any]], zones: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for grid in grids:
        grid_area = grid["geometry"].area
        for zone in zones:
            if not grid["geometry"].intersects(zone["geometry"]):
                continue
            area = grid["geometry"].intersection(zone["geometry"]).area
            if area <= 0:
                continue
            rows.append({
                "grid_id": grid["id"], "zoning_feature_id": zone["id"],
                "zone_code": zone.get("zone_code"), "zone_name": zone.get("zone_name"),
                "intersection_area_m2": float(area), "grid_area_ratio": float(area / grid_area) if grid_area else 0,
            })
    return sorted(rows, key=lambda row: (row["grid_id"], row.get("zone_code") or "", row["zoning_feature_id"]))


def _grid_shapes(db: Any, scope: str) -> list[dict[str, Any]]:
    limit = 1 if scope == "smoke" else 25 if scope == "limited" else None
    query = select(Grid).order_by(Grid.id)
    if limit:
        query = query.limit(limit)
    rows = []
    for grid in db.scalars(query):
        try:
            geometry = to_shape(grid.geom)
        except Exception:
            source_shape = shape(grid.geojson["geometry"])
            from shapely.ops import transform
            geometry = transform(_TO_5179.transform, source_shape)
        rows.append({"id": grid.id, "geometry": geometry})
    return rows


def _source(db: Any, dataset: str) -> DataSource:
    source_id = f"vworld_{dataset}"
    names = {"zoning": "VWorld 도시지역 용도지역", "cadastral": "VWorld 연속지적도"}
    source = db.get(DataSource, source_id) or DataSource(
        id=source_id, category="용도지역" if dataset == "zoning" else "지적",
        name=names[dataset], organization="국토교통부 / VWorld", source_url=VWORLD_GUIDE_URL,
        source_type="OFFICIAL", status="NOT_COLLECTED",
        limitation="VWorld 2D Data API의 전주시 분석격자 bbox 조회 결과입니다.",
    )
    db.add(source);db.flush();return source


def rebuild_grid_zoning_stats(db: Any) -> int:
    grids = _grid_shapes(db, "full")
    zones = [{"id": row.id, "zone_code": row.zone_code, "zone_name": row.zone_name, "geometry": to_shape(row.geom)} for row in db.scalars(select(VworldZoningArea))]
    rows = zoning_intersections(grids, zones)
    db.execute(delete(GridZoningStat))
    for row in rows:
        db.add(GridZoningStat(id=f"{row['grid_id']}:{row['zoning_feature_id']}", source="VWorld", **row))
    db.commit();return len(rows)


def collect_vworld(db: Any, dataset: str, scope: str = "smoke", *, client: CachedClient | None = None, api_key: str | None = None, domain: str | None = None, data_dir: str | Path | None = None) -> dict[str, int]:
    if dataset not in {"zoning", "cadastral"} or scope not in {"smoke", "limited", "full"}:
        raise ValueError("invalid VWorld dataset or scope")
    source = _source(db, dataset);db.commit()
    key = (api_key or os.getenv("VWORLD_API_KEY", "")).strip()
    if not key:
        source.status="NEEDS_API_KEY";db.commit();raise ExternalError("VWorld 인증 실패: VWORLD_API_KEY 미설정")
    if scope == "full" and not db.scalar(select(RawDataAsset.id).where(RawDataAsset.source_id == source.id, RawDataAsset.collection_status == "COLLECTED").limit(1)):
        raise ValueError("VWorld full 수집 전에 smoke 성공이 필요합니다")
    layer=load_layer_config()[dataset];grids=_grid_shapes(db,scope)
    if not grids:raise ValueError("프로젝트 분석격자가 없습니다")
    root=Path(data_dir or os.getenv("DATA_DIR","data"));raw_root=root/"raw"/"vworld"/dataset;raw_root.mkdir(parents=True,exist_ok=True)
    session=client or CachedClient(root/"cache"/"vworld",min_interval=0.3)
    url=os.getenv("VWORLD_DATA_URL",VWORLD_API_URL);domain_value=domain or os.getenv("VWORLD_DOMAIN","http://localhost")
    requested=normalized=repaired=empty=0
    model=VworldZoningArea if dataset=="zoning" else CadastralParcel
    for grid in grids:
        page=1
        while True:
            params={"service":"data","version":"2.0","request":"GetFeature","key":key,"format":"json","size":1000,"page":page,"data":layer["dataset_id"],"geomFilter":bbox_filter(grid["geometry"].bounds),"geometry":"true","attribute":"true","crs":layer["source_crs"],"domain":domain_value}
            result=session.get("VWorld",f"{dataset}-{grid['id']}-{page}",url,params);requested+=1
            raw_path=raw_root/f"{grid['id']}-page-{page}.json";raw_path.write_bytes(result["body"])
            parsed=parse_vworld_response(result["body"]);empty+=parsed["status"]=="EMPTY_VALID"
            digest=hashlib.sha256(result["body"]+f"{dataset}:{grid['id']}:{page}".encode()).hexdigest()
            asset=db.get(RawDataAsset,digest) or RawDataAsset(id=digest,source_id=source.id,provider=source.organization,source_url=layer["verified_reference"],reference_period="수집 시점",storage_location=str(raw_path),collection_status=parsed["status"])
            asset.row_count=len(parsed["features"]);asset.request_parameters={key_:value for key_,value in params.items() if key_ not in {"key","domain"}};db.add(asset)
            for feature in parsed["features"]:
                props=feature["properties"];ident=f"{dataset}:{feature['id']}"
                row=db.get(model,ident)
                if dataset=="zoning":
                    row=row or VworldZoningArea(id=ident,source_feature_id=feature["id"],source_crs=layer["source_crs"],source="VWorld")
                    row.zone_name=props.get("uname");row.zone_code=props.get("ucode") or props.get("zone_code") or feature["id"]
                else:
                    row=row or CadastralParcel(id=ident,source_feature_id=feature["id"],source_crs=layer["source_crs"],source="VWorld")
                    row.pnu=str(props.get("pnu") or "") or None;row.legal_dong_code=row.pnu[:10] if row.pnu else None;row.lot_main_no=row.pnu[-8:-4] if row.pnu else None;row.lot_sub_no=row.pnu[-4:] if row.pnu else None
                row.geom=from_shape(feature["geometry"],srid=5179);row.properties=props;row.geometry_repaired=feature["geometry_repaired"];row.raw_source_id=digest;row.collected_at=datetime.now(timezone.utc);db.add(row);normalized+=1;repaired+=feature["geometry_repaired"]
            db.commit()
            if page>=parsed["total_pages"]:break
            page+=1
    stored=db.scalar(select(func.count()).select_from(model)) or 0
    intersections=rebuild_grid_zoning_stats(db) if dataset=="zoning" else 0
    source.status="COLLECTED" if scope == "full" else "PARTIAL";source.raw_row_count=requested;source.normalized_row_count=stored;source.missing_count=0;source.reference_period="수집 시점";source.quality=f"{layer['dataset_id']} feature {stored}개 / geometry 보정 {repaired}개";source.collected_at=datetime.now(timezone.utc);db.commit()
    return {"requests":requested,"normalized":stored,"geometry_repaired":repaired,"empty_requests":empty,"grid_intersections":intersections}
