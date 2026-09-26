from app.grid_metrics import consistent_baseline, grid_energy_intensity

MONTHS = [f"2025{m:02d}" for m in range(1, 13)]


def rows(code, energy_type, value, area, months=MONTHS, grid="g"):
    return [{"grid_id": grid, "kapt_code": code, "energy_type": energy_type, "use_ym": m, "usage_kwh": value, "matched_gross_floor_area_m2": area} for m in months]


def test_intensity_uses_only_parcels_observed_in_all_twelve_months():
    data = rows("A", "ELECTRICITY", 1000.0, 1000.0) + rows("B", "ELECTRICITY", 500.0, 500.0, MONTHS[:11])
    result = grid_energy_intensity(data, {"A": 10, "B": 5})["g"]["ELECTRICITY"]
    assert result["observed_parcels"] == 2 and result["complete_parcels"] == 1
    assert result["kwh"] == 12000.0 and result["area_m2"] == 1000.0
    assert result["kwh_per_m2"] == 12.0 and result["kwh_per_household"] == 1200.0


def test_ratios_use_only_parcels_with_their_own_denominator():
    data = rows("A", "ELECTRICITY", 1000.0, 1000.0) + rows("B", "ELECTRICITY", 500.0, None)
    result = grid_energy_intensity(data, {"A": 10})["g"]["ELECTRICITY"]
    assert result["complete_parcels"] == 2 and result["kwh"] == 18000.0
    # B has neither area nor households: both ratios describe parcel A only.
    assert result["area_parcels"] == 1 and result["kwh_per_m2"] == 12.0
    assert result["household_parcels"] == 1 and result["kwh_per_household"] == 1200.0
    assert grid_energy_intensity(rows("C", "ELECTRICITY", 5.0, None), {})["g"]["ELECTRICITY"]["kwh_per_m2"] is None


def test_consistent_baseline_prefers_parcels_with_both_energy_types():
    data = rows("A", "ELECTRICITY", 10.0, 100.0) + rows("A", "GAS", 20.0, 100.0) + rows("B", "ELECTRICITY", 5.0, 50.0)
    base = consistent_baseline(data, MONTHS)
    assert base["parcels"] == ["A"] and base["excluded_parcels"] == ["B"]
    assert base["energy_types"] == ["ELECTRICITY", "GAS"] and base["area_m2"] == 100.0
    assert base["monthly"][0] == {"use_ym": "202501", "electricity_kwh": 10.0, "gas_kwh": 20.0}


def test_consistent_baseline_falls_back_to_electricity_and_rejects_incomplete_sets():
    base = consistent_baseline(rows("B", "ELECTRICITY", 5.0, 50.0), MONTHS)
    assert base["energy_types"] == ["ELECTRICITY"] and base["monthly"][0]["gas_kwh"] is None
    assert consistent_baseline(rows("C", "ELECTRICITY", 5.0, 50.0, MONTHS[:6]), MONTHS) is None
    assert consistent_baseline(rows("D", "ELECTRICITY", 5.0, None), MONTHS) is None


def test_implausible_published_floor_area_is_never_used_as_a_denominator():
    from types import SimpleNamespace
    from app.grid_metrics import floor_area_status, validated_complex_areas
    assert floor_area_status(94993.33, 796) == ("OK", None)
    assert floor_area_status(225711, 320)[0] == "IMPLAUSIBLE"          # 705 m² per household
    assert floor_area_status(3540.77, 135, 11460.69)[0] == "IMPLAUSIBLE"  # smaller than the billed area
    assert floor_area_status(0, 96)[0] == "MISSING"
    complexes = [SimpleNamespace(kapt_code="A", name="a", gross_floor_area_m2=1000.0, households=10, management_area_m2=None),
                 SimpleNamespace(kapt_code="B", name="b", gross_floor_area_m2=225711.0, households=320, management_area_m2=19023.65)]
    areas, issues = validated_complex_areas(complexes)
    assert areas == {"A": 1000.0, "B": None} and issues["B"]["status"] == "IMPLAUSIBLE"
    data = rows("A", "ELECTRICITY", 1000.0, 1000.0) + rows("B", "ELECTRICITY", 50000.0, 225711.0)
    result = grid_energy_intensity(data, {"A": 10, "B": 320}, areas)["g"]["ELECTRICITY"]
    assert result["complete_parcels"] == 2 and result["area_parcels"] == 1 and result["kwh_per_m2"] == 12.0  # B's area is not usable
    base = consistent_baseline(data, MONTHS, areas)
    assert base["parcels"] == ["A"] and base["excluded_parcels"] == ["B"] and base["area_m2"] == 1000.0


def test_partial_or_mixed_meters_are_kept_out_of_totals_and_ratios():
    from app.grid_metrics import electricity_plausibility
    assert electricity_plausibility(75.9 * 211, 211)[0] == "SUSPECT"      # common-area meter only
    assert electricity_plausibility(23873.3 * 494, 494)[0] == "SUSPECT"   # includes other buildings
    assert electricity_plausibility(4200.0 * 500, 500) == ("OK", None)
    assert electricity_plausibility(1000.0, None)[0] == "UNKNOWN"         # no households: cannot judge
    data = rows("A", "ELECTRICITY", 35000.0, 50000.0) + rows("P", "ELECTRICITY", 1300.0, 30000.0)
    result = grid_energy_intensity(data, {"A": 100, "P": 211})["g"]["ELECTRICITY"]
    assert result["complete_parcels"] == 1 and result["suspect_parcels"] == 1
    assert result["kwh"] == 420000.0 and result["kwh_per_household"] == 4200.0
    base = consistent_baseline(data, MONTHS, None, {"A": 100, "P": 211})
    assert base["parcels"] == ["A"] and "P" in base["excluded_parcels"]
