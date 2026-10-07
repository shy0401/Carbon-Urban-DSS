"""Fixed simulation cases and the cross-PC reproduction check (app/cases.py, `python -m app.cli verify-cases`)."""
import json

from app import cases


def test_cases_file_is_valid_and_every_input_is_what_the_screen_sends():
    from app.area import AnalyzeInput
    from app.main import OptimizationInput, ScenarioInput
    doc = cases.load()
    ids = [c["id"] for c in doc["cases"]]
    assert len(ids) == len(set(ids))
    for spec in doc["cases"]:
        assert spec["kind"] in cases.RUNNERS, spec["id"]
        assert spec.get("title") and spec.get("region"), spec["id"]
        i = spec["input"]
        if spec["kind"] in ("area", "area_report"):
            AnalyzeInput(**i)
            assert i["region"] == spec["region"]
        elif spec["kind"] == "scenario":
            assert ScenarioInput(**i).region == spec["region"]
        elif spec["kind"] == "optimize":
            OptimizationInput(**i)
        elif spec["kind"] == "grid_report":
            assert all(ScenarioInput(**p).grid_id == i["grid_id"] for p in i["scenarios"])
    # each region with cases also has its data fingerprint, so a data difference is told apart from a calculation difference
    regions = {c["region"] for c in doc["cases"] if c["kind"] != "dataset"}
    assert regions <= {c["input"]["region"] for c in doc["cases"] if c["kind"] == "dataset"}


def test_flatten_and_tolerance():
    flat = cases.flatten({"a": 1, "b": {"c": 2.5, "d": {"e": None}}, "z": [1, 2]})
    assert flat == {"a": 1, "b.c": 2.5, "b.d.e": None, "z": [1, 2]}
    assert cases.same(1000.0, 1000.0005)                 # within 1e-6 relative
    assert not cases.same(1000.0, 1000.1)
    assert cases.same(10.0, 10.4, tol=0.5)                # a case may widen one value
    assert not cases.same(None, 0.0) and not cases.same(0.0, None)   # 자료 없음 is never 0
    assert cases.same([["제3종일반주거지역", 99.85]], [["제3종일반주거지역", 99.85]])
    assert not cases.same(True, 1)


def _spec(values, facts):
    return {"id": "X", "kind": "area", "expected": {"values": values, "facts": facts, "facts_sha256": cases.facts_hash(facts)}}


def test_compare_reports_value_and_sentence_differences():
    facts = ["2025년 전력 1,000 kWh입니다."]
    spec = _spec({"effort.pv_capacity_kw": 120.0, "label": "송천1동 (행정동)"}, facts)
    same = cases.compare(spec, {"values": {"effort.pv_capacity_kw": 120.0, "label": "송천1동 (행정동)"}, "facts": facts, "facts_sha256": cases.facts_hash(facts)})
    assert same["status"] == "MATCH" and same["checked"] == 2
    other = ["2025년 전력 1,001 kWh입니다."]
    diff = cases.compare(spec, {"values": {"effort.pv_capacity_kw": 125.0, "label": "송천1동 (행정동)", "new": 1}, "facts": other,
                                "facts_sha256": cases.facts_hash(other)})
    assert diff["status"] == "DIFF"
    assert {d["key"] for d in diff["diffs"]} == {"effort.pv_capacity_kw", "new"}
    assert diff["diffs"][0]["label"] == "필요 태양광 kW"
    assert diff["text_diffs"] == [{"expected": facts[0], "actual": other[0]}]
    assert cases.compare({"id": "Y"}, {"values": {}, "facts": [], "facts_sha256": ""})["status"] == "NOT_RECORDED"
    assert cases.compare(spec, {"error": "ValueError: x"})["status"] == "ERROR"


def test_one_failing_case_does_not_stop_the_run_and_nothing_is_committed(monkeypatch):
    class FakeDb:
        commits = rollbacks = 0

        def commit(self):
            FakeDb.commits += 1

        def rollback(self):
            FakeDb.rollbacks += 1

    def boom(db, spec):
        raise ValueError("행정동을 찾을 수 없습니다")

    def fine(db, spec):
        return {"far": 225.0}, ["근거"]

    monkeypatch.setattr(cases, "RUNNERS", {"area": boom, "scenario": fine})
    doc = {"recorded_on": "2026-10-08", "cases": [{"id": "A", "kind": "area", "title": "a", "input": {}}, {"id": "B", "kind": "scenario", "title": "b", "input": {}}]}
    lines = []
    recorded = cases.record(FakeDb(), doc, note="test", log=lines.append)
    assert "expected" not in recorded["cases"][0] and recorded["cases"][1]["expected"]["values"] == {"far": 225.0}
    assert recorded["data_note"] == "test" and "expected" not in doc["cases"][1]   # the input document is not changed
    report = cases.verify(FakeDb(), recorded, log=lines.append)
    assert report["counts"] == {"MATCH": 1, "DIFF": 0, "ERROR": 1, "NOT_RECORDED": 0} and not report["all_match"]
    assert FakeDb.commits == 0 and FakeDb.rollbacks >= 1
    assert any(line.startswith("[오류] A") for line in lines) and any(line.startswith("[일치] B") for line in lines)
    only = cases.verify(FakeDb(), recorded, only={"B"}, log=lines.append)
    assert only["all_match"] and only["counts"]["MATCH"] == 1
    json.dumps(report, default=str)


def test_scenario_case_uses_the_engine_without_saving(monkeypatch):
    import app.main as main
    seen = {}

    def compute(db, request):
        seen["request"] = request
        return {"grid_id": request.grid_id, "far": 225.0, "bcr": 15.0, "gross_floor_area": 90000.0, "annual": {"current": {"carbon_kg": 10.0}, "scenario": {"carbon_kg": 8.0}},
                "percent_change": {"carbon_kg": -20.0}, "monthly": [], "zoning_check": {"zones": [{"zone": "제3종일반주거지역", "share": 99.85}], "far_limit": 300.0},
                "legal_status": "조례 기본 상한 이내", "assumptions": ["가정 1"], "_region": "52110"}

    class FakeDb:
        def rollback(self):
            seen["rolled_back"] = True

    monkeypatch.setattr(main, "compute_scenario", compute)
    spec = {"id": "J06", "kind": "scenario", "input": {"site_area": 40000, "building_count": 10, "footprint_per_building": 600, "floors": 15,
                                                         "households": 1000, "population": 2500, "average_household_area": 84, "green_ratio": 0.3,
                                                         "grid_id": "cell_966500_1764500", "region": "52110"}}
    got = cases.run_one(FakeDb(), spec)
    assert seen["rolled_back"] and seen["request"].floors == 15
    assert got["values"]["far"] == 225.0 and got["values"]["zoning.dominant_zone"] == "제3종일반주거지역" and got["values"]["carbon_change_pct"] == -20.0
    assert got["facts"] == ["가정 1"]
