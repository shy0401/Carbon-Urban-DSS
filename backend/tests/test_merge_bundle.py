"""Bundle merge: natural-key matching, never overwriting local rows, raw-file provenance rule.

The SQL helpers are tested without a database. The end-to-end test needs a PostgreSQL server where it
may create two throwaway databases; it runs only when MERGE_TEST_ADMIN_URL is set, e.g.
MERGE_TEST_ADMIN_URL=postgresql+psycopg://carbon@/postgres?host=/tmp/pg&port=55432
"""
import os
import uuid
from pathlib import Path

import pytest

from app import merge_bundle as mb
from app.merge_bundle import Column, TableSpec


def test_key_match_uses_null_safe_comparison_only_for_nullable_columns():
    sql = mb.key_match(["code", "ym"], {"ym"})
    assert sql == 'p."code" = s."code" AND p."ym" IS NOT DISTINCT FROM s."ym"'


def test_json_and_geometry_columns_are_compared_through_a_cast():
    assert mb.differs(Column("raw_record", "json", True, False)) == 's."raw_record"::jsonb IS DISTINCT FROM p."raw_record"::jsonb'
    assert mb.differs(Column("geom", "USER-DEFINED", True, False)) == 's."geom"::text IS DISTINCT FROM p."geom"::text'
    assert mb.differs(Column("usage_kwh", "double precision", True, False)) == 's."usage_kwh" IS DISTINCT FROM p."usage_kwh"'


def test_compared_columns_leave_out_keys_volatile_ignored_and_omitted_columns():
    spec = TableSpec("building_register", ignore=("reference_period",), omit=("seq",))
    cols = [Column(n, "text", True, False) for n in ("id", "approval_year", "reference_period", "collected_at", "seq", "grid_id")]
    assert [c.name for c in mb.compared_columns(spec, cols, ("id",))] == ["approval_year", "grid_id"]


def test_missing_required_lists_not_null_columns_without_default_that_the_source_lacks():
    target = [Column("id", "integer", False, True), Column("code", "text", False, False), Column("note", "text", True, False)]
    assert mb.missing_required(target, ["note"]) == ["code"]
    assert mb.missing_required(target, ["code"]) == []


def test_raw_asset_kept_only_when_the_bundle_file_is_the_file_here(tmp_path: Path):
    f = tmp_path / "raw" / "kapt-energy" / "2021" / "A1" / "202101.json"
    f.parent.mkdir(parents=True)
    f.write_text("{}", encoding="utf-8")
    other = tmp_path / "raw" / "sgis" / "b.json"
    other.parent.mkdir(parents=True)
    other.write_text("local version", encoding="utf-8")
    manifest = {"kapt-energy/2021/A1/202101.json": mb.file_sha256(f), "sgis/b.json": "0" * 64,
                "kapt-energy/2021/A1/202102.json": "1" * 64}
    assert mb.raw_file_allowed("/data/raw/kapt-energy/2021/A1/202101.json", tmp_path, manifest)
    assert not mb.raw_file_allowed("/data/raw/sgis/b.json", tmp_path, manifest)                    # kept local (differs)
    assert not mb.raw_file_allowed("/data/raw/kapt-energy/2021/A1/202102.json", tmp_path, manifest)  # listed, not here
    assert not mb.raw_file_allowed("/data/raw/kapt-energy/2021/A1/202101.json", tmp_path, {})       # no manifest
    assert not mb.raw_file_allowed("/data/cache/abc.body", tmp_path, manifest)                      # other PC's cache
    assert not mb.raw_file_allowed("/data/raw/../.env", tmp_path, manifest)
    assert not mb.raw_file_allowed(None, tmp_path, manifest)


def test_read_manifest_accepts_windows_paths_and_bom(tmp_path: Path):
    m = tmp_path / "raw-manifest.csv"
    m.write_text('\ufeff"path","bytes","sha256"\n"kapt-energy\\2021\\A1\\202101.json","2","ABC"\n', encoding="utf-8")
    assert mb.read_manifest(m) == {"kapt-energy/2021/A1/202101.json": "abc"}
    assert mb.read_manifest(tmp_path / "missing.csv") == {}


def test_merge_lists_cover_every_table_once_and_keep_work_products_local():
    names = [s.name for s in mb.MERGE_TABLES]
    assert len(names) == len(set(names))
    assert not set(names) & set(mb.LOCAL_ONLY)
    for local in ("scenarios", "decision_reports", "grid_500m", "study_regions", "team_grid100", "emission_factors"):
        assert local in mb.LOCAL_ONLY
    energy = next(s for s in mb.MERGE_TABLES if s.name == "energy_monthly")
    assert energy.omit == ("id",) and "use_ym" in energy.key


def test_database_url_swaps_only_the_database_name():
    url = mb.database_url("dss_merge_src", "postgresql+psycopg://carbon:pw@postgres:5432/carbon")
    assert url == "postgresql+psycopg://carbon:pw@postgres:5432/dss_merge_src"


SCHEMA = """
CREATE TABLE data_sources (id varchar PRIMARY KEY);
CREATE TABLE energy_monthly (id serial PRIMARY KEY, source varchar NOT NULL, sigungu_code varchar NOT NULL, bjdong_code varchar NOT NULL,
  lot_type varchar NOT NULL, bun varchar NOT NULL, ji varchar NOT NULL, use_ym varchar NOT NULL, energy_type varchar NOT NULL,
  usage_kwh double precision, raw_record json NOT NULL, collected_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (sigungu_code, bjdong_code, lot_type, bun, ji, use_ym, energy_type));
CREATE TABLE apartment_energy_monthly (id varchar PRIMARY KEY, complex_code varchar NOT NULL, year_month varchar NOT NULL, source varchar NOT NULL,
  electricity_quantity double precision, quality_status varchar NOT NULL, UNIQUE (complex_code, year_month, source));
CREATE TABLE raw_data_assets (id varchar PRIMARY KEY, source_id varchar NOT NULL REFERENCES data_sources(id), storage_location text NOT NULL);
CREATE TABLE scenarios (id varchar PRIMARY KEY, name text);
"""


@pytest.mark.skipif(not os.getenv("MERGE_TEST_ADMIN_URL"), reason="needs a PostgreSQL server (MERGE_TEST_ADMIN_URL)")
def test_merge_inserts_only_missing_rows_and_never_changes_local_ones(tmp_path: Path):
    from sqlalchemy import create_engine, text
    admin_url = os.environ["MERGE_TEST_ADMIN_URL"]
    tag = uuid.uuid4().hex[:8]
    src_db, dst_db = f"merge_t_src_{tag}", f"merge_t_dst_{tag}"
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f"CREATE DATABASE {src_db}")); c.execute(text(f"CREATE DATABASE {dst_db}"))
    src_url, dst_url = mb.database_url(src_db, admin_url), mb.database_url(dst_db, admin_url)
    try:
        for url in (src_url, dst_url):
            with create_engine(url).begin() as c:
                c.exec_driver_sql(SCHEMA)
                c.execute(text("INSERT INTO data_sources VALUES ('kapt_energy')"))
        with create_engine(dst_url).begin() as c:  # local: one shared row, one row the teammate has with another value
            c.execute(text("INSERT INTO energy_monthly (source,sigungu_code,bjdong_code,lot_type,bun,ji,use_ym,energy_type,usage_kwh,raw_record) VALUES "
                           "('HUB','52111','12800','0','0001','0002','202501','ELECTRICITY',100,'{\"a\": 1, \"b\": 2}'),"
                           "('HUB','52111','12800','0','0001','0002','202502','ELECTRICITY',200,'{}')"))
            c.execute(text("INSERT INTO apartment_energy_monthly VALUES ('A1:202201:K-apt','A1','202201','K-apt',5,'SUCCESS')"))
            c.execute(text("INSERT INTO scenarios VALUES ('mine','local plan')"))
        with create_engine(src_url).begin() as c:  # teammate: same + differing + new rows, ids from its own sequence
            c.execute(text("SELECT setval('energy_monthly_id_seq', 500)"))
            c.execute(text("INSERT INTO energy_monthly (source,sigungu_code,bjdong_code,lot_type,bun,ji,use_ym,energy_type,usage_kwh,raw_record) VALUES "
                           "('HUB','52111','12800','0','0001','0002','202501','ELECTRICITY',100,'{\"b\": 2, \"a\": 1}'),"
                           "('HUB','52111','12800','0','0001','0002','202502','ELECTRICITY',999,'{}'),"
                           "('HUB','52111','12800','0','0001','0002','202503','ELECTRICITY',NULL,'{}')"))
            c.execute(text("INSERT INTO apartment_energy_monthly VALUES ('A1:202201:K-apt','A1','202201','K-apt',5,'SUCCESS'),"
                           "('A1:202101:K-apt','A1','202101','K-apt',7,'SUCCESS'),('A1:202102:K-apt','A1','202102','K-apt',NULL,'NOT_REPORTED')"))
            c.execute(text("INSERT INTO raw_data_assets VALUES ('r1','kapt_energy','/data/raw/kapt-energy/2021/A1/202101.json'),"
                           "('r2','kapt_energy','/data/cache/x.body'),('r3','kapt_energy','/data/raw/kapt-energy/2021/A1/202199.json')"))
            c.execute(text("INSERT INTO scenarios VALUES ('theirs','teammate plan')"))
        raw = tmp_path / "raw" / "kapt-energy" / "2021" / "A1"; raw.mkdir(parents=True); (raw / "202101.json").write_text("{}")
        manifest = tmp_path / "raw-manifest.csv"
        manifest.write_text('"path","bytes","sha256"\n"kapt-energy/2021/A1/202101.json","2","' + mb.file_sha256(raw / "202101.json") + '"\n', encoding="utf-8")
        specs = [s for s in mb.MERGE_TABLES if s.name in ("energy_monthly", "apartment_energy_monthly", "raw_data_assets")]

        dry = mb.merge(src_url, dst_url, tmp_path, dry_run=True, tables=specs, raw_manifest=manifest)
        assert dry["totals"]["inserted"] == 4
        with create_engine(dst_url).connect() as c:
            assert c.execute(text("SELECT count(*) FROM energy_monthly")).scalar_one() == 2  # dry run wrote nothing

        report = mb.merge(src_url, dst_url, tmp_path, tables=specs, raw_manifest=manifest)
        by = {r["table"]: r for r in report["tables"]}
        e = by["energy_monthly"]
        assert (e["source_rows"], e["matched"], e["identical"], e["differing"], e["inserted"]) == (3, 2, 1, 1, 1)
        assert e["differing_columns"] == {"usage_kwh": 1}          # json key order alone is not a difference
        assert e["differing_samples"][0]["use_ym"] == "202502"
        a = by["apartment_energy_monthly"]
        assert (a["matched"], a["identical"], a["inserted"]) == (1, 1, 2)
        r = by["raw_data_assets"]
        assert r["inserted"] == 1 and r["skipped"] == {"no_matching_raw_file": 2}
        assert "scenarios" in report["not_merged"]
        with create_engine(dst_url).connect() as c:
            assert c.execute(text("SELECT usage_kwh FROM energy_monthly WHERE use_ym='202502'")).scalar_one() == 200  # local value kept
            assert c.execute(text("SELECT usage_kwh IS NULL FROM energy_monthly WHERE use_ym='202503'")).scalar_one()  # NULL stays NULL, not 0
            assert c.execute(text("SELECT max(id) FROM energy_monthly")).scalar_one() < 500  # local sequence, not the teammate's ids (501+)
            assert c.execute(text("SELECT count(*) FROM scenarios")).scalar_one() == 1
            assert c.execute(text("SELECT quality_status FROM apartment_energy_monthly WHERE year_month='202102'")).scalar_one() == "NOT_REPORTED"

        again = mb.merge(src_url, dst_url, tmp_path, tables=specs, raw_manifest=manifest)   # idempotent
        assert again["totals"]["inserted"] == 0
    finally:
        with admin.connect() as c:
            c.execute(text(f"DROP DATABASE IF EXISTS {src_db} WITH (FORCE)")); c.execute(text(f"DROP DATABASE IF EXISTS {dst_db} WITH (FORCE)"))
        admin.dispose()
