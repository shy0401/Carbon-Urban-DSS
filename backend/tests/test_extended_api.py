from fastapi.testclient import TestClient
from app.main import app


def test_baseline_area_is_restricted_to_matching_observation_year():
    from app.db import Session
    from app.models import TestbedSector
    from app.service import dashboard
    with Session() as db:
        sector=db.get(TestbedSector,'prototype')
        sector.metadata_json=dict(sector.metadata_json,baseline_floor_area_m2=94993.33,baseline_year=2025)
        db.flush()
        assert dashboard(db,year=2025)['baseline_floor_area_m2']==94993.33
        assert dashboard(db,year=2024)['baseline_floor_area_m2'] is None
        db.rollback()

def test_nondefault_year_is_returned_and_missing_months_are_null():
    c=TestClient(app)
    response=c.get('/api/dashboard?year=2024')
    assert response.status_code==200
    data=response.json()
    assert data['year']==2024
    assert len(data['monthly'])==12
    assert all(r['use_ym'].startswith('2024') for r in data['monthly'])

def test_model_reports_training_gate_not_fake_accuracy():
    c=TestClient(app)
    response=c.get('/api/model')
    assert response.status_code==200
    body=response.json()
    assert len(body['models'])==2
    for model in body['models']:
        if model['status']=='INSUFFICIENT_TRAINING_DATA':
            assert model['metrics'] is None
            assert not model['validated']

def test_job_history_persists_and_unknown_job_returns_404():
    c=TestClient(app)
    rows=c.get('/api/v1/collection-jobs').json()
    assert isinstance(rows,list)
    if rows:
        row=c.get('/api/v1/collection-jobs/'+rows[0]['id']).json()
        assert row['id']==rows[0]['id']
        assert row['status'] in ('QUEUED','RUNNING','SUCCESS','PARTIAL','FAILED')
    assert c.get('/api/v1/collection-jobs/missing-id').status_code==404

def test_impossible_green_footprint_and_capacity_rejected():
    c=TestClient(app)
    payload={'site_area':10000,'building_count':4,'footprint_per_building':2000,'floors':10,'households':100,'population':200,'green_ratio':.4}
    assert c.post('/api/scenarios',json=payload).status_code==422
    payload.update(footprint_per_building=500,green_ratio=.2,households=500,average_household_area=100)
    assert c.post('/api/scenarios',json=payload).status_code==422

def test_offline_recollection_blocked_without_job_creation(monkeypatch,tmp_path):
    monkeypatch.setenv('DEMO_OFFLINE_MODE','true')
    c=TestClient(app)
    before=len(c.get('/api/collections').json())
    assert c.get('/api/system').json()['offline_mode'] is True
    assert c.post('/api/collections',json={'datasets':['weather'],'start_month':'2025-01','end_month':'2025-12'}).status_code==409
    assert len(c.get('/api/collections').json())==before
