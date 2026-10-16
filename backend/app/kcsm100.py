"""선도소프트가 보낸 탄소공간지도 100m 건물 전기 배출(2026-10-17 받음)을 이 도구에 붙인다.

받은 묶음: ``1. 배출_건물_전기_격자_100m/속성정보(csv)/탄소배출_건물_전기_격자_100m_<시도>_<시군구>_<구>_<연도>.csv``
(같은 이름의 SHP와 데이터정의서 xlsx가 함께 옴). 전주 덕진구·완산구, 2023·2024년. 원본은
``DATA_DIR/raw/sundosoft_kcsm100/<받은 날>/``에 그대로 두고 ``python -m app.cli import-kcsm100``으로 넣는다.

원본에서 확인한 것 (2026-10-17):

* 행 = (100m 격자, 법정동) 한 쌍. 법정동 경계에 걸친 칸은 법정동마다 한 행씩 있어 칸 값은 그 행들의 합이다.
* ``grid_cd``는 국가기본격자 100m 코드(``다마555632``)이고 SHP 도형(EPSG:3857)은 그 코드의 EPSG:5179 칸과 같다.
* 열은 ``e1``~``e12``(월), ``e_sum``(연). 데이터정의서는 ``e_01``~``e_12``·``e_tot``라고 적어 이름이 다르다(둘 다 읽음).
  ``emd_cd``(법정동 8자리)는 정의서에 없다. 단위는 정의서대로 tonCO2-eq.
* 빈 값은 없고 0이 많다(행의 약 70%). 0이 '건물 없음'인지 '사용량 미연계'인지는 제공기관 확인이 필요하다.

규칙 (DATA_STANDARD 4·5.12절):

* 제공 값은 고치지 않는다. 0은 0(제공값)으로 두고 화면에 '0 (확인 필요)'로 적는다.
* 앞 자료 연도에 100 tCO2eq 이상이던 칸이 다음 해에 절반 미만이면 '급감(원자료 누락 의심)'으로 표시만 한다.
* 이 도구의 계산값(건축HUB 계측 kWh × 승인 계수)과 더하지 않고 같은 범위끼리 맞대기만 한다.
* 이용 조건(외부 공개·재배포)을 아직 받지 않았다: 공개 시연 주소(게이트웨이)에서는 빼고, Git에 올리지 않는다.
"""
from __future__ import annotations

import csv
import hashlib
import io
import math
import os
import re
from pathlib import Path
from typing import Any, Callable, Iterable

from sqlalchemy import JSON, Float, Integer, String, delete, func, insert, select, update
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base

SOURCE = "탄소공간지도 100m 건물 전기 배출 (선도소프트 제공, 2026-10-17 받음)"
SOURCE_SHORT = "탄소공간지도 100m (선도소프트)"
UNIT = "tCO2eq"
BLOCKS = "가나다라마바사아"
X0, Y0 = 700000, 1300000
FILE_RE = re.compile(r"탄소배출_건물_전기_격자_100m_(.+)_(\d{4})\.csv$")
DROP_BASE_T = 100.0   # 팀 기준: 앞 해 100 tCO2eq 이상인 칸만 급감을 본다
DROP_RATIO = 0.5      # 앞 해의 50% 미만이면 급감
LIMIT = 12000
RESTRICTED_TEXT = ("선도소프트가 준 탄소공간지도 100m 자료는 이용 조건(외부 공개·재배포)을 확인하기 전이라 "
                   "공개 시연 주소에서 제공하지 않습니다. 이 PC의 화면에서만 볼 수 있습니다.")


class KcsmGrid100(Base):
    __tablename__ = "kcsm_grid100"
    id: Mapped[str] = mapped_column(String, primary_key=True)  # "<grid100>|<year>"
    region_code: Mapped[str] = mapped_column(String, index=True)
    grid_code: Mapped[str] = mapped_column(String)
    x: Mapped[int] = mapped_column(Integer)
    y: Mapped[int] = mapped_column(Integer)
    grid500: Mapped[str] = mapped_column(String, index=True)   # 이 도구의 500m 칸 cell_<x>_<y>
    year: Mapped[int] = mapped_column(Integer, index=True)
    annual_t: Mapped[float | None] = mapped_column(Float, nullable=True)
    monthly: Mapped[list] = mapped_column(JSON, default=list)   # 1~12월 tCO2eq (없는 달 None)
    parts: Mapped[list] = mapped_column(JSON, default=list)     # [{"emd": 법정동 8자리, "t": 연 tCO2eq}]
    flags: Mapped[dict] = mapped_column(JSON, default=dict)     # {"drop": {"from_year", "from_t"}}
    source_file: Mapped[str] = mapped_column(String)


class KcsmImport(Base):
    __tablename__ = "kcsm_imports"
    path: Mapped[str] = mapped_column(String, primary_key=True)
    sha256: Mapped[str] = mapped_column(String)
    rows: Mapped[int] = mapped_column(Integer, default=0)


# --------------------------------------------------------------------------- parsing (pure)
def grid100_origin(code: str) -> tuple[int, int] | None:
    """'다마555632' → (955500, 1763200): 100km 블록 두 글자 + x 3자리 + y 3자리(100m 단위), EPSG:5179 왼쪽 아래."""
    code = (code or "").strip()
    if len(code) != 8 or code[0] not in BLOCKS or code[1] not in BLOCKS or not code[2:].isdigit():
        return None
    return X0 + 100000 * BLOCKS.index(code[0]) + 100 * int(code[2:5]), Y0 + 100000 * BLOCKS.index(code[1]) + 100 * int(code[5:8])


def num(value: Any) -> float | None:
    s = str(value if value is not None else "").strip()
    if not s or s.lower() in ("nan", "none", "null"):
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def region_of(emd_code: str) -> str | None:
    """법정동 8자리(52113137) → 이 도구의 시·군·구 코드: 일반구는 그 시(52113 → 52110), 자치구·군은 그대로."""
    digits = re.sub(r"\D", "", emd_code or "")
    return digits[:4] + "0" if len(digits) >= 5 else None


def month_value(row: dict[str, str], m: int) -> float | None:
    for key in (f"e{m}", f"e_{m:02d}", f"e{m:02d}"):
        if key in row:
            return num(row[key])
    return None


def total_value(row: dict[str, str]) -> float | None:
    for key in ("e_sum", "e_tot", "e_total"):
        if key in row:
            return num(row[key])
    return None


def read_csv_text(raw: bytes) -> list[dict[str, str]]:
    """Provider CSVs come in CP949; UTF-8 (with or without BOM) is read too."""
    for enc in ("utf-8-sig", "cp949"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError("CSV 인코딩을 읽지 못했습니다 (CP949·UTF-8 아님)")
    return [{(k or "").strip(): (v or "") for k, v in r.items()} for r in csv.DictReader(io.StringIO(text))]


def aggregate(rows: Iterable[dict[str, str]], year: int, source_file: str) -> tuple[dict[str, dict[str, Any]], dict[str, int]]:
    """(격자, 법정동) 행 → 칸 하나. 칸 값 = 법정동 행의 합. 연 합계와 월 합이 다르면 세어 둔다(값은 고치지 않음)."""
    cells: dict[str, dict[str, Any]] = {}
    stats = {"rows": 0, "bad_code": 0, "sum_mismatch": 0}
    for r in rows:
        stats["rows"] += 1
        code = (r.get("grid_cd") or "").strip()
        origin = grid100_origin(code)
        emd = (r.get("emd_cd") or "").strip()
        if origin is None:
            stats["bad_code"] += 1
            continue
        months = [month_value(r, m) for m in range(1, 13)]
        total = total_value(r)
        known = [v for v in months if v is not None]
        if total is None and len(known) == 12:
            total = sum(known)
        if total is not None and len(known) == 12 and abs(sum(known) - total) > 0.02:
            stats["sum_mismatch"] += 1
        x, y = origin
        cell = cells.setdefault(code, {
            "id": f"{code}|{year}", "region_code": region_of(emd) or "", "grid_code": code, "x": x, "y": y,
            "grid500": f"cell_{x // 500 * 500}_{y // 500 * 500}", "year": year, "annual_t": None,
            "monthly": [None] * 12, "parts": [], "flags": {}, "source_file": source_file})
        if total is not None:
            cell["annual_t"] = round((cell["annual_t"] or 0.0) + total, 6)
        for i, v in enumerate(months):
            if v is not None:
                cell["monthly"][i] = round((cell["monthly"][i] or 0.0) + v, 6)
        cell["parts"].append({"emd": emd, "t": total})
    return cells, stats


def drop_flag(prev_t: float | None, now_t: float | None, prev_year: int) -> dict[str, Any] | None:
    """급감(원자료 누락 의심): 앞 자료 연도 ≥ 100 tCO2eq이고 이번 해가 그 50% 미만(0 포함)."""
    if prev_t is None or now_t is None or prev_t < DROP_BASE_T or now_t >= prev_t * DROP_RATIO:
        return None
    return {"from_year": prev_year, "from_t": round(prev_t, 2)}


# --------------------------------------------------------------------------- import
def kcsm_root() -> Path:
    return Path(os.getenv("DATA_DIR", "data")) / "raw" / "sundosoft_kcsm100"


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def source_files(root: Path) -> dict[int, list[Path]]:
    """CSV files by year (the newest copy of the same file name wins when several deliveries are kept)."""
    found: dict[str, Path] = {}
    for path in sorted(root.rglob("*.csv")):
        if FILE_RE.search(path.name):
            found[path.name] = path
    out: dict[int, list[Path]] = {}
    for name, path in sorted(found.items()):
        out.setdefault(int(FILE_RE.search(name).group(2)), []).append(path)
    return out


def create_tables(db: Any) -> None:
    for model in (KcsmGrid100, KcsmImport):
        model.__table__.create(db.get_bind(), checkfirst=True)


def import_kcsm100(db: Any, root: Path | None = None, force: bool = False, log: Callable[[str], Any] = print) -> dict[str, Any]:
    """Every year whose files changed is rewritten whole (cells of one year come from both 구 files)."""
    root = root or kcsm_root()
    create_tables(db)
    stats: dict[str, Any] = {"years": [], "cells": 0, "rows": 0, "bad_code": 0, "sum_mismatch": 0, "skipped_years": [], "files": 0}
    by_year = source_files(root)
    for year, paths in sorted(by_year.items()):
        rels = [str(p.relative_to(root)) for p in paths]
        shas = [_sha(p) for p in paths]
        done = [db.get(KcsmImport, rel) for rel in rels]
        if not force and all(d is not None and d.sha256 == s for d, s in zip(done, shas)):
            stats["skipped_years"].append(year)
            continue
        cells: dict[str, dict[str, Any]] = {}
        for path, rel in zip(paths, rels):
            part, s = aggregate(read_csv_text(path.read_bytes()), year, rel)
            for code, cell in part.items():
                if code in cells:  # the same cell in both 구 files: add the 법정동 parts
                    merged = cells[code]
                    if cell["annual_t"] is not None:
                        merged["annual_t"] = round((merged["annual_t"] or 0.0) + cell["annual_t"], 6)
                    merged["monthly"] = [None if a is None and b is None else round((a or 0.0) + (b or 0.0), 6)
                                         for a, b in zip(merged["monthly"], cell["monthly"])]
                    merged["parts"] += cell["parts"]
                    merged["source_file"] = ";".join(sorted({*merged["source_file"].split(";"), rel}))
                else:
                    cells[code] = cell
            for k in ("rows", "bad_code", "sum_mismatch"):
                stats[k] += s[k]
            stats["files"] += 1
        regions = {c["region_code"] for c in cells.values()}
        db.execute(delete(KcsmGrid100).where(KcsmGrid100.year == year, KcsmGrid100.region_code.in_(regions)))
        rows = list(cells.values())
        for start in range(0, len(rows), 5000):
            db.execute(insert(KcsmGrid100), rows[start:start + 5000])
        for d, rel, sha in zip(done, rels, shas):
            if d:
                d.sha256, d.rows = sha, len(rows)
            else:
                db.add(KcsmImport(path=rel, sha256=sha, rows=len(rows)))
        db.commit()
        stats["years"].append(year)
        stats["cells"] += len(rows)
        log(f"{year}: {len(paths)} files, {len(rows)} cells")
    if stats["years"]:
        stats["flagged"] = refresh_flags(db)
    _CELLS.clear()
    return stats


def refresh_flags(db: Any) -> int:
    """Recompute 급감 flags between consecutive data years of each region (values are never changed)."""
    rows = db.execute(select(KcsmGrid100.id, KcsmGrid100.region_code, KcsmGrid100.grid_code, KcsmGrid100.year, KcsmGrid100.annual_t)).all()
    by_cell: dict[tuple[str, str], dict[int, tuple[str, float | None]]] = {}
    years_of: dict[str, set[int]] = {}
    for rid, region, code, year, value in rows:
        by_cell.setdefault((region, code), {})[year] = (rid, value)
        years_of.setdefault(region, set()).add(year)
    updates = []
    for (region, _), years in by_cell.items():
        ordered = sorted(years_of[region])
        for i, year in enumerate(ordered):
            if year not in years:
                continue
            flags: dict[str, Any] = {}
            if i > 0 and ordered[i - 1] in years:
                drop = drop_flag(years[ordered[i - 1]][1], years[year][1], ordered[i - 1])
                if drop:
                    flags["drop"] = drop
            updates.append({"rid": years[year][0], "flags": flags})
    from sqlalchemy import bindparam
    stmt = update(KcsmGrid100).where(KcsmGrid100.id == bindparam("rid")).values(flags=bindparam("flags"))
    for start in range(0, len(updates), 5000):
        db.connection().execute(stmt, updates[start:start + 5000])
    db.commit()
    return sum(1 for u in updates if u["flags"])


def counts(db: Any) -> dict[str, Any]:
    try:
        rows = db.execute(select(KcsmGrid100.region_code, KcsmGrid100.year, func.count(), func.sum(KcsmGrid100.annual_t))
                          .group_by(KcsmGrid100.region_code, KcsmGrid100.year)).all()
    except Exception:  # noqa: BLE001 - table missing
        db.rollback()
        return {}
    return {f"{r}:{y}": {"cells": int(n)} for r, y, n, _ in rows}


# --------------------------------------------------------------------------- readers
_CELLS: dict[tuple[str, int], tuple[int, list[tuple[Any, ...]], list[tuple[float, float]] | None]] = {}


def years(db: Any, region_code: str | None) -> list[int]:
    if not region_code:
        return []
    try:
        return sorted(int(y) for (y,) in db.execute(select(KcsmGrid100.year).where(KcsmGrid100.region_code == region_code).distinct()))
    except Exception:  # noqa: BLE001 - never imported
        db.rollback()
        return []


def cells(db: Any, region_code: str, year: int) -> list[tuple[Any, ...]]:
    """(grid_code, x, y, grid500, annual_t, monthly, flags) of a region-year, cached and checked against the row count."""
    count = db.scalar(select(func.count()).select_from(KcsmGrid100).where(KcsmGrid100.region_code == region_code, KcsmGrid100.year == year)) or 0
    hit = _CELLS.get((region_code, year))
    if hit is None or hit[0] != count:
        rows = list(db.execute(select(KcsmGrid100.grid_code, KcsmGrid100.x, KcsmGrid100.y, KcsmGrid100.grid500, KcsmGrid100.annual_t,
                                      KcsmGrid100.monthly, KcsmGrid100.flags)
                               .where(KcsmGrid100.region_code == region_code, KcsmGrid100.year == year)
                               .order_by(KcsmGrid100.y, KcsmGrid100.x)).tuples())
        if len(_CELLS) >= 8:
            _CELLS.pop(next(iter(_CELLS)))
        _CELLS[(region_code, year)] = hit = (count, rows, None)
    return hit[1]


def centers(region_code: str, year: int) -> list[tuple[float, float]]:
    """lon/lat of each cell center, in the order of ``cells`` (computed once per cached region-year)."""
    count, rows, done = _CELLS[(region_code, year)]
    if done is None:
        from pyproj import Transformer
        to_ll = Transformer.from_crs(5179, 4326, always_xy=True).transform
        lon, lat = to_ll([r[1] + 50 for r in rows], [r[2] + 50 for r in rows]) if rows else ([], [])
        done = list(zip(lon, lat))
        _CELLS[(region_code, year)] = (count, rows, done)
    return done


def status_of(value: float | None) -> str:
    return "missing" if value is None else "zero" if value == 0 else "value"


def meta(db: Any, region_code: str | None, year: int) -> dict[str, Any]:
    out: dict[str, Any] = {"source": SOURCE, "unit": UNIT, "years": years(db, region_code), "year": None, "cells": 0, "returned": 0,
                           "truncated": False, "reason": None}
    if not out["years"]:
        out["reason"] = "이 지역에는 선도소프트 탄소공간지도 100m 자료가 없습니다(전주시 2023·2024년만 받음)."
        return out
    from .team_grid import year_for
    chosen = year_for(out["years"], year)
    if chosen is None:
        out["reason"] = f"{year}년 이전의 100m 전력 배출 자료가 없습니다. 가장 이른 자료는 {out['years'][0]}년입니다."
        return out
    out["year"] = chosen
    out["cells"] = len(cells(db, region_code, chosen))
    return out


def features(db: Any, region_code: str | None, year: int, bbox: tuple[float, float, float, float] | None = None,
             grid500: str | None = None, limit: int = LIMIT, meta_only: bool = False) -> dict[str, Any]:
    """100m cells for the map (viewport ``bbox`` in lon/lat, or one 500m cell). Callers refuse the public gateway."""
    m = meta(db, region_code, year)
    empty = {"type": "FeatureCollection", "features": [], "meta": m, "summary": None}
    if m["year"] is None or meta_only:
        return empty
    rows = cells(db, region_code, m["year"])
    prev_year = max((y for y in m["years"] if y < m["year"]), default=None)
    prev = {r[0]: r[4] for r in cells(db, region_code, prev_year)} if prev_year else {}
    if grid500:
        match = re.fullmatch(r"cell_(\d+)_(\d+)", grid500)
        if not match:
            m["reason"] = "격자 이름이 올바르지 않습니다."
            return empty
        picked = [r for r in rows if r[3] == grid500]
    elif bbox:
        from pyproj import Transformer
        to_tm = Transformer.from_crs(4326, 5179, always_xy=True).transform
        w, s, e, n = bbox
        xs, ys = to_tm([w, e, w, e], [s, s, n, n])
        x0, x1, y0, y1 = min(xs) - 100, max(xs), min(ys) - 100, max(ys)
        picked = [r for r in rows if x0 <= r[1] <= x1 and y0 <= r[2] <= y1]
    else:
        picked = list(rows)
    if len(picked) > limit:
        m["truncated"] = True
        picked = picked[:limit]
    m["returned"] = len(picked)
    from pyproj import Transformer
    to_ll = Transformer.from_crs(5179, 4326, always_xy=True).transform
    xs = [v for r in picked for v in (r[1], r[1] + 100, r[1] + 100, r[1])]
    ys = [v for r in picked for v in (r[2], r[2], r[2] + 100, r[2] + 100)]
    lon, lat = to_ll(xs, ys) if picked else ([], [])
    feats = []
    for i, (code, x, y, g500, annual, monthly, flags) in enumerate(picked):
        ring = [[round(lon[4 * i + k], 6), round(lat[4 * i + k], 6)] for k in range(4)]
        ring.append(ring[0])
        before = prev.get(code)
        drop = (flags or {}).get("drop")
        feats.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [ring]}, "properties": {
            "id": code, "x": int(x), "y": int(y), "grid500": g500, "elec_t": annual, "status": status_of(annual),
            "prev_year": prev_year, "prev_t": before,
            "change_pct": round((annual - before) / before * 100, 1) if annual is not None and before else None,
            "drop": bool(drop), "drop_from_t": drop["from_t"] if drop else None,
            **({"monthly": monthly} if grid500 else {})}})
    summary = None
    if grid500:
        values = [f["properties"]["elec_t"] for f in feats]
        known = [v for v in values if v is not None]
        summary = {"cells": len(feats), "value_cells": sum(1 for v in known if v > 0), "zero_cells": sum(1 for v in known if v == 0),
                   "total_t": round(sum(known), 2) if known else None,
                   "prev_total_t": round(sum(v for v in (prev.get(f["properties"]["id"]) for f in feats) if v is not None), 2) if prev_year else None,
                   "drop_cells": sum(1 for f in feats if f["properties"]["drop"]),
                   "monthly": [round(sum(f["properties"]["monthly"][i] for f in feats if f["properties"]["monthly"][i] is not None), 2)
                               if any(f["properties"]["monthly"][i] is not None for f in feats) else None for i in range(12)]}
    return {"type": "FeatureCollection", "features": feats, "meta": m, "summary": summary}


# --------------------------------------------------------------------------- area simulation
def area_inputs(db: Any, region_code: str | None) -> dict[str, Any] | None:
    """Every cell of every year of the region with its center (for the area simulation); None when nothing was imported."""
    ys = years(db, region_code)
    if not ys:
        return None
    out: dict[int, list[tuple[Any, ...]]] = {}
    for year in ys:
        rows = cells(db, region_code, year)
        pts = centers(region_code, year)
        out[year] = [(r[0], r[3], pt[0], pt[1], r[4], r[5], (r[6] or {}).get("drop")) for r, pt in zip(rows, pts)]
    return {"years": ys, "cells": out, "source": SOURCE}


def area_block(area: dict[str, Any], kcsm: dict[str, Any] | None, building_energy: dict[int, dict[str, Any]] | None = None,
               register: list[dict[str, Any]] | None = None, factor_for_year: Callable[[int], float | None] | None = None,
               inside: Callable[[float, float, dict[str, Any] | None], bool] | None = None) -> dict[str, Any] | None:
    """The area's 100m electricity emissions per year, two ways, and the tool's own value on the same 500m grids.

    boundary: cells whose center lies inside the area outline (행정동·다각형·반경) — the 100m data's own precision;
    grid:     cells inside the area's 500m grids — the same footprint as every other block of the area simulation.
    tool:     건축HUB 12개월 계측 지번 kWh of the same grids × that year's GIR factor (DATA_STANDARD 5.12: compared, never added).
    """
    if not kcsm or not kcsm.get("years"):
        return None
    grid_ids = set(area.get("grid_ids") or [])
    geometry = area.get("geometry") if area.get("type") in ("admin", "polygon", "circle") else None
    if inside is None:
        from .area import point_in_geometry as inside_fn

        def inside(lon: float, lat: float, geom: dict[str, Any] | None) -> bool:
            return inside_fn(lon, lat, geom)
    years_out: dict[int, dict[str, Any]] = {}
    previous: dict[str, float | None] = {}
    for year in sorted(kcsm["years"]):
        rows = kcsm["cells"].get(year) or []
        grid_rows = [r for r in rows if r[1] in grid_ids]
        boundary_rows = [r for r in rows if inside(r[2], r[3], geometry)] if geometry else grid_rows
        if not boundary_rows and not grid_rows:
            continue

        def total(rs: list[tuple[Any, ...]]) -> float | None:
            known = [r[4] for r in rs if r[4] is not None]
            return round(sum(known), 2) if known else None
        monthly = [round(sum(r[5][i] for r in boundary_rows if r[5] and r[5][i] is not None), 2)
                   if any(r[5] and r[5][i] is not None for r in boundary_rows) else None for i in range(12)]
        drops = [r for r in boundary_rows if r[6]]
        item: dict[str, Any] = {
            "year": year, "boundary_t": total(boundary_rows), "grid_t": total(grid_rows),
            "cells": len(boundary_rows), "value_cells": sum(1 for r in boundary_rows if r[4]), "zero_cells": sum(1 for r in boundary_rows if r[4] == 0),
            "grid_cells": len(grid_rows), "monthly": monthly,
            "drop_cells": len(drops), "drop_from_t": round(sum(r[6]["from_t"] for r in drops), 2) if drops else None,
            "drop_now_t": round(sum(r[4] or 0 for r in drops), 2) if drops else None,
        }
        be = (building_energy or {}).get(year) or {}
        factor = factor_for_year(year) if factor_for_year else None
        if be.get("electricity_kwh") is not None and factor:
            tool_t = be["electricity_kwh"] * factor / 1000
            item["tool"] = {"kwh": be["electricity_kwh"], "factor": factor, "t": round(tool_t, 2), "parcels": be.get("electricity_complete"),
                            "complete": be.get("complete", True),
                            "share_pct": round(tool_t / item["grid_t"] * 100, 1) if item["grid_t"] else None}
        if register:
            gfa = [float(r["gfa"]) for r in register if r.get("grid_id") in grid_ids and r.get("gfa")
                   and (r.get("approval_year") is None or r["approval_year"] <= year)]
            item["register_gfa_m2"] = round(sum(gfa), 1) if gfa else None
            item["register_buildings"] = len(gfa)
        if previous and item["boundary_t"] is not None:
            before = previous.get("boundary_t")
            item["change_pct"] = round((item["boundary_t"] - before) / before * 100, 1) if before else None
            item["change_from"] = previous.get("year")
        previous = item
        years_out[year] = item
    if not years_out:
        return {"available": False, "source": SOURCE, "years": {}, "reason": "구역 안에 탄소공간지도 100m 칸이 없습니다."}
    return {"available": True, "source": SOURCE, "unit": UNIT, "years": years_out,
            "boundary_basis": ("행정동 경계 안에 중심점이 있는 100m 칸" if area.get("type") == "admin" else
                               "구역 안에 중심점이 있는 100m 칸" if geometry else "구역 500m 격자 안의 100m 칸"),
            "grid_basis": f"구역 500m 격자 {len(grid_ids)}개 안의 100m 칸 (이 화면의 다른 값과 같은 범위)",
            "note": ("선도소프트가 준 탄소공간지도 값(건물 전기, tCO2eq, 산정 계수 확인 필요)입니다. 0은 제공값이며 건물 없음인지 미연계인지 확인이 필요합니다. "
                     "이 도구의 건축HUB 계측값과 더하지 않고 같은 격자 범위끼리 비교만 합니다.")}
