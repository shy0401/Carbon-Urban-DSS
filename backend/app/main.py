import json,uuid,re
from contextlib import asynccontextmanager
from typing import Literal
from fastapi import FastAPI,HTTPException,Query
from fastapi.responses import JSONResponse
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel,Field,model_validator
from sqlalchemy import select,text,func
from .db import Base,engine,Session
from .models import *
from .catalog import seed_sources
from .collectors import collect_regions,collect_spatial,collect_weather,DATA
from .service import serialize,dashboard,factors_for
from .domain import scenario_calculation,month_range
from .tasks import queue_collection
from .settings import DEFAULT_YEAR,offline_mode
from . import official,kapt,kapt_energy,kma_asos,sgis,vworld
from .imports import router as uploads_router
from .reporting import router as reports_router
from .overlays import router as overlays_router, grid_zoning_summary
from .readiness import build_readiness
from .collection_preflight import CollectionBlockedError,available_collection_datasets

@asynccontextmanager
async def lifespan(app):
    with engine.begin() as connection: connection.execute(text('CREATE EXTENSION IF NOT EXISTS postgis'))
    Base.metadata.create_all(engine)
    from .migrations import apply_migrations
    apply_migrations(engine)
    with Session() as db:
        seed_sources(db)
        kma_asos.backfill_weather_observations(db)
        # K-apt rows stored before the no-report rule (all-zero months) must not stay as 0 kWh.
        try:kapt_energy.reclassify_existing(db)
        except Exception:db.rollback()
        # Import durable real raw assets on first startup; subsequent boots reuse normalized data.
        for source,model,collector in [('regions',Region,collect_regions),('buildings',Building,collect_spatial),('weather',WeatherMonthly,collect_weather)]:
            if db.scalar(select(func.count()).select_from(model))==0:
                try: collector(db)
                except Exception as exc:
                    db.rollback();s=db.get(DataSource,source);s.status='FAILED';s.quality='초기 수집 실패: '+type(exc).__name__;db.commit()
        from .emissions import collect_factors
        collect_factors(db)
        # SGIS 1km grid statistics bundle(s) cut by scripts/sgis/extract_sgis_grid.py (skipped when already loaded).
        try:
            from .sgis_grid import import_sgis_grid
            import_sgis_grid(db)
        except Exception as exc:
            db.rollback();print('SGIS 1km 격자 통계 가져오기 실패:',type(exc).__name__,exc)
        if not db.get(DataSource,'kapt') or db.scalar(select(func.count()).select_from(kapt.ApartmentComplex))==0:
            try:kapt.collect_kapt(db)
            except Exception:
                db.rollback()
        if not db.get(DataSource,'jeonju_apartments'):
            try:kapt.collect_municipal(db)
            except Exception:
                db.rollback()
        if not offline_mode() and not db.scalar(select(CollectionJob.id).limit(1)):
            startup_datasets=available_collection_datasets(['energy','weather'])
            if startup_datasets:queue_collection(db,startup_datasets,f'{DEFAULT_YEAR}-01',f'{DEFAULT_YEAR}-12')
    yield

app=FastAPI(title='Carbon Urban DSS',version='0.1.0',lifespan=lifespan)
app.add_middleware(GZipMiddleware,minimum_size=2048)
app.include_router(uploads_router)
app.include_router(reports_router)
app.include_router(overlays_router)
from .area import router as area_router
from .area_report import router as area_report_router
app.include_router(area_router)
app.include_router(area_report_router)
from .sgis_grid import router as sgis_grid_router
app.include_router(sgis_grid_router)

@app.get('/api/health')
@app.get('/health')
def health():
    try:
        with engine.connect() as c: version=c.execute(text('SELECT PostGIS_Version()')).scalar()
        return {'status':'ok','database':'connected','postgis':version}
    except Exception: return JSONResponse({'status':'degraded','database':'unavailable'},status_code=503)

@app.get('/api/dashboard')
def get_dashboard(year:int=Query(DEFAULT_YEAR,ge=2000,le=2100),grid_id:str|None=None):
    from .overlays import grid_context
    with Session() as db:
        data=dashboard(db,grid_id,year)
        # Official context of the same grid (zoning, overlapping 행정동, buildings, K-apt complexes).
        data['context']=grid_context(db,data['selected_sector']['grid_id'] if data['selected_sector'] else None)
        return data

@app.get('/api/sources')
def sources(year:int=Query(DEFAULT_YEAR,ge=2000,le=2100)):
    with Session() as db:return dashboard(db,year=year)['sources']

@app.get('/api/readiness')
def readiness():
    with Session() as db:return build_readiness(db)

PREVIEW_MODELS={'energy':EnergyMonthly,'kapt_energy':kapt_energy.ApartmentEnergyMonthly,'weather':WeatherMonthly,'weather_kma':kma_asos.WeatherDailyObservation,'sgis_admin':sgis.SgisPopulationAdmin,'vworld_zoning':vworld.VworldZoningArea,'vworld_cadastral':vworld.CadastralParcel,'buildings':Building,'regions':Region,'grid':Grid,'factors':EmissionFactor,'zoning':ZoningArea,'population':PopulationGrid}

def raw_preview(asset):
    try:
        from pathlib import Path
        p=Path(asset.storage_location)
        if not p.resolve().is_relative_to(DATA.resolve()):return []
        b=p.read_bytes()
        if p.suffix.lower()=='.csv':
            import csv,io
            return list(csv.DictReader(io.StringIO(b.decode('utf-8-sig'))))[:8]
        if p.suffix.lower() in ('.xls','.xlsx'):
            import pandas as pd
            frame=pd.read_excel(p,header=None,nrows=10).fillna('')
            return frame.to_dict(orient='records')
        if b.startswith(b'PK'):
            import io,zipfile
            z=zipfile.ZipFile(io.BytesIO(b));lines=z.read(z.namelist()[0]).decode('cp949').splitlines()
            return [{'line':l} for l in lines if '전주시' in l][:8]
        s=b.decode('utf-8-sig')
        if s.lstrip().startswith('{'):
            j=json.loads(s)
            if 'elements' in j:return j['elements'][:8]
            if 'daily' in j:return [{k:v[i] for k,v in j['daily'].items()} for i in range(min(8,len(j['daily']['time'])))]
            if 'features' in j:return j['features'][:8]
            return [j] if len(s)<20000 else [{'description':'GeoJSON 원본','bytes':len(b)}]
        if '<item>' in s:
            from .domain import parse_energy
            return parse_energy(b)[0][:8]
        return [{'response':s[:3000]}]
    except Exception:return [{'error':'원본 미리보기 변환 불가'}]

@app.get('/api/sources/{source_id}')
def source_detail(source_id:str):
    with Session() as db:
        source=db.get(DataSource,source_id)
        if not source:raise HTTPException(404,'데이터 소스를 찾을 수 없습니다')
        assets=db.scalars(select(RawDataAsset).where(RawDataAsset.source_id==source_id).order_by(RawDataAsset.collected_at.desc())).all()
        jobs=[serialize(j) for j in db.scalars(select(CollectionJob).order_by(CollectionJob.created_at.desc()).limit(30)) if source_id in j.datasets]
        model=PREVIEW_MODELS.get(source_id)
        if source_id=='kapt':model=kapt.ApartmentComplex
        if source_id=='jeonju_apartments':model=kapt.MunicipalApartment
        preview=[serialize(r) for r in db.scalars(select(model).limit(8))] if model else []
        if source_id.startswith('upload:'):
            from .imports import ImportedRecord,UploadBatch
            batch=db.scalar(select(UploadBatch).where(UploadBatch.source_id==source_id))
            if batch:preview=[serialize(r) for r in db.scalars(select(ImportedRecord).where(ImportedRecord.batch_id==batch.id).limit(8))]
        import hashlib
        from pathlib import Path
        asset_rows=[]
        for a in assets[:100]:
            value=serialize(a);path=Path(a.storage_location)
            value['filename']=path.name
            value['sha256']=hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() and path.resolve().is_relative_to(DATA.resolve()) else None
            asset_rows.append(value)
        details=serialize(source)
        try:
            from .quality import dataset_quality
            details['quality_scores']=dataset_quality(db,source_id,DEFAULT_YEAR)
        except ImportError:pass
        return dict(source=details,raw_preview=raw_preview(assets[0]) if assets else [],normalized_preview=preview,jobs=jobs,assets=asset_rows,errors=[a.error for a in assets if a.error]+[e for j in jobs for e in j['errors']],coverage={'period':source.reference_period,'geography':source.geographic_coverage,'raw_rows':source.raw_row_count,'normalized_rows':source.normalized_row_count,'missing':source.missing_count},fields=list(preview[0]) if preview else [],quality_scores=details.get('quality_scores'),license='ODbL' if source.source_type=='FALLBACK' and source_id in ('buildings','boundary') else '공급기관 원문 이용조건 참조',manual_import={'formats':['CSV','XLSX','GeoJSON','ZIP(SHP+SHX+DBF+PRJ)'],'upload_location':'수집 데이터 → 파일 업로드','source_url':source.source_url})

class CollectionInput(BaseModel):
    datasets:list[Literal['energy','weather','kapt_energy','kma_asos','sgis','vworld_zoning','vworld_cadastral','vworld_buildings','building_register']]=Field(min_length=1,max_length=9)
    start_month:str=Field(default='2025-01',pattern=r'^20\d{2}-(0[1-9]|1[0-2])$')
    end_month:str=Field(default='2025-12',pattern=r'^20\d{2}-(0[1-9]|1[0-2])$')
    region:str='전주시'
    scope:Literal['smoke','limited','full']='smoke'
    @model_validator(mode='after')
    def validate_period(self):
        if self.region not in ('전주시','Jeonju','52110'):raise ValueError('현재 자동 수집 범위는 전주시입니다')
        if self.start_month>self.end_month or len(month_range(self.start_month,self.end_month))>12:raise ValueError('수집기간은 최대 12개월이며 시작월 ≤ 종료월이어야 합니다')
        if self.end_month>=now().strftime('%Y-%m'):raise ValueError('완료된 과거 월만 수집 가능합니다')
        self.datasets=list(dict.fromkeys(self.datasets));return self

@app.post('/api/collections',status_code=202)
def create_collection(request:CollectionInput):
    if offline_mode():raise HTTPException(409,'오프라인 모드에서는 외부 수집을 시작하지 않습니다')
    try:
        with Session() as db:return serialize(queue_collection(db,request.datasets,request.start_month,request.end_month,request.scope))
    except CollectionBlockedError as exc:
        raise HTTPException(409,str(exc)) from None

class MissingInput(BaseModel):
    from_year:int=Field(default=2015,ge=2000,le=2100)
    to_year:int=Field(default=DEFAULT_YEAR,ge=2000,le=2100)
    @model_validator(mode='after')
    def validate_years(self):
        if self.from_year>self.to_year:raise ValueError('시작 연도가 끝 연도보다 늦습니다')
        if self.to_year>=now().year:raise ValueError('끝나지 않은 올해는 아직 수집할 수 없습니다')
        if self.to_year-self.from_year>20:raise ValueError('한 번에 최대 21년까지 수집합니다')
        return self

@app.get('/api/collection/missing')
def missing_plan(from_year:int=2015,to_year:int=DEFAULT_YEAR):
    """What is still missing, what is blocked by a key/approval, and what needs a provider file. No external calls."""
    from .history import plan_missing
    from .tasks import ALL_MISSING,resume_overdue
    try:request=MissingInput(from_year=from_year,to_year=to_year)
    except ValueError as exc:raise HTTPException(422,'연도 범위를 확인하세요 (끝 연도는 작년까지, 최대 21년)') from None
    with Session() as db:
        try: resume_overdue(db)
        except Exception: db.rollback()
        plan=plan_missing(db,request.from_year,request.to_year)
        jobs=[j for j in db.scalars(select(CollectionJob).order_by(CollectionJob.created_at.desc()).limit(40)) if j.datasets==[ALL_MISSING]]
        plan['job']=serialize(jobs[0]) if jobs else None
        plan['offline']=offline_mode()
        return plan

@app.post('/api/collection/missing',status_code=202)
def start_missing(request:MissingInput):
    """Start (or, if it is waiting for a quota reset, restart now) the background 'collect everything missing' job."""
    if offline_mode():raise HTTPException(409,'오프라인 모드에서는 외부 수집을 시작하지 않습니다')
    from .tasks import queue_all_missing
    with Session() as db:return serialize(queue_all_missing(db,request.from_year,request.to_year))

@app.get('/api/collections')
@app.get('/api/v1/collection-jobs')
def collections():
    with Session() as db:return mark_resolved_failures([serialize(r) for r in db.scalars(select(CollectionJob).order_by(CollectionJob.created_at.desc()).limit(40))])

def mark_resolved_failures(jobs):
    """Flag failed datasets that a later job collected successfully (history stays unchanged)."""
    ordered=sorted(jobs,key=lambda job:job.get('created_at') or '')
    for index,job in enumerate(ordered):
        if job.get('status') not in ('FAILED','PARTIAL'):continue
        failed={e.get('dataset') for e in job.get('errors') or [] if isinstance(e,dict) and e.get('dataset')} or set(job.get('datasets') or [])
        later=[j for j in ordered[index+1:] if j.get('status')=='SUCCESS']
        resolved={d for d in failed if any(d in (j.get('datasets') or []) for j in later)}
        job['resolved_datasets']=sorted(resolved)
        job['resolved']=bool(failed) and resolved==failed
    return jobs

@app.get('/api/v1/collection-jobs/{job_id}')
def collection_detail(job_id:str):
    with Session() as db:
        job=db.get(CollectionJob,job_id)
        if not job:raise HTTPException(404,'수집 작업을 찾을 수 없습니다')
        return serialize(job)

class JobInput(BaseModel):
    source:Literal['energy','weather','kapt_energy','kma_asos','sgis','vworld_zoning','vworld_cadastral','vworld_buildings','building_register']
    start_month:str='2025-01'
    end_month:str='2025-12'
    region:str='전주시'
    scope:Literal['smoke','limited','full']='smoke'

@app.post('/api/v1/collection-jobs',status_code=202)
def create_v1_job(request:JobInput):
    try:validated=CollectionInput(datasets=[request.source],start_month=request.start_month,end_month=request.end_month,region=request.region,scope=request.scope)
    except ValueError:raise HTTPException(422,'수집 기간 또는 지역 형식이 올바르지 않습니다') from None
    return create_collection(validated)

def grid_energy_properties(db,year,factors):
    """Observed energy per grid for the map (sums, months, 12-month intensities)."""
    from .domain import carbon_kg
    from .grid_metrics import grid_energy_intensity
    from .kapt import ApartmentComplex
    within=EnergyMonthly.use_ym.between(f'{year}01',f'{year}12')
    rows=db.scalars(select(EnergyMonthly).where(within,EnergyMonthly.grid_id.is_not(None),EnergyMonthly.usage_kwh.is_not(None))).all()
    result={}
    for r in rows:
        p=result.setdefault(r.grid_id,{'electricity_kwh':None,'gas_kwh':None,'electricity_months':set(),'gas_months':set(),'parcels':set()})
        key='electricity' if r.energy_type=='ELECTRICITY' else 'gas'
        p[key+'_kwh']=(p[key+'_kwh'] or 0)+r.usage_kwh;p[key+'_months'].add(r.use_ym);p['parcels'].add((r.sigungu_code,r.bjdong_code,r.bun,r.ji))
    from .grid_metrics import validated_complex_areas
    complexes=list(db.scalars(select(ApartmentComplex)))
    households={row.kapt_code:row.households for row in complexes}
    areas,_=validated_complex_areas(complexes)
    intensity=grid_energy_intensity([{'grid_id':r.grid_id,'energy_type':r.energy_type,'use_ym':r.use_ym,'usage_kwh':r.usage_kwh,'kapt_code':(r.raw_record or {}).get('kapt_code'),'matched_gross_floor_area_m2':(r.raw_record or {}).get('matched_gross_floor_area_m2')} for r in rows],households,areas)
    electricity_factor=factors.get('ELECTRICITY')
    for grid_id,p in result.items():
        e=intensity.get(grid_id,{}).get('ELECTRICITY') or {};g=intensity.get(grid_id,{}).get('GAS') or {}
        p['electricity_months']=len(p['electricity_months']);p['gas_months']=len(p['gas_months']);p['energy_parcels']=len(p.pop('parcels'))
        p['electricity_complete_parcels']=e.get('complete_parcels') or 0;p['electricity_observed_parcels']=e.get('observed_parcels') or 0
        p['electricity_suspect_parcels']=e.get('suspect_parcels') or 0
        p['electricity_area_parcels']=e.get('area_parcels') or 0;p['electricity_household_parcels']=e.get('household_parcels') or 0
        p['electricity_kwh_per_m2']=e.get('kwh_per_m2');p['electricity_kwh_per_household']=e.get('kwh_per_household')
        p['electricity_area_m2']=e.get('area_m2');p['electricity_households']=e.get('households')
        p['gas_kwh_per_m2']=g.get('kwh_per_m2');p['gas_complete_parcels']=g.get('complete_parcels') or 0;p['gas_observed_parcels']=g.get('observed_parcels') or 0
        p['gas_area_parcels']=g.get('area_parcels') or 0;p['gas_area_m2']=g.get('area_m2')
        # 12-month totals of parcels observed in every month (partial-year parcels excluded).
        p['electricity_kwh_annual']=e.get('kwh');p['gas_kwh_annual']=g.get('kwh')
        p['electricity_carbon_kg_annual']=carbon_kg(e.get('kwh'),electricity_factor)
        p['electricity_carbon_kg']=carbon_kg(p['electricity_kwh'],electricity_factor)
        p['electricity_carbon_kg_per_m2']=carbon_kg(p['electricity_kwh_per_m2'],electricity_factor)
    return result

@app.get('/api/map')
def map_data(year:int=Query(DEFAULT_YEAR,ge=2000,le=2100)):
    from .domain import carbon_kg
    from .overlays import city_boundary,complex_features,grid_building_summary
    with Session() as db:
        sector=db.get(TestbedSector,'prototype')
        factors=factors_for(db,year)
        energy=grid_energy_properties(db,year,factors)
        zoning=grid_zoning_summary(db)
        buildings=grid_building_summary(db)
        complexes=complex_features(db)
        from .sgis_grid import grid_metric_properties
        sgis_props=grid_metric_properties(db)
        from .register_grid import grid_register_summary,map_properties as register_properties
        register=grid_register_summary(db)
        by_grid={}
        for feature in complexes['features']:
            c=feature['properties'];item=by_grid.setdefault(c.get('grid_id'),{'complex_count':0,'complex_households':None,'complex_gfa_m2':None,'complex_gfa_excluded':0})
            item['complex_count']+=1
            if c.get('households') is not None:item['complex_households']=(item['complex_households'] or 0)+c['households']
            # Only plausible published floor areas are summed; the rest are counted as excluded.
            if c.get('floor_area_status')=='OK':item['complex_gfa_m2']=(item['complex_gfa_m2'] or 0)+c['gross_floor_area_m2']
            else:item['complex_gfa_excluded']+=1
        empty_energy={'electricity_kwh':None,'gas_kwh':None,'electricity_months':0,'gas_months':0,'energy_parcels':0,'electricity_complete_parcels':0,'electricity_observed_parcels':0,'electricity_suspect_parcels':0,'electricity_area_parcels':0,'electricity_household_parcels':0,'electricity_kwh_per_m2':None,'electricity_kwh_per_household':None,'electricity_area_m2':None,'electricity_households':None,'gas_kwh_per_m2':None,'gas_complete_parcels':0,'gas_observed_parcels':0,'gas_area_parcels':0,'gas_area_m2':None,'electricity_kwh_annual':None,'gas_kwh_annual':None,'electricity_carbon_kg_annual':None,'electricity_carbon_kg':None,'electricity_carbon_kg_per_m2':None}
        grids=[]
        for r in db.scalars(select(Grid)):
            f=dict(r.geojson);base=dict(r.properties);grid_id=base.get('id',r.id)
            p={'id':grid_id,'area_m2':r.area_m2 or 250000,'x':base.get('x'),'y':base.get('y'),'selected':bool(sector and sector.grid_id==grid_id)}
            p.update(energy.get(grid_id,empty_energy))
            g=carbon_kg(p['gas_kwh'],factors.get('GAS'))
            p['carbon_kg']=p['electricity_carbon_kg']+g if p['electricity_carbon_kg'] is not None and g is not None else None
            p['completeness']=round((p['electricity_months']+p['gas_months'])/24*100,1)
            z=zoning.get(grid_id)
            p['zoning_status']=z['zoning_status'] if z else None
            p['residential_zone_ratio']=z['residential_zone_ratio'] if z else None
            p['urban_zone_ratio']=z['urban_zone_ratio'] if z else None
            p['dominant_zone']=z.get('dominant_zone') if z else None
            p['zone_shares']=z['shares'] if z else None
            b=buildings.get(grid_id)
            if b:
                p.update(building_source='VWORLD',building_status=b['status'],building_count=b['building_count'],footprint_m2=b['footprint_m2'],coverage_pct=b['coverage_pct'],far_est_pct=b['far_est_pct'],floor_area_est_m2=b['floor_area_est_m2'],avg_floors=b['avg_floors'],max_floors=b['max_floors'],floors_known_pct=b['floors_known_pct'],building_density=b['density_per_km2'],residential_building_share=b['residential_share_pct'],dominant_use=b['dominant_use'],use_share_pct=b['category_share_pct'],use_known_pct=b.get('use_known_pct'))
            else:
                # Fallback: OSM apartment outlines only (not every building).
                p.update(building_source='OSM' if base.get('building_count') else None,building_status=None,building_count=base.get('building_count'),footprint_m2=None,coverage_pct=None,far_est_pct=None,floor_area_est_m2=None,avg_floors=None,max_floors=None,floors_known_pct=None,building_density=None,residential_building_share=None,dominant_use=None,use_share_pct=None,use_known_pct=None)
            p.update(by_grid.get(grid_id,{'complex_count':0,'complex_households':None,'complex_gfa_m2':None,'complex_gfa_excluded':0}))
            # Parent SGIS 1km cell densities/shares (official, noisy); absent when no bundle is loaded.
            p.update(sgis_props.get(grid_id,{}))
            # 건축물대장 표제부 linked to this grid: official floor area, FAR floor area, use mix.
            p.update(register_properties(register.get(grid_id)))
            f['properties']=p;grids.append(f)
        official_buildings=any(b['building_count'] for b in buildings.values())
        spatial_path=DATA/'spatial.json';spatial=json.loads(spatial_path.read_text(encoding='utf-8')) if spatial_path.exists() else {}
        official_boundary=city_boundary(db)
        boundary=official_boundary or spatial.get('boundary',{'type':'FeatureCollection','features':[]})
        electricity_factor=factors.get('ELECTRICITY')
        return {
            'grids':{'type':'FeatureCollection','features':grids},
            'buildings':{'type':'FeatureCollection','features':[] if official_buildings else [b.geojson for b in db.scalars(select(Building))]},
            'buildings_mode':'viewport' if official_buildings else 'embedded',
            'buildings_source':'VWorld LT_C_SPBD 도로명주소 건물(화면 범위 조회)' if official_buildings else 'OpenStreetMap 공동주택 윤곽(대체 자료, 전체 건물 아님)',
            'boundary':boundary,'boundary_source':official_boundary['features'][0]['properties']['source'] if official_boundary else 'OpenStreetMap 행정경계(대체 자료)',
            'complexes':complexes,'complex_floor_area_issues':sum(1 for f in complexes['features'] if f['properties'].get('floor_area_status')!='OK'),
            'factors':{'electricity':{'value':electricity_factor['factor'],'unit':electricity_factor['factor_unit'],'source':electricity_factor.get('source'),'reference_year':electricity_factor.get('reference_year')} if electricity_factor else None,'gas':None if not factors.get('GAS') else {'value':factors['GAS']['factor'],'unit':factors['GAS']['factor_unit']}},
            'register':{'grids':len(register),'buildings':sum(r['buildings'] for r in register.values()),'source':'건축HUB 건축물대장 표제부 (격자 연결분)'} if register else None,
            'sgis_grid':{'year':next((v.get('sgis1k_year') for v in sgis_props.values()),None),'source':'SGIS 격자 통계 1km (공공데이터포털 15141768)','note':'소속 1km 공식 격자의 밀도·비율이며 500m로 나눈 값이 아닙니다. 비밀보호 잡음(±7) 포함.'} if sgis_props else None,
            'selected_sector':serialize(sector) if sector else None,'center':[127.148,35.8242],'crs':'EPSG:5179','grid_size_m':500,'grid_area_m2':250000,'year':year,'offline_mode':offline_mode(),
        }

@app.get('/api/grids/{grid_id}')
def grid_detail(grid_id:str,year:int=Query(DEFAULT_YEAR,ge=2000,le=2100)):
    with Session() as db:
        grid=db.get(Grid,grid_id)
        if not grid:raise HTTPException(404,'격자를 찾을 수 없습니다')
        return dict(dashboard(db,grid_id,year),grid=serialize(grid))

class ScenarioInput(BaseModel):
    site_area:float=Field(default=50000,gt=0,le=250000)
    building_count:int=Field(default=8,ge=1,le=200)
    footprint_per_building:float=Field(default=600,gt=0,le=250000)
    floors:int=Field(default=15,ge=3,le=40)
    households:int=Field(default=600,ge=0,le=100000)
    population:int=Field(default=1500,ge=0,le=1000000)
    efficiency_factor:float=Field(default=0.85,gt=0,le=2)
    pv_ratio:float=Field(default=0.1,ge=0,le=1)
    green_ratio:float=Field(default=0.2,ge=0,le=1)
    average_household_area:float=Field(default=85,gt=0,le=500)
    grid_id:str|None=None
    year:int=Field(default=DEFAULT_YEAR,ge=2000,le=2100)
    @model_validator(mode='after')
    def validate_footprint(self):
        if self.building_count*self.footprint_per_building>self.site_area:raise ValueError('건축면적 합계가 부지 면적을 초과합니다')
        if self.building_count*self.footprint_per_building+self.site_area*self.green_ratio>self.site_area:raise ValueError('건축면적과 녹지면적 합계가 부지를 초과합니다')
        if self.households*self.average_household_area>self.building_count*self.footprint_per_building*self.floors:raise ValueError('입력 세대수의 면적 수요가 연면적을 초과합니다')
        return self

@app.post('/api/scenarios')
def scenario(request:ScenarioInput):
    with Session() as db:
        if request.grid_id and not db.get(Grid,request.grid_id):raise HTTPException(404,'격자를 찾을 수 없습니다')
        baseline=dashboard(db,request.grid_id,request.year);result=scenario_calculation(request.model_dump(),baseline['baseline_monthly'],baseline['baseline_floor_area_m2'],factors_for(db,request.year))
        result['baseline_scope']=baseline.get('baseline_scope')
        result['id']=str(uuid.uuid4());result['quality']='기준 에너지·연면적 부족' if not baseline['baseline_floor_area_m2'] else '공간 매칭된 관측 원단위 기반'
        result['calculations']={key:result[key] for key in ['total_footprint','gross_floor_area','far','bcr','households','population','green_area_m2']}
        result['baseline']={k:baseline.get(k) for k in ['current_far','current_bcr','households','population','gross_floor_area_m2','developable_site_area_m2']}
        result['legal_status']='법적 상한 미확정'
        db.add(Scenario(id=result['id'],inputs=dict(request.model_dump(),grid_id=baseline['selected_sector']['grid_id'] if baseline['selected_sector'] else None)));db.flush();db.add(ScenarioResult(id=result['id'],result=result));db.commit();return result

class OptimizationInput(ScenarioInput):
    min_households:int=Field(default=500,ge=0,le=100000)
    min_population:int=Field(default=1000,ge=0,le=1000000)

@app.post('/api/optimize')
def optimization(request:OptimizationInput):
    from .modeling import optimize
    with Session() as db:
        baseline=dashboard(db,request.grid_id,request.year)
        result=optimize(request.model_dump(),baseline['baseline_monthly'],baseline['baseline_floor_area_m2'],factors_for(db,request.year))
        result['baseline_scope']=baseline.get('baseline_scope')
        sid=str(uuid.uuid4());db.add(Scenario(id=sid,inputs=dict(request.model_dump(),type='OPTIMIZATION')));db.flush();db.add(ScenarioResult(id=sid,result=result));db.commit();return result

@app.get('/api/model')
def models(year:int=Query(DEFAULT_YEAR,ge=2000,le=2100)):
    from .model_service import model_status
    with Session() as db:return model_status(db,year)

@app.get('/api/scenarios')
def scenario_history():
    with Session() as db:
        return [dict(serialize(s),result=db.get(ScenarioResult,s.id).result if db.get(ScenarioResult,s.id) else None) for s in db.scalars(select(Scenario).order_by(Scenario.created_at.desc()).limit(30))]

@app.post('/api/model/validate')
def validate_models(year:int=Query(DEFAULT_YEAR,ge=2000,le=2100)):
    from .model_service import model_status
    with Session() as db:return model_status(db,year,train=True)

@app.get('/api/system')
def system():
    return {'offline_mode':offline_mode(),'baseline_year':DEFAULT_YEAR,'version':app.version}

class OfflineInput(BaseModel):
    enabled:bool

@app.post('/api/system/offline')
def set_offline(request:OfflineInput):
    flag=DATA/'offline.flag'
    if request.enabled:flag.write_text('Use verified local DB and cache only.\n',encoding='utf-8')
    else:flag.unlink(missing_ok=True)
    return system()
