"""팀원 데이터셋(urban-carbon, 윤영준, 2026-10-01)의 격자 자료를 이 도구에 붙인다.

공유 묶음의 ``data/processed/<도시>/<연도>/grid_500m.csv``, ``grid_100m.csv``, ``<도시>/developments.csv``를
``DATA_DIR/raw/team_urban_carbon/<묶음 날짜>/<도시>/...``에 두고 ``python -m app.cli import-team-grid``로 넣는다.

넣는 것 (이 도구에 없던 출처):

* 탄소공간지도(국토교통부) 500m 건물 배출: 전기·가스·지역난방, 월별과 연간(tCO₂eq), 2016·2019·2022·2024
* 국토통계지도(국토지리정보원) 100m 인구·건물 수·추정 연면적 — **국외 반출 금지**: 공개 시연(게이트웨이 경유)
  응답에서는 빼고(``public``), Git·외부로 내보내지 않는다
* 건축물대장 용도별 연면적의 격자 합 — 이 도구가 대장을 받지 않은 지역에서만 지도에 쓴다
* 개발 사례(500m 칸 × 두 시점의 연면적 증가와 배출 전후)

넣지 않는 것 (이미 있는 출처와 중복): SGIS 격자 통계, 기상, K-apt 단지, 건축HUB 지번 에너지(이 도구가 전 지번으로
받는다), VWorld 지번·용도지역. 합본 폴더(``00_*``)는 도시 표를 이어 붙인 것이라 읽지 않는다(같은 칸을 두 번 세지 않음).

중복 규칙: 한 칸은 (데이터셋, 격자 ID, 연도)로 한 번만 저장한다. 같은 파일을 다시 넣으면 그 파일의 행을 지우고 다시
쓴다(SHA-256이 같으면 건너뜀). 빈 값은 0이 아니라 결측(None)이다.
"""
from __future__ import annotations

import csv
import hashlib
import math
import os
import re
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import JSON, Boolean, Float, Integer, String, delete, func, insert, select
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base

SNAPSHOT = "2026-10-01"
SOURCE_CARBONMAP = "국토교통부 탄소공간지도 500m 건물 배출 (팀 수집: 윤영준, 2026-10-01)"
SOURCE_NGII = "국토지리정보원 국토통계지도 100m (팀 수집, 국외 반출 금지)"
YEARS = (2016, 2019, 2022, 2024)
HEADER_PUBLIC = "x-public-gateway"
UNKNOWN_ZERO = ("zero_with_buildings", "zero_buildings_unknown")


class TeamGrid500(Base):
    __tablename__ = "team_grid500"
    id: Mapped[str] = mapped_column(String, primary_key=True)  # "<dataset>|<grid>|<year>"
    dataset: Mapped[str] = mapped_column(String, index=True)
    region_code: Mapped[str] = mapped_column(String, index=True)
    grid_code: Mapped[str] = mapped_column(String, index=True)
    x: Mapped[int] = mapped_column(Integer)
    y: Mapped[int] = mapped_column(Integer)
    year: Mapped[int] = mapped_column(Integer, index=True)
    elec_t: Mapped[float | None] = mapped_column(Float, nullable=True)
    gas_t: Mapped[float | None] = mapped_column(Float, nullable=True)
    heat_t: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_t: Mapped[float | None] = mapped_column(Float, nullable=True)
    monthly: Mapped[dict] = mapped_column(JSON, default=dict)
    ngii: Mapped[dict] = mapped_column(JSON, default=dict)       # 국토통계지도 (국외 반출 금지)
    register: Mapped[dict] = mapped_column(JSON, default=dict)   # 건축물대장 합
    flags: Mapped[dict] = mapped_column(JSON, default=dict)      # 팀 데이터셋의 점검 표시
    partial: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    source_file: Mapped[str] = mapped_column(String)


class TeamGrid100(Base):
    __tablename__ = "team_grid100"
    id: Mapped[str] = mapped_column(String, primary_key=True)  # "<dataset>|<grid100>|<year>"
    dataset: Mapped[str] = mapped_column(String, index=True)
    region_code: Mapped[str] = mapped_column(String, index=True)
    grid_code: Mapped[str] = mapped_column(String)
    grid500_code: Mapped[str] = mapped_column(String, index=True)
    x: Mapped[int] = mapped_column(Integer)
    y: Mapped[int] = mapped_column(Integer)
    year: Mapped[int] = mapped_column(Integer, index=True)
    population: Mapped[float | None] = mapped_column(Float, nullable=True)
    population_status: Mapped[str | None] = mapped_column(String, nullable=True)  # observed | masked(1~5명 비공개) | empty
    building_count: Mapped[float | None] = mapped_column(Float, nullable=True)
    floor_area_est: Mapped[float | None] = mapped_column(Float, nullable=True)
    approval_year: Mapped[float | None] = mapped_column(Float, nullable=True)
    zone_class: Mapped[str | None] = mapped_column(String, nullable=True)
    reg_floor_area: Mapped[float | None] = mapped_column(Float, nullable=True)


class TeamDevelopment(Base):
    __tablename__ = "team_developments"
    id: Mapped[str] = mapped_column(String, primary_key=True)  # "<dataset>|<development_id>|<grid>"
    dataset: Mapped[str] = mapped_column(String, index=True)
    region_code: Mapped[str] = mapped_column(String, index=True)
    grid_code: Mapped[str] = mapped_column(String)
    x: Mapped[int] = mapped_column(Integer)
    y: Mapped[int] = mapped_column(Integer)
    before_year: Mapped[int] = mapped_column(Integer)
    after_year: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class TeamImport(Base):
    __tablename__ = "team_imports"
    path: Mapped[str] = mapped_column(String, primary_key=True)
    sha256: Mapped[str] = mapped_column(String)
    rows: Mapped[int] = mapped_column(Integer, default=0)


# --------------------------------------------------------------------------- parsing (pure)
def num(value: Any) -> float | None:
    """CSV cell → float; '' / 'nan' / unreadable → None (결측, never 0)."""
    if value is None:
        return None
    s = str(value).strip()
    if not s or s.lower() in ("nan", "none", "null", "n/a"):
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def truth(value: Any) -> bool | None:
    s = str(value or "").strip().lower()
    return True if s == "true" else False if s == "false" else None


def dataset_region(name: str) -> str | None:
    """'52110_전주시' → '52110'; 합본('00_…') and anything without a 5-digit code → None."""
    m = re.match(r"^(\d{5})_", name)
    return m.group(1) if m and not name.startswith("00_") else None


NGII_500 = {
    "population": "population_total_persons_sum", "population_masked_cells": "population_total_persons_masked_cells",
    "population_min": "population_total_persons_min_est", "population_max": "population_total_persons_max_est",
    "buildings": "building_count_sum", "apartments": "apartment_building_count_sum", "detached": "detached_building_count_sum",
    "floor_area": "floor_area_total_est_m2", "approval_year": "approval_year_mean_wmean", "height": "height_mean_m_wmean",
    "floors": "ground_floors_mean_wmean",
}
REGISTER_500 = {
    "floor_area": "reg_floor_area_m2", "residential": "reg_residential_floor_area_m2", "nonresidential": "reg_nonresidential_floor_area_m2",
    "dwellings": "reg_dwellings", "buildings": "reg_building_count", "commercial": "reg_commercial_floor_area_m2",
    "office": "reg_office_floor_area_m2", "industrial": "reg_industrial_floor_area_m2",
}
FLAGS_500 = ("carbon_zero_status", "elec_drop_status", "gas_drop_status", "heat_drop_status", "elec_underreport_status",
             "floor_area_check_status", "train_issues", "zone_main_class")


def row500(dataset: str, year: int, r: dict[str, str], source_file: str) -> dict[str, Any] | None:
    grid = (r.get("grid_id_500m") or "").strip()
    x, y = num(r.get("x_min_m")), num(r.get("y_min_m"))
    if not grid or x is None or y is None:
        return None
    monthly = {}
    for e in ("elec", "gas", "heat"):
        months = [num(r.get(f"{e}_tco2e_m{m:02d}")) for m in range(1, 13)]
        if any(v is not None for v in months):
            monthly[e] = months
    flags = {k: r.get(k) for k in FLAGS_500 if r.get(k) not in (None, "")}
    flags["train_usable"] = truth(r.get("train_usable"))
    return {
        "id": f"{dataset}|{grid}|{year}", "dataset": dataset, "region_code": dataset_region(dataset) or "", "grid_code": grid,
        "x": int(x), "y": int(y), "year": year,
        "elec_t": num(r.get("elec_tco2e_total")), "gas_t": num(r.get("gas_tco2e_total")), "heat_t": num(r.get("heat_tco2e_total")),
        "total_t": num(r.get("buildings_tco2e_total")), "monthly": monthly,
        "ngii": {k: num(r.get(c)) for k, c in NGII_500.items()},
        "register": {k: num(r.get(c)) for k, c in REGISTER_500.items()},
        "flags": flags, "partial": truth(r.get("is_partial_cell")), "source_file": source_file,
    }


def row100(dataset: str, year: int, r: dict[str, str]) -> dict[str, Any] | None:
    grid, grid500 = (r.get("grid_id_100m") or "").strip(), (r.get("grid_id_500m") or "").strip()
    x, y = num(r.get("x_min_m")), num(r.get("y_min_m"))
    if not grid or x is None or y is None:
        return None
    status = (r.get("population_total_persons_status") or "").strip() or None
    out = {
        "id": f"{dataset}|{grid}|{year}", "dataset": dataset, "region_code": dataset_region(dataset) or "", "grid_code": grid,
        "grid500_code": grid500, "x": int(x), "y": int(y), "year": year,
        "population": num(r.get("population_total_persons")), "population_status": status,
        "building_count": num(r.get("building_count")), "floor_area_est": num(r.get("floor_area_total_est_m2")),
        "approval_year": num(r.get("approval_year_mean")), "zone_class": (r.get("zone_class") or None),
        "reg_floor_area": num(r.get("reg_floor_area_m2")),
    }
    # a cell with nothing at all (no people, no building, no register floor area) carries no information
    if status in (None, "empty") and out["building_count"] is None and not out["reg_floor_area"]:
        return None
    return out


def dev_row(dataset: str, r: dict[str, str]) -> dict[str, Any] | None:
    grid = (r.get("grid_id_500m") or "").strip()
    x, y, b, a = num(r.get("x_min_m")), num(r.get("y_min_m")), num(r.get("before_year")), num(r.get("after_year"))
    if not grid or None in (x, y, b, a):
        return None
    dev = (r.get("development_id") or f"{int(b)}_{int(a)}_{grid}").strip()
    values = {k: (num(v) if num(v) is not None else (v or None)) for k, v in r.items()}
    return {"id": f"{dataset}|{dev}|{grid}", "dataset": dataset, "region_code": dataset_region(dataset) or "", "grid_code": grid,
            "x": int(x), "y": int(y), "before_year": int(b), "after_year": int(a), "data": values}


# --------------------------------------------------------------------------- import
def team_root() -> Path:
    return Path(os.getenv("DATA_DIR", "data")) / "raw" / "team_urban_carbon"


def dataset_dirs(root: Path) -> list[Path]:
    """City dataset folders of every snapshot (the newest snapshot wins for the same dataset name)."""
    found: dict[str, Path] = {}
    for snap in sorted(p for p in root.glob("*") if p.is_dir()):
        for d in sorted(p for p in snap.glob("*") if p.is_dir()):
            if dataset_region(d.name):
                found[d.name] = d
    return [found[k] for k in sorted(found)]


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _rows(path: Path) -> Iterable[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        yield from csv.DictReader(f)


def import_team_grid(db: Any, root: Path | None = None, force: bool = False, log=print) -> dict[str, Any]:
    root = root or team_root()
    for model in (TeamGrid500, TeamGrid100, TeamDevelopment, TeamImport):
        model.__table__.create(db.get_bind(), checkfirst=True)
    stats: dict[str, Any] = {"datasets": [], "grid500": 0, "grid100": 0, "developments": 0, "skipped_files": 0}
    for d in dataset_dirs(root):
        stats["datasets"].append(d.name)
        jobs: list[tuple[Path, Any]] = []
        for year_dir in sorted(p for p in d.glob("*") if p.is_dir() and p.name.isdigit()):
            year = int(year_dir.name)
            jobs.append((year_dir / "grid_500m.csv", ("g500", year)))
            jobs.append((year_dir / "grid_100m.csv", ("g100", year)))
        jobs.append((d / "developments.csv", ("dev", None)))
        for path, (kind, year) in jobs:
            if not path.exists():
                continue
            rel = str(path.relative_to(root))
            sha = _sha(path)
            done = db.get(TeamImport, rel)
            if done and done.sha256 == sha and not force:
                stats["skipped_files"] += 1
                continue
            if kind == "g500":
                db.execute(delete(TeamGrid500).where(TeamGrid500.dataset == d.name, TeamGrid500.year == year))
                rows = [x for x in (row500(d.name, year, r, rel) for r in _rows(path)) if x]
                model = TeamGrid500
            elif kind == "g100":
                db.execute(delete(TeamGrid100).where(TeamGrid100.dataset == d.name, TeamGrid100.year == year))
                rows = [x for x in (row100(d.name, year, r) for r in _rows(path)) if x]
                model = TeamGrid100
            else:
                db.execute(delete(TeamDevelopment).where(TeamDevelopment.dataset == d.name))
                rows = [x for x in (dev_row(d.name, r) for r in _rows(path)) if x]
                model = TeamDevelopment
            unique = {r["id"]: r for r in rows}  # the same key twice in one file: the last row (no double count)
            rows = list(unique.values())
            for start in range(0, len(rows), 5000):
                db.execute(insert(model), rows[start:start + 5000])
            if done:
                done.sha256, done.rows = sha, len(rows)
            else:
                db.add(TeamImport(path=rel, sha256=sha, rows=len(rows)))
            db.commit()
            stats[{"g500": "grid500", "g100": "grid100", "dev": "developments"}[kind]] += len(rows)
            log(f"{rel}: {len(rows)}")
    _CACHE.clear()
    return stats


def counts(db: Any) -> dict[str, int]:
    out = {}
    for name, model in (("grid500", TeamGrid500), ("grid100", TeamGrid100), ("developments", TeamDevelopment)):
        try:
            out[name] = int(db.scalar(select(func.count()).select_from(model)) or 0)
        except Exception:  # noqa: BLE001 - table missing
            db.rollback()
            out[name] = 0
    return out


# --------------------------------------------------------------------------- readers
_CACHE: dict[tuple[Any, ...], Any] = {}


def year_for(available: Iterable[int], year: int) -> int | None:
    """The newest team year not after the map year (2025 → 2024, 2020 → 2019); None before the first."""
    ok = [y for y in available if y <= year]
    return max(ok) if ok else None


def _change(now: float | None, base: float | None) -> float | None:
    return round((now - base) / base * 100, 1) if now is not None and base else None


def cell_properties(now: dict[str, Any], base: dict[str, Any] | None, public: bool, register_known: bool) -> dict[str, Any]:
    """Map properties of one 500m cell from the team rows of the chosen year (and of the first year for the change)."""
    ngii = now.get("ngii") or {}
    floor = ngii.get("floor_area")
    flags = now.get("flags") or {}
    # 0 with buildings (or unknown buildings) is a missing value in the source, not "no emission"
    unknown_zero = flags.get("carbon_zero_status") in UNKNOWN_ZERO
    pick = (lambda k: None if unknown_zero else now.get(k))  # noqa: E731
    base_total = None if not base or (base.get("flags") or {}).get("carbon_zero_status") in UNKNOWN_ZERO else base.get("total_t")
    p: dict[str, Any] = {
        "cm_year": now["year"], "cm_total_t": pick("total_t"), "cm_elec_t": pick("elec_t"), "cm_gas_t": pick("gas_t"),
        "cm_heat_t": pick("heat_t"), "cm_flags": flags, "cm_partial": now.get("partial"),
        "cm_change_base_year": base["year"] if base else None,
        "cm_change_pct": _change(pick("total_t"), base_total),
        "cm_kg_per_m2": round(now["total_t"] * 1000 / floor, 1) if pick("total_t") is not None and floor else None,
    }
    if not public:
        # 국토통계지도: 국외 반출 금지 — only for local (non-gateway) requests
        p.update({"ngii_population": ngii.get("population"), "ngii_population_masked_cells": ngii.get("population_masked_cells"),
                  "ngii_buildings": ngii.get("buildings"), "ngii_floor_area_m2": floor, "ngii_approval_year": ngii.get("approval_year")})
    else:
        p["cm_kg_per_m2"] = None  # its denominator is the restricted floor area
    reg = now.get("register") or {}
    if not register_known and reg.get("floor_area"):
        p.update({"team_reg_floor_area_m2": reg.get("floor_area"), "team_reg_residential_m2": reg.get("residential"),
                  "team_reg_nonresidential_m2": reg.get("nonresidential"), "team_reg_dwellings": reg.get("dwellings")})
    return p


def map_properties(db: Any, region_code: str | None, year: int, grid_ids: Iterable[str], public: bool = False,
                   register_ids: Iterable[str] = ()) -> dict[str, dict[str, Any]]:
    """{'cell_x_y': props} for the cells of the region's team dataset (empty when the region has none)."""
    if not region_code:
        return {}
    try:
        years = sorted({int(y) for (y,) in db.execute(select(TeamGrid500.year).where(TeamGrid500.region_code == region_code).distinct())})
    except Exception:  # noqa: BLE001 - table missing
        db.rollback()
        return {}
    chosen = year_for(years, year)
    if chosen is None:
        return {}
    first = years[0] if years and years[0] < chosen else None
    key = (region_code, chosen, first, public)
    if key not in _CACHE:
        def load(y: int) -> dict[str, dict[str, Any]]:
            cols = (TeamGrid500.x, TeamGrid500.y, TeamGrid500.year, TeamGrid500.total_t, TeamGrid500.elec_t, TeamGrid500.gas_t,
                    TeamGrid500.heat_t, TeamGrid500.ngii, TeamGrid500.register, TeamGrid500.flags, TeamGrid500.partial)
            out = {}
            for x, yy, yr, total, e, g, h, ngii, reg, flags, partial in db.execute(
                    select(*cols).where(TeamGrid500.region_code == region_code, TeamGrid500.year == y)):
                out[f"cell_{x}_{yy}"] = {"year": yr, "total_t": total, "elec_t": e, "gas_t": g, "heat_t": h, "ngii": ngii,
                                          "register": reg, "flags": flags, "partial": partial}
            return out
        _CACHE[key] = (load(chosen), load(first) if first else {})
    now_rows, base_rows = _CACHE[key]
    wanted = set(grid_ids)
    register_known = set(register_ids)
    return {gid: cell_properties(row, base_rows.get(gid), public, gid in register_known) for gid, row in now_rows.items() if gid in wanted}


def region_totals(db: Any, region_code: str) -> dict[int, dict[str, float]]:
    """{year: {elec, gas, heat, total (tCO2e), cells}} of a region's team dataset."""
    out: dict[int, dict[str, float]] = {}
    try:
        for year, e, g, h, t, n in db.execute(select(TeamGrid500.year, func.sum(TeamGrid500.elec_t), func.sum(TeamGrid500.gas_t),
                                                      func.sum(TeamGrid500.heat_t), func.sum(TeamGrid500.total_t), func.count())
                                               .where(TeamGrid500.region_code == region_code).group_by(TeamGrid500.year)):
            out[int(year)] = {"elec_t": round(e or 0, 1), "gas_t": round(g or 0, 1), "heat_t": round(h or 0, 1), "total_t": round(t or 0, 1), "cells": int(n)}
    except Exception:  # noqa: BLE001
        db.rollback()
    return out


def pair_stats(pairs: list[tuple[float, float]]) -> dict[str, Any] | None:
    """ours/theirs per cell: count, sum ratio, median ratio, share within ±20%, Pearson r of log values (pure)."""
    pairs = [(a, b) for a, b in pairs if a and b and a > 0 and b > 0]
    if len(pairs) < 3:
        return None
    ratios = sorted(a / b for a, b in pairs)
    n = len(ratios)
    med = ratios[n // 2] if n % 2 else (ratios[n // 2 - 1] + ratios[n // 2]) / 2
    la, lb = [math.log(a) for a, _ in pairs], [math.log(b) for _, b in pairs]
    ma, mb = sum(la) / n, sum(lb) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(la, lb))
    va, vb = sum((x - ma) ** 2 for x in la), sum((y - mb) ** 2 for y in lb)
    r = cov / math.sqrt(va * vb) if va and vb else None
    return {"cells": n, "sum_ratio": round(sum(a for a, _ in pairs) / sum(b for _, b in pairs), 3), "median_ratio": round(med, 3),
            "within_20pct": round(sum(1 for x in ratios if 0.8 <= x <= 1.2) / n, 3), "log_r": round(r, 3) if r is not None else None}


def carbonmap_comparison(db: Any, region_code: str) -> dict[str, Any] | None:
    """Region totals of 탄소공간지도 and, for the newest common year, this tool's 건축HUB electricity carbon per cell."""
    totals = region_totals(db, region_code)
    if not totals:
        return None
    out: dict[str, Any] = {"years": {str(y): v for y, v in sorted(totals.items())}, "source": SOURCE_CARBONMAP}
    try:
        from .energy_parcels import grid_building_energy
        from .service import factors_for
        for year in sorted(totals, reverse=True):
            hub = grid_building_energy(db, year)
            if not hub:
                continue
            factor = (factors_for(db, year).get("ELECTRICITY") or {}).get("factor")
            if not factor:
                continue
            team = {f"cell_{x}_{y}": e for x, y, e in db.execute(select(TeamGrid500.x, TeamGrid500.y, TeamGrid500.elec_t)
                                                                    .where(TeamGrid500.region_code == region_code, TeamGrid500.year == year))}
            pairs = [(item["electricity_kwh"] * factor / 1000, team[g]) for g, item in hub.items()
                     if g in team and item.get("electricity_kwh") and team[g]]
            stats = pair_stats(pairs)
            if stats:
                out["cells"] = dict(stats, year=year, factor=factor)
                break
    except Exception:  # noqa: BLE001
        db.rollback()
    return out


def developments(db: Any, region_code: str) -> list[dict[str, Any]]:
    try:
        rows = db.scalars(select(TeamDevelopment).where(TeamDevelopment.region_code == region_code)
                          .order_by(TeamDevelopment.before_year, TeamDevelopment.grid_code)).all()
    except Exception:  # noqa: BLE001
        db.rollback()
        return []
    keep = ("dong_name", "zone_main_class", "floor_area_added_m2", "buildings_tco2e_before", "buildings_tco2e_after", "buildings_tco2e_change",
            "elec_tco2e_change", "gas_tco2e_change", "heat_tco2e_change", "pair_usable", "site_kind", "use_kind", "development_id", "development_cells")
    return [dict({"grid_id": f"cell_{r.x}_{r.y}", "grid_code": r.grid_code, "before_year": r.before_year, "after_year": r.after_year},
                 **{k: (r.data or {}).get(k) for k in keep}) for r in rows]


def is_public(request: Any) -> bool:
    """Requests that came through the public demo gateway (deploy/gateway.conf sets the header)."""
    try:
        return (request.headers.get(HEADER_PUBLIC) or "") == "1"
    except Exception:  # noqa: BLE001
        return False
