"""추정 계층 (DATA_STANDARD 4.1): 빈 달·빈 해를 관측 표와 따로 채우는 규칙."""
from app import estimates as est
from app.benchmarks import efficiency_band, industry_block, primary_intensity, zeb_grade


def series_for(years: dict[int, list[float | None]], first_year: int = 2020) -> dict[int, float]:
    out = {}
    for year, months in years.items():
        for m, v in enumerate(months, start=1):
            if v is not None:
                out[est.month_index(year, m, first_year)] = v
    return out


def test_fillable_only_between_observations_and_short_runs():
    s = series_for({2020: [10] * 8 + [None, None] + [10, 10], 2021: [10] * 12})
    t = est.fillable(s, "ELECTRICITY", 2020)
    assert t == [8, 9]  # 2020-09, 2020-10 inside the observed span, run of 2
    # a new meter that starts in July is not filled before its first month
    s = series_for({2020: [None] * 6 + [5] * 6})
    assert est.fillable(s, "ELECTRICITY", 2020) == []
    # a gap of four months stays empty (vacancy or a moved meter is not guessed)
    s = series_for({2020: [10, 10, None, None, None, None, 10, 10, 10, 10, 10, 10]})
    assert est.fillable(s, "ELECTRICITY", 2020) == []


def test_fillable_skips_two_month_gas_bills():
    # July missing, August present: billed together, not a gap
    s = series_for({2021: [9, 8, 7, 5, 3, 2, None, 4, 2, 4, 7, 9]}, 2021)
    assert est.fillable(s, "GAS", 2021) == []
    assert est.fillable(s, "ELECTRICITY", 2021) == [6]


def test_neighbor_year_estimate_scales_by_common_months():
    # the same parcel used 10% more in 2021 than 2022 in the months both years have → September 2021 = 1.1 × September 2022
    s = series_for({2021: [110] * 8 + [None] + [110] * 3, 2022: [100] * 12}, 2021)
    value, refs = est.neighbor_year_estimate(s, est.month_index(2021, 9, 2021))
    assert refs == [1]
    assert round(value, 6) == 110.0


def test_neighbor_needs_six_common_months_then_profile():
    s = series_for({2021: [None] * 3 + [100] * 5 + [None] + [100] * 3}, 2021)
    t = est.month_index(2021, 9, 2021)
    assert est.neighbor_year_estimate(s, t) == (None, [])
    profile = {m: 1 / 12 for m in range(1, 13)}
    assert round(est.profile_estimate(s, t, profile), 6) == 100.0
    filled = est.fill_entity(s, "ELECTRICITY", 2021, {2021: profile})
    assert filled[t][1] == "FILL_CITY_MONTH_PROFILE"


def test_hub_grid_years_keeps_observed_and_estimated_apart():
    grid_of = {"p1": "g1", "p2": "g1"}
    series = {"p1": series_for({2021: [10] * 12, 2022: [10] * 12}, 2021),
              "p2": series_for({2021: [20] * 10 + [None, 20], 2022: [20] * 12}, 2021)}
    fills, _ = est.hub_fill(series, "ELECTRICITY", 2021, [2021, 2022])
    out = est.hub_grid_years(series, fills, grid_of, "ELECTRICITY", 2021, [2021, 2022])
    item = out[("g1", 2021)]
    assert item["complete_parcels"] == 1 and item["partial_parcels"] == 1 and item["filled_parcels"] == 1
    assert item["observed_all_kwh"] == 120 + 220
    assert round(item["filled_kwh"], 6) == 20.0


def test_backcast_drops_parcels_not_yet_built_and_uses_same_index():
    grid_of = {"old": "g1", "new": "g1"}
    months = {y: [100.0] * 12 for y in (2021, 2022, 2023)}
    series = {"old": series_for(months, 2020), "new": series_for(months, 2020)}
    out = est.hub_backcast(series, {}, grid_of, "ELECTRICITY", 2020, [2016, 2019], first_built={"old": 1990, "new": 2018}, unknown_year=set(),
                           kepco={}, hdd={}, same_index={2016: (0.95, 40), 2019: (1.0, 40)})
    assert round(out[("g1", 2016)]["value"], 6) == 1200 * 0.95      # only the old parcel existed
    assert round(out[("g1", 2019)]["value"], 6) == 2400.0            # both existed
    assert out[("g1", 2016)]["exist_share"] == 0.5


def test_backcast_gas_regression_on_heating_degree_days():
    grid_of = {"p": "g1"}
    hdd = {}
    s = {}
    for y in (2021, 2022, 2023):
        for m in range(1, 13):
            h = [500, 400, 300, 150, 50, 0, 0, 0, 10, 100, 250, 450][m - 1] + (y - 2021) * 5
            hdd[(y, m)] = h
            s[est.month_index(y, m, 2020)] = 100 + 2 * h
    for m in range(1, 13):
        hdd[(2017, m)] = [520, 410, 300, 150, 50, 0, 0, 0, 10, 100, 250, 450][m - 1]
    out = est.hub_backcast({"p": s}, {}, grid_of, "GAS", 2020, [2017], first_built={}, unknown_year=set(), kepco={}, hdd=hdd)
    expected = sum(100 + 2 * h for h in [520, 410, 300, 150, 50, 0, 0, 0, 10, 100, 250, 450])
    assert round(out[("g1", 2017)]["value"], 3) == expected


def test_kapt_estimates_methods():
    first = 2015
    years = list(range(2015, 2020))
    monthly = {}
    info = {}
    for i in range(25):  # peers with 12 months in every year
        code = f"P{i}"
        info[code] = {"households": 500, "approval_year": 2000}
        monthly[code] = series_for({y: [125000.0 * (1 + 0.02 * (y - 2015))] * 12 for y in years}, first)
    info["A"] = {"households": 500, "approval_year": 2000}
    monthly["A"] = series_for({2016: [120000.0] * 12, 2017: [126000.0] * 9 + [None] * 3, 2018: [None] * 12}, first)
    info["NEVER"] = {"households": 400, "approval_year": 2010}
    info["NEW"] = {"households": 400, "approval_year": 2019}
    out = est.kapt_estimates(monthly, info, first, years)
    assert out[("A", 2017)]["method"] in ("FILL_SAME_ENTITY_NEIGHBOR_YEAR", "FILL_CITY_MONTH_PROFILE")
    assert out[("A", 2018)]["method"] == "KAPT_NEIGHBOR_YEAR_CITY_INDEX"
    assert out[("A", 2018)]["ref_year"] == 2016
    assert out[("NEVER", 2016)]["method"] == "KAPT_PEER_MEDIAN_PER_HOUSEHOLD"
    assert ("NEW", 2019) not in out          # the year of 사용승인 is not estimated
    assert ("P0", 2016) not in out           # complete years stay observed only


def test_same_complex_index():
    monthly = {f"C{i}": series_for({y: [100.0 + (y - 2021) * 10] * 12 for y in range(2015, 2024)}, 2015) for i in range(20)}
    idx = est.same_complex_index(monthly, 2015, [2015, 2022], base_years=(2021, 2022, 2023))
    assert round(idx[2022][0], 6) == 1.0 + 0.0  # 2022 is the base mean
    assert round(idx[2015][0], 6) == round(40 / 110, 6)


def test_sgis_trend_needs_three_consecutive_years():
    out = est.sgis_trend({"A": {2022: 100.0, 2023: 110.0, 2024: 120.0}, "B": {2021: 100.0, 2023: 100.0, 2024: 100.0}}, [2025])
    assert out[("A", 2025)]["value"] == 130
    assert ("B", 2025) not in out


def test_area_block_never_adds_into_observed():
    history = {"years": [2019, 2025], "area": {"grid_ids": ["g1"], "complex_codes": ["K1", "K2"], "admin_codes": ["A1"]},
               "complexes": [{"kapt_code": "K1", "approval_year": 2000}, {"kapt_code": "K2", "approval_year": 2001}],
               "building_energy": {"years": {2025: {"electricity_kwh": 900.0}}},
               "energy": {2019: {"electricity": {"by_complex": {}}}, 2025: {"electricity": {"by_complex": {"K1": 500.0}}}},
               "population": {2019: {"population": 10}, 2025: {"population": None}}}
    inputs = {"hub": {2019: {"g1": {"ELECTRICITY": {"value": 800.0, "method": "BACKCAST_SAME_BUILDING", "basis": {"parcels": 3, "same_index": 0.98}}}},
                      2025: {"g1": {"ELECTRICITY": {"value": 1000.0, "method": "FILL_SAME_ENTITY_NEIGHBOR_YEAR", "basis": {"filled_kwh": 60.0, "filled_months": 2}}}}},
              "kapt": {2025: {"K1": {"value": 999.0, "method": "X", "basis": {}}, "K2": {"value": 300.0, "method": "KAPT_NEIGHBOR_YEAR_CITY_INDEX", "basis": {}}}},
              "population": {2025: {"A1": {"value": 12.0, "method": "SGIS_LINEAR_TREND_3Y", "basis": {"years": [2022, 2023, 2024]}}}},
              "households": {}}
    block = est.area_block(history, inputs)
    assert block["buildings"][2019]["backcast"] is True
    assert block["buildings"][2025]["electricity_observed_kwh"] == 900.0
    assert block["buildings"][2025]["electricity_filled_kwh"] == 60.0
    a = block["apartments"][2025]
    assert a["observed_kwh"] == 500.0 and a["estimated_kwh"] == 300.0 and a["total_kwh"] == 800.0  # K1 observed wins over its estimate
    assert block["population"][2025]["population"] == 12
    facts = []
    history["estimates"] = block
    est.estimate_facts(history, lambda fid, text, *n, **k: facts.append((fid, text)))
    ids = [f for f, _ in facts]
    assert "estimate_buildings_backcast" in ids and "estimate_apartments" in ids and "estimate_population" in ids
    assert all("추정" in text for _, text in facts)


def test_benchmarks():
    assert primary_intensity(50.0, 40.0) == 50 * 2.75 + 40 * 1.1
    assert efficiency_band(59.9, True) == "1+++등급" and efficiency_band(150, True) == "2등급" and efficiency_band(800, False) == "등외"
    assert zeb_grade(20) == "5등급" and zeb_grade(19.9) == "등급 기준(20%) 미만" and zeb_grade(100) == "1등급"
    history = {"building_energy": {"years": {2025: {"kwh_per_m2": 60.0, "gas_kwh_per_m2": 50.0, "complete": True}}}}
    effort = {"available": True, "new_load_kwh": 100000.0, "added_floor_area_m2": 2000.0, "mix": {"pv_counted": True, "pv_kwh": 25000.0, "new_efficiency_pct": 0}}
    block = industry_block(history, effort, "52110")
    assert block["zone"] == "중부"
    assert block["buildings"]["primary_kwh_m2"] == round(60 * 2.75 + 50 * 1.1, 1)
    assert block["zeb"]["self_sufficiency_pct"] == 25.0 and block["zeb"]["grade"] == "5등급" and block["zeb"]["mandatory_scale"]
