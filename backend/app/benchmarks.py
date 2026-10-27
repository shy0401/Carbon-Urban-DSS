"""업계·정부 기준과 맞대기 (참고, docs/DATA_STANDARD.md 5.14).

인증·평가 실무가 쓰는 기준값을 한곳에 두고, 지역 시뮬레이션의 관측·계획 값을 그 기준 위에 놓는다. 판정이 아니라 **참고 위치**다:
* 건축물 에너지효율등급·제로에너지건축물(ZEB) 인증은 표준 조건의 설계 평가(난방·냉방·급탕·조명·환기 5개 용도, ECO2)이고,
  이 도구의 값은 계량된 실사용(가전·취사 포함)이라 같은 숫자라도 뜻이 다르다.
* 국토교통부 표준지표는 같은 용도 건물의 단위면적당 사용량 중앙값이다(2024년, 지역 중부·남부).

출처 (2026-10-27 확인):
* 1차에너지 환산계수: 한국에너지공단 제로에너지건축물 통합 인증시스템 '인증제도 안내' — 연료 1.1, 전력 2.75, 지역난방 0.728,
  지역냉방 0.937 (https://zeb.energy.or.kr/BC/BC07/BC07_01_001.do). EG-TIPS 질의응답(2021)에는 지역난방 0.614로 적혀 있어
  지역난방은 이 도구에서 쓰지 않는다(건축HUB에 열 사용량이 없음).
* ZEB 등급(에너지자립률 1등급 100% 이상 … 5등급 20~40%), 에너지효율등급 구간(주거용 1+++ 60 미만 … 7등급 370~420,
  주거용 외 1+++ 80 미만 … 7등급 610~700 kWh/m²·년): 한국에너지공단 (구)제로에너지건축물 인증시스템 인증기준
  (https://min24.energy.or.kr/nzeb/BC/BC03/BC03_05_002.do).
* ZEB 의무: 2025년부터 민간 공동주택 30세대 이상·연면적 1,000m² 이상 건축물 5등급 수준, 공공 1,000m² 이상 4등급
  (한국건축산업신문 칸 2025, https://www.kharn.kr/mobile/article.html?no=28109).
* 표준지표 2024 (중앙값, kWh/m²·년): 공동주택 중부 136·남부 111, 업무시설 중부 159·남부 102 — 국토교통부 2025 발표
  (환경일보 https://www.hkbs.co.kr/news/articleView.html?idxno=802871). 1차/최종 에너지 구분은 기사에 없어 **확인 필요**.
* 지역 구분: 전북은 「건축물의 에너지절약설계기준」 별표 1의 중부2지역으로 보고 표준지표 '중부'에 맞댄다(**확인 필요**).
"""
from __future__ import annotations

from typing import Any

PRIMARY_ENERGY_FACTOR = {"ELECTRICITY": 2.75, "GAS": 1.1, "DISTRICT_HEATING": 0.728, "DISTRICT_COOLING": 0.937}
ZEB_GRADES = ((100.0, "1등급"), (80.0, "2등급"), (60.0, "3등급"), (40.0, "4등급"), (20.0, "5등급"))
ZEB_PRIVATE_MIN_GFA_M2 = 1000.0
ZEB_PRIVATE_MIN_HOUSEHOLDS = 30
EFFICIENCY_RESIDENTIAL = ((60, "1+++"), (90, "1++"), (120, "1+"), (150, "1"), (190, "2"), (230, "3"), (270, "4"), (320, "5"), (370, "6"), (420, "7"))
EFFICIENCY_NONRESIDENTIAL = ((80, "1+++"), (140, "1++"), (200, "1+"), (260, "1"), (320, "2"), (380, "3"), (450, "4"), (520, "5"), (610, "6"), (700, "7"))
STANDARD_INDICATOR_2024 = {"공동주택": {"중부": 136.0, "남부": 111.0}, "업무시설": {"중부": 159.0, "남부": 102.0}}
# 시·도 코드 앞 두 자리 → 표준지표 지역 (에너지절약설계기준 별표 1; 시·군 단위 예외는 넣지 않음, 확인 필요)
SOUTH_SIDO = {"26", "27", "29", "31", "46", "12"}   # 부산·대구·광주·울산·전남(옛 46, 통합 12)
SOURCES = {
    "primary": "한국에너지공단 제로에너지건축물 통합 인증시스템(1차에너지 환산계수)",
    "grades": "한국에너지공단 인증기준(에너지효율등급·ZEB 등급)",
    "zeb_mandate": "ZEB 의무화(2025, 민간 5등급·공공 4등급)",
    "standard": "국토교통부 2024 건물 용도별 표준지표(중앙값)",
}


def efficiency_band(primary_kwh_m2: float | None, residential: bool) -> str | None:
    if primary_kwh_m2 is None:
        return None
    table = EFFICIENCY_RESIDENTIAL if residential else EFFICIENCY_NONRESIDENTIAL
    for limit, grade in table:
        if primary_kwh_m2 < limit:
            return f"{grade}등급"
    return "등외"


def zeb_grade(self_sufficiency_pct: float | None) -> str | None:
    if self_sufficiency_pct is None:
        return None
    for limit, grade in ZEB_GRADES:
        if self_sufficiency_pct >= limit:
            return grade
    return "등급 기준(20%) 미만"


def climate_region(region_code: str | None) -> str:
    return "남부" if str(region_code or "")[:2] in SOUTH_SIDO else "중부"


def primary_intensity(electricity_kwh_m2: float | None, gas_kwh_m2: float | None) -> float | None:
    """단위면적당 1차에너지(kWh/m²·년) = 전력 × 2.75 + 가스 × 1.1 (가스 없는 지번은 0이 아니라 전력만)."""
    if electricity_kwh_m2 is None:
        return None
    return electricity_kwh_m2 * PRIMARY_ENERGY_FACTOR["ELECTRICITY"] + (gas_kwh_m2 or 0.0) * PRIMARY_ENERGY_FACTOR["GAS"]


def industry_block(history: dict[str, Any], effort_result: dict[str, Any] | None = None, region_code: str | None = None) -> dict[str, Any]:
    """The area's observed and planned values on the certification / government reference scales (reference only)."""
    zone = climate_region(region_code or "52110")
    be = (history.get("building_energy") or {}).get("years") or {}
    latest = max((int(y) for y, v in be.items() if v.get("kwh_per_m2") is not None and v.get("complete", True) and not v.get("provider_gap")), default=None)
    table: list[dict[str, str]] = []
    out: dict[str, Any] = {"available": False, "zone": zone, "table": table, "notes": [], "sources": SOURCES}
    if latest is not None:
        v = be.get(latest) or be.get(str(latest))
        e_m2 = float(v["kwh_per_m2"])
        g_m2 = v.get("gas_kwh_per_m2")
        final = e_m2 + (g_m2 or 0.0)
        primary = primary_intensity(e_m2, g_m2)
        out["buildings"] = {"year": latest, "electricity_kwh_m2": round(e_m2, 1), "gas_kwh_m2": None if g_m2 is None else round(g_m2, 1),
                            "final_kwh_m2": round(final, 1), "primary_kwh_m2": round(primary, 1),
                            "band_residential": efficiency_band(primary, True), "band_nonresidential": efficiency_band(primary, False),
                            "standard_apartment": STANDARD_INDICATOR_2024["공동주택"][zone], "standard_office": STANDARD_INDICATOR_2024["업무시설"][zone]}
        b = out["buildings"]
        table += [
            {"label": f"건물 전체 최종에너지 원단위 ({latest}년, 전력+가스)", "value": f"{final:,.1f} kWh/m²·년",
             "reference": f"표준지표 2024 공동주택 {zone} {b['standard_apartment']:,.0f}, 업무시설 {zone} {b['standard_office']:,.0f}", "source": SOURCES["standard"]},
            {"label": f"건물 전체 1차에너지 환산 원단위 ({latest}년)", "value": f"{primary:,.1f} kWh/m²·년",
             "reference": f"효율등급 구간: 주거용 {b['band_residential']}, 주거용 외 {b['band_nonresidential']} 수준", "source": SOURCES["grades"]},
        ]
        out["available"] = True
    e = effort_result or {}
    if e.get("available") and e.get("new_load_kwh"):
        added = float(e.get("added_floor_area_m2") or 0)
        mix = e.get("mix") or {}
        pv_kwh = mix.get("pv_kwh") if mix.get("pv_counted") else None
        new_kwh = float(e["new_load_kwh"]) * (1 - float(mix.get("new_efficiency_pct") or 0) / 100)
        ratio = round(pv_kwh / new_kwh * 100, 1) if pv_kwh and new_kwh > 0 else None
        out["zeb"] = {"added_floor_area_m2": added, "new_load_kwh": round(new_kwh, 1), "pv_kwh": pv_kwh, "self_sufficiency_pct": ratio,
                      "grade": zeb_grade(ratio), "mandatory_scale": added >= ZEB_PRIVATE_MIN_GFA_M2,
                      "needed_pv_kwh_grade5": round(new_kwh * 0.2, 1), "needed_pv_kwh_grade4": round(new_kwh * 0.4, 1)}
        z = out["zeb"]
        table.append({"label": "신축 에너지자립률 (전력 기준, 참고)",
                      "value": f"{ratio:,.1f}% ({z['grade']})" if ratio is not None else "태양광 미입력",
                      "reference": f"ZEB 5등급 20% · 4등급 40% (신축 전력 {new_kwh:,.0f} kWh/년 기준 태양광 {z['needed_pv_kwh_grade5']:,.0f} · {z['needed_pv_kwh_grade4']:,.0f} kWh/년)",
                      "source": SOURCES["grades"]})
        if z["mandatory_scale"]:
            out["notes"].append(f"추가 연면적 {added:,.0f}m²는 2025년 민간 ZEB 의무 규모(연면적 {ZEB_PRIVATE_MIN_GFA_M2:,.0f}m² 이상, 공동주택은 {ZEB_PRIVATE_MIN_HOUSEHOLDS}세대 이상)에 해당할 수 있습니다(용도·허가 시점 확인 필요).")
        out["available"] = True
    if out["available"]:
        out["notes"] += [
            "효율등급·ZEB 등급은 표준 조건의 설계 평가(5개 용도)이고 이 값은 계량된 실사용(가전·취사 포함)이라 등급 판정이 아니라 참고 위치입니다.",
            "1차에너지 환산: 전력 2.75, 가스(연료) 1.1. 지역난방 열은 건축HUB에 없어 빠졌습니다.",
            "표준지표의 1차/최종 에너지 구분과 전북의 지역(중부) 배정은 원문 확인이 필요합니다.",
        ]
    return out


def industry_facts(block: dict[str, Any], add: Any) -> None:
    if not block.get("available"):
        return
    b = block.get("buildings")
    if b:
        add("bench_buildings", f"{b['year']}년 건물 전체(건축HUB 계측 지번) 원단위는 전력 {b['electricity_kwh_m2']:,.1f}"
            + (f"·가스 {b['gas_kwh_m2']:,.1f}" if b.get("gas_kwh_m2") is not None else "")
            + f" kWh/m²·년이고 1차에너지로 환산하면 {b['primary_kwh_m2']:,.1f} kWh/m²·년입니다(전력 2.75·가스 1.1). "
            f"국토교통부 2024 표준지표 공동주택({block['zone']}) 중앙값 {b['standard_apartment']:,.0f} kWh/m²·년과 나란히 보는 참고값입니다.",
            b["year"], b["electricity_kwh_m2"], b.get("gas_kwh_m2"), b["primary_kwh_m2"], 2.75, 1.1, 2024, b["standard_apartment"])
    z = block.get("zeb")
    if z:
        if z.get("self_sufficiency_pct") is not None:
            add("bench_zeb", f"신축 전력 {z['new_load_kwh']:,.0f} kWh/년에 태양광 {z['pv_kwh']:,.0f} kWh/년이면 전력 기준 에너지자립률은 {z['self_sufficiency_pct']:,.1f}%로 "
                f"ZEB {z['grade']} 수준입니다(참고, 인증은 설계 평가).", z["new_load_kwh"], z["pv_kwh"], z["self_sufficiency_pct"])
        else:
            add("bench_zeb", f"신축 전력 {z['new_load_kwh']:,.0f} kWh/년 기준으로 ZEB 5등급(자립률 20%)에는 태양광 약 {z['needed_pv_kwh_grade5']:,.0f} kWh/년, "
                f"4등급(40%)에는 {z['needed_pv_kwh_grade4']:,.0f} kWh/년이 필요합니다(참고).", z["new_load_kwh"], z["needed_pv_kwh_grade5"], z["needed_pv_kwh_grade4"], 20, 40, 5, 4)
