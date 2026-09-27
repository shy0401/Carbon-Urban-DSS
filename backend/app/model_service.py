import math,uuid
from collections import defaultdict
from sqlalchemy import select
from .models import EnergyMonthly,ModelRun
from .modeling import fit_candidates,model_eligibility

FEATURE_LABELS={'floor_area_m2':'연면적(분모)','month_sin':'월(계절)','month_cos':'월(계절)','hdd':'난방도일 HDD','cdd':'냉방도일 CDD',
                'area_per_household':'세대당 연면적','age':'사용승인 후 경과연수'}


def _approval_year(value):
    text=str(value or '')[:4]
    return int(text) if text.isdigit() and 1900<int(text)<2100 else None


def model_rows(db,year,typ,region=None):
    """Grid-month rows for spatial validation, with the same parcel rule as the map intensities.

    Per grid only the K-apt parcels observed in all 12 months count, their published floor area must
    pass ``floor_area_status`` (e.g. 152,757,779 m² for one complex is a typing error), and for
    electricity the per-household consumption must be plausible (a meter that covers only the common
    areas is left out). Energy and floor area of a grid come from exactly those parcels in every month,
    so the intensity is never "all parcels ÷ some areas".

    Grid features describe the same parcels: floor area per household (unit size) and years since
    approval (floor-area weighted). Nothing is filled in: a grid without the value leaves that
    feature out of the comparison (``fit_candidates`` uses a feature only when every row has it).
    """
    from .grid_metrics import electricity_plausibility,validated_complex_areas,MONTHS_PER_YEAR
    from .kapt import ApartmentComplex
    from .regions import DEFAULT_REGION,scope,weather_rows
    sc=scope(db,region)
    complexes={c.kapt_code:c for c in db.scalars(select(ApartmentComplex)) if sc.owns_complex(c.bjd_code,c.grid_id)}
    areas,_=validated_complex_areas(complexes.values())
    within=EnergyMonthly.use_ym.between(f'{year}01',f'{year}12')
    clause=sc.legal_clause(EnergyMonthly.sigungu_code)
    if clause is not None:within=within & clause
    parcels=defaultdict(dict)
    for grid,ym,kwh,raw in db.execute(select(EnergyMonthly.grid_id,EnergyMonthly.use_ym,EnergyMonthly.usage_kwh,EnergyMonthly.raw_record)
                                      .where(within,EnergyMonthly.energy_type==typ,EnergyMonthly.grid_id.is_not(None),EnergyMonthly.usage_kwh.is_not(None))):
        code=(raw or {}).get('kapt_code')
        if code and code in complexes:
            months=parcels[(grid,code)];months[ym]=months.get(ym,0.0)+float(kwh)
    chosen=defaultdict(list)
    for (grid,code),months in parcels.items():
        area=areas.get(code);info=complexes.get(code)
        if len(months)<MONTHS_PER_YEAR or not area:
            continue
        if typ=='ELECTRICITY' and electricity_plausibility(sum(months.values()),info.households if info else None)[0]=='SUSPECT':
            continue
        chosen[grid].append((months,float(area),info))
    weather={r.use_ym:r for r in weather_rows(db,sc.code,f'{year}01',f'{year}12')}
    rows=[]
    for grid,items in sorted(chosen.items()):
        area=sum(a for _,a,_ in items)
        with_households=[(a,i.households) for _,a,i in items if i and i.households and i.households>0]
        per_household=round(sum(a for a,_ in with_households)/sum(h for _,h in with_households),1) if len(with_households)==len(items) else None
        dated=[(a,_approval_year(i.approval_date)) for _,a,i in items if i and _approval_year(i.approval_date)]
        age=round(year-sum(a*y for a,y in dated)/sum(a for a,_ in dated),1) if len(dated)==len(items) else None
        parts=grid.split('_')
        block=f'{int(parts[-2])//2000}:{int(parts[-1])//2000}' if len(parts)==3 and parts[-2].isdigit() else None
        for ym in sorted(items[0][0]):
            month=int(ym[-2:]);w=weather.get(ym)
            rows.append(dict(grid_id=grid,spatial_block=block,use_ym=ym,usage_kwh=sum(m[ym] for m,_,_ in items),floor_area_m2=area,parcels=len(items),
                             month_sin=math.sin(2*math.pi*month/12),month_cos=math.cos(2*math.pi*month/12),hdd=w.hdd if w else None,cdd=w.cdd if w else None,
                             area_per_household=per_household,age=age))
    return rows


def model_status(db,year,train=False,region=None):
    from .regions import DEFAULT_REGION,scope
    sc=scope(db,region)
    results=[]
    for typ in ['ELECTRICITY','GAS']:
        rows=model_rows(db,year,typ,sc.code)
        result=fit_candidates(rows) if train else dict(model_eligibility(rows),models=[])
        used=result['models'][0]['features'] if result.get('models') else ['floor_area_m2','month_sin','month_cos']+[f for f in ['hdd','cdd','area_per_household','age'] if rows and all(r.get(f) is not None for r in rows)]
        labels=list(dict.fromkeys(FEATURE_LABELS.get(f,f) for f in used))
        result.update(energy_type=typ,training_period=f'{year}-01 ~ {year}-12',features=labels,
                      unavailable_features=['인구','층수','용적률·건폐율(단지별 공식 값 미연계)','난방방식(전주 단지 97%가 개별난방이라 구분력 없음)' if sc.is_default else '난방방식(구분력 미검토)'],
                      scope='K-apt 공동주택 지번 중 12개월 모두 관측되고 연면적·세대당 전력이 타당한 지번만 (격자별 같은 지번 집합)',
                      method='INTENSITY_ESTIMATE',name='관측 월별 연면적 원단위',validation_method='미검증' if not result['validated'] else 'Spatial Block Cross Validation',metrics=None)
        results.append(result)
    status='SPATIALLY_EVALUATED' if all(r['validated'] for r in results) else ('READY_FOR_SPATIAL_VALIDATION' if all(r['status']=='READY_FOR_SPATIAL_VALIDATION' for r in results) else 'INSUFFICIENT_TRAINING_DATA')
    report={'year':year,'region':sc.code,'region_name':sc.name,'status':status,'models':results,'limitations':['OBSERVED 자료는 모델 출력으로 덮어쓰지 않습니다.','현 단계 시뮬레이션은 월별 관측 원단위만 사용합니다. ML 비교는 참고 검증 결과이며 자동 승격하지 않습니다.']}
    if train:
        row=ModelRun(id=str(uuid.uuid4()),year=year,result=report);db.add(row);db.commit();report['run_id']=row.id
    else:
        latest=latest_run(db,year,sc.code)
        if latest:report['last_validation']=latest.result;report['last_run_id']=latest.id;report['last_run_at']=latest.created_at.isoformat() if latest.created_at else None
    return report


def latest_run(db,year,region=None):
    """Latest validation run of a year for one region (runs stored before regions existed belong to the original one)."""
    from .regions import DEFAULT_REGION
    code=region or DEFAULT_REGION
    try:runs=list(db.scalars(select(ModelRun).where(ModelRun.year==year).order_by(ModelRun.created_at.desc()).limit(50)))
    except AttributeError:  # minimal test double with scalar() only
        run=db.scalar(select(ModelRun).where(ModelRun.year==year).order_by(ModelRun.created_at.desc()));runs=[run] if run else []
    for run in runs:
        if (run.result or {}).get('region',DEFAULT_REGION)==code:return run
    return None
