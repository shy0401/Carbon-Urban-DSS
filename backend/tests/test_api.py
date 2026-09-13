"""Integration checks run against the actual PostGIS DB in Compose."""
from fastapi.testclient import TestClient
from sqlalchemy import text,select
from app.main import app
from app.db import engine,Session
from app.models import Grid

def test_health_and_postgis():
    client=TestClient(app)
    response=client.get('/api/health')
    assert response.status_code==200
    assert response.json()['database']=='connected'
    with engine.connect() as connection:
        assert connection.execute(text('SELECT ST_SRID(ST_SetSRID(ST_MakePoint(0,0),5179))')).scalar()==5179

def test_stored_grid_exact_dimensions():
    with engine.connect() as c:
        row=c.execute(text('SELECT COUNT(*),MAX(ABS(ST_Area(geom)-250000)),MAX(ABS(ST_XMax(geom)-ST_XMin(geom)-500)),MAX(ABS(ST_YMax(geom)-ST_YMin(geom)-500)) FROM grid_500m')).one()
    assert row[0]>0
    assert row[1]<0.01
    assert row[2]<0.0001
    assert row[3]<0.0001

def test_dashboard_and_map_have_real_spatial_records():
    c=TestClient(app)
    d=c.get('/api/dashboard').json();m=c.get('/api/map').json()
    assert len(m['buildings']['features'])>0
    assert d['selected_sector']['area_m2']==250000
    assert len(d['monthly'])==12

def test_invalid_scenario_geometry_rejected():
    c=TestClient(app)
    response=c.post('/api/scenarios',json={'site_area':100,'building_count':10,'footprint_per_building':500,'floors':15})
    assert response.status_code==422

def test_collection_range_prevents_reckless_requests():
    c=TestClient(app)
    assert c.post('/api/collections',json={'datasets':['energy'],'start_month':'2020-01','end_month':'2025-12'}).status_code==422
