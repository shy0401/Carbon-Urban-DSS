"""탄소 감축 방안 (기준 문서 5.15): 다른 안과 견주지 않고 같은 계획을 대책 없음에서 수단을 하나씩 더해 줄인다. 절감률은 실측 지표."""
import pytest

from app.area import recommended_mix
from app.reduction_plan import building_plan, plan_text, roof_pv, zeb_grade

FACTORS = {"ELECTRICITY": {"factor": 0.4}, "GAS": {"factor": 0.2}}


def test_ladder_from_no_measures_through_envelope_operation_rooftop_pv_and_greenery():
    p = building_plan({"electricity_kwh": 1_000_000, "gas_kwh": 500_000}, 1000, FACTORS, {"kwh_per_kw": 1200, "label": "추정"}, plan_carbon_kg=450_000, green_area_m2=3000)
    assert p["available"] and p["start"]["carbon_kg"] == 500_000
    keys = [s["key"] for s in p["steps"]]
    assert keys == ["envelope", "operation", "rooftop_pv", "greenery"]   # 히트펌프 단계는 2026-11-11부터 기본에서 뺌
    env, op, pv, green = p["steps"]
    # 단열·창호: 가스 500,000 × (1 − 0.236) = 382,000 kWh, 전력은 그대로
    assert env["electricity_kwh"] == 1_000_000 and env["gas_kwh"] == 382_000 and env["carbon_kg"] == 476_400 and env["cumulative_pct"] == 4.7
    # 에너지 절약 운영: 전력 1,000,000 × (1 − 0.048) = 952,000 kWh
    assert op["electricity_kwh"] == 952_000 and op["gas_kwh"] == 382_000 and op["carbon_kg"] == 457_200 and op["reduction_kg"] == 19_200
    # 옥상 1,000 × 0.6 = 600 m² → 60 kW × 1,200 = 72,000 kWh
    assert p["pv"]["roof_m2"] == 600 and p["pv"]["kw"] == 60 and p["pv"]["kwh"] == 72_000
    assert pv["carbon_kg"] == 428_400 and pv["cumulative_pct"] == 14.3
    # 녹지 3,000 m² × 1.0 kg = 3,000 kg 흡수(상쇄): 전력·가스는 그대로, 탄소만 줄어든다
    assert green["electricity_kwh"] == 880_000 and green["carbon_kg"] == 425_400 and green["reduction_kg"] == 3000
    assert p["green"] == {"area_m2": 3000, "uptake_kg": 3000, "range_kg": [2640.0, 4770.0]}
    # 지표의 실측 범위: 계산은 중앙값, 범위는 그 단계 감축량이 움직일 수 있는 폭 (가스 500,000 × 20.5~25.8% × 0.2, 전력 1,000,000 × 1.95~17.0% × 0.4)
    assert env["range_pct"] == [20.5, 25.8] and env["reduction_range_kg"] == [20_500, 25_800]
    assert op["range_pct"] == [1.95, 17.0] and op["reduction_range_kg"] == [7_800, 68_000]
    assert pv["range_pct"] is None and pv["reduction_range_kg"] is None
    assert green["range_pct"] is None and green["reduction_range_kg"] == [2640.0, 4770.0]
    assert p["final_carbon_kg"] == 425_400 and p["final_pct"] == 14.9
    assert p["self_sufficiency_pct"] == 6.5 and p["zeb_grade"] is None
    assert p["residual"]["electricity_kwh"] == 880_000 and p["residual"]["offsite_pv_kw"] == 733.3
    assert p["plan"] == {"carbon_kg": 450_000, "pct": 10.0}
    assert "425.4 t" in plan_text(p) and "구역 밖 재생에너지" in plan_text(p)
    assert any("78쌍" in a for a in p["assumptions"]) and any("히트펌프" in a and "넣지 않았습니다" in a for a in p["assumptions"])


def test_missing_inputs_drop_the_step_instead_of_using_zero():
    assert building_plan({"electricity_kwh": None, "gas_kwh": 1}, 1000, FACTORS)["available"] is False
    assert building_plan({"electricity_kwh": 1, "gas_kwh": 1}, 1000, {"ELECTRICITY": {"factor": None}})["available"] is False
    no_gas = building_plan({"electricity_kwh": 100_000, "gas_kwh": None}, 500, FACTORS, None)
    assert [s["key"] for s in no_gas["steps"]] == ["operation"] and no_gas["start"]["gas_kwh"] is None
    assert any("가스 사용량이 없어" in a for a in no_gas["assumptions"])
    no_yield = building_plan({"electricity_kwh": 100_000, "gas_kwh": 50_000}, 500, FACTORS, None)
    assert [s["key"] for s in no_yield["steps"]] == ["envelope", "operation"] and no_yield["pv"]["kwh"] is None
    assert no_yield["residual"]["offsite_pv_kw"] is None
    assert no_yield["green"] is None and any("녹지 면적이 없어" in a for a in no_yield["assumptions"])


def test_rooftop_pv_beyond_own_use_is_not_counted_and_zeb_band_is_reference_only():
    p = building_plan({"electricity_kwh": 10_000, "gas_kwh": 0}, 2000, FACTORS, {"kwh_per_kw": 1200, "label": "추정"})
    # 에너지 절약 운영 뒤 전력 10,000 × (1 − 0.048) = 9,520 kWh까지만 태양광으로 셈
    assert p["pv"]["kwh"] == 144_000 and p["pv"]["used_kwh"] == 9520 and p["pv"]["surplus_kwh"] == 134_480
    assert p["final_carbon_kg"] == 0 and p["final_pct"] == 100.0 and p["residual"]["offsite_pv_kw"] is None
    assert zeb_grade(19.9) is None and zeb_grade(20) == "5등급" and zeb_grade(45) == "4등급" and zeb_grade(120) == "1등급"
    assert roof_pv(0, 1200) is None and roof_pv(100, None) == {"roof_m2": 60.0, "kw": 6.0, "kwh": None}


def _effort(**kw):
    base = {"available": True, "factor_kgco2eq_per_kwh": 0.433, "new_load_kwh": 5_331_000.0, "baseline_kwh": 101_269_161.0, "removed_floor_area_m2": 0,
            "intensity_kwh_per_m2": 53.31, "required_reduction_kgco2eq": 11_078_232.3, "pv_yield": {"kwh_per_kw": 1199.9}}
    base.update(kw)
    return base


def test_recommended_mix_is_new_11_3_existing_4_8_then_pv_in_10_kw_steps():
    rec = recommended_mix(_effort())
    assert [s["key"] for s in rec["steps"]] == ["new", "existing", "pv"]
    assert rec["new_efficiency_pct"] == 11.3 and rec["existing_efficiency_pct"] == 4.8   # 실측 문헌 중앙값 (docs/REDUCTION_INDICATORS.md)
    assert rec["steps"][0]["detail"] == "신축 전력 11.3% 절감" and rec["steps"][1]["detail"] == "기존 건물 전력 4.8% 절감"
    assert rec["pv_kw"] % 10 == 0 and rec["met"] and rec["roof_m2"] == rec["pv_kw"] * 10
    smaller = recommended_mix(dict(_effort(), pv_kw=None) | {"pv_yield": {"kwh_per_kw": 1199.9}})
    assert smaller["pv_kw"] == rec["pv_kw"]
    # 신축 11.3% + 기존 4.8% = 602,403 + 4,860,920 kWh → 2,365,619 kg; 나머지 8,712,614 kg ÷ 0.433 ÷ 1,199.9 = 16,769 kW → 16,770
    assert rec["pv_kw"] == 16770 and rec["new_kwh"] == pytest.approx(602_403.0) and rec["existing_kwh"] == pytest.approx(4_860_919.7, abs=0.1)


def test_recommended_mix_without_yield_states_the_offset_kwh_only():
    rec = recommended_mix(_effort(pv_yield=None))
    assert [s["key"] for s in rec["steps"]] == ["new", "existing"] and not rec["met"] and rec["offset_kwh"] > 0
    assert recommended_mix({"available": True, "factor_kgco2eq_per_kwh": None}) is None
