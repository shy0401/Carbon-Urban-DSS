"""Fixed simulation cases and the cross-PC reproduction check (``python -m app.cli verify-cases``).

Each case is one thing a user does in the app — a region and an area, a plan and a target, a 3D site plan,
a legal-limit check, a report — written as the exact inputs the screen sends. The runner calls the same
engine functions the API uses and reads only: scenarios and reports are computed but never saved (the grid
report needs its plans in the session, so they are flushed and rolled back).

The recorded file (``backend/cases/simulation_cases.json``) keeps, for every case, the values and the
evidence sentences (근거 문장) the reference PC produced. Another PC that loaded the same data bundle
(``scripts\\dss.cmd MergeBundle`` or ``ImportBundle``) must give the same values: a ``dataset`` case compares
the row counts and sums the calculations read, so a different data version is told apart from a different
calculation.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

CASES_FILE = Path(__file__).resolve().parent.parent / "cases" / "simulation_cases.json"
ABS_TOL = 0.01      # numbers: |actual − expected| ≤ max(ABS_TOL, REL_TOL × |expected|) unless a case gives its own
REL_TOL = 1e-6
KST = timezone(timedelta(hours=9), "KST")   # 기록 시각 (일광절약시간 없음, 컨테이너 시간대와 무관)
LAST_YEAR = 2025    # dataset fingerprints stop here so months collected later do not change them

LABELS = {
    "label": "구역 이름", "grids": "구역 격자 수", "complexes": "구역 K-apt 단지 수",
    "event_year": "개발(사용승인) 연도", "effort.baseline_year": "감축 기준 연도", "effort.basis": "감축 기준 건물",
    "effort.baseline_kwh": "기준 전력 kWh", "effort.baseline_kgco2eq": "기준 전력 탄소 kgCO2eq",
    "effort.bau_kgco2eq": "개발 후(대책 없음) 탄소 kgCO2eq", "effort.target_kgco2eq": "목표 탄소 kgCO2eq",
    "effort.required_reduction_kgco2eq": "필요 감축량 kgCO2eq", "effort.new_only_efficiency_pct": "신축만으로 필요한 효율 개선 %",
    "effort.all_buildings_efficiency_pct": "전체 건물 효율 개선 %", "effort.pv_capacity_kw": "필요 태양광 kW",
    "effort.pv_yield_kwh_per_kw": "태양광 kW당 연 발전량", "effort.pv_basis": "발전량 근거",
    "gross_floor_area": "계획 연면적 m²", "far": "용적률 %", "bcr": "건폐율 %", "households": "세대수",
    "carbon_now_kg": "현재(기준) 탄소 kgCO2eq/년", "carbon_plan_kg": "계획 탄소 kgCO2eq/년", "carbon_change_pct": "탄소 변화 %",
    "legal_status": "법적 상한 1차 확인", "zoning.dominant_zone": "주된 용도지역", "zoning.far_limit": "용적률 상한 %",
    "zoning.bcr_limit": "건폐율 상한 %", "status": "결과 상태", "evaluated": "검토한 후보 수", "feasible": "조건을 만족한 후보 수",
}


# --------------------------------------------------------------------------- values

def flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    """Nested dicts → dotted keys (``effort.pv_capacity_kw``); lists and scalars stay as they are."""
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            out.update(flatten(item, f"{prefix}{key}."))
        return out
    return {prefix[:-1]: value}


def _round(value: Any) -> Any:
    if isinstance(value, float):
        return None if math.isnan(value) else round(value, 6)
    if isinstance(value, dict):
        return {str(k): _round(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_round(v) for v in value]
    return value


def same(expected: Any, actual: Any, tol: float | None = None) -> bool:
    if isinstance(expected, bool) or isinstance(actual, bool) or expected is None or actual is None:
        return type(expected) is type(actual) and expected == actual
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        limit = tol if tol is not None else max(ABS_TOL, REL_TOL * abs(expected))
        return abs(float(actual) - float(expected)) <= limit
    if isinstance(expected, list) and isinstance(actual, list):
        return len(expected) == len(actual) and all(same(e, a, tol) for e, a in zip(expected, actual))
    return expected == actual


def facts_hash(texts: list[str]) -> str:
    return hashlib.sha256("\n".join(texts).encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- case kinds

def _year_table(table: dict[Any, Any], pick: Callable[[dict[str, Any]], Any]) -> dict[str, Any]:
    return {str(y): pick(v or {}) for y, v in sorted(table.items(), key=lambda kv: int(kv[0]))}


def area_summary(result: dict[str, Any]) -> dict[str, Any]:
    h = result["history"]
    be = (h.get("building_energy") or {}).get("years") or {}
    comparison = result.get("before_after") or {}
    est = (comparison.get("metrics") or {}).get("estimated") or {}
    effort = result.get("effort") or {}
    options = effort.get("options") or {}
    pv = effort.get("pv_yield") or {}
    summary = {
        "label": h["area"].get("label"), "grids": len(h["area"].get("grid_ids") or []), "complexes": len(h["area"].get("complex_codes") or []),
        "kapt_electricity_kwh": _year_table(h["energy"], lambda v: (v.get("electricity") or {}).get("kwh")),
        "kapt_complete_parcels": _year_table(h["energy"], lambda v: (v.get("electricity") or {}).get("complete_parcels")),
        "building_electricity_kwh": {str(y): v.get("electricity_kwh") for y, v in sorted(be.items(), key=lambda kv: int(kv[0]))},
        "building_parcels": {str(y): v.get("electricity_complete") for y, v in sorted(be.items(), key=lambda kv: int(kv[0]))},
        "event_year": comparison.get("event_year") if comparison.get("available") else None,
        "estimated_change_kwh": est.get("change_kwh"), "event_added_kwh": est.get("event_added_kwh"),
        "facts": len(result.get("facts") or []),
    }
    if effort:
        summary["effort"] = {
            "available": effort.get("available"), "basis": effort.get("basis"), "baseline_year": effort.get("baseline_year"),
            "baseline_kwh": effort.get("baseline_kwh"), "baseline_kgco2eq": effort.get("baseline_kgco2eq"),
            "bau_kgco2eq": effort.get("bau_kgco2eq"), "target_kgco2eq": effort.get("target_kgco2eq"),
            "required_reduction_kgco2eq": effort.get("required_reduction_kgco2eq"),
            "new_only_efficiency_pct": options.get("new_only_efficiency_pct"), "all_buildings_efficiency_pct": options.get("all_buildings_efficiency_pct"),
            "pv_capacity_kw": options.get("pv_capacity_kw"), "pv_yield_kwh_per_kw": pv.get("kwh_per_kw"), "pv_basis": pv.get("basis"),
        }
    return summary


def run_area(db: Any, spec: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    from .area import analyze
    i = spec["input"]
    result = analyze(db, i["area"], i.get("from_year", 2015), i.get("to_year", LAST_YEAR), i.get("event_year"), i.get("window", 3),
                     i.get("plan"), i.get("target_pct"), i.get("pv_yield_kwh_per_kw"), region=i.get("region"),
                     effort_basis=i.get("effort_basis", "apartments"))
    return area_summary(result), [f["text"] for f in result["facts"]]


def run_area_report(db: Any, spec: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """The area report the 지역 시뮬레이션 screen writes (template wording, no local model): built, rendered, not saved."""
    from .area import analyze
    from .area_report import area_markdown, summarize_area
    i = spec["input"]
    result = analyze(db, i["area"], i.get("from_year", 2015), i.get("to_year", LAST_YEAR), i.get("event_year"), i.get("window", 3),
                     i.get("plan"), i.get("target_pct"), i.get("pv_yield_kwh_per_kw"), region=i.get("region"),
                     effort_basis=i.get("effort_basis", "apartments"))
    history = result["history"]
    snapshot = {"title": f"{history['area']['label']} 개발 영향·감축 검토", "created_at": "-", "area": history["area"],
                "history": {k: v for k, v in history.items() if k != "area"}, "effort": result["effort"], "facts": result["facts"],
                "summary": summarize_area(result["facts"], False), "evidence_hash": "-"}
    markdown = area_markdown(snapshot)
    summary = area_summary(result)
    summary["report"] = {"sections": markdown.count("\n## ") + markdown.startswith("## "), "table_rows": markdown.count("\n| "),
                         "mode": snapshot["summary"]["mode"]}
    return summary, [f["text"] for f in result["facts"]]


def scenario_summary(result: dict[str, Any]) -> dict[str, Any]:
    annual = result.get("annual") or {}
    zoning = result.get("zoning_check") or {}
    monthly = result.get("monthly") or []
    peak = max(monthly, key=lambda m: m["scenario"].get("electricity_kwh") or -1) if monthly else None
    zones = zoning.get("zones") or []
    return {
        "grid_id": result.get("grid_id"), "data_class": result.get("data_class"), "baseline_basis": result.get("baseline_basis"),
        "gross_floor_area": result.get("gross_floor_area"), "far": result.get("far"), "bcr": result.get("bcr"),
        "households": result.get("households"), "population": result.get("population"),
        "carbon_now_kg": (annual.get("current") or {}).get("carbon_kg"), "carbon_plan_kg": (annual.get("scenario") or {}).get("carbon_kg"),
        "electricity_plan_kwh": (annual.get("scenario") or {}).get("electricity_kwh"), "gas_plan_kwh": (annual.get("scenario") or {}).get("gas_kwh"),
        "carbon_change_pct": (result.get("percent_change") or {}).get("carbon_kg"),
        "carbon_per_person": result.get("carbon_per_person"),
        "peak_month": peak["use_ym"][-2:] if peak else None,
        "legal_status": result.get("legal_status"),
        "zoning": {"status": zoning.get("status"), "dominant_zone": zones[0].get("zone") if zones else None,
                   "dominant_share": zones[0].get("share") if zones else None, "far_limit": zoning.get("far_limit"),
                   "bcr_limit": zoning.get("bcr_limit"), "basis": zoning.get("basis")},
    }


def run_scenario(db: Any, spec: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    from .main import ScenarioInput, compute_scenario
    result = compute_scenario(db, ScenarioInput(**spec["input"]))
    db.rollback()
    return scenario_summary(result), list(result.get("assumptions") or [])


def run_optimize(db: Any, spec: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    from .main import OptimizationInput, compute_optimization
    result = compute_optimization(db, OptimizationInput(**spec["input"]))
    db.rollback()
    alts = result.get("alternatives") or []
    zoning = result.get("zoning_check") or {}
    summary = {"status": result.get("status"), "evaluated": result.get("evaluated"), "feasible": result.get("feasible"),
               "legal_status": result.get("legal_status"), "max_households_under_limit": result.get("max_households_under_limit"),
               "zoning": {"far_limit": zoning.get("far_limit"), "bcr_limit": zoning.get("bcr_limit")},
               "alternatives": [{"label": a.get("label"), "floors": a.get("floors"), "buildings": a.get("building_count"), "households": a.get("households"),
                                 "far": a.get("far"), "carbon_kg": a.get("annual_carbon_kg")} for a in alts]}
    return summary, [a.get("label") or "" for a in alts]


def run_zoning(db: Any, spec: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    from .zoning_limits import check_plan, site_zoning
    i = spec["input"]
    zoning = site_zoning(db, i["lon"], i["lat"], i["site_area"], i.get("rotation", 0.0), region_code=i.get("region"))
    check = check_plan(zoning, bcr=i.get("bcr"), far=i.get("far"), site_area_m2=i["site_area"], households=i.get("households"))
    special = zoning.get("special") or {}
    summary = {"status": zoning.get("status"), "zones": [[z.get("zone"), z.get("share")] for z in zoning.get("zones") or []],
               "far_limit": zoning.get("far_limit"), "bcr_limit": zoning.get("bcr_limit"), "basis": zoning.get("basis"),
               "greenbelt_share": (special.get("greenbelt") or {}).get("share"), "district_plans": len(special.get("district_plans") or []),
               "check": {"label": check.get("label"), "far": check.get("far"), "bcr": check.get("bcr")}}
    return summary, list(check.get("notes") or [])


def run_grid_report(db: Any, spec: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """The 500m grid report with the given plans compared: the plans live only in this session and are rolled back."""
    from .main import ScenarioInput, compute_scenario, _public
    from .models import Scenario, ScenarioResult
    from .reporting import create_snapshot, report_markdown, summarize, summary_pool
    i = spec["input"]
    try:
        ids = []
        for plan in i.get("scenarios") or []:
            request = ScenarioInput(**plan)
            result = compute_scenario(db, request)
            db.add(Scenario(id=result["id"], inputs=dict(request.model_dump(), grid_id=result["grid_id"], region=result["_region"])))
            db.flush()
            db.add(ScenarioResult(id=result["id"], result=_public(result)))
            db.flush()
            ids.append(result["id"])
        snapshot = create_snapshot(db, i["year"], i.get("grid_id"), ids, i.get("region"))
        snapshot["summary"] = summarize(summary_pool(snapshot), False)
        snapshot["id"] = "verify-cases"
        markdown = report_markdown(snapshot)
    finally:
        db.rollback()
    totals = snapshot.get("totals") or {}
    texts = [f["text"] for f in snapshot["facts"]] + [f["text"] for f in (snapshot.get("context") or {}).get("facts") or []]
    summary = {"grid_id": snapshot.get("grid_id"), "electricity_kwh": totals.get("electricity_kwh"), "gas_kwh": totals.get("gas_kwh"),
               "carbon_kg": totals.get("carbon_kg"), "facts": len(snapshot["facts"]), "context_facts": len((snapshot.get("context") or {}).get("facts") or []),
               "scenarios": len(ids), "cautions": len(snapshot.get("cautions") or []),
               "report": {"sections": markdown.count("\n## ") + markdown.startswith("## "), "mode": snapshot["summary"]["mode"]}}
    return summary, texts


def run_dataset(db: Any, spec: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Row counts and sums of what the calculations read for one region (up to LAST_YEAR), and the emission factors."""
    from sqlalchemy import func, select
    from .kapt_energy import ApartmentEnergyMonthly
    from .models import EmissionFactor, EnergyMonthly
    from .regions import GridRegion, scope
    from .solar import SolarMonthly
    region = spec["input"]["region"]
    sc = scope(db, region)
    year = func.substr(EnergyMonthly.use_ym, 1, 4)
    query = (select(year, EnergyMonthly.energy_type, func.count(), func.sum(EnergyMonthly.usage_kwh))
             .where(EnergyMonthly.use_ym <= f"{LAST_YEAR}12").group_by(year, EnergyMonthly.energy_type))
    clause = sc.legal_clause(EnergyMonthly.sigungu_code)
    if clause is not None:
        query = query.where(clause)
    building: dict[str, Any] = {}
    for y, kind, rows, total in db.execute(query):
        building[f"{y}_{kind}"] = [int(rows), round(float(total or 0), 1)]
    kyear = func.substr(ApartmentEnergyMonthly.year_month, 1, 4)
    kq = (select(kyear, func.count(), func.sum(ApartmentEnergyMonthly.electricity_quantity))
          .join(GridRegion, GridRegion.grid_id == ApartmentEnergyMonthly.grid_id)
          .where(GridRegion.region_code == sc.code, ApartmentEnergyMonthly.year_month <= f"{LAST_YEAR}12").group_by(kyear))
    kapt = {str(y): [int(rows), round(float(total or 0), 1)] for y, rows, total in db.execute(kq)}
    factors = sorted([f.energy_type, f.reference_year, f.factor] for f in db.scalars(select(EmissionFactor)))
    try:
        solar = db.scalar(select(func.count()).select_from(SolarMonthly).where(SolarMonthly.region_code == sc.code, SolarMonthly.irradiation_mj_m2.is_not(None),
                                                                                SolarMonthly.use_ym <= f"{LAST_YEAR}12"))
    except Exception:  # noqa: BLE001 - table not created yet
        db.rollback()
        solar = None
    summary = {"region": sc.code, "name": sc.name, "grids": len(sc.grid_ids), "building_energy": dict(sorted(building.items())),
               "kapt": dict(sorted(kapt.items())), "factors": factors, "solar_months": solar}
    return summary, []


RUNNERS: dict[str, Callable[[Any, dict[str, Any]], tuple[dict[str, Any], list[str]]]] = {
    "dataset": run_dataset, "area": run_area, "area_report": run_area_report, "scenario": run_scenario,
    "optimize": run_optimize, "zoning": run_zoning, "grid_report": run_grid_report,
}


# --------------------------------------------------------------------------- run and compare

def load(path: str | Path | None = None) -> dict[str, Any]:
    return json.loads(Path(path or CASES_FILE).read_text(encoding="utf-8"))


def run_one(db: Any, spec: dict[str, Any]) -> dict[str, Any]:
    kind = spec["kind"]
    if kind not in RUNNERS:
        return {"error": f"알 수 없는 사례 종류: {kind}"}
    try:
        summary, texts = RUNNERS[kind](db, spec)
    except Exception as exc:  # noqa: BLE001 - one case failing does not stop the others
        db.rollback()
        return {"error": f"{type(exc).__name__}: {str(getattr(exc, 'detail', exc))[:300]}"}
    return {"values": _round(flatten(summary)), "facts": texts, "facts_sha256": facts_hash(texts)}


def compare(spec: dict[str, Any], got: dict[str, Any]) -> dict[str, Any]:
    if "error" in got:
        return {"status": "ERROR", "message": got["error"], "diffs": []}
    expected = spec.get("expected")
    if not expected:
        return {"status": "NOT_RECORDED", "diffs": [], "checked": 0}
    tolerance = spec.get("tolerance") or {}
    diffs = []
    keys = sorted(set(expected["values"]) | set(got["values"]))
    for key in keys:
        e, a = expected["values"].get(key, "(없음)"), got["values"].get(key, "(없음)")
        if not same(e, a, tolerance.get(key)):
            diffs.append({"key": key, "label": LABELS.get(key, key), "expected": e, "actual": a})
    text_diffs = []
    if expected.get("facts_sha256") != got["facts_sha256"]:
        before, after = expected.get("facts") or [], got["facts"]
        text_diffs = [{"expected": e, "actual": a} for e, a in zip(before + [None] * (len(after) - len(before)), after + [None] * (len(before) - len(after))) if e != a]
    status = "MATCH" if not diffs and not text_diffs else "DIFF"
    return {"status": status, "diffs": diffs, "text_diffs": text_diffs, "checked": len(keys), "facts": len(got["facts"])}


def verify(db: Any, cases: dict[str, Any], only: set[str] | None = None, log: Callable[[str], None] = print) -> dict[str, Any]:
    results = []
    for spec in cases["cases"]:
        if only and spec["id"] not in only:
            continue
        got = run_one(db, spec)
        verdict = compare(spec, got)
        results.append({"id": spec["id"], "title": spec.get("title"), "kind": spec["kind"], **verdict, "got": got})
        word = {"MATCH": "일치", "DIFF": "다름", "ERROR": "오류", "NOT_RECORDED": "기준값 없음"}[verdict["status"]]
        extra = f"값 {verdict.get('checked', 0)}개" + (f", 근거 문장 {verdict['facts']}개" if verdict.get("facts") else "")
        log(f"[{word}] {spec['id']} {spec.get('title', '')} — {verdict.get('message') or extra}")
        for d in verdict["diffs"][:12]:
            log(f"       {d['label']}: 기준 {d['expected']} / 이 PC {d['actual']}")
        for d in verdict.get("text_diffs", [])[:5]:
            log(f"       문장 기준: {d['expected']}\n       문장 이 PC: {d['actual']}")
    counts = {s: sum(1 for r in results if r["status"] == s) for s in ("MATCH", "DIFF", "ERROR", "NOT_RECORDED")}
    ok = counts["MATCH"] == len(results) and results
    data_diff = any(r["kind"] == "dataset" and r["status"] == "DIFF" for r in results)
    if ok:
        log(f"결과: {len(results)}개 사례 모두 일치 — 이 PC의 계산 결과는 기준 PC({cases.get('recorded_on', '-')})와 같습니다.")
    else:
        log(f"결과: 일치 {counts['MATCH']} · 다름 {counts['DIFF']} · 오류 {counts['ERROR']} · 기준값 없음 {counts['NOT_RECORDED']} (사례 {len(results)}개)")
        if data_diff:
            log("자료 지문(dataset)이 다릅니다: 계산이 아니라 DB 자료가 기준 PC와 다릅니다. 같은 날짜의 자료 묶음을 가져왔는지 확인하세요.")
    return {"checked_at": datetime.now(timezone.utc).isoformat(), "cases_recorded_on": cases.get("recorded_on"), "counts": counts,
            "all_match": bool(ok), "results": results}


def record(db: Any, cases: dict[str, Any], note: str | None = None, log: Callable[[str], None] = print) -> dict[str, Any]:
    """Run every case and store what this PC computed as the expected values (the reference PC does this once per data bundle)."""
    out = json.loads(json.dumps(cases))
    for spec in out["cases"]:
        got = run_one(db, spec)
        if "error" in got:
            log(f"[오류] {spec['id']}: {got['error']}")
            spec.pop("expected", None)
            continue
        spec["expected"] = got
        log(f"[기록] {spec['id']} {spec.get('title', '')} — 값 {len(got['values'])}개, 근거 문장 {len(got['facts'])}개")
    out["recorded_on"] = datetime.now(KST).isoformat(timespec="seconds")   # 한국 시각으로 적는다
    if note:
        out["data_note"] = note
    return out
