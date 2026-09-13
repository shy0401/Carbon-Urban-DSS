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
