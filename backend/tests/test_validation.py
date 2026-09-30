"""공식 통계 대조(검증)·난방방식 구분·전력 출처 일관성 (DB 없이)."""
from types import SimpleNamespace

from app.area import consistent_energy, yearly_energy
from app.modeling import fit_candidates
from app.service import grid_heating, heating_group
from app.validation import monthly_agreement, pearson, ratio_summary


def test_monthly_agreement_reports_yearly_ratio_correlation_and_range():
    other = {f"2025{m:02d}": 100.0 + 10 * m for m in range(1, 13)}
    hub = {ym: v * 0.8 for ym, v in other.items()}
    a = monthly_agreement(hub, other, 2025)
    assert a == {"year": 2025, "ratio": 0.8, "monthly_r": 1.0, "ratio_min": 0.8, "ratio_max": 0.8}
    hub.pop("202512")
    assert monthly_agreement(hub, other, 2025) is None  # a missing month: no yearly ratio (never a partial year)
    assert pearson([1, 2], [1, 2]) is None and pearson([1, 1, 1], [1, 2, 3]) is None


def test_ratio_summary_drops_empty_values():
    s = ratio_summary([0.7, 0.75, 0.8, 0.9, 1.0, 1.9, None, 0, float("inf")])
    assert s["pairs"] == 6 and s["median"] == 0.85 and s["within_20pct"] == round(3 / 6, 3)
    assert ratio_summary([]) is None


def test_heating_groups_follow_floor_area():
    assert heating_group("지역난방") == "district" and heating_group("개별난방") == "individual" and heating_group("중앙난방") == "individual"
    assert heating_group("-") is None and heating_group(None) is None
    complexes = [SimpleNamespace(heating_type="지역난방", gross_floor_area_m2=5000), SimpleNamespace(heating_type="개별난방", gross_floor_area_m2=20000),
                 SimpleNamespace(heating_type=None, gross_floor_area_m2=99999)]
    assert grid_heating(complexes) == "individual"
    assert grid_heating([SimpleNamespace(heating_type="-", gross_floor_area_m2=1)]) is None


def rows_for(code: str, source: str, kwh: float, year: int, energy: str = "ELECTRICITY") -> list[dict]:
    return [{"use_ym": f"{year}{m:02d}", "energy_type": energy, "usage_kwh": kwh, "grid_id": "g1", "kapt_code": code,
             "parcel": f"{source}:{code}", "source": source} for m in range(1, 13)]


def test_area_series_keeps_one_provider_per_energy_type():
    complexes = {"A1": {"kapt_code": "A1", "approval_year": 2000, "households": 500, "gfa": 50000, "floor_area_ok": True}}
    area = {"grid_ids": ["g1"], "complex_codes": ["A1"]}
    # K-apt reports 150,000 kWh/month in both years (3,600 kWh per household a year); 건축HUB meters 200,000 from 2024
    rows = rows_for("A1", "KAPT", 150000.0, 2023) + rows_for("A1", "KAPT", 150000.0, 2024) + rows_for("A1", "HUB", 200000.0, 2024) \
        + rows_for("A1", "HUB", 50000.0, 2024, "GAS")
    mixed = yearly_energy(rows, area, complexes, [2023, 2024])
    assert mixed[2024]["electricity"]["kwh"] == 12 * 350000.0  # both providers counted: the old jump
    series = consistent_energy(rows, area, complexes, [2023, 2024])
    assert series[2023]["electricity"]["kwh"] == series[2024]["electricity"]["kwh"] == 1_800_000.0
    assert series[2024]["gas"]["kwh"] == 600_000.0 and series[2023]["gas"]["kwh"] is None
    assert "K-apt" in series[2024]["sources"]["electricity"]


def test_constant_features_are_not_used():
    rows = []
    for g in range(12):
        for m in range(1, 13):
            rows.append({"grid_id": f"g{g}", "spatial_block": f"b{g % 4}", "use_ym": f"2025{m:02d}", "usage_kwh": 1000.0 + 10 * g + m,
                         "floor_area_m2": 100.0, "month_sin": 0.0, "month_cos": 1.0, "hdd": float(m), "cdd": 0.0,
                         "area_per_household": 80.0 + g, "age": 10.0, "district_share": 0.0})
    result = fit_candidates(rows)
    features = result["models"][0]["features"]
    assert "district_share" not in features and "age" not in features and "area_per_household" in features


def test_existing_change_uses_complexes_reported_in_every_observed_year():
    from app.area import before_after
    def year(y, by):
        return {"electricity": {"kwh": sum(by.values()) or None, "by_cohort": {"2000": sum(by.values())}, "by_complex": by},
                "gas": {"kwh": None, "by_cohort": {}, "by_complex": {}}, "estimated": {"kwh": None}}
    # B starts reporting to K-apt in 2023: its 1,000 must not look like a rise in use of the existing buildings
    energy = {2021: year(2021, {"A": 1000.0}), 2022: year(2022, {"A": 1000.0}), 2023: year(2023, {"A": 1000.0, "B": 1000.0}),
              2024: year(2024, {"A": 1100.0, "B": 1000.0}), 2025: year(2025, {"A": 1100.0, "B": 1000.0})}
    history = {"years": list(energy), "energy": energy, "events": {y: {"complexes": 1 if y == 2023 else 0, "households": 10 if y == 2023 else 0} for y in energy},
               "complexes": [{"kapt_code": "A", "approval_year": 2000}, {"kapt_code": "B", "approval_year": 2001}],
               "weather": {}, "population": {}, "stock": {}, "factor": {}}
    m = before_after(history, 2023, 2)["metrics"]["electricity"]
    assert m["existing_complexes"] == 1 and m["existing_change_pct"] == 10.0  # A only: 1,000 → 1,100
    assert m["total_change_pct"] == 110.0  # the totals still show the new reporter (that is why the same-set figure exists)


def test_area_gas_total_keeps_summer_bimonthly_parcels():
    complexes = {"A1": {"kapt_code": "A1", "approval_year": 2000, "households": 500, "gfa": 50000, "floor_area_ok": True}}
    area = {"grid_ids": ["g1"], "complex_codes": ["A1"]}
    gas = [r for r in rows_for("A1", "HUB", 1000.0, 2025, "GAS") if r["use_ym"] not in ("202507", "202509")]
    gap = [r for r in rows_for("A1", "HUB", 1000.0, 2025, "ELECTRICITY") if r["use_ym"] != "202507"]
    out = yearly_energy(gas + gap, area, complexes, [2025])[2025]
    assert out["gas"]["kwh"] == 10_000.0 and out["gas"]["complete_parcels"] == 1
    assert out["electricity"]["kwh"] is None and out["electricity"]["partial_parcels"] == 1


def test_gas_completeness_splits_full_bimonthly_and_gaps():
    from app.validation import completeness_summary
    every = [f"2025{m:02d}" for m in range(1, 13)]
    skip = [ym for ym in every if ym not in ("202506", "202508")]
    gap = [ym for ym in every if ym not in ("202503",)]
    s = completeness_summary(2025, [(every, 1e6), (skip, 2e6), (gap, 3e6), (every, 1e6)])
    assert s == {"year": 2025, "parcels": 4, "full": 2, "bimonthly": 1, "partial": 1, "full_gwh": 2.0, "bimonthly_gwh": 2.0, "partial_gwh": 3.0}
    assert completeness_summary(2025, []) is None
