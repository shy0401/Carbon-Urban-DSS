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
