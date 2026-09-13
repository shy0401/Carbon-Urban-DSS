import json,uuid,re
from contextlib import asynccontextmanager
from typing import Literal
from fastapi import FastAPI,HTTPException,Query
from fastapi.responses import JSONResponse
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
from . import official,kapt
from .imports import router as uploads_router
from .reporting import router as reports_router

@asynccontextmanager
async def lifespan(app):
    with engine.begin() as connection: connection.execute(text('CREATE EXTENSION IF NOT EXISTS postgis'))
    Base.metadata.create_all(engine)
    with Session() as db:
        seed_sources(db)
        # Import durable real raw assets on first startup; subsequent boots reuse normalized data.
        for source,model,collector in [('regions',Region,collect_regions),('buildings',Building,collect_spatial),('weather',WeatherMonthly,collect_weather)]:
            if db.scalar(select(func.count()).select_from(model))==0:
                try: collector(db)
                except Exception as exc:
                    db.rollback();s=db.get(DataSource,source);s.status='FAILED';s.quality='초기 수집 실패: '+type(exc).__name__;db.commit()
        from .emissions import collect_factors
        collect_factors(db)
        if not db.get(DataSource,'kapt') or db.scalar(select(func.count()).select_from(kapt.ApartmentComplex))==0:
            try:kapt.collect_kapt(db)
            except Exception:
                db.rollback()
        if not db.get(DataSource,'jeonju_apartments'):
            try:kapt.collect_municipal(db)
            except Exception:
                db.rollback()
        if not offline_mode() and not db.scalar(select(CollectionJob.id).limit(1)):
            queue_collection(db,['energy','weather'],f'{DEFAULT_YEAR}-01',f'{DEFAULT_YEAR}-12')
    yield

app=FastAPI(title='Carbon Urban DSS',version='0.1.0',lifespan=lifespan)
app.include_router(uploads_router)
app.include_router(reports_router)

@app.get('/api/health')
@app.get('/health')
def health():
    try:
        with engine.connect() as c: version=c.execute(text('SELECT PostGIS_Version()')).scalar()
        return {'status':'ok','database':'connected','postgis':version}
    except Exception: return JSONResponse({'status':'degraded','database':'unavailable'},status_code=503)

@app.get('/api/dashboard')
def get_dashboard(year:int=Query(DEFAULT_YEAR,ge=2000,le=2100),grid_id:str|None=None):
    with Session() as db:return dashboard(db,grid_id,year)

@app.get('/api/sources')
def sources(year:int=Query(DEFAULT_YEAR,ge=2000,le=2100)):
    with Session() as db:return dashboard(db,year=year)['sources']

PREVIEW_MODELS={'energy':EnergyMonthly,'weather':WeatherMonthly,'buildings':Building,'regions':Region,'grid':Grid,'factors':EmissionFactor,'zoning':ZoningArea,'population':PopulationGrid}

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
    datasets:list[Literal['energy','weather']]=Field(min_length=1,max_length=2)
    start_month:str=Field(default='2025-01',pattern=r'^20\d{2}-(0[1-9]|1[0-2])$')
    end_month:str=Field(default='2025-12',pattern=r'^20\d{2}-(0[1-9]|1[0-2])$')
    region:str='전주시'
    @model_validator(mode='after')
    def validate_period(self):
        if self.region not in ('전주시','Jeonju','52110'):raise ValueError('현재 자동 수집 범위는 전주시입니다')
        if self.start_month>self.end_month or len(month_range(self.start_month,self.end_month))>12:raise ValueError('수집기간은 최대 12개월이며 시작월 ≤ 종료월이어야 합니다')
        if self.end_month>=now().strftime('%Y-%m'):raise ValueError('완료된 과거 월만 수집 가능합니다')
        self.datasets=list(dict.fromkeys(self.datasets));return self

@app.post('/api/collections',status_code=202)
def create_collection(request:CollectionInput):
    if offline_mode():raise HTTPException(409,'오프라인 모드에서는 외부 수집을 시작하지 않습니다')
    with Session() as db:return serialize(queue_collection(db,request.datasets,request.start_month,request.end_month))

@app.get('/api/collections')
@app.get('/api/v1/collection-jobs')
def collections():
    with Session() as db:return [serialize(r) for r in db.scalars(select(CollectionJob).order_by(CollectionJob.created_at.desc()).limit(40))]

@app.get('/api/v1/collection-jobs/{job_id}')
def collection_detail(job_id:str):
    with Session() as db:
        job=db.get(CollectionJob,job_id)
        if not job:raise HTTPException(404,'수집 작업을 찾을 수 없습니다')
        return serialize(job)

class JobInput(BaseModel):
    source:Literal['energy','weather']
    start_month:str='2025-01'
    end_month:str='2025-12'
    region:str='전주시'

@app.post('/api/v1/collection-jobs',status_code=202)
def create_v1_job(request:JobInput):
    try:validated=CollectionInput(datasets=[request.source],start_month=request.start_month,end_month=request.end_month,region=request.region)
    except ValueError:raise HTTPException(422,'수집 기간 또는 지역 형식이 올바르지 않습니다') from None
    return create_collection(validated)

@app.get('/api/map')
def map_data(year:int=Query(DEFAULT_YEAR,ge=2000,le=2100)):
    with Session() as db:
        sector=db.get(TestbedSector,'prototype')
        grids=[]
        for r in db.scalars(select(Grid)):
            f=dict(r.geojson);f['properties']=dict(r.properties,selected=bool(sector and sector.grid_id==r.id),electricity_kwh=None,gas_kwh=None,carbon_kg=None,completeness=0)
            grids.append(f)
        for grid_id,typ,total,months in db.execute(select(EnergyMonthly.grid_id,EnergyMonthly.energy_type,func.sum(EnergyMonthly.usage_kwh),func.count(func.distinct(EnergyMonthly.use_ym))).where(EnergyMonthly.grid_id.is_not(None),EnergyMonthly.usage_kwh.is_not(None),EnergyMonthly.use_ym.between(f'{year}01',f'{year}12')).group_by(EnergyMonthly.grid_id,EnergyMonthly.energy_type)):
            for f in grids:
                if f['properties']['id']==grid_id:
                    f['properties']['electricity_kwh' if typ=='ELECTRICITY' else 'gas_kwh']=total
                    f['properties']['completeness']+=months/24*100
        from .domain import carbon_kg
        factors=factors_for(db,year)
        for f in grids:
            p=f['properties'];e=carbon_kg(p.get('electricity_kwh'),factors.get('ELECTRICITY'));g=carbon_kg(p.get('gas_kwh'),factors.get('GAS'))
            p['carbon_kg']=e+g if e is not None and g is not None else None
            p['electricity_carbon_kg']=e
            meta=sector.metadata_json if sector and sector.grid_id==p.get('id',p.get('grid_id')) else {}
            area=meta.get('baseline_floor_area_m2') if meta.get('baseline_year')==year else None
            p['carbon_intensity']=p['carbon_kg']/area if p['carbon_kg'] is not None and area else None
            p['far']=None;p['population_density']=None
        spatial_path=DATA/'spatial.json';spatial=json.loads(spatial_path.read_text(encoding='utf-8')) if spatial_path.exists() else {}
        return {'grids':{'type':'FeatureCollection','features':grids},'buildings':{'type':'FeatureCollection','features':[b.geojson for b in db.scalars(select(Building))]},'boundary':spatial.get('boundary',{'type':'FeatureCollection','features':[]}),'selected_sector':serialize(sector) if sector else None,'center':[127.148,35.8242],'crs':'EPSG:5179','grid_size_m':500,'year':year,'offline_mode':offline_mode()}

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
        baseline=dashboard(db,request.grid_id,request.year);result=scenario_calculation(request.model_dump(),baseline['monthly'],baseline['baseline_floor_area_m2'],factors_for(db,request.year))
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
        result=optimize(request.model_dump(),baseline['monthly'],baseline['baseline_floor_area_m2'],factors_for(db,request.year))
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
