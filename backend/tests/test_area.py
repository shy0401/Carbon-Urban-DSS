import pytest

from app.area import (
    area_facts, before_after, build_history, city_intensity, effort, haversine_m,
    point_in_geometry, resolve_area,
)


def square(x, y, d=0.005):
    return {'type': 'Polygon', 'coordinates': [[[x, y], [x + d, y], [x + d, y + d], [x, y + d], [x, y]]]}


GRIDS = [{'id': 'g1', 'geometry': square(127.100, 35.800)}, {'id': 'g2', 'geometry': square(127.105, 35.800)}, {'id': 'g3', 'geometry': square(127.200, 35.900)}]
ADMIN = [{'type': 'Feature', 'geometry': square(127.099, 35.799, 0.012), 'properties': {'adm_code': '35012650', 'adm_name': '전북특별자치도 전주시 덕진구 송천1동'}},
         {'type': 'Feature', 'geometry': square(127.195, 35.895, 0.02), 'properties': {'adm_code': '35011999', 'adm_name': '전북특별자치도 전주시 완산구 먼동'}}]
COMPLEXES = {
    'OLD': {'kapt_code': 'OLD', 'name': '기존단지', 'approval_year': 2010, 'approval_date': '2010-05-01', 'households': 500, 'gfa': 50000.0, 'floor_area_ok': True, 'lon': 127.1025, 'lat': 35.8025, 'grid_id': 'g1'},
    'NEW': {'kapt_code': 'NEW', 'name': '신규단지', 'approval_year': 2020, 'approval_date': '2020-06-30', 'households': 300, 'gfa': 30000.0, 'floor_area_ok': True, 'lon': 127.1075, 'lat': 35.8025, 'grid_id': 'g2'},
    'FAR': {'kapt_code': 'FAR', 'name': '먼단지', 'approval_year': 2019, 'approval_date': '2019-01-01', 'households': 100, 'gfa': 99999999.0, 'floor_area_ok': False, 'lon': 127.2025, 'lat': 35.9025, 'grid_id': 'g3'},
}
POINTS = [{'kapt_code': c['kapt_code'], 'lon': c['lon'], 'lat': c['lat'], 'grid_id': c['grid_id']} for c in COMPLEXES.values()]
ZONING = {'g1': {'dominant_zone': 'RESIDENTIAL'}, 'g2': {'dominant_zone': 'RESIDENTIAL'}, 'g3': {'dominant_zone': 'COMMERCIAL'}}
YEARS = list(range(2017, 2024))


def energy_rows():
    rows = []
    for year in range(2018, 2023):
        for month in range(1, 13):
            rows.append({'use_ym': f'{year}{month:02d}', 'energy_type': 'ELECTRICITY', 'usage_kwh': 100.0, 'grid_id': 'g1', 'kapt_code': 'OLD', 'parcel': 'p-old'})
    for year in (2020, 2021, 2022):
        for month in range(7 if year == 2020 else 1, 13):
            rows.append({'use_ym': f'{year}{month:02d}', 'energy_type': 'ELECTRICITY', 'usage_kwh': 50.0, 'grid_id': 'g2', 'kapt_code': 'NEW', 'parcel': 'p-new'})
    return rows


def inputs():
    rows = energy_rows()
    return {'complexes': COMPLEXES, 'energy': rows, 'weather': [], 'population': [
        {'adm_code': '35012650', 'adm_name': '전북특별자치도 전주시 덕진구 송천1동', 'reference_year': 2019, 'value': 1000},
        {'adm_code': '35012650', 'adm_name': '전북특별자치도 전주시 덕진구 송천1동', 'reference_year': 2021, 'value': 1500},
        {'adm_code': '35012', 'adm_name': '덕진구', 'reference_year': 2021, 'value': 999999},
    ], 'households': [], 'factor': {'electricity': 0.5}, 'city_intensity': city_intensity(rows, COMPLEXES, YEARS)}


def test_geometry_helpers():
    assert point_in_geometry(127.1025, 35.8025, square(127.1, 35.8))
    assert not point_in_geometry(127.2, 35.8025, square(127.1, 35.8))
    assert haversine_m(127.0, 35.0, 127.0, 35.01) == pytest.approx(1112, rel=0.01)


def test_every_area_type_resolves_members():
    admin = resolve_area({'type': 'admin', 'code': '35012650'}, GRIDS, POINTS, ADMIN, ZONING)
    assert admin['grid_ids'] == ['g1', 'g2'] and admin['complex_codes'] == ['NEW', 'OLD']
    assert admin['label'] == '덕진구 송천1동 (행정동)' and admin['admin_exact']
    circle = resolve_area({'type': 'circle', 'lon': 127.1025, 'lat': 35.8025, 'radius_m': 200}, GRIDS, POINTS, ADMIN, ZONING)
    assert circle['complex_codes'] == ['OLD'] and circle['admin_codes'] == ['35012650']
    zone = resolve_area({'type': 'zone', 'category': 'COMMERCIAL'}, GRIDS, POINTS, ADMIN, ZONING)
    assert zone['grid_ids'] == ['g3'] and zone['complex_codes'] == ['FAR']
    grid = resolve_area({'type': 'grid', 'grid_id': 'g2'}, GRIDS, POINTS, ADMIN, ZONING)
    assert grid['complex_codes'] == ['NEW']
    with pytest.raises(ValueError):
        resolve_area({'type': 'circle', 'lon': 127.1, 'lat': 35.8, 'radius_m': 50}, GRIDS, POINTS, ADMIN, ZONING)


def test_annual_values_use_only_complete_parcels_and_never_fill_missing_years():
    area = resolve_area({'type': 'admin', 'code': '35012650'}, GRIDS, POINTS, ADMIN, ZONING)
    history = build_history(area, YEARS, inputs())
    energy = history['energy']
    assert energy[2017]['electricity']['kwh'] is None  # no observation: missing, not 0
    assert energy[2020]['electricity']['kwh'] == 1200.0  # NEW has 6 months only → excluded
    assert energy[2020]['electricity']['partial_parcels'] == 1
    assert energy[2021]['electricity']['by_cohort'] == {'2010': 1200.0, '2020': 600.0}
    assert energy[2021]['electricity']['intensity_kwh_per_m2'] == pytest.approx(1800 / 80000, abs=1e-3)
    assert energy[2021]['electricity_carbon_kgco2eq'] == 900.0
    assert history['population'][2021]['population'] == 1500  # 행정동 row only, 구 합계 excluded
    assert history['population'][2020]['population'] is None
    assert history['stock'][2019]['gfa_m2'] == 50000.0 and history['stock'][2020]['gfa_m2'] == 80000.0


def test_before_after_separates_existing_buildings_from_the_new_development():
    area = resolve_area({'type': 'admin', 'code': '35012650'}, GRIDS, POINTS, ADMIN, ZONING)
    history = build_history(area, YEARS, inputs())
    result = before_after(history, 2020, 3)
    m = result['metrics']['electricity']
    assert result['before_years'] == [2017, 2018, 2019] and result['after_years'] == [2021, 2022, 2023]
    assert m['before_total_kwh'] == 1200.0 and m['after_total_kwh'] == 1800.0
    assert m['total_change_pct'] == 50.0
    assert m['existing_change_pct'] == 0.0
    assert m['new_development_kwh'] == 600.0 and m['new_share_pct'] == pytest.approx(33.3, abs=0.1)
    est = result['metrics']['estimated']
    assert est['added_gfa_m2'] == 30000.0 and est['event_change_pct'] == 60.0


def test_effort_is_the_exact_gap_to_the_target():
    area = resolve_area({'type': 'admin', 'code': '35012650'}, GRIDS, POINTS, ADMIN, ZONING)
    history = build_history(area, YEARS, inputs())
    result = effort(history, {'added_floor_area_m2': 40000}, 40)
    intensity = 1800 / 80000
    base_c = 1800 * 0.5
    bau_c = (1800 + intensity * 40000) * 0.5
    need = bau_c - base_c * 0.6
    assert result['baseline_mode'] == 'OBSERVED' and result['baseline_year'] == 2022
    assert result['required_reduction_kgco2eq'] == pytest.approx(need, abs=0.1)
    assert result['options']['all_buildings_efficiency_pct'] == pytest.approx(need / bau_c * 100, abs=0.1)
    assert result['options']['offset_kwh_per_year'] == pytest.approx(need / 0.5, abs=0.1)
    assert result['options']['pv_capacity_kw'] is None  # no yield assumption → no kW
    with pytest.raises(ValueError):
        effort(history, {}, 120)


def test_effort_estimates_the_baseline_when_the_area_has_no_observation():
    area = resolve_area({'type': 'zone', 'category': 'COMMERCIAL'}, GRIDS, POINTS, ADMIN, ZONING)
    history = build_history(area, YEARS, inputs())
    result = effort(history, {'added_floor_area_m2': 1000}, 20)
    # FAR's published floor area is implausible → no plausible stock → no estimate.
    assert result['available'] is False


def test_facts_carry_their_numbers_for_verification():
    area = resolve_area({'type': 'admin', 'code': '35012650'}, GRIDS, POINTS, ADMIN, ZONING)
    history = build_history(area, YEARS, inputs())
    comparison = before_after(history, 2020, 3)
    facts = area_facts(history, comparison, effort(history, {'added_floor_area_m2': 40000}, 40))
    change = next(f for f in facts if f['id'] == 'change')
    assert change['numbers'] == [50.0] and '+50.0%' in change['text']
    assert all(isinstance(n, (int, float)) for f in facts for n in f['numbers'])
