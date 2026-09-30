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

def monthly_energy(db,grid_id=None,year=2025,clause=None):
    # Summed in SQL: the city-wide 건축HUB collection holds hundreds of thousands of rows per year.
    # SUM ignores NULL and returns NULL when no value is known, like nullable_sum.
    # ``clause``: SQL condition limiting the rows to one study region (``Scope.legal_clause``).
    query=select(EnergyMonthly.use_ym,EnergyMonthly.energy_type,func.sum(EnergyMonthly.usage_kwh),func.count()).where(EnergyMonthly.use_ym.between(f'{year}01',f'{year}12'))
    if grid_id: query=query.where(EnergyMonthly.grid_id==grid_id)
    if clause is not None: query=query.where(clause)
    sums={(ym,typ):(total,count) for ym,typ,total,count in db.execute(query.group_by(EnergyMonthly.use_ym,EnergyMonthly.energy_type))}
    factors=factors_for(db,year);result=[]
    for ym in month_range(f'{year}-01',f'{year}-12'):
        record={'use_ym':ym}
        for typ,key in [('ELECTRICITY','electricity_kwh'),('GAS','gas_kwh')]:
            total,count=sums.get((ym,typ),(None,0))
            record[key]=float(total) if total is not None else None
            record[typ.lower()+'_records']=int(count)
        e=carbon_kg(record['electricity_kwh'],factors.get('ELECTRICITY'));g=carbon_kg(record['gas_kwh'],factors.get('GAS'))
        record['electricity_carbon_kg']=e;record['gas_carbon_kg']=g
        record['carbon_kg']=e+g if e is not None and g is not None else None
        result.append(record)
    return result

_POOLED={}

def heating_group(heating_type):
    """'district' for 지역난방 (heat bought from a network: little gas), 'individual' otherwise, None when unknown."""
    text=str(heating_type or '').strip()
    if not text or text=='-':return None
    return 'district' if '지역' in text else 'individual'

def grid_heating(complexes):
    """Heating group of a grid from its complexes, weighted by floor area (None: no complex with a known type)."""
    weights={}
    for c in complexes:
        group=heating_group(getattr(c,'heating_type',None));area=getattr(c,'gross_floor_area_m2',None) or 0
        if group:weights[group]=weights.get(group,0)+(area if area>0 else 1)
    if not weights:return None
    return max(weights,key=weights.get)

def pooled_baseline(db,year,sc=None,heating=None):
    """Consistent baseline over every K-apt-linked parcel of a region (``sc``; None = all regions).

    Used when the selected grid has no parcel observed in all 12 months: the plan is then scaled with the
    region's pooled observed intensity (ESTIMATED), never with zeros."""
    from .grid_metrics import consistent_baseline,validated_complex_areas
    from .kapt import ApartmentComplex
    code=EnergyMonthly.raw_record['kapt_code'].as_string()
    query=select(EnergyMonthly.energy_type,EnergyMonthly.use_ym,EnergyMonthly.usage_kwh,code).where(EnergyMonthly.use_ym.between(f'{year}01',f'{year}12'),EnergyMonthly.usage_kwh.is_not(None),code.is_not(None))
    if sc is not None:query=query.where(sc.legal_clause(EnergyMonthly.sigungu_code))
    try:rows=[{'energy_type':t,'use_ym':ym,'usage_kwh':v,'kapt_code':c} for t,ym,v,c in db.execute(query)]
    except Exception:
        db.rollback();return None
    complexes=list(db.scalars(select(ApartmentComplex)))
    if heating:
        # 지역난방 단지는 가스를 거의 쓰지 않는다(수원 2025 중앙값 3.0 vs 개별난방 71.8 kWh/m²): 같은 난방 방식끼리만 평균
        allowed={c.kapt_code for c in complexes if heating_group(c.heating_type)==heating}
        rows=[r for r in rows if r['kapt_code'] in allowed]
    key=(sc.code if sc is not None else '*',year,heating,len(rows),sum(r['usage_kwh'] for r in rows))
    if key in _POOLED:return _POOLED[key]
    areas,_=validated_complex_areas(complexes)
    base=consistent_baseline(rows,month_range(f'{year}-01',f'{year}-12'),areas,{c.kapt_code:c.households for c in complexes}) if rows else None
    if len(_POOLED)>32:_POOLED.clear()
    _POOLED[key]=base
    return base

def baseline_estimate(db,year,sc,factors,grid_id=None):
    """Pooled baseline for a grid without its own: the region first, then every prepared region.

    The pool keeps the grid's heating group (its complexes' 난방방식) when it is known, because a region that mixes
    지역난방 and 개별난방 (수원: 258 vs 188 complexes) has two gas intensities 20× apart."""
    from .regions import DEFAULT_REGION,scope
    from .kapt import ApartmentComplex
    region=sc if sc is not None else scope(db,DEFAULT_REGION)
    heating=grid_heating(db.scalars(select(ApartmentComplex).where(ApartmentComplex.grid_id==grid_id)).all()) if grid_id else None
    mixed=None
    if not heating:
        groups=[heating_group(c.heating_type) for c in db.scalars(select(ApartmentComplex)) if region.owns_complex(c.bjd_code,c.grid_id)]
        known=[g for g in groups if g]
        if known and 0.1<=sum(g=='district' for g in known)/len(known)<=0.9:mixed=True
    for basis,target in (('REGION_POOLED',region),('ALL_REGIONS_POOLED',None)):
        base=pooled_baseline(db,year,target,heating)
        if base:
            monthly=[]
            for r in base['monthly']:
                e=carbon_kg(r['electricity_kwh'],factors.get('ELECTRICITY'));g=carbon_kg(r['gas_kwh'],factors.get('GAS'))
                monthly.append(dict(r,electricity_carbon_kg=e,gas_carbon_kg=g,carbon_kg=e+g if e is not None and g is not None else None))
            label=f'{region.short} 관측 공동주택 평균 원단위' if basis=='REGION_POOLED' else '준비된 모든 지역의 관측 공동주택 평균 원단위'
            if heating:label+=f" ({'지역난방' if heating=='district' else '개별·중앙난방'} 단지끼리)"
            elif mixed:label+=' (지역난방·개별난방 단지가 섞인 평균: 가스는 난방 방식에 따라 크게 다름)'
            return {'basis':basis,'label':label,'area_m2':base['area_m2'],'parcels':len(base['parcels']),'energy_types':base['energy_types'],'monthly':monthly,'data_class':'ESTIMATED',
                    'heating':heating,'heating_mixed':bool(mixed)}
    return None

def region_sector(db,sc):
    """Default 대상지 of a study region: the original testbed sector, or the region's default grid."""
    if sc is None or sc.is_default:
        return db.get(TestbedSector,'prototype')
    if not sc.default_grid_id:return None
    return TestbedSector(id=f'region:{sc.code}',grid_id=sc.default_grid_id,name=f'{sc.short} 기본 대상지',area_m2=250000,
                         reason='지역 준비 때 K-apt 세대수가 가장 많은 격자(없으면 지역 중심 격자)로 정한 기본 대상지',candidates=[],metadata_json={})

def dashboard(db,grid_id=None,year=2025,region=None):
    from .regions import scope,weather_rows
    sc=scope(db,region) if region is not None else None
    sector=region_sector(db,sc);selected=serialize(sector) if sector else None
    selected_grid=grid_id or (sector.grid_id if sector else None)
    if grid_id and (not sector or grid_id!=sector.grid_id):
        grid=db.get(Grid,grid_id)
        selected=dict(id=grid_id,grid_id=grid_id,name=f'선택 격자 {grid_id}',area_m2=250000,reason='사용자가 선택한 500m 분석 격자') if grid else None
    monthly=monthly_energy(db,selected_grid,year) if selected_grid else []
    clause=sc.legal_clause(EnergyMonthly.sigungu_code) if sc else None
    regional=monthly_energy(db,year=year,clause=clause)
    totals={k:nullable_sum(r[k] for r in monthly) for k in ['electricity_kwh','gas_kwh','carbon_kg']}
    coverage={typ:sum(row[key] is not None for row in monthly) for typ,key in [('electricity_months','electricity_kwh'),('gas_months','gas_kwh')]}
    within=EnergyMonthly.use_ym.between(f'{year}01',f'{year}12')
    if clause is not None:within=within & clause
    count=db.scalar(select(func.count()).select_from(EnergyMonthly).where(within));matched=db.scalar(select(func.count()).select_from(EnergyMonthly).where(within,EnergyMonthly.grid_id.is_not(None)))
    meta=(sector.metadata_json or {}) if sector and selected_grid==sector.grid_id else {}
    area=meta.get('baseline_floor_area_m2') if meta.get('baseline_year')==year else None
    from .grid_metrics import consistent_baseline,grid_energy_intensity
    from .kapt import ApartmentComplex
    observed=db.scalars(select(EnergyMonthly).where(within,EnergyMonthly.grid_id==selected_grid,EnergyMonthly.usage_kwh.is_not(None))).all() if selected_grid else []
    observed_rows=[{'grid_id':o.grid_id,'energy_type':o.energy_type,'use_ym':o.use_ym,'usage_kwh':o.usage_kwh,'kapt_code':(o.raw_record or {}).get('kapt_code'),'matched_gross_floor_area_m2':(o.raw_record or {}).get('matched_gross_floor_area_m2')} for o in observed]
    # Scenario baseline: one fixed parcel set observed in all 12 months, with its own floor area.
    from .grid_metrics import validated_complex_areas
    area_by_code,area_issues=validated_complex_areas(db.scalars(select(ApartmentComplex)))
    all_households={row.kapt_code:row.households for row in db.scalars(select(ApartmentComplex))}
    base=consistent_baseline(observed_rows,month_range(f'{year}-01',f'{year}-12'),area_by_code,all_households) if observed_rows else None
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
    estimate=baseline_estimate(db,year,sc,factors,selected_grid) if not base and selected_grid else None
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
    return dict(selected_sector=selected,year=year,**totals,current_far=meta.get('observed_current_far'),current_bcr=meta.get('observed_current_bcr'),households=households,population=population,gross_floor_area_m2=area,developable_site_area_m2=meta.get('site_area_m2'),legal_far_limit=None,legal_bcr_limit=None,legal_status='법적 상한 미확정',quality='에너지 실측 확보·공간매칭 필요' if count==0 else '공간매칭된 관측 / 표본 범위 확인',quality_scores=quality_score,monthly=monthly,weather=[serialize(r) for r in weather_rows(db,sc.code if sc else None,f'{year}01',f'{year}12')],region={'code':sc.code,'name':sc.name,'short_name':sc.short} if sc else None,sources=source_rows,coverage=dict(**coverage,total_months=12,energy_records=count,matched_records=matched),regional_monthly=regional,regional_totals={k:nullable_sum(r[k] for r in regional) for k in totals},carbon_status='공식 배출계수 확인 필요' if not factors else '전력 GIR 승인 계수 · 가스 가정 계수(IPCC 2006)' if (factors.get('GAS') or {}).get('id','').startswith('rule-') else '검증된 계수 적용 / 미확보 에너지원은 제외',electricity_carbon_kg=nullable_sum(r.get('electricity_carbon_kg') for r in monthly),gas_carbon_kg=nullable_sum(r.get('gas_carbon_kg') for r in monthly),baseline_floor_area_m2=area,baseline_monthly=baseline_monthly,baseline_scope={k:base[k] for k in ['parcels','parcel_names','energy_types','excluded_parcels','excluded_names','area_m2']} if base else None,baseline_basis='GRID_OBSERVED' if base else estimate['basis'] if estimate else None,baseline_estimate=estimate,carbon_factors={k:{'factor':v['factor'],'unit':v['factor_unit'],'source':v['source'],'notes':v['notes'],'assumed':v['id'].startswith('rule-')} for k,v in factors.items()},floor_area_issues=grid_area_issues,baseline_totals=base_totals,normalized={'energy_kwh_per_m2':(base_totals['electricity_kwh']+base_totals['gas_kwh'])/area if base and area and base_totals['electricity_kwh'] is not None and base_totals['gas_kwh'] is not None else None,'energy_kwh_per_person':(base_totals['electricity_kwh']+base_totals['gas_kwh'])/population if base and population and base_totals['electricity_kwh'] is not None and base_totals['gas_kwh'] is not None else None,'co2eq_kg_per_m2':base_totals['carbon_kg']/area if base and area and base_totals['carbon_kg'] is not None else None,'co2eq_kg_per_person':base_totals['carbon_kg']/population if base and population and base_totals['carbon_kg'] is not None else None,'electricity_kwh_per_m2':e_int.get('kwh_per_m2'),'electricity_matched_floor_area_m2':e_int.get('area_m2'),'electricity_kwh_per_household':e_int.get('kwh_per_household'),'electricity_households':e_int.get('households'),'electricity_complete_parcels':e_int.get('complete_parcels') or 0,'electricity_area_parcels':e_int.get('area_parcels') or 0,'electricity_household_parcels':e_int.get('household_parcels') or 0,'electricity_observed_parcels':e_int.get('observed_parcels') or 0,'electricity_suspect_parcels':e_int.get('suspect_parcels') or 0,'electricity_carbon_kg_per_m2':carbon_kg(e_int.get('kwh_per_m2'),factors.get('ELECTRICITY'))},annual_complete={'electricity':coverage['electricity_months']==12,'gas':coverage['gas_months']==12},scope='격자에 좌표 매칭된 관측 지번 합계. 격자 전체 건물의 총소비를 의미하지 않습니다.',observations_label='OBSERVED',metadata_label='CALCULATED')
