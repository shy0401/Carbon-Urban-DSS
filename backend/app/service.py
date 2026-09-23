from sqlalchemy import select,func
from .models import *
from .domain import nullable_sum,carbon_kg,month_range

def serialize(row):
    result={}
    for col in row.__table__.columns:
        if col.key=='geom':continue
        value=getattr(row,col.key)
        result[col.key]=value.isoformat() if isinstance(value,datetime) else value
    return result

def factors_for(db,year=2025):
    return {r.energy_type:serialize(r) for r in db.scalars(select(EmissionFactor).where(EmissionFactor.effective_from<=f'{year}-12-31').order_by(EmissionFactor.reference_year,EmissionFactor.effective_from))}

def monthly_energy(db,grid_id=None,year=2025):
    query=select(EnergyMonthly).where(EnergyMonthly.use_ym.between(f'{year}01',f'{year}12'))
    if grid_id: query=query.where(EnergyMonthly.grid_id==grid_id)
    rows=db.scalars(query).all();factors=factors_for(db,year);result=[]
    for ym in month_range(f'{year}-01',f'{year}-12'):
        record={'use_ym':ym}
        for typ,key in [('ELECTRICITY','electricity_kwh'),('GAS','gas_kwh')]:
            values=[r.usage_kwh for r in rows if r.use_ym==ym and r.energy_type==typ]
            record[key]=nullable_sum(values)
            record[typ.lower()+'_records']=len(values)
        e=carbon_kg(record['electricity_kwh'],factors.get('ELECTRICITY'));g=carbon_kg(record['gas_kwh'],factors.get('GAS'))
        record['electricity_carbon_kg']=e;record['gas_carbon_kg']=g
        record['carbon_kg']=e+g if e is not None and g is not None else None
        result.append(record)
    return result

def dashboard(db,grid_id=None,year=2025):
    sector=db.get(TestbedSector,'prototype');selected=serialize(sector) if sector else None
    selected_grid=grid_id or (sector.grid_id if sector else None)
    if grid_id and (not sector or grid_id!=sector.grid_id):
        grid=db.get(Grid,grid_id)
        selected=dict(id=grid_id,grid_id=grid_id,name=f'선택 격자 {grid_id}',area_m2=250000,reason='사용자가 선택한 500m 분석 격자') if grid else None
    monthly=monthly_energy(db,selected_grid,year) if selected_grid else []
    regional=monthly_energy(db,year=year)
    totals={k:nullable_sum(r[k] for r in monthly) for k in ['electricity_kwh','gas_kwh','carbon_kg']}
    coverage={typ:sum(row[key] is not None for row in monthly) for typ,key in [('electricity_months','electricity_kwh'),('gas_months','gas_kwh')]}
    within=EnergyMonthly.use_ym.between(f'{year}01',f'{year}12')
    count=db.scalar(select(func.count()).select_from(EnergyMonthly).where(within));matched=db.scalar(select(func.count()).select_from(EnergyMonthly).where(within,EnergyMonthly.grid_id.is_not(None)))
    meta=sector.metadata_json if sector and selected_grid==sector.grid_id else {}
    area=meta.get('baseline_floor_area_m2') if meta.get('baseline_year')==year else None
    from .grid_metrics import consistent_baseline,grid_energy_intensity
    from .kapt import ApartmentComplex
    observed=db.scalars(select(EnergyMonthly).where(within,EnergyMonthly.grid_id==selected_grid,EnergyMonthly.usage_kwh.is_not(None))).all() if selected_grid else []
    observed_rows=[{'grid_id':o.grid_id,'energy_type':o.energy_type,'use_ym':o.use_ym,'usage_kwh':o.usage_kwh,'kapt_code':(o.raw_record or {}).get('kapt_code'),'matched_gross_floor_area_m2':(o.raw_record or {}).get('matched_gross_floor_area_m2')} for o in observed]
    # Scenario baseline: one fixed parcel set observed in all 12 months, with its own floor area.
    from .grid_metrics import validated_complex_areas
    area_by_code,area_issues=validated_complex_areas(db.scalars(select(ApartmentComplex)))
    base=consistent_baseline(observed_rows,month_range(f'{year}-01',f'{year}-12'),area_by_code) if observed_rows else None
    factors=factors_for(db,year)
    if observed_rows:area=base['area_m2'] if base else None
    baseline_monthly=monthly
    if base:
        baseline_monthly=[]
        for r in base['monthly']:
            e=carbon_kg(r['electricity_kwh'],factors.get('ELECTRICITY'));g=carbon_kg(r['gas_kwh'],factors.get('GAS'))
            baseline_monthly.append(dict(r,electricity_carbon_kg=e,gas_carbon_kg=g,carbon_kg=e+g if e is not None and g is not None else None))
        names={row.kapt_code:row.name for row in db.scalars(select(ApartmentComplex).where(ApartmentComplex.kapt_code.in_(base['parcels']+base['excluded_parcels'])))}
        base['parcel_names']=[names.get(code,code) for code in base['parcels']];base['excluded_names']=[names.get(code,code) for code in base['excluded_parcels']]
    households_by_code={row.kapt_code:row.households for row in db.scalars(select(ApartmentComplex).where(ApartmentComplex.grid_id==selected_grid))} if selected_grid else {}
    intensity=grid_energy_intensity(observed_rows,households_by_code,area_by_code).get(selected_grid,{}) if selected_grid else {}
    observed_codes={row['kapt_code'] for row in observed_rows if row['kapt_code']}
    grid_area_issues=[dict(issue,kapt_code=code) for code,issue in area_issues.items() if code in observed_codes]
    e_int=intensity.get('ELECTRICITY') or {}
    base_totals={k:nullable_sum(r[k] for r in baseline_monthly) for k in ['electricity_kwh','gas_kwh','carbon_kg']} if base else {'electricity_kwh':None,'gas_kwh':None,'carbon_kg':None}
    population=meta.get('population');households=meta.get('households')
    source_rows=[]
    for r in db.scalars(select(DataSource).where(DataSource.status!='REPLACED')):
        s=serialize(r)
        try:
            from .quality import dataset_quality
            s['quality_scores']=dataset_quality(db,r.id,year)
        except ImportError:pass
        source_rows.append(s)
    quality_score={'coverage_score':(coverage['electricity_months']+coverage['gas_months'])/24,'completeness_score':(coverage['electricity_months']+coverage['gas_months'])/24,'temporal_score':(coverage['electricity_months']+coverage['gas_months'])/24,'spatial_match_score':matched/count if count else None}
    known=[v for v in quality_score.values() if v is not None];quality_score['overall']=sum(known)/len(known) if known else None
    return dict(selected_sector=selected,year=year,**totals,current_far=meta.get('observed_current_far'),current_bcr=meta.get('observed_current_bcr'),households=households,population=population,gross_floor_area_m2=area,developable_site_area_m2=meta.get('site_area_m2'),legal_far_limit=None,legal_bcr_limit=None,legal_status='법적 상한 미확정',quality='에너지 실측 확보·공간매칭 필요' if count==0 else '공간매칭된 관측 / 표본 범위 확인',quality_scores=quality_score,monthly=monthly,weather=[serialize(r) for r in db.scalars(select(WeatherMonthly).where(WeatherMonthly.use_ym.between(f'{year}01',f'{year}12')).order_by(WeatherMonthly.use_ym))],sources=source_rows,coverage=dict(**coverage,total_months=12,energy_records=count,matched_records=matched),regional_monthly=regional,regional_totals={k:nullable_sum(r[k] for r in regional) for k in totals},carbon_status='공식 배출계수 확인 필요' if not factors_for(db,year) else '검증된 계수 적용 / 미확보 에너지원은 제외',electricity_carbon_kg=nullable_sum(r.get('electricity_carbon_kg') for r in monthly),gas_carbon_kg=nullable_sum(r.get('gas_carbon_kg') for r in monthly),baseline_floor_area_m2=area,baseline_monthly=baseline_monthly,baseline_scope={k:base[k] for k in ['parcels','parcel_names','energy_types','excluded_parcels','excluded_names','area_m2']} if base else None,floor_area_issues=grid_area_issues,baseline_totals=base_totals,normalized={'energy_kwh_per_m2':(base_totals['electricity_kwh']+base_totals['gas_kwh'])/area if base and area and base_totals['electricity_kwh'] is not None and base_totals['gas_kwh'] is not None else None,'energy_kwh_per_person':(base_totals['electricity_kwh']+base_totals['gas_kwh'])/population if base and population and base_totals['electricity_kwh'] is not None and base_totals['gas_kwh'] is not None else None,'co2eq_kg_per_m2':base_totals['carbon_kg']/area if base and area and base_totals['carbon_kg'] is not None else None,'co2eq_kg_per_person':base_totals['carbon_kg']/population if base and population and base_totals['carbon_kg'] is not None else None,'electricity_kwh_per_m2':e_int.get('kwh_per_m2'),'electricity_matched_floor_area_m2':e_int.get('area_m2'),'electricity_kwh_per_household':e_int.get('kwh_per_household'),'electricity_households':e_int.get('households'),'electricity_complete_parcels':e_int.get('complete_parcels') or 0,'electricity_area_parcels':e_int.get('area_parcels') or 0,'electricity_household_parcels':e_int.get('household_parcels') or 0,'electricity_observed_parcels':e_int.get('observed_parcels') or 0,'electricity_carbon_kg_per_m2':carbon_kg(e_int.get('kwh_per_m2'),factors.get('ELECTRICITY'))},annual_complete={'electricity':coverage['electricity_months']==12,'gas':coverage['gas_months']==12},scope='격자에 좌표 매칭된 관측 지번 합계. 격자 전체 건물의 총소비를 의미하지 않습니다.',observations_label='OBSERVED',metadata_label='CALCULATED')
