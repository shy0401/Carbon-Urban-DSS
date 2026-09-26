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
    if m['buildings_mode']=='embedded':
        assert len(m['buildings']['features'])>0
    else:
        # Official buildings are served per viewport; the prototype grid has buildings.
        lon,lat=m['center'];box=f'{lon-0.02},{lat-0.02},{lon+0.02},{lat+0.02}'
        viewport=c.get('/api/map/buildings',params={'bbox':box}).json()
        assert viewport['total']>0 and viewport['features'][0]['properties']['use_category']
    assert d['selected_sector']['area_m2']==250000
    assert len(d['monthly'])==12


def test_map_grids_carry_explicit_indicator_fields():
    m=TestClient(app).get('/api/map').json()
    props=m['grids']['features'][0]['properties']
    for key in ('electricity_kwh','electricity_months','electricity_kwh_per_m2','electricity_complete_parcels','residential_zone_ratio','zone_shares','building_count','coverage_pct','far_est_pct','floors_known_pct','complex_count','completeness'):
        assert key in props
    assert m['grid_area_m2']==250000 and m['complexes']['type']=='FeatureCollection'
    # A ratio is never reported without the observations behind it.
    for feature in m['grids']['features']:
        p=feature['properties']
        if p['electricity_kwh_per_m2'] is not None:
            assert p['electricity_complete_parcels']>0 and p['electricity_area_m2']>0


def test_building_viewport_rejects_oversized_or_malformed_bbox():
    c=TestClient(app)
    assert c.get('/api/map/buildings',params={'bbox':'127,35,128,36'}).status_code==422
    assert c.get('/api/map/buildings',params={'bbox':'a,b,c,d'}).status_code==422

def test_invalid_scenario_geometry_rejected():
    c=TestClient(app)
    response=c.post('/api/scenarios',json={'site_area':100,'building_count':10,'footprint_per_building':500,'floors':15})
    assert response.status_code==422

def test_collection_range_prevents_reckless_requests():
    c=TestClient(app)
    assert c.post('/api/collections',json={'datasets':['energy'],'start_month':'2020-01','end_month':'2025-12'}).status_code==422

def test_scenario_3d_scene_is_stored_only_as_png_for_a_saved_scenario():
    import base64,uuid
    from app.db import Session,engine
    from app.models import Base,Scenario,ScenarioImage
    Base.metadata.create_all(engine,tables=[Scenario.__table__,ScenarioImage.__table__])  # the app does this at startup
    c=TestClient(app)
    png=base64.b64encode(b'\x89PNG\r\n\x1a\n'+b'\x00'*32).decode()
    assert c.put('/api/scenarios/none/image',json={'data_url':'data:image/png;base64,'+png}).status_code==404
    sid=str(uuid.uuid4())
    with Session() as db:db.add(Scenario(id=sid,inputs={'floors':12,'building_count':4}));db.commit()
    try:
        assert c.put(f'/api/scenarios/{sid}/image',json={'data_url':'data:image/jpeg;base64,'+png}).status_code==422
        assert c.put(f'/api/scenarios/{sid}/image',json={'data_url':'data:image/png;base64,'+base64.b64encode(b'not png at all').decode()}).status_code==422
        assert c.get(f'/api/scenarios/{sid}/image').status_code==404
        ok=c.put(f'/api/scenarios/{sid}/image',json={'data_url':'data:image/png;base64,'+png})
        assert ok.status_code==200 and ok.json()['bytes']==40
        shown=c.get(f'/api/scenarios/{sid}/image')
        assert shown.status_code==200 and shown.headers['content-type']=='image/png' and shown.content.startswith(b'\x89PNG')
        assert any(s['id']==sid and s['has_image'] for s in c.get('/api/scenarios').json())
    finally:
        with Session() as db:
            img=db.get(ScenarioImage,sid)
            if img:db.delete(img)
            db.delete(db.get(Scenario,sid));db.commit()
