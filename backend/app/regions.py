"""전국 지역 체계: 법정 행정구역, 분석 지역(시·군·구), 격자-지역 연결.

The tool started as a Jeonju-only study. Every table keeps its nationally unique keys (grid ids are
EPSG:5179 lower-left corners, SGIS and 법정 codes are national), so several regions can live in one
database; what was missing is *which rows belong to which study region*. This module adds that:

* ``admin_units``   – every active 법정 시도·시군구·읍면동 code (행정안전부 법정동코드 전체자료).
* ``study_regions`` – a region the user analyses: one 시·군·구, or a city with 일반구 as a whole
                      (e.g. 전주시 52110 = 완산구 52111 + 덕진구 52113). Holds the SGIS codes of the same
                      area (SGIS uses its own statistical codes), preparation status per dataset, centre,
                      default grid and weather point.
* ``grid_regions``  – which 500m analysis cells belong to a region (a border cell can belong to two).

``DEFAULT_REGION`` keeps every existing call working (Jeonju) while the API takes ``region=``.
"""
from __future__ import annotations

import io
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, Text, delete, func, insert, select
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base

DEFAULT_REGION = "52110"  # 전북특별자치도 전주시 (the original study area)
LEGAL_DONG_URL = "https://www.code.go.kr/etc/codeFullDown.do"


def now() -> datetime:
    return datetime.now(timezone.utc)


class AdminUnit(Base):
    __tablename__ = "admin_units"
    code: Mapped[str] = mapped_column(String, primary_key=True)          # 10-digit 법정동코드
    level: Mapped[str] = mapped_column(String, index=True)               # SIDO | SIGUNGU | EMD | RI
    sido_code: Mapped[str] = mapped_column(String, index=True)           # 2 digits
    sigungu_code: Mapped[str] = mapped_column(String, index=True)        # 5 digits ("00000"-padded for 시도)
    name: Mapped[str] = mapped_column(String)                            # full name, e.g. "경기도 수원시 장안구"
    parent_code: Mapped[str | None] = mapped_column(String, nullable=True)
    source_version: Mapped[str | None] = mapped_column(String, nullable=True)


class StudyRegion(Base):
    __tablename__ = "study_regions"
    code: Mapped[str] = mapped_column(String, primary_key=True)          # 5-digit 법정 시군구 (city with 구: its own code)
    name: Mapped[str] = mapped_column(String)
    sido_name: Mapped[str] = mapped_column(String)
    legal_codes: Mapped[list] = mapped_column(JSON, default=list)        # 5-digit 법정 codes covered (구 of a city)
    sgis_codes: Mapped[list] = mapped_column(JSON, default=list)         # SGIS 5-digit statistical codes of the same area
    status: Mapped[str] = mapped_column(String, default="NOT_PREPARED")  # NOT_PREPARED | PREPARING | READY | PARTIAL
    datasets: Mapped[dict] = mapped_column(JSON, default=dict)           # {dataset: {status, at, rows, message}}
    grid_count: Mapped[int] = mapped_column(Integer, default=0)
    default_grid_id: Mapped[str | None] = mapped_column(String, nullable=True)
    center_lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    center_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    bbox: Mapped[list | None] = mapped_column(JSON, nullable=True)       # [west, south, east, north] (EPSG:4326)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class GridRegion(Base):
    __tablename__ = "grid_regions"
    grid_id: Mapped[str] = mapped_column(String, primary_key=True)
    region_code: Mapped[str] = mapped_column(String, primary_key=True, index=True)


class RegionWeatherMonthly(Base):
    """Monthly weather of a study region other than the original one (ERA5-Land at the region centre).

    The original region keeps ``weather_monthly`` (KMA ASOS 146 with ERA5-Land fallback)."""
    __tablename__ = "region_weather_monthly"
    region_code: Mapped[str] = mapped_column(String, primary_key=True)
    use_ym: Mapped[str] = mapped_column(String, primary_key=True)
    provider: Mapped[str] = mapped_column(String)
    source_type: Mapped[str] = mapped_column(String)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    mean_temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    precipitation: Mapped[float | None] = mapped_column(Float, nullable=True)
    hdd: Mapped[float | None] = mapped_column(Float, nullable=True)
    cdd: Mapped[float | None] = mapped_column(Float, nullable=True)
    days_observed: Mapped[int] = mapped_column(Integer)
    expected_days: Mapped[int] = mapped_column(Integer)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


# --------------------------------------------------------------------------- 법정 행정구역
def parse_legal_dong(body: bytes) -> list[dict[str, Any]]:
    """Rows of the 행정안전부 법정동코드 전체자료 zip (tab separated, cp949). Only '존재' codes."""
    archive = zipfile.ZipFile(io.BytesIO(body))
    text = archive.read(archive.namelist()[0]).decode("cp949")
    rows = []
    for line in text.splitlines()[1:]:
        cols = line.split("\t")
        if len(cols) < 3 or cols[2].strip() != "존재" or len(cols[0].strip()) != 10:
            continue
        code, name = cols[0].strip(), cols[1].strip()
        if code[2:] == "00000000":
            level, parent = "SIDO", None
        elif code[5:] == "00000":
            level, parent = "SIGUNGU", code[:2] + "00000000"
        elif code[8:] == "00":
            level, parent = "EMD", code[:5] + "00000"
        else:
            level, parent = "RI", code[:8] + "00"
        rows.append({"code": code, "level": level, "sido_code": code[:2], "sigungu_code": code[:5], "name": name, "parent_code": parent})
    return rows


def load_admin_units(db: Any, body: bytes, version: str | None = None) -> int:
    """Replace ``admin_units`` with the given legal-dong file (idempotent)."""
    rows = parse_legal_dong(body)
    for row in rows:
        row["source_version"] = version
    db.execute(delete(AdminUnit))
    for start in range(0, len(rows), 5000):
        db.execute(insert(AdminUnit), rows[start:start + 5000])
    db.commit()
    _CATALOG.clear()
    return len(rows)


def region_catalog(units: Iterable[Any]) -> list[dict[str, Any]]:
    """Selectable study regions from 시군구 units: every 시·군·구, with a city's 일반구 grouped under it.

    A 5-digit code whose last digit is not 0, whose "<first four>0" exists and whose name continues that
    unit's name is an 일반구 of that city (수원시 41110 → 장안구 41111 …). Seoul's 자치구 end in 0, so each is a region.
    """
    sigungu = {}
    sido_names = {}
    for unit in units:
        level = unit["level"] if isinstance(unit, dict) else unit.level
        code = unit["code"] if isinstance(unit, dict) else unit.code
        name = unit["name"] if isinstance(unit, dict) else unit.name
        if level == "SIDO":
            sido_names[code[:2]] = name
        elif level == "SIGUNGU":
            sigungu[code[:5]] = name
    def city_of(code: str) -> str | None:
        # An 일반구 carries its city's name: 41111 '경기도 수원시 장안구' under 41110 '경기도 수원시'.
        # A neighbouring 군 with a similar code is not one (43745 증평군 is not part of 43740 영동군).
        parent = code[:4] + "0"
        if code[4] != "0" and parent in sigungu and sigungu[code].startswith(sigungu[parent] + " "):
            return parent
        return None

    regions: dict[str, dict[str, Any]] = {}
    for code, name in sorted(sigungu.items()):
        if city_of(code):
            continue
        sido = sido_names.get(code[:2]) or name.split()[0]
        regions[code] = {"code": code, "name": name, "sido_code": code[:2], "sido_name": sido, "legal_codes": [code], "districts": []}
    for code, name in sorted(sigungu.items()):
        parent = city_of(code)
        if parent and parent in regions:
            regions[parent]["legal_codes"].append(code)
            regions[parent]["districts"].append({"code": code, "name": name.split()[-1]})
    return list(regions.values())


_CATALOG: dict[str, Any] = {}


def catalog(db: Any) -> list[dict[str, Any]]:
    """Region catalog from ``admin_units`` (empty until the legal-dong file is loaded).

    Cached per unit count, so a load by another process (the worker) shows up at once."""
    try:
        count = db.scalar(select(func.count()).select_from(AdminUnit).where(AdminUnit.level.in_(("SIDO", "SIGUNGU")))) or 0
    except Exception:  # noqa: BLE001 - table not created yet
        _rollback(db)
        return []
    if _CATALOG.get("count") == count and _CATALOG.get("rows") is not None:
        return _CATALOG["rows"]
    units = [{"code": u.code, "level": u.level, "name": u.name} for u in db.scalars(select(AdminUnit).where(AdminUnit.level.in_(("SIDO", "SIGUNGU"))))]
    rows = region_catalog(units)
    _CATALOG.update(rows=rows, count=count)
    return rows


def catalog_entry(db: Any, code: str) -> dict[str, Any] | None:
    return next((row for row in catalog(db) if row["code"] == code), None)


# --------------------------------------------------------------------------- SGIS ↔ 법정 names
_SIDO_KEYS = {
    "서울": ("서울",), "부산": ("부산",), "대구": ("대구",), "인천": ("인천",), "광주": ("광주",), "대전": ("대전",), "울산": ("울산",), "세종": ("세종",),
    "경기": ("경기",), "강원": ("강원",), "충청북": ("충북",), "충북": ("충북",), "충청남": ("충남",), "충남": ("충남",),
    "전라북": ("전북",), "전북": ("전북",), "전라남": ("전남",), "전남광주": ("전남", "광주"), "전남": ("전남",),
    "경상북": ("경북",), "경북": ("경북",), "경상남": ("경남",), "경남": ("경남",), "제주": ("제주",),
}


def sido_keys(name: str) -> tuple[str, ...]:
    """Normalised province keys: 전라북도 / 전북특별자치도 → ('전북',); 전남광주통합특별시 → ('전남', '광주')."""
    text = (name or "").replace(" ", "")
    for prefix in sorted(_SIDO_KEYS, key=len, reverse=True):
        if text.startswith(prefix):
            return _SIDO_KEYS[prefix]
    return (text[:2],) if text else ()


def split_name(full: str) -> tuple[str, str]:
    """('경기도', '수원시 장안구') from a full 시군구 name."""
    parts = (full or "").split()
    return (parts[0], " ".join(parts[1:])) if len(parts) > 1 else (full or "", full or "")


def match_sgis(legal_name: str, sgis_rows: list[dict[str, Any]]) -> list[str]:
    """SGIS 시군구 codes for a 법정 region name (city names match all their 구)."""
    sido, local = split_name(legal_name)
    keys = set(sido_keys(sido))
    if not local or local == sido:  # 세종특별자치시: the province itself
        return sorted({row["adm_code"] for row in sgis_rows if keys & set(sido_keys(split_name(row["adm_name"])[0]))})
    found = []
    for row in sgis_rows:
        row_sido, row_local = split_name(row.get("adm_name") or "")
        if not keys & set(sido_keys(row_sido)):
            continue
        if row_local == local or row_local.startswith(local + " "):
            found.append(row["adm_code"])
    return sorted(set(found))


# --------------------------------------------------------------------------- regions and grids
_GRID_IDS: dict[str, tuple[float, frozenset[str]]] = {}
GRID_CACHE_S = 120.0


def forget_region_cache(code: str | None = None) -> None:
    if code is None:
        _GRID_IDS.clear()
    else:
        _GRID_IDS.pop(code, None)


def _rollback(db: Any) -> None:
    try:
        db.rollback()
    except Exception:  # noqa: BLE001 - not a real session (tests)
        pass


def region_grid_ids(db: Any, code: str | None) -> frozenset[str]:
    """Analysis cells of a study region (cached for two minutes)."""
    code = code or DEFAULT_REGION
    hit = _GRID_IDS.get(code)
    if hit and time.monotonic() - hit[0] < GRID_CACHE_S:
        return hit[1]
    try:
        ids = frozenset(db.scalars(select(GridRegion.grid_id).where(GridRegion.region_code == code)))
    except Exception:  # noqa: BLE001 - table not created yet
        _rollback(db)
        ids = frozenset()
    if not ids and code == DEFAULT_REGION:
        # Legacy single-region databases (and tests) have grids but no links yet.
        try:
            from .models import Grid
            ids = frozenset(db.scalars(select(Grid.id)))
        except Exception:  # noqa: BLE001
            _rollback(db)
            return frozenset()
    _GRID_IDS[code] = (time.monotonic(), ids)
    return ids


def get_region(db: Any, code: str | None) -> StudyRegion | None:
    try:
        return db.get(StudyRegion, code or DEFAULT_REGION)
    except Exception:  # noqa: BLE001
        _rollback(db)
        return None


def _other_regions(db: Any, code: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(법정 codes, SGIS codes) claimed by the other study regions."""
    try:
        legal, sgis = set(), set()
        for region in db.scalars(select(StudyRegion).where(StudyRegion.code != code)):
            legal.update(region.legal_codes or [])
            sgis.update(region.sgis_codes or [])
        return tuple(sorted(legal)), tuple(sorted(sgis))
    except Exception:  # noqa: BLE001
        _rollback(db)
        return (), ()


def region_for_grid(db: Any, grid_id: str | None) -> str:
    if not grid_id:
        return DEFAULT_REGION
    try:
        codes = list(db.scalars(select(GridRegion.region_code).where(GridRegion.grid_id == grid_id)))
    except Exception:  # noqa: BLE001
        db.rollback()
        codes = []
    return DEFAULT_REGION if not codes or DEFAULT_REGION in codes else sorted(codes)[0]


def sgis_prefixes(db: Any, code: str | None) -> tuple[str, ...]:
    """SGIS 시군구 codes of the region (for filtering 행정동 statistics and boundaries)."""
    region = get_region(db, code)
    if region and region.sgis_codes:
        return tuple(region.sgis_codes)
    return ()


def link_grids(db: Any, code: str, grid_ids: Iterable[str]) -> int:
    ids = sorted(set(grid_ids))
    have = set(db.scalars(select(GridRegion.grid_id).where(GridRegion.region_code == code)))
    rows = [{"grid_id": gid, "region_code": code} for gid in ids if gid not in have]
    for start in range(0, len(rows), 5000):
        db.execute(insert(GridRegion), rows[start:start + 5000])
    forget_region_cache(code)
    return len(rows)


def ensure_default_region(db: Any) -> StudyRegion | None:
    """Register the original Jeonju study area (its grids, 법정 and SGIS codes) once."""
    from .models import Grid
    region = db.get(StudyRegion, DEFAULT_REGION)
    grid_ids = list(db.scalars(select(Grid.id)))
    if region is None:
        if not grid_ids:
            return None
        sgis = _jeonju_sgis_codes(db)
        region = StudyRegion(code=DEFAULT_REGION, name="전북특별자치도 전주시", sido_name="전북특별자치도", legal_codes=["52111", "52113"],
                             sgis_codes=sgis, status="READY", datasets={"grid": {"status": "DONE", "rows": len(grid_ids), "message": "기존 전주 분석 격자"}},
                             grid_count=len(grid_ids), message="최초 연구 지역 (기존 자료)")
        db.add(region)
        db.flush()
    if not db.scalar(select(func.count()).select_from(GridRegion).where(GridRegion.region_code == DEFAULT_REGION)):
        # Only grids that no other region claims are Jeonju's legacy cells.
        claimed = set(db.scalars(select(GridRegion.grid_id)))
        link_grids(db, DEFAULT_REGION, [gid for gid in grid_ids if gid not in claimed])
    if not region.sgis_codes:
        region.sgis_codes = _jeonju_sgis_codes(db)
    region.grid_count = db.scalar(select(func.count()).select_from(GridRegion).where(GridRegion.region_code == DEFAULT_REGION)) or 0
    _set_center(db, region)
    try:
        from .models import TestbedSector
        sector = db.get(TestbedSector, "prototype")
        if sector and not region.default_grid_id:
            region.default_grid_id = sector.grid_id
    except Exception:  # noqa: BLE001
        pass
    db.commit()
    return region


def _jeonju_sgis_codes(db: Any) -> list[str]:
    try:
        from .sgis import SgisPopulationAdmin
        codes = {code[:5] for code, name in db.execute(select(SgisPopulationAdmin.adm_code, SgisPopulationAdmin.adm_name)) if code and len(code) >= 5 and "전주" in (name or "")}
        return sorted(codes)
    except Exception:  # noqa: BLE001
        db.rollback()
        return []


def _set_center(db: Any, region: StudyRegion) -> None:
    """Centre and bbox (EPSG:4326) from the grid ids (cell_<x>_<y> are EPSG:5179 lower-left corners)."""
    from pyproj import Transformer
    ids = region_grid_ids(db, region.code)
    xs, ys = [], []
    for gid in ids:
        try:
            _, x, y = gid.split("_")
            xs.append(float(x)); ys.append(float(y))
        except ValueError:
            continue
    if not xs:
        return
    to4326 = Transformer.from_crs(5179, 4326, always_xy=True).transform
    west, south = to4326(min(xs), min(ys))
    east, north = to4326(max(xs) + 500, max(ys) + 500)
    region.bbox = [round(west, 6), round(south, 6), round(east, 6), round(north, 6)]
    cx, cy = to4326((min(xs) + max(xs) + 500) / 2, (min(ys) + max(ys) + 500) / 2)
    region.center_lon, region.center_lat = round(cx, 6), round(cy, 6)


# Layers only a region's own collection brings in (the rest of a region comes from the national base layers).
DETAIL_STEPS = ("zoning", "buildings", "register", "building_energy", "kapt_energy")


def detail_level(region: StudyRegion | None) -> str:
    """How far a region's map goes.

    * ``DETAILED``: the region's own collection brought energy, buildings, zoning or the building register.
    * ``BASIC``: analysis cells built from the national layers only (SGIS grid statistics, 행정동, K-apt list, 조례).
    * ``NONE``: no analysis cells yet (opening the region builds them in seconds).
    """
    if region is None or not region.grid_count:
        return "NONE"
    if region.code == DEFAULT_REGION:
        return "DETAILED"
    datasets = region.datasets or {}
    return "DETAILED" if any((datasets.get(step) or {}).get("status") == "DONE" for step in DETAIL_STEPS) else "BASIC"


def region_summary(region: StudyRegion | None) -> dict[str, Any] | None:
    if region is None:
        return None
    return {"code": region.code, "name": region.name, "sido_name": region.sido_name, "status": region.status, "level": detail_level(region), "legal_codes": region.legal_codes,
            "sgis_codes": region.sgis_codes, "grid_count": region.grid_count, "default_grid_id": region.default_grid_id,
            "center": [region.center_lon, region.center_lat] if region.center_lon is not None else None, "bbox": region.bbox,
            "datasets": region.datasets or {}, "message": region.message,
            "updated_at": region.updated_at.isoformat() if region.updated_at else None}


def short_name(full: str) -> str:
    """'전북특별자치도 전주시' → '전주시'; '서울특별시 종로구' → '종로구'; '세종특별자치시' stays."""
    parts = (full or "").split()
    return " ".join(parts[1:]) if len(parts) > 1 else (full or "")


# --------------------------------------------------------------------------- scope used by the readers
@dataclass(frozen=True)
class Scope:
    """What a reader needs to know about the region it answers for."""
    code: str
    name: str
    short: str
    grid_ids: frozenset[str]
    legal_codes: tuple[str, ...]
    sgis_codes: tuple[str, ...]
    center: tuple[float, float] | None
    bbox: tuple[float, float, float, float] | None
    default_grid_id: str | None
    status: str
    is_default: bool
    # 법정/SGIS codes of the other study regions. The original region keeps its legacy rule "everything the
    # database holds belongs to it" for rows no other region claims (older rows carry no region).
    foreign_legal: tuple[str, ...] = ()
    foreign_sgis: tuple[str, ...] = ()

    def has(self, grid_id: str | None) -> bool:
        return bool(grid_id) and grid_id in self.grid_ids

    def owns_legal(self, code: str | None) -> bool:
        """A 법정동/PNU/bjd code (any length ≥ 5) inside the region's 법정 시·군·구."""
        if not code:
            return False
        prefix = str(code)[:5]
        if prefix in self.legal_codes:
            return True
        return self.is_default and prefix not in self.foreign_legal

    def owns_complex(self, bjd_code: str | None, grid_id: str | None) -> bool:
        return self.owns_legal(bjd_code) if bjd_code else (self.has(grid_id) if not self.is_default else grid_id is None or self.has(grid_id))

    def owns_sgis(self, code: str | None) -> bool:
        """An SGIS 시군구/행정동 code inside the region (SGIS 행정동 codes start with their 시군구 code)."""
        if not code:
            return False
        if any(str(code).startswith(prefix) for prefix in self.sgis_codes):
            return True
        return self.is_default and not any(str(code).startswith(prefix) for prefix in self.foreign_sgis) and not self.sgis_codes

    def legal_clause(self, column: Any) -> Any:
        """SQL condition on a 5-digit 법정 시·군·구 column (energy_monthly.sigungu_code): None = no filter."""
        if not self.is_default:
            return column.in_(list(self.legal_codes))
        if self.foreign_legal:
            return column.notin_(list(self.foreign_legal))
        return None


class RegionNotReady(LookupError):
    pass


JEONJU_CENTER = (127.148, 35.8242)


def scope(db: Any, code: str | None = None) -> Scope:
    """The study region of ``code`` (the original region when empty). Unknown or unprepared → RegionNotReady."""
    code = (code or DEFAULT_REGION).strip()
    region = get_region(db, code)
    if region is None and code != DEFAULT_REGION:
        raise RegionNotReady(f"아직 지도를 만들지 않은 지역입니다(준비하지 않은 지역): {code}. 지도를 열면 전국 공통 자료로 몇 초 만에 만듭니다")
    grid_ids = region_grid_ids(db, code)
    if code != DEFAULT_REGION and not grid_ids:
        raise RegionNotReady(f"{region.name if region else code}의 분석 격자가 아직 없습니다. 지도를 열면 전국 공통 자료로 몇 초 만에 만듭니다")
    foreign_legal, foreign_sgis = _other_regions(db, code) if code == DEFAULT_REGION else ((), ())
    if region is None:  # legacy database without the region tables filled
        return Scope(DEFAULT_REGION, "전북특별자치도 전주시", "전주시", grid_ids, ("52111", "52113"), (), JEONJU_CENTER, None, None, "READY", True,
                     foreign_legal, foreign_sgis)
    center = (region.center_lon, region.center_lat) if region.center_lon is not None and region.center_lat is not None else (JEONJU_CENTER if code == DEFAULT_REGION else None)
    return Scope(code=region.code, name=region.name, short=short_name(region.name), grid_ids=grid_ids,
                 legal_codes=tuple(region.legal_codes or ()), sgis_codes=tuple(region.sgis_codes or ()), center=center,
                 bbox=tuple(region.bbox) if region.bbox else None, default_grid_id=region.default_grid_id,
                 status=region.status, is_default=region.code == DEFAULT_REGION, foreign_legal=foreign_legal, foreign_sgis=foreign_sgis)


def weather_rows(db: Any, region_code: str | None, first_ym: str, last_ym: str) -> list[Any]:
    """Monthly weather rows (YYYYMM range) of a region: ``weather_monthly`` for the original region,
    ``region_weather_monthly`` for the others. Both expose the same attribute names."""
    from .models import WeatherMonthly
    code = region_code or DEFAULT_REGION
    if code == DEFAULT_REGION:
        return list(db.scalars(select(WeatherMonthly).where(WeatherMonthly.use_ym.between(first_ym, last_ym)).order_by(WeatherMonthly.use_ym)))
    try:
        return list(db.scalars(select(RegionWeatherMonthly).where(RegionWeatherMonthly.region_code == code,
                                                                  RegionWeatherMonthly.use_ym.between(first_ym, last_ym)).order_by(RegionWeatherMonthly.use_ym)))
    except Exception:  # noqa: BLE001 - table not created yet
        db.rollback()
        return []


def legal_leaves(db: Any, legal_codes: Iterable[str]) -> list[dict[str, str]]:
    """법정동/리 codes that 건축HUB answers for (the lowest level: 동, or 리 inside 읍·면), sorted.

    ``[{"sigunguCd", "bjdongCd", "name"}]`` — the same shape as ``official.register_regions``."""
    codes = set(legal_codes)
    if not codes:
        return []
    units = list(db.scalars(select(AdminUnit).where(AdminUnit.sigungu_code.in_(codes), AdminUnit.level.in_(("EMD", "RI")))))
    with_children = {u.parent_code for u in units if u.level == "RI"}
    leaves = [u for u in units if u.level == "RI" or u.code not in with_children]
    return [{"sigunguCd": u.code[:5], "bjdongCd": u.code[5:], "name": u.name} for u in sorted(leaves, key=lambda u: u.code)]


def list_codes(legal_codes: Iterable[str]) -> list[str]:
    """법정 codes that K-apt/건축HUB lists answer for: a city's 일반구 instead of the city code itself.
    (A region's legal codes are the city and its 일반구 only, so a shared 4-digit prefix means "district".)"""
    codes = list(dict.fromkeys(legal_codes))
    return [c for c in codes if not (c.endswith("0") and any(o != c and o[:4] == c[:4] for o in codes))]


def grid_cell_geometry(grid_id: str) -> tuple[float, float, float, float] | None:
    """(x_min, y_min, x_max, y_max) in EPSG:5179 of an analysis cell id ``cell_<x>_<y>``."""
    try:
        _, x, y = grid_id.split("_")
        x0, y0 = float(x), float(y)
    except (ValueError, AttributeError):
        return None
    return x0, y0, x0 + 500.0, y0 + 500.0
