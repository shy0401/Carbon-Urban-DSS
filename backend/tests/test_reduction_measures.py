"""감축 수단 목록 (기준 문서 5.15): 사다리에 넣지 않은 수단은 따로 본 값으로, 근거가 없으면 지표만, 내재탄소는 참고 계산."""
from pathlib import Path

import pytest

from app.reduction_measures import (EMBODIED_KG_PER_M2, EMBODIED_MEASURES, EMBODIED_READYMIX_SHARE, MEASURES, catalog, embodied, embodied_text,
                                    measure_table)
from app.reduction_plan import ENVELOPE_GAS_SAVING, ENVELOPE_GAS_SAVING_RANGE, OPERATION_ELECTRICITY_SAVING, OPERATION_ELECTRICITY_SAVING_RANGE, building_plan

FACTORS = {"ELECTRICITY": {"factor": 0.4}, "GAS": {"factor": 0.2}}


def by_key(rows):
    return {r["key"]: r for r in rows}


def test_catalog_has_every_field_a_reader_needs_and_matches_the_ladder_constants():
    c = catalog()
    keys = [m["key"] for m in c["measures"]]
    assert len(keys) == len(set(keys)) == 14 and [m["key"] for m in c["embodied_measures"]] == ["low_carbon_concrete", "modular", "frame_system", "keep_structure"]
    for m in c["measures"] + c["embodied_measures"]:
        assert m["title"] and m["what"] and m["cost"] and m["note"] and m["evidence_label"] and m["use_label"] and m["apply"]
        assert m["sources"] and all(s["label"] and s["url"] for s in m["sources"])
        if m["range_pct"]:
            assert m["range_pct"][0] <= m["range_pct"][1]
    # 사다리 단계의 지표는 reduction_plan 상수와 같아야 한다(두 곳에 적힌 같은 값)
    table = {m["key"]: m for m in MEASURES}
    assert table["envelope"]["value"] == ENVELOPE_GAS_SAVING and table["envelope"]["range"] == ENVELOPE_GAS_SAVING_RANGE
    assert table["operation"]["value"] == OPERATION_ELECTRICITY_SAVING and table["operation"]["range"] == OPERATION_ELECTRICITY_SAVING_RANGE
    # 사다리에는 실측 지표와 가정(태양광·녹지)만: 설계·계산과 기업 발표 값은 '지표만' 또는 내재탄소 참고
    assert {m["key"] for m in MEASURES if m["use"] == "ladder"} == {"envelope", "operation", "rooftop_pv", "greenery"}
    assert all(m["evidence"] in ("measured", "agency") for m in MEASURES if m["use"] == "alone")
    assert all(m["evidence"] == "calc" for m in EMBODIED_MEASURES)
    assert c["embodied_basis"]["kg_per_m2"] == 445.4 and c["embodied_basis"]["range_kg_per_m2"] == [340.3, 586.0] and c["embodied_basis"]["readymix_share_pct"] == 14.9


def test_each_measure_alone_on_the_plan_and_indicator_only_rows_have_no_value():
    rows = by_key(measure_table(1_000_000, 500_000, 0.4, 0.2, pv={"kwh": 72_000}, green={"uptake_kg": 3000, "range_kg": [2640.0, 4770.0]}))
    # 대책 없음 500,000 kg = 전력 400,000 + 가스 100,000
    assert rows["envelope"]["alone_kg"] == 23_600 and rows["envelope"]["alone_pct"] == 4.7 and rows["envelope"]["alone_range_kg"] == [20_500, 25_800]
    assert rows["operation"]["alone_kg"] == 19_200 and rows["operation"]["alone_range_kg"] == [7_800, 68_000]
    # 신축 통합 기준: 총에너지 −11.3%를 전력·가스에 같은 비율로. 범위의 음수는 늘어남(+6.7%)
    assert rows["new_build_package"]["alone_kg"] == 56_500 and rows["new_build_package"]["alone_range_kg"] == [-33_500, 230_000]
    assert rows["heat_recovery_ventilation"]["alone_kg"] == 17_500 and rows["heat_recovery_ventilation"]["alone_range_kg"] == [5_000, 30_000]
    assert rows["home_energy_display"]["alone_kg"] == 46_800 and rows["home_energy_display"]["alone_pct"] == 9.4   # 전력 400,000 × 11.7%
    assert rows["rooftop_pv"]["alone_kg"] == 28_800 and rows["greenery"]["alone_kg"] == 3000
    # 계산 근거가 계획안에 없는 수단: 값을 지어내지 않고 지표와 이유만
    for key in ("passive_package", "window_retrofit", "shading", "common_lighting", "elevator_regeneration", "condensing_boiler", "district_heating_control"):
        assert rows[key]["alone_kg"] is None and rows[key]["alone_range_kg"] is None and rows[key]["reason"]
    assert rows["common_lighting"]["value_pct"] == 40.0 and rows["common_lighting"]["range_pct"] == [10.0, 82.5]


def test_missing_gas_pv_or_green_leaves_the_value_empty_not_zero():
    rows = by_key(measure_table(1_000_000, None, 0.4, None))
    assert rows["envelope"]["alone_kg"] is None and "가스" in rows["envelope"]["reason"]
    assert rows["rooftop_pv"]["alone_kg"] is None and rows["greenery"]["alone_kg"] is None
    assert rows["new_build_package"]["alone_kg"] == 45_200   # 전력만 있는 계획안: 400,000 × 11.3%


def test_embodied_carbon_is_a_reference_calculation_with_its_range_and_options():
    e = embodied(20_000, 500_000, floors=12)
    assert e["carbon_kg"] == 8_908_000 and e["range_kg"] == [6_806_000, 11_720_000] and e["years_of_operation"] == 17.8
    opt = by_key(e["options"])
    # 저탄소 콘크리트: 레미콘 몫 14.9%에만 −12.05%(−7.8~−16.3%)
    assert opt["low_carbon_concrete"]["reduction_kg"] == pytest.approx(20_000 * EMBODIED_KG_PER_M2 * EMBODIED_READYMIX_SHARE * 0.1205, abs=0.1)
    assert opt["low_carbon_concrete"]["reduction_pct"] == 1.8
    assert opt["modular"]["reduction_kg"] == 3_126_708 and opt["modular"]["reduction_pct"] == 35.1
    assert opt["frame_system"]["reduction_kg"] is None and opt["keep_structure"]["reduction_kg"] is None and opt["frame_system"]["reason"]
    assert "8,908 t" in embodied_text(e) and "17.8년치" in embodied_text(e) and "참고 계산" in embodied_text(e)
    # 49층 계획안: 국내 모듈러 준공 사례가 13층까지라 값을 내지 않는다
    high = by_key(embodied(20_000, 500_000, floors=49)["options"])
    assert high["modular"]["reduction_kg"] is None and "13층" in high["modular"]["reason"]
    assert embodied(None) is None and embodied(0) is None and embodied_text(None) is None


def test_the_ladder_result_carries_the_measures_and_embodied_block_without_changing_the_ladder():
    args = ({"electricity_kwh": 1_000_000, "gas_kwh": 500_000}, 1000, FACTORS, {"kwh_per_kw": 1200, "label": "추정"})
    before = building_plan(*args, plan_carbon_kg=450_000, green_area_m2=3000)
    after = building_plan(*args, plan_carbon_kg=450_000, green_area_m2=3000, floor_area_m2=20_000, floors=12)
    assert after["steps"] == before["steps"] and after["final_carbon_kg"] == before["final_carbon_kg"] == 425_400
    assert before["embodied"] is None and after["embodied"]["carbon_kg"] == 8_908_000
    assert [m["key"] for m in after["measures"]] == [m["key"] for m in MEASURES]
    rows = by_key(after["measures"])
    assert rows["new_build_package"]["alone_kg"] == 56_500 and rows["passive_package"]["alone_kg"] is None


def test_indicator_document_lists_every_measure_with_the_same_indicator():
    """코드의 목록과 docs/REDUCTION_INDICATORS.md 7·9절 표는 같은 값이어야 한다 (컨테이너에는 docs가 없어 건너뜀)."""
    doc = Path(__file__).resolve().parents[2] / "docs" / "REDUCTION_INDICATORS.md"
    if not doc.is_file():
        pytest.skip("docs are not in this image")
    text = doc.read_text(encoding="utf-8")
    c = catalog()
    for m in c["measures"] + c["embodied_measures"]:
        assert f"| {m['title']} | {m['indicator_text']} |" in text, m["key"]
    assert "445.4 kgCO2/m²" in text and "340.3~586.0" in text and "14.9%" in text
