"""Regional PV yield from irradiation (docs/DATA_STANDARD.md 5.13)."""
from datetime import date, timedelta

import pytest

from app import solar
from app.area import area_facts, effort, pv_basis


def _days(year: int, mj: float, skip: int | None = None):
    d = date(year, 1, 1)
    out = []
    while d.year == year:
        if skip is None or d.timetuple().tm_yday != skip:
            out.append((d.isoformat(), mj))
        d += timedelta(days=1)
    return out


def test_daily_years_need_every_day_and_count_a_date_once():
    rows = _days(2025, 3.6) + [("2025-01-01", 99.0)]          # a re-collected page repeats a date
    assert solar.daily_years(rows) == {2025: 365.0}            # 365 days × 3.6 MJ = 365 kWh/m²
    assert solar.daily_years(_days(2024, 3.6, skip=100)) == {}  # one missing day → no annual value (never a partial sum)
    assert solar.daily_years([("2025-01-01", None)]) == {}


def test_monthly_years_need_twelve_complete_months():
    full = [(f"2025{m:02d}", 360.0) for m in range(1, 13)]
    assert solar.monthly_years(full) == {2025: 1200.0}
    assert solar.monthly_years(full[:11] + [("202512", None)]) == {}


def test_monthly_solar_keeps_only_complete_months():
    daily = {"time": [f"2025-02-{d:02d}" for d in range(1, 29)], "shortwave_radiation_sum": [10.0] * 28}
    assert solar.monthly_solar(daily, list(range(28))) == 280.0
    daily["shortwave_radiation_sum"][3] = None
    assert solar.monthly_solar(daily, list(range(28))) is None
    assert solar.monthly_solar({"time": daily["time"]}, list(range(28))) is None  # variable not requested


def test_choose_prefers_the_latest_year_and_an_observation_over_reanalysis():
    c = [{"year": 2024, "irradiation_kwh_m2": 1300.0, "source": "ASOS", "source_type": "OFFICIAL"},
         {"year": 2025, "irradiation_kwh_m2": 1350.0, "source": "ERA5", "source_type": "FALLBACK"},
         {"year": 2025, "irradiation_kwh_m2": 1320.0, "source": "ASOS", "source_type": "OFFICIAL"}]
    best = solar.choose(c)
    assert (best["year"], best["source"], best["yield_kwh_per_kw"]) == (2025, "ASOS", 1056.0)  # 1320 × 0.80
    assert solar.choose(c, up_to=2024)["year"] == 2024
    assert solar.choose([], None) is None


def _history(solar_estimate):
    return {"years": [2025], "energy": {2025: {"electricity": {"kwh": 1_000_000.0, "intensity_kwh_per_m2": 20.0, "intensity_area_m2": 50_000.0}}},
            "factor": {"electricity": 0.5}, "solar": solar_estimate, "stock": {2025: {"gfa_m2": 50_000.0}}}


def test_effort_uses_the_regional_estimate_unless_the_user_gives_a_yield():
    est = solar.estimate(2025, 1300.0, "ERA5-Land 일사량 (Open-Meteo, 재분석)", "FALLBACK")
    result = effort(_history(est), {"added_floor_area_m2": 10_000}, 40)
    need_kwh = result["required_reduction_kgco2eq"] / 0.5
    assert result["pv_yield"]["basis"] == "ESTIMATED" and result["pv_yield"]["kwh_per_kw"] == 1040.0
    assert result["options"]["pv_capacity_kw"] == pytest.approx(need_kwh / 1040.0, abs=0.1)
    assert any("지역 일사량 추정" in a for a in result["assumptions"])
    mine = effort(_history(est), {"added_floor_area_m2": 10_000}, 40, 1200)
    assert mine["pv_yield"]["basis"] == "USER" and mine["options"]["pv_capacity_kw"] == pytest.approx(need_kwh / 1200, abs=0.1)
    none = effort(_history(None), {"added_floor_area_m2": 10_000}, 40)
    assert none["pv_yield"] is None and none["options"]["pv_capacity_kw"] is None   # no irradiation → no kW, not a guess
    assert pv_basis(_history(None), None) is None


def test_pv_fact_states_that_the_capacity_is_an_estimate_and_carries_its_numbers():
    est = solar.estimate(2025, 1300.0, "ERA5-Land 일사량 (Open-Meteo, 재분석)", "FALLBACK")
    history = _history(est) | {"area": {"label": "격자 A", "grid_ids": ["g"], "complex_codes": []}, "coverage": {"energy_years": [2025]},
                               "events": {}, "register": {}, "building_energy": {}, "sgis_grid": {}}
    history["energy"][2025]["electricity"].update({"complete_parcels": 3})
    result = effort(history, {"added_floor_area_m2": 10_000}, 40)
    facts = {f["id"]: f for f in area_facts(history, None, result)}
    pv = facts["effort_pv"]
    assert "추정값" in pv["text"] and "1,300 kWh/m²" in pv["text"] and "1,040 kWh/kW·년" in pv["text"]
    assert 1040.0 in pv["numbers"] and result["options"]["pv_capacity_kw"] in pv["numbers"]


def test_store_months_writes_complete_months_and_null_for_gaps():
    class FakeDb:
        def __init__(self):
            self.rows = {}

        def get(self, model, key):
            return self.rows.get(key)

        def add(self, row):
            self.rows[(row.region_code, row.use_ym, row.provider)] = row

    days = [f"2025-01-{d:02d}" for d in range(1, 32)] + [f"2025-02-{d:02d}" for d in range(1, 29)]
    values = [10.0] * 31 + [12.0] * 27 + [None]
    db = FakeDb()
    assert solar.store_months(db, "36110", {"daily": {"time": days, "shortwave_radiation_sum": values}}, 36.5, 127.3) == 2
    jan, feb = db.rows[("36110", "202501", "Open-Meteo / ERA5-Land")], db.rows[("36110", "202502", "Open-Meteo / ERA5-Land")]
    assert (jan.irradiation_mj_m2, jan.days_observed, jan.expected_days) == (310.0, 31, 31)
    assert feb.irradiation_mj_m2 is None and feb.days_observed == 27   # a missing day: no month value, not a partial sum
    assert solar.store_months(db, "36110", {"daily": {"time": days}}, 36.5, 127.3) == 0
