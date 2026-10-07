"""The shared data standard (docs/DATA_STANDARD.md) made checkable and applicable.

``apply_standard`` brings stored values that an earlier rule produced in line with the current one (version
``VERSION``): degree days (HDD 18 °C · CDD 24 °C, from the daily data that is kept), and the stored K-apt
electricity carbon (the year's GIR factor). It never touches raw files and never turns a missing value into 0;
a value that cannot be recomputed under the new rule (no daily data left) is set to NULL, not kept under the
old rule.

``check_standard`` counts what does not follow the standard, in the database and in CSV tables a teammate hands
over, and writes ``DATA_DIR/ops/standard-check.json`` (shown on the guide page).
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from sqlalchemy import func, select, text

from .degree_days import CDD_BASE_C, HDD_BASE_C, RULE, RULE_ID, degree_days

VERSION = "1.0"
ELECTRICITY_UNDERREPORT_KWH_PER_HOUSEHOLD = 2000.0  # urban-carbon config/rules.yaml electricity_underreport (ADR 0012)
DOC = "docs/DATA_STANDARD.md"
Log = Callable[[str], None]

NULL_MARKERS = {"-", "N/A", "n/a", "NA", "NULL", "null", "None", "nan", "NaN", "#N/A"}
UNIT_SUFFIXES = ("_kwh", "_mwh", "_m2", "_m3", "_kgco2eq", "_tco2e", "_tco2eq", "_c", "_persons", "_pct", "_count", "_households",
                 "_mm", "_m", "_kw", "_mj", "_won", "_days", "_ratio", "_share", "_year", "_years", "_months", "_cells")
NUMERIC_FREE = {"year", "month", "use_ym", "year_month", "x", "y", "x_min_m", "y_min_m", "bun", "ji", "lot_type", "households",
                "floors", "id", "seq"}
CELL_RE = re.compile(r"^cell_(\d+)_(\d+)$")
SGIS500_RE = re.compile(r"^[가나다라마바사아]{2}\d{2}[ab]\d{2}[ab]$")


def _root(data_dir: str | Path | None = None) -> Path:
    return Path(data_dir or os.getenv("DATA_DIR", "data"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def marker_path(data_dir: str | Path | None = None) -> Path:
    return _root(data_dir) / "ops" / "standard.json"


def applied_version(data_dir: str | Path | None = None) -> str | None:
    try:
        return json.loads(marker_path(data_dir).read_text(encoding="utf-8")).get("version")
    except (OSError, ValueError):
        return None


# --------------------------------------------------------------------------- apply
def _kma_degree_days(db: Any) -> dict[str, tuple[float | None, float | None]]:
    """use_ym → (HDD, CDD) from the stored KMA daily means (one value per date)."""
    import calendar
    from .kma_asos import WeatherDailyObservation
    by_month: dict[str, dict[str, float]] = defaultdict(dict)
    for date, temp in db.execute(select(WeatherDailyObservation.observed_date, WeatherDailyObservation.avg_temperature_c)):
        if date and temp is not None:
            by_month[date[:7].replace("-", "")][date] = temp
    out = {}
    for ym, days in by_month.items():
        out[ym] = degree_days(days.values(), calendar.monthrange(int(ym[:4]), int(ym[4:]))[1])
    return out


def recompute_degree_days(db: Any, data_dir: str | Path | None = None, *, log: Log = print, fetch: bool = True) -> dict[str, int]:
    """Recompute every stored monthly HDD/CDD under the current rule. Returns counts per table."""
    from .domain import monthly_weather
    from .kma_asos import WeatherMonthlyObservation, refresh_effective_weather
    from .regions import RegionWeatherMonthly
    stats = {"kma_months": 0, "era5_months": 0, "era5_cleared": 0, "region_months": 0, "region_cleared": 0}
    kma = _kma_degree_days(db)
    era5_years: set[int] = set()
    for row in db.scalars(select(WeatherMonthlyObservation)):
        if row.source_type == "OFFICIAL":
            hdd, cdd = kma.get(row.use_ym, (None, None))
            row.hdd, row.cdd = hdd, cdd
            stats["kma_months"] += 1
        else:
            era5_years.add(int(row.use_ym[:4]))
    db.flush()
    raw = _root(data_dir) / "raw"
    for year in sorted(era5_years):
        payload = None
        path = raw / f"weather-{year}.json"
        try:
            if path.exists():
                payload = json.loads(path.read_text(encoding="utf-8"))
            elif fetch:
                from .collectors import client
                params = dict(latitude=35.8242, longitude=127.1480, start_date=f"{year}-01-01", end_date=f"{year}-12-31",
                              daily="temperature_2m_mean,temperature_2m_min,temperature_2m_max,precipitation_sum", timezone="Asia/Seoul",
                              models="era5_land")
                payload = json.loads(client.get("weather", "archive", "https://archive-api.open-meteo.com/v1/archive", params)["body"])
        except Exception as exc:  # noqa: BLE001 - an unreachable fallback month is cleared below, not guessed
            log(f"ERA5 {year} 다시 받기 실패: {type(exc).__name__}")
        months = {m["use_ym"]: m for m in monthly_weather(payload)} if payload else {}
        for row in db.scalars(select(WeatherMonthlyObservation).where(WeatherMonthlyObservation.source_type != "OFFICIAL",
                                                                      WeatherMonthlyObservation.use_ym.startswith(str(year)))):
            m = months.get(row.use_ym)
            if m:
                row.hdd, row.cdd = m["hdd"], m["cdd"]
                stats["era5_months"] += 1
            else:
                row.cdd = None  # no daily data left to apply the new cooling base: missing, not the old-rule value
                stats["era5_cleared"] += 1
    db.flush()
    refresh_effective_weather(db)
    regions = sorted(set(db.scalars(select(RegionWeatherMonthly.region_code).distinct())))
    for code in regions:
        path = raw / "weather-regions" / f"{code}.json"
        months = {}
        if path.exists():
            try:
                months = {m["use_ym"]: m for m in monthly_weather(json.loads(path.read_bytes()))}
            except (ValueError, KeyError) as exc:
                log(f"{code} 기상 원본을 읽지 못함: {type(exc).__name__}")
        for row in db.scalars(select(RegionWeatherMonthly).where(RegionWeatherMonthly.region_code == code)):
            m = months.get(row.use_ym)
            if m:
                row.hdd, row.cdd = m["hdd"], m["cdd"]
                stats["region_months"] += 1
            else:
                row.cdd = None
                stats["region_cleared"] += 1
    db.commit()
    log(f"냉난방도일 다시 계산 ({RULE}): {stats}")
    return stats


def recompute_kapt_carbon(db: Any, *, log: Log = print) -> dict[str, int]:
    """Stored K-apt electricity carbon = quantity × the year's GIR factor (NULL before 2019 or when not SUCCESS)."""
    from .emissions import electricity_factor_for_year
    years = [int(y) for y in db.scalars(text("SELECT DISTINCT left(year_month, 4) FROM apartment_energy_monthly")) if y and y.isdigit()]
    changed = 0
    for year in sorted(years):
        factor = electricity_factor_for_year(year)
        result = db.execute(text(
            "UPDATE apartment_energy_monthly SET electricity_carbon_kg = CASE WHEN quality_status = 'SUCCESS' AND electricity_quantity IS NOT NULL "
            "AND CAST(:f AS double precision) IS NOT NULL THEN electricity_quantity * CAST(:f AS double precision) ELSE NULL END "
            "WHERE left(year_month, 4) = :y"), {"f": factor, "y": str(year)})
        changed += result.rowcount or 0
    db.commit()
    log(f"K-apt 전력 탄소 다시 계산: {changed:,}행")
    return {"kapt_rows": changed}


def apply_standard(db: Any, data_dir: str | Path | None = None, *, log: Log = print, fetch: bool = True) -> dict[str, Any]:
    """Bring stored values to the current standard and record the version applied."""
    from .emissions import collect_factors
    result: dict[str, Any] = {"version": VERSION, "rule": RULE, "at": _now()}
    try:
        result["factors"] = collect_factors(db)
    except Exception as exc:  # noqa: BLE001 - a missing GIR text is reported by the check, not fatal here
        db.rollback()
        result["factors_error"] = f"{type(exc).__name__}: {exc}"
    result["degree_days"] = recompute_degree_days(db, data_dir, log=log, fetch=fetch)
    result["kapt"] = recompute_kapt_carbon(db, log=log)
    path = marker_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return result


# --------------------------------------------------------------------------- check
def _item(cid: str, label: str, status: str, detail: str, count: int | None = None, **extra: Any) -> dict[str, Any]:
    return {"id": cid, "label": label, "status": status, "detail": detail, "count": count, **extra}


def check_database(db: Any, data_dir: str | Path | None = None, *, raw_sample: int | None = None) -> list[dict[str, Any]]:
    from .emissions import ELECTRICITY_SCHEDULE, electricity_factor_for_year
    from .service import factors_for
    items: list[dict[str, Any]] = []

    negative = db.scalar(text("SELECT count(*) FROM energy_monthly WHERE usage_kwh < 0")) or 0
    items.append(_item("energy_negative", "건축HUB 음수 사용량은 NULL (4절)", "OK" if not negative else "FAIL",
                       "음수 행 없음" if not negative else f"음수 사용량 {negative:,}행: NULL로 두고 원값은 raw_record에", negative))
    zero = db.scalar(text("SELECT count(*) FROM energy_monthly WHERE usage_kwh = 0")) or 0
    items.append(_item("energy_zero", "건축HUB 0은 제공기관이 준 관측 0만 (1절)", "INFO",
                       f"관측 0 {zero:,}행 (제공기관 값 그대로, 결측을 0으로 바꾼 것 아님)", zero))

    leftover = db.scalar(text(
        "SELECT count(*) FROM apartment_energy_monthly WHERE quality_status = 'NOT_REPORTED' AND (electricity_quantity IS NOT NULL "
        "OR gas_quantity IS NOT NULL OR heating_quantity IS NOT NULL OR hot_water_quantity IS NOT NULL OR water_quantity IS NOT NULL)")) or 0
    items.append(_item("kapt_not_reported", "K-apt 미보고 달의 양은 모두 NULL (4절)", "OK" if not leftover else "FAIL",
                       "미보고 달에 남은 양 없음" if not leftover else f"미보고인데 양이 남은 행 {leftover:,}", leftover))

    bad_carbon = 0
    for year, n in db.execute(text("SELECT left(year_month,4), count(*) FROM apartment_energy_monthly GROUP BY 1")):
        factor = electricity_factor_for_year(int(year)) if year and year.isdigit() else None
        if factor:
            bad = db.scalar(text("SELECT count(*) FROM apartment_energy_monthly WHERE left(year_month,4) = :y AND quality_status = 'SUCCESS' "
                                 "AND electricity_quantity IS NOT NULL AND (electricity_carbon_kg IS NULL OR "
                                 "abs(electricity_carbon_kg - electricity_quantity * :f) > 0.005 * electricity_quantity * :f)"),
                            {"y": year, "f": factor}) or 0
        else:
            bad = db.scalar(text("SELECT count(*) FROM apartment_energy_monthly WHERE left(year_month,4) = :y AND electricity_carbon_kg IS NOT NULL"),
                            {"y": year}) or 0
        bad_carbon += bad
    items.append(_item("kapt_carbon", "K-apt 전력 탄소 = 사용량 × 그해 계수 (5.4절)", "OK" if not bad_carbon else "WARN",
                       "모두 그해 계수" if not bad_carbon else f"{bad_carbon:,}행이 다른 계수 → apply-standard", bad_carbon))

    low = db.execute(text(
        "SELECT count(*), count(DISTINCT e.complex_code) FROM (SELECT complex_code, left(year_month,4) y, sum(electricity_quantity) kwh, count(*) n "
        "FROM apartment_energy_monthly WHERE quality_status = 'SUCCESS' AND electricity_quantity IS NOT NULL GROUP BY complex_code, left(year_month,4), source) e "
        "JOIN apartment_complexes c ON c.kapt_code = e.complex_code WHERE e.n = 12 AND c.households > 0 AND e.kwh / c.households < :limit"),
        {"limit": ELECTRICITY_UNDERREPORT_KWH_PER_HOUSEHOLD}).one()
    items.append(_item("kapt_underreport", f"단지 세대당 전기 {ELECTRICITY_UNDERREPORT_KWH_PER_HOUSEHOLD:,.0f} kWh/년 미만은 누락 의심으로 표시 (4절, 팀 기준)", "INFO",
                       f"12개월 단지-연도 중 {low[0]:,}건({low[1]:,}개 단지): 값은 그대로 두고 해석 때 주의", low[0]))

    mismatched = []
    for year in range(2015, datetime.now().year + 1):
        stored = (factors_for(db, year).get("ELECTRICITY") or {}).get("factor")
        expected = electricity_factor_for_year(year)
        if (stored is None) != (expected is None) or (stored is not None and abs(stored - expected) > 1e-9):
            mismatched.append(f"{year}: DB {stored} / 기준 {expected}")
    items.append(_item("electricity_factors", "연도별 전력 계수 = 기준 표 (5.4절)", "OK" if not mismatched else "FAIL",
                       "기준 표와 같음 (" + ", ".join(f"{p[:4]}~ {f}" for p, f in ELECTRICITY_SCHEDULE) + ")" if not mismatched
                       else "다름: " + "; ".join(mismatched[:6]) + " → GIR 원문을 data/raw/research/gir에 두고 apply-standard", len(mismatched)))

    kma = _kma_degree_days(db)
    from .kma_asos import WeatherMonthlyObservation
    off = 0
    for row in db.scalars(select(WeatherMonthlyObservation).where(WeatherMonthlyObservation.source_type == "OFFICIAL")):
        hdd, cdd = kma.get(row.use_ym, (None, None))
        if (row.cdd is None) != (cdd is None) or (cdd is not None and abs(row.cdd - cdd) > 0.05) or \
                (row.hdd is None) != (hdd is None) or (hdd is not None and abs(row.hdd - hdd) > 0.05):
            off += 1
    partial = db.scalar(text("SELECT count(*) FROM weather_monthly_observations WHERE valid_day_count < expected_day_count AND (hdd IS NOT NULL OR cdd IS NOT NULL)")) or 0
    partial += db.scalar(text("SELECT count(*) FROM region_weather_monthly WHERE days_observed < expected_days AND (hdd IS NOT NULL OR cdd IS NOT NULL)")) or 0
    version = applied_version(data_dir)
    status = "OK" if not off and not partial and version == VERSION else ("FAIL" if partial else "WARN")
    items.append(_item("degree_days", f"냉난방도일 {RULE}, 빠진 날이 있는 달은 NULL (5.10절)", status,
                       f"ASOS 월 {off}개가 일자료 재계산과 다름, 빠진 날 있는데 값 있는 달 {partial}개, 적용 판 {version or '없음'}"
                       + ("" if status == "OK" else " → apply-standard"), off + partial, hdd_base_c=HDD_BASE_C, cdd_base_c=CDD_BASE_C))

    bad_ids = db.scalar(text(r"SELECT count(*) FROM grid_500m WHERE id !~ '^cell_[0-9]+_[0-9]+$'")) or 0
    off_grid = db.scalar(text(r"SELECT count(*) FROM grid_500m WHERE id ~ '^cell_[0-9]+_[0-9]+$' AND "
                              r"(split_part(id,'_',2)::bigint % 500 <> 0 OR split_part(id,'_',3)::bigint % 500 <> 0)")) or 0
    items.append(_item("grid_ids", "칸 ID = cell_<왼쪽아래 x>_<y>, 500의 배수 (3절)", "OK" if not bad_ids else "WARN",
                       f"형식이 다른 ID {bad_ids:,}개" + (f", 500m 눈금이 아닌 칸 {off_grid:,}개(예전 시험 격자)" if off_grid else ""), bad_ids + off_grid))

    raw = _root(data_dir) / "raw"
    locations = [loc for (loc,) in db.execute(text("SELECT storage_location FROM raw_data_assets WHERE storage_location LIKE '/data/raw/%'"))]
    checked = locations if not raw_sample or len(locations) <= raw_sample else locations[::max(1, len(locations) // raw_sample)]
    missing = [loc for loc in checked if not (raw / loc[len("/data/raw/"):]).exists()]
    scope = f"기록 {len(locations):,}건" + (f" 중 표본 {len(checked):,}건" if len(checked) < len(locations) else "")
    items.append(_item("raw_files", "원본은 data/raw에 그대로 (1·7절)", "OK" if not missing else "WARN",
                       f"{scope}, 파일 없음 {len(missing):,}건" + (f" (예: {missing[0]})" if missing else ""), len(missing)))
    return items


def _encoding(raw: bytes) -> tuple[str | None, bool]:
    bom = raw.startswith(b"\xef\xbb\xbf")
    try:
        raw.decode("utf-8")
        return "utf-8", bom
    except UnicodeDecodeError:
        return None, bom


def check_csv(path: str | Path) -> list[dict[str, Any]]:
    """A table handed over by a teammate: encoding, empty-cell convention, keys, units, ID formats (7절)."""
    p = Path(path)
    name = p.name
    if not p.exists():
        return [_item("csv_missing", f"{name}", "FAIL", "파일이 없습니다")]
    raw = p.read_bytes()
    encoding, bom = _encoding(raw)
    items = [_item("csv_encoding", f"{name}: UTF-8", "OK" if encoding else "FAIL",
                   ("UTF-8" + (" (BOM: 엑셀용 사본)" if bom else "")) if encoding else "UTF-8이 아닙니다(cp949 등) → UTF-8로 다시 저장")]
    if not encoding:
        return items
    reader = csv.reader(io.StringIO(raw.decode("utf-8-sig")))
    try:
        header = next(reader)
    except StopIteration:
        return items + [_item("csv_empty", f"{name}: 내용", "FAIL", "빈 파일")]
    header = [h.strip() for h in header]
    dup = sorted({h for h in header if header.count(h) > 1})
    items.append(_item("csv_header", f"{name}: 열 이름", "OK" if not dup and all(header) else "FAIL",
                       f"열 {len(header)}개" + (f", 중복 {dup}" if dup else "") + (", 이름 없는 열" if not all(header) else "")))
    rows = list(reader)
    markers: dict[str, int] = defaultdict(int)
    numeric: dict[str, int] = defaultdict(int)
    negative: dict[str, int] = defaultdict(int)
    filled: dict[str, int] = defaultdict(int)
    for row in rows:
        for col, value in zip(header, row):
            v = value.strip()
            if not v:
                continue
            if v in NULL_MARKERS:
                markers[col] += 1
                continue
            filled[col] += 1
            try:
                number = float(v.replace(",", ""))
            except ValueError:
                continue
            numeric[col] += 1
            if number < 0 and col.endswith(("_kwh", "_m2", "_tco2e", "_kgco2eq", "_persons")):
                negative[col] += 1
    total_markers = sum(markers.values())
    items.append(_item("csv_nulls", f"{name}: 빈칸 = NULL", "OK" if not total_markers else "WARN",
                       "빈칸만 씀" if not total_markers else
                       "빈칸 대신 쓴 표기 " + ", ".join(f"{c} {n}개" for c, n in sorted(markers.items())[:5]) + " → 빈칸으로", total_markers))
    no_unit = [c for c in header if numeric.get(c) and numeric[c] >= 0.9 * max(filled.get(c, 0), 1)
               and not c.lower().endswith(UNIT_SUFFIXES) and c.lower() not in NUMERIC_FREE and not c.lower().endswith(("_id", "_code", "_cd"))
               and not c.lower().startswith(("is_", "has_", "n_"))]
    items.append(_item("csv_units", f"{name}: 숫자 열 이름에 단위", "OK" if not no_unit else "WARN",
                       "단위 접미사 있음" if not no_unit else "단위가 이름에 없는 숫자 열: " + ", ".join(no_unit[:8]), len(no_unit)))
    neg = sum(negative.values())
    items.append(_item("csv_negative", f"{name}: 음수 사용량·면적·배출량 없음", "OK" if not neg else "FAIL",
                       "없음" if not neg else ", ".join(f"{c} {n}개" for c, n in negative.items()), neg))
    keys = _key_columns(header)
    if keys:
        idx = [header.index(k) for k in keys]
        seen: set[tuple[str, ...]] = set()
        dups = 0
        for row in rows:
            key = tuple(row[i].strip() if i < len(row) else "" for i in idx)
            dups += key in seen
            seen.add(key)
        items.append(_item("csv_keys", f"{name}: 키 {'+'.join(keys)} 중복 없음", "OK" if not dups else "FAIL",
                           f"{len(rows):,}행, 중복 {dups:,}" , dups))
    for col, pattern, label in (("grid_id", CELL_RE, "cell_<x>_<y>"), ("grid_id_500m", SGIS500_RE, "SGIS 500m 코드"),
                                ("grid_cd_500m", SGIS500_RE, "SGIS 500m 코드")):
        if col in header:
            i = header.index(col)
            bad = sum(1 for row in rows if i < len(row) and row[i].strip() and not pattern.match(row[i].strip()))
            items.append(_item(f"csv_{col}", f"{name}: {col} 형식 ({label})", "OK" if not bad else "FAIL", f"형식이 다른 값 {bad:,}개", bad))
    return items


def _key_columns(header: list[str]) -> list[str]:
    h = set(header)
    if {"sigungu_code", "bjdong_code", "lot_type", "bun", "ji", "use_ym", "energy_type"} <= h:
        return ["sigungu_code", "bjdong_code", "lot_type", "bun", "ji", "use_ym", "energy_type"]
    if {"complex_code", "year_month"} <= h:
        return ["complex_code", "year_month"] + (["source"] if "source" in h else [])
    for grid in ("grid_id", "grid_id_500m", "grid_id_100m", "grid_cd_500m"):
        if grid in h:
            return [grid] + [c for c in ("year", "region") if c in h]
    return []


def check_standard(db: Any | None, data_dir: str | Path | None = None, csv_paths: Iterable[str | Path] = (), *, write: bool = True,
                   raw_sample: int | None = None) -> dict[str, Any]:
    items = check_database(db, data_dir, raw_sample=raw_sample) if db is not None else []
    for path in csv_paths:
        items += check_csv(path)
    counts = defaultdict(int)
    for item in items:
        counts[item["status"]] += 1
    report = {"version": VERSION, "doc": DOC, "rule": RULE, "rule_id": RULE_ID, "checked_at": _now(), "applied_version": applied_version(data_dir),
              "summary": dict(counts), "ok": not counts.get("FAIL"), "items": items}
    if write and db is not None:
        out = _root(data_dir) / "ops" / "standard-check.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report


def last_check(data_dir: str | Path | None = None) -> dict[str, Any] | None:
    try:
        return json.loads((_root(data_dir) / "ops" / "standard-check.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def summary() -> dict[str, Any]:
    """The rules a screen shows next to the last check (numbers come from the code the calculations use)."""
    from .emissions import ELECTRICITY_SCHEDULE, GAS_FACTOR, GAS_NCV_FACTOR
    return {
        "version": VERSION, "doc": DOC,
        "electricity_factors": [{"published": p, "factor": f} for p, f in ELECTRICITY_SCHEDULE],
        "gas_factor": GAS_FACTOR, "gas_factor_ncv": GAS_NCV_FACTOR,
        "degree_days": {"rule": RULE, "hdd_base_c": HDD_BASE_C, "cdd_base_c": CDD_BASE_C},
        "annual_rule": "12개월 모두 관측된 지번(단지)만 연간 합계",
        "pv_rule": _pv_rule(),
        "missing_rule": "없는 값은 NULL, 0과 구분",
    }


def _pv_rule() -> dict[str, Any]:
    from .solar import PERFORMANCE_RATIO, RULE as PV_RULE
    return {"rule": PV_RULE, "performance_ratio": PERFORMANCE_RATIO}
