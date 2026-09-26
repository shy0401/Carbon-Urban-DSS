"""SGIS official 500m grid cells for Jeonju from the SGIS OpenAPI (grid/data.geojson).

The API gives the *boundary and code* of every official 500m cell of a 시군구 (grid_level_div=500m);
it gives no statistics. Statistics for 500m cells still need an SGIS 자료신청 (총괄 항목만 제공).
What this buys:

* the official grid code (e.g. 다마62a48a) of each project cell — both grids are 500m squares on
  EPSG:5179 multiples of 500, so a project cell ``cell_<x>_<y>`` and an official cell coincide
  exactly when their lower-left corners match;
* an official cell count for the city, so the project grid can be checked against it;
* the code to put on an SGIS application and to join the statistics file when it arrives.

Nothing is estimated: a project cell with no matching official cell simply has no code.
Measured 2026-09-27 (PC): 완산구 433 + 덕진구 532 features, 49 border cells listed twice → 916 official
cells, of which 910 coincide with the 916 project cells (the other 6 on each side are edge cells).
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import Float, Integer, String, delete, func, insert, select
from sqlalchemy.orm import Mapped, mapped_column

from .cache import CachedClient, ExternalError, parse_cached_response
from .db import Base
from .models import DataSource, RawDataAsset

SOURCE_ID = "sgis_grid"
GRID_PATH = "grid/data.geojson"
SIZE_M = 500
HALF = {"a": 0, "b": 500}  # sub-cell letter → offset inside the 1km cell (checked against the geometry on import)


class SgisOfficialGridCell(Base):
    __tablename__ = "sgis_official_grid_cells"
    grid_cd: Mapped[str] = mapped_column(String, primary_key=True)
    size_m: Mapped[int] = mapped_column(Integer)
    x_min: Mapped[float] = mapped_column(Float)
    y_min: Mapped[float] = mapped_column(Float)
    adm_cd: Mapped[str] = mapped_column(String, index=True)   # 시군구 the API listed it under ("35011,35012" on the border)
    grid_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)  # matching project cell
    collected_at: Mapped[datetime] = mapped_column(String, default=lambda: datetime.now(timezone.utc).isoformat())


def parse_grid_geojson(body: bytes) -> dict[str, Any]:
    """{status, cells: [{grid_cd, x_min, y_min, size_m}]} from the API answer. Squares only."""
    try:
        payload = json.loads(body.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExternalError("SGIS 격자 응답 파싱 실패") from exc
    code = int(payload.get("errCd", 0) or 0)
    if code in (-401, -410, -411):
        raise ExternalError("SGIS 인증 실패: consumer key/secret 또는 access token을 확인하세요")
    if code == -100:
        return {"status": "EMPTY_VALID", "cells": []}
    if code != 0:
        raise ExternalError(f"SGIS 격자 API 오류: provider_code={code} {payload.get('errMsg', '')}"[:120])
    cells = []
    for feature in payload.get("features") or []:
        geometry = feature.get("geometry") or {}
        rings = geometry.get("coordinates") or []
        if geometry.get("type") != "Polygon" or not rings:
            continue
        xs = [float(p[0]) for p in rings[0]]
        ys = [float(p[1]) for p in rings[0]]
        size = round(max(xs) - min(xs))
        if size != round(max(ys) - min(ys)):
            continue
        cells.append({"grid_cd": str((feature.get("properties") or {}).get("adm_cd") or ""), "x_min": min(xs), "y_min": min(ys), "size_m": size})
    return {"status": "SUCCESS", "cells": cells}


def project_cell_id(x_min: float, y_min: float) -> str:
    return f"cell_{int(round(x_min))}_{int(round(y_min))}"


def sub_cell_letters(grid_cd: str, x_min: float, y_min: float) -> tuple[str, str] | None:
    """('a'|'b', 'a'|'b') taken from a 500m code like 다마62a48a, or None for another format."""
    if len(grid_cd) != 8:
        return None
    return grid_cd[4], grid_cd[7]


def collect_sgis_grid_official(db: Any, *, client: Any | None = None, token_manager: Any | None = None,
                               data_dir: str | Path | None = None, district_codes: list[str] | None = None) -> dict[str, Any]:
    """Fetch the official 500m cells of every Jeonju 시군구 and link them to project cells."""
    from .models import Grid
    from .sgis import SGIS_BASE_URL, SgisTokenManager, clear_credential_error, record_credential_error
    root = Path(data_dir or os.getenv("DATA_DIR", "data"))
    manager = token_manager or SgisTokenManager(os.getenv("SGIS_CONSUMER_KEY", "").strip(), os.getenv("SGIS_CONSUMER_SECRET", "").strip())
    fingerprint = f"{manager.consumer_key}|{manager.consumer_secret}"
    try:
        token = manager.get_token()
        clear_credential_error(root / "cache" / "sgis-auth", fingerprint)
    except ExternalError as exc:
        record_credential_error(root / "cache" / "sgis-auth", fingerprint, str(exc))
        raise
    session = client or CachedClient(root / "cache" / "sgis", min_interval=0.3)
    base = os.getenv("SGIS_BASE_URL", SGIS_BASE_URL).rstrip("/")
    codes = district_codes or _district_codes(db)
    if not codes:
        raise ExternalError("SGIS 시군구 코드를 모릅니다: 행정동 통계(sgis)를 먼저 수집하세요")
    source = _source(db)
    raw_root = root / "raw" / "sgis_grid_official"
    raw_root.mkdir(parents=True, exist_ok=True)
    cells: dict[str, dict[str, Any]] = {}
    requests = 0
    for adm_cd in codes:
        result = session.get("SGIS", f"grid-500m-{adm_cd}", f"{base}/{GRID_PATH}", {"accessToken": token, "adm_cd": adm_cd, "grid_level_div": "500m"})
        requests += 1
        raw_path = raw_root / f"grid-500m-{adm_cd}.geojson"
        raw_path.write_bytes(result["body"])
        parsed = parse_cached_response(session, result, parse_grid_geojson)
        digest = hashlib.sha256(result["body"] + adm_cd.encode()).hexdigest()
        asset = db.get(RawDataAsset, digest) or RawDataAsset(
            id=digest, source_id=SOURCE_ID, provider="국가데이터처 / SGIS", source_url="https://sgis.kostat.go.kr/developer/html/newOpenApi/api/dataApi/admGrid.html",
            reference_period="current", storage_location=str(raw_path), collection_status=parsed["status"])
        asset.row_count = len(parsed["cells"])
        asset.request_parameters = {"adm_cd": adm_cd, "grid_level_div": "500m"}
        db.add(asset)
        for cell in parsed["cells"]:
            if cell["size_m"] == SIZE_M and cell["grid_cd"]:
                known = cells.get(cell["grid_cd"])
                # A cell on the 완산구/덕진구 border is listed by both districts: keep both codes.
                cells[cell["grid_cd"]] = dict(cell, adm_cd=f"{known['adm_cd']},{adm_cd}" if known else adm_cd)
    # The sub-cell letters must agree with the geometry (a = lower/left half, b = upper/right).
    mismatched = 0
    for cell in cells.values():
        letters = sub_cell_letters(cell["grid_cd"], cell["x_min"], cell["y_min"])
        if letters and (HALF.get(letters[0]) != cell["x_min"] % 1000 or HALF.get(letters[1]) != cell["y_min"] % 1000):
            mismatched += 1
    project = set(db.scalars(select(Grid.id)))
    linked = 0
    rows = []
    for cell in cells.values():
        grid_id = project_cell_id(cell["x_min"], cell["y_min"])
        matched = grid_id if grid_id in project else None
        linked += bool(matched)
        rows.append({"grid_cd": cell["grid_cd"], "size_m": cell["size_m"], "x_min": cell["x_min"], "y_min": cell["y_min"], "adm_cd": cell["adm_cd"],
                     "grid_id": matched, "collected_at": datetime.now(timezone.utc).isoformat()})
    db.execute(delete(SgisOfficialGridCell))
    if rows:
        db.execute(insert(SgisOfficialGridCell), rows)
    _GRID_CODES.clear()
    source.status = "PARTIAL"
    source.normalized_row_count = len(rows)
    source.raw_row_count = db.scalar(select(func.count()).select_from(RawDataAsset).where(RawDataAsset.source_id == SOURCE_ID)) or 0
    source.reference_period = "현재 (SGIS 격자 경계 API)"
    source.quality = (f"공식 500m 격자 경계·코드 {len(rows):,}개 (시군구 {len(codes)}곳, API) / 프로젝트 격자 {len(project)}개 중 {linked}개 일치"
                      f"{f' / 코드-좌표 불일치 {mismatched}개' if mismatched else ''} / 통계값은 SGIS 자료신청 필요")
    source.limitation = "경계·격자코드만 API로 받습니다. 500m 인구·가구 통계값은 SGIS 자료제공 신청(총괄 항목)으로 받은 파일을 업로드해야 합니다."
    source.collected_at = datetime.now(timezone.utc)
    db.commit()
    return {"requests": requests, "districts": codes, "cells": len(rows), "linked": linked, "project_cells": len(project), "code_mismatch": mismatched}


def _district_codes(db: Any) -> list[str]:
    """SGIS 시군구 codes of Jeonju from the collected 행정동 statistics (5-digit prefixes)."""
    try:
        from .sgis import SgisPopulationAdmin
        codes = set()
        for code in db.scalars(select(SgisPopulationAdmin.adm_code).distinct()):
            if code and len(code) >= 5:
                codes.add(code[:5])
        return sorted(codes)
    except Exception:  # noqa: BLE001 - table not there yet
        db.rollback()
        return []


def _source(db: Any) -> DataSource:
    source = db.get(DataSource, SOURCE_ID) or DataSource(
        id=SOURCE_ID, category="인구", name="SGIS 공식 500m 격자", organization="국가데이터처 / SGIS",
        source_url="https://sgis.kostat.go.kr/view/pss/openDataIntrcn", source_type="OFFICIAL", status="MANUAL_DOWNLOAD_REQUIRED")
    db.add(source)
    db.flush()
    return source


_GRID_CODES: dict[int, dict[str, str]] = {}


def official_codes(db: Any) -> dict[str, str]:
    """{project grid_id: official 500m code} (cached per row count)."""
    try:
        count = db.scalar(select(func.count()).select_from(SgisOfficialGridCell)) or 0
    except Exception:  # noqa: BLE001
        db.rollback()
        return {}
    if not count:
        return {}
    if count not in _GRID_CODES:
        _GRID_CODES.clear()
        _GRID_CODES[count] = {grid_id: code for code, grid_id in db.execute(select(SgisOfficialGridCell.grid_cd, SgisOfficialGridCell.grid_id).where(SgisOfficialGridCell.grid_id.is_not(None)))}
    return _GRID_CODES[count]


def meta(db: Any) -> dict[str, Any]:
    codes = official_codes(db)
    try:
        total = db.scalar(select(func.count()).select_from(SgisOfficialGridCell)) or 0
    except Exception:  # noqa: BLE001
        db.rollback()
        total = 0
    return {"official_cells": total, "linked": len(codes), "size_m": SIZE_M, "statistics": "SGIS 자료신청 필요 (총괄 항목)"}
