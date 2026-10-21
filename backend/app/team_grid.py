"""팀원 데이터셋(urban-carbon, 윤영준)의 격자 자료를 이 도구에 붙인다.

두 가지 묶음 모양을 읽는다(``DATA_DIR/raw/team_urban_carbon/<묶음 날짜>/``, ``python -m app.cli import-team-grid``):

* 2026-10-01 공유 묶음: ``<도시>/<연도>/grid_500m.csv``, ``grid_100m.csv``, ``<도시>/developments.csv`` (4개 도시 × 4개 해)
* 2026-10-20 인계 묶음(7차): ``code/data/processed/<도시>/training.csv``(500m 칸 × 7개 해, 월별·100m 없음),
  ``developments.csv``, 그리고 모델 점수 ``00_합본_7차/baseline/development_cases.csv``(학습 42곳 교차검증)와
  ``code/docs/results/data/r011-split-a/holdout_cases_join7_42_w10.csv``(시험 10곳) — 53개 지역

같은 도시·같은 해는 가장 새 묶음 한 곳에서만 읽는다(500m는 해마다, 100m는 해마다, 개발 사례는 도시마다). 새 묶음에
월별 값이 없으면 앞 묶음의 월별 값을 연간 합계가 같을 때만 남긴다. 100m는 7차 묶음에 없어 2026-10-01 값을 그대로 쓴다.

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

SNAPSHOT = "2026-10-20"
SOURCE_CARBONMAP = "국토교통부 탄소공간지도 500m 건물 배출 (팀 수집: 윤영준, 7차 인계 2026-10-20)"
SOURCE_NGII = "국토지리정보원 국토통계지도 100m (팀 수집, 국외 반출 금지)"
YEARS = (2014, 2016, 2018, 2019, 2021, 2022, 2024)
TRAINING_FILE = "training.csv"  # 7차 인계: 한 도시의 모든 해 500m 칸
# 모델 점수 파일(7차): 학습 42곳 사례의 교차검증 예측과 시험 10곳 사례의 예측(학습에 없던 지역)
CASES_CV = ("code", "data", "processed", "00_합본_7차", "baseline", "development_cases.csv")
CASES_TEST = ("code", "docs", "results", "data", "r011-split-a", "holdout_cases_join7_42_w10.csv")
MODEL_NAME = "팀 변화 모델 7차 (00_합본_7차, 42곳, 사례 가중 ×10)"
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
             "floor_area_check_status", "register_check_status", "train_issues", "zone_main_class")


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
    # 7차 표는 한 칸에 가능한 전후 해 쌍을 모두 담으므로 해까지 넣어 한 줄 = 한 쌍
    return {"id": f"{dataset}|{dev}|{grid}|{int(b)}-{int(a)}", "dataset": dataset, "region_code": dataset_region(dataset) or "", "grid_code": grid,
            "x": int(x), "y": int(y), "before_year": int(b), "after_year": int(a), "data": values}


# --------------------------------------------------------------------------- import
def team_root() -> Path:
    return Path(os.getenv("DATA_DIR", "data")) / "raw" / "team_urban_carbon"


def snapshot_dirs(root: Path) -> list[Path]:
    """Snapshot folders, oldest first (``_incoming``·``_docs`` 같은 이름은 묶음이 아님)."""
    return sorted(p for p in root.glob("*") if p.is_dir() and not p.name.startswith(("_", ".")))


def city_dirs(snap: Path) -> list[Path]:
    """City folders of one snapshot: ``<snap>/<도시>`` (10-01 공유) and ``<snap>/code/data/processed/<도시>`` (10-20 인계)."""
    out: list[Path] = []
    for base in (snap, snap / "code" / "data" / "processed"):
        if base.is_dir():
            out += [d for d in sorted(base.iterdir()) if d.is_dir() and dataset_region(d.name)]
    return out


def dataset_dirs(root: Path) -> list[Path]:
    """City dataset folders of every snapshot (the newest snapshot wins for the same dataset name)."""
    found: dict[str, Path] = {}
    for snap in snapshot_dirs(root):
        for d in city_dirs(snap):
            found[d.name] = d
    return [found[k] for k in sorted(found)]


def dataset_snapshots(root: Path) -> dict[str, list[Path]]:
    """{dataset name: its folders in every snapshot, newest first}."""
    found: dict[str, list[Path]] = {}
    for snap in snapshot_dirs(root):
        for d in city_dirs(snap):
            found.setdefault(d.name, []).insert(0, d)
    return dict(sorted(found.items()))


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _rows(path: Path) -> Iterable[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        yield from csv.DictReader(f)


def file_years(path: Path) -> list[int]:
    """Years present in a multi-year table (the ``year`` column)."""
    years = {int(v) for v in (num(r.get("year")) for r in _rows(path)) if v is not None}
    return sorted(years)


def plan_sources(folders: list[Path]) -> dict[str, Any]:
    """Which file gives each kind of a dataset: the newest folder that has it (500m and 100m per year)."""
    g500: dict[int, tuple[Path, str]] = {}
    g100: dict[int, Path] = {}
    dev: Path | None = None
    for folder in folders:  # newest first
        training = folder / TRAINING_FILE
        if training.exists():
            for year in file_years(training):
                g500.setdefault(year, (training, "training"))
        for year_dir in sorted(p for p in folder.glob("*") if p.is_dir() and p.name.isdigit()):
            year = int(year_dir.name)
            if (year_dir / "grid_500m.csv").exists():
                g500.setdefault(year, (year_dir / "grid_500m.csv", "grid500"))
            if (year_dir / "grid_100m.csv").exists():
                g100.setdefault(year, year_dir / "grid_100m.csv")
        if dev is None and (folder / "developments.csv").exists():
            dev = folder / "developments.csv"
    return {"g500": g500, "g100": g100, "dev": dev}


def _close(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= max(0.5, 0.005 * abs(b))


def _insert(db: Any, model: Any, rows: list[dict[str, Any]]) -> None:
    for start in range(0, len(rows), 5000):
        db.execute(insert(model), rows[start:start + 5000])


def _write_g500(db: Any, dataset: str, year: int, rows: list[dict[str, Any]]) -> dict[str, int]:
    """Replace one dataset-year of 500m rows. A row without months keeps the months it had when its annual totals are
    the same (the 10-01 shared bundle had months, the 7차 table has none); otherwise the months are left out."""
    old = {g: (t, e, gs, h, m) for g, t, e, gs, h, m in db.execute(
        select(TeamGrid500.grid_code, TeamGrid500.total_t, TeamGrid500.elec_t, TeamGrid500.gas_t, TeamGrid500.heat_t, TeamGrid500.monthly)
        .where(TeamGrid500.dataset == dataset, TeamGrid500.year == year))}
    kept = dropped = 0
    for r in rows:
        if r["monthly"] or r["grid_code"] not in old:
            continue
        t, e, gs, h, months = old[r["grid_code"]]
        if not months:
            continue
        if all(_close(a, b) for a, b in ((r["total_t"], t), (r["elec_t"], e), (r["gas_t"], gs), (r["heat_t"], h))):
            r["monthly"] = months
            r["flags"] = dict(r["flags"], monthly_from="2026-10-01 공유 묶음")
            kept += 1
        else:
            dropped += 1
    db.execute(delete(TeamGrid500).where(TeamGrid500.dataset == dataset, TeamGrid500.year == year))
    _insert(db, TeamGrid500, rows)
    return {"months_kept": kept, "months_dropped": dropped}


def _done(db: Any, rel: str, sha: str, force: bool) -> tuple[bool, Any]:
    done = db.get(TeamImport, rel)
    return bool(done and done.sha256 == sha and not force), done


def _record(db: Any, done: Any, rel: str, sha: str, rows: int) -> None:
    if done:
        done.sha256, done.rows = sha, rows
    else:
        db.add(TeamImport(path=rel, sha256=sha, rows=rows))


def newest_file(root: Path, parts: tuple[str, ...]) -> Path | None:
    for snap in reversed(snapshot_dirs(root)):
        path = snap.joinpath(*parts)
        if path.exists():
            return path
    return None


def case_scores(root: Path) -> dict[tuple[str, str, int, int], dict[str, Any]]:
    """{(dataset, grid, before, after): model score} from the 7차 score files (pure reading).

    학습 42곳 사례는 교차검증 예측(그 칸을 빼고 학습한 모델)과 도시 보류 예측(그 지역을 빼고 학습)을, 시험 10곳 사례는
    7차 모델을 그대로 적용한 예측을 담는다. 어느 쪽도 그 사례를 보고 학습한 값이 아니다. ``row``는 점수 파일의 그 줄."""
    out: dict[tuple[str, str, int, int], dict[str, Any]] = {}
    cv = newest_file(root, CASES_CV)
    if cv:
        for r in _rows(cv):
            b, a = num(r.get("before_year")), num(r.get("after_year"))
            if b is None or a is None:
                continue
            out[(r.get("region") or "", (r.get("grid_id_500m") or "").strip(), int(b), int(a))] = {
                "set": "train_cv", "actual_tco2e": num(r.get("actual_change_tco2e")),
                "pred_tco2e": num(r.get("pred_change_model_all_regions_cv_tco2e")),
                "pred_other_regions_tco2e": num(r.get("pred_change_model_other_regions_tco2e")),
                "years_from": r.get("years_from") or None, "model": MODEL_NAME, "row": r}
    test = newest_file(root, CASES_TEST)
    if test:
        for r in _rows(test):
            b, a = num(r.get("before_year")), num(r.get("after_year"))
            if b is None or a is None:
                continue
            out[(r.get("region") or "", (r.get("grid_id_500m") or "").strip(), int(b), int(a))] = {
                "set": "test", "actual_tco2e": num(r.get("actual_change_tco2e")), "pred_tco2e": num(r.get("pred_change_model_frozen")),
                "years_from": r.get("years_from") or None, "model": MODEL_NAME, "row": r}
    return out


SCORE_ONLY = "|score|"  # id mark of a case whose chosen years are not one of the cell's listed pairs


def apply_case_scores(db: Any, scores: dict[tuple[str, str, int, int], dict[str, Any]]) -> int:
    """Put each score on its development pair row (``data["model"]``); returns how many cases got one.

    팀은 사례마다 착공·승인일로 전후 해를 고르므로(ADR 0026 보완) 그 해 쌍이 ``developments.csv``의 쌍에 없을 수 있다.
    그런 사례는 같은 칸의 좌표로 점수 파일의 줄을 한 줄 더한다(id에 ``|score|``). 지어낸 값은 없다."""
    if not scores:
        return 0
    datasets = sorted({k[0] for k in scores})
    hit = 0
    cells: dict[tuple[str, str], tuple[int, int, str]] = {}
    seen: set[tuple[str, str, int, int]] = set()
    for row in db.scalars(select(TeamDevelopment).where(TeamDevelopment.dataset.in_(datasets))):
        key = (row.dataset, row.grid_code, row.before_year, row.after_year)
        cells[(row.dataset, row.grid_code)] = (row.x, row.y, row.region_code)
        if SCORE_ONLY in row.id:
            if key not in scores:
                db.delete(row)
            continue
        score = scores.get(key)
        data = dict(row.data or {})
        if score is None and "model" not in data:
            continue
        if score is None:
            data.pop("model", None)
        else:
            data["model"] = {k: v for k, v in score.items() if k != "row"}
            seen.add(key)
            hit += 1
        row.data = data
    db.flush()
    existing = {r for r in db.scalars(select(TeamDevelopment.id).where(TeamDevelopment.id.contains(SCORE_ONLY)))}
    for key, score in scores.items():
        if key in seen:
            continue
        dataset, grid, b, a = key
        raw = score.get("row") or {}
        x, y = num(raw.get("x_min_m")), num(raw.get("y_min_m"))
        region = dataset_region(dataset) or ""
        if (x is None or y is None) and (dataset, grid) in cells:
            x, y, region = cells[(dataset, grid)]
        if x is None or y is None:
            continue
        values = {k: (num(v) if num(v) is not None else (v or None)) for k, v in raw.items() if k != "region"}
        values.setdefault("pair_usable", True)
        values["model"] = {k: v for k, v in score.items() if k != "row"}
        values["source"] = "팀 모델 점수 파일(사례마다 고른 전후 해)"
        rid = f"{dataset}{SCORE_ONLY}{grid}|{b}-{a}"
        if rid in existing:
            db.get(TeamDevelopment, rid).data = values
        else:
            db.add(TeamDevelopment(id=rid, dataset=dataset, region_code=region, grid_code=grid, x=int(x), y=int(y),
                                   before_year=b, after_year=a, data=values))
        hit += 1
    return hit


def import_team_grid(db: Any, root: Path | None = None, force: bool = False, log=print) -> dict[str, Any]:
    root = root or team_root()
    for model in (TeamGrid500, TeamGrid100, TeamDevelopment, TeamImport):
        model.__table__.create(db.get_bind(), checkfirst=True)
    stats: dict[str, Any] = {"datasets": [], "grid500": 0, "grid100": 0, "developments": 0, "skipped_files": 0,
                             "months_kept": 0, "months_dropped": 0, "scored_cases": None}
    dev_changed = False
    for name, folders in dataset_snapshots(root).items():
        stats["datasets"].append(name)
        plan = plan_sources(folders)
        # 500m: a multi-year training table is one file for several years
        by_file: dict[Path, list[int]] = {}
        for year, (path, _kind) in sorted(plan["g500"].items()):
            by_file.setdefault(path, []).append(year)
        for path, years in by_file.items():
            rel = str(path.relative_to(root))
            sha = _sha(path)
            skip, done = _done(db, rel, sha, force)
            if skip:
                stats["skipped_files"] += 1
                continue
            rows_by_year: dict[int, list[dict[str, Any]]] = {y: [] for y in years}
            if path.name == TRAINING_FILE:
                for r in _rows(path):
                    y = num(r.get("year"))
                    if y is not None and int(y) in rows_by_year:
                        row = row500(name, int(y), r, rel)
                        if row:
                            rows_by_year[int(y)].append(row)
            else:
                rows_by_year[years[0]] = [x for x in (row500(name, years[0], r, rel) for r in _rows(path)) if x]
            total = 0
            for year, rows in rows_by_year.items():
                rows = list({r["id"]: r for r in rows}.values())  # the same key twice in one file: the last row (no double count)
                kept = _write_g500(db, name, year, rows)
                stats["months_kept"] += kept["months_kept"]
                stats["months_dropped"] += kept["months_dropped"]
                total += len(rows)
            _record(db, done, rel, sha, total)
            db.commit()
            stats["grid500"] += total
            log(f"{rel}: {total} ({', '.join(str(y) for y in years)})")
        for year, path in sorted(plan["g100"].items()):
            rel = str(path.relative_to(root))
            sha = _sha(path)
            skip, done = _done(db, rel, sha, force)
            if skip:
                stats["skipped_files"] += 1
                continue
            db.execute(delete(TeamGrid100).where(TeamGrid100.dataset == name, TeamGrid100.year == year))
            rows = list({r["id"]: r for r in (x for x in (row100(name, year, r) for r in _rows(path)) if x)}.values())
            _insert(db, TeamGrid100, rows)
            _record(db, done, rel, sha, len(rows))
            db.commit()
            stats["grid100"] += len(rows)
            log(f"{rel}: {len(rows)}")
        path = plan["dev"]
        if path is not None:
            rel = str(path.relative_to(root))
            sha = _sha(path)
            skip, done = _done(db, rel, sha, force)
            if skip:
                stats["skipped_files"] += 1
            else:
                db.execute(delete(TeamDevelopment).where(TeamDevelopment.dataset == name))
                rows = list({r["id"]: r for r in (x for x in (dev_row(name, r) for r in _rows(path)) if x)}.values())
                _insert(db, TeamDevelopment, rows)
                _record(db, done, rel, sha, len(rows))
                db.commit()
                dev_changed = True
                stats["developments"] += len(rows)
                log(f"{rel}: {len(rows)}")
    # model scores of the development cases (7차): again whenever a case table or a score file changed
    files = [p for p in (newest_file(root, CASES_CV), newest_file(root, CASES_TEST)) if p]
    changed = dev_changed
    for p in files:
        rel = str(p.relative_to(root))
        sha = _sha(p)
        skip, done = _done(db, rel, sha, force)
        if not skip:
            changed = True
            _record(db, done, rel, sha, 0)
    if changed and files:
        stats["scored_cases"] = apply_case_scores(db, case_scores(root))
        db.commit()
        log(f"model scores on development cases: {stats['scored_cases']}")
    _CACHE.clear()
    _DATASETS.clear()
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


_DATASETS: dict[str, list[str]] = {}
_MEAN_KEYS = ("approval_year", "height", "floors")  # 국토통계 500m 값 가운데 합이 아니라 평균인 것


def region_datasets(db: Any, region_code: str | None) -> list[str]:
    """Team datasets of a study region: the one of its own code (전주 52110), else those of its 일반구 (수원 41110 → 41113 권선구,
    41117 영통구 — this tool keeps a city with its 구 as one region, ``StudyRegion.legal_codes``)."""
    if not region_code:
        return []
    if region_code in _DATASETS:
        return _DATASETS[region_code]
    codes = {region_code}
    try:
        from .regions import StudyRegion
        region = db.get(StudyRegion, region_code)
        if region is not None:
            codes.update(str(c) for c in (region.legal_codes or []))
    except Exception:  # noqa: BLE001 - table missing (tests)
        db.rollback()
    try:
        pairs = list(db.execute(select(TeamGrid500.region_code, TeamGrid500.dataset).where(TeamGrid500.region_code.in_(sorted(codes))).distinct()))
    except Exception:  # noqa: BLE001
        db.rollback()
        return []
    own = sorted({d for c, d in pairs if c == region_code})
    found = own or sorted({d for _, d in pairs})
    _DATASETS[region_code] = found
    return found


def combine_parts(parts: list[dict[str, Any]]) -> dict[str, Any]:
    """One 500m cell held by two 구 tables (each with its own part of the cell, ``is_partial_cell``) as one row (pure).

    배출·연면적·인구·대장 값은 더하고(없는 값은 빼고 더하되 모두 없으면 None), 평균값(사용승인연도·높이·층수)은 연면적이 큰 쪽,
    표시는 합치고, 학습 가능은 모든 몫이 가능할 때만. 시 경계인지 알 수 없어 ``partial``은 None으로 둔다."""
    if len(parts) == 1:
        return parts[0]

    def total(values: list[Any]) -> float | None:
        vals = [v for v in values if v is not None]
        return float(sum(vals)) if vals else None
    biggest = max(parts, key=lambda p: ((p.get("ngii") or {}).get("floor_area") or 0))
    keys = {k for p in parts for k in (p.get("ngii") or {})}
    ngii = {k: ((biggest.get("ngii") or {}).get(k) if k in _MEAN_KEYS else total([(p.get("ngii") or {}).get(k) for p in parts])) for k in keys}
    register = {k: total([(p.get("register") or {}).get(k) for p in parts]) for k in {k for p in parts for k in (p.get("register") or {})}}
    flags: dict[str, Any] = {}
    for p in parts:
        for k, v in (p.get("flags") or {}).items():
            if v in (None, "", "ok", "none", "positive") and k in flags:
                continue
            flags[k] = v
    issues = sorted({i for p in parts for i in str((p.get("flags") or {}).get("train_issues") or "").split("+") if i and i != "none"})
    flags["train_issues"] = "+".join(issues) if issues else "none"
    flags["train_usable"] = all((p.get("flags") or {}).get("train_usable") is True for p in parts)
    flags["districts"] = len(parts)
    monthly: dict[str, list[float | None]] = {}
    for source in ("elec", "gas", "heat"):
        series = [(p.get("monthly") or {}).get(source) for p in parts]
        if all(series):
            monthly[source] = [total(list(m)) for m in zip(*series)]
    return {"year": parts[0]["year"], "total_t": total([p.get("total_t") for p in parts]), "elec_t": total([p.get("elec_t") for p in parts]),
            "gas_t": total([p.get("gas_t") for p in parts]), "heat_t": total([p.get("heat_t") for p in parts]), "ngii": ngii,
            "register": register, "flags": flags, "partial": None, "monthly": monthly}


def map_properties(db: Any, region_code: str | None, year: int, grid_ids: Iterable[str], public: bool = False,
                   register_ids: Iterable[str] = ()) -> dict[str, dict[str, Any]]:
    """{'cell_x_y': props} for the cells of the region's team datasets (empty when the region has none)."""
    datasets = region_datasets(db, region_code)
    if not datasets:
        return {}
    try:
        years = sorted({int(y) for (y,) in db.execute(select(TeamGrid500.year).where(TeamGrid500.dataset.in_(datasets)).distinct())})
    except Exception:  # noqa: BLE001 - table missing
        db.rollback()
        return {}
    chosen = year_for(years, year)
    if chosen is None:
        return {}
    first = years[0] if years and years[0] < chosen else None
    key = (region_code, tuple(datasets), chosen, first, public)
    if key not in _CACHE:
        def load(y: int) -> dict[str, dict[str, Any]]:
            cols = (TeamGrid500.x, TeamGrid500.y, TeamGrid500.year, TeamGrid500.total_t, TeamGrid500.elec_t, TeamGrid500.gas_t,
                    TeamGrid500.heat_t, TeamGrid500.ngii, TeamGrid500.register, TeamGrid500.flags, TeamGrid500.partial)
            parts: dict[str, list[dict[str, Any]]] = {}
            for x, yy, yr, total, e, g, h, ngii, reg, flags, partial in db.execute(
                    select(*cols).where(TeamGrid500.dataset.in_(datasets), TeamGrid500.year == y)):
                parts.setdefault(f"cell_{x}_{yy}", []).append({"year": yr, "total_t": total, "elec_t": e, "gas_t": g, "heat_t": h, "ngii": ngii,
                                                                "register": reg, "flags": flags, "partial": partial})
            return {gid: combine_parts(rows) for gid, rows in parts.items()}
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
                                                      func.sum(TeamGrid500.heat_t), func.sum(TeamGrid500.total_t), func.count(func.distinct(TeamGrid500.grid_code)))
                                               .where(TeamGrid500.dataset.in_(region_datasets(db, region_code))).group_by(TeamGrid500.year)):
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
        from .regions import region_grid_ids
        from .service import factors_for
        for year in sorted(totals, reverse=True):
            hub = grid_building_energy(db, year, region_grid_ids(db, region_code) or None)
            if not hub:
                continue
            factor = (factors_for(db, year).get("ELECTRICITY") or {}).get("factor")
            if not factor:
                continue
            team: dict[str, float] = {}
            for x, y, e in db.execute(select(TeamGrid500.x, TeamGrid500.y, TeamGrid500.elec_t)
                                      .where(TeamGrid500.dataset.in_(region_datasets(db, region_code)), TeamGrid500.year == year)):
                if e is not None:
                    team[f"cell_{x}_{y}"] = team.get(f"cell_{x}_{y}", 0.0) + e
            pairs = [(item["electricity_kwh"] * factor / 1000, team[g]) for g, item in hub.items()
                     if g in team and item.get("electricity_kwh") and team[g]]
            stats = pair_stats(pairs)
            if stats:
                out["cells"] = dict(stats, year=year, factor=factor)
                break
    except Exception:  # noqa: BLE001
        db.rollback()
    return out


def developments(db: Any, region_code: str, scored_only: bool = False) -> list[dict[str, Any]]:
    """Development pairs of a region (7차: every before/after pair of a developed cell; ``model`` on the scored pair)."""
    try:
        rows = db.scalars(select(TeamDevelopment).where(TeamDevelopment.dataset.in_(region_datasets(db, region_code)))
                          .order_by(TeamDevelopment.before_year, TeamDevelopment.grid_code)).all()
    except Exception:  # noqa: BLE001
        db.rollback()
        return []
    keep = ("dong_name", "zone_main_class", "floor_area_added_m2", "reg_floor_area_added_m2", "reg_dwellings_added", "buildings_tco2e_before",
            "buildings_tco2e_after", "buildings_tco2e_change", "elec_tco2e_change", "gas_tco2e_change", "heat_tco2e_change", "pair_usable",
            "site_kind", "use_kind", "development_id", "development_cells", "case_start_year", "case_approval_year", "model")
    out = [dict({"grid_id": f"cell_{r.x}_{r.y}", "grid_code": r.grid_code, "dataset": r.dataset, "before_year": r.before_year, "after_year": r.after_year},
                **{k: (r.data or {}).get(k) for k in keep}) for r in rows]
    return [d for d in out if d.get("model")] if scored_only else out


def relative_error(actual: float | None, predicted: float | None) -> float | None:
    """|예측 − 실제| ÷ |실제| (팀 기준: 실제 100 tCO2e 이상 사례만 오차를 잰다)."""
    if actual is None or predicted is None or abs(actual) < 100:
        return None
    return abs(predicted - actual) / abs(actual)


def score_summary(cases: list[dict[str, Any]]) -> dict[str, Any] | None:
    """사례별 오차 중앙값·±50% 안·방향 일치·예측 합 ÷ 실제 합 (팀 결과 표와 같은 정의, pure)."""
    pairs = [(c["actual_tco2e"], c["pred_tco2e"]) for c in cases if c.get("actual_tco2e") is not None and c.get("pred_tco2e") is not None]
    if not pairs:
        return None
    errors = sorted(e for e in (relative_error(a, p) for a, p in pairs) if e is not None)
    n = len(errors)
    med = (errors[n // 2] if n % 2 else (errors[n // 2 - 1] + errors[n // 2]) / 2) if n else None
    actual_sum = sum(a for a, _ in pairs)
    return {"cases": len(pairs), "measured": n, "median_relative_error": round(med, 3) if med is not None else None,
            "within_50pct": round(sum(1 for e in errors if e <= 0.5) / n, 3) if n else None,
            "same_direction": round(sum(1 for a, p in pairs if (a >= 0) == (p >= 0)) / len(pairs), 3),
            "sum_ratio": round(sum(p for _, p in pairs) / actual_sum, 3) if actual_sum else None,
            "big_cases": sum(1 for a, _ in pairs if abs(a) >= 1000)}


def development_summary(db: Any, region_code: str) -> dict[str, Any]:
    """개발 사례 수와, 점수가 있으면 이 지역 사례에서 팀 변화 모델이 맞힌 정도(학습 교차검증 또는 시험)."""
    devs = developments(db, region_code)
    cells = {d["grid_code"] for d in devs}
    usable = {(d["grid_code"], d["before_year"], d["after_year"]) for d in devs if d.get("pair_usable") in (True, "True", 1, 1.0)}
    scored = [d["model"] for d in devs if d.get("model")]
    out: dict[str, Any] = {"cases": len(cells), "usable": len(usable), "pairs": len(devs), "scored": len(scored)}
    if scored:
        sets = sorted({s.get("set") for s in scored})
        out["model"] = {"name": scored[0].get("model"), "set": sets[0] if len(sets) == 1 else "mixed",
                        "all": score_summary(scored), "big": score_summary([s for s in scored if s.get("actual_tco2e") is not None and abs(s["actual_tco2e"]) >= 1000])}
    return out


GRID100_LIMIT = 12000
_GRID100: dict[tuple[str, int], tuple[int, list[tuple[Any, ...]]]] = {}


def _grid100_rows(db: Any, region_code: str, year: int) -> tuple[int, list[tuple[Any, ...]]]:
    """All 100m rows of a region-year, kept in memory and checked against the row count (a re-import replaces them)."""
    count = db.scalar(select(func.count()).select_from(TeamGrid100).where(TeamGrid100.region_code == region_code, TeamGrid100.year == year)) or 0
    hit = _GRID100.get((region_code, year))
    if hit is None or hit[0] != count:
        cols = (TeamGrid100.grid_code, TeamGrid100.x, TeamGrid100.y, TeamGrid100.population, TeamGrid100.population_status,
                TeamGrid100.building_count, TeamGrid100.floor_area_est, TeamGrid100.approval_year, TeamGrid100.zone_class)
        rows = list(db.execute(select(*cols).where(TeamGrid100.region_code == region_code, TeamGrid100.year == year)
                               .order_by(TeamGrid100.y, TeamGrid100.x)).tuples())
        if len(_GRID100) >= 8:
            _GRID100.pop(next(iter(_GRID100)))
        _GRID100[(region_code, year)] = (count, rows)
    return _GRID100[(region_code, year)]


def grid100_features(db: Any, region_code: str | None, year: int, bbox: tuple[float, float, float, float] | None = None,
                     grid500: str | None = None, limit: int = GRID100_LIMIT, meta_only: bool = False) -> dict[str, Any]:
    """국토통계지도 100m cells (팀 수집) for the map: a lon/lat viewport (``bbox``) or one 500m cell (``grid500`` = cell_x_y).

    The newest team year not after ``year`` is used. Only cells with information exist in the source (the rest are absent, not 0).
    Population keeps its status: ``observed`` (6 and more), ``masked`` (1~5명 비공개, value None) or ``empty`` (blank in the
    source — no people or no data, not known; value None). Callers must refuse public-gateway requests (국외 반출 금지)."""
    from pyproj import Transformer
    meta: dict[str, Any] = {"source": SOURCE_NGII, "years": [], "year": None, "cells": 0, "returned": 0, "truncated": False, "reason": None}
    empty = {"type": "FeatureCollection", "features": [], "meta": meta, "summary": None}
    if not region_code:
        meta["reason"] = "지역을 고르지 않았습니다."
        return empty
    try:
        meta["years"] = sorted({int(y) for (y,) in db.execute(select(TeamGrid100.year).where(TeamGrid100.region_code == region_code).distinct())})
    except Exception:  # noqa: BLE001 - table missing (team dataset never imported)
        db.rollback()
        meta["reason"] = "100m 격자 자료(국토통계지도)를 아직 가져오지 않았습니다."
        return empty
    if not meta["years"]:
        meta["reason"] = "이 지역에는 100m 격자 자료(국토통계지도)가 없습니다. 팀 100m 자료는 전주·세종·부산 강서·서울 강동만 있습니다(7차 인계 묶음에는 100m 없음)."
        return empty
    chosen = year_for(meta["years"], year)
    if chosen is None:
        meta["reason"] = f"{year}년 이전의 100m 자료가 없습니다. 가장 이른 자료는 {meta['years'][0]}년입니다."
        return empty
    meta["year"] = chosen
    count, rows = _grid100_rows(db, region_code, chosen)
    meta["cells"] = count
    if meta_only:
        return empty
    if grid500:
        m = re.fullmatch(r"cell_(\d+)_(\d+)", grid500)
        if not m:
            meta["reason"] = "격자 이름이 올바르지 않습니다."
            return empty
        gx, gy = int(m.group(1)), int(m.group(2))
        picked = [r for r in rows if gx <= r[1] < gx + 500 and gy <= r[2] < gy + 500]
    elif bbox:
        to_tm = Transformer.from_crs(4326, 5179, always_xy=True).transform
        w, s, e, n = bbox
        xs, ys = to_tm([w, e, w, e], [s, s, n, n])
        x0, x1, y0, y1 = min(xs) - 100, max(xs), min(ys) - 100, max(ys)
        picked = [r for r in rows if x0 <= r[1] <= x1 and y0 <= r[2] <= y1]
    else:
        picked = list(rows)
    if len(picked) > limit:
        meta["truncated"] = True
        picked = picked[:limit]
    meta["returned"] = len(picked)
    to_ll = Transformer.from_crs(5179, 4326, always_xy=True).transform
    corners_x = [v for r in picked for v in (r[1], r[1] + 100, r[1] + 100, r[1])]
    corners_y = [v for r in picked for v in (r[2], r[2], r[2] + 100, r[2] + 100)]
    lon, lat = to_ll(corners_x, corners_y) if picked else ([], [])
    features = []
    for i, (code, x, y, pop, status, bldg, floor, approval, zone) in enumerate(picked):
        ring = [[round(lon[4 * i + k], 6), round(lat[4 * i + k], 6)] for k in range(4)]
        ring.append(ring[0])
        features.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [ring]}, "properties": {
            "id": code, "x": int(x), "y": int(y), "grid500": f"cell_{int(x) // 500 * 500}_{int(y) // 500 * 500}",
            "population": pop if status == "observed" else None, "population_status": status or "empty",
            "building_count": bldg, "floor_area_m2": floor, "approval_year": int(round(approval)) if approval is not None else None, "zone_class": zone}})
    summary = None
    if grid500:
        def total(values: list[float | None]) -> float | None:
            vals = [v for v in values if v is not None]
            return float(sum(vals)) if vals else None
        props = [f["properties"] for f in features]
        summary = {"cells_with_data": len(props), "population_sum": total([p["population"] for p in props]),
                   "population_cells": sum(1 for p in props if p["population"] is not None),
                   "masked_cells": sum(1 for p in props if p["population_status"] == "masked"),
                   "buildings_sum": total([p["building_count"] for p in props]), "floor_area_sum": total([p["floor_area_m2"] for p in props])}
    return {"type": "FeatureCollection", "features": features, "meta": meta, "summary": summary}


def is_public(request: Any) -> bool:
    """Requests that came through the public demo gateway (deploy/gateway.conf sets the header)."""
    try:
        return (request.headers.get(HEADER_PUBLIC) or "") == "1"
    except Exception:  # noqa: BLE001
        return False
