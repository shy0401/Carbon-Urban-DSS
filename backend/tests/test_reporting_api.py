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
        assert export.status_code==200 and '기준 자료' in export.text
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
