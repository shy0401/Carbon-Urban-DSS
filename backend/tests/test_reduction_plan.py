"""탄소 감축 방안 (기준 문서 5.15): 다른 안과 견주지 않고 같은 계획을 대책 없음에서 수단을 하나씩 더해 줄인다."""
import pytest

from app.area import recommended_mix
from app.reduction_plan import building_plan, plan_text, roof_pv, zeb_grade

FACTORS = {"ELECTRICITY": {"factor": 0.4}, "GAS": {"factor": 0.2}}


def test_ladder_from_no_measures_through_efficiency_heat_pump_and_rooftop_pv():
    p = building_plan({"electricity_kwh": 1_000_000, "gas_kwh": 500_000}, 1000, FACTORS, {"kwh_per_kw": 1200, "label": "추정"}, plan_carbon_kg=450_000)
    assert p["available"] and p["start"]["carbon_kg"] == 500_000
    keys = [s["key"] for s in p["steps"]]
    assert keys == ["efficiency", "heat_pump", "rooftop_pv"]
    eff, hp, pv = p["steps"]
    assert eff["carbon_kg"] == 400_000 and eff["reduction_kg"] == 100_000 and eff["cumulative_pct"] == 20.0
    # 가스 400,000 kWh × 0.9 ÷ COP 3 = 전력 120,000 kWh: 0.4 × 920,000
    assert hp["electricity_kwh"] == 920_000 and hp["gas_kwh"] == 0 and hp["carbon_kg"] == 368_000 and hp["reduction_kg"] == 32_000
    # 옥상 1,000 × 0.6 = 600 m² → 60 kW × 1,200 = 72,000 kWh
    assert p["pv"]["roof_m2"] == 600 and p["pv"]["kw"] == 60 and p["pv"]["kwh"] == 72_000
    assert pv["carbon_kg"] == 339_200 and pv["cumulative_pct"] == 32.2
    assert p["final_carbon_kg"] == 339_200 and p["final_pct"] == 32.2
    assert p["self_sufficiency_pct"] == 7.8 and p["zeb_grade"] is None
    assert p["residual"]["electricity_kwh"] == 848_000 and p["residual"]["offsite_pv_kw"] == 706.7
    assert p["plan"] == {"carbon_kg": 450_000, "pct": 10.0}
    assert "339.2 t" in plan_text(p) and "구역 밖 재생에너지" in plan_text(p)


def test_missing_inputs_drop_the_step_instead_of_using_zero():
    assert building_plan({"electricity_kwh": None, "gas_kwh": 1}, 1000, FACTORS)["available"] is False
    assert building_plan({"electricity_kwh": 1, "gas_kwh": 1}, 1000, {"ELECTRICITY": {"factor": None}})["available"] is False
    no_gas = building_plan({"electricity_kwh": 100_000, "gas_kwh": None}, 500, FACTORS, None)
    assert [s["key"] for s in no_gas["steps"]] == ["efficiency"] and no_gas["start"]["gas_kwh"] is None
    assert any("가스 사용량이 없어" in a for a in no_gas["assumptions"])
    no_yield = building_plan({"electricity_kwh": 100_000, "gas_kwh": 50_000}, 500, FACTORS, None)
    assert [s["key"] for s in no_yield["steps"]] == ["efficiency", "heat_pump"] and no_yield["pv"]["kwh"] is None
    assert no_yield["residual"]["offsite_pv_kw"] is None


def test_rooftop_pv_beyond_own_use_is_not_counted_and_zeb_band_is_reference_only():
    p = building_plan({"electricity_kwh": 10_000, "gas_kwh": 0}, 2000, FACTORS, {"kwh_per_kw": 1200, "label": "추정"})
    assert p["pv"]["kwh"] == 144_000 and p["pv"]["used_kwh"] == 8000 and p["pv"]["surplus_kwh"] == 136_000
    assert p["final_carbon_kg"] == 0 and p["final_pct"] == 100.0 and p["residual"]["offsite_pv_kw"] is None
    assert zeb_grade(19.9) is None and zeb_grade(20) == "5등급" and zeb_grade(45) == "4등급" and zeb_grade(120) == "1등급"
    assert roof_pv(0, 1200) is None and roof_pv(100, None) == {"roof_m2": 60.0, "kw": 6.0, "kwh": None}


def _effort(**kw):
    base = {"available": True, "factor_kgco2eq_per_kwh": 0.433, "new_load_kwh": 5_331_000.0, "baseline_kwh": 101_269_161.0, "removed_floor_area_m2": 0,
            "intensity_kwh_per_m2": 53.31, "required_reduction_kgco2eq": 11_078_232.3, "pv_yield": {"kwh_per_kw": 1199.9}}
    base.update(kw)
    return base


def test_recommended_mix_is_new_20_existing_5_then_pv_in_10_kw_steps():
    rec = recommended_mix(_effort())
    assert [s["key"] for s in rec["steps"]] == ["new", "existing", "pv"]
    assert rec["new_efficiency_pct"] == 20 and rec["existing_efficiency_pct"] == 5
    assert rec["pv_kw"] % 10 == 0 and rec["met"] and rec["roof_m2"] == rec["pv_kw"] * 10
    smaller = recommended_mix(dict(_effort(), pv_kw=None) | {"pv_yield": {"kwh_per_kw": 1199.9}})
    assert smaller["pv_kw"] == rec["pv_kw"]
    # 신축 20% + 기존 5% = 1,066,200 + 5,063,458 kWh → 2,654,077 kg; 나머지 8,424,155 kg ÷ 0.433 ÷ 1,199.9 = 16,214 kW → 16,220
    assert rec["pv_kw"] == 16220 and rec["new_kwh"] == pytest.approx(1_066_200.0) and rec["existing_kwh"] == pytest.approx(5_063_458.1, abs=0.1)


def test_recommended_mix_without_yield_states_the_offset_kwh_only():
    rec = recommended_mix(_effort(pv_yield=None))
    assert [s["key"] for s in rec["steps"]] == ["new", "existing"] and not rec["met"] and rec["offset_kwh"] > 0
    assert recommended_mix({"available": True, "factor_kgco2eq_per_kwh": None}) is None
