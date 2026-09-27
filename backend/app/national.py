"""전국 기초 자료: 행정구역, SGIS 시군구·행정동 인구·가구·경계, K-apt 단지 목록, SGIS 공식 500m 격자.

These are the national layers whose collection fits in the providers' limits (hundreds of requests,
not hundreds of thousands). Quota-bound layers (K-apt monthly energy, 건축HUB energy, 건축물대장,
VWorld zoning/buildings) are collected per study region when the region is prepared.

Every value keeps the provider's meaning: SGIS suppressed values stay ``None`` with their status,
a 시군구 whose SGIS code cannot be matched to a 법정 region is kept without a region (never guessed).
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from geoalchemy2 import Geometry
from geoalchemy2.shape import from_shape
from sqlalchemy import JSON, DateTime, Float, Integer, String, Text, func, select, text
from sqlalchemy.orm import Mapped, mapped_column

from .cache import CachedClient, ExternalError, parse_cached_response
from .db import Base
from .regions import StudyRegion, catalog, list_codes, load_admin_units, match_sgis

Log = Callable[[str], None]


def now() -> datetime:
    return datetime.now(timezone.utc)


class NationalUnit(Base):
    """SGIS administrative statistics and simplified boundaries for all of Korea (one row per year and code)."""
    __tablename__ = "national_units"
    id: Mapped[str] = mapped_column(String, primary_key=True)            # "<year>:<adm_code>"
    year: Mapped[int] = mapped_column(Integer, index=True)
    level: Mapped[str] = mapped_column(String, index=True)               # SIDO | SIGUNGU | EMD
    adm_code: Mapped[str] = mapped_column(String, index=True)            # SGIS statistical code
    adm_name: Mapped[str | None] = mapped_column(String, nullable=True)
    parent_code: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    region_code: Mapped[str | None] = mapped_column(String, index=True, nullable=True)  # study region (법정) it belongs to
    population: Mapped[float | None] = mapped_column(Float, nullable=True)
    population_status: Mapped[str | None] = mapped_column(String, nullable=True)
    households: Mapped[float | None] = mapped_column(Float, nullable=True)
    household_status: Mapped[str | None] = mapped_column(String, nullable=True)
    area_m2: Mapped[float | None] = mapped_column(Float, nullable=True)
    geom: Mapped[object | None] = mapped_column(Geometry("GEOMETRY", srid=5179, spatial_index=True), nullable=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class NationalComplex(Base):
    """K-apt 공동주택 단지 목록 (전국). Coordinates come from the list itself (K-apt TM → WGS84)."""
    __tablename__ = "national_complexes"
    kapt_code: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    bjd_code: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    sigungu_code: Mapped[str | None] = mapped_column(String, index=True, nullable=True)   # 5-digit 법정 code of the list request
    region_code: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    approval_month: Mapped[str | None] = mapped_column(String, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    snapshot_month: Mapped[str] = mapped_column(String)
    raw_record: Mapped[dict] = mapped_column(JSON, default=dict)


def _root() -> Path:
    return Path(os.getenv("DATA_DIR", "data"))


def _source(db: Any, source_id: str, name: str, organization: str, url: str, category: str = "기초") -> Any:
    from .models import DataSource
    source = db.get(DataSource, source_id) or DataSource(id=source_id, category=category, name=name, organization=organization,
                                                         source_url=url, source_type="OFFICIAL", status="NOT_COLLECTED")
    source.geographic_coverage = "전국"
    db.add(source)
    db.flush()
    return source


# --------------------------------------------------------------------------- 법정 행정구역
def collect_admin_units(db: Any, log: Log = print) -> dict[str, Any]:
    """전국 법정동코드 (행정안전부 code.go.kr 전체자료) → admin_units."""
    from .collectors import RAW, downloaded, record_asset, update_source
    _source(db, "admin_units", "전국 법정 행정구역 코드", "행정안전부", LEGAL_URL)
    result = downloaded(db, "admin_units", "legal-dong.zip", LEGAL_URL, {"codeseId": "법정동코드"})
    version = hashlib.sha256(result["body"]).hexdigest()
    count = load_admin_units(db, result["body"], version[:16])
    record_asset(db, "admin_units", dict(result, path=str(RAW / "legal-dong.zip")), count, "현행 코드 SHA256:" + version[:16])
    regions = catalog(db)
    update_source(db, "admin_units", count, count, quality=f"법정 행정구역 {count:,}개 (분석 가능 시·군·구 {len(regions)}곳)", missing=0)
    log(f"법정 행정구역 {count}개, 분석 지역 {len(regions)}곳")
    return {"units": count, "regions": len(regions)}


LEGAL_URL = "https://www.code.go.kr/etc/codeFullDown.do"


# --------------------------------------------------------------------------- SGIS 전국 인구·가구·경계
class _Sgis:
    def __init__(self, db: Any, year: int, log: Log):
        from .sgis import SGIS_BASE_URL, SgisTokenManager
        self.db, self.year, self.log = db, year, log
        self.root = _root()
        self.manager = SgisTokenManager(os.getenv("SGIS_CONSUMER_KEY", "").strip(), os.getenv("SGIS_CONSUMER_SECRET", "").strip())
        self.session = CachedClient(self.root / "cache" / "sgis", min_interval=0.3)
        self.base = os.getenv("SGIS_BASE_URL", SGIS_BASE_URL).rstrip("/")
        self.requests = 0
        self.raw_dir = self.root / "raw" / "sgis-national" / str(year)
        self.raw_dir.mkdir(parents=True, exist_ok=True)

    def get(self, name: str, path: str, params: dict[str, Any], parser: Callable[[bytes], dict[str, Any]]) -> dict[str, Any]:
        query = {"accessToken": self.manager.get_token(), **{k: str(v) for k, v in params.items() if v is not None}}
        result = self.session.get("SGIS", f"national-{name}", f"{self.base}/{path}", query)
        self.requests += 1
        (self.raw_dir / f"{name}.json").write_bytes(result["body"])
        return parse_cached_response(self.session, result, parser)


def _pick_year(sgis: _Sgis, requested: int) -> tuple[int, dict[str, Any]]:
    from .sgis import parse_sgis_statistics
    last = None
    for year in range(requested, max(2014, requested - 6), -1):
        try:
            parsed = sgis.get(f"population-{year}-sido", "stats/searchpopulation.json", {"year": year}, lambda b: parse_sgis_statistics(b, "population"))
        except ExternalError as exc:
            if "인증" in str(exc):
                raise
            last = exc
            continue
        if parsed["status"] == "SUCCESS" and parsed["rows"]:
            return year, parsed
    raise last or ExternalError("SGIS가 최근 6개 연도에 공표 자료를 제공하지 않습니다")


def _upsert_unit(db: Any, year: int, level: str, row: dict[str, Any], parent: str | None, *, households: dict[str, Any] | None = None) -> Any:
    key = f"{year}:{row['adm_code']}"
    unit = db.get(NationalUnit, key) or NationalUnit(id=key, year=year, level=level, adm_code=row["adm_code"])
    unit.adm_name = row.get("adm_name") or unit.adm_name
    unit.parent_code = parent
    if "value" in row:
        unit.population, unit.population_status = row["value"], row["value_status"]
    if households is not None:
        unit.households, unit.household_status = households.get("value"), households.get("value_status")
    unit.collected_at = now()
    db.add(unit)
    return unit


def _store_geometry(db: Any, year: int, level: str, parent: str | None, parsed: dict[str, Any], tolerance: float) -> int:
    stored = 0
    for feature in parsed.get("features") or []:
        if not feature["adm_code"]:
            continue
        key = f"{year}:{feature['adm_code']}"
        unit = db.get(NationalUnit, key) or NationalUnit(id=key, year=year, level=level, adm_code=feature["adm_code"], parent_code=parent)
        unit.adm_name = unit.adm_name or feature["adm_name"]
        geometry = feature["geometry"]
        unit.area_m2 = float(geometry.area)
        simple = geometry.simplify(tolerance, preserve_topology=True) if tolerance else geometry
        unit.geom = from_shape(simple if not simple.is_empty else geometry, srid=5179)
        db.add(unit)
        stored += 1
    return stored


def collect_national_sgis(db: Any, year: int | None = None, *, include_emd: bool = True, log: Log = print) -> dict[str, Any]:
    """시도 → 시군구 → (행정동) population, households and boundaries for all of Korea.

    Requests: 1 (시도) + 3 per 시도 + 3 per 시군구 when ``include_emd`` (about 800 in total).
    """
    from .collectors import update_source
    from .sgis import parse_sgis_boundary, parse_sgis_statistics
    source = _source(db, "sgis_national", "SGIS 전국 시군구·행정동 인구·가구·경계", "국가데이터처 / SGIS",
                     "https://sgis.kostat.go.kr/developer/html/newOpenApi/api/dataApi/basics.html", "인구")
    db.commit()
    sgis = _Sgis(db, int(year or os.getenv("SGIS_BASE_YEAR", "2024")), log)
    used, national = _pick_year(sgis, sgis.year)
    sgis.year = used
    pop = lambda b: parse_sgis_statistics(b, "population")  # noqa: E731
    hh = lambda b: parse_sgis_statistics(b, "household")  # noqa: E731
    counts = {"SIDO": 0, "SIGUNGU": 0, "EMD": 0, "boundaries": 0}
    sigungu_rows: list[dict[str, Any]] = []
    for sido in national["rows"]:
        _upsert_unit(db, used, "SIDO", sido, None)
        counts["SIDO"] += 1
        code = sido["adm_code"]
        districts = sgis.get(f"population-{used}-{code}", "stats/searchpopulation.json", {"year": used, "adm_cd": code, "low_search": 1}, pop)
        households = sgis.get(f"household-{used}-{code}", "stats/household.json", {"year": used, "adm_cd": code, "low_search": 1}, hh)
        by_code = {row["adm_code"]: row for row in households["rows"]}
        for row in districts["rows"]:
            _upsert_unit(db, used, "SIGUNGU", row, code, households=by_code.get(row["adm_code"], {}))
            sigungu_rows.append(row)
            counts["SIGUNGU"] += 1
        boundary = sgis.get(f"boundary-{used}-{code}", "boundary/hadmarea.geojson", {"year": used, "adm_cd": code, "low_search": 1}, parse_sgis_boundary)
        counts["boundaries"] += _store_geometry(db, used, "SIGUNGU", code, boundary, 30.0)
        db.commit()
        log(f"{sido.get('adm_name')}: 시군구 {len(districts['rows'])}곳")
    if include_emd:
        for index, district in enumerate(sigungu_rows, 1):
            code = district["adm_code"]
            try:
                dongs = sgis.get(f"population-{used}-{code}", "stats/searchpopulation.json", {"year": used, "adm_cd": code, "low_search": 1}, pop)
                households = sgis.get(f"household-{used}-{code}", "stats/household.json", {"year": used, "adm_cd": code, "low_search": 1}, hh)
                boundary = sgis.get(f"boundary-{used}-{code}", "boundary/hadmarea.geojson", {"year": used, "adm_cd": code, "low_search": 1}, parse_sgis_boundary)
            except ExternalError as exc:
                if "인증" in str(exc):
                    raise
                log(f"{district.get('adm_name')} 행정동 실패: {exc}")
                continue
            by_code = {row["adm_code"]: row for row in households["rows"]}
            for row in dongs["rows"]:
                _upsert_unit(db, used, "EMD", row, code, households=by_code.get(row["adm_code"], {}))
                counts["EMD"] += 1
            counts["boundaries"] += _store_geometry(db, used, "EMD", code, boundary, 10.0)
            db.commit()
            if index % 25 == 0:
                log(f"행정동 {index}/{len(sigungu_rows)} 시군구")
    mapped = assign_units_to_regions(db, used)
    source.reference_period = str(used)
    db.commit()
    update_source(db, "sgis_national", counts["SIGUNGU"] + counts["EMD"], sgis.requests, status="COLLECTED",
                  quality=f"SGIS {used} 시도 {counts['SIDO']}·시군구 {counts['SIGUNGU']}·행정동 {counts['EMD']} / 경계 {counts['boundaries']}개 (단순화) / 법정 지역 연결 {mapped['matched']}곳, 미연결 {mapped['unmatched']}곳",
                  missing=mapped["unmatched"])
    return dict(counts, year=used, requests=sgis.requests, **mapped)


def assign_units_to_regions(db: Any, year: int) -> dict[str, Any]:
    """Tag SGIS 시군구/행정동 rows with the 법정 study region of the same name (never guessed)."""
    sigungu = [{"adm_code": u.adm_code, "adm_name": u.adm_name} for u in db.scalars(select(NationalUnit).where(NationalUnit.year == year, NationalUnit.level == "SIGUNGU"))]
    code_to_region: dict[str, str] = {}
    for region in catalog(db):
        for code in match_sgis(region["name"], sigungu):
            code_to_region.setdefault(code, region["code"])
    for unit in db.scalars(select(NationalUnit).where(NationalUnit.year == year)):
        if unit.level == "SIGUNGU":
            unit.region_code = code_to_region.get(unit.adm_code)
        elif unit.level == "EMD":
            unit.region_code = code_to_region.get(unit.parent_code or unit.adm_code[:5])
    # Keep the SGIS codes on the study regions that already exist.
    for region in db.scalars(select(StudyRegion)):
        codes = sorted(code for code, owner in code_to_region.items() if owner == region.code)
        if codes:
            region.sgis_codes = codes
    db.commit()
    unmatched = [row["adm_name"] for row in sigungu if row["adm_code"] not in code_to_region]
    return {"matched": len(set(code_to_region.values())), "unmatched": len(unmatched), "unmatched_names": unmatched[:20]}


def sgis_codes_for(db: Any, region_code: str) -> list[str]:
    try:
        year = db.scalar(select(func.max(NationalUnit.year)))
        if not year:
            return []
        return sorted(db.scalars(select(NationalUnit.adm_code).where(NationalUnit.year == year, NationalUnit.level == "SIGUNGU", NationalUnit.region_code == region_code)))
    except Exception:  # noqa: BLE001
        db.rollback()
        return []


# --------------------------------------------------------------------------- K-apt 단지 목록 (전국)
def collect_national_complexes(db: Any, search_month: str | None = None, *, log: Log = print, delay_s: float = 0.6) -> dict[str, Any]:
    """K-apt 공동주택 단지 목록 for every 법정 시·군·구 (≈ 260 list requests, no detail pages)."""
    import re

    import httpx

    from .collectors import update_source
    from .kapt import KAPT_LIST_URL, KAPT_MAIN_URL, _coordinates
    from .settings import offline_mode
    if offline_mode():
        raise ExternalError("오프라인 모드: K-apt 목록을 받지 않습니다")
    month = search_month or datetime.now(timezone.utc).strftime("%Y%m")
    _source(db, "kapt_national", "K-apt 공동주택 단지 목록 (전국)", "국토교통부 / 한국부동산원 K-apt", KAPT_MAIN_URL, "건물")
    db.commit()
    client = httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": "Carbon-Urban-DSS/1.0 public-data-research", "Accept-Language": "ko-KR,ko;q=0.9"})
    landing = client.get(KAPT_MAIN_URL)
    match = re.search(r'<meta\s+name="_csrf"\s+content="([^"]+)"', landing.text)
    if not match:
        raise ExternalError("K-apt 첫 화면에 CSRF 토큰이 없습니다")
    token = match.group(1)
    headers = {"X-CSRF-TOKEN": token, "X-Requested-With": "XMLHttpRequest"}
    raw_dir = _root() / "raw" / "kapt-national" / month
    raw_dir.mkdir(parents=True, exist_ok=True)
    regions = catalog(db)
    leaf_codes = []
    for region in regions:
        leaf_codes += [(code, region["code"]) for code in list_codes(region["legal_codes"])]
    stored, failed, requests = 0, [], 0
    for index, (code, region_code) in enumerate(leaf_codes, 1):
        raw_path = raw_dir / f"list-{code}.json"
        try:
            if raw_path.exists():
                payload = json.loads(raw_path.read_text(encoding="utf-8"))
            else:
                time.sleep(delay_s)
                response = client.post(KAPT_LIST_URL, data={"bjdCode": code, "kaptName": "", "searchDate": month, "kaptDuty": "ALL", "_csrf": token}, headers=headers)
                requests += 1
                response.raise_for_status()
                payload = response.json()
                raw_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        except (httpx.HTTPError, ValueError) as exc:
            failed.append({"code": code, "error": type(exc).__name__})
            continue
        for record in payload.get("resultList") or []:
            kapt_code = record.get("kaptCode")
            if not kapt_code:
                continue
            lon, lat = _coordinates(record)
            row = db.get(NationalComplex, kapt_code) or NationalComplex(kapt_code=kapt_code, snapshot_month=month)
            row.name = record.get("kaptName") or row.name or kapt_code
            row.bjd_code = record.get("bjdCode")
            row.sigungu_code = code
            row.region_code = region_code
            row.address = (record.get("addr") or "").strip() or None
            row.approval_month = record.get("kaptUsedate")
            row.longitude, row.latitude = lon, lat
            row.snapshot_month = month
            row.raw_record = {k: record.get(k) for k in ("kaptCode", "kaptName", "bjdCode", "bjdName", "bun1", "bun2", "addr", "kaptUsedate", "occuFirstDate", "x", "y")}
            db.add(row)
            stored += 1
        db.commit()
        if index % 30 == 0:
            log(f"K-apt 단지 목록 {index}/{len(leaf_codes)} 시군구, 누적 {stored}건")
    total = db.scalar(select(func.count()).select_from(NationalComplex)) or 0
    update_source(db, "kapt_national", total, requests, status="COLLECTED" if not failed else "PARTIAL",
                  quality=f"K-apt 단지 목록 {total:,}개 ({len(leaf_codes)}개 시군구·구 조회, 기준 {month}){f' / 실패 {len(failed)}곳' if failed else ''}",
                  missing=len(failed))
    return {"complexes": total, "requests": requests, "districts": len(leaf_codes), "failed": failed[:20], "month": month}


# --------------------------------------------------------------------------- SGIS 공식 500m 격자 (전국)
def collect_national_grid500(db: Any, *, log: Log = print, codes: list[str] | None = None) -> dict[str, Any]:
    """Official 500m cell codes and boundaries of every SGIS 시군구 (additive; border cells keep all districts)."""
    from .sgis_grid_official import collect_sgis_grid_official
    if codes is None:
        year = db.scalar(select(func.max(NationalUnit.year)))
        codes = sorted(db.scalars(select(NationalUnit.adm_code).where(NationalUnit.year == year, NationalUnit.level == "SIGUNGU"))) if year else []
    if not codes:
        raise ExternalError("SGIS 시군구 코드가 없습니다: 전국 SGIS 인구·경계를 먼저 받으세요")
    total = {"requests": 0, "cells": 0}
    for start in range(0, len(codes), 20):
        batch = codes[start:start + 20]
        result = collect_sgis_grid_official(db, district_codes=batch)
        total["requests"] += result["requests"]
        total["cells"] = result["cells"]
        log(f"SGIS 500m 격자 {min(start + 20, len(codes))}/{len(codes)} 시군구, 누적 {result['cells']:,}칸")
    return total


# --------------------------------------------------------------------------- 전국 개요 지도
_OVERVIEW: dict[str, Any] = {}


def national_overview(db: Any) -> dict[str, Any]:
    """Regions of Korea with SGIS population/households, K-apt complex counts, area and study status.

    Geometry: SGIS 시군구 boundaries unioned per study region and simplified (display only).
    Cached until the underlying row counts change.
    """
    try:
        year = db.scalar(select(func.max(NationalUnit.year)))
        units = db.scalar(select(func.count()).select_from(NationalUnit)) or 0
        complexes = db.scalar(select(func.count()).select_from(NationalComplex)) or 0
        studies = [(r.code, r.status, r.updated_at) for r in db.scalars(select(StudyRegion))]
    except Exception:  # noqa: BLE001
        db.rollback()
        return {"type": "FeatureCollection", "features": [], "meta": {"year": None, "regions": 0}}
    key = json.dumps([year, units, complexes, [(c, s, str(u)) for c, s, u in studies]])
    if _OVERVIEW.get("key") == key:
        return _OVERVIEW["value"]
    stats: dict[str, dict[str, Any]] = {}
    for unit in db.scalars(select(NationalUnit).where(NationalUnit.year == year, NationalUnit.level == "SIGUNGU", NationalUnit.region_code.is_not(None))):
        item = stats.setdefault(unit.region_code, {"population": 0.0, "households": 0.0, "area_m2": 0.0, "suppressed": 0, "sgis_codes": []})
        item["sgis_codes"].append(unit.adm_code)
        for field in ("population", "households", "area_m2"):
            value = getattr(unit, field)
            if value is None:
                item["suppressed"] += field != "area_m2"
            else:
                item[field] += value
    counts = dict(db.execute(select(NationalComplex.region_code, func.count()).group_by(NationalComplex.region_code)).all())
    geometry: dict[str, Any] = {}
    try:
        rows = db.execute(text(
            "SELECT region_code, ST_AsGeoJSON(ST_Transform(ST_SimplifyPreserveTopology(ST_Union(geom), 150), 4326), 5) AS g "
            "FROM national_units WHERE year = :y AND level = 'SIGUNGU' AND region_code IS NOT NULL AND geom IS NOT NULL GROUP BY region_code"), {"y": year})
        geometry = {code: json.loads(g) for code, g in rows if g}
    except Exception:  # noqa: BLE001 - no PostGIS (tests)
        db.rollback()
    status = {code: state for code, state, _ in studies}
    features = []
    for region in catalog(db):
        s = stats.get(region["code"], {})
        area_km2 = s.get("area_m2", 0) / 1e6 if s.get("area_m2") else None
        population = s.get("population") if s else None
        features.append({"type": "Feature", "id": region["code"], "geometry": geometry.get(region["code"]), "properties": {
            "code": region["code"], "name": region["name"], "sido_name": region["sido_name"], "districts": region["districts"],
            "population": population, "households": s.get("households") if s else None,
            "density": round(population / area_km2, 1) if population and area_km2 else None, "area_km2": round(area_km2, 2) if area_km2 else None,
            "complexes": counts.get(region["code"], 0), "study_status": status.get(region["code"], "NOT_PREPARED"),
            "sgis_codes": s.get("sgis_codes", [])}})
    value = {"type": "FeatureCollection", "features": features,
             "meta": {"year": year, "regions": len(features), "with_geometry": sum(1 for f in features if f["geometry"]), "complexes": complexes,
                      "sources": {"population": f"SGIS {year} 행정구역 통계 (시군구 합)" if year else None, "complexes": "K-apt 단지 목록", "units": "행정안전부 법정동코드"}}}
    _OVERVIEW.update(key=key, value=value)
    return value
