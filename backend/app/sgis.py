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
from geoalchemy2 import Geometry
from geoalchemy2.shape import from_shape
from shapely.geometry import shape
from shapely.validation import make_valid
from sqlalchemy import DateTime, Float, JSON, String, func, select
from sqlalchemy.orm import Mapped, mapped_column

from .cache import CachedClient, ExternalError, clear_credential_error, parse_cached_response, record_credential_error
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


class SgisAdminBoundary(Base):
    """Official SGIS administrative boundary (행정동 등) for one reference year.

    Geometry is stored in EPSG:5179 exactly as delivered by SGIS (UTM-K). It is
    used only to display administrative statistics; values are never spread to
    the project 500m grid.
    """
    __tablename__ = "sgis_admin_boundaries"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    reference_year: Mapped[int] = mapped_column(index=True)
    adm_code: Mapped[str] = mapped_column(String, index=True)
    adm_name: Mapped[str | None] = mapped_column(String, nullable=True)
    parent_code: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    geom: Mapped[object] = mapped_column(Geometry("GEOMETRY", srid=5179, spatial_index=True))
    area_m2: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String, default="SGIS")
    raw_source_id: Mapped[str | None] = mapped_column(String, nullable=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


SGIS_AUTH_MESSAGE = "SGIS 인증 실패: consumer key/secret 또는 access token을 확인하세요"
SGIS_NO_DATA = -100
TARGET_CITY_KEYWORD = "전주"
PROVINCE_KEYWORDS = ("전북", "전라북도")


def _payload(body: bytes, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(body.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExternalError(f"SGIS {label} 응답 파싱 실패") from exc
    if not isinstance(payload, dict):
        raise ExternalError(f"SGIS {label} 응답 형식 오류")
    code = int(payload.get("errCd", 0) or 0)
    if code in (-401, -410, -411):
        raise ExternalError(SGIS_AUTH_MESSAGE)
    return payload


def parse_sgis_boundary(body: bytes) -> dict[str, Any]:
    """Parse hadmarea.geojson. Coordinates are UTM-K (EPSG:5179)."""
    payload = _payload(body, "경계")
    code = int(payload.get("errCd", 0) or 0)
    if code == SGIS_NO_DATA:
        return {"provider_code": code, "features": [], "status": "EMPTY_VALID"}
    if code != 0:
        raise ExternalError(f"SGIS 경계 API 오류: provider_code={code}")
    features = []
    for raw in payload.get("features") or []:
        properties = dict(raw.get("properties") or {})
        try:
            geometry = shape(raw.get("geometry"))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ExternalError("SGIS 경계 geometry 파싱 실패") from exc
        repaired = not geometry.is_valid
        if repaired:
            geometry = make_valid(geometry)
        if geometry.is_empty:
            continue
        features.append({
            "adm_code": str(properties.get("adm_cd") or ""),
            "adm_name": properties.get("adm_nm"),
            "geometry": geometry, "geometry_repaired": repaired, "properties": properties,
        })
    return {"provider_code": code, "features": features, "status": "SUCCESS"}


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


def _candidate_years(year: int) -> list[int]:
    """Requested year first, then at most five older census years (not before 2015)."""
    return [candidate for candidate in range(int(year), max(2014, int(year) - 6), -1)]


class _SgisRun:
    def __init__(self, db: Any, session: Any, token: str, root: Path, base: str, credential_fingerprint: str, source: DataSource):
        self.db, self.session, self.token, self.root, self.base = db, session, token, root, base
        self.credential_fingerprint, self.source = credential_fingerprint, source
        self.requests = 0

    def fetch(self, operation: str, path: str, params: dict[str, Any], raw_name: str, parser: Callable[[bytes], dict[str, Any]], year: int) -> dict[str, Any]:
        query = {"accessToken": self.token, **{key: str(value) for key, value in params.items() if value is not None}}
        result = self.session.get("SGIS", operation, f"{self.base}/{path}", query)
        self.requests += 1
        raw_root = self.root / "raw" / "sgis" / str(year)
        raw_root.mkdir(parents=True, exist_ok=True)
        raw_path = raw_root / raw_name
        raw_path.write_bytes(result["body"])
        try:
            parsed = parse_cached_response(self.session, result, parser)
        except ExternalError as exc:
            if "인증 실패" in str(exc):
                record_credential_error(self.root / "cache" / "sgis-auth", self.credential_fingerprint, str(exc))
            raise
        digest = hashlib.sha256(result["body"] + operation.encode()).hexdigest()
        asset = self.db.get(RawDataAsset, digest) or RawDataAsset(
            id=digest, source_id=self.source.id, provider=self.source.organization, source_url=SGIS_GUIDE_URL,
            reference_period=str(year), storage_location=str(raw_path), collection_status=parsed.get("status", "SUCCESS"),
        )
        asset.row_count = len(parsed.get("rows") or parsed.get("features") or [])
        asset.request_parameters = {**{key: value for key, value in params.items() if value is not None}, "endpoint": path, "provider_code": parsed.get("provider_code")}
        self.db.add(asset)
        parsed["raw_source_id"] = digest
        return parsed


def _store_statistics(db: Any, kind: str, year: int, rows: list[dict[str, Any]], raw_source_id: str) -> dict[str, int]:
    counts = {"rows": 0, "suppressed": 0, "missing": 0}
    for row in rows:
        counts["rows"] += 1
        counts["suppressed"] += row["value_status"] == "SUPPRESSED"
        counts["missing"] += row["value_status"] == "NOT_AVAILABLE"
        key = f"{year}:{row['adm_code']}"
        if kind == "population":
            model = db.get(SgisPopulationAdmin, key) or SgisPopulationAdmin(id=key, reference_year=year, adm_code=row["adm_code"], source="SGIS")
            model.population_count = row["value"]
        else:
            model = db.get(SgisHouseholdAdmin, key) or SgisHouseholdAdmin(id=key, reference_year=year, adm_code=row["adm_code"], source="SGIS")
            model.household_count = row["value"]
            model.family_member_count = row["family_member_count"]
            model.average_family_member_count = row["average_family_member_count"]
        model.adm_name = row["adm_name"];model.value_status = row["value_status"];model.raw_source_id = raw_source_id
        model.raw_record = row["raw_record"];model.collected_at = datetime.now(timezone.utc)
        db.add(model)
    return counts


def _resolve_city(run: _SgisRun, year: int) -> tuple[str, list[dict[str, Any]]] | None:
    """Discover year-specific province and Jeonju district codes from SGIS itself.

    SGIS statistical area codes change over time (e.g. 전북특별자치도), so codes are
    looked up per reference year instead of hard-coding them.
    """
    national = run.fetch(f"population-{year}-sido", "stats/searchpopulation.json", {"year": year}, "population-sido.json", lambda body: parse_sgis_statistics(body, "population"), year)
    if national["status"] == "EMPTY_VALID" or not national["rows"]:
        return None
    province = next((row for row in national["rows"] if any(keyword in str(row.get("adm_name") or "") for keyword in PROVINCE_KEYWORDS)), None)
    if not province:
        raise ExternalError("SGIS 시도 목록에서 전북을 찾지 못했습니다")
    districts = run.fetch(f"population-{year}-{province['adm_code']}", "stats/searchpopulation.json", {"year": year, "adm_cd": province["adm_code"], "low_search": 1}, f"population-{province['adm_code']}.json", lambda body: parse_sgis_statistics(body, "population"), year)
    jeonju = [row for row in districts["rows"] if TARGET_CITY_KEYWORD in str(row.get("adm_name") or "")]
    if not jeonju:
        raise ExternalError("SGIS 시군구 목록에서 전주시를 찾지 못했습니다")
    _store_statistics(run.db, "population", year, jeonju, districts["raw_source_id"])
    return province["adm_code"], jeonju


def _store_boundaries(db: Any, year: int, parent_code: str, parsed: dict[str, Any]) -> int:
    stored = 0
    for feature in parsed["features"]:
        if not feature["adm_code"]:
            continue
        key = f"{year}:{feature['adm_code']}"
        row = db.get(SgisAdminBoundary, key) or SgisAdminBoundary(id=key, reference_year=year, adm_code=feature["adm_code"])
        row.adm_name = feature["adm_name"];row.parent_code = parent_code
        row.geom = from_shape(feature["geometry"], srid=5179);row.area_m2 = float(feature["geometry"].area)
        row.raw_source_id = parsed["raw_source_id"];row.collected_at = datetime.now(timezone.utc)
        db.add(row);stored += 1
    return stored


def collect_sgis_admin(db: Any, year: int = 2023, scope: str = "smoke", *, token_manager: SgisTokenManager | None = None, client: CachedClient | None = None, data_dir: str | Path | None = None) -> dict[str, Any]:
    """Collect official SGIS administrative statistics for Jeonju.

    smoke   : token + year-specific province/district code discovery + district population
    limited : + 행정동 population and official 행정동 boundaries
    full    : + 행정동 households
    The requested year is tried first and older years are used only when SGIS
    reports that the year is not published (errCd -100); the year actually used
    is recorded as the reference period.
    """
    if scope not in {"smoke", "limited", "full"}:
        raise ValueError("scope must be smoke, limited, or full")
    source = _source(db);db.commit()
    root = Path(data_dir or os.getenv("DATA_DIR", "data"))
    manager = token_manager or SgisTokenManager(os.getenv("SGIS_CONSUMER_KEY", "").strip(), os.getenv("SGIS_CONSUMER_SECRET", "").strip())
    credential_fingerprint = f"{manager.consumer_key}|{manager.consumer_secret}"
    try:
        token = manager.get_token()
        clear_credential_error(root / "cache" / "sgis-auth", credential_fingerprint)
    except ExternalError as exc:
        record_credential_error(root / "cache" / "sgis-auth", credential_fingerprint, str(exc))
        source.status = "NEEDS_API_APPROVAL";db.commit();raise
    session = client or CachedClient(root / "cache" / "sgis", min_interval=0.3)
    base = os.getenv("SGIS_BASE_URL", SGIS_BASE_URL).rstrip("/")
    run = _SgisRun(db, session, token, root, base, credential_fingerprint, source)
    resolved = None
    used_year = None
    last_error: ExternalError | None = None
    for candidate in _candidate_years(year):
        try:
            resolved = _resolve_city(run, candidate)
        except ExternalError as exc:
            if "인증 실패" in str(exc):
                raise
            # An unpublished year can be reported as an error instead of -100.
            last_error, resolved = exc, None
        if resolved:
            used_year = candidate
            break
    if not resolved or used_year is None:
        raise last_error or ExternalError("SGIS가 요청 연도 이전 6개 연도에 공표 자료를 제공하지 않습니다")
    province_code, districts = resolved
    totals: dict[str, Any] = {"reference_year": used_year, "requested_year": int(year), "district_rows": len(districts), "dong_population_rows": 0, "dong_household_rows": 0, "boundaries": 0, "suppressed": 0, "missing": 0}
    if scope in {"limited", "full"}:
        for district in districts:
            code = district["adm_code"]
            population = run.fetch(f"population-{used_year}-{code}", "stats/searchpopulation.json", {"year": used_year, "adm_cd": code, "low_search": 1}, f"population-{code}.json", lambda body: parse_sgis_statistics(body, "population"), used_year)
            counts = _store_statistics(db, "population", used_year, population["rows"], population["raw_source_id"])
            totals["dong_population_rows"] += counts["rows"];totals["suppressed"] += counts["suppressed"];totals["missing"] += counts["missing"]
            boundary = run.fetch(f"boundary-{used_year}-{code}", "boundary/hadmarea.geojson", {"year": used_year, "adm_cd": code, "low_search": 1}, f"boundary-{code}.geojson", parse_sgis_boundary, used_year)
            totals["boundaries"] += _store_boundaries(db, used_year, code, boundary)
            db.commit()
    if scope == "full":
        for district in districts:
            code = district["adm_code"]
            households = run.fetch(f"household-{used_year}-{code}", "stats/household.json", {"year": used_year, "adm_cd": code, "low_search": 1}, f"household-{code}.json", lambda body: parse_sgis_statistics(body, "household"), used_year)
            counts = _store_statistics(db, "household", used_year, households["rows"], households["raw_source_id"])
            totals["dong_household_rows"] += counts["rows"];totals["suppressed"] += counts["suppressed"];totals["missing"] += counts["missing"]
            db.commit()
    totals["requests"] = run.requests
    population_rows = db.scalar(select(func.count()).select_from(SgisPopulationAdmin).where(SgisPopulationAdmin.reference_year == used_year)) or 0
    household_rows = db.scalar(select(func.count()).select_from(SgisHouseholdAdmin).where(SgisHouseholdAdmin.reference_year == used_year)) or 0
    boundary_rows = db.scalar(select(func.count()).select_from(SgisAdminBoundary).where(SgisAdminBoundary.reference_year == used_year)) or 0
    source.status = "COLLECTED" if scope == "full" and household_rows else "PARTIAL"
    source.reference_period = str(used_year)
    source.raw_row_count = run.requests
    source.normalized_row_count = population_rows + household_rows
    source.missing_count = totals["missing"] + totals["suppressed"]
    source.quality = f"SGIS {used_year} 행정통계 인구 {population_rows}행·가구 {household_rows}행·행정동 경계 {boundary_rows}개 / 500m 공식 격자 미확보"
    source.collected_at = datetime.now(timezone.utc)
    db.commit()
    return totals
