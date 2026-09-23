"""Operator commands used by scripts/dss.ps1. Never prints credential values.

python -m app.ops status [--out FILE]
python -m app.ops run --dataset sgis --scope smoke
python -m app.ops staged --dataset vworld_zoning [--max-scope full]
python -m app.ops probe sgis|vworld [--out FILE]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select, text

from .settings import DATA_DIR, DEFAULT_YEAR, offline_mode

SCOPES = ["smoke", "limited", "full"]
# Maximum automatic scope. Cadastral parcels are numerous; full needs an explicit opt-in.
MAX_SCOPE = {"sgis": "full", "vworld_zoning": "full", "vworld_cadastral": "limited", "kapt_energy": "full", "kma_asos": "full", "energy": "limited"}
CREDENTIALS = ["DATA_GO_KR_SERVICE_KEY", "SGIS_CONSUMER_KEY", "SGIS_CONSUMER_SECRET", "VWORLD_API_KEY", "VWORLD_DOMAIN"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _init() -> None:
    from .cli import init_tables
    init_tables()


def table_counts(db: Any) -> dict[str, int]:
    names = [row[0] for row in db.execute(text(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='public' "
        "AND table_type='BASE TABLE' AND table_name <> 'spatial_ref_sys' ORDER BY table_name"))]
    return {name: int(db.execute(text(f'SELECT count(*) FROM "{name}"')).scalar() or 0) for name in names}


def credential_status() -> list[dict[str, Any]]:
    from .collection_preflight import credential_format_problem
    rows = []
    for name in CREDENTIALS:
        value = os.getenv(name, "")
        rows.append({"name": name, "configured": bool(value.strip()), "format_problem": credential_format_problem(name, value)})
    return rows


def raw_summary(root: Path | None = None) -> dict[str, Any]:
    raw = (root or DATA_DIR) / "raw"
    files = sorted(path for path in raw.rglob("*") if path.is_file()) if raw.exists() else []
    digest = hashlib.sha256()
    by_folder: dict[str, int] = {}
    total = 0
    for path in files:
        relative = path.relative_to(raw).as_posix()
        size = path.stat().st_size
        total += size
        folder = relative.split("/", 1)[0] if "/" in relative else "."
        by_folder[folder] = by_folder.get(folder, 0) + 1
        digest.update(relative.encode() + b"\0" + hashlib.sha256(path.read_bytes()).hexdigest().encode() + b"\n")
    return {"files": len(files), "bytes": total, "by_folder": by_folder, "aggregate_sha256": digest.hexdigest()}


def status() -> dict[str, Any]:
    _init()
    from .db import Session
    from .readiness import build_readiness
    with Session() as db:
        readiness = build_readiness(db)
        counts = table_counts(db)
        postgis = db.execute(text("SELECT PostGIS_Version()")).scalar()
        migrations = [row[0] for row in db.execute(text("SELECT version FROM schema_migrations ORDER BY version"))]
    return {
        "generated_at": _now(), "offline_mode": offline_mode(), "postgis": postgis, "migrations": migrations,
        "table_counts": counts, "raw": raw_summary(), "credentials": credential_status(),
        "readiness": {
            "summary": readiness["summary"],
            "sources": [{key: item.get(key) for key in ("id", "state", "status", "normalized_rows", "raw_rows", "reference_period", "blocker", "collectable_now")} for item in readiness["sources"]],
            "replaced_sources": readiness.get("replaced_sources", []),
        },
    }


def run_dataset(dataset: str, scope: str, year: int = DEFAULT_YEAR) -> dict[str, Any]:
    """Run one collection synchronously through the same code path as the worker."""
    _init()
    from .catalog import seed_sources
    from .collection_preflight import collection_blockers
    from .db import Session
    from .models import CollectionJob, CollectionJobConfig, DataSource
    from .service import serialize
    from .tasks import run_collection

    started = _now()
    if offline_mode():
        return {"dataset": dataset, "scope": scope, "status": "BLOCKED", "blockers": [{"dataset": dataset, "message": "오프라인 모드"}], "started_at": started}
    with Session() as db:
        seed_sources(db)
        blockers = collection_blockers([dataset])
        if blockers:
            return {"dataset": dataset, "scope": scope, "status": "BLOCKED", "blockers": blockers, "started_at": started}
        running = db.scalar(select(CollectionJob).where(CollectionJob.status.in_(["QUEUED", "RUNNING"])))
        if running:
            age = datetime.now(timezone.utc) - running.created_at
            if age < timedelta(hours=3):
                return {"dataset": dataset, "scope": scope, "status": "BUSY", "running_job": running.id, "started_at": started}
            running.status = "FAILED";running.message = "3시간 이상 끝나지 않은 작업을 운영 명령이 종료 처리";running.finished_at = datetime.now(timezone.utc)
            db.commit()
        job = CollectionJob(id=str(uuid.uuid4()), datasets=[dataset], start_month=f"{year}-01", end_month=f"{year}-12")
        db.add(job);db.flush();db.add(CollectionJobConfig(job_id=job.id, scope=scope));db.commit()
        job_id = job.id
    run_collection(job_id)
    with Session() as db:
        job = db.get(CollectionJob, job_id)
        source_id = {"kma_asos": "weather_kma", "sgis": "sgis_admin"}.get(dataset, dataset)
        source = db.get(DataSource, source_id)
        return {
            "dataset": dataset, "scope": scope, "status": job.status, "errors": job.errors, "message": job.message,
            "job_id": job_id, "started_at": started, "finished_at": _now(),
            "source": {key: value for key, value in serialize(source).items() if key in ("status", "normalized_row_count", "raw_row_count", "missing_count", "quality", "reference_period")} if source else None,
        }


def staged(dataset: str, max_scope: str | None = None, year: int = DEFAULT_YEAR) -> dict[str, Any]:
    """SMOKE → LIMITED → FULL. Stop at the first step that is not SUCCESS."""
    limit = SCOPES.index(max_scope or MAX_SCOPE.get(dataset, "limited"))
    steps = []
    for scope in SCOPES[: limit + 1]:
        result = run_dataset(dataset, scope, year)
        steps.append(result)
        if result["status"] != "SUCCESS":
            break
    final = steps[-1]["status"] if steps else "NOT_RUN"
    return {"dataset": dataset, "final_status": final, "reached_scope": steps[-1]["scope"] if steps else None, "steps": steps}


# ---------------------------------------------------------------------------
# Probes: minimal real requests; output is a sanitized structural summary.

def _keys(value: Any) -> list[str]:
    return sorted(value.keys()) if isinstance(value, dict) else []


def _coordinate_sample(geometry: dict[str, Any] | None) -> list[float] | None:
    coords = (geometry or {}).get("coordinates")
    while isinstance(coords, list) and coords and isinstance(coords[0], list):
        coords = coords[0]
    return [round(float(value), 1) for value in coords[:2]] if isinstance(coords, list) and coords else None


def probe_sgis() -> dict[str, Any]:
    from .sgis import SGIS_BASE_URL, SgisTokenManager
    base = os.getenv("SGIS_BASE_URL", SGIS_BASE_URL).rstrip("/")
    report: dict[str, Any] = {"provider": "SGIS", "checked_at": _now(), "steps": []}
    client = httpx.Client(timeout=30, follow_redirects=True)
    try:
        manager = SgisTokenManager(os.getenv("SGIS_CONSUMER_KEY", "").strip(), os.getenv("SGIS_CONSUMER_SECRET", "").strip(), requester=client)
        token = manager.get_token()
        report["steps"].append({"step": "auth", "ok": True})
    except Exception as exc:  # sanitized: collectors never include secrets in messages
        report["steps"].append({"step": "auth", "ok": False, "error": str(exc)[:200]})
        return report
    found = None
    for year in range(int(os.getenv("SGIS_BASE_YEAR", "2024")), 2018, -1):
        response = client.get(f"{base}/stats/searchpopulation.json", params={"accessToken": token, "year": year})
        payload = response.json()
        rows = payload.get("result") or []
        report["steps"].append({"step": f"sido-population-{year}", "http": response.status_code, "errCd": payload.get("errCd"), "rows": len(rows), "row_keys": _keys(rows[0]) if rows else [], "names": [row.get("adm_nm") for row in rows][:20]})
        province = next((row for row in rows if any(key in str(row.get("adm_nm")) for key in ("전북", "전라북도"))), None)
        if province:
            found = (year, province)
            break
    if not found:
        return report
    year, province = found
    response = client.get(f"{base}/stats/searchpopulation.json", params={"accessToken": token, "year": year, "adm_cd": province.get("adm_cd"), "low_search": 1})
    payload = response.json();rows = payload.get("result") or []
    jeonju = [row for row in rows if "전주" in str(row.get("adm_nm"))]
    report["steps"].append({"step": "sigungu-population", "year": year, "province_code": province.get("adm_cd"), "errCd": payload.get("errCd"), "rows": len(rows), "jeonju": [{"adm_cd": row.get("adm_cd"), "adm_nm": row.get("adm_nm"), "population": row.get("population")} for row in jeonju]})
    if jeonju:
        code = jeonju[0].get("adm_cd")
        response = client.get(f"{base}/stats/searchpopulation.json", params={"accessToken": token, "year": year, "adm_cd": code, "low_search": 1})
        payload = response.json();rows = payload.get("result") or []
        report["steps"].append({"step": "dong-population", "adm_cd": code, "errCd": payload.get("errCd"), "rows": len(rows), "sample": rows[:3]})
        response = client.get(f"{base}/stats/household.json", params={"accessToken": token, "year": year, "adm_cd": code, "low_search": 1})
        payload = response.json();rows = payload.get("result") or []
        report["steps"].append({"step": "dong-household", "adm_cd": code, "errCd": payload.get("errCd"), "rows": len(rows), "row_keys": _keys(rows[0]) if rows else []})
        response = client.get(f"{base}/boundary/hadmarea.geojson", params={"accessToken": token, "year": year, "adm_cd": code, "low_search": 1})
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        features = payload.get("features") or []
        report["steps"].append({"step": "dong-boundary", "adm_cd": code, "http": response.status_code, "errCd": payload.get("errCd"), "top_keys": _keys(payload), "features": len(features), "property_keys": _keys((features[0] or {}).get("properties")) if features else [], "coordinate_sample": _coordinate_sample(features[0].get("geometry")) if features else None})
    return report


AUTH_ERRORS = {"INCORRECT_KEY", "INVALID_KEY", "UNAVAILABLE_KEY"}
DOMAIN_VARIANTS = ["http://localhost", "localhost", "http://127.0.0.1", "http://localhost:5173", "http://localhost:8000", "https://localhost", "none"]


def _vworld_request(client: httpx.Client, url: str, key: str, layer: dict[str, Any], bounds: tuple[float, float, float, float], domain: str, size: int = 10) -> dict[str, Any]:
    from .vworld import bbox_filter
    params = {"service": "data", "version": "2.0", "request": "GetFeature", "key": key, "format": "json", "size": size, "page": 1,
              "data": layer["dataset_id"], "geomFilter": bbox_filter(bounds), "geometry": "true", "attribute": "true", "crs": layer["source_crs"]}
    if domain.lower() not in {"none", "-"}:
        params["domain"] = domain
    response = client.get(url, params=params)
    try:
        payload = response.json()
    except ValueError:
        return {"http": response.status_code, "status": "NOT_JSON", "body_start": response.text.replace(key, "[REDACTED]")[:200]}
    body = payload.get("response", payload)
    features = (((body.get("result") or {}).get("featureCollection")) or {}).get("features") or []
    error = body.get("error") if isinstance(body.get("error"), dict) else None
    return {
        "http": response.status_code, "status": body.get("status"),
        "error": {"code": error.get("code"), "text": str(error.get("text"))[:200]} if error else None,
        "record": body.get("record"), "page": body.get("page"), "features": len(features),
        "property_keys": _keys(features[0].get("properties")) if features else [],
        "sample_properties": {k: v for k, v in (features[0].get("properties") or {}).items() if k in ("uname", "ucode", "pnu", "jibun", "sido_name", "sigg_name")} if features else {},
        "coordinate_sample": _coordinate_sample(features[0].get("geometry")) if features else None,
    }


def probe_vworld() -> dict[str, Any]:
    """Minimal VWorld requests. If the configured domain is rejected, try common
    development domains to find the one registered with the key (values of the key
    itself are never written)."""
    from geoalchemy2.shape import to_shape
    from .db import Session
    from .models import Grid
    from .vworld import VWORLD_API_URL, load_layer_config
    _init()
    configured = os.getenv("VWORLD_DOMAIN", "http://localhost").strip() or "http://localhost"
    report: dict[str, Any] = {"provider": "VWorld", "checked_at": _now(), "configured_domain": configured, "working_domain": None, "steps": []}
    key = os.getenv("VWORLD_API_KEY", "").strip()
    with Session() as db:
        grid = db.scalar(select(Grid).order_by(Grid.id).limit(1))
        bounds = to_shape(grid.geom).bounds if grid else None
    if not bounds:
        report["steps"].append({"step": "grid", "ok": False, "error": "분석격자 없음"})
        return report
    config = load_layer_config()
    url = os.getenv("VWORLD_DATA_URL", VWORLD_API_URL)
    client = httpx.Client(timeout=30, follow_redirects=True)
    for domain in [configured] + [variant for variant in DOMAIN_VARIANTS if variant != configured]:
        result = _vworld_request(client, url, key, config["zoning"], bounds, domain)
        report["steps"].append({"step": "zoning", "domain": domain, "grid_id": grid.id, **result})
        code = (result.get("error") or {}).get("code")
        if result.get("status") in ("OK", "NOT_FOUND") or (result.get("status") == "ERROR" and code not in AUTH_ERRORS):
            # The key/domain pair was accepted even if the request itself failed for another reason.
            report["working_domain"] = domain
            report["key_accepted"] = True
            break
    if report["working_domain"]:
        result = _vworld_request(client, url, key, config["cadastral"], bounds, report["working_domain"])
        report["steps"].append({"step": "cadastral", "domain": report["working_domain"], "grid_id": grid.id, **result})
    return report


REJECTION_CACHES = {"vworld": ["cache/vworld"], "sgis": ["cache/sgis", "cache/sgis-auth"], "data_go_kr": ["cache/kapt-energy", "cache/kma-asos", "cache"]}


def clear_rejections(provider: str, root: Path | None = None) -> dict[str, Any]:
    """Forget cached *rejections* (never successful responses) so a provider can be
    retried immediately after the account owner fixed the key registration."""
    base = root or DATA_DIR
    removed = 0
    for relative in REJECTION_CACHES[provider]:
        folder = base / relative
        if not folder.exists():
            continue
        for meta_path in folder.glob("*.json"):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if meta.get("error"):
                meta_path.unlink(missing_ok=True)
                meta_path.with_suffix(".body").unlink(missing_ok=True)
                removed += 1
    return {"provider": provider, "removed_rejections": removed, "checked_at": _now()}


def _redact(value: str) -> str:
    for name in CREDENTIALS:
        secret = os.getenv(name, "").strip()
        if name != "VWORLD_DOMAIN" and len(secret) >= 6:
            value = value.replace(secret, "[REDACTED]")
    return value


def _write(payload: dict[str, Any], out: str | None) -> None:
    text_value = _redact(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    if out:
        path = Path(out);path.parent.mkdir(parents=True, exist_ok=True);path.write_text(text_value, encoding="utf-8")
    print(text_value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.ops")
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("status");s.add_argument("--out")
    r = sub.add_parser("run");r.add_argument("--dataset", required=True);r.add_argument("--scope", choices=SCOPES, default="smoke");r.add_argument("--year", type=int, default=DEFAULT_YEAR);r.add_argument("--out")
    st = sub.add_parser("staged");st.add_argument("--dataset", required=True);st.add_argument("--max-scope", choices=SCOPES);st.add_argument("--year", type=int, default=DEFAULT_YEAR);st.add_argument("--out")
    p = sub.add_parser("probe");p.add_argument("provider", choices=["sgis", "vworld"]);p.add_argument("--out")
    c = sub.add_parser("clear-rejections");c.add_argument("provider", choices=sorted(REJECTION_CACHES));c.add_argument("--out")
    args = parser.parse_args(argv)
    if args.command == "status":
        _write(status(), args.out);return 0
    if args.command == "run":
        result = run_dataset(args.dataset, args.scope, args.year);_write(result, args.out)
        return 0 if result["status"] == "SUCCESS" else 2
    if args.command == "staged":
        result = staged(args.dataset, args.max_scope, args.year);_write(result, args.out)
        return 0 if result["final_status"] == "SUCCESS" else 2
    if args.command == "clear-rejections":
        _write(clear_rejections(args.provider), args.out);return 0
    if args.command == "probe":
        _write(probe_sgis() if args.provider == "sgis" else probe_vworld(), args.out);return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
