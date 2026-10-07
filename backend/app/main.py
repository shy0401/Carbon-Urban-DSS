import json,os,uuid,re
from contextlib import asynccontextmanager
from typing import Literal
from fastapi import FastAPI,HTTPException,Query,Request
from fastapi.responses import JSONResponse
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel,Field,model_validator
from sqlalchemy import select,text,func
from .db import Base,engine,Session
from .models import *
from .catalog import seed_sources
from .collectors import collect_regions,collect_spatial,collect_weather,DATA
from .service import serialize,dashboard,factors_for
from .domain import scenario_calculation,month_range,carbon_kg
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
        try:
            from .emissions import ensure_gas_factor
            ensure_gas_factor(db)
        except Exception:db.rollback()
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
        # Parcel → grid lookup for the city-wide 건축HUB energy (built once from the cadastral layer).
        try:
            from .energy_parcels import ParcelGrid,build_parcel_grid
            if not db.scalar(select(func.count()).select_from(ParcelGrid)) and db.scalar(text("SELECT count(*) FROM cadastral_parcels")):
                print('parcel_grid 생성:',build_parcel_grid(db),'필지')
        except Exception as exc:
            db.rollback();print('parcel_grid 생성 실패:',type(exc).__name__,exc)
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
        # Study-region records (the original Jeonju area is registered from its existing grids).
        try:
            from .regions import ensure_default_region
            ensure_default_region(db)
        except Exception as exc:
            db.rollback();print('기본 지역 등록 실패:',type(exc).__name__,exc)
        if not offline_mode() and not db.scalar(select(CollectionJob.id).limit(1)):
            startup_datasets=available_collection_datasets(['energy','weather'])
            if startup_datasets:queue_collection(db,startup_datasets,f'{DEFAULT_YEAR}-01',f'{DEFAULT_YEAR}-12')
    _warm_caches_in_background()
    yield

def _warm_caches_in_background():
    """Build the provider error indexes and touch the default dashboard once after start-up, so the first
    visitor of 수집 데이터·대시보드 does not wait for a cold scan (measured 24 s) or cold DB pages."""
    if os.getenv('DSS_WARM_CACHE','1')=='0' or os.getenv('PYTEST_CURRENT_TEST'):return
    import threading
    def warm():
        try:
            with Session() as db:
                build_readiness(db)
                dashboard(db,None,DEFAULT_YEAR)
            from .area import warm_inputs
            warm_inputs(2015,DEFAULT_YEAR)
            from .sgis_grid500 import data_root,import_sgis_grid500,scan
            if scan(data_root())[0]:
                with Session() as db:import_sgis_grid500(db)
            # 공통 데이터 기준(docs/DATA_STANDARD.md): 판이 바뀌었으면 저장된 값(냉난방도일·K-apt 탄소)을 새 규칙으로 맞추고 점검
            from .standard import VERSION as STANDARD_VERSION,applied_version,apply_standard,check_standard
            if applied_version()!=STANDARD_VERSION:
                with Session() as db:
                    apply_standard(db)
                    check_standard(db,raw_sample=5000)
            # GIR 지역 온실가스 인벤토리·가스공사 시·도 판매량 (data/raw/research/gir, data/raw/gas): 새 파일만 읽음
            from .regional_stats import import_all
            with Session() as db:
                loaded=import_all(db)
                if any(loaded.values()):print('지역 통계 가져오기:',loaded)
        except Exception as exc:  # noqa: BLE001 - warming is best effort
            print('캐시 예열 실패:',type(exc).__name__,exc)
    threading.Thread(target=warm,name='warm-caches',daemon=True).start()

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
from . import energy_parcels  # noqa: F401 - registers parcel_grid before create_all
from . import sgis_grid_official  # noqa: F401 - registers sgis_official_grid_cells before create_all
from . import regions,national,ordinances  # noqa: F401 - registers admin_units, study_regions, grid_regions, national_*, zoning_ordinances before create_all
from .regions_api import router as regions_router
app.include_router(regions_router)
from .province_map import router as province_map_router
app.include_router(province_map_router)
from .dongs import router as dongs_router
app.include_router(dongs_router)
from .sgis_grid500 import router as sgis_grid500_router  # also registers sgis_grid500_values before create_all
from . import regional_stats  # noqa: F401 - registers gir_regional_ghg, citygas_sido_monthly before create_all
from . import team_grid  # noqa: F401 - registers team_grid500/100, team_developments before create_all
from . import solar  # noqa: F401 - registers solar_monthly before create_all
app.include_router(sgis_grid500_router)
from .national_map import router as national_map_router
app.include_router(national_map_router)
from .validation import router as validation_router
app.include_router(validation_router)
from .regions import RegionNotReady,DEFAULT_REGION,region_for_grid

def _scope(db,region):
    """Study region scope for a reader; an unknown or unprepared region is a 404 with the reason."""
    from .regions import scope
    try:return scope(db,region)
    except RegionNotReady as exc:raise HTTPException(404,str(exc)) from None

@app.get('/api/health')
@app.get('/health')
def health():
    try:
        with engine.connect() as c: version=c.execute(text('SELECT PostGIS_Version()')).scalar()
        return {'status':'ok','database':'connected','postgis':version}
    except Exception: return JSONResponse({'status':'degraded','database':'unavailable'},status_code=503)

@app.get('/api/dashboard')
def get_dashboard(year:int=Query(DEFAULT_YEAR,ge=2000,le=2100),grid_id:str|None=None,region:str|None=Query(None,max_length=10)):
    from .overlays import grid_context
    with Session() as db:
        region=region or region_for_grid(db,grid_id)
        _scope(db,region)
        data=dashboard(db,grid_id,year,region)
        # Official context of the same grid (zoning, overlapping 행정동, buildings, K-apt complexes).
        selected=data['selected_sector']['grid_id'] if data['selected_sector'] else None
        data['context']=grid_context(db,selected)
        # Every metered building of the same grid (건축HUB by 법정동, 2024-), next to the apartment figures.
        try:
            from .energy_parcels import grid_building_energy,map_properties as building_energy_properties
            factor=(factors_for(db,year).get('ELECTRICITY') or {}).get('factor')
            item=grid_building_energy(db,year).get(selected) if selected else None
            from .energy_parcels import year_complete
            data['building_energy']=dict(building_energy_properties(item,factor),year=year,complete=year_complete(year)) if item else None
        except Exception:
            db.rollback();data['building_energy']=None
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

@app.get('/api/standard')
def standard_status():
    """The shared data standard (docs/DATA_STANDARD.md): the rules the calculations use and the last check."""
    from .standard import last_check,summary
    return {**summary(),'last_check':last_check()}

@app.post('/api/standard/check')
def standard_check():
    from .standard import check_standard
    with Session() as db:
        return check_standard(db,raw_sample=5000)

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

def grid_energy_properties(db,year,factors,sc=None):
    """Observed energy per grid for the map (sums, months, 12-month intensities). ``sc``: one study region only."""
    from .domain import carbon_kg
    from .grid_metrics import grid_energy_intensity
    from .kapt import ApartmentComplex
    within=EnergyMonthly.use_ym.between(f'{year}01',f'{year}12')
    clause=sc.legal_clause(EnergyMonthly.sigungu_code) if sc is not None else None
    if clause is not None:within=within & clause
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
        # 도시가스 탄소: 가정 계수 규칙 (emissions.ensure_gas_factor), 12개월 관측 지번만
        p['gas_carbon_kg_annual']=carbon_kg(g.get('kwh'),factors.get('GAS'))
    return result

def _level(db,code):
    from .regions import detail_level,get_region
    return detail_level(get_region(db,code)) if code!=DEFAULT_REGION else 'DETAILED'

@app.get('/api/map')
def map_data(request:Request,year:int=Query(DEFAULT_YEAR,ge=2000,le=2100),region:str|None=Query(None,max_length=10)):
    from .domain import carbon_kg
    from .overlays import city_boundary,complex_features,grid_building_summary
    from .service import region_sector
    with Session() as db:
        sc=_scope(db,region)
        ids=sorted(sc.grid_ids)
        sector=region_sector(db,sc)
        factors=factors_for(db,year)
        energy=grid_energy_properties(db,year,factors,sc)
        zoning=grid_zoning_summary(db)
        buildings=grid_building_summary(db,sc.grid_ids)
        complexes=complex_features(db,sc)
        from .sgis_grid import grid_metric_properties
        sgis_props=grid_metric_properties(db,ids)
        from .sgis_grid500 import grid500_properties,coverage as grid500_coverage,project_code
        grid500=grid500_properties(db,ids)
        from .register_grid import grid_register_summary,map_properties as register_properties
        register=grid_register_summary(db)
        from .energy_parcels import grid_building_energy,map_properties as building_energy_properties,year_complete
        building_energy=grid_building_energy(db,year)
        from .sgis_grid_official import official_codes,meta as official_grid_meta
        official=official_codes(db)
        # 팀 데이터셋(탄소공간지도 500m 배출, 국토통계지도 100m 합; 국토통계는 공개 게이트웨이 응답에서 뺌)
        from .team_grid import map_properties as team_properties,is_public
        team=team_properties(db,sc.code,year,ids,public=is_public(request),register_ids=register.keys())
        e_factor=(factors.get('ELECTRICITY') or {}).get('factor')
        by_grid={}
        for feature in complexes['features']:
            c=feature['properties'];item=by_grid.setdefault(c.get('grid_id'),{'complex_count':0,'complex_households':None,'complex_gfa_m2':None,'complex_gfa_excluded':0})
            item['complex_count']+=1
            if c.get('households') is not None:item['complex_households']=(item['complex_households'] or 0)+c['households']
            # Only plausible published floor areas are summed; the rest are counted as excluded.
            if c.get('floor_area_status')=='OK':item['complex_gfa_m2']=(item['complex_gfa_m2'] or 0)+c['gross_floor_area_m2']
            elif c.get('floor_area_status'):item['complex_gfa_excluded']+=1  # None: list-only complex (no detail page yet)
        empty_energy={'electricity_kwh':None,'gas_kwh':None,'electricity_months':0,'gas_months':0,'energy_parcels':0,'electricity_complete_parcels':0,'electricity_observed_parcels':0,'electricity_suspect_parcels':0,'electricity_area_parcels':0,'electricity_household_parcels':0,'electricity_kwh_per_m2':None,'electricity_kwh_per_household':None,'electricity_area_m2':None,'electricity_households':None,'gas_kwh_per_m2':None,'gas_complete_parcels':0,'gas_observed_parcels':0,'gas_area_parcels':0,'gas_area_m2':None,'electricity_kwh_annual':None,'gas_kwh_annual':None,'electricity_carbon_kg_annual':None,'electricity_carbon_kg':None,'electricity_carbon_kg_per_m2':None,'gas_carbon_kg_annual':None}
        grids=[]
        rows=[r for start in range(0,len(ids),2000) for r in db.scalars(select(Grid).where(Grid.id.in_(ids[start:start+2000])).order_by(Grid.id))]
        for r in rows:
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
            # Official SGIS 500m cell code that coincides with this project cell (API boundary; no statistics).
            p['sgis500_code']=official.get(grid_id) or (project_code(grid_id) if grid500 else None)
            # Own SGIS 500m cell statistics (자료제공 신청분): totals only, disclosure noise included; NO_STAT = no row, not 0.
            p.update(grid500.get(grid_id,{}))
            # 건축물대장 표제부 linked to this grid: official floor area, FAR floor area, use mix.
            p.update(register_properties(register.get(grid_id)))
            # Every metered building of the grid (건축HUB by 법정동, placed through the cadastral parcel).
            p.update(building_energy_properties(building_energy.get(grid_id),e_factor))
            p.update(team.get(grid_id,{}))
            f['properties']=p;grids.append(f)
        official_buildings=any(b['building_count'] for b in buildings.values()) or not sc.is_default
        spatial_path=DATA/'spatial.json';spatial=json.loads(spatial_path.read_text(encoding='utf-8')) if spatial_path.exists() and sc.is_default else {}
        official_boundary=city_boundary(db,sc)
        boundary=official_boundary or spatial.get('boundary',{'type':'FeatureCollection','features':[]})
        electricity_factor=factors.get('ELECTRICITY')
        return {
            'grids':{'type':'FeatureCollection','features':grids},
            'buildings':{'type':'FeatureCollection','features':[] if official_buildings else [b.geojson for b in db.scalars(select(Building))]},
            'buildings_mode':'viewport' if official_buildings else 'embedded',
            'buildings_source':'VWorld LT_C_SPBD 도로명주소 건물(화면 범위 조회)' if official_buildings else 'OpenStreetMap 공동주택 윤곽(대체 자료, 전체 건물 아님)',
            'boundary':boundary,'boundary_source':official_boundary['features'][0]['properties']['source'] if official_boundary else 'OpenStreetMap 행정경계(대체 자료)',
            'complexes':complexes,'complex_floor_area_issues':sum(1 for f in complexes['features'] if f['properties'].get('floor_area_status') not in ('OK',None)),
            'complexes_source':complexes.get('source'),
            'factors':{'electricity':{'value':electricity_factor['factor'],'unit':electricity_factor['factor_unit'],'source':electricity_factor.get('source'),'reference_year':electricity_factor.get('reference_year')} if electricity_factor else None,'gas':None if not factors.get('GAS') else {'value':factors['GAS']['factor'],'unit':factors['GAS']['factor_unit']}},
            'building_energy':{'grids':len(building_energy),'parcels':sum(v['parcels'] for v in building_energy.values()),'complete':year_complete(year),'source':'건축HUB 건물에너지 (법정동 단위 전 지번, 연속지적으로 격자 배치)'} if building_energy else None,
            'register':{'grids':len(register),'buildings':sum(r['buildings'] for r in register.values()),'source':'건축HUB 건축물대장 표제부 (격자 연결분)'} if register else None,
            'sgis_grid':{'year':next((v.get('sgis1k_year') for v in sgis_props.values()),None),'source':'SGIS 격자 통계 1km (공공데이터포털 15141768)','note':'소속 1km 공식 격자의 밀도·비율이며 500m로 나눈 값이 아닙니다. 비밀보호 잡음(±7) 포함.'} if sgis_props else None,
            'sgis_grid500':dict({k:v for k,v in grid500_coverage(db).items() if k in ('first_year','last_year','base_year','source')},cells=sum(1 for v in grid500.values() if v.get('sgis500_status')=='OBSERVED'),note='격자 자체의 500m 공식 통계(총괄 항목). 인구 5 미만은 0 또는 5, 사업체 3 미만은 0 또는 3으로 대체, 그 이상 최대 ±7(사업체 ±4) 잡음. 통계 없음은 0이 아닙니다.') if grid500 else None,
            'sgis_grid_official':dict(official_grid_meta(db),source='SGIS OpenAPI grid/data.geojson (grid_level_div=500m)') if official else None,
            'selected_sector':serialize(sector) if sector else None,'center':list(sc.center) if sc.center else [127.148,35.8242],'bbox':list(sc.bbox) if sc.bbox else None,'crs':'EPSG:5179','grid_size_m':500,'grid_area_m2':250000,'year':year,'offline_mode':offline_mode(),
            'region':{'code':sc.code,'name':sc.name,'short_name':sc.short,'status':sc.status,'grids':len(ids),'level':_level(db,sc.code)},
        }

@app.get('/api/grids/{grid_id}')
def grid_detail(grid_id:str,year:int=Query(DEFAULT_YEAR,ge=2000,le=2100),region:str|None=Query(None,max_length=10)):
    with Session() as db:
        grid=db.get(Grid,grid_id)
        if not grid:raise HTTPException(404,'격자를 찾을 수 없습니다')
        from .sgis_grid_official import official_codes
        try:code=official_codes(db).get(grid_id)
        except Exception:db.rollback();code=None
        body=serialize(grid);body['properties']=dict(body.get('properties') or {},sgis500_code=code)
        region=region or region_for_grid(db,grid_id)
        _scope(db,region)
        return dict(dashboard(db,grid_id,year,region),grid=body)

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
    # Site centre placed in the 3D view (defaults to the grid centre) and its clockwise rotation.
    site_lon:float|None=Field(default=None,ge=124,le=132)
    site_lat:float|None=Field(default=None,ge=33,le=39)
    site_rotation:float=Field(default=0,ge=0,lt=90)
    # Study region (defaults to the region of grid_id): decides the default 대상지 and the legal-limit basis.
    region:str|None=Field(default=None,max_length=10)
    @model_validator(mode='after')
    def validate_footprint(self):
        if self.building_count*self.footprint_per_building>self.site_area:raise ValueError('건축면적 합계가 부지 면적을 초과합니다')
        if self.building_count*self.footprint_per_building+self.site_area*self.green_ratio>self.site_area:raise ValueError('건축면적과 녹지면적 합계가 부지를 초과합니다')
        if self.households*self.average_household_area>self.building_count*self.footprint_per_building*self.floors:raise ValueError('입력 세대수의 면적 수요가 연면적을 초과합니다')
        return self

def _request_region(db,request):
    region=request.region or region_for_grid(db,request.grid_id)
    _scope(db,region)
    return region

@app.post('/api/scenarios')
def scenario(request:ScenarioInput):
    with Session() as db:
        if request.grid_id and not db.get(Grid,request.grid_id):raise HTTPException(404,'격자를 찾을 수 없습니다')
        region=_request_region(db,request)
        baseline=dashboard(db,request.grid_id,request.year,region);factors=factors_for(db,request.year)
        estimate=baseline.get('baseline_estimate')
        if estimate:
            # No parcel of this grid is observed for 12 months: the plan runs on the region's pooled intensity.
            # "현재" is then the same planned floor area at that average intensity (BAU), not this grid's use.
            params=request.model_dump();gfa=params['building_count']*params['footprint_per_building']*params['floors']
            ratio=gfa/estimate['area_m2'] if estimate['area_m2'] else 0
            scaled=[]
            for row in estimate['monthly']:
                r=dict(row,electricity_kwh=row['electricity_kwh']*ratio if row['electricity_kwh'] is not None else None,gas_kwh=row['gas_kwh']*ratio if row['gas_kwh'] is not None else None)
                e=carbon_kg(r['electricity_kwh'],factors.get('ELECTRICITY'));g=carbon_kg(r['gas_kwh'],factors.get('GAS'))
                scaled.append(dict(r,electricity_carbon_kg=e,gas_carbon_kg=g,carbon_kg=e+g if e is not None and g is not None else None))
            result=scenario_calculation(params,scaled,gfa,factors)
            result['data_class']='ESTIMATED';result['baseline_basis']=estimate['basis']
            result['baseline_estimate']={k:estimate[k] for k in ('basis','label','area_m2','parcels','energy_types')}
            result['assumptions'].insert(0,f"이 격자에는 12개월 관측과 연면적이 모두 있는 지번이 없어 {estimate['label']}(관측 지번 {estimate['parcels']}곳, 연면적 {estimate['area_m2']:,.0f}m²)로 추정했습니다. '현재' 값은 계획 연면적을 그 평균 원단위로 운영할 때의 기준(BAU)입니다.")
        else:
            result=scenario_calculation(request.model_dump(),baseline['baseline_monthly'],baseline['baseline_floor_area_m2'],factors)
            result['baseline_basis']='GRID_OBSERVED' if baseline.get('baseline_scope') else None
        result['baseline_scope']=baseline.get('baseline_scope')
        result['id']=str(uuid.uuid4());result['quality']=(f"{estimate['label']} 기반 추정 (이 격자 관측 없음)" if estimate else '기준 에너지·연면적 부족' if not baseline['baseline_floor_area_m2'] else '공간 매칭된 관측 원단위 기반')
        result['calculations']={key:result[key] for key in ['total_footprint','gross_floor_area','far','bcr','households','population','green_area_m2']}
        result['baseline']={k:baseline.get(k) for k in ['current_far','current_bcr','households','population','gross_floor_area_m2','developable_site_area_m2']}
        result['grid_id']=baseline['selected_sector']['grid_id'] if baseline['selected_sector'] else None
        result['region']=baseline.get('region')
        zoning=_site_zoning_for(db,request,result['grid_id'],region)
        if zoning:
            from .zoning_limits import check_plan
            zoning['check']=check_plan(zoning,bcr=result.get('bcr'),far=result.get('far'),site_area_m2=request.site_area,households=request.households)
            result['legal_status']=zoning['check']['label']
        else:result['legal_status']='법적 상한 미확정'
        result['zoning_check']=zoning
        db.add(Scenario(id=result['id'],inputs=dict(request.model_dump(),grid_id=result['grid_id'],region=region)));db.flush();db.add(ScenarioResult(id=result['id'],result=result));db.commit();return result

def _site_zoning_for(db,request,grid_id,region=None):
    """용도지역 parts of the planned site: the placed centre, else the grid centre. None when nothing is known."""
    from .zoning_limits import grid_center_lonlat,site_zoning
    if request.site_lon is not None and request.site_lat is not None:center=(request.site_lon,request.site_lat)
    else:center=grid_center_lonlat(db,grid_id) if grid_id else None
    if not center:return None
    zoning=site_zoning(db,center[0],center[1],request.site_area,request.site_rotation,region_code=region)
    zoning['site_basis']='SITE' if request.site_lon is not None else 'GRID_CENTER'
    return zoning

@app.get('/api/zoning/site')
def zoning_site(lon:float=Query(...,ge=124,le=132),lat:float=Query(...,ge=33,le=39),site_area:float=Query(...,gt=0,le=250000),rotation:float=Query(0,ge=0,lt=90),
                bcr:float|None=Query(None,ge=0,le=100),far:float|None=Query(None,ge=0,le=5000),households:int|None=Query(None,ge=0),region:str|None=Query(None,max_length=10)):
    """용도지역 and 상한 (지역 조례 → 시행령 → 국토계획법 제79조) for a square site; with bcr/far the 1st-pass check as well."""
    from .zoning_limits import check_plan,site_zoning
    with Session() as db:
        zoning=site_zoning(db,lon,lat,site_area,rotation,region_code=region)
        if bcr is not None or far is not None:zoning['check']=check_plan(zoning,bcr=bcr,far=far,site_area_m2=site_area,households=households)
        return zoning

class OptimizationInput(ScenarioInput):
    min_households:int=Field(default=500,ge=0,le=100000)
    min_population:int=Field(default=1000,ge=0,le=1000000)

@app.post('/api/optimize')
def optimization(request:OptimizationInput):
    from .modeling import optimize
    with Session() as db:
        region=_request_region(db,request)
        baseline=dashboard(db,request.grid_id,request.year,region)
        grid_id=baseline['selected_sector']['grid_id'] if baseline['selected_sector'] else None
        zoning=_site_zoning_for(db,request,grid_id,region)
        legal={}
        if zoning and zoning.get('status')=='OK':legal={'legal_far_limit':zoning['far_limit'],'legal_bcr_limit':zoning['bcr_limit']}
        estimate=baseline.get('baseline_estimate')
        monthly_base,area_base=(estimate['monthly'],estimate['area_m2']) if estimate else (baseline['baseline_monthly'],baseline['baseline_floor_area_m2'])
        result=optimize(request.model_dump(),monthly_base,area_base,factors_for(db,request.year),legal)
        if estimate:result['baseline_basis']=estimate['basis'];result['baseline_estimate']={k:estimate[k] for k in ('basis','label','area_m2','parcels','energy_types')}
        if legal:
            source_name=(zoning.get('source') or {}).get('name') or '조례'
            basis_text={'DECREE':'국토계획법 시행령 상한','MIXED':f'{source_name}·시행령 상한'}.get(zoning.get('basis'),f'{source_name} 기본 상한')
            limit_text=f"{basis_text}(건폐율 {legal['legal_bcr_limit']:g}%·용적률 {legal['legal_far_limit']:g}%)"
            if (zoning.get('special') or {}).get('greenbelt'):result['legal_status']=f"개발제한구역 포함 대지 — 건축 원칙적 제한 (참고로 {limit_text} 적용)"
            elif result.get('status')=='ENERGY_OPTIMAL':result['legal_status']=f"{limit_text} 안의 후보만 탐색 / 인허가 판단 아님"
            elif result.get('status')=='NO_FEASIBLE_CANDIDATES':
                # The largest capacity the limit allows on this site, so the user knows how far to relax the targets.
                max_gfa=request.site_area*legal['legal_far_limit']/100
                max_households=int(max_gfa/request.average_household_area)
                result['legal_status']=f"{limit_text} 적용"
                result['reason']=(f"{limit_text} 안에서는 최소 세대수 {request.min_households:,}·인구 {request.min_population:,} 조건을 만족하는 후보가 없습니다. "
                                  f"이 대지(대지면적 {request.site_area:,.0f}m², 평균 세대면적 {request.average_household_area:g}m²)의 상한 연면적은 약 {max_gfa:,.0f}m², 최대 약 {max_households:,}세대입니다. "
                                  "최소 세대수를 낮추거나 대지면적·평균 세대면적을 바꿔 보세요.")
                result['max_households_under_limit']=max_households
        result['zoning_check']=zoning
        result['baseline_scope']=baseline.get('baseline_scope')
        result['region']=baseline.get('region')
        sid=str(uuid.uuid4());db.add(Scenario(id=sid,inputs=dict(request.model_dump(),type='OPTIMIZATION',region=region)));db.flush();db.add(ScenarioResult(id=sid,result=result));db.commit();return result

@app.get('/api/model')
def models(year:int=Query(DEFAULT_YEAR,ge=2000,le=2100),region:str|None=Query(None,max_length=10)):
    from .model_service import model_status
    with Session() as db:return model_status(db,year,region=_scope(db,region).code)

@app.get('/api/scenarios')
def scenario_history():
    with Session() as db:
        images={row for row in db.scalars(select(ScenarioImage.scenario_id))}
        return [dict(serialize(s),result=db.get(ScenarioResult,s.id).result if db.get(ScenarioResult,s.id) else None,has_image=s.id in images) for s in db.scalars(select(Scenario).order_by(Scenario.created_at.desc()).limit(30))]

class ScenarioImageInput(BaseModel):
    data_url:str=Field(min_length=32,max_length=6_000_000)

@app.put('/api/scenarios/{scenario_id}/image')
def put_scenario_image(scenario_id:str,request:ScenarioImageInput):
    """Store the browser's PNG of the 3D concept massing for a saved scenario (replaces an older one)."""
    import base64,binascii
    prefix='data:image/png;base64,'
    if not request.data_url.startswith(prefix):raise HTTPException(422,'PNG data URL만 받습니다')
    try:png=base64.b64decode(request.data_url[len(prefix):],validate=True)
    except (binascii.Error,ValueError):raise HTTPException(422,'이미지 인코딩 오류') from None
    if not png.startswith(b'\x89PNG'):raise HTTPException(422,'PNG가 아닙니다')
    with Session() as db:
        if not db.get(Scenario,scenario_id):raise HTTPException(404,'시나리오를 찾을 수 없습니다')
        row=db.get(ScenarioImage,scenario_id) or ScenarioImage(scenario_id=scenario_id,png=png)
        row.png=png;row.created_at=now();db.add(row);db.commit()
        return {'scenario_id':scenario_id,'bytes':len(png)}

@app.get('/api/scenarios/{scenario_id}/image')
def get_scenario_image(scenario_id:str):
    from fastapi.responses import Response
    with Session() as db:
        row=db.get(ScenarioImage,scenario_id)
        if not row:raise HTTPException(404,'저장된 3D 장면이 없습니다')
        return Response(row.png,media_type='image/png',headers={'Cache-Control':'private, max-age=60'})

@app.post('/api/model/validate')
def validate_models(year:int=Query(DEFAULT_YEAR,ge=2000,le=2100),region:str|None=Query(None,max_length=10)):
    from .model_service import model_status
    with Session() as db:return model_status(db,year,train=True,region=_scope(db,region).code)

@app.get('/api/system')
def system(region:str|None=Query(None,max_length=10)):
    from .regions import StudyRegion,short_name
    from .service import region_sector
    with Session() as db:
        try:sc=_scope(db,region)
        except HTTPException:sc=_scope(db,None)
        sector=region_sector(db,sc)
        default_grid=sector.grid_id if sector else None
        from .regions import detail_level
        try:prepared=[{'code':r.code,'name':r.name,'short_name':short_name(r.name),'status':r.status,'level':detail_level(r),'grid_count':r.grid_count,'default_grid_id':r.default_grid_id}
                      for r in db.scalars(select(StudyRegion).order_by(StudyRegion.code)) if r.grid_count]
        except Exception:db.rollback();prepared=[]
    return {'offline_mode':offline_mode(),'baseline_year':DEFAULT_YEAR,'version':app.version,'default_grid_id':default_grid,
            'default_region':DEFAULT_REGION,'region':{'code':sc.code,'name':sc.name,'short_name':sc.short,'center':list(sc.center) if sc.center else None},'regions':prepared}

class OfflineInput(BaseModel):
    enabled:bool

@app.post('/api/system/offline')
def set_offline(request:OfflineInput):
    flag=DATA/'offline.flag'
    if request.enabled:flag.write_text('Use verified local DB and cache only.\n',encoding='utf-8')
    else:flag.unlink(missing_ok=True)
    return system(None)
