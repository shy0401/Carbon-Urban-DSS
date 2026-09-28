"""Opening any 시·군·구 on the map: the basic steps from the national layers, once."""
from types import SimpleNamespace

from app import region_prepare
from app.regions import detail_level


class Db:
    def __init__(self, region):
        self.region = region

    def refresh(self, _obj):
        pass

    def get(self, _model, _code):
        return self.region

    def commit(self):
        pass

    def rollback(self):
        pass


def fresh_region():
    return SimpleNamespace(code="41820", name="경기도 가평군", grid_count=0, datasets={}, status="NOT_PREPARED", message=None)


def test_opening_builds_the_basic_map_once(monkeypatch):
    region = fresh_region()
    calls = []

    def fake_prepare(db, code, steps, log=print):
        calls.append(list(steps))
        region.grid_count = 3500
        region.datasets = {step: {"status": "DONE"} for step in steps}
        return {}

    monkeypatch.setattr(region_prepare, "create_region", lambda db, code: region)
    monkeypatch.setattr(region_prepare, "prepare_region", fake_prepare)
    opened = region_prepare.open_region(Db(region), "41820", log=lambda m: None)
    assert calls == [list(region_prepare.BASIC_STEPS)]
    assert opened.grid_count == 3500 and detail_level(opened) == "BASIC"
    assert "기본 지도" in opened.message
    region_prepare.open_region(Db(region), "41820", log=lambda m: None)
    assert len(calls) == 1


def test_a_failed_grid_step_is_tried_once_more(monkeypatch):
    region = fresh_region()
    calls = []

    def fake_prepare(db, code, steps, log=print):
        calls.append(list(steps))
        if len(calls) == 1:
            region.datasets = {"grid": {"status": "FAILED", "message": "duplicate key"}}
        else:
            region.grid_count = 10
            region.datasets = {"grid": {"status": "DONE"}}
        return {}

    monkeypatch.setattr(region_prepare, "create_region", lambda db, code: region)
    monkeypatch.setattr(region_prepare, "prepare_region", fake_prepare)
    region_prepare.open_region(Db(region), "41820", log=lambda m: None)
    assert calls[1] == ["grid"] and region.grid_count == 10


def test_detail_level_follows_the_regions_own_collection():
    assert detail_level(None) == "NONE"
    assert detail_level(SimpleNamespace(code="41820", grid_count=0, datasets={})) == "NONE"
    assert detail_level(SimpleNamespace(code="41820", grid_count=5, datasets={"grid": {"status": "DONE"}, "weather": {"status": "DONE"}})) == "BASIC"
    assert detail_level(SimpleNamespace(code="41820", grid_count=5, datasets={"buildings": {"status": "DONE"}})) == "DETAILED"
    assert detail_level(SimpleNamespace(code="41820", grid_count=5, datasets={"buildings": {"status": "FAILED"}})) == "BASIC"
    assert detail_level(SimpleNamespace(code="52110", grid_count=916, datasets={})) == "DETAILED"
