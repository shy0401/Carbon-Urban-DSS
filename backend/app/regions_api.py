"""/api/regions: 전국 행정구역 목록, 전국 개요 지도, 분석 지역 준비."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from .db import Session
from .regions import DEFAULT_REGION, AdminUnit, StudyRegion, catalog, region_summary, short_name

router = APIRouter(prefix="/api/regions", tags=["regions"])

Step = Literal["grid", "sgis_admin", "complexes", "weather", "zoning", "zoning_other", "special_areas", "ordinance", "buildings", "cadastral",
               "register", "building_energy", "kapt_energy", "finalize"]


def _count(db: Any, model: Any, *where: Any) -> int:
    try:
        return db.scalar(select(func.count()).select_from(model).where(*where)) or 0
    except Exception:  # noqa: BLE001 - optional table
        db.rollback()
        return 0


def national_meta(db: Any) -> dict[str, Any]:
    """What of the national base layers is in the database (counts only, no external calls)."""
    from .models import DataSource
    from .national import NationalComplex, NationalUnit
    from .sgis_grid import SgisGridCell, latest_year
    from .sgis_grid_official import SgisOfficialGridCell
    year = None
    try:
        year = db.scalar(select(func.max(NationalUnit.year)))
    except Exception:  # noqa: BLE001
        db.rollback()
    grid_year = latest_year(db)
    sources = {}
    for source_id in ("admin_units", "sgis_national", "kapt_national", "sgis_grid", "sgis_grid_1k", "zoning_ordinances"):
        source = db.get(DataSource, source_id)
        sources[source_id] = {"status": source.status, "quality": source.quality, "collected_at": source.collected_at.isoformat() if source.collected_at else None,
                              "coverage": source.geographic_coverage} if source else None
    return {
        "admin_units": _count(db, AdminUnit), "sigungu": _count(db, AdminUnit, AdminUnit.level == "SIGUNGU"), "regions": len(catalog(db)),
        "sgis_year": year, "sgis_sigungu": _count(db, NationalUnit, NationalUnit.year == year, NationalUnit.level == "SIGUNGU") if year else 0,
        "sgis_emd": _count(db, NationalUnit, NationalUnit.year == year, NationalUnit.level == "EMD") if year else 0,
        "complexes": _count(db, NationalComplex), "grid500_official": _count(db, SgisOfficialGridCell),
        "grid1k_year": grid_year, "grid1k_cells": _count(db, SgisGridCell, SgisGridCell.year == grid_year) if grid_year else 0,
        "sources": sources, "ordinances": _ordinance_counts(db),
    }


def _ordinance_counts(db: Any) -> dict[str, Any]:
    from .ordinances import ordinance_summary
    return ordinance_summary(db)


@router.get("")
def regions() -> dict[str, Any]:
    from .region_prepare import STEP_LABELS, STEPS
    with Session() as db:
        try:
            from .tasks import resume_overdue_regions
            resume_overdue_regions(db)
        except Exception:  # noqa: BLE001 - no queue (tests): the regions are still listed
            db.rollback()
        rows = [region_summary(r) for r in db.scalars(select(StudyRegion).order_by(StudyRegion.code))]
        for row in rows:
            row["short_name"] = short_name(row["name"])
        return {"default": DEFAULT_REGION, "regions": rows, "national": national_meta(db),
                "steps": [{"id": s, "label": STEP_LABELS[s]} for s in STEPS]}


@router.get("/catalog")
def region_catalog(q: str | None = Query(None, max_length=40)) -> dict[str, Any]:
    with Session() as db:
        status = {code: state for code, state in db.execute(select(StudyRegion.code, StudyRegion.status))}
        rows = []
        for entry in catalog(db):
            if q and q.replace(" ", "") not in entry["name"].replace(" ", ""):
                continue
            rows.append({"code": entry["code"], "name": entry["name"], "short_name": short_name(entry["name"]), "sido_name": entry["sido_name"],
                         "districts": entry["districts"], "study_status": status.get(entry["code"], "NOT_PREPARED")})
        return {"regions": rows, "total": len(rows)}


@router.get("/overview")
def overview() -> dict[str, Any]:
    from .national import national_overview
    with Session() as db:
        return national_overview(db)


@router.get("/{code}")
def region_detail(code: str) -> dict[str, Any]:
    from .region_prepare import STEP_LABELS, STEPS, create_region
    with Session() as db:
        region = db.get(StudyRegion, code)
        if region is None:
            try:
                entry = next(r for r in catalog(db) if r["code"] == code)
            except StopIteration:
                raise HTTPException(404, "전국 행정구역 목록에 없는 지역입니다") from None
            return {"code": code, "name": entry["name"], "short_name": short_name(entry["name"]), "sido_name": entry["sido_name"],
                    "status": "NOT_PREPARED", "legal_codes": entry["legal_codes"], "districts": entry["districts"], "datasets": {},
                    "steps": [{"id": s, "label": STEP_LABELS[s], "status": None} for s in STEPS]}
        body = region_summary(region)
        body["short_name"] = short_name(region.name)
        body["steps"] = [dict({"id": s, "label": STEP_LABELS[s], "status": None}, **((region.datasets or {}).get(s) or {})) for s in STEPS]
        return body


def _stale(region: StudyRegion) -> bool:
    """PREPARING but no worker holds the region lock and nothing was written for 3 minutes (worker restarted)."""
    from datetime import datetime, timedelta, timezone
    try:
        import os

        import redis
        if redis.Redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0")).exists("carbon:region-prepare"):
            return False
    except Exception:  # noqa: BLE001 - no Redis: trust the timestamp
        pass
    updated = region.updated_at
    if updated is None:
        return True
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - updated > timedelta(minutes=3)


class PrepareInput(BaseModel):
    steps: list[Step] | None = Field(default=None, max_length=14)
    force: bool = False


@router.post("/{code}/prepare", status_code=202)
def prepare(code: str, request: PrepareInput | None = None) -> dict[str, Any]:
    """Start (or resume) collecting one region's data in the background."""
    from .region_prepare import create_region
    from .settings import offline_mode
    from .tasks import queue_region_prepare
    if offline_mode():
        raise HTTPException(409, "오프라인 모드에서는 외부 수집을 시작하지 않습니다")
    request = request or PrepareInput()
    with Session() as db:
        try:
            region = create_region(db, code)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from None
        if region.status == "PREPARING" and not _stale(region):
            return region_summary(region)
        queue_region_prepare(db, region, request.steps, request.force)
        db.refresh(region)
        return region_summary(region)


class NationalInput(BaseModel):
    datasets: list[Literal["admin_units", "sgis_national", "kapt_national", "grid500", "ordinances"]] = Field(
        default=["admin_units", "sgis_national", "kapt_national", "grid500", "ordinances"], min_length=1)


@router.post("/national/collect", status_code=202)
def collect_national(request: NationalInput | None = None) -> dict[str, Any]:
    """Collect the national base layers in the background (about 1,300 requests in total)."""
    from .settings import offline_mode
    from .tasks import run_national
    if offline_mode():
        raise HTTPException(409, "오프라인 모드에서는 외부 수집을 시작하지 않습니다")
    datasets = (request or NationalInput()).datasets
    try:
        run_national.delay(datasets)
    except Exception:  # noqa: BLE001
        raise HTTPException(503, "수집 작업 큐에 연결하지 못했습니다") from None
    return {"queued": datasets}
