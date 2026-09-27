from fastapi.testclient import TestClient
from app.main import app


def test_baseline_area_is_restricted_to_matching_observation_year():
    """Stored sector metadata applies only to its own year, and only where no observation exists
    (with observations the area comes from the same parcel set as the energy)."""
    from sqlalchemy import select
    from app.db import Session
    from app.models import EnergyMonthly, Grid, TestbedSector
    from app.service import dashboard
    with Session() as db:
        observed={row for row in db.scalars(select(EnergyMonthly.grid_id).where(EnergyMonthly.grid_id.is_not(None)).distinct())}
        empty_grid=next(grid_id for grid_id in db.scalars(select(Grid.id).order_by(Grid.id)) if grid_id not in observed)
        sector=db.get(TestbedSector,'prototype')
        sector.grid_id=empty_grid
        sector.metadata_json=dict(sector.metadata_json,baseline_floor_area_m2=94993.33,baseline_year=2025)
        db.flush()
        assert dashboard(db,year=2025)['baseline_floor_area_m2']==94993.33
        assert dashboard(db,year=2024)['baseline_floor_area_m2'] is None
        db.rollback()


def test_scenario_baseline_uses_one_parcel_set_for_energy_and_area():
    from app.db import Session
    from app.service import dashboard
    with Session() as db:
        data=dashboard(db,year=2025)
        scope=data['baseline_scope']
        if scope is None:
            assert data['baseline_floor_area_m2'] is None or not data['coverage']['energy_records']
            return
        assert data['baseline_floor_area_m2']==scope['area_m2']
        assert len(data['baseline_monthly'])==12
        assert all(row['electricity_kwh'] is not None for row in data['baseline_monthly'])
        if 'GAS' in scope['energy_types']:
            assert all(row['gas_kwh'] is not None for row in data['baseline_monthly'])

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
        assert row['status'] in ('QUEUED','RUNNING','WAITING','SUCCESS','PARTIAL','FAILED')  # WAITING: paused for a daily quota, resumes itself
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

def test_missing_provider_credentials_are_blocked_before_job_creation(monkeypatch):
    monkeypatch.setenv('DEMO_OFFLINE_MODE','false')
    monkeypatch.delenv('SGIS_CONSUMER_KEY',raising=False)
    monkeypatch.delenv('SGIS_CONSUMER_SECRET',raising=False)
    c=TestClient(app)
    before=len(c.get('/api/collections').json())
    response=c.post('/api/collections',json={'datasets':['sgis'],'start_month':'2025-01','end_month':'2025-08'})
    assert response.status_code==409
    assert 'SGIS_CONSUMER_KEY' in response.json()['detail']
    assert len(c.get('/api/collections').json())==before


def test_failed_collection_is_marked_resolved_when_a_later_job_succeeds():
    from app.main import mark_resolved_failures
    jobs = [
        {'id': 'b', 'status': 'SUCCESS', 'datasets': ['vworld_zoning'], 'created_at': '2026-09-23T04:20:00', 'errors': []},
        {'id': 'a', 'status': 'FAILED', 'datasets': ['vworld_zoning', 'kapt_energy'], 'created_at': '2026-09-23T04:04:00',
         'errors': [{'dataset': 'vworld_zoning', 'message': 'INVALID_RANGE'}, {'dataset': 'kapt_energy', 'message': '형식 오류'}]},
    ]
    marked = {job['id']: job for job in mark_resolved_failures(jobs)}
    assert marked['a']['resolved_datasets'] == ['vworld_zoning']
    assert marked['a']['resolved'] is False
    assert 'resolved' not in marked['b']
