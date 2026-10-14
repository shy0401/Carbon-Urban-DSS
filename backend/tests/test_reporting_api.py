from fastapi.testclient import TestClient
from sqlalchemy import select
from app.main import app
from app.db import Session
from app.models import Grid

def test_report_persists_snapshot_and_download():
    with TestClient(app) as c:
        response=c.post('/api/reports',json={'year':2025})
        assert response.status_code==201
        r=response.json();rid=r['id']
        assert r['summary']['mode']=='TEMPLATE'
        saved=c.get('/api/reports/'+rid).json()
        assert saved['evidence_hash']==r['evidence_hash']
        export=c.get('/api/reports/'+rid+'/markdown')
        assert export.status_code==200 and '## 6. 유의사항' in export.text and r['place'] in export.text
        assert c.get('/api/reports/missing').status_code==404

def test_selected_grid_is_preserved_in_dashboard_and_report():
    with Session() as db:gid=db.scalar(select(Grid.id).order_by(Grid.id))
    c=TestClient(app)
    d=c.get('/api/dashboard',params={'year':2024,'grid_id':gid}).json()
    assert d['selected_sector']['grid_id']==gid
    r=c.post('/api/reports',json={'year':2024,'grid_id':gid}).json()
    assert r['grid_id']==gid and r['year']==2024

def test_incompatible_scenario_comparison_is_rejected():
    c=TestClient(app)
    s=c.post('/api/scenarios',json={'year':2024}).json()
    assert c.post('/api/reports',json={'year':2025,'scenario_ids':[s['id']]}).status_code==422

def test_plan_report_names_plans_a_b_c_and_carries_the_reference_comparison():
    c=TestClient(app)
    s=c.post('/api/scenarios',json={'year':2024}).json()
    assert 'place' in s and 'cell_' not in (s['place'] or '')
    assert set(s['annual'])>={'current','scenario','reference','difference'} and 'savings_pct' in s
    r=c.post('/api/reports',json={'year':2024,'scenario_ids':[s['id']]}).json()
    assert r['kind']=='PLAN' and r['scenarios'][0]['label']=='계획안 A'
    ids=[f['id'] for f in r['facts']]
    assert ids[0]=='scope' and ids[1]=='scenario_1'   # plan sentences right after the scope
    assert any(f['id']=='scenario_1' and f['text'].startswith('계획안 A') for f in r['facts'])
    assert not any('cell_' in f['text'] for f in r['facts'])
    assert c.get('/api/reports/'+r['id']+'/markdown').text.count('\n## ')==7

def test_grid100_layer_is_refused_on_the_public_gateway():
    """국토통계지도 100m: 국외 반출 금지 — the public demo gateway never gets the cells."""
    c=TestClient(app)
    r=c.get('/api/map/grid100',params={'grid':'cell_971500_1761500'},headers={'X-Public-Gateway':'1'})
    assert r.status_code==403 and '국외 반출' in r.json()['detail']
