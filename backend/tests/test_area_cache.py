import time

import app.area as area


def test_stale_inputs_are_served_while_a_background_reload_runs(monkeypatch):
    calls = []
    monkeypatch.setattr(area, 'prepare_inputs', lambda db, years: calls.append(tuple(years)) or {'years': list(years), 'n': len(calls)})
    reloads = []
    monkeypatch.setattr(area, '_refresh_in_background', lambda key: reloads.append(key))
    area._INPUTS.clear()
    first = area.cached_inputs(None, [2024, 2025])
    assert first['n'] == 1 and calls == [(2024, 2025)]
    assert area.cached_inputs(None, [2024, 2025]) is first  # fresh: no reload
    area._INPUTS[(2024, 2025)] = (time.monotonic() - area.INPUTS_TTL - 1, first)
    assert area.cached_inputs(None, [2024, 2025]) is first  # stale: answered at once
    assert reloads == [(2024, 2025)] and calls == [(2024, 2025)]
    area.cached_inputs(None, [2020, 2025]); area.cached_inputs(None, [2015, 2025])
    assert len(area._INPUTS) == 2  # bounded
    area._INPUTS.clear()
