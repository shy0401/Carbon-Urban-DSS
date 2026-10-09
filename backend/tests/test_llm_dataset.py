import json

from app import llm_dataset
from app.area_report import AREA_SYSTEM, verify_narrative
from app.llm_dataset import build_dataset, evaluate, reference_summary

FACTS = [
    {"id": "scope", "text": "분석 대상은 덕진구 송천1동 (행정동)이고 기간은 2015~2025년입니다. 격자 19개와 공동주택 단지 38개가 포함됩니다.", "numbers": [2015, 2025, 19, 38]},
    {"id": "coverage", "text": "12개월이 모두 관측된 전력 자료가 있는 연도가 없어 연간 에너지와 탄소를 계산하지 않았습니다.", "numbers": []},
    {"id": "event", "text": "2019년에 단지 5개(3,345세대)가 사용승인되었습니다.", "numbers": [2019, 5, 3345]},
    {"id": "estimated_change", "text": "관측이 부족해 연면적으로 추정하면, 이 개발로 단지 연면적이 527,251m²(+28.1%) 늘어 연간 전력 부하가 약 16,328,408 kWh 늘어난 것으로 추정됩니다(추정값).", "numbers": [527251, 28.1, 16328408]},
    {"id": "effort_target", "text": "2025년 대비 40% 감축을 목표로 하면 계획 반영 후 연간 17,401,119 kgCO2eq를 줄여야 합니다.", "numbers": [2025, 40, 17401119]},
    {"id": "effort_all", "text": "기존 건물까지 함께 줄이면 지역 전체 전력 소비를 41.7% 줄여야 합니다.", "numbers": [41.7]},
    {"id": "rules", "text": "관측이 없는 연도는 0이 아니라 자료 없음으로 두었고, 행정동 통계는 격자에 배분하지 않았습니다.", "numbers": [0]},
]


def test_reference_summary_uses_only_engine_sentences_and_passes_the_app_verifier():
    summary = reference_summary(FACTS, seed="x")
    assert summary and summary.startswith("분석 대상은")
    assert verify_narrative(summary, FACTS) == []
    assert "41.7%" in summary and len(summary) <= llm_dataset.MAX_SUMMARY
    # the rules sentence is context for the reader of the facts, not part of the summary
    assert "배분하지 않았습니다" not in summary


def test_reference_summary_needs_at_least_two_sentences():
    assert reference_summary(FACTS[:1]) is None


def _fake_engine(monkeypatch):
    inputs = {"admin": [{"properties": {"adm_code": "1"}}, {"properties": {"adm_code": "2"}}, {"properties": {"adm_code": "3"}}],
              "zoning": {"g": {"dominant_zone": "COMMERCIAL"}, "h": {"dominant_zone": "UNKNOWN"}},
              "complexes": {"A": {"kapt_code": "A", "lon": 127.1, "lat": 35.8}}, "energy": [], "years": [2024, 2025],
              "building_energy": {2025: {"cell_1_1": {}, "cell_2_2": {}}}}
    monkeypatch.setattr(llm_dataset, "prepare_inputs", lambda db, years, region=None: dict(inputs, region={"code": region or "52110"}))
    calls = []

    def analyze(db, spec, f, t, event, window, plan, target, pv, *, inputs, effort_basis="apartments", region=None):
        calls.append(dict(spec, basis=effort_basis, region=region))
        facts = [dict(FACTS[0], text=FACTS[0]["text"].replace("덕진구 송천1동 (행정동)", json.dumps(spec, ensure_ascii=False))), FACTS[4] | {"text": FACTS[4]["text"].replace("40%", f"{target:.0f}%"), "numbers": [2025, target, 17401119]}, FACTS[5]]
        return {"facts": facts}
    monkeypatch.setattr(llm_dataset, "analyze", analyze)
    return calls


def test_build_dataset_writes_verified_chat_examples_split_by_area(tmp_path, monkeypatch):
    calls = _fake_engine(monkeypatch)
    manifest = build_dataset(None, 2024, 2025, out_dir=tmp_path, per_area=3, log=lambda m: None)
    assert {c["type"] for c in calls} == {"admin", "zone", "circle", "grid"}
    assert {c["basis"] for c in calls} == {"apartments", "buildings"}
    assert all(c.get("category") != "UNKNOWN" for c in calls)
    train = [json.loads(l) for l in (tmp_path / "train.jsonl").read_text(encoding="utf-8").splitlines()]
    evalrows = [json.loads(l) for l in (tmp_path / "eval.jsonl").read_text(encoding="utf-8").splitlines()]
    assert manifest["train"] == len(train) and manifest["eval"] == len(evalrows)
    assert manifest["stats"]["dropped_unverified"] == 0
    row = (train or evalrows)[0]
    assert [m["role"] for m in row["messages"]] == ["system", "user", "assistant"]
    assert row["messages"][0]["content"] == AREA_SYSTEM
    assert "summary" in json.loads(row["messages"][2]["content"])
    assert all("facts" in r for r in evalrows) and all("facts" not in r for r in train)
    # no area appears in both splits
    area = lambda r: json.loads(r["messages"][1]["content"])[0]["text"].split("이고")[0]  # noqa: E731
    assert not ({area(r) for r in train} & {area(r) for r in evalrows})


def test_evaluate_counts_pass_rejected_and_error_without_publishing_bad_numbers(tmp_path):
    path = tmp_path / "eval.jsonl"
    path.write_text("\n".join(json.dumps({"id": str(i), "facts": FACTS}) for i in range(3)), encoding="utf-8")
    answers = iter([reference_summary(FACTS), "2019년에 전력이 12.5% 감소했습니다.", None])

    def generate(facts, model):
        text = next(answers)
        if text is None:
            raise ConnectionError("down")
        return text

    report = evaluate(path, model="test-model", generate=generate, log=lambda m: None)
    assert (report["pass"], report["rejected"], report["error"]) == (1, 1, 1)
    assert report["pass_rate"] == 0.5
    assert report["violation_kinds"] == {"근거에 없는 숫자": 1}
    saved = json.loads(open(report["saved"], encoding="utf-8").read())
    assert saved["results"][1]["outcome"] == "rejected"


def test_evaluate_limit_spreads_over_the_file(tmp_path):
    """A multi-region eval file lists the regions one after another: a limited run samples all of them."""
    path = tmp_path / "eval.jsonl"
    path.write_text("\n".join(json.dumps({"id": str(i), "facts": FACTS}) for i in range(10)), encoding="utf-8")
    report = evaluate(path, model="m", limit=4, generate=lambda facts, model: reference_summary(FACTS), log=lambda m: None)
    saved = json.loads(open(report["saved"], encoding="utf-8").read())
    assert [r["id"] for r in saved["results"]] == ["0", "2", "5", "7"]


def test_reference_summary_states_the_building_basis_and_does_not_chain_an_estimate_as_a_result():
    facts = FACTS[:3] + [
        {"id": "building_energy", "text": "건축HUB가 계측하는 구역 안 건물 전체의 2025년 전력은 38,404,995 kWh입니다.", "numbers": [2025, 38404995]},
        FACTS[3],
        {"id": "effort_basis", "text": "감축 노력은 구역 건물 전체(건축HUB 계측 지번, 상가·업무 포함) 기준입니다: 2025년 전력 38,404,995 kWh, 원단위 69.30 kWh/m²·년.", "numbers": [2025, 38404995, 69.3]},
        FACTS[4], FACTS[5]]
    for seed in ("a", "b", "c", "d"):
        summary = reference_summary(facts, seed=seed)
        assert "그 결과" not in summary  # before/after is a difference, not a measured cause
        assert summary.index("건물 전체") < summary.index("2019년에") and "감축 노력은 구역 건물 전체" in summary
        assert summary.index("감축 노력은") < summary.index("40% 감축을")
        assert verify_narrative(summary, facts) == []


def test_build_dataset_takes_areas_from_several_regions_with_fewer_samples_outside_the_first(tmp_path, monkeypatch):
    calls = _fake_engine(monkeypatch)
    manifest = build_dataset(None, 2024, 2025, out_dir=tmp_path, per_area=3, per_area_other=1, regions=["52110", "52710"], log=lambda m: None)
    first = [c for c in calls if c["region"] == "52110"]
    other = [c for c in calls if c["region"] == "52710"]
    assert first and other and len(other) < len(first)
    assert manifest["regions"] == ["52110", "52710"] and set(manifest["coverage"]) == {"52110", "52710"}
    assert manifest["coverage"]["52710"]["areas"] == len(other)  # one analysis per area outside the first region
