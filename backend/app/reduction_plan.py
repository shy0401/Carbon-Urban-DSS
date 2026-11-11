"""탄소 감축 방안: 계획안 하나를 '대책 없음'에서 시작해 수단을 차례로 더할 때 줄어드는 양 (기준 문서 5.15).

다른 계획안과 견주지 않는다. 같은 계획(같은 연면적·동수·층수)에서
  0. 대책 없음(기준안: 관측 원단위 그대로, 효율 1.0·태양광 0)
  1. 단열·창호 기준 강화(가스 사용 23.6% 절감: 준공 시기만 다른 개별난방 단지 78쌍 실측)
  2. 에너지 절약 운영(전력 사용 4.8% 절감: 계량·제어·행동 실측 문헌 6건 중앙값)
  3. 지붕 태양광(옥상 면적이 허락하는 만큼)
  4. 녹지·조경 흡수(녹지 면적 × 연 1.0 kgCO2/m², 상쇄)
을 차례로 더하고, 그래도 남는 전력을 운영 넷제로까지 채우는 데 필요한 외부 재생에너지를 적는다.
절감률은 설계 목표가 아니라 실측에서 나온 지표이며, 출처와 범위는 docs/REDUCTION_INDICATORS.md에 있다.
값은 모두 이 파일 상수이며 DATA_STANDARD 5.15와 같아야 한다. 값이 없으면 0으로 채우지 않고 그 단계를 뺀다.
난방·급탕 전기화(히트펌프)는 초기 비용이 크고 국내 공동주택 실측 근거가 부족해 2026-11-11부터 기본 단계에서 뺐다.
"""
from __future__ import annotations

from typing import Any

from .benchmarks import PRIMARY_ENERGY_FACTOR

# 지표(실측 기반). 근거 표: docs/REDUCTION_INDICATORS.md
ENVELOPE_GAS_SAVING = 0.236            # 단열·창호 기준 강화: 가스 −23.6% (개별난방 단지 78쌍, 준공 2017~ 대 ~2008, 95% 구간 −25.8~−20.5%)
OPERATION_ELECTRICITY_SAVING = 0.048   # 에너지 절약 운영: 전력 −4.8% (실측 문헌 6건 중앙값, 범위 −17.0~−1.95%)
GREEN_UPTAKE_KG_PER_M2 = 1.0           # 녹지·조경 흡수: 연 1.0 kgCO2/m² = 10 t/ha (국립산림과학원 표준 탄소흡수량 20년생 8.8~15.9 t/ha의 낮은 쪽, 가정)
GREEN_UPTAKE_RANGE_T_PER_HA = (8.8, 15.9)
ROOF_USABLE_RATIO = 0.60     # 옥상 중 패널을 놓을 수 있는 비율 (설비·통로·옥탑 제외, 가정)
ROOF_M2_PER_KW = 10.0        # 태양광 1 kW에 필요한 옥상 면적 (경사 설치·그림자 이격 포함, 가정)
# 제로에너지건축물 인증 등급의 에너지자립률 하한(%) — 참고 위치일 뿐 인증 판정이 아니다(1++ 효율등급·BEMS 등 다른 요건 있음).
ZEB_GRADES = ((100.0, "1등급"), (80.0, "2등급"), (60.0, "3등급"), (40.0, "4등급"), (20.0, "5등급"))


def zeb_grade(self_sufficiency_pct: float | None) -> str | None:
    """에너지자립률(%)이 닿는 ZEB 등급 구간 (참고). 20% 미만은 None."""
    if self_sufficiency_pct is None:
        return None
    for floor, label in ZEB_GRADES:
        if self_sufficiency_pct >= floor:
            return label
    return None


def roof_pv(footprint_m2: float | None, kwh_per_kw: float | None) -> dict[str, Any] | None:
    """옥상에 놓을 수 있는 태양광 용량과 연 발전량. 건축면적이나 발전량 근거가 없으면 None."""
    if not footprint_m2 or footprint_m2 <= 0:
        return None
    roof = footprint_m2 * ROOF_USABLE_RATIO
    kw = round(roof / ROOF_M2_PER_KW, 1)
    return {"roof_m2": round(roof, 1), "kw": kw, "kwh": round(kw * kwh_per_kw, 1) if kwh_per_kw else None}


def _carbon(electricity_kwh: float, gas_kwh: float, fe: float, fg: float | None) -> float:
    return electricity_kwh * fe + (gas_kwh * fg if fg else 0.0)


def building_plan(reference: dict[str, Any] | None, footprint_m2: float | None, factors: dict[str, Any] | None,
                  pv_yield: dict[str, Any] | None = None, plan_carbon_kg: float | None = None,
                  green_area_m2: float | None = None) -> dict[str, Any]:
    """계획안 하나의 감축 방안 사다리.

    reference: 기준안 연간 {'electricity_kwh', 'gas_kwh'} (같은 연면적을 관측 원단위 그대로 지을 때)
    footprint_m2: 건축면적 합계(옥상 면적의 근거)
    factors: {'ELECTRICITY': {'factor'}, 'GAS': {'factor'}} — 가스 계수가 없으면 단열·창호 단계와 가스 탄소를 뺀다
    pv_yield: {'kwh_per_kw', 'label'} — 지역 일사량 추정 또는 사용자 값. 없으면 태양광은 용량만 적는다
    plan_carbon_kg: 입력한 계획안의 연간 운영탄소(사다리 위 위치를 말하기 위해)
    green_area_m2: 계획안의 녹지 면적(대지면적 × 녹지 비율). 없으면 녹지·조경 흡수 단계를 뺀다
    """
    ref = reference or {}
    e0, g0 = ref.get("electricity_kwh"), ref.get("gas_kwh")
    fe = ((factors or {}).get("ELECTRICITY") or {}).get("factor")
    fg = ((factors or {}).get("GAS") or {}).get("factor")
    if e0 is None or not fe:
        return {"available": False, "reason": "기준안의 연간 전력 또는 전력 배출계수가 없어 감축 방안을 계산하지 않았습니다."}
    gas_known = g0 is not None
    g0 = float(g0 or 0.0)
    e0 = float(e0)
    c0 = _carbon(e0, g0, fe, fg if gas_known else None)
    steps: list[dict[str, Any]] = []

    def step(key: str, title: str, detail: str, e: float, g: float, offset_kg: float = 0.0) -> None:
        c = max(_carbon(e, g, fe, fg if gas_known else None) - offset_kg, 0.0)
        prev = steps[-1]["carbon_kg"] if steps else c0
        steps.append({"key": key, "title": title, "detail": detail, "electricity_kwh": round(e, 1), "gas_kwh": round(g, 1) if gas_known else None,
                      "carbon_kg": round(c, 1), "reduction_kg": round(prev - c, 1), "cumulative_pct": round((c0 - c) / c0 * 100, 1) if c0 > 0 else None})

    e1, g1 = e0, g0
    if gas_known and g0 > 0 and fg:
        g1 = g0 * (1 - ENVELOPE_GAS_SAVING)
        step("envelope", "단열·창호 기준 강화", f"가스 사용을 {ENVELOPE_GAS_SAVING * 100:.1f}% 줄임 (준공 시기만 다른 개별난방 단지 78쌍의 실측 차이)", e1, g1)
    e2, g2 = e1 * (1 - OPERATION_ELECTRICITY_SAVING), g1
    step("operation", "에너지 절약 운영", f"계량·제어·행동 개선으로 전력 사용을 {OPERATION_ELECTRICITY_SAVING * 100:.1f}% 줄임 (실측 문헌 6건 중앙값)", e2, g2)
    kwh_per_kw = (pv_yield or {}).get("kwh_per_kw")
    pv = roof_pv(footprint_m2, kwh_per_kw)
    e3 = e2
    if pv and pv["kwh"]:
        used = min(pv["kwh"], e2)
        e3 = e2 - used
        pv["used_kwh"] = round(used, 1)
        pv["surplus_kwh"] = round(pv["kwh"] - used, 1)
        step("rooftop_pv", "지붕 태양광", f"옥상 {pv['roof_m2']:,.0f} m²(건축면적의 {ROOF_USABLE_RATIO * 100:.0f}%)에 {pv['kw']:,.1f} kW, 연 {pv['kwh']:,.0f} kWh 발전", e3, g2)
    green = None
    if green_area_m2 and green_area_m2 > 0:
        before = steps[-1]["carbon_kg"] if steps else c0
        uptake = min(green_area_m2 * GREEN_UPTAKE_KG_PER_M2, before)
        green = {"area_m2": round(green_area_m2, 1), "uptake_kg": round(uptake, 1),
                 "range_kg": [round(green_area_m2 * lo / 10, 1) for lo in GREEN_UPTAKE_RANGE_T_PER_HA]}
        if uptake > 0:
            step("greenery", "녹지·조경 흡수", f"녹지 {green_area_m2:,.0f} m² × 연 {GREEN_UPTAKE_KG_PER_M2:.1f} kgCO2/m² = {uptake / 1000:,.1f} t 흡수(상쇄)", e3, g2, offset_kg=uptake)
    final = steps[-1]["carbon_kg"] if steps else c0
    # 에너지자립률(ZEB 참고): 태양광 1차에너지 ÷ 절감 뒤 소비 1차에너지
    demand_primary = e2 * PRIMARY_ENERGY_FACTOR["ELECTRICITY"] + g2 * PRIMARY_ENERGY_FACTOR["GAS"]
    self_pct = round(pv["kwh"] * PRIMARY_ENERGY_FACTOR["ELECTRICITY"] / demand_primary * 100, 1) if pv and pv["kwh"] and demand_primary > 0 else None
    residual = {"electricity_kwh": round(e3, 1), "gas_kwh": round(g2, 1) if gas_known else None, "carbon_kg": round(final, 1),
                "offsite_pv_kw": round(e3 / kwh_per_kw, 1) if kwh_per_kw and e3 > 0 else None}
    assumptions = [
        f"단열·창호 기준 강화는 가스 사용 {ENVELOPE_GAS_SAVING * 100:.1f}% 절감을 적용했습니다. 같은 지역·난방 방식·규모에서 준공 시기만 다른 개별난방 단지 78쌍의 실측 차이(면적당 가스, 95% 구간 20.5~25.8%)이며, 같은 비교에서 전기는 5.2% 많아 전기 절감은 넣지 않았습니다.",
        f"에너지 절약 운영은 전력 사용 {OPERATION_ELECTRICITY_SAVING * 100:.1f}% 절감을 적용했습니다. 계량·제어·행동 개선을 실측한 문헌 6건의 중앙값이며 범위는 1.95~17.0%입니다.",
        f"지붕 태양광은 건축면적의 {ROOF_USABLE_RATIO * 100:.0f}%를 쓸 수 있고 1 kW에 {ROOF_M2_PER_KW:.0f} m²가 든다고 가정했습니다."
        + (f" 발전량은 {pv_yield['label']} 기준 {kwh_per_kw:,.0f} kWh/kW·년입니다." if kwh_per_kw and (pv_yield or {}).get("label") else ""),
        f"녹지·조경 흡수는 녹지 1 m²에 연 {GREEN_UPTAKE_KG_PER_M2:.1f} kgCO2(1 ha에 10 t)를 가정했습니다. 국립산림과학원 표준 탄소흡수량(20년생 주요 수종 1 ha에 연 {GREEN_UPTAKE_RANGE_T_PER_HA[0]}~{GREEN_UPTAKE_RANGE_T_PER_HA[1]} t)의 낮은 쪽이며, 조경 녹지는 숲보다 나무가 성기어 더 작을 수 있습니다(확인 필요).",
        "난방·급탕 전기화(히트펌프)는 초기 비용이 크고 국내 공동주택 실측 근거가 부족해 기본 단계에 넣지 않았습니다.",
        "에너지자립률은 태양광 발전량과 소비를 1차에너지(전력 2.75·가스 1.1)로 환산한 비율이며 ZEB 등급은 참고 위치입니다(1++ 효율등급·BEMS 요건 별도).",
    ]
    if not gas_known:
        assumptions.append("기준안 가스 사용량이 없어 단열·창호 단계와 가스 탄소를 넣지 않았습니다.")
    elif not fg:
        assumptions.append("가스 배출계수가 없어 단열·창호 단계와 가스 탄소를 넣지 않았습니다.")
    if pv and not pv["kwh"]:
        assumptions.append("태양광 발전량 근거가 없어 용량만 적고 감축량에는 넣지 않았습니다.")
    if not green_area_m2:
        assumptions.append("녹지 면적이 없어 녹지·조경 흡수 단계를 넣지 않았습니다.")
    return {
        "available": True, "start": {"label": "대책 없음 (기준안)", "electricity_kwh": round(e0, 1), "gas_kwh": round(g0, 1) if gas_known else None, "carbon_kg": round(c0, 1)},
        "steps": steps, "final_carbon_kg": round(final, 1), "final_pct": round((c0 - final) / c0 * 100, 1) if c0 > 0 else None,
        "pv": pv, "pv_yield": pv_yield, "green": green, "self_sufficiency_pct": self_pct, "zeb_grade": zeb_grade(self_pct), "residual": residual,
        "plan": {"carbon_kg": round(plan_carbon_kg, 1), "pct": round((c0 - plan_carbon_kg) / c0 * 100, 1) if c0 > 0 else None} if plan_carbon_kg is not None else None,
        "factors": {"electricity": fe, "gas": fg if gas_known else None},
        "assumptions": assumptions,
    }


def plan_text(plan: dict[str, Any]) -> str | None:
    """보고서 요약에 넣는 한 문장 (엔진 값 그대로)."""
    if not plan or not plan.get("available") or not plan.get("steps"):
        return None
    t = lambda kg: f"{kg / 1000:,.1f} t"  # noqa: E731
    parts = [f"{s['title']} −{t(s['reduction_kg'])}" for s in plan["steps"]]
    text = (f"탄소 감축 방안: 대책 없이 지으면 연간 {t(plan['start']['carbon_kg'])}이고, " + ", ".join(parts)
            + f"을 차례로 더하면 {t(plan['final_carbon_kg'])}(대책 없음 대비 −{plan['final_pct']:.1f}%)까지 줄어듭니다.")
    r = plan["residual"]
    if r["carbon_kg"] > 0 and r.get("offsite_pv_kw"):
        text += f" 남는 {t(r['carbon_kg'])}는 구역 밖 재생에너지(태양광 약 {r['offsite_pv_kw']:,.0f} kW 상당) 조달로 채웁니다."
    return text
