"""SGIS token management and administrative population/household statistics."""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import httpx
from sqlalchemy import DateTime, Float, JSON, String, func, select
from sqlalchemy.orm import Mapped, mapped_column

from .cache import CachedClient, ExternalError
from .db import Base
from .models import DataSource, RawDataAsset

SGIS_BASE_URL = "https://sgisapi.kostat.go.kr/OpenAPI3"
SGIS_GUIDE_URL = "https://sgis.kostat.go.kr/developer/upload/doc/DataAPI-definition.pdf"


class SgisPopulationAdmin(Base):
    __tablename__ = "sgis_population_admin"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    reference_year: Mapped[int] = mapped_column(index=True)
    adm_code: Mapped[str] = mapped_column(String, index=True)
    adm_name: Mapped[str | None] = mapped_column(String, nullable=True)
    population_count: Mapped[float | None] = mapped_column(Float, nullable=True)
    value_status: Mapped[str] = mapped_column(String)
    source: Mapped[str] = mapped_column(String)
    raw_source_id: Mapped[str | None] = mapped_column(String, nullable=True)
    raw_record: Mapped[dict] = mapped_column(JSON, default=dict)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class SgisHouseholdAdmin(Base):
    __tablename__ = "sgis_household_admin"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    reference_year: Mapped[int] = mapped_column(index=True)
    adm_code: Mapped[str] = mapped_column(String, index=True)
    adm_name: Mapped[str | None] = mapped_column(String, nullable=True)
    household_count: Mapped[float | None] = mapped_column(Float, nullable=True)
    family_member_count: Mapped[float | None] = mapped_column(Float, nullable=True)
    average_family_member_count: Mapped[float | None] = mapped_column(Float, nullable=True)
    value_status: Mapped[str] = mapped_column(String)
    source: Mapped[str] = mapped_column(String)
    raw_source_id: Mapped[str | None] = mapped_column(String, nullable=True)
    raw_record: Mapped[dict] = mapped_column(JSON, default=dict)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


def _value(value: Any) -> tuple[float | None, str]:
    if value is None or (isinstance(value, str) and value.strip() in {"", "-", "N/A", "null"}):
        return None, "NOT_AVAILABLE"
    if isinstance(value, str) and value.strip() in {"*", "X", "x"}:
        return None, "SUPPRESSED"
    try:
        number = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None, "NOT_AVAILABLE"
    return number, "OBSERVED_ZERO" if number == 0 else "OBSERVED"


def parse_sgis_statistics(body: bytes, kind: str) -> dict[str, Any]:
    if kind not in {"population", "household"}:
        raise ValueError("kind must be population or household")
    try:
        payload = json.loads(body.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExternalError("SGIS 응답 파싱 실패") from exc
    code = int(payload.get("errCd", -999))
    if code == -100:
        return {"provider_code": code, "provider_message": payload.get("errMsg"), "rows": [], "status": "EMPTY_VALID"}
    if code != 0:
        if code == -401:
            raise ExternalError("SGIS 인증 실패: consumer key/secret 또는 access token을 확인하세요")
        raise ExternalError(f"SGIS API 오류: provider_code={code}")
    rows = []
    field = "population" if kind == "population" else "household_cnt"
    for raw in payload.get("result") or []:
        value, status = _value(raw.get(field))
        row = {
            "adm_code": str(raw.get("adm_cd") or ""), "adm_name": raw.get("adm_nm"),
            "value": value, "value_status": status, "raw_record": dict(raw),
        }
        if kind == "household":
            row["family_member_count"] = _value(raw.get("family_member_cnt"))[0]
            row["average_family_member_count"] = _value(raw.get("avg_family_member_cnt"))[0]
        rows.append(row)
    return {"provider_code": code, "provider_message": payload.get("errMsg"), "rows": rows, "status": "SUCCESS"}


class SgisTokenManager:
    def __init__(self, consumer_key: str, consumer_secret: str, *, requester: Any | None = None, redis_client: Any | None = None, now: Callable[[], float] = time.time):
        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret
        self.requester = requester or httpx.Client(timeout=30, follow_redirects=True)
        self.redis = redis_client
        self.now = now
        self._token: str | None = None
        self._expires_at = 0.0

    def _cached(self) -> str | None:
        if self._token and self._expires_at - self.now() > 60:
            return self._token
        if self.redis:
            raw = self.redis.get("carbon:sgis-token")
            if raw:
                cached = json.loads(raw)
                if float(cached["expires_at"]) - self.now() > 60:
                    self._token, self._expires_at = cached["token"], float(cached["expires_at"])
                    return self._token
        return None

    def get_token(self) -> str:
        cached = self._cached()
        if cached:
            return cached
        if not self.consumer_key or not self.consumer_secret:
            raise ExternalError("SGIS 인증 실패: SGIS_CONSUMER_KEY/SGIS_CONSUMER_SECRET 미설정")
        base = os.getenv("SGIS_BASE_URL", SGIS_BASE_URL).rstrip("/")
        response = self.requester.get(f"{base}/auth/authentication.json", params={"consumer_key": self.consumer_key, "consumer_secret": self.consumer_secret})
        if getattr(response, "status_code", 200) >= 400:
            raise ExternalError(f"SGIS 인증 HTTP {response.status_code}")
        payload = response.json()
        if int(payload.get("errCd", -999)) != 0:
            raise ExternalError(f"SGIS 인증 실패: provider_code={payload.get('errCd')}")
        result = payload.get("result") or {}
        token = str(result.get("accessToken") or "")
        raw_expiry = float(result.get("accessTimeout") or 0)
        expiry = raw_expiry / 1000 if raw_expiry > 100_000_000_000 else raw_expiry
        if not token or expiry <= self.now():
            raise ExternalError("SGIS 인증 응답에 유효한 token/만료시각이 없습니다")
        self._token, self._expires_at = token, expiry
        if self.redis:
            ttl = max(int(expiry - self.now() - 60), 1)
            self.redis.setex("carbon:sgis-token", ttl, json.dumps({"token": token, "expires_at": expiry}))
        return token


def _source(db: Any) -> DataSource:
    source = db.get(DataSource, "sgis_admin") or DataSource(
        id="sgis_admin", category="인구", name="SGIS 행정구역 인구·가구",
        organization="국가데이터처 / SGIS", source_url=SGIS_GUIDE_URL, source_type="OFFICIAL",
        status="NOT_COLLECTED", limitation="행정구역 통계이며 프로젝트 500m 격자 인구로 배분하지 않습니다.",
    )
    db.add(source)
    grid = db.get(DataSource, "sgis_grid") or DataSource(
        id="sgis_grid", category="인구", name="SGIS 공식 500m 격자",
        organization="국가데이터처 / SGIS", source_url="https://sgis.kostat.go.kr/view/pss/openDataIntrcn",
        source_type="OFFICIAL", status="MANUAL_DOWNLOAD_REQUIRED",
        quality="requires_official_download", limitation="공식 경계·인구·기준연도·비밀보호 플래그 원본이 필요합니다.",
    )
    db.add(grid);db.flush()
    return source


def collect_sgis_admin(db: Any, year: int = 2020, scope: str = "smoke", *, token_manager: SgisTokenManager | None = None, client: CachedClient | None = None, data_dir: str | Path | None = None) -> dict[str, int]:
    if scope not in {"smoke", "limited", "full"}:
        raise ValueError("scope must be smoke, limited, or full")
    source = _source(db);db.commit()
    manager = token_manager or SgisTokenManager(os.getenv("SGIS_CONSUMER_KEY", "").strip(), os.getenv("SGIS_CONSUMER_SECRET", "").strip())
    try:
        token = manager.get_token()
    except ExternalError:
        source.status="NEEDS_API_APPROVAL";db.commit();raise
    root=Path(data_dir or os.getenv("DATA_DIR","data"));raw_root=root/"raw"/"sgis"/str(year);raw_root.mkdir(parents=True,exist_ok=True)
    session=client or CachedClient(root/"cache"/"sgis")
    base=os.getenv("SGIS_BASE_URL",SGIS_BASE_URL).rstrip("/")
    province=os.getenv("SGIS_JEONBUK_ADM_CD","35")
    kinds=["population"] if scope=="smoke" else ["population","household"]
    totals={"population_rows":0,"household_rows":0,"suppressed":0,"missing":0}
    for kind in kinds:
        endpoint="searchpopulation.json" if kind=="population" else "household.json"
        params={"accessToken":token,"year":str(year),"adm_cd":province,"low_search":"1"}
        result=session.get("SGIS",f"{kind}-{year}-{province}",f"{base}/stats/{endpoint}",params)
        raw_path=raw_root/f"{kind}-{province}.json";raw_path.write_bytes(result["body"])
        parsed=parse_sgis_statistics(result["body"],kind)
        selected=[row for row in parsed["rows"] if "전주" in str(row.get("adm_name") or "")]
        digest=hashlib.sha256(result["body"]+kind.encode()).hexdigest()
        asset=db.get(RawDataAsset,digest) or RawDataAsset(id=digest,source_id=source.id,provider=source.organization,source_url=SGIS_GUIDE_URL,reference_period=str(year),storage_location=str(raw_path),collection_status=parsed["status"])
        asset.row_count=len(parsed["rows"]);asset.request_parameters={"year":year,"adm_cd":province,"low_search":1,"provider_code":parsed["provider_code"]};db.add(asset)
        for row in selected:
            totals["suppressed"]+=row["value_status"]=="SUPPRESSED";totals["missing"]+=row["value_status"]=="NOT_AVAILABLE"
            if kind=="population":
                model=db.get(SgisPopulationAdmin,f"{year}:{row['adm_code']}") or SgisPopulationAdmin(id=f"{year}:{row['adm_code']}",reference_year=year,adm_code=row["adm_code"],source="SGIS")
                model.adm_name=row["adm_name"];model.population_count=row["value"]
            else:
                model=db.get(SgisHouseholdAdmin,f"{year}:{row['adm_code']}") or SgisHouseholdAdmin(id=f"{year}:{row['adm_code']}",reference_year=year,adm_code=row["adm_code"],source="SGIS")
                model.adm_name=row["adm_name"];model.household_count=row["value"];model.family_member_count=row["family_member_count"];model.average_family_member_count=row["average_family_member_count"]
            model.value_status=row["value_status"];model.raw_source_id=digest;model.raw_record=row["raw_record"];model.collected_at=datetime.now(timezone.utc);db.add(model)
        totals[f"{kind}_rows"]+=len(selected);db.commit()
    normalized=(db.scalar(select(func.count()).select_from(SgisPopulationAdmin))+db.scalar(select(func.count()).select_from(SgisHouseholdAdmin)))
    source.status="COLLECTED" if normalized and scope != "smoke" else "PARTIAL";source.reference_period=str(year);source.raw_row_count=sum(totals[key] for key in ("population_rows","household_rows"));source.normalized_row_count=normalized;source.missing_count=totals["missing"]+totals["suppressed"];source.quality=f"SGIS 행정통계 {normalized}행 / 공식 500m 격자 미확보";source.collected_at=datetime.now(timezone.utc);db.commit()
    return totals
