import math,uuid
from sqlalchemy import select,func
from .models import EnergyMonthly,TestbedSector,WeatherMonthly,ModelRun,Building
from .modeling import fit_candidates,model_eligibility

def model_rows(db,year,typ):
    """Use only documented energy-matched floor area, not every OSM polygon in a cell."""
    from .scope import matched_areas
    observed=db.scalars(select(EnergyMonthly).where(EnergyMonthly.use_ym.between(f'{year}01',f'{year}12'))).all()
    areas=matched_areas(observed)
    # Kapt collector may save comparable exact parcel-area groups in additional sector records.
    weather={r.use_ym:r for r in db.scalars(select(WeatherMonthly).where(WeatherMonthly.use_ym.between(f'{year}01',f'{year}12')))}
    aggregate=db.execute(select(EnergyMonthly.grid_id,EnergyMonthly.use_ym,func.sum(EnergyMonthly.usage_kwh)).where(EnergyMonthly.energy_type==typ,EnergyMonthly.use_ym.between(f'{year}01',f'{year}12'),EnergyMonthly.usage_kwh.is_not(None),EnergyMonthly.grid_id.is_not(None)).group_by(EnergyMonthly.grid_id,EnergyMonthly.use_ym)).all()
    rows=[]
    for grid,ym,kwh in aggregate:
        if grid not in areas:continue
        parts=grid.split('_')
        block=f'{int(parts[-2])//2000}:{int(parts[-1])//2000}' if len(parts)==3 and parts[-2].isdigit() else None
        month=int(ym[-2:]);w=weather.get(ym)
        rows.append(dict(grid_id=grid,spatial_block=block,use_ym=ym,usage_kwh=kwh,floor_area_m2=areas[grid],month_sin=math.sin(2*math.pi*month/12),month_cos=math.cos(2*math.pi*month/12),hdd=w.hdd if w else None,cdd=w.cdd if w else None))
    return rows

def model_status(db,year,train=False):
    results=[]
    for typ in ['ELECTRICITY','GAS']:
        rows=model_rows(db,year,typ)
        result=fit_candidates(rows) if train else dict(model_eligibility(rows),models=[])
        result.update(energy_type=typ,training_period=f'{year}-01 ~ {year}-12',features=['floor_area_m2','month','HDD','CDD'],unavailable_features=['population','households','building_age','floors','FAR','BCR'],method='INTENSITY_ESTIMATE',name='관측 월별 연면적 원단위',validation_method='미검증' if not result['validated'] else 'Spatial Block Cross Validation',metrics=None)
        results.append(result)
    status='SPATIALLY_EVALUATED' if all(r['validated'] for r in results) else ('READY_FOR_SPATIAL_VALIDATION' if all(r['status']=='READY_FOR_SPATIAL_VALIDATION' for r in results) else 'INSUFFICIENT_TRAINING_DATA')
    report={'year':year,'status':status,'models':results,'limitations':['OBSERVED 자료는 모델 출력으로 덮어쓰지 않습니다.','현 단계 시뮬레이션은 월별 관측 원단위만 사용합니다. ML 비교는 참고 검증 결과이며 자동 승격하지 않습니다.']}
    if train:
        row=ModelRun(id=str(uuid.uuid4()),year=year,result=report);db.add(row);db.commit();report['run_id']=row.id
    else:
        latest=db.scalar(select(ModelRun).where(ModelRun.year==year).order_by(ModelRun.created_at.desc()))
        if latest:report['last_validation']=latest.result;report['last_run_id']=latest.id
    return report
