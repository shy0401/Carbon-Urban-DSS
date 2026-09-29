"""SGIS 500m 격자 통계 (SGIS 자료제공 신청분, 2000~2024).

신청해서 받은 파일(DATA_DIR/raw/sgis_grid_500m/**/<연도>년_<주제>_<100km 블록>_500M.csv)을 읽는다.

* 파일 형식: 머리줄 없는 ``기준연도,격자코드,통계항목,값`` (cp949). 격자코드는 SGIS 500m 코드(예: 다마62a48a),
  프로젝트 분석 격자 ``cell_<x>_<y>``(EPSG:5179 좌하단)와 모서리가 같다.
* 500m 격자는 총괄 항목만 제공된다(statistics_code.xls '격자' 시트): 총인구·남·여(to_in_001/007/008),
  총가구(to_ga_001), 총주택(to_ho_001), 총사업체(to_fa_010), 총종사자(to_em_020). 나이·주택유형 등 세부는 1km뿐이다.
* 통계자료 이용안내(statistics_guide.hwp)의 비밀보호: 인구 부문 5 미만은 0 또는 5로, 사업체 부문 3 미만은 0 또는 3으로
  확률 대체했고, 그 이상 값에는 최대 ±7(사업체 ±4)의 잡음이 있다. 그래서 값은 "잡음 포함 공식 통계"로 보여 주고,
  0·5(사업체 0·3)는 '작은 값(대체 가능)'으로 표시한다. 파일에 행이 없는 격자·항목은 '통계 없음'이지 0이 아니다.
* 인구주택총조사 2000·2005·2010은 인구만, 2015~2024는 다섯 주제 모두. 사업체는 연도마다 산업분류가 다르지만
  총괄 항목(총사업체·총종사자)은 영향이 없다. '9023년' 파일은 이용안내에 없는 연도 표기라 읽지 않는다.
"""
from __future__ import annotations

import json
import re
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

from fastapi import APIRouter, HTTPException
from sqlalchemy import Float, Integer, String, delete, func, insert, select, text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base

SOURCE_ID = "sgis_grid_500m_stats"
BLOCKS = "가나다라마바사아"
X0, Y0 = 700000, 1300000
MIN_BASE = 20  # 증감률을 낼 때 두 해 모두 이만큼은 있어야 한다 (작은 값·잡음 영향)
FILE_RE = re.compile(r"^(\d{4})년_(인구|가구|주택|사업체|종사자)_([가-힣]{2})_500M\.csv$")
ITEMS = {"to_in_001": "population", "to_in_007": "male", "to_in_008": "female", "to_ga_001": "households",
         "to_ho_001": "housing", "to_fa_010": "businesses", "to_em_020": "workers"}
VALUE_COLUMNS = ("population", "male", "female", "households", "housing", "businesses", "workers")
BUSINESS_PART = ("businesses", "workers")  # 사업체 부문: 작은 값 기준 3
SMALL = {"population": (0.0, 5.0), "households": (0.0, 5.0), "housing": (0.0, 5.0), "businesses": (0.0, 3.0), "workers": (0.0, 3.0)}
SOURCE_TEXT = "SGIS 500m 격자 통계 (자료제공 신청분, 비밀보호 잡음 포함)"


class SgisGrid500Value(Base):
    __tablename__ = "sgis_grid500_values"
    id: Mapped[str] = mapped_column(String, primary_key=True)  # "<year>:<grid_cd>"
    year: Mapped[int] = mapped_column(Integer, index=True)
    grid_cd: Mapped[str] = mapped_column(String, index=True)
    population: Mapped[float | None] = mapped_column(Float, nullable=True)
    male: Mapped[float | None] = mapped_column(Float, nullable=True)
    female: Mapped[float | None] = mapped_column(Float, nullable=True)
    households: Mapped[float | None] = mapped_column(Float, nullable=True)
    housing: Mapped[float | None] = mapped_column(Float, nullable=True)
    businesses: Mapped[float | None] = mapped_column(Float, nullable=True)
    workers: Mapped[float | None] = mapped_column(Float, nullable=True)


# --------------------------------------------------------------------------- codes
def code500_for(x: float, y: float) -> str | None:
    """SGIS 500m code of the cell containing EPSG:5179 point (x, y): 1km code with a/b halves (a = lower/left)."""
    ix, iy = int((x - X0) // 100000), int((y - Y0) // 100000)
    if not (0 <= ix < len(BLOCKS) and 0 <= iy < len(BLOCKS)):
        return None
    rx, ry = x - X0 - ix * 100000, y - Y0 - iy * 100000
    return f"{BLOCKS[ix]}{BLOCKS[iy]}{int(rx // 1000):02d}{'a' if rx % 1000 < 500 else 'b'}{int(ry // 1000):02d}{'a' if ry % 1000 < 500 else 'b'}"


def code500_origin(code: str) -> tuple[int, int] | None:
    """Lower-left EPSG:5179 corner of a 500m code (None when the code is not a 500m code)."""
    if len(code) != 8 or code[0] not in BLOCKS or code[1] not in BLOCKS or not (code[2:4].isdigit() and code[5:7].isdigit()) \
            or code[4] not in "ab" or code[7] not in "ab":
        return None
    x = X0 + 100000 * BLOCKS.index(code[0]) + 1000 * int(code[2:4]) + (500 if code[4] == "b" else 0)
    y = Y0 + 100000 * BLOCKS.index(code[1]) + 1000 * int(code[5:7]) + (500 if code[7] == "b" else 0)
    return x, y


def project_code(grid_id: str) -> str | None:
    """Project cell 'cell_<x>_<y>' → its SGIS 500m code (same corners)."""
    try:
        _, x, y = grid_id.split("_")
        return code500_for(float(x), float(y))
    except (ValueError, AttributeError):
        return None


# --------------------------------------------------------------------------- files
def data_root() -> Path:
    from .settings import DATA_DIR
    return Path(DATA_DIR) / "raw" / "sgis_grid_500m"


def scan(root: Path) -> tuple[dict[int, list[Path]], list[str]]:
    """{year: [500M csv files]} and the file names that are not read (unknown year label, other sizes are ignored)."""
    years: dict[int, list[Path]] = {}
    ignored: list[str] = []
    for path in sorted(root.rglob("*_500M.csv")) if root.exists() else []:
        match = FILE_RE.match(path.name)
        if not match:
            ignored.append(path.name)
            continue
        year = int(match.group(1))
        if not 1990 <= year <= 2100:
            ignored.append(path.name)
            continue
        years.setdefault(year, []).append(path)
    return years, ignored


THEMES = ("인구", "가구", "주택", "사업체", "종사자")
FIRST_FULL_YEAR = 2015  # 2000·2005·2010 500m 격자는 인구만 제공된다


def missing_files(root: Path) -> list[dict[str, Any]]:
    """(year, theme, block) 500M files missing among the blocks that year has at all (2015~: all five themes).

    Grouped as [{"theme", "block", "years": [...]}] so a re-request can name exactly what is missing."""
    found: dict[int, set[tuple[str, str]]] = {}
    for path in sorted(root.rglob("*_500M.csv")) if root.exists() else []:
        match = FILE_RE.match(path.name)
        if match and 1990 <= int(match.group(1)) <= 2100:
            found.setdefault(int(match.group(1)), set()).add((match.group(2), match.group(3)))
    gaps: dict[tuple[str, str], list[int]] = {}
    for year, have in sorted(found.items()):
        blocks = {block for _, block in have}
        themes = THEMES if year >= FIRST_FULL_YEAR else ("인구",)
        for theme in themes:
            for block in sorted(blocks):
                if (theme, block) not in have:
                    gaps.setdefault((theme, block), []).append(year)
    return [{"theme": theme, "block": block, "years": years} for (theme, block), years in sorted(gaps.items(), key=lambda kv: (THEMES.index(kv[0][0]), kv[0][1]))]


def missing_text(gaps: list[dict[str, Any]]) -> str:
    def span(years: list[int]) -> str:
        return f"{years[0]}~{years[-1]}년" if len(years) > 1 and years[-1] - years[0] + 1 == len(years) else ", ".join(f"{y}년" for y in years)
    return "; ".join(f"{g['theme']} {g['block']} 블록 {span(g['years'])}" for g in gaps)


def read_rows(path: Path) -> Iterable[tuple[int, str, str, float]]:
    """(year, grid code, item, value) of one file. 'N/A' or blank values are left out (no published value)."""
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp949")
    for line in text.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4 or not parts[0].isdigit():
            continue
        try:
            value = float(parts[3])
        except ValueError:
            continue
        yield int(parts[0]), parts[1], parts[2], value


def pivot(files: list[Path], year: int) -> tuple[dict[str, dict[str, float]], dict[str, int]]:
    """{grid code: {column: value}} for one year, with counts of rows skipped (other year, bad code, other item)."""
    cells: dict[str, dict[str, float]] = {}
    skipped = {"other_year": 0, "bad_code": 0, "other_item": 0}
    for path in files:
        for row_year, code, item, value in read_rows(path):
            if row_year != year:
                skipped["other_year"] += 1
                continue
            column = ITEMS.get(item)
            if column is None:
                skipped["other_item"] += 1
                continue
            if code500_origin(code) is None:
                skipped["bad_code"] += 1
                continue
            cells.setdefault(code, {})[column] = value
    return cells, skipped


def _signature(files: list[Path]) -> list[list[Any]]:
    return sorted([p.name, p.stat().st_size] for p in files)


# --------------------------------------------------------------------------- import
LOCK_KEY = 5_000_500  # pg advisory lock: the API start-up import and a CLI run never load the same year at once


@contextmanager
def _import_lock(db: Any):
    bind = db.get_bind()
    if bind.dialect.name != "postgresql":
        yield
        return
    with bind.connect() as connection:
        connection.execute(text("SELECT pg_advisory_lock(:k)"), {"k": LOCK_KEY})
        try:
            yield
        finally:
            connection.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
            connection.commit()


def import_sgis_grid500(db: Any, root: str | Path | None = None, force: bool = False, log: Any = print) -> dict[str, Any]:
    """Load every year found under DATA_DIR/raw/sgis_grid_500m. A year whose files did not change is skipped."""
    base = Path(root) if root else data_root()
    years, ignored = scan(base)
    if not years:
        raise FileNotFoundError(f"500m 격자 통계 파일(<연도>년_<주제>_<블록>_500M.csv)이 없습니다: {base}")
    with _import_lock(db):
        return _import(db, base, years, ignored, force, log)


def _import(db: Any, base: Path, years: dict[int, list[Path]], ignored: list[str], force: bool, log: Any) -> dict[str, Any]:
    from .collectors import update_source
    state_path = base / ".imported.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    result: dict[str, Any] = {"years": [], "skipped": [], "ignored_files": sorted(set(ignored))[:20], "ignored_count": len(ignored), "rows": {}, "problems": {}}
    for year in sorted(years):
        files = years[year]
        signature = _signature(files)
        have = db.scalar(select(func.count()).select_from(SgisGrid500Value).where(SgisGrid500Value.year == year)) or 0
        if not force and have and state.get(str(year), {}).get("signature") == signature and state[str(year)].get("rows") == have:
            result["skipped"].append(year)
            continue
        cells, skipped = pivot(files, year)
        db.execute(delete(SgisGrid500Value).where(SgisGrid500Value.year == year))
        rows = _load(db, year, cells)
        db.commit()
        state[str(year)] = {"signature": signature, "rows": rows}
        result["years"].append(year)
        result["rows"][year] = rows
        if any(skipped.values()):
            result["problems"][year] = skipped
        log(f"{year}년 500m 격자 {rows:,}개 ({len(files)}개 파일)")
    try:
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass
    _CACHE.clear()
    summary = coverage(db)
    _source(db)
    update_source(db, SOURCE_ID, summary["rows"], raw_count=summary["rows"], status="COLLECTED",
                  quality=f"{summary['first_year']}~{summary['last_year']}년 {len(summary['years'])}개 연도, 최근 연도 500m 격자 {summary['last_cells']:,}개 · "
                          "총괄 항목(인구·가구·주택·사업체·종사자). 비밀보호: 인구 5 미만 0/5, 사업체 3 미만 0/3 대체, ±7(±4) 잡음")
    source = _source(db)
    gaps = missing_files(base)
    source.reference_period = f"{summary['first_year']}~{summary['last_year']}년"
    source.geographic_coverage = f"받은 파일의 100km 블록 {len({p.name.split('_')[2] for files in years.values() for p in files})}개"
    source.missing_count = sum(len(g["years"]) for g in gaps)
    if gaps:
        source.quality = f"{source.quality} · 빠진 파일: {missing_text(gaps)}"[:1000]
    db.commit()
    result["missing_files"] = gaps
    result["coverage"] = summary
    return result


def _load(db: Any, year: int, cells: dict[str, dict[str, float]]) -> int:
    columns = ("id", "year", "grid_cd", *VALUE_COLUMNS)
    rows = ((f"{year}:{code}", year, code, *(values.get(c) for c in VALUE_COLUMNS)) for code, values in sorted(cells.items()))
    from .sgis_grid import _copy_rows
    copied = _copy_rows(db, "sgis_grid500_values", columns, rows)
    if copied is not None:
        return copied
    batch = [dict(zip(columns, (f"{year}:{code}", year, code, *(values.get(c) for c in VALUE_COLUMNS)))) for code, values in sorted(cells.items())]
    for start in range(0, len(batch), 5000):
        db.execute(insert(SgisGrid500Value), batch[start:start + 5000])
    return len(batch)


def _source(db: Any):
    from .models import DataSource
    source = db.get(DataSource, SOURCE_ID)
    if source is None:
        source = DataSource(id=SOURCE_ID, category="인구", name="SGIS 500m 격자 통계 (자료제공 신청)", organization="국가데이터처 / SGIS",
                            source_url="https://sgis.mods.go.kr/view/pss/dataProvdIntrcn", source_type="OFFICIAL", status="NOT_COLLECTED",
                            limitation="500m는 총괄 항목만 제공. 비밀보호 잡음(인구 ±7, 사업체 ±4)과 작은 값 대체(0/5, 0/3) 포함.")
        db.add(source)
        db.flush()
    return source


# --------------------------------------------------------------------------- readers
_CACHE: dict[Any, Any] = {}
COVERAGE_TTL = 300  # a CLI import in another process shows up here within 5 minutes


def coverage(db: Any) -> dict[str, Any]:
    """Years loaded, row counts and which themes each year has (cached until the next import)."""
    cached = _CACHE.get("coverage")
    if cached and time.monotonic() - cached[0] < COVERAGE_TTL:
        return cached[1]
    try:
        rows = db.execute(select(SgisGrid500Value.year, func.count(), func.count(SgisGrid500Value.population), func.count(SgisGrid500Value.households),
                                 func.count(SgisGrid500Value.housing), func.count(SgisGrid500Value.workers))
                          .group_by(SgisGrid500Value.year).order_by(SgisGrid500Value.year)).all()
    except Exception:  # noqa: BLE001 - table not created yet
        db.rollback()
        rows = []
    years = [{"year": y, "cells": n, "population": p, "households": h, "housing": ho, "workers": w} for y, n, p, h, ho, w in rows]
    summary = {"years": years, "rows": sum(y["cells"] for y in years), "first_year": years[0]["year"] if years else None,
               "last_year": years[-1]["year"] if years else None, "last_cells": years[-1]["cells"] if years else 0,
               "base_year": next((y["year"] for y in years if y["year"] >= 2015 and y["population"]), None), "source": SOURCE_TEXT}
    _CACHE["coverage"] = (time.monotonic(), summary)
    return summary


def latest_year(db: Any) -> int | None:
    return coverage(db)["last_year"]


def values_for(db: Any, codes: Iterable[str], year: int) -> dict[str, dict[str, float | None]]:
    """{500m code: {column: value}} of one year for the given codes."""
    wanted = sorted({c for c in codes if c})
    out: dict[str, dict[str, float | None]] = {}
    for start in range(0, len(wanted), 4000):
        for row in db.execute(select(SgisGrid500Value).where(SgisGrid500Value.year == year, SgisGrid500Value.grid_cd.in_(wanted[start:start + 4000]))).scalars():
            out[row.grid_cd] = {c: getattr(row, c) for c in VALUE_COLUMNS}
    return out


def change_pct(before: float | None, after: float | None) -> float | None:
    """Percent change, only when both years have at least MIN_BASE (small values are replaced or noisy)."""
    if before is None or after is None or before < MIN_BASE or after < MIN_BASE:
        return None
    return round((after - before) / before * 100, 1)


def small_flags(values: dict[str, float | None]) -> list[str]:
    return sorted(k for k, small in SMALL.items() if values.get(k) in small)


def grid500_properties(db: Any, grid_ids: Iterable[str]) -> dict[str, dict[str, Any]]:
    """Map properties of analysis cells from their own SGIS 500m cell (latest year, and the change since the base year)."""
    ids = list(grid_ids)
    info = coverage(db)
    year, base = info["last_year"], info["base_year"]
    if not year or not ids:
        return {}
    codes = {gid: project_code(gid) for gid in ids}
    key = ("props", year, base, info["rows"], hash(frozenset(ids)))
    if key in _CACHE:
        return _CACHE[key]
    now = values_for(db, codes.values(), year)
    then = values_for(db, codes.values(), base) if base and base != year else {}
    out: dict[str, dict[str, Any]] = {}
    for gid, code in codes.items():
        cell = now.get(code or "")
        if cell is None:
            out[gid] = {"sgis500_year": year, "sgis500_status": "NO_STAT"}
            continue
        prev = then.get(code or "") or {}
        out[gid] = {
            "sgis500_year": year, "sgis500_status": "OBSERVED",
            **{f"sgis500_{c}": cell.get(c) for c in ("population", "households", "housing", "businesses", "workers")},
            "sgis500_pop_density": cell["population"] * 4 if cell.get("population") is not None else None,
            "sgis500_base_year": base if base != year else None, "sgis500_base_population": prev.get("population"),
            "sgis500_pop_change_pct": change_pct(prev.get("population"), cell.get("population")),
            "sgis500_small": small_flags(cell),
        }
    if len(_CACHE) > 12:
        for k in [k for k in _CACHE if k != "coverage"][:6]:
            _CACHE.pop(k, None)
    _CACHE[key] = out
    return out


def series(db: Any, code: str) -> list[dict[str, Any]]:
    """Every loaded year of one 500m cell (years without a row are left out: no published value)."""
    rows = db.execute(select(SgisGrid500Value).where(SgisGrid500Value.grid_cd == code).order_by(SgisGrid500Value.year)).scalars()
    return [{"year": r.year, **{c: getattr(r, c) for c in VALUE_COLUMNS}} for r in rows]


router = APIRouter(prefix="/api/sgis-grid", tags=["sgis-grid"])


@router.get("/500m/meta")
def grid500_meta() -> dict[str, Any]:
    from .db import Session
    with Session() as db:
        return coverage(db)


@router.get("/500m/cell/{grid_id}")
def grid500_cell(grid_id: str) -> dict[str, Any]:
    """SGIS 500m values of one analysis cell for every loaded year."""
    from .db import Session
    code = project_code(grid_id) if grid_id.startswith("cell_") else (grid_id if code500_origin(grid_id) else None)
    if code is None:
        raise HTTPException(422, "분석 격자 id(cell_<x>_<y>) 또는 SGIS 500m 격자코드가 아닙니다")
    with Session() as db:
        info = coverage(db)
        return {"code": code, "years": [y["year"] for y in info["years"]], "series": series(db, code), "source": SOURCE_TEXT,
                "note": "인구 부문 5 미만은 0 또는 5, 사업체 부문 3 미만은 0 또는 3으로 대체, 그 이상은 최대 ±7(±4) 잡음. 행이 없는 해는 통계 없음(0 아님)."}
