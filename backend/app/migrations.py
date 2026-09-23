"""Small versioned schema migrations applied after ``create_all``.

``create_all`` creates missing tables but never alters existing ones. Every
schema change to an existing table must be added here as a new, idempotent
version so every team PC and restored backup converges to the same schema.
Applied versions are recorded in ``schema_migrations``.
"""
from __future__ import annotations

from sqlalchemy import text

MIGRATIONS: list[tuple[str, list[str]]] = [
    ("2026092301_baseline", []),
    ("2026092302_energy_grid_month_index", [
        "CREATE INDEX IF NOT EXISTS ix_energy_monthly_grid_ym ON energy_monthly (grid_id, use_ym)",
    ]),
]


def apply_migrations(engine) -> list[str]:
    applied: list[str] = []
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        ))
        # Serialize concurrent API/worker startups.
        connection.execute(text("SELECT pg_advisory_xact_lock(2026092301)"))
        done = {row[0] for row in connection.execute(text("SELECT version FROM schema_migrations"))}
        for version, statements in MIGRATIONS:
            if version in done:
                continue
            for statement in statements:
                connection.execute(text(statement))
            connection.execute(text("INSERT INTO schema_migrations (version) VALUES (:version)"), {"version": version})
            applied.append(version)
    return applied
