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
        assert snapshot['kind']=='STATUS' and snapshot['place'] and 'cell_' not in snapshot['place']
        assert not any('cell_' in f['text'] for f in snapshot['facts'])   # the place, never the cell id, names the site
        assert snapshot['evidence_hash'] and 'SHA' not in report_markdown(snapshot)   # kept in the stored record, not printed
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


def test_markdown_names_the_place_shows_the_plan_and_its_savings_and_hides_cell_ids_and_hashes():
    """10/14: the report a developer or a 지자체 reader prints — plan first, no cell id, no evidence hash in the text."""
    from app.reporting import report_cautions, report_markdown
    scenario = {'id': 's1', 'label': '계획안 A', 'inputs': {'site_area': 10000, 'floors': 12, 'building_count': 4, 'footprint_per_building': 700, 'households': 240, 'population': 560, 'efficiency_factor': 0.8, 'pv_ratio': 0.15, 'green_ratio': 0.25},
                'created_at': 't', 'has_image': True, 'image_url': '/api/scenarios/s1/image',
                'result': {'gross_floor_area': 33600.0, 'total_footprint': 2800.0, 'far': 336.0, 'bcr': 28.0, 'carbon_per_person': 1000.5, 'carbon_per_household': 2334.5,
                           'annual': {'scenario': {'electricity_kwh': 1200000.0, 'gas_kwh': 800000.0, 'carbon_kg': 560280.0, 'electricity_carbon_kg': 544920.0},
                                      'reference': {'electricity_kwh': 1764705.9, 'gas_kwh': 1000000.0, 'carbon_kg': 760000.0, 'electricity_carbon_kg': 700000.0},
                                      'difference': {'carbon_kg': None, 'electricity_carbon_kg': -1000.5}},
                           'savings_pct': {'electricity_kwh': 32.0, 'gas_kwh': 20.0, 'carbon_kg': 26.3}, 'baseline_intensity': {'electricity_kwh_per_m2': 36.9, 'gas_kwh_per_m2': 48.2},
                           'zoning_check': {'zones': [{'zone': '제3종일반주거지역', 'share': 99.8, 'applied_bcr_limit': 50, 'applied_far_limit': 300}], 'bcr_limit': 50.02, 'far_limit': 300.31,
                                            'check': {'label': '조례 기본 상한 이내 (1차 확인)', 'notes': ['대지의 100%가 지구단위계획구역입니다.']}, 'source': {'name': '전주시 도시계획 조례', 'articles': '제45조·제47조'}}}}
    detail = {'building_energy': {'bldg_parcels': 55}, 'register': None, 'official_code': '다마68b62a', 'model': None, 'exclusions': None, 'facts': []}
    data = {'coverage': {'electricity_months': 12, 'gas_months': 12}}
    snapshot = {'id': 'r1', 'title': '탄소 시뮬레이션 검토 보고서', 'kind': 'PLAN', 'place': '전주시 송천1동 일대', 'year': 2025, 'grid_id': 'cell_968500_1762000', 'created_at': '2026-10-14T13:00:00', 'sector': {'name': '선택 격자 cell_968500_1762000'},
                'summary': {'paragraphs': ['요약 문장.']}, 'facts': [{'id': 'electricity_intensity', 'text': '전력 원단위는 34.0 kWh/m²입니다.'}],
                'factors': {'ELECTRICITY': {'factor': 0.433, 'assumed': False, 'source': 'GIR'}, 'GAS': {'factor': 0.1826, 'assumed': True, 'source': 'rule'}},
                'context': {'official_code': '다마68b62a', 'facts': [{'id': 'official_grid', 'text': '공식 격자 다마68b62a와 같은 칸입니다.'}, {'id': 'context_admin', 'text': '대상 격자는 행정동 송천1동(격자의 100%, 인구 63,939명)에 걸쳐 있습니다.'}, {'id': 'building_energy', 'text': '건물 전체 전력 14,988,979kWh입니다.'}]},
                'totals': {'electricity_kwh': 9227634.0, 'gas_kwh': 19050333.0, 'carbon_kg': None, 'electricity_carbon_kg': 4190300.0}, 'coverage': data['coverage'], 'scenarios': [scenario],
                'cautions': report_cautions(data, detail, [scenario]), 'sources': [{'name': 'K-apt', 'status': 'PARTIAL', 'reference_period': '2025-01', 'collected_at': '2026-09-26T10:00:00', 'normalized_row_count': 1252, 'source_url': 'u'}],
                'evidence_hash': 'abc123hash', 'scope': '격자 관측 지번 합계'}
    text = report_markdown(snapshot)
    for heading in ('## 1. 검토 요약', '## 2. 대상지 개요', '## 3. 계획 개요', '## 4. 에너지·탄소 산정', '## 5. 용도지역·조례 상한 확인', '## 6. 유의사항', '## 7. 자료 출처'):
        assert heading in text
    assert text.count('\n## ') == 7
    assert '전주시 송천1동 일대' in text and 'cell_968500_1762000' not in text and 'abc123hash' not in text and 'SHA' not in text and '다마68b62a' not in text
    assert '| 용적률 | 336.0% (상한 300.31%) |' in text and '| 효율 계수 | 0.80배 |' in text and '| 태양광 전력 대체율 | 15% |' in text
    assert '| 연간 운영탄소 (전력+가스) | 560.3 tCO2eq | 760.0 tCO2eq | −26.3% |' in text
    assert '| 1인당 운영탄소 | 1,000.5 kgCO2eq' in text and '건축HUB' not in text.split('## 6. 유의사항')[0].split('## 2. 대상지 개요')[1]  # grid energy facts stay out of the plan sections
    assert '전력 36.9 kWh/m²·년' in text and '0.433' in text and '0.1826' in text
    assert '![계획안 A 3D 개념 배치](/api/scenarios/s1/image)' in text and '실제 배치안이 아닙니다' in text
    assert '| 제3종일반주거지역 | 99.8% | 50% | 300% |' in text and '조례 기본 상한 이내 (1차 확인)' in text and '지구단위계획구역' in text
    assert '| K-apt | 2025-01 | 2026-09-26 |' in text and '1,252' not in text
    assert '보고서 번호 r1' in text
    assert any('가스 탄소' in c for c in snapshot['cautions']) and any('3D 개념 배치' in c for c in snapshot['cautions'])


def test_status_report_markdown_without_plans_keeps_seven_sections_and_the_grid_energy():
    from app.reporting import report_markdown
    snapshot = {'id': 'r2', 'title': '격자 에너지·탄소 현황 보고서', 'kind': 'STATUS', 'place': '전주시 효자5동 일대', 'year': 2025, 'grid_id': 'cell_1_2', 'created_at': 't', 'sector': {'name': 'x'},
                'summary': {'paragraphs': ['요약.']}, 'facts': [{'id': 'missing', 'text': '기준 자료 또는 배출계수가 부족하여 연간 전체 운영탄소를 확정할 수 없습니다.'}],
                'context': {'facts': [{'id': 'building_energy', 'text': '건물 전체 전력 14,988,979kWh입니다.'}, {'id': 'context_zoning', 'text': '대상 격자의 공식 용도지역 면적 구성은 주거 63.9%입니다.'}]},
                'totals': {'electricity_kwh': None, 'gas_kwh': None, 'carbon_kg': None, 'electricity_carbon_kg': None}, 'coverage': {'electricity_months': 7, 'gas_months': 12}, 'scenarios': [],
                'cautions': ['주의.'], 'sources': [], 'evidence_hash': 'h', 'scope': '범위'}
    text = report_markdown(snapshot)
    assert text.count('\n## ') == 7 and '## 3. 에너지·탄소 현황' in text and '건물 전체 전력 14,988,979kWh' in text and '기준 자료' in text
    assert '계획안이 없습니다' in text and 'cell_1_2' not in text


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


def test_template_summary_leads_with_the_plan_sentences_when_plans_exist():
    from app.reporting import summarize
    facts=[{'id':'scope','text':'범위.'},{'id':'scenario_1','text':'계획안 A.'},{'id':'carbon_1','text':'탄소 A.'},{'id':'zoning_1','text':'상한 A.'},
           {'id':'scenario_2','text':'계획안 B.'},{'id':'carbon_2','text':'탄소 B.'},{'id':'annual','text':'격자 연간.'},{'id':'coverage','text':'자료.'}]
    assert summarize(facts,False)['paragraphs']==['범위.','계획안 A.','탄소 A.','상한 A.','계획안 B.','탄소 B.']
    assert summarize(facts[6:],False)['paragraphs']==['격자 연간.','자료.']   # no plan: the first sentences as before


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
