"""지역 합계를 독립된 공식 통계와 맞대는 검증 (화면: 모델 → 공식 통계와 맞대기).

이 도구의 관측·계산 값이 믿을 만한지를, 같은 것을 다른 기관이 센 통계와 비교해 숫자로 보여 준다.
어느 한쪽을 정답으로 보지 않고 차이와 그 까닭(포함 범위)을 함께 적는다.

* 전력 덮음: 건축HUB 지번 전력(모든 지번 합) ÷ 한전 시군구 건물 전력(주택용+일반용+교육용). 월별 상관계수와
  달마다의 비율 범위도 본다(계절 모양이 같으면 같은 수요를 센 것이고, 비율이 안정적이면 빠진 몫이 일정한 것).
* K-apt ↔ 건축HUB: 같은 단지(K-apt 지번과 건축HUB 지번이 한 단지로 이어진 곳)의 같은 해 12개월 전력 비율.
* 온실가스: 온실가스종합정보센터 지역 인벤토리(최근 연도)의 건물 등 배출과, 이 도구가 건축HUB 지번 에너지로 계산한
  최근 연도 탄소. 연도와 포함 범위가 다르므로 비율은 '같은 크기인지' 정도로만 본다.
* 인구: SGIS 행정구역 인구와 SGIS 500m 격자 인구 합(경계 격자 균등 분할).
* 격자 연결: 건축HUB 지번 중 연속지적으로 500m 격자에 놓인 비율.
"""
from __future__ import annotations

import math
import statistics
import time
from typing import Any, Iterable

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select, text

from .db import Session

router = APIRouter(prefix="/api/validation", tags=["validation"])
HUB = "국토교통부 건축HUB"
_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
TTL = 300.0


# --------------------------------------------------------------------------- pure helpers (tested without a database)
def pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    num = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    den = math.sqrt(sum((a - mx) ** 2 for a in xs) * sum((b - my) ** 2 for b in ys))
    return round(num / den, 3) if den else None


def monthly_agreement(hub: dict[str, float], other: dict[str, float], year: int) -> dict[str, Any] | None:
    """{'YYYYMM': kWh} of one year from both sides → yearly ratio, monthly correlation and ratio range (12 months only)."""
    months = [f"{year}{m:02d}" for m in range(1, 13)]
    if any(hub.get(ym) is None or not other.get(ym) for ym in months):
        return None
    xs = [hub[ym] for ym in months]
    ys = [other[ym] for ym in months]
    ratios = [a / b for a, b in zip(xs, ys)]
    return {"year": year, "ratio": round(sum(xs) / sum(ys), 3), "monthly_r": pearson(xs, ys),
            "ratio_min": round(min(ratios), 3), "ratio_max": round(max(ratios), 3)}


def ratio_summary(ratios: Iterable[float]) -> dict[str, Any] | None:
    values = sorted(r for r in ratios if r is not None and r > 0 and math.isfinite(r))
    if not values:
        return None
    n = len(values)
    return {"pairs": n, "median": round(statistics.median(values), 3), "p10": round(values[int(n * 0.1)], 3),
            "p90": round(values[max(0, int(n * 0.9) - 1)], 3), "within_20pct": round(sum(1 for r in values if 0.8 <= r <= 1.2) / n, 3)}


def completeness_summary(year: int, parcels: list[tuple[list[str], float | None]]) -> dict[str, Any] | None:
    """Gas parcel-years by how much of the year their rows cover (full 12 / summer bi-monthly / real gaps)."""
    from .grid_metrics import annual_complete, bimonthly_only
    if not parcels:
        return None
    full = bim = 0
    kwh_full = kwh_bim = kwh_gap = 0.0
    for months, kwh in parcels:
        value = float(kwh or 0.0)
        if bimonthly_only("GAS", months):
            bim += 1
            kwh_bim += value
        elif annual_complete("GAS", months):
            full += 1
            kwh_full += value
        else:
            kwh_gap += value
    n = len(parcels)
    return {"year": year, "parcels": n, "full": full, "bimonthly": bim, "partial": n - full - bim,
            "full_gwh": round(kwh_full / 1e6, 1), "bimonthly_gwh": round(kwh_bim / 1e6, 1), "partial_gwh": round(kwh_gap / 1e6, 1)}


# --------------------------------------------------------------------------- database
def region_validation(db: Any, region: str | None = None) -> dict[str, Any]:
    from .models import EnergyMonthly
    from .regional_stats import (BUILDING_USES, GIR_SIDO, KepcoSigunguMonthly, annual, gir_latest_year, gir_values, kepco_key,
                                 match_region, region_index)
    from .regions import scope
    from .service import factors_for
    sc = scope(db, region)
    clause = sc.legal_clause(EnergyMonthly.sigungu_code)
    notes: list[str] = []

    # 건축HUB monthly electricity/gas of the region (all parcels, the provider's own rows only)
    hub: dict[str, dict[str, float]] = {"ELECTRICITY": {}, "GAS": {}}
    q = select(EnergyMonthly.energy_type, EnergyMonthly.use_ym, func.sum(EnergyMonthly.usage_kwh)).where(
        EnergyMonthly.source == HUB, EnergyMonthly.usage_kwh.is_not(None))
    if clause is not None:
        q = q.where(clause)
    for typ, ym, kwh in db.execute(q.group_by(EnergyMonthly.energy_type, EnergyMonthly.use_ym)):
        hub.setdefault(typ, {})[ym] = float(kwh)
    hub_years = sorted({int(ym[:4]) for ym in hub["ELECTRICITY"]})

    # 한전 시군구 전력 (계약종별) of the same 시·군·구
    kepco: dict[tuple[str, str], dict[tuple[str, int], list]] = {}
    try:
        for year, sido, sgg, category, months in db.execute(select(KepcoSigunguMonthly.year, KepcoSigunguMonthly.sido, KepcoSigunguMonthly.sgg,
                                                                   KepcoSigunguMonthly.category, KepcoSigunguMonthly.months)
                                                            .where(KepcoSigunguMonthly.kind == "contract")):
            key = kepco_key(sido, sgg)
            if key:
                kepco.setdefault(key, {})[(category, int(year))] = months
    except Exception:  # noqa: BLE001 - table missing
        db.rollback()
    hit = match_region({k: k for k in kepco}, sc.code[:2], sc.short, True)
    mine = kepco.get(hit, {}) if hit else {}
    electricity = []
    for year in hub_years:
        parts = [mine.get((c, year)) for c in BUILDING_USES]
        building = ({f"{year}{m + 1:02d}": sum(p[m] for p in parts) for m in range(12) if all(p and p[m] is not None for p in parts)}
                    if all(parts) else {})
        total_months = mine.get(("합계", year))
        agree = monthly_agreement(hub["ELECTRICITY"], building, year)
        hub_total = sum(v for ym, v in hub["ELECTRICITY"].items() if ym.startswith(str(year)))
        kepco_building = sum(building.values()) if len(building) == 12 else None
        kepco_total = annual(total_months)
        electricity.append({"year": year, "hub_gwh": round(hub_total / 1e6, 1), "hub_months": sum(1 for ym in hub["ELECTRICITY"] if ym.startswith(str(year))),
                            "kepco_building_gwh": round(kepco_building / 1e6, 1) if kepco_building else None,
                            "kepco_total_gwh": round(kepco_total / 1e6, 1) if kepco_total else None,
                            "coverage_building": agree["ratio"] if agree else None,
                            "coverage_total": round(hub_total / kepco_total, 3) if kepco_total else None,
                            "monthly_r": agree["monthly_r"] if agree else None,
                            "ratio_min": agree["ratio_min"] if agree else None, "ratio_max": agree["ratio_max"] if agree else None})
    if not hit:
        notes.append("한전 시군구별 전력판매량에서 이 시·군·구를 찾지 못했습니다")

    # K-apt ↔ 건축HUB for the same complex and year (12 months on both sides)
    pairs_sql = """
      WITH h AS (SELECT raw_record->>'kapt_code' AS kc, left(use_ym, 4) AS y, count(DISTINCT use_ym) AS m, sum(usage_kwh) AS kwh
                 FROM energy_monthly WHERE match_method = 'KAPT_COMPLEX_CENTROID' AND energy_type = 'ELECTRICITY' AND source = :hub
                   AND usage_kwh IS NOT NULL AND sigungu_code = ANY(:legal) GROUP BY 1, 2),
           k AS (SELECT complex_code AS kc, left(year_month, 4) AS y, count(*) AS m, sum(electricity_quantity) AS kwh
                 FROM apartment_energy_monthly WHERE quality_status = 'SUCCESS' AND electricity_quantity IS NOT NULL GROUP BY 1, 2)
      SELECT h.y, k.kwh / h.kwh AS ratio FROM h JOIN k ON k.kc = h.kc AND k.y = h.y WHERE h.m = 12 AND k.m = 12 AND h.kwh > 0"""
    kapt_pairs = None
    try:
        legal = list(sc.legal_codes or [])
        rows = list(db.execute(text(pairs_sql), {"hub": HUB, "legal": legal})) if legal else []
        kapt_pairs = ratio_summary(float(r[1]) for r in rows)
        if kapt_pairs:
            kapt_pairs["years"] = sorted({int(r[0]) for r in rows})
    except Exception:  # noqa: BLE001 - K-apt tables missing
        db.rollback()

    # 온실가스: GIR 최근 연도 vs 이 도구 계산 (건축HUB 최근 완전 연도)
    ghg = None
    gir_year = gir_latest_year(db)
    if gir_year:
        values = gir_values(db, [gir_year])
        g = region_index(values)
        found = match_region(g, sc.code[:2], sc.short, True)
        if found:
            v = values[found]
            direct = v.get(("에너지/A. 연료연소/4. 기타", gir_year))
            elec = v.get(("전력/A. 연료연소/4. 기타", gir_year))
            heat = v.get(("열/A. 연료연소/4. 기타", gir_year))
            full = [y for y in hub_years if sum(1 for ym in hub["ELECTRICITY"] if ym.startswith(str(y))) == 12]
            ours_year = full[-1] if full else None
            factors = factors_for(db, ours_year) if ours_year else {}
            ef = (factors.get("ELECTRICITY") or {}).get("factor")
            gf = (factors.get("GAS") or {}).get("factor")
            e_kwh = sum(val for ym, val in hub["ELECTRICITY"].items() if ours_year and ym.startswith(str(ours_year)))
            g_kwh = sum(val for ym, val in hub["GAS"].items() if ours_year and ym.startswith(str(ours_year)))
            ghg = {"gir_year": gir_year, "gir_total_kt": round(v.get(("총배출량", gir_year)) or 0, 1) if v.get(("총배출량", gir_year)) is not None else None,
                   "gir_building_direct_kt": round(direct, 1) if direct is not None else None,
                   "gir_building_electricity_kt": round(elec, 1) if elec is not None else None,
                   "gir_building_heat_kt": round(heat, 1) if heat is not None else None,
                   "ours_year": ours_year, "electricity_factor": ef, "gas_factor": gf,
                   "ours_electricity_kt": round(e_kwh * ef / 1e6, 1) if ours_year and ef and e_kwh else None,
                   "ours_gas_kt": round(g_kwh * gf / 1e6, 1) if ours_year and gf and g_kwh else None}
            if ghg["ours_electricity_kt"] and elec:
                ghg["electricity_ratio"] = round(ghg["ours_electricity_kt"] / elec, 3)
            if ghg["ours_gas_kt"] and direct:
                ghg["gas_over_direct_ratio"] = round(ghg["ours_gas_kt"] / direct, 3)

    # 인구: SGIS 행정 vs 500m 격자 합 (전국 지도와 같은 값)
    population = None
    try:
        from .national_map import static
        st = static(db)
        row = next((r for r in st["regions"] if r["code"] == sc.code), None)
        if row and row["metrics"].get("population"):
            p500 = row["metrics"].get("pop500")
            population = {"year": st.get("unit_year"), "admin": row["metrics"]["population"], "grid500": p500,
                          "ratio": round(p500 / row["metrics"]["population"], 3) if p500 else None,
                          "note": row["notes"].get("pop500")}
    except Exception:  # noqa: BLE001 - national tables missing
        db.rollback()

    # 격자 연결: 건축HUB 지번 → 연속지적 → 500m 격자
    link = None
    try:
        link_year = hub_years[-1] if hub_years else None
        if link_year and sc.legal_codes:
            r = db.execute(text("""
              WITH p AS (SELECT DISTINCT sigungu_code || bjdong_code || (CASE WHEN coalesce(lot_type, '0') = '1' THEN '2' ELSE '1' END)
                                || lpad(right(coalesce(bun, '0'), 4), 4, '0') || lpad(right(coalesce(ji, '0'), 4), 4, '0') AS pnu
                         FROM energy_monthly WHERE source = :hub AND use_ym LIKE :y AND sigungu_code = ANY(:legal))
              SELECT count(*), count(g.pnu) FROM p LEFT JOIN parcel_grid g ON g.pnu = p.pnu"""),
                           {"hub": HUB, "y": f"{link_year}%", "legal": list(sc.legal_codes)}).one()
            if r[0]:
                link = {"year": link_year, "parcels": int(r[0]), "linked": int(r[1]), "share": round(r[1] / r[0], 3)}
    except Exception:  # noqa: BLE001
        db.rollback()

    # 가스 지번의 연간 완전성: 12개월 / 여름 격월 고지 / 실제로 빠진 달
    gas_completeness = None
    try:
        gas_year = max((int(ym[:4]) for ym in hub["GAS"]), default=None)
        if gas_year and sc.legal_codes:
            rows = db.execute(text("""
              SELECT array_agg(use_ym), sum(usage_kwh) FROM energy_monthly
              WHERE source = :hub AND energy_type = 'GAS' AND usage_kwh IS NOT NULL AND use_ym LIKE :y AND sigungu_code = ANY(:legal)
              GROUP BY sigungu_code, bjdong_code, lot_type, bun, ji"""), {"hub": HUB, "y": f"{gas_year}%", "legal": list(sc.legal_codes)}).all()
            gas_completeness = completeness_summary(gas_year, [(list(m), k) for m, k in rows])
    except Exception:  # noqa: BLE001 - array_agg needs PostgreSQL
        db.rollback()

    # 탄소공간지도 500m 건물 배출(팀 데이터셋): 지역 합계와, 같은 해 이 도구의 건축HUB 전력 탄소를 칸끼리
    carbonmap = None
    try:
        from .team_grid import carbonmap_comparison, developments
        carbonmap = carbonmap_comparison(db, sc.code)
        if carbonmap is not None:
            devs = developments(db, sc.code)
            usable = [d for d in devs if d.get("pair_usable") in (True, "True")]
            carbonmap["developments"] = {"cases": len(devs), "usable": len(usable)}
    except Exception:  # noqa: BLE001
        db.rollback()

    if not hub_years:
        notes.append("이 지역에는 아직 건축HUB 지번 에너지가 없습니다(상세 자료 수집 후 비교)")
    return {"region": {"code": sc.code, "name": sc.name, "short_name": sc.short}, "electricity": electricity, "kapt_vs_hub": kapt_pairs,
            "ghg": ghg, "population": population, "grid_link": link, "gas_completeness": gas_completeness, "carbonmap": carbonmap, "notes": notes,
            "sources": {"hub": "건축HUB 건물에너지 (지번 월별, 모든 지번)", "kepco": "한국전력공사 시군구별 전력판매량 (계약종별)",
                        "kapt": "K-apt 공동주택 관리비 에너지 (단지 월별)", "gir": "온실가스종합정보센터 지역 온실가스 인벤토리",
                        "sgis": "SGIS 행정구역 통계·500m 격자 통계"}}


@router.get("")
def validation(region: str | None = Query(None, max_length=10)) -> dict[str, Any]:
    key = region or "*"
    cached = _CACHE.get(key)
    if cached and cached[0] > time.monotonic() - TTL:
        return cached[1]
    from .regions import RegionNotReady
    with Session() as db:
        try:
            body = region_validation(db, region)
        except RegionNotReady as exc:
            raise HTTPException(404, str(exc)) from None
    _CACHE[key] = (time.monotonic(), body)
    return body
