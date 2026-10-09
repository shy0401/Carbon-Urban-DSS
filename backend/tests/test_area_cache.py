import time

import app.area as area


def test_stale_inputs_are_served_while_a_background_reload_runs(monkeypatch):
    calls = []
    monkeypatch.setattr(area, 'prepare_inputs', lambda db, years, region=None: calls.append((region, *years)) or {'years': list(years), 'n': len(calls)})
    reloads = []
    monkeypatch.setattr(area, '_refresh_in_background', lambda key: reloads.append(key))
    area._INPUTS.clear()
    first = area.cached_inputs(None, [2024, 2025])
    assert first['n'] == 1 and calls == [(None, 2024, 2025)]
    assert area.cached_inputs(None, [2024, 2025]) is first  # fresh: no reload
    key = ('52110', 2024, 2025)  # the original region is the default key
    assert key in area._INPUTS
    area._INPUTS[key] = (time.monotonic() - area.INPUTS_TTL - 1, first)
    assert area.cached_inputs(None, [2024, 2025]) is first  # stale: answered at once
    assert reloads == [key] and calls == [(None, 2024, 2025)]
    area.cached_inputs(None, [2020, 2025]); area.cached_inputs(None, [2015, 2025]); area.cached_inputs(None, [2015, 2025], '41110')
    assert len(area._INPUTS) == 3  # bounded
    assert ('41110', 2015, 2025) in area._INPUTS  # another region has its own entry
    area._INPUTS.clear()


def test_a_narrower_year_range_is_cut_from_a_cached_wider_one(monkeypatch):
    rows = [{'use_ym': f'{y}{m:02d}', 'energy_type': 'ELECTRICITY', 'usage_kwh': 1.0, 'grid_id': 'g', 'kapt_code': 'A', 'parcel': 'kapt:A', 'source': 'KAPT'}
            for y in range(2015, 2026) for m in range(1, 13)]
    wide = {'years': list(range(2015, 2026)), 'energy': rows, 'weather': [{'use_ym': f'{y}01', 'hdd': 1, 'cdd': 1} for y in range(2015, 2026)],
            'complexes': {}, 'building_energy': {2020: {'g': {}}, 2024: {'g': {}}}, 'building_energy_complete': {2020: True, 2024: True},
            'solar': {'year': 2025}, 'region': {'code': '52110'}}
    loads = []
    monkeypatch.setattr(area, 'prepare_inputs', lambda db, years, region=None: loads.append(years) or dict(wide, years=list(years)))
    area._INPUTS.clear()
    area.cached_inputs(None, list(range(2015, 2026)))
    part = area.cached_inputs(None, list(range(2021, 2026)))
    assert loads == [list(range(2015, 2026))]  # no second load
    assert part['years'] == list(range(2021, 2026)) and {r['use_ym'][:4] for r in part['energy']} == {str(y) for y in range(2021, 2026)}
    assert [w['use_ym'] for w in part['weather']] == [f'{y}01' for y in range(2021, 2026)]
    assert set(part['building_energy']) == {2024} and set(part['building_energy_complete']) == {2024}
    assert part['solar'] == {'year': 2025}  # same last year: the wide range's yield
    assert ('52110', *range(2021, 2026)) in area._INPUTS
    area._INPUTS.clear()
