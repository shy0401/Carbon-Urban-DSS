"""Local administrative commands. Never prints environment or credential values."""
import argparse,json,hashlib
from pathlib import Path
from sqlalchemy import select,func,text
from .db import Base,engine,Session
from .models import DataSource,Grid,Building,Region,WeatherMonthly,EnergyMonthly,TestbedSector,RawDataAsset,ModelRun
from .catalog import seed_sources
from .settings import DATA_DIR,DEFAULT_YEAR

def init_tables():
    from . import official,kapt,kapt_energy,kma_asos,sgis,sgis_grid,vworld,energy_parcels,sgis_grid_official,regions,national,ordinances,sgis_grid500,regional_stats,team_grid,solar
    try:from . import imports
    except ImportError:pass
    with engine.begin() as c:c.execute(text('CREATE EXTENSION IF NOT EXISTS postgis'))
    Base.metadata.create_all(engine)
    from .migrations import apply_migrations
    apply_migrations(engine)
    with Session() as db:
        try:
            from .emissions import ensure_gas_factor
            ensure_gas_factor(db)
        except Exception:db.rollback()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['demo','online','status','enrich','collect','collect-history','collect-missing','validate-models','snapshot','llm-dataset','llm-eval','import-sgis-grid','import-sgis-grid500','import-regional-stats','import-team-grid',
        'national-admin','national-sgis','national-complexes','national-grid500','national-ordinances','national-all','prepare-region','regions',
        'check-standard','apply-standard','backfill-solar']);parser.add_argument('--year',type=int,default=DEFAULT_YEAR)
    parser.add_argument('--from',dest='from_year',type=int,default=2015);parser.add_argument('--to',dest='to_year',type=int,default=DEFAULT_YEAR)
    parser.add_argument('--datasets',default='',help='comma-separated: sgis,kma_asos,kapt_energy,energy,vworld_zoning,vworld_buildings,vworld_cadastral,building_register');parser.add_argument('--force',action='store_true')
    parser.add_argument('--source',choices=['energy','weather','kapt-energy','kma','sgis','vworld-zoning','vworld-cadastral'])
    parser.add_argument('--scope',choices=['smoke','limited','full'],default='smoke')
    parser.add_argument('--region',default=None,help='prepare-region/validate-models: 5-digit 법정 시·군·구 code (e.g. 41110 수원시)')
    parser.add_argument('--steps',default='',help='prepare-region: comma-separated steps (default: all)')
    parser.add_argument('--no-emd',action='store_true',help='national-sgis: 시군구만 (행정동 생략)')
    parser.add_argument('--model',default=None,help='llm-eval: Ollama model name (default OLLAMA_NARRATIVE_MODEL, then OLLAMA_MODEL)');parser.add_argument('--limit',type=int,default=None);parser.add_argument('--file',default=None)
    parser.add_argument('--csv',action='append',default=[],help='check-standard: a CSV table to check before importing (repeatable)')
    args=parser.parse_args();init_tables()
    with Session() as db:
        seed_sources(db)
        if args.command in ('demo','snapshot'):
            from .service import dashboard
            if not db.scalar(select(func.count()).select_from(Grid)):
                from .collectors import collect_regions,collect_spatial,collect_weather
                for fn in [collect_regions,collect_spatial,collect_weather]:fn(db)
            if not db.scalar(select(func.count()).select_from(Grid)):raise SystemExit('No verified local geometry available')
            payload=dashboard(db,year=args.year);path=DATA_DIR/'snapshots';path.mkdir(exist_ok=True)
            (path/f'dashboard-{args.year}.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
            manifest=[]
            for f in sorted((DATA_DIR/'raw').rglob('*')):
                if f.is_file():manifest.append({'file':str(f.relative_to(DATA_DIR)),'sha256':hashlib.sha256(f.read_bytes()).hexdigest(),'bytes':f.stat().st_size})
            (path/'raw-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
            if args.command=='demo':(DATA_DIR/'offline.flag').write_text('Verified local observations only. No outbound API calls.\n',encoding='utf-8')
            print(json.dumps({'status':'prepared','offline_mode':args.command=='demo','raw_files':len(manifest),'energy_records':payload['coverage']['energy_records'],'year':args.year}))
        elif args.command=='online':
            (DATA_DIR/'offline.flag').unlink(missing_ok=True);print('Online collection enabled unless DEMO_OFFLINE_MODE environment forces offline.')
        elif args.command=='status':
            from .service import serialize
            print(json.dumps([serialize(s) for s in db.scalars(select(DataSource))],ensure_ascii=False,indent=2))
        elif args.command=='enrich':
            from .official import collect_register,collect_kma
            for label,fn in [('register',lambda:collect_register(db,'smoke')),('KMA',lambda:collect_kma(db,args.year))]:
                try:print(label,fn())
                except Exception as exc:print(label,'not collected',type(exc).__name__)
            try:
                from .kapt import collect_kapt
                print('Kapt',collect_kapt(db))
            except (ImportError,AttributeError):print('Kapt adapter not installed')
            from .emissions import collect_factors
            print('Factors',collect_factors(db))
        elif args.command=='collect':
            from .tasks import queue_collection
            aliases={'kapt-energy':'kapt_energy','kma':'kma_asos','vworld-zoning':'vworld_zoning','vworld-cadastral':'vworld_cadastral'}
            datasets=[aliases.get(args.source,args.source)] if args.source else ['weather']
            job=queue_collection(db,datasets,f'{args.year}-01',f'{args.year}-12',args.scope);print('job',job.id,job.status)
        elif args.command in ('collect-history','collect-missing'):
            from .history import collect_history
            datasets=[d.strip() for d in args.datasets.split(',') if d.strip()] or None
            result=collect_history(db,args.from_year,args.to_year,datasets=datasets,force=args.force,log=lambda m:print(m,flush=True))
            statuses={}
            for item in result['items'].values():statuses[item['status']]=statuses.get(item['status'],0)+1
            print(json.dumps({'statuses':statuses,'blocked':result['blocked'],'resume_at':result.get('resume_at')},ensure_ascii=False))
        elif args.command=='llm-dataset':
            from .llm_dataset import build_dataset
            print(json.dumps(build_dataset(db,args.from_year,args.to_year,log=lambda m:print(m,flush=True)),ensure_ascii=False))
        elif args.command=='llm-eval':
            from .llm_dataset import evaluate
            print(json.dumps(evaluate(args.file,model=args.model,limit=args.limit,log=lambda m:print(m,flush=True)),ensure_ascii=False))
        elif args.command=='import-sgis-grid':
            from .sgis_grid import import_sgis_grid,meta
            result=import_sgis_grid(db,args.file,force=args.force)
            print(json.dumps(dict(result,loaded={k:meta(db)[k] for k in ('year','cells','stat_rows')}),ensure_ascii=False))
        elif args.command=='import-sgis-grid500':
            # SGIS 500m 격자 통계 (자료제공 신청분): DATA_DIR/raw/sgis_grid_500m/**/<연도>년_<주제>_<블록>_500M.csv
            from .sgis_grid500 import import_sgis_grid500
            result=import_sgis_grid500(db,args.file,force=args.force,log=lambda m:print(m,flush=True))
            print(json.dumps(result,ensure_ascii=False,default=str))
        elif args.command=='import-regional-stats':
            # GIR 지역 온실가스 인벤토리(DATA_DIR/raw/research/gir/regional_*/*.xlsx), 가스공사 시·도 도시가스(DATA_DIR/raw/gas/*.csv)
            from .regional_stats import import_all,row_counts
            result=import_all(db,force=args.force)
            print(json.dumps(dict(result,rows=row_counts(db)),ensure_ascii=False))
        elif args.command=='import-team-grid':
            # 팀 데이터셋(urban-carbon): DATA_DIR/raw/team_urban_carbon/<묶음 날짜>/<5자리 코드>_<도시>/<연도>/grid_500m.csv 등
            from .team_grid import import_team_grid,counts
            result=import_team_grid(db,Path(args.file) if args.file else None,force=args.force,log=lambda m:print(m,flush=True))
            print(json.dumps(dict(result,rows=counts(db)),ensure_ascii=False))
        elif args.command=='validate-models':
            from .model_service import model_status
            print(json.dumps(model_status(db,args.year,train=True,region=args.region),ensure_ascii=False,indent=2))
        elif args.command.startswith('national-'):
            from .regions import ensure_default_region
            from . import national
            ensure_default_region(db)
            say=lambda m:print(m,flush=True)
            steps={'national-admin':['admin'],'national-sgis':['sgis'],'national-complexes':['complexes'],'national-grid500':['grid500'],
                   'national-ordinances':['ordinances'],'national-all':['admin','sgis','complexes','grid500','ordinances']}[args.command]
            for step in steps:
                if step=='admin':result=national.collect_admin_units(db,log=say)
                elif step=='sgis':result=national.collect_national_sgis(db,include_emd=not args.no_emd,log=say)
                elif step=='complexes':result=national.collect_national_complexes(db,log=say)
                elif step=='ordinances':
                    from .ordinances import collect_ordinances
                    result=collect_ordinances(db,[args.region] if args.region else None,force=args.force,log=say)
                else:result=national.collect_national_grid500(db,log=say)
                print(json.dumps({step:result},ensure_ascii=False,default=str),flush=True)
        elif args.command=='prepare-region':
            if not args.region:raise SystemExit('--region 코드가 필요합니다 (예: 41110)')
            from .region_prepare import prepare_region
            from .regions import ensure_default_region
            ensure_default_region(db)
            steps=[s.strip() for s in args.steps.split(',') if s.strip()] or None
            result=prepare_region(db,args.region,steps,log=lambda m:print(m,flush=True),force=args.force)
            print(json.dumps({'code':result['code'],'status':result['status'],'datasets':{k:{'status':v.get('status'),'message':v.get('message')} for k,v in (result['datasets'] or {}).items()}},ensure_ascii=False,indent=1))
        elif args.command=='backfill-solar':
            # ERA5-Land 일사량을 지역마다 받아 태양광 연 발전량 추정에 씀 (docs/DATA_STANDARD.md 5.13)
            from .solar import backfill
            regions=[r.strip() for r in (args.region or '').split(',') if r.strip()] or None
            print(json.dumps(backfill(db,regions=regions,log=lambda m:print(m,flush=True)),ensure_ascii=False,indent=1,default=str))
        elif args.command in ('check-standard','apply-standard'):
            # docs/DATA_STANDARD.md: apply brings stored values to the current rule, check counts what does not follow it.
            from .standard import apply_standard,check_standard
            if args.command=='apply-standard':
                print(json.dumps(apply_standard(db,log=lambda m:print(m,flush=True)),ensure_ascii=False,indent=1,default=str))
            report=check_standard(db,csv_paths=args.csv)
            for item in report['items']:
                print(f"[{item['status']:4}] {item['label']}: {item['detail']}",flush=True)
            print(json.dumps({'version':report['version'],'summary':report['summary'],'ok':report['ok']},ensure_ascii=False))
            if args.command=='check-standard' and not report['ok']:raise SystemExit(1)
        elif args.command=='regions':
            from .regions import StudyRegion,region_summary
            print(json.dumps([region_summary(r) for r in db.scalars(select(StudyRegion))],ensure_ascii=False,indent=1,default=str))

if __name__=='__main__':main()
