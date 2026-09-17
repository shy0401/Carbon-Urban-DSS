"""Local administrative commands. Never prints environment or credential values."""
import argparse,json,hashlib
from pathlib import Path
from sqlalchemy import select,func,text
from .db import Base,engine,Session
from .models import DataSource,Grid,Building,Region,WeatherMonthly,EnergyMonthly,TestbedSector,RawDataAsset,ModelRun
from .catalog import seed_sources
from .settings import DATA_DIR,DEFAULT_YEAR

def init_tables():
    from . import official,kapt,kapt_energy,kma_asos,sgis,vworld
    try:from . import imports
    except ImportError:pass
    with engine.begin() as c:c.execute(text('CREATE EXTENSION IF NOT EXISTS postgis'))
    Base.metadata.create_all(engine)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['demo','online','status','enrich','collect','validate-models','snapshot']);parser.add_argument('--year',type=int,default=DEFAULT_YEAR)
    parser.add_argument('--source',choices=['energy','weather','kapt-energy','kma','sgis','vworld-zoning','vworld-cadastral'])
    parser.add_argument('--scope',choices=['smoke','limited','full'],default='smoke')
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
            for label,fn in [('register',lambda:collect_register(db)),('KMA',lambda:collect_kma(db,args.year))]:
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
            datasets=[aliases.get(args.source,args.source)] if args.source else ['energy','weather']
            job=queue_collection(db,datasets,f'{args.year}-01',f'{args.year}-12',args.scope);print('job',job.id,job.status)
        elif args.command=='validate-models':
            from .model_service import model_status
            print(json.dumps(model_status(db,args.year,train=True),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
