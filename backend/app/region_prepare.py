"""지역 준비: 전국 어느 시·군·구든 그 지역 자료를 직접 수집해 분석 가능한 상태로 만든다.

A study region is prepared once. Every step asks the provider for that region only and writes into the
same national tables the original Jeonju study uses (keys are nationally unique), so every reader keeps
working and simply filters by the region (``regions.scope``).

Steps (``STEPS``), each recorded in ``study_regions.datasets``:

* grid            – SGIS official 500m cells of the region's SGIS 시군구 codes → analysis cells ``cell_<x>_<y>``
* sgis_admin      – SGIS 행정동 population, households and boundaries (latest published year)
* complexes       – K-apt 단지 목록 + 상세 (households, floor area, 사용승인일, coordinates)
* weather         – ERA5-Land monthly weather at the region centre (Open-Meteo archive), 2015–
* zoning, buildings, cadastral – VWorld layers per 1km tile
* zoning_other    – VWorld 관리·농림·자연환경보전지역 (the non-urban 용도지역) per 1km tile
* special_areas   – VWorld 개발제한구역·지구단위계획구역 per 1km tile
* ordinance       – the 도시·군계획 조례 that sets the region's 건폐율·용적률 (law.go.kr)
* register        – 건축HUB 건축물대장 표제부 for every 법정동/리 of the region
* building_energy – 건축HUB 전 지번 electricity/gas of the analysis year (quota-bound)
* kapt_energy     – K-apt monthly energy of the analysis year (quota-bound: 5,000 requests a day, shared)
* finalize        – energy ↔ grid links, default grid, status

A daily quota stops only its own step (status WAITING, resumed on the next run); a missing key or approval
marks it BLOCKED. Nothing is estimated to fill a gap: an unfinished step simply leaves its layer empty and
the screens say so.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import func, insert, select, update

from .cache import CachedClient, ExternalError
from .regions import (DEFAULT_REGION, RegionWeatherMonthly, StudyRegion, _set_center, catalog_entry, forget_region_cache,
                      legal_leaves, link_grids, list_codes, match_sgis, region_grid_ids)

Log = Callable[[str], None]

STEPS = ("grid", "sgis_admin", "complexes", "weather", "zoning", "zoning_other", "special_areas", "ordinance",
         "buildings", "cadastral", "register", "building_energy", "kapt_energy", "finalize")
STEP_LABELS = {
    "grid": "500m 분석 격자 (SGIS 공식 격자)", "sgis_admin": "SGIS 행정동 인구·가구·경계", "complexes": "K-apt 공동주택 단지",
    "weather": "기상 (ERA5-Land, 지역 중심)", "zoning": "VWorld 용도지역", "buildings": "VWorld 도로명주소 건물",
    "zoning_other": "VWorld 관리·농림·자연환경보전지역", "special_areas": "VWorld 개발제한구역·지구단위계획구역",
    "ordinance": "도시·군계획 조례 (건폐율·용적률)",
    "cadastral": "VWorld 연속지적", "register": "건축물대장 표제부", "building_energy": "건축HUB 건물 에너지 (전 지번)",
    "kapt_energy": "K-apt 월별 에너지", "finalize": "연결·기본 대상지 정리",
}
QUOTA_BOUND = ("building_energy", "kapt_energy")
# Opening any 시·군·구 on the map builds these right away (national layers already in the database + one weather call).
BASIC_STEPS = ("grid", "sgis_admin", "ordinance", "weather")
_OPEN_LOCKS: dict[str, Any] = {}
DONE_STATES = ("DONE", "SKIPPED")


def now() -> datetime:
    return datetime.now(timezone.utc)


def _root() -> Path:
    return Path(os.getenv("DATA_DIR", "data"))


def analysis_year() -> int:
    from .settings import DEFAULT_YEAR
    return int(DEFAULT_YEAR)


# --------------------------------------------------------------------------- region record
def create_region(db: Any, code: str) -> StudyRegion:
    """The study region of a catalog code (5-digit 법정 시·군·구; a city with 일반구 as a whole)."""
    region = db.get(StudyRegion, code)
    if region is not None:
        return region
    entry = catalog_entry(db, code)
    if entry is None:
        raise LookupError(f"전국 행정구역 목록에 없는 코드입니다: {code} (법정 행정구역 자료를 먼저 받아야 합니다)")
    region = StudyRegion(code=code, name=entry["name"], sido_name=entry["sido_name"], legal_codes=list(entry["legal_codes"]),
                         sgis_codes=[], status="NOT_PREPARED", datasets={}, grid_count=0, message=None)
    db.add(region)
    db.commit()
    return region


def _mark(db: Any, region: StudyRegion, step: str, status: str, message: str | None = None, **extra: Any) -> None:
    # Re-read the row under a lock: another process (a CLI run, the API queueing a step) may have written
    # other steps since this session loaded it, and ``datasets`` is replaced as a whole.
    try:
        db.refresh(region, with_for_update=True)
    except Exception:  # noqa: BLE001 - SQLite in tests
        db.rollback()
        db.refresh(region)
    datasets = dict(region.datasets or {})
    item = dict(datasets.get(step) or {})
    item.update(status=status, at=now().isoformat(timespec="seconds"), label=STEP_LABELS.get(step, step))
    if message is not None:
        item["message"] = message[:300]
    item.update(extra)
    datasets[step] = item
    region.datasets = datasets
    region.updated_at = now()
    db.commit()


def overall_status(datasets: dict[str, Any]) -> str:
    states = [(datasets.get(step) or {}).get("status") for step in STEPS]
    if any(state == "RUNNING" for state in states):
        return "PREPARING"
    if all(state in DONE_STATES for state in states):
        return "READY"
    if (datasets.get("grid") or {}).get("status") == "DONE":
        return "PARTIAL"
    return "NOT_PREPARED"


def _classify(exc: Exception) -> tuple[str, str]:
    message = str(exc) if type(exc).__name__ in ("ExternalError", "ValueError", "LookupError", "RuntimeError") else f"처리 실패: {type(exc).__name__}"
    lowered = message.lower()
    if "한도" in message or "호출 제한" in message or "limited" in lowered or message.startswith("22"):
        return "WAITING", message
    if "인증" in message or "미설정" in message or "승인" in message:
        return "BLOCKED", message
    return "FAILED", message


# --------------------------------------------------------------------------- SGIS codes of the region
def ensure_sgis_codes(db: Any, region: StudyRegion, log: Log = print) -> list[str]:
    """SGIS 시군구 codes of the region: from the national SGIS layer when present, else asked from SGIS (2 requests)."""
    if region.sgis_codes:
        return list(region.sgis_codes)
    from .national import sgis_codes_for
    codes = sgis_codes_for(db, region.code)
    if not codes:
        from .national import _Sgis, _pick_year
        from .regions import sido_keys, split_name
        from .sgis import parse_sgis_statistics
        sgis = _Sgis(db, int(os.getenv("SGIS_BASE_YEAR", "2024")), log)
        used, national = _pick_year(sgis, sgis.year)
        keys = set(sido_keys(region.sido_name or split_name(region.name)[0]))
        rows: list[dict[str, Any]] = []
        for sido in national["rows"]:
            if keys & set(sido_keys(sido.get("adm_name") or "")):
                districts = sgis.get(f"population-{used}-{sido['adm_code']}", "stats/searchpopulation.json",
                                     {"year": used, "adm_cd": sido["adm_code"], "low_search": 1}, lambda b: parse_sgis_statistics(b, "population"))
                rows += [dict(r, adm_name=f"{sido.get('adm_name')} {r.get('adm_name')}" if not str(r.get("adm_name") or "").startswith(str(sido.get("adm_name"))) else r.get("adm_name")) for r in districts["rows"]]
        codes = match_sgis(region.name, rows)
    if not codes:
        raise ExternalError(f"SGIS 시군구 코드를 찾지 못했습니다: {region.name} (이름 대응 실패, 추정하지 않음)")
    region.sgis_codes = sorted(codes)
    db.commit()
    return list(region.sgis_codes)


# --------------------------------------------------------------------------- steps
def step_grid(db: Any, region: StudyRegion, log: Log) -> dict[str, Any]:
    """Analysis cells = the SGIS official 500m cells listed for the region's SGIS 시군구 (border cells included)."""
    from geoalchemy2.shape import from_shape
    from pyproj import Transformer
    from shapely.geometry import box, mapping
    from shapely.ops import transform

    from .models import Grid
    from .sgis_grid_official import SgisOfficialGridCell, collect_sgis_grid_official, project_cell_id
    codes = ensure_sgis_codes(db, region, log)

    def cells_for(code_list: list[str]) -> dict[str, Any]:
        found: dict[str, Any] = {}
        for code in code_list:
            for cell in db.scalars(select(SgisOfficialGridCell).where(SgisOfficialGridCell.adm_cd.like(f"%{code}%"), SgisOfficialGridCell.size_m == 500)):
                if code in (cell.adm_cd or "").split(","):
                    found[cell.grid_cd] = cell
        return found

    have = cells_for(codes)
    listed = {c for cell in have.values() for c in (cell.adm_cd or "").split(",")}
    missing = [code for code in codes if code not in listed]
    requests = 0
    if missing:
        log(f"SGIS 공식 500m 격자 요청: {', '.join(missing)}")
        requests = collect_sgis_grid_official(db, district_codes=missing)["requests"]
        have = cells_for(codes)
    if not have:
        raise ExternalError("SGIS가 이 지역의 500m 격자를 돌려주지 않았습니다")
    to4326 = Transformer.from_crs(5179, 4326, always_xy=True).transform
    existing = set(db.scalars(select(Grid.id).where(Grid.id.in_([project_cell_id(c.x_min, c.y_min) for c in have.values()]))))
    new_rows = []
    ids = []
    for cell in have.values():
        grid_id = project_cell_id(cell.x_min, cell.y_min)
        ids.append(grid_id)
        if grid_id in existing:
            continue
        x, y = int(round(cell.x_min)), int(round(cell.y_min))
        metric = box(x, y, x + 500, y + 500)
        props = {"id": grid_id, "area_m2": 250000, "x": x, "y": y, "region_code": region.code, "sgis500_code": cell.grid_cd,
                 "source": "SGIS 공식 500m 격자"}
        new_rows.append({"id": grid_id, "geom": from_shape(metric, srid=5179), "area_m2": 250000, "properties": props,
                         "geojson": {"type": "Feature", "properties": props, "geometry": mapping(transform(to4326, metric))}})
        existing.add(grid_id)
    for start in range(0, len(new_rows), 2000):
        db.execute(insert(Grid), new_rows[start:start + 2000])
    # Official code ↔ analysis cell link for the cells just created.
    for cell in have.values():
        if not cell.grid_id:
            cell.grid_id = project_cell_id(cell.x_min, cell.y_min)
    db.commit()
    linked = link_grids(db, region.code, ids)
    db.commit()
    forget_region_cache(region.code)
    region.grid_count = len(region_grid_ids(db, region.code))
    _set_center(db, region)
    if not region.default_grid_id:
        # Until the finalize step picks the densest housing cell, the centre cell is the default 대상지.
        region.default_grid_id = centre_cell(region, region_grid_ids(db, region.code))
    db.commit()
    from .sgis_grid_official import _GRID_CODES
    _GRID_CODES.clear()
    return {"rows": region.grid_count, "message": f"분석 격자 {region.grid_count:,}개 (새로 만든 격자 {len(new_rows):,}개, 연결 {linked:,}개, SGIS 요청 {requests}회)"}


def step_sgis_admin(db: Any, region: StudyRegion, log: Log) -> dict[str, Any]:
    """SGIS 행정동 statistics and full-resolution boundaries for the region (same requests as the national layer: cached)."""
    from .national import NationalUnit, _Sgis, _pick_year
    from .sgis import (SgisHouseholdAdmin, SgisPopulationAdmin, _store_boundaries, _store_statistics, parse_sgis_boundary,
                       parse_sgis_statistics)
    codes = ensure_sgis_codes(db, region, log)
    year = db.scalar(select(func.max(NationalUnit.year)))
    sgis = _Sgis(db, int(year or os.getenv("SGIS_BASE_YEAR", "2024")), log)
    if not year:
        year, _ = _pick_year(sgis, sgis.year)
        sgis.year = year
    counts = {"dongs": 0, "boundaries": 0, "suppressed": 0}

    def digest(name: str) -> str:
        path = sgis.raw_dir / f"{name}.json"
        return hashlib.sha256(path.read_bytes() + name.encode()).hexdigest() if path.exists() else name

    for code in codes:
        pop_name, hh_name, b_name = f"population-{year}-{code}", f"household-{year}-{code}", f"boundary-{year}-{code}"
        pop = sgis.get(pop_name, "stats/searchpopulation.json", {"year": year, "adm_cd": code, "low_search": 1}, lambda b: parse_sgis_statistics(b, "population"))
        households = sgis.get(hh_name, "stats/household.json", {"year": year, "adm_cd": code, "low_search": 1}, lambda b: parse_sgis_statistics(b, "household"))
        boundary = sgis.get(b_name, "boundary/hadmarea.geojson", {"year": year, "adm_cd": code, "low_search": 1}, parse_sgis_boundary)
        stored = _store_statistics(db, "population", year, pop["rows"], digest(pop_name))
        _store_statistics(db, "household", year, households["rows"], digest(hh_name))
        boundary["raw_source_id"] = digest(b_name)
        counts["boundaries"] += _store_boundaries(db, year, code, boundary)
        counts["dongs"] += stored["rows"]
        counts["suppressed"] += stored["suppressed"]
        # the 시군구 row itself (as the original collection keeps 완산구/덕진구)
        unit = db.get(NationalUnit, f"{year}:{code}")
        if unit is not None:
            key = f"{year}:{code}"
            row = db.get(SgisPopulationAdmin, key) or SgisPopulationAdmin(id=key, reference_year=year, adm_code=code, source="SGIS")
            row.adm_name, row.population_count, row.value_status = unit.adm_name, unit.population, unit.population_status or "NOT_AVAILABLE"
            row.raw_record = {"from": "national_units"}
            db.add(row)
            hrow = db.get(SgisHouseholdAdmin, key) or SgisHouseholdAdmin(id=key, reference_year=year, adm_code=code, source="SGIS")
            hrow.adm_name, hrow.household_count, hrow.value_status = unit.adm_name, unit.households, unit.household_status or "NOT_AVAILABLE"
            hrow.raw_record = {"from": "national_units"}
            db.add(hrow)
        db.commit()
    return {"rows": counts["dongs"], "message": f"SGIS {year} 행정동 {counts['dongs']}곳 (경계 {counts['boundaries']}개, 비공개 {counts['suppressed']}곳)", "year": year}


def _kapt_month() -> str:
    """K-apt list snapshot month: the national list month when collected, else the last finished month."""
    base = _root() / "raw" / "kapt-national"
    months = sorted(p.name for p in base.iterdir() if p.is_dir() and p.name.isdigit()) if base.exists() else []
    if months:
        return months[-1]
    first = now().replace(day=1) - timedelta(days=1)
    return first.strftime("%Y%m")


def step_complexes(db: Any, region: StudyRegion, log: Log, *, delay_s: float = 0.4) -> dict[str, Any]:
    """K-apt 단지 목록 (by 법정 구/시군구 code) and every complex's detail page."""

    import httpx

    from .kapt import (KAPT_LIST_URL, KAPT_MAIN_URL, LIST_HEADERS, _client, apply_complex, csrf_token, fetch_complex_detail, list_damaged,
                       normalize_detail, normalize_summary)
    from .settings import offline_mode
    month = _kapt_month()
    codes = list_codes(region.legal_codes or [])
    raw_dir = _root() / "raw" / "kapt-national" / month
    raw_dir.mkdir(parents=True, exist_ok=True)
    detail_dir = _root() / "raw" / "kapt-regions" / region.code
    detail_dir.mkdir(parents=True, exist_ok=True)
    lists: dict[str, list[dict[str, Any]]] = {}
    web = None
    token = None
    for code in codes:
        path = raw_dir / f"list-{code}.json"
        if not path.exists() or list_damaged(json.loads(path.read_text(encoding="utf-8"))):
            if offline_mode():
                raise ExternalError("오프라인 모드: K-apt 목록을 받지 않습니다")
            if web is None:
                web = httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": "Carbon-Urban-DSS/1.0 public-data-research", "Accept-Language": "ko-KR,ko;q=0.9"})
                landing = web.get(KAPT_MAIN_URL)
                token = csrf_token(landing.text)
                if not token:
                    raise ExternalError("K-apt 첫 화면에 CSRF 토큰이 없습니다")
            response = web.post(KAPT_LIST_URL, data={"bjdCode": code, "kaptName": "", "searchDate": month, "kaptDuty": "ALL", "_csrf": token},
                                headers={"X-CSRF-TOKEN": token, **LIST_HEADERS})
            response.raise_for_status()
            path.write_text(json.dumps(response.json(), ensure_ascii=False), encoding="utf-8")
        lists[code] = json.loads(path.read_text(encoding="utf-8")).get("resultList") or []
    if web is not None:
        web.close()
    summaries = [normalize_summary(row, code, month) for code, rows in lists.items() for row in rows if row.get("kaptCode")]
    client = _client(detail_dir)
    client.min_interval = delay_s
    details, failed = 0, []
    try:
        for index, row in enumerate(summaries, 1):
            code = row["kapt_code"]
            path = detail_dir / f"kapt_detail_{code}.json"
            pair = None
            try:
                if path.exists():
                    payload = json.loads(path.read_text(encoding="utf-8"))
                else:
                    payload = fetch_complex_detail(client, code)
                    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                pair = (normalize_detail(payload), payload)
                details += 1
            except (RuntimeError, ExternalError, ValueError, TypeError, KeyError, httpx.HTTPError) as exc:
                # One unreadable detail page leaves that complex with its list values only.
                failed.append(f"{code}: {type(exc).__name__}")
            apply_complex(db, row, pair, month)
            if index % 50 == 0:
                db.commit()
                log(f"K-apt 단지 {index}/{len(summaries)}")
    finally:
        client.client.close()
    db.commit()
    return {"rows": len(summaries), "message": f"K-apt 단지 {len(summaries):,}개 (상세 {details:,}개{f', 상세 실패 {len(failed)}개' if failed else ''}, 목록 기준 {month})",
            "details": details, "failed": failed[:10]}


def step_weather(db: Any, region: StudyRegion, log: Log) -> dict[str, Any]:
    """ERA5-Land monthly weather (HDD 18°C · CDD 24°C, degree_days.py) at the region centre, 2015-01 to the analysis year."""
    from .collectors import client
    from .domain import monthly_weather
    if region.code == DEFAULT_REGION:
        return {"status": "SKIPPED", "rows": 0, "message": "원래 지역은 기상청 ASOS 146(전주) 자료를 씁니다"}
    if region.center_lon is None or region.center_lat is None:
        raise ValueError("지역 중심을 모릅니다: 격자 단계를 먼저 끝내야 합니다")
    last = analysis_year()
    params = dict(latitude=round(region.center_lat, 4), longitude=round(region.center_lon, 4), start_date="2015-01-01", end_date=f"{last}-12-31",
                  daily="temperature_2m_mean,temperature_2m_min,temperature_2m_max,precipitation_sum", timezone="Asia/Seoul", models="era5_land")
    result = client.get("weather", f"region-{region.code}", "https://archive-api.open-meteo.com/v1/archive", params)
    raw = _root() / "raw" / "weather-regions"
    raw.mkdir(parents=True, exist_ok=True)
    (raw / f"{region.code}.json").write_bytes(result["body"])
    payload = json.loads(result["body"])
    rows = monthly_weather(payload)
    for row in rows:
        item = db.get(RegionWeatherMonthly, (region.code, row["use_ym"])) or RegionWeatherMonthly(region_code=region.code, use_ym=row["use_ym"])
        item.provider, item.source_type = "Open-Meteo / ERA5-Land", "FALLBACK"
        item.latitude, item.longitude = params["latitude"], params["longitude"]
        for key in ("mean_temperature", "min_temperature", "max_temperature", "precipitation", "hdd", "cdd", "days_observed", "expected_days"):
            setattr(item, key, row[key])
        item.collected_at = now()
        db.add(item)
    db.commit()
    solar_months = 0
    try:  # 일사량 → 태양광 연 발전량 추정 (docs/DATA_STANDARD.md 5.13); ERA5 (era5_land has no radiation at Open-Meteo)
        from .solar import fetch_region
        solar_months = fetch_region(db, region.code, params["latitude"], params["longitude"], 2015, last, raw.parent / "weather-solar")
        db.commit()
    except Exception as exc:  # noqa: BLE001 - irradiation is optional; the weather step still succeeds
        db.rollback()
        log(f"일사량 받기 실패: {type(exc).__name__}")
    complete = sum(1 for r in rows if r["days_observed"] >= r["expected_days"])
    return {"rows": len(rows), "message": f"ERA5-Land {len(rows)}개월 (완전월 {complete}개월, 일사량 {solar_months}개월, 지점 {params['latitude']}, {params['longitude']})"}


def _vworld_step(dataset: str) -> Callable[[Any, StudyRegion, Log], dict[str, Any]]:
    def run(db: Any, region: StudyRegion, log: Log) -> dict[str, Any]:
        from .vworld import VworldGridCoverage, collect_vworld_cells
        ids = sorted(region_grid_ids(db, region.code))
        done = set(db.scalars(select(VworldGridCoverage.grid_id).where(VworldGridCoverage.dataset == dataset)))
        todo = [g for g in ids if g not in done]
        if not todo:
            return {"rows": len(ids), "message": f"요청할 격자 없음 (격자 {len(ids):,}개 모두 조회됨)"}
        stats = collect_vworld_cells(db, dataset, todo, progress=lambda f, m: log(m) if int(f * 100) % 10 == 0 else None)
        if dataset == "cadastral":
            from .energy_parcels import build_parcel_grid
            stats["parcel_grid"] = build_parcel_grid(db)
        extra = f", 필지-격자 {stats['parcel_grid']:,}건" if "parcel_grid" in stats else ""
        return {"rows": stats["features"], "message": f"{stats['tiles']:,}개 1km 타일, 요청 {stats['requests']:,}회, 도형 {stats['features']:,}개{extra}"}
    return run


def _vworld_multi(datasets: tuple[str, ...]) -> Callable[[Any, StudyRegion, Log], dict[str, Any]]:
    """Several VWorld layers in one step (each keeps its own per-cell coverage)."""
    def run(db: Any, region: StudyRegion, log: Log) -> dict[str, Any]:
        rows, parts = 0, []
        for dataset in datasets:
            result = _vworld_step(dataset)(db, region, log)
            rows += result["rows"] if "요청할 격자 없음" not in result["message"] else 0
            parts.append(f"{dataset}: {result['message']}")
        return {"rows": rows, "message": " / ".join(parts)}
    return run


def step_ordinance(db: Any, region: StudyRegion, log: Log) -> dict[str, Any]:
    """The 도시·군계획 조례 that applies here: its 용도지역 건폐율·용적률 (else the screens use 시행령 상한)."""
    from .ordinances import collect_ordinances, ordinance_for_region
    collect_ordinances(db, [region.code], log=log)
    info = ordinance_for_region(db, region.code) or {}
    row = info.get("row") or {}
    status = info.get("status")
    if status in ("PARSED", "PARTIAL"):
        message = f"{row.get('title')} ({row.get('effective')} 시행): 건폐율 {row.get('zones_bcr')}·용적률 {row.get('zones_far')}개 용도지역"
        return {"rows": row.get("zones_far") or 0, "message": message}
    reason = row.get("message") or "조례를 받지 못했습니다"
    # Not a failure of the region: the limits fall back to 국토계획법 시행령 (전국 공통 규정).
    return {"rows": 0, "status": "DONE", "message": f"{reason} → 국토계획법 시행령 상한을 씁니다"}


def step_register(db: Any, region: StudyRegion, log: Log) -> dict[str, Any]:
    from .official import collect_register
    leaves = legal_leaves(db, region.legal_codes or [])
    if not leaves:
        raise ValueError("이 지역의 법정동·리 코드가 없습니다 (전국 법정 행정구역 자료 필요)")
    result = collect_register(db, "full", lambda f, m: log(m) if int(f * 100) % 10 == 0 else None, regions=leaves, update=False)
    return {"rows": result["rows"], "message": f"표제부 {result['rows']:,}건 (법정동·리 {len(leaves)}곳, 격자 연결 {result['linked']:,}건, 일시 오류 {result['failed']}건)"}


def step_building_energy(db: Any, region: StudyRegion, log: Log) -> dict[str, Any]:
    from .energy_parcels import build_parcel_grid, collect_energy_all
    leaves = legal_leaves(db, region.legal_codes or [])
    if not leaves:
        raise ValueError("이 지역의 법정동·리 코드가 없습니다")
    year = analysis_year()
    stats = collect_energy_all(db, year, lambda f, m: log(m) if int(f * 100) % 5 == 0 else None, regions=leaves)
    build_parcel_grid(db)
    return {"rows": stats["inserted"] + stats["updated"], "message": f"{year}년 법정동·리 {len(leaves)}곳, 요청 {stats['requests']:,}회, 새 행 {stats['inserted']:,}", "year": year}


def collect_energy_years(db: Any, code: str, years: list[int], *, log: Log = print) -> dict[str, Any]:
    """건축HUB all-parcel energy of a prepared region for past years (the region step takes only the analysis year).

    Years run newest first; the provider's daily quota stops the run and leaves the remaining years for the next run
    (answers already received are cached on disk, so a re-run does not spend the quota again)."""
    from .energy_parcels import HUB_FIRST_YEAR, build_parcel_grid, collect_energy_all
    region = db.get(StudyRegion, code)
    if region is None:
        raise ValueError(f"준비한 지역이 아닙니다: {code}")
    leaves = legal_leaves(db, region.legal_codes or [])
    if not leaves:
        raise ValueError("이 지역의 법정동·리 코드가 없습니다")
    done: dict[int, Any] = {}
    left: list[int] = []
    quota = False
    for year in sorted({y for y in years if y >= HUB_FIRST_YEAR}, reverse=True):
        if quota:
            left.append(year)
            continue
        try:
            stats = collect_energy_all(db, year, lambda f, m: log(m) if int(f * 100) % 10 == 0 else None, regions=leaves)
            done[year] = {"requests": stats["requests"], "inserted": stats["inserted"], "updated": stats["updated"]}
            log(f"{code} {year}: 요청 {stats['requests']:,}회, 새 행 {stats['inserted']:,}")
            _mark_energy_year(db, region, year, "DONE")
        except ExternalError as exc:
            db.rollback()
            status, message = _classify(exc)
            log(f"{code} {year}: {status} {message}")
            left.append(year)
            _mark_energy_year(db, region, year, status)  # a year stopped half way stays 잠정값 (energy_parcels.region_year_complete)
            quota = status == "WAITING"  # daily quota: stop here; other errors: try the next year
    if done:
        build_parcel_grid(db)
    return {"region": code, "done": done, "left": sorted(left), "years_before_hub": sorted(y for y in years if y < HUB_FIRST_YEAR)}


def _mark_energy_year(db: Any, region: StudyRegion, year: int, status: str) -> None:
    """``study_regions.datasets.energy_years[year]``: DONE only when every 법정동 × month of the year was answered."""
    try:
        db.refresh(region, with_for_update=True)
    except Exception:  # noqa: BLE001 - SQLite in tests
        db.rollback()
        db.refresh(region)
    datasets = dict(region.datasets or {})
    years = dict(datasets.get("energy_years") or {})
    years[str(year)] = status
    datasets["energy_years"] = years
    region.datasets = datasets
    db.commit()


def step_kapt_energy(db: Any, region: StudyRegion, log: Log) -> dict[str, Any]:
    from .kapt_energy import collect_kapt_energy
    year = analysis_year()
    stats = collect_kapt_energy(db, year, "full", region=region.code, progress=lambda f, m: log(m) if int(f * 100) % 10 == 0 else None)
    if stats.get("failed"):
        raise ExternalError(f"K-apt 제공기관 일시 오류로 {stats['failed']}개 단지·월이 비었습니다. 다시 실행하면 그 달만 요청합니다")
    return {"rows": stats.get("normalized", 0), "message": f"{year}년 요청 {stats['requested']:,}회 / 유효 {stats['normalized']:,} · 미보고 {stats['not_reported']:,} · 이상값 {stats['suspect']:,}", "year": year}


def step_finalize(db: Any, region: StudyRegion, log: Log) -> dict[str, Any]:
    """Energy ↔ grid links and the default 대상지 (the cell with the most K-apt households, else the centre cell)."""
    from .kapt import ApartmentComplex, merge_energy_coordinates
    try:
        merge_energy_coordinates(db, analysis_year())
    except Exception as exc:  # noqa: BLE001 - linking is best effort; the map still shows the layers
        db.rollback()
        log(f"에너지-격자 연결 실패: {type(exc).__name__}")
    ids = region_grid_ids(db, region.code)
    households: dict[str, int] = {}
    for row in db.scalars(select(ApartmentComplex).where(ApartmentComplex.grid_id.is_not(None))):
        if row.grid_id in ids and region.legal_codes and (row.bjd_code or "")[:5] in region.legal_codes:
            households[row.grid_id] = households.get(row.grid_id, 0) + (row.households or 0)
    if households:
        region.default_grid_id = max(households, key=lambda g: (households[g], g))
        reason = f"K-apt 세대수가 가장 많은 격자 ({households[region.default_grid_id]:,}세대)"
    else:
        region.default_grid_id = centre_cell(region, ids)
        reason = "지역 중심 격자 (공동주택 자료 없음)"
    db.commit()
    from .area import forget_inputs
    forget_inputs()
    return {"rows": len(ids), "message": f"기본 대상지 {region.default_grid_id}: {reason}"}


def centre_cell(region: StudyRegion, ids: frozenset[str] | set[str]) -> str | None:
    """The analysis cell under the region centre (else the middle one of the sorted ids)."""
    if not ids:
        return None
    if region.center_lon is not None and region.center_lat is not None:
        from pyproj import Transformer
        x, y = Transformer.from_crs(4326, 5179, always_xy=True).transform(region.center_lon, region.center_lat)
        centre = f"cell_{int(x // 500 * 500)}_{int(y // 500 * 500)}"
        if centre in ids:
            return centre
    ordered = sorted(ids)
    return ordered[len(ordered) // 2]


RUNNERS: dict[str, Callable[[Any, StudyRegion, Log], dict[str, Any]]] = {
    "grid": step_grid, "sgis_admin": step_sgis_admin, "complexes": step_complexes, "weather": step_weather,
    "zoning": _vworld_step("zoning"), "buildings": _vworld_step("buildings"), "cadastral": _vworld_step("cadastral"),
    "zoning_other": _vworld_multi(("zoning_management", "zoning_agriculture", "zoning_conservation")),
    "special_areas": _vworld_multi(("greenbelt", "district_plan")), "ordinance": step_ordinance,
    "register": step_register, "building_energy": step_building_energy, "kapt_energy": step_kapt_energy, "finalize": step_finalize,
}
REQUIRES = {step: ("grid",) for step in STEPS if step not in ("grid", "ordinance")}
REQUIRES["kapt_energy"] = ("grid", "complexes")


def prepare_region(db: Any, code: str, steps: list[str] | None = None, *, log: Log = print, force: bool = False) -> dict[str, Any]:
    """Run the preparation steps of one region in order. Finished steps are skipped unless ``force``."""
    region = create_region(db, code)
    db.refresh(region)
    wanted = [step for step in STEPS if steps is None or step in steps]
    region.status = "PREPARING"
    region.message = "지역 자료를 수집하는 중입니다"
    db.commit()
    for step in wanted:
        state = (region.datasets or {}).get(step, {}).get("status")
        if state in DONE_STATES and not force and step != "finalize":
            continue
        blocked = [need for need in REQUIRES.get(step, ()) if (region.datasets or {}).get(need, {}).get("status") != "DONE"]
        if blocked:
            _mark(db, region, step, "PENDING", f"먼저 필요한 단계: {', '.join(STEP_LABELS[b] for b in blocked)}")
            continue
        _mark(db, region, step, "RUNNING", "수집 중")
        progress_log = _progress_logger(db, region, step, log)
        try:
            result = RUNNERS[step](db, region, progress_log)
        except Exception as exc:  # noqa: BLE001 - one step never stops the others
            db.rollback()
            region = db.get(StudyRegion, code)
            status, message = _classify(exc)
            _mark(db, region, step, status, message)
            log(f"{STEP_LABELS[step]}: {status} {message}")
            continue
        region = db.get(StudyRegion, code)
        status = result.pop("status", "DONE")
        _mark(db, region, step, status, result.pop("message", None), **{k: v for k, v in result.items() if k in ("rows", "year")})
        log(f"{STEP_LABELS[step]}: {status}")
    region = db.get(StudyRegion, code)
    db.refresh(region)  # sessions keep objects after commit: read what other processes wrote
    region.status = overall_status(region.datasets or {})
    waiting = [STEP_LABELS[s] for s in STEPS if (region.datasets or {}).get(s, {}).get("status") == "WAITING"]
    region.message = ("준비 완료" if region.status == "READY"
                      else f"일일 호출 한도로 남은 단계: {', '.join(waiting)} — 한도가 풀리면 이어서 수집합니다" if waiting
                      else "일부 단계가 끝나지 않았습니다 (단계별 상태 참고)")
    if code == DEFAULT_REGION and not waiting:
        # The original study area's layers came from the Jeonju collection, not from these steps.
        region.status, region.message = "READY", "최초 연구 지역 (기존 자료 + 추가 단계)"
    region.updated_at = now()
    db.commit()
    forget_region_cache(code)
    return {"code": code, "status": region.status, "datasets": region.datasets}


def open_region(db: Any, code: str, *, log: Log = print) -> StudyRegion:
    """Analysis cells of any 시·군·구 from the national layers (the basic map), built once in seconds.

    Runs in the caller's process (not the one-region-at-a-time worker queue): the grid, SGIS 행정동 and 조례 steps read
    data the national collection already stored; weather is a single request and may fail without blocking the map.
    The region's own collection (energy, buildings, zoning, register) stays a separate, explicit request.
    """
    import threading
    region = create_region(db, code)
    if region.grid_count or code == DEFAULT_REGION:
        return region
    lock = _OPEN_LOCKS.setdefault(code, threading.Lock())
    with lock:
        db.refresh(region)
        if region.grid_count:
            return region
        if region.status == "PREPARING" and (region.datasets or {}).get("grid", {}).get("status") in ("RUNNING", "QUEUED"):
            raise RuntimeError(f"{region.name}의 격자를 다른 작업이 만드는 중입니다. 잠시 뒤 다시 여세요")
        previous = region.message
        steps = [step for step in BASIC_STEPS if (region.datasets or {}).get(step, {}).get("status") not in DONE_STATES]
        prepare_region(db, code, steps, log=log)
        region = db.get(StudyRegion, code)
        db.refresh(region)
        if (region.datasets or {}).get("grid", {}).get("status") == "FAILED":
            # e.g. a border cell another region inserted at the same moment: the second run finds it and links it.
            prepare_region(db, code, ["grid"], log=log)
        region = db.get(StudyRegion, code)
        db.refresh(region)
        if region.grid_count and not any((region.datasets or {}).get(s, {}).get("status") in ("RUNNING", "QUEUED") for s in STEPS):
            from .regions import detail_level
            if detail_level(region) == "BASIC":
                region.message = "기본 지도: 전국 공통 자료(SGIS 격자 통계·행정동·K-apt 단지 목록·조례)만 있습니다. 에너지·건물·용도지역은 상세 자료 수집 뒤 채워집니다"
            elif previous:
                region.message = previous
            db.commit()
        return region


def _progress_logger(db: Any, region: StudyRegion, step: str, log: Log) -> Log:
    """Write the latest progress line into the step (at most every few seconds)."""
    import time
    last = [0.0]

    def write(message: str) -> None:
        log(message)
        if time.monotonic() - last[0] < 5:
            return
        last[0] = time.monotonic()
        try:
            db.refresh(region, with_for_update=True)
            datasets = dict(region.datasets or {})
            item = dict(datasets.get(step) or {})
            item["message"] = str(message)[:200]
            datasets[step] = item
            region.datasets = datasets
            db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
    return write


def next_quota_reset() -> datetime:
    """00:20 KST of the next day (data.go.kr quotas reset at midnight KST)."""
    kst = timezone(timedelta(hours=9))
    local = now().astimezone(kst)
    target = (local + timedelta(days=1)).replace(hour=0, minute=20, second=0, microsecond=0)
    return target.astimezone(timezone.utc)
