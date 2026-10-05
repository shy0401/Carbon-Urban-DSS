"""Merge another PC's data bundle into this database without duplicating anything.

A teammate's bundle (scripts\\dss.cmd ExportBundle) is restored by scripts\\dss.ps1 into a throwaway
database on the same PostgreSQL server. This module then copies, table by table, only the rows this
database does not have yet:

* Rows are matched on the table's natural key (primary key, or the unique key for energy_monthly whose
  id is a local sequence). A row already here is never changed, even when the teammate's value differs;
  those rows are counted per column and sampled in the report so the difference can be looked at.
* Only observation tables are merged (MERGE_TABLES). Settings, work products and region preparation
  state (grids, study regions, scenarios, reports, collection jobs, team CSV imports) stay local.
* raw_data_assets rows are merged only when the raw file they point to came with the bundle and the file
  here is that same file (SHA-256 against the bundle's raw-manifest.csv), and their data source is known.
  Records that point to the other PC's response cache, or to a raw file kept local because it differs,
  are left out.

python -m app.merge_bundle --source-db dss_merge_src [--raw-manifest FILE] [--dry-run] [--out FILE]
Credentials are never printed: the report holds table names, counts and key values only.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine, make_url

# Not data values: when a row was fetched or matched, and which stored response it came from.
VOLATILE = frozenset({"collected_at", "matched_at", "created_at", "updated_at", "raw_source_id"})
SAMPLE_LIMIT = 5


@dataclass(frozen=True)
class TableSpec:
    name: str
    key: tuple[str, ...] = ()          # empty → the table's primary key
    omit: tuple[str, ...] = ()         # columns never copied (local sequences)
    ignore: tuple[str, ...] = ()       # columns left out of the "same value?" comparison
    raw_files: bool = False            # raw_data_assets: keep only rows whose file exists here


MERGE_TABLES: tuple[TableSpec, ...] = (
    TableSpec("energy_monthly", key=("sigungu_code", "bjdong_code", "lot_type", "bun", "ji", "use_ym", "energy_type"), omit=("id",)),
    TableSpec("apartment_complexes"),
    TableSpec("national_complexes"),
    TableSpec("complex_grid_mapping"),
    TableSpec("apartment_energy_monthly"),
    TableSpec("building_register", ignore=("reference_period",)),  # reference_period = the day it was fetched
    TableSpec("buildings"),
    TableSpec("cadastral_parcels"),
    TableSpec("parcel_grid"),
    TableSpec("vworld_buildings"),
    TableSpec("vworld_zoning_areas"),
    TableSpec("vworld_special_areas"),
    TableSpec("grid_zoning_stats"),
    TableSpec("vworld_grid_coverage"),
    TableSpec("zoning_ordinances"),
    TableSpec("sgis_admin_boundaries"),
    TableSpec("sgis_population_admin"),
    TableSpec("sgis_household_admin"),
    TableSpec("sgis_grid_cells"),
    TableSpec("sgis_grid_stats"),
    TableSpec("sgis_grid500_values"),
    TableSpec("sgis_official_grid_cells"),
    TableSpec("national_units"),
    TableSpec("admin_units"),
    TableSpec("weather_daily_observations"),
    TableSpec("weather_monthly_observations"),
    TableSpec("weather_monthly"),
    TableSpec("region_weather_monthly"),
    TableSpec("kepco_sigungu_monthly"),
    TableSpec("gir_regional_ghg"),
    TableSpec("citygas_sido_monthly"),
    TableSpec("raw_data_assets", raw_files=True),
)

# Tables that are deliberately not merged, with the reason shown in the report.
LOCAL_ONLY: dict[str, str] = {
    "grid_500m": "격자는 지역 준비로 만듦", "grid_regions": "지역 준비 결과", "regions": "법정동 코드표", "study_regions": "지역 준비 상태",
    "testbed_sectors": "로컬 설정", "data_sources": "로컬 수집 상태", "collection_jobs": "로컬 작업 기록", "collection_job_configs": "로컬 작업 기록",
    "schema_migrations": "스키마 버전", "emission_factors": "배출계수 규칙(로컬 결정)", "scenarios": "작업물", "scenario_results": "작업물",
    "scenario_images": "작업물", "decision_reports": "작업물", "model_runs": "로컬 모델 기록", "upload_batches": "업로드 기록",
    "imported_records": "업로드 기록", "grid_id_mappings": "업로드 기록", "population_grid": "업로드 기록",
    "municipal_apartments": "업로드 기록", "municipal_apartments_under_construction": "업로드 기록", "zoning_areas": "업로드 기록",
    "team_grid500": "팀 CSV 가져오기로만 넣음", "team_grid100": "팀 CSV 가져오기로만 넣음(국토통계지도 반출 금지)",
    "team_developments": "팀 CSV 가져오기로만 넣음", "team_imports": "팀 CSV 가져오기 기록",
}


@dataclass
class Column:
    name: str
    data_type: str
    nullable: bool
    has_default: bool


@dataclass
class TableResult:
    table: str
    status: str = "ok"
    source_rows: int = 0
    matched: int = 0
    identical: int = 0
    differing: int = 0
    differing_columns: dict[str, int] = field(default_factory=dict)
    differing_samples: list[dict[str, Any]] = field(default_factory=list)
    new_rows: int = 0
    inserted: int = 0
    skipped: dict[str, int] = field(default_factory=dict)
    message: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v not in (None, {}, [])}


# --------------------------------------------------------------------------- pure SQL helpers
def q(name: str) -> str:
    """Quote an identifier (column names here come from information_schema, never from users)."""
    return '"' + name.replace('"', '""') + '"'


def key_match(key: Iterable[str], nullable: set[str], left: str = "p", right: str = "s") -> str:
    parts = []
    for c in key:
        op = "IS NOT DISTINCT FROM" if c in nullable else "="
        parts.append(f"{left}.{q(c)} {op} {right}.{q(c)}")
    return " AND ".join(parts)


def differs(col: Column, left: str = "s", right: str = "p") -> str:
    """SQL that is true when the column differs. json has no equality operator; geometry compares as EWKB text."""
    c = q(col.name)
    if col.data_type == "json":
        return f"{left}.{c}::jsonb IS DISTINCT FROM {right}.{c}::jsonb"
    if col.data_type == "USER-DEFINED":
        return f"{left}.{c}::text IS DISTINCT FROM {right}.{c}::text"
    return f"{left}.{c} IS DISTINCT FROM {right}.{c}"


def compared_columns(spec: TableSpec, cols: list[Column], key: Iterable[str]) -> list[Column]:
    skip = set(key) | VOLATILE | set(spec.ignore) | set(spec.omit)
    return [c for c in cols if c.name not in skip]


def missing_required(target: list[Column], copied: Iterable[str]) -> list[str]:
    """NOT NULL target columns without a default that the source cannot fill."""
    have = set(copied)
    return [c.name for c in target if not c.nullable and not c.has_default and c.name not in have]


def raw_file_allowed(location: str | None, data_dir: Path, manifest: dict[str, str]) -> bool:
    """A raw_data_assets row is kept only when it points into data/raw, that file came with the bundle
    (raw-manifest.csv) and the file here is that same file (SHA-256). A file kept local because its
    content differs from the teammate's (a raw conflict) does not get the teammate's record."""
    if not location or not location.startswith("/data/raw/"):
        return False
    relative = location[len("/data/raw/"):]
    if ".." in Path(relative).parts or relative not in manifest:
        return False
    path = data_dir / "raw" / relative
    return path.is_file() and file_sha256(path) == manifest[relative]


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def read_manifest(path: Path | None) -> dict[str, str]:
    """raw-manifest.csv of a bundle (path,bytes,sha256; written by Export-Csv, UTF-8 with BOM)."""
    if not path or not path.is_file():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        return {r["path"].replace("\\", "/"): r["sha256"].lower() for r in csv.DictReader(f) if r.get("path") and r.get("sha256")}


# --------------------------------------------------------------------------- database access
def _columns(conn: Connection, table: str) -> list[Column]:
    rows = conn.execute(text(
        "SELECT column_name, data_type, is_nullable = 'YES', column_default IS NOT NULL FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = :t ORDER BY ordinal_position"), {"t": table}).all()
    return [Column(*r) for r in rows]


def _primary_key(conn: Connection, table: str) -> tuple[str, ...]:
    rows = conn.execute(text(
        "SELECT a.attname FROM pg_index i JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) "
        "WHERE i.indrelid = to_regclass(:t) AND i.indisprimary ORDER BY array_position(i.indkey, a.attnum)"),
        {"t": f"public.{table}"}).scalars().all()
    return tuple(rows)


def _copy_into_temp(src: Connection, dst: Connection, table: str, cols: list[Column]) -> int:
    """Stream the source rows into a session temp table _merge_src (same column types as here)."""
    names = ", ".join(q(c.name) for c in cols)
    dst.execute(text("DROP TABLE IF EXISTS _merge_src"))
    dst.execute(text(f"CREATE TEMP TABLE _merge_src AS SELECT {names} FROM public.{q(table)} WITH NO DATA"))
    src_raw = src.connection.driver_connection
    dst_raw = dst.connection.driver_connection
    with src_raw.cursor() as rc, dst_raw.cursor() as wc:
        with rc.copy(f"COPY (SELECT {names} FROM public.{q(table)}) TO STDOUT") as reader, \
                wc.copy(f"COPY _merge_src ({names}) FROM STDIN") as writer:
            for block in reader:
                writer.write(block)
    return int(dst.execute(text("SELECT count(*) FROM _merge_src")).scalar_one())


def merge_table(src: Connection, dst: Connection, spec: TableSpec, data_dir: Path, dry_run: bool,
                manifest: dict[str, str] | None = None) -> TableResult:
    res = TableResult(spec.name)
    src_cols = {c.name: c for c in _columns(src, spec.name)}
    if not src_cols:
        res.status = "absent"; res.message = "묶음에 없는 표"; return res
    target = _columns(dst, spec.name)
    if not target:
        res.status = "skipped"; res.message = "이 PC 스키마에 없는 표"; return res
    cols = [c for c in target if c.name in src_cols and c.name not in spec.omit]
    unknown = sorted(set(src_cols) - {c.name for c in target})
    lacking = missing_required(target, [c.name for c in cols])
    key = spec.key or _primary_key(dst, spec.name)
    if lacking or not key or not set(key) <= {c.name for c in cols}:
        res.status = "skipped"
        res.message = f"스키마 차이: 필요한 열 없음 {lacking or list(key)}"
        return res
    if unknown:
        res.skipped["source_only_columns"] = len(unknown)
        res.message = "묶음에만 있는 열은 버림: " + ", ".join(unknown)
    nullable = {c.name for c in cols if c.nullable}
    res.source_rows = _copy_into_temp(src, dst, spec.name, cols)
    on = key_match(key, nullable)
    t = f"public.{q(spec.name)}"
    compare = compared_columns(spec, cols, key)
    if compare:
        sums = ", ".join(f"sum(CASE WHEN {differs(c)} THEN 1 ELSE 0 END)" for c in compare)
        anydiff = " OR ".join(differs(c) for c in compare)
        row = dst.execute(text(f"SELECT count(*), sum(CASE WHEN {anydiff} THEN 1 ELSE 0 END), {sums} FROM _merge_src s JOIN {t} p ON {on}")).one()
        res.matched, res.differing = int(row[0]), int(row[1] or 0)
        res.differing_columns = {c.name: int(n) for c, n in zip(compare, row[2:]) if n}
        if res.differing:
            keys = ", ".join(f"s.{q(k)}" for k in key)
            samples = dst.execute(text(f"SELECT {keys} FROM _merge_src s JOIN {t} p ON {on} WHERE {anydiff} LIMIT {SAMPLE_LIMIT}")).all()
            res.differing_samples = [dict(zip(key, map(str, r))) for r in samples]
    else:
        res.matched = int(dst.execute(text(f"SELECT count(*) FROM _merge_src s JOIN {t} p ON {on}")).scalar_one())
    res.identical = res.matched - res.differing
    new_filter = f"NOT EXISTS (SELECT 1 FROM {t} p WHERE {on})"
    res.new_rows = int(dst.execute(text(f"SELECT count(*) FROM _merge_src s WHERE {new_filter}")).scalar_one())
    if spec.raw_files and res.new_rows:
        candidates = dst.execute(text(f"SELECT s.id, s.storage_location, s.source_id IN (SELECT id FROM public.data_sources) FROM _merge_src s WHERE {new_filter}")).all()
        ok = {r[0]: raw_file_allowed(r[1], data_dir, manifest or {}) for r in candidates}
        keep = [r[0] for r in candidates if r[2] and ok[r[0]]]
        res.skipped["no_matching_raw_file"] = sum(1 for r in candidates if not ok[r[0]])
        res.skipped["unknown_source"] = sum(1 for r in candidates if ok[r[0]] and not r[2])
        dst.execute(text("DELETE FROM _merge_src WHERE NOT (id = ANY(:keep))"), {"keep": keep})
    names = ", ".join(q(c.name) for c in cols)
    inserted = dst.execute(text(f"INSERT INTO {t} ({names}) SELECT {names} FROM _merge_src s WHERE {new_filter} ON CONFLICT DO NOTHING"))
    res.inserted = max(int(inserted.rowcount or 0), 0)
    kept_out = res.new_rows - res.inserted - sum(v for k, v in res.skipped.items() if k != "source_only_columns")
    if kept_out > 0:
        res.skipped["other_unique_key"] = kept_out
    dst.execute(text("DROP TABLE IF EXISTS _merge_src"))
    if dry_run:
        res.status = "dry-run"
    res.skipped = {k: v for k, v in res.skipped.items() if v}
    return res


def merge(source_url: str, target_url: str, data_dir: Path, dry_run: bool = False,
          tables: Iterable[TableSpec] = MERGE_TABLES, raw_manifest: Path | None = None) -> dict[str, Any]:
    src_engine: Engine = create_engine(source_url)
    dst_engine: Engine = create_engine(target_url)
    results: list[dict[str, Any]] = []
    manifest = read_manifest(raw_manifest)
    try:
        with src_engine.connect() as src:
            src_tables = set(src.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")).scalars())
            for spec in tables:
                with dst_engine.connect() as dst:
                    trans = dst.begin()
                    try:
                        r = merge_table(src, dst, spec, data_dir, dry_run, manifest)
                        trans.rollback() if dry_run else trans.commit()
                    except Exception as exc:  # one table failing never leaves a half-merged table
                        trans.rollback()
                        r = TableResult(spec.name, status="error", message=f"{type(exc).__name__}: {str(exc).splitlines()[0][:300]}")
                    results.append(r.as_dict())
            local_only = {name: why for name, why in LOCAL_ONLY.items() if name in src_tables}
            unlisted = sorted(src_tables - {s.name for s in MERGE_TABLES} - set(LOCAL_ONLY) - {"spatial_ref_sys"})
    finally:
        src_engine.dispose(); dst_engine.dispose()
    totals = {k: sum(r.get(k, 0) for r in results) for k in ("source_rows", "matched", "identical", "differing", "new_rows", "inserted")}
    return {"dry_run": dry_run, "totals": totals, "tables": results, "not_merged": local_only, "unlisted_tables": unlisted,
            "rule": "기존 행은 바꾸지 않고, 자연 키로 없는 행만 넣음"}


def database_url(name: str, base: str | None = None) -> str:
    url = make_url(base or os.getenv("DATABASE_URL", "postgresql+psycopg://carbon:carbon_local@localhost:5432/carbon"))
    return url.set(database=name).render_as_string(hide_password=False)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--source-db", help="database on the same server holding the restored bundle")
    p.add_argument("--list-tables", action="store_true", help="print the merged table names (for pg_restore -t) and exit")
    p.add_argument("--dry-run", action="store_true", help="compare and count only; nothing is written")
    p.add_argument("--raw-manifest", help="the bundle's raw-manifest.csv (needed to merge raw_data_assets)")
    p.add_argument("--out")
    args = p.parse_args(argv)
    if args.list_tables:
        print("\n".join(s.name for s in MERGE_TABLES))
        return 0
    if not args.source_db:
        p.error("--source-db is required")
    if args.source_db in {"carbon", make_url(os.getenv("DATABASE_URL", "postgresql+psycopg://x@y/carbon")).database}:
        print("source database must differ from this database", file=sys.stderr)
        return 2
    report = merge(database_url(args.source_db), os.getenv("DATABASE_URL", database_url("carbon")),
                   Path(os.getenv("DATA_DIR", "/data")), dry_run=args.dry_run,
                   raw_manifest=Path(args.raw_manifest) if args.raw_manifest else None)
    body = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    if args.out:
        out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True); out.write_text(body, encoding="utf-8")
    print(body)
    return 1 if any(r["status"] == "error" for r in report["tables"]) else 0


if __name__ == "__main__":
    sys.exit(main())
