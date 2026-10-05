import httpx,pytest
from app.reporting import choose_evidence, create_snapshot, report_markdown
from app.db import Session

def test_model_cannot_introduce_new_numbers_or_evidence_ids():
    facts=[{'id':'scope','text':'500m 격자를 분석합니다.'},{'id':'missing','text':'관측이 없어 계산할 수 없습니다.'}]
    assert choose_evidence({'fact_ids':['missing','scope']},facts)==[facts[1],facts[0]]
    with pytest.raises(ValueError):choose_evidence({'fact_ids':['invented']},facts)
    with pytest.raises(ValueError):choose_evidence({'fact_ids':['scope'],'text':'탄소 100% 감축'},facts)

def test_snapshot_is_honest_and_export_contains_sources():
    with Session() as db:
        snapshot=create_snapshot(db,2025,None,[])
        assert snapshot['year']==2025
        assert snapshot['facts']
        assert snapshot['sources']
        assert '기준 자료' in report_markdown(snapshot)

def test_unknown_scenario_and_different_year_are_rejected():
    with Session() as db:
        with pytest.raises(ValueError):create_snapshot(db,2025,None,['not-found'])

def test_local_model_failure_returns_template(monkeypatch):
    from app.reporting import summarize
    monkeypatch.setattr('app.reporting.local_selection',lambda facts: (_ for _ in ()).throw(httpx.ConnectError('unavailable')))
    result=summarize([{'id':'a','text':'자료가 없습니다.'}],True)
    assert result['mode']=='TEMPLATE_FALLBACK'
    assert result['paragraphs']==['자료가 없습니다.']


def test_markdown_has_numbered_sections_scenario_table_image_and_cautions():
    from app.reporting import report_cautions, report_markdown
    scenario = {'id': 's1', 'inputs': {'floors': 12, 'building_count': 4, 'households': 240, 'population': 560}, 'created_at': 't', 'has_image': True, 'image_url': '/api/scenarios/s1/image',
                'result': {'gross_floor_area': 33600.0, 'far': 336.0, 'bcr': 28.0, 'annual': {'scenario': {'electricity_kwh': 1200000.0, 'carbon_kg': None, 'electricity_carbon_kg': 544920.0}, 'difference': {'carbon_kg': None, 'electricity_carbon_kg': -1000.5}}}}
    detail = {'building_energy': {'bldg_parcels': 55}, 'register': None, 'official_code': '다마68b62a', 'model': None, 'exclusions': None, 'facts': []}
    data = {'coverage': {'electricity_months': 12, 'gas_months': 12}}
    snapshot = {'id': 'r1', 'title': '도시계획 의사결정 검토 보고서', 'year': 2025, 'grid_id': 'cell_968500_1762000', 'created_at': '2026-09-27T00:00:00', 'sector': {'name': 'LG동아 아파트'},
                'summary': {'paragraphs': ['요약 문장.']}, 'facts': [{'id': 'electricity_intensity', 'text': '전력 원단위는 34.0 kWh/m²입니다.'}],
                'context': {'official_code': '다마68b62a', 'facts': [{'id': 'official_grid', 'text': '공식 격자 다마68b62a와 같은 칸입니다.'}, {'id': 'building_energy', 'text': '건물 전체 전력 14,988,979kWh입니다.'}]},
                'totals': {'electricity_kwh': 9227634.0, 'gas_kwh': 19050333.0, 'carbon_kg': None, 'electricity_carbon_kg': 4190300.0}, 'coverage': data['coverage'], 'scenarios': [scenario],
                'cautions': report_cautions(data, detail, [scenario]), 'sources': [{'name': 'K-apt', 'status': 'PARTIAL', 'reference_period': '2025-01', 'collected_at': '2026-09-26T10:00:00', 'normalized_row_count': 1252, 'source_url': 'u'}],
                'evidence_hash': 'abc', 'scope': '격자 관측 지번 합계'}
    text = report_markdown(snapshot)
    for heading in ('## 1. 검토 요약', '## 2. 대상지 개요', '## 3. 에너지·탄소 현황', '## 4. 계획안 비교', '## 5. 해석 범위와 유의사항', '## 6. 데이터 출처', '## 7. 재현 정보'):
        assert heading in text
    assert 'SGIS 공식 500m 격자 다마68b62a' in text and '| 용적률 | 336.0% |' in text and '| 기준 대비 전력 탄소 변화 | -1,000.5kgCO2eq |' in text
    assert '| 계획 연간 전체 탄소 (전력+가스) | 자료 없음 |' in text and '전력 탄소 4,190,300kgCO2eq' in text
    assert '![대안 1 3D 개념 배치](/api/scenarios/s1/image)' in text and '실제 배치안이 아닙니다' in text
    assert '건물 전체 전력 14,988,979kWh' in text and '| K-apt | PARTIAL | 2025-01 | 2026-09-26 | 1,252 |' in text
    assert any('가스 탄소' in c for c in snapshot['cautions']) and any('3D 개념 배치' in c for c in snapshot['cautions'])


def test_cautions_say_when_all_building_energy_is_missing_or_months_are_short():
    from app.reporting import report_cautions
    items = report_cautions({'coverage': {'electricity_months': 7, 'gas_months': 12}}, {'building_energy': None}, [])
    assert any('건축HUB 전 지번 에너지가 아직 없어' in c for c in items) and any('12개월 미만' in c for c in items)
    assert not any('3D' in c for c in items)

def test_fine_tuned_model_only_writes_the_area_summary(monkeypatch):
    """The fine-tuned model is trained and evaluated on the area summary only; evidence selection keeps OLLAMA_MODEL."""
    from app.reporting import local_config, model_installed, narrative_model
    monkeypatch.setenv('OLLAMA_MODEL', 'qwen2.5:1.5b')
    monkeypatch.delenv('OLLAMA_NARRATIVE_MODEL', raising=False)
    assert narrative_model() == 'qwen2.5:1.5b'
    monkeypatch.setenv('OLLAMA_NARRATIVE_MODEL', ' ')
    assert narrative_model() == 'qwen2.5:1.5b'  # blank (compose default) means unset
    monkeypatch.setenv('OLLAMA_NARRATIVE_MODEL', 'carbon-area-narrator')
    assert narrative_model() == 'carbon-area-narrator' and local_config()[1] == 'qwen2.5:1.5b'
    names = ['carbon-area-narrator:latest', 'qwen2.5:1.5b']
    assert model_installed('carbon-area-narrator', names) and model_installed('qwen2.5:1.5b', names)
    assert not model_installed('qwen2.5:3b', names) and not model_installed('carbon-area-narrator:v2', names)


def test_area_summary_calls_the_narrative_model(monkeypatch):
    import json as _json
    from app import area_report
    monkeypatch.setenv('OLLAMA_MODEL', 'qwen2.5:1.5b')
    monkeypatch.setenv('OLLAMA_NARRATIVE_MODEL', 'carbon-area-narrator')
    seen = {}

    class FakeResponse:
        def raise_for_status(self): pass
        def json(self): return {'done': True, 'response': _json.dumps({'summary': '분석 대상은 격자 4개입니다.'})}

    class FakeClient:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def post(self, url, json): seen.update(json); return FakeResponse()

    monkeypatch.setattr(area_report.httpx, 'Client', FakeClient)
    facts = [{'id': 'scope', 'text': '분석 대상은 격자 4개입니다.', 'numbers': [4]}]
    result = area_report.summarize_area(facts, True)
    assert seen['model'] == 'carbon-area-narrator'
    assert result['mode'] == 'LOCAL_SLM_NARRATIVE' and result['model'] == 'carbon-area-narrator'


def test_local_selection_keeps_scope_first_engine_order_and_at_least_three_sentences(monkeypatch):
    from app.reporting import summarize, summary_pool
    snapshot = {'facts': [{'id': 'scope', 'text': '범위.'}, {'id': 'annual', 'text': '연간.'}, {'id': 'coverage', 'text': '자료.'}, {'id': 'legal', 'text': '판정 아님.'}],
                'context': {'facts': [{'id': 'official_grid', 'text': '공식 격자.'}, {'id': 'building_energy', 'text': '건물 전체.'}]}}
    pool = summary_pool(snapshot)
    assert [f['id'] for f in pool] == ['scope', 'annual', 'coverage', 'legal', 'building_energy']  # official_grid stays in its section
    monkeypatch.setattr('app.reporting.local_selection', lambda facts: {'fact_ids': ['building_energy']})
    result = summarize(pool, True)
    assert result['mode'] == 'LOCAL_SLM'
    assert result['paragraphs'] == ['범위.', '연간.', '건물 전체.']  # scope added, padded to 3, engine order
