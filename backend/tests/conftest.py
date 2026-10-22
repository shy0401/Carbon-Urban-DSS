"""Shared fixtures.

Tests that go through the API create scenarios, decision reports and collection jobs in the real database
(there is no test database). The session fixture below remembers the ids that existed before the run and deletes
only the rows that appeared during it, so a test run leaves no rows behind (DATA_STANDARD 7절: 작업물 표에 시험 행을
남기지 않는다). Rows that existed before are never touched. Without a reachable database nothing happens.
"""
from __future__ import annotations

import pytest

# child rows first, then the rows they point at
TABLES = ["scenario_images", "scenario_results", "scenarios", "decision_reports", "collection_jobs"]


def _ids(db, table: str) -> set[str]:
    from sqlalchemy import text
    column = "scenario_id" if table == "scenario_images" else "id"
    return {str(value) for (value,) in db.execute(text(f"SELECT {column} FROM {table}"))}


@pytest.fixture(scope="session", autouse=True)
def leave_no_rows_behind():
    try:
        from app.db import Session
        with Session() as db:
            before = {table: _ids(db, table) for table in TABLES}
    except Exception:  # noqa: BLE001 - no database here (pure unit-test run): nothing to clean
        yield
        return
    yield
    try:
        from sqlalchemy import text
        with Session() as db:
            removed: dict[str, int] = {}
            for table in TABLES:
                column = "scenario_id" if table == "scenario_images" else "id"
                new = _ids(db, table) - before[table]
                if not new:
                    continue
                db.execute(text(f"DELETE FROM {table} WHERE {column} = ANY(:ids)"), {"ids": sorted(new)})
                removed[table] = len(new)
            db.commit()
        if removed:
            print("\n[conftest] removed rows created by this test run: " + ", ".join(f"{k} {v}" for k, v in removed.items()))
    except Exception as exc:  # noqa: BLE001 - never fail the run on cleanup; say what was left
        print(f"\n[conftest] cleanup skipped: {type(exc).__name__}: {exc}")
