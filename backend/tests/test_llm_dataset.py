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
              "complexes": {"A": {"kapt_code": "A", "lon": 127.1, "lat": 35.8}}, "energy": [], "years": [2024, 2025]}
    monkeypatch.setattr(llm_dataset, "prepare_inputs", lambda db, years: inputs)
    calls = []

    def analyze(db, spec, f, t, event, window, plan, target, pv, *, inputs):
        calls.append(spec)
        facts = [dict(FACTS[0], text=FACTS[0]["text"].replace("덕진구 송천1동 (행정동)", json.dumps(spec, ensure_ascii=False))), FACTS[4] | {"text": FACTS[4]["text"].replace("40%", f"{target:.0f}%"), "numbers": [2025, target, 17401119]}, FACTS[5]]
        return {"facts": facts}
    monkeypatch.setattr(llm_dataset, "analyze", analyze)
    return calls


def test_build_dataset_writes_verified_chat_examples_split_by_area(tmp_path, monkeypatch):
    calls = _fake_engine(monkeypatch)
    manifest = build_dataset(None, 2024, 2025, out_dir=tmp_path, per_area=3, log=lambda m: None)
    assert {c["type"] for c in calls} == {"admin", "zone", "circle"}
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
