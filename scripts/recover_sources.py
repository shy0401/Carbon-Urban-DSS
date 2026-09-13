"""Run inside api with current sources mounted. Preserves cached originals and never retries known invalid keys."""
import json
from pathlib import Path
from sqlalchemy import select
from app.db import Session
from app.models import DataSource
from app.collectors import collect_regions, collect_weather
from app.kapt import collect_kapt, collect_municipal, ApartmentComplex
from app.emissions import collect_factors

results = {}
with Session() as db:
    for name, action in [('regions', lambda: collect_regions(db)), ('weather', lambda: collect_weather(db)),
                         ('jeonju_apartments', lambda: collect_municipal(db)), ('factors', lambda: collect_factors(db))]:
        try:
            action()
            results[name] = {'status':'normalized_from_verified_source'}
        except Exception as exc:
            db.rollback(); results[name] = {'status':'failed','error_type':type(exc).__name__}
        print(name, results[name]['status'], flush=True)
    codes = list(db.scalars(select(ApartmentComplex.kapt_code).order_by(ApartmentComplex.kapt_code)))
    print('kapt: requesting remaining details for', len(codes), 'known complexes; rate limited', flush=True)
    try:
        result = collect_kapt(db, detail_codes=codes, max_details=500)
        results['kapt'] = {key:result[key] for key in ['summary_rows','detail_rows']}
    except Exception as exc:
        db.rollback()
        results['kapt'] = {'error_type':type(exc).__name__, 'status':'partial; stopped at provider error'}
        # Persist successfully acquired detail files; do not retry the failed endpoint.
        result = collect_kapt(db, detail_codes=[])
        results['kapt'].update({key:result[key] for key in ['summary_rows','detail_rows']})
    results['sources'] = [{'id':s.id,'status':s.status,'rows':s.normalized_row_count,'quality':s.quality} for s in db.scalars(select(DataSource))]
target=Path('/data/deployment/source-recovery.json')
target.parent.mkdir(parents=True,exist_ok=True)
target.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in results.items() if k!='sources'},ensure_ascii=False),flush=True)
