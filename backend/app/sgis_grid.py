"""SGIS official grid statistics (공공데이터포털 '국가데이터처_SGIS 격자 통계 및 경계', 1km).

The public package covers 1km cells only (500m/100m need an SGIS application). Values carry
statistical-disclosure noise: in the population part values under 5 are replaced by 0 or 5 at
random and larger values have up to ±7 noise (business part: 3 and ±4). So:

* a cell value is shown as an official statistic "with noise", never as an exact count;
* 0 or 5 (business 0 or 3) means "small, possibly replaced";
* a cell without a row for an item has no published statistic (e.g. no residents) — shown as
  "통계 없음", not 0;
* totals come from the ``to_*`` items; sums of detailed items are not totals.

The project 500m cells nest exactly in the 1km cells (both aligned to EPSG:5179 multiples), so a
500m cell gets its parent 1km cell's *densities and shares* — never a divided count. For an area,
the observed value is the sum of the whole 1km cells it touches (wider than the area); an
area-proportional figure is offered separately and always labelled ESTIMATED.
Input: the Jeonju bundle made by scripts/sgis/extract_sgis_grid.py in DATA_DIR/raw/sgis_grid_1k/<year>/.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from sqlalchemy import Float, Integer, String, delete, func, insert, select
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base

BLOCKS = "가나다라마바사아"
X0, Y0 = 700000, 1300000
SOURCE_ID = "sgis_grid_1k"
MIN_BASE = 20  # shares from fewer units are too noisy to show

HOUSING_AGE_BANDS = (
    ("1979년 이전", ("ho_yr_001",)), ("1980년대", ("ho_yr_002",)), ("1990년대", ("ho_yr_003",)),
    ("2000년대", ("ho_yr_004", "ho_yr_005")),
    ("2010년대", tuple(f"ho_yr_{i:03d}" for i in range(6, 16))),
    ("2020년 이후", tuple(f"ho_yr_{i:03d}" for i in range(16, 21))),
)
HOUSING_TYPES = (("아파트", "ho_gb_003"), ("단독주택", "ho_gb_002"), ("다세대", "ho_gb_001"), ("연립주택", "ho_gb_004"),
                 ("영업용 건물 내 주택", "ho_gb_005"), ("주택 이외 거처", "ho_gb_006"))
HOUSEHOLD_TYPES = (("1인가구", ("ga_sd_005",)), ("1세대가구", ("ga_sd_001",)), ("2세대가구", ("ga_sd_002",)),
                   ("3세대 이상", ("ga_sd_003", "ga_sd_004")), ("비혈연가구", ("ga_sd_006",)))
HOUSING_AREA_BANDS = (("40㎡ 이하", ("ho_ar_001", "ho_ar_002")), ("40~60㎡", ("ho_ar_003",)), ("60~85㎡", ("ho_ar_004",)),
                      ("85~130㎡", ("ho_ar_005", "ho_ar_006")), ("130㎡ 초과", ("ho_ar_007", "ho_ar_008", "ho_ar_009")))
AGE_ALL = tuple(f"in_age_{i:03d}" for i in range(1, 22))
AGE_65 = tuple(f"in_age_{i:03d}" for i in range(14, 22))
AGE_14 = tuple(f"in_age_{i:03d}" for i in range(1, 4))
OLD_HOUSING = ("ho_yr_001", "ho_yr_002", "ho_yr_003")
ALL_HOUSING_YEARS = tuple(f"ho_yr_{i:03d}" for i in range(1, 21))
SECTOR_NAMES = ("농림어업", "광업", "제조업", "전기·가스·증기", "수도·하수·폐기물", "건설업", "도소매업", "운수·창고업",
                "숙박·음식점업", "정보통신업", "금융·보험업", "부동산업", "전문·과학·기술", "사업시설·지원·임대",
                "공공행정·국방", "교육서비스", "보건·사회복지", "예술·스포츠·여가", "협회·수리·개인서비스")  # KSIC 대분류 순서 (cp_bnu/cp_bem 001~019)


class SgisGridCell(Base):
    __tablename__ = "sgis_grid_cells"
    id: Mapped[str] = mapped_column(String, primary_key=True)  # "<year>:<grid_cd>"
    year: Mapped[int] = mapped_column(Integer, index=True)
    grid_cd: Mapped[str] = mapped_column(String, index=True)
    size_m: Mapped[int] = mapped_column(Integer)
    x_min: Mapped[float] = mapped_column(Float)
    y_min: Mapped[float] = mapped_column(Float)


class SgisGridStat(Base):
    __tablename__ = "sgis_grid_stats"
    id: Mapped[str] = mapped_column(String, primary_key=True)  # "<year>:<grid_cd>:<item>"
    year: Mapped[int] = mapped_column(Integer, index=True)
    grid_cd: Mapped[str] = mapped_column(String, index=True)
    item: Mapped[str] = mapped_column(String)
    value: Mapped[float] = mapped_column(Float)
    group: Mapped[str] = mapped_column("item_group", String)  # population, household, housing, business, worker, …


# --------------------------------------------------------------------------- grid codes
def code_for(x: float, y: float, size_m: int = 1000) -> str | None:
    """1km grid code (e.g. 다마6862) of the cell containing EPSG:5179 point (x, y)."""
    if size_m != 1000:
        raise ValueError("only 1km codes are supported")
    ix, iy = int((x - X0) // 100000), int((y - Y0) // 100000)
    if not (0 <= ix < len(BLOCKS) and 0 <= iy < len(BLOCKS)):
        return None
    return f"{BLOCKS[ix]}{BLOCKS[iy]}{int((x - X0 - ix * 100000) // 1000):02d}{int((y - Y0 - iy * 100000) // 1000):02d}"


def code_origin(code: str) -> tuple[int, int] | None:
    if len(code) != 6 or code[0] not in BLOCKS or code[1] not in BLOCKS or not code[2:].isdigit():
        return None
    return X0 + 100000 * BLOCKS.index(code[0]) + 1000 * int(code[2:4]), Y0 + 100000 * BLOCKS.index(code[1]) + 1000 * int(code[4:6])


def parent_code(grid_id: str) -> str | None:
    """Project cell id 'cell_<x>_<y>' (lower-left, EPSG:5179) → the 1km cell that contains it."""
    try:
        _, x, y = grid_id.split("_")
        return code_for(float(x), float(y))
    except (ValueError, AttributeError):
        return None


# --------------------------------------------------------------------------- import
def bundles(root: Path) -> list[Path]:
    return sorted(p for p in root.glob("*/manifest.json")) if root.exists() else []


def import_sgis_grid(db: Any, root: str | Path | None = None, force: bool = False) -> dict[str, Any]:
    """Load every DATA_DIR/raw/sgis_grid_1k/<year>/ bundle. Skips a year already loaded with the same row counts."""
    from .collectors import update_source
    from .settings import DATA_DIR
    base = Path(root) if root else DATA_DIR / "raw" / "sgis_grid_1k"
    result: dict[str, Any] = {"years": [], "skipped": []}
    for manifest_path in bundles(base):
        folder = manifest_path.parent
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        years = manifest.get("base_years") or []
        if len(years) != 1:
            raise ValueError(f"한 번들에는 기준연도 하나만 있어야 합니다: {folder}")
        year = int(years[0])
        have_cells = db.scalar(select(func.count()).select_from(SgisGridCell).where(SgisGridCell.year == year)) or 0
        have_stats = db.scalar(select(func.count()).select_from(SgisGridStat).where(SgisGridStat.year == year)) or 0
        if not force and have_cells == manifest.get("cells") and have_stats == manifest.get("stat_rows"):
            result["skipped"].append(year)
            continue
        db.execute(delete(SgisGridStat).where(SgisGridStat.year == year))
        db.execute(delete(SgisGridCell).where(SgisGridCell.year == year))
        cell_rows = []
        with (folder / "cells.csv").open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                code = row["grid_cd"]
                origin = code_origin(code)
                if origin is None or origin != (int(float(row["x_min"])), int(float(row["y_min"]))):
                    raise ValueError(f"격자코드와 좌표가 맞지 않습니다: {code}")
                cell_rows.append({"id": f"{year}:{code}", "year": year, "grid_cd": code, "size_m": int(row["size_m"]), "x_min": origin[0], "y_min": origin[1]})
        stat_rows = []
        with (folder / "stats.csv").open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if int(row["base_year"]) != year:
                    continue
                stat_rows.append({"id": f"{year}:{row['grid_cd']}:{row['item']}", "year": year, "grid_cd": row["grid_cd"], "item": row["item"],
                                  "value": float(row["value"]), "group": row["group"]})
        if cell_rows:
            db.execute(insert(SgisGridCell), cell_rows)
        for start in range(0, len(stat_rows), 5000):
            db.execute(insert(SgisGridStat), stat_rows[start:start + 5000])
        cells, stats = len(cell_rows), len(stat_rows)
        db.commit()
        _VALUES_CACHE.clear()
        update_source(db, SOURCE_ID, stats, raw_count=cells, status="COLLECTED",
                      quality=f"{year}년 1km 격자 {cells}개 · 통계값 {stats:,}행 (비밀보호 잡음 포함, 인구 부문 5 미만은 0/5 확률 대체)")
        source = _source(db)
        if source:
            source.reference_period = f"{year}년 (기준시점 6월 30일)"
            db.commit()
        result["years"].append(year)
    return result


def _source(db: Any):
    from .models import DataSource
    return db.get(DataSource, SOURCE_ID)


_VALUES_CACHE: dict[tuple[int, int], dict[str, dict[str, float]]] = {}


def latest_year(db: Any) -> int | None:
    try:
        return db.scalar(select(func.max(SgisGridStat.year)))
    except Exception:  # noqa: BLE001 - table not created yet
        db.rollback()
        return None


def grid_values(db: Any, year: int | None = None) -> tuple[int | None, dict[str, dict[str, float]]]:
    """{grid_cd: {item: value}} for one year (latest by default). Cached per (year, row count)."""
    year = year or latest_year(db)
    if not year:
        return None, {}
    count = db.scalar(select(func.count()).select_from(SgisGridStat).where(SgisGridStat.year == year)) or 0
    key = (year, count)
    if key not in _VALUES_CACHE:
        values: dict[str, dict[str, float]] = {}
        for code, item, value in db.execute(select(SgisGridStat.grid_cd, SgisGridStat.item, SgisGridStat.value).where(SgisGridStat.year == year)):
            values.setdefault(code, {})[item] = value
        _VALUES_CACHE.clear()
        _VALUES_CACHE[key] = values
    return year, _VALUES_CACHE[key]


# --------------------------------------------------------------------------- summaries
def _sum(values: dict[str, float], items: tuple[str, ...]) -> float | None:
    present = [values[i] for i in items if i in values]
    return float(sum(present)) if present else None


def _share(part: float | None, whole: float | None) -> float | None:
    if part is None or whole is None or whole < MIN_BASE:
        return None
    return round(part / whole * 100, 1)


def cell_summary(values: dict[str, float]) -> dict[str, Any]:
    """Totals, densities (per km²) and shares for one 1km cell (or a sum of cells)."""
    pop = values.get("to_in_001")
    households = values.get("to_ga_001")
    housing = values.get("to_ho_001")
    housing_years = _sum(values, ALL_HOUSING_YEARS)
    ages = _sum(values, AGE_ALL)
    housing_types = _sum(values, tuple(code for _, code in HOUSING_TYPES))
    return {
        "population": pop, "male": values.get("to_in_007"), "female": values.get("to_in_008"),
        "households": households, "housing": housing,
        "businesses": values.get("to_fa_010"), "workers": values.get("to_em_020"),
        "elderly_pct": _share(_sum(values, AGE_65), ages),
        "children_pct": _share(_sum(values, AGE_14), ages),
        "single_household_pct": _share(values.get("ga_sd_005"), households),
        "old_housing_pct": _share(_sum(values, OLD_HOUSING), housing_years),
        "apartment_pct": _share(values.get("ho_gb_003"), housing_types),
        # Distributions keep None for items without a published value (not 0).
        "housing_age": {label: _sum(values, codes) for label, codes in HOUSING_AGE_BANDS},
        "housing_types": {label: values.get(code) for label, code in HOUSING_TYPES},
        "housing_area": {label: _sum(values, codes) for label, codes in HOUSING_AREA_BANDS},
        "household_types": {label: _sum(values, codes) for label, codes in HOUSEHOLD_TYPES},
        "sectors": sorted(
            ({"name": name, "businesses": values.get(f"cp_bnu_{i:03d}"), "workers": values.get(f"cp_bem_{i:03d}")}
             for i, name in enumerate(SECTOR_NAMES, start=1) if f"cp_bnu_{i:03d}" in values or f"cp_bem_{i:03d}" in values),
            key=lambda row: -(row["workers"] or 0)),
        "small_flags": sorted(k for k in ("to_in_001", "to_ga_001", "to_ho_001") if values.get(k) in (0.0, 5.0)),
    }


def add_values(cells: list[dict[str, float]]) -> dict[str, float]:
    total: dict[str, float] = {}
    for values in cells:
        for item, value in values.items():
            total[item] = total.get(item, 0.0) + value
    return total


def grid_metric_properties(db: Any) -> dict[str, dict[str, Any]]:
    """Map properties for every project 500m cell from its parent 1km cell (densities and shares only)."""
    from .models import Grid
    year, values = grid_values(db)
    if not year:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for grid_id in db.scalars(select(Grid.id)):
        code = parent_code(grid_id)
        cell = values.get(code or "")
        if cell is None:
            out[grid_id] = {"sgis1k_code": code, "sgis1k_year": year, "sgis1k_status": "NO_STAT"}
            continue
        s = cell_summary(cell)
        out[grid_id] = {
            "sgis1k_code": code, "sgis1k_year": year, "sgis1k_status": "OBSERVED",
            "sgis1k_population": s["population"], "sgis1k_households": s["households"], "sgis1k_housing": s["housing"],
            "sgis1k_businesses": s["businesses"], "sgis1k_workers": s["workers"],
            # 1km cell = 1 km², so the count is also the density per km²
            "sgis_pop_density": s["population"], "sgis_housing_density": s["housing"], "sgis_worker_density": s["workers"],
            "sgis_elderly_pct": s["elderly_pct"], "sgis_single_household_pct": s["single_household_pct"],
            "sgis_old_housing_pct": s["old_housing_pct"], "sgis_apartment_pct": s["apartment_pct"],
            "sgis1k_small": s["small_flags"],
        }
    return out


def grid_context_block(db: Any, grid_id: str) -> dict[str, Any] | None:
    year, values = grid_values(db)
    if not year:
        return None
    code = parent_code(grid_id)
    cell = values.get(code or "")
    if cell is None:
        return {"year": year, "code": code, "status": "NO_STAT", "source": "SGIS 격자 통계 1km (공공데이터포털)"}
    return {"year": year, "code": code, "status": "OBSERVED", "source": "SGIS 격자 통계 1km (공공데이터포털)", **cell_summary(cell)}


def area_block(grid_ids: list[str], year: int | None, values: dict[str, dict[str, float]]) -> dict[str, Any] | None:
    """SGIS 1km cells overlapping an area (by its 500m member cells).

    ``overlap`` sums the whole 1km cells (observed values, wider than the area);
    ``estimated`` scales each cell by the share of its four 500m children inside the area (ESTIMATED).
    """
    if not year or not values:
        return None
    children: dict[str, int] = {}
    for grid_id in grid_ids:
        code = parent_code(grid_id)
        if code:
            children[code] = children.get(code, 0) + 1
    with_stats = [code for code in children if code in values]
    overlap = add_values([values[c] for c in with_stats])
    estimated_pop = round(sum(values[c].get("to_in_001", 0.0) * children[c] / 4 for c in with_stats)) if with_stats else None
    estimated_households = round(sum(values[c].get("to_ga_001", 0.0) * children[c] / 4 for c in with_stats)) if with_stats else None
    return {
        "year": year, "cells": len(children), "cells_with_stats": len(with_stats),
        "coverage_pct": round(len(grid_ids) * 0.25 / max(1, len(children)) * 100, 1) if children else None,
        "overlap": cell_summary(overlap) if with_stats else None,
        "estimated": {"population": estimated_pop, "households": estimated_households, "data_class": "ESTIMATED",
                      "basis": "1km 격자 값 × (구역에 든 500m 격자 수 ÷ 4)"},
        "source": "SGIS 격자 통계 1km (공공데이터포털), 비밀보호 잡음 포함",
    }


def context_fact(block: dict[str, Any] | None) -> dict[str, str] | None:
    if not block:
        return None
    if block.get("status") != "OBSERVED":
        return {"id": "context_sgis_grid", "text": f"대상 격자가 속한 SGIS 1km 격자({block.get('code')})에는 {block['year']}년 통계가 없습니다(인구·사업체가 없는 격자일 수 있음)."}
    parts = [f"인구 {block['population']:,.0f}명" if block.get("population") is not None else None,
             f"가구 {block['households']:,.0f}" if block.get("households") is not None else None,
             f"주택 {block['housing']:,.0f}호" if block.get("housing") is not None else None,
             f"2000년 이전 준공 주택 {block['old_housing_pct']:.1f}%" if block.get("old_housing_pct") is not None else None]
    text = ", ".join(p for p in parts if p)
    return {"id": "context_sgis_grid", "text": f"대상 격자가 속한 SGIS {block['year']}년 1km 격자({block['code']})는 {text}입니다. 공식 격자 통계이며 비밀보호 잡음(±7)이 들어 있고, 500m 격자 값으로 나누지 않았습니다."}


def meta(db: Any) -> dict[str, Any]:
    from .settings import DATA_DIR
    year = latest_year(db)
    cells = db.scalar(select(func.count()).select_from(SgisGridCell).where(SgisGridCell.year == year)) if year else 0
    stats = db.scalar(select(func.count()).select_from(SgisGridStat).where(SgisGridStat.year == year)) if year else 0
    manifests = [json.loads(p.read_text(encoding="utf-8")) for p in bundles(DATA_DIR / "raw" / "sgis_grid_1k")]
    return {"year": year, "cells": cells, "stat_rows": stats, "grid_size_m": 1000,
            "bundles": [{k: m.get(k) for k in ("dataset", "base_years", "cells", "stat_rows", "created_at")} for m in manifests],
            "rules": manifests[-1].get("rules", []) if manifests else []}


router = APIRouter(prefix="/api/sgis-grid", tags=["sgis-grid"])


@router.get("/meta")
def sgis_grid_meta() -> dict[str, Any]:
    from .db import Session
    with Session() as db:
        return meta(db)
