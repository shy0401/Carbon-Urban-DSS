from app.area_report import summarize_area, verify_narrative

FACTS = [
    {'id': 'latest_energy', 'text': '2025년 관측 전력은 5,309,649 kWh(12개월 관측 지번 3곳)입니다.', 'numbers': [2025, 5309649.0, 3]},
    {'id': 'change', 'text': '지역 전력은 +12.5% 변했습니다.', 'numbers': [12.5]},
]


def test_narrative_with_engine_numbers_passes():
    text = '2025년 이 지역의 관측 전력은 5,309,649 kWh였고, 지번 3곳에서 12개월이 모두 관측되었습니다. 개발 뒤 전력은 12.5% 증가했습니다.'
    assert verify_narrative(text, FACTS) == []


def test_invented_number_wrong_direction_and_overclaim_are_rejected():
    assert any('근거에 없는 숫자' in p for p in verify_narrative('전력은 5,400,000 kWh입니다.', FACTS))
    assert any('증가를 감소' in p for p in verify_narrative('전력은 12.5% 감소했습니다.', FACTS))
    assert any('단정' in p for p in verify_narrative('2025년에 넷제로 달성이 가능합니다.', FACTS))


def test_template_mode_uses_fact_text_verbatim():
    summary = summarize_area(FACTS, use_local=False)
    assert summary['mode'] == 'TEMPLATE'
    assert summary['paragraphs'] == [f['text'] for f in FACTS]


def test_report_uses_the_reduction_basis_the_user_chose(monkeypatch):
    """The area page sends effort_basis; the report must compute the effort on the same buildings."""
    import contextlib
    from app import area_report
    seen = {}

    def fake_analyze(db, spec, *args, **kwargs):
        seen.update(kwargs)
        area = {'label': '구역', 'geometry': None}
        return {'history': {'area': area, 'years': [2025]}, 'before_after': None, 'effort': None, 'facts': FACTS, 'region': None}

    monkeypatch.setattr(area_report, 'analyze', fake_analyze)
    monkeypatch.setattr(area_report, 'Session', lambda: contextlib.nullcontext(None))
    request = area_report.AreaReportInput(area={'type': 'grid', 'grid_id': 'cell_1_1'}, from_year=2024, to_year=2025, effort_basis='buildings')
    snapshot = area_report._snapshot(request)
    assert seen['effort_basis'] == 'buildings'
    assert snapshot['request']['effort_basis'] == 'buildings'


def test_direction_words_are_checked_for_every_signed_change():
    facts = FACTS + [{'id': 'building_energy_trend', 'text': '건물 전체 전력은 2021년에서 2025년으로 +10.0% 변했습니다.', 'numbers': [2021, 2025, 10.0], 'signed_pct': 10.0}]
    assert '증가를 감소로 서술' in verify_narrative('건물 전체 전력은 2021년부터 2025년까지 10.0% 감소했습니다.', facts)
    assert verify_narrative('건물 전체 전력은 2021년부터 2025년까지 10.0% 증가했습니다.', facts) == []


def test_effort_amount_without_its_basis_is_rejected():
    facts = [
        {'id': 'latest_energy', 'text': '2025년 관측 전력은 84,145,683 kWh입니다.', 'numbers': [2025, 84145683.0]},
        {'id': 'effort_basis', 'text': '감축 노력은 구역 건물 전체 기준입니다: 2025년 전력 160,874,572 kWh, 원단위 66.26 kWh/m²·년.', 'numbers': [2025, 160874572.0, 66.26]},
        {'id': 'effort_target', 'text': '2025년 대비 40% 감축을 목표로 하면 계획 반영 후 연간 33,145,897 kgCO2eq를 줄여야 합니다.', 'numbers': [2025, 40, 33145897.0]},
    ]
    misleading = '2025년 관측 전력은 84,145,683 kWh입니다. 40% 감축을 목표로 하면 연간 33,145,897 kgCO2eq를 줄여야 합니다.'
    assert '감축 기준 설명 없이 감축량 서술' in verify_narrative(misleading, facts)
    stated = '감축 노력은 구역 건물 전체 기준입니다: 2025년 전력 160,874,572 kWh. 40% 감축을 목표로 하면 연간 33,145,897 kgCO2eq를 줄여야 합니다.'
    assert verify_narrative(stated, facts) == []
    assert verify_narrative('2025년 관측 전력은 84,145,683 kWh입니다.', facts) == []  # no effort quoted → basis not required


def test_model_prompt_carries_only_summary_facts_but_checker_keeps_them_all():
    import json
    from app.area_report import NARRATIVE_FACTS, facts_prompt
    from app.llm_dataset import SLOTS
    facts = [
        {'id': 'scope', 'text': '분석 대상은 격자 A입니다.', 'numbers': []},
        {'id': 'sgis_grid', 'text': 'SGIS 2024년 1km 격자 기준 인구 12,345명입니다.', 'numbers': [2024, 12345]},
        {'id': 'building_energy_gap', 'text': '2020년 건축HUB 값은 쓰되 비교하지 않습니다.', 'numbers': [2020]},
        {'id': 'gap_7', 'text': '개발 전 관측 연도가 없습니다.', 'numbers': []},
        {'id': 'rules', 'text': '관측이 없는 연도는 0이 아니라 자료 없음으로 두었습니다.', 'numbers': [0]},
        {'id': 'latest_energy', 'text': '2025년 관측 전력은 5,309,649 kWh입니다.', 'numbers': [2025, 5309649.0]},
    ]
    assert [f['id'] for f in json.loads(facts_prompt(facts))] == ['scope', 'latest_energy']
    assert verify_narrative('구역 인구는 12,345명이고 2025년 관측 전력은 5,309,649 kWh입니다.', facts) == []
    assert {i for ids, _ in SLOTS for i in ids} <= NARRATIVE_FACTS  # every training sentence is visible to the model


def test_output_budget_fits_the_longest_training_summary(monkeypatch):
    import json
    from app import area_report
    from app.llm_dataset import MAX_SUMMARY
    sent = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"done": True, "response": json.dumps({"summary": "요약"})}

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, json=None):
            sent.update(json)
            return FakeResponse()

    monkeypatch.setattr(area_report.httpx, "Client", FakeClient)
    assert area_report.local_narrative([{"id": "scope", "text": "분석 대상은 격자 A입니다.", "numbers": []}], model="m") == "요약"
    # even at one token per character (digits are single tokens) the longest target plus the JSON wrapper fits
    assert sent["options"]["num_predict"] >= MAX_SUMMARY + 20
    assert sent["options"]["num_ctx"] >= sent["options"]["num_predict"] + 1500
