"""Reproducible calculations, conservative model gating and constrained enumeration."""
import math
from statistics import mean
from .domain import scenario_calculation

def validation_metrics(actual,predicted):
    pairs=[(float(a),float(p)) for a,p in zip(actual,predicted) if a is not None and p is not None]
    if not pairs:return {k:None for k in ['mae','rmse','r2','nmae','smape']}
    a,p=zip(*pairs);error=[abs(x-y) for x,y in pairs];m=mean(a)
    sse=sum((x-y)**2 for x,y in pairs);sst=sum((x-m)**2 for x in a)
    return dict(mae=mean(error),rmse=math.sqrt(sse/len(a)),r2=1-sse/sst if sst else None,nmae=mean(error)/abs(m) if m else None,smape=mean(2*abs(x-y)/(abs(x)+abs(y)) if abs(x)+abs(y)>0 else 0 for x,y in pairs))

def model_eligibility(rows):
    grids={r.get('grid_id') for r in rows if r.get('grid_id')}
    blocks={r.get('spatial_block') for r in rows if r.get('spatial_block') is not None}
    periods={r.get('use_ym') for r in rows}
    ready=len(rows)>=120 and len(grids)>=10 and len(blocks)>=3 and len(periods)>=10
    return dict(status='READY_FOR_SPATIAL_VALIDATION' if ready else 'INSUFFICIENT_TRAINING_DATA',validated=False,observations=len(rows),grid_count=len(grids),spatial_blocks=len(blocks),months=len(periods),requirements={'observations':120,'grids':10,'spatial_blocks':3,'months':10},limitations=['지리적 일반화 검증을 위한 최소 표본 규칙입니다. 이 조건 자체가 정확도를 보장하지 않습니다.'])

def fit_candidates(rows):
    """Out-of-fold metrics only; target is intensity, metrics back-transformed to kWh."""
    eligibility=model_eligibility(rows)
    if eligibility['status']!='READY_FOR_SPATIAL_VALIDATION':return dict(eligibility,models=[])
    import numpy as np
    from sklearn.model_selection import GroupKFold
    from sklearn.linear_model import ElasticNet,Ridge
    from sklearn.ensemble import RandomForestRegressor,HistGradientBoostingRegressor
    from sklearn.preprocessing import StandardScaler,SplineTransformer
    from sklearn.pipeline import make_pipeline
    features=['month_sin','month_cos']
    for feature in ['hdd','cdd','households','age','floors','far','bcr','population']:
        if all(r.get(feature) is not None for r in rows):features.append(feature)
    x=np.asarray([[r[f] for f in features] for r in rows],dtype=float)
    area=np.asarray([r['floor_area_m2'] for r in rows]);y=np.asarray([r['usage_kwh'] for r in rows])/area
    groups=np.asarray([r['spatial_block'] for r in rows]);splitter=GroupKFold(n_splits=min(5,len(set(groups))))
    specifications={
        'Intensity baseline':None,
        'ElasticNet':lambda:make_pipeline(StandardScaler(),ElasticNet(alpha=.01,l1_ratio=.5,max_iter=10000,random_state=42)),
        'RandomForestRegressor':lambda:RandomForestRegressor(n_estimators=100,max_depth=6,min_samples_leaf=5,random_state=42,n_jobs=1),
        'HistGradientBoostingRegressor':lambda:HistGradientBoostingRegressor(max_iter=100,max_leaf_nodes=15,l2_regularization=1,random_state=42),
        'Additive spline Ridge':lambda:make_pipeline(SplineTransformer(n_knots=4,degree=2),Ridge(alpha=10)),
    }
    models=[]
    for name,build in specifications.items():
        prediction=np.empty(len(rows));folds=[]
        for train,test in splitter.split(x,y,groups):
            if build is None:
                monthly={month:mean(y[i] for i in train if rows[i]['use_ym'][-2:]==month) for month in {rows[i]['use_ym'][-2:] for i in train}}
                pred=np.array([monthly.get(rows[i]['use_ym'][-2:],float(np.mean(y[train]))) for i in test])
            else:
                estimator=build();estimator.fit(x[train],y[train]);pred=estimator.predict(x[test])
            prediction[test]=np.maximum(pred,0)*area[test]
            folds.append({'train_rows':len(train),'test_rows':len(test),'test_blocks':sorted(set(groups[test].tolist()))})
        models.append(dict(name=name,features=['floor_area_m2']+features,validation_method='Spatial Block Cross Validation / 2km blocks',metrics=validation_metrics([r['usage_kwh'] for r in rows],prediction.tolist()),folds=folds,observations=len(rows),limitations=['고정 하이퍼파라미터. 검증결과는 공간 분할된 기존 표본 내 성능이며 미래 시점 성능은 검증하지 않았습니다.']))
    return dict(eligibility,status='SPATIALLY_EVALUATED',validated=True,models=models)

def optimize(params,baseline,baseline_floor_area,factors,legal=None):
    legal=legal or {}
    known_e=sum(r.get('electricity_kwh') is not None for r in baseline)
    known_g=sum(r.get('gas_kwh') is not None for r in baseline)
    if not baseline_floor_area or max(known_e,known_g)<12:
        return dict(status='INSUFFICIENT_BASELINE_DATA',alternatives=[],evaluated=0,feasible=0,reason='공간 매칭된 연면적과 적어도 한 에너지원의 12개월 관측이 필요합니다.',legal_status='법적 상한 미확정')
    complete_carbon=known_e==12 and known_g==12 and bool(factors.get('ELECTRICITY')) and bool(factors.get('GAS'))
    objective='ANNUAL_OPERATIONAL_CARBON' if complete_carbon else ('ANNUAL_ENERGY' if known_e==known_g==12 else ('ELECTRICITY_ONLY' if known_e==12 else 'GAS_ONLY'))
    site=params['site_area'];footprint=params['footprint_per_building'];green=params.get('green_ratio',0)
    max_count=min(80,int(site*(1-green)/footprint));max_floor=min(40,int(legal.get('max_floors') or 40))
    household_area=params.get('average_household_area',85)
    persons_per_household=params['population']/params['households'] if params.get('households') else 2.5
    candidates=[];evaluated=0
    for count in range(1,max_count+1):
        for floors in range(3,max_floor+1):
            evaluated+=1;gfa=count*footprint*floors;far=gfa/site*100;bcr=count*footprint/site*100
            households=int(gfa/household_area);population=int(households*persons_per_household)
            if households<params.get('min_households',0) or population<params.get('min_population',0):continue
            if legal.get('legal_far_limit') is not None and far>legal['legal_far_limit']:continue
            if legal.get('legal_bcr_limit') is not None and bcr>legal['legal_bcr_limit']:continue
            inputs=dict(params,building_count=count,floors=floors,households=households,population=population)
            result=scenario_calculation(inputs,baseline,baseline_floor_area,factors);annual=result['annual']['scenario']
            score=annual['carbon_kg'] if complete_carbon else (annual['electricity_kwh']+annual['gas_kwh'] if objective=='ANNUAL_ENERGY' else annual['electricity_kwh'] if objective=='ELECTRICITY_ONLY' else annual['gas_kwh'])
            if score is None:continue
            candidates.append(dict(floors=floors,building_count=count,far=far,bcr=bcr,gross_floor_area=gfa,households=households,population=population,annual_energy_kwh=annual['electricity_kwh']+annual['gas_kwh'] if annual['electricity_kwh'] is not None and annual['gas_kwh'] is not None else None,annual_electricity_kwh=annual['electricity_kwh'],annual_gas_kwh=annual['gas_kwh'],annual_carbon_kg=annual['carbon_kg'],carbon_per_person=annual['carbon_kg']/population if annual['carbon_kg'] is not None and population else None,carbon_per_m2=annual['carbon_kg']/gfa if annual['carbon_kg'] is not None else None,objective_value=score,objective_per_household=score/households if households else None,method='INTENSITY_ESTIMATE',inputs=inputs))
    if not candidates:return dict(status='NO_FEASIBLE_CANDIDATES',alternatives=[],evaluated=evaluated,feasible=0,reason='입력한 수용량·건축면적 조건을 만족하는 후보가 없습니다.',legal_status='법적 상한 미확정')
    lowest=min(candidates,key=lambda c:(c['objective_value'],c['building_count'],c['floors']))
    per_household=min(candidates,key=lambda c:(c['objective_per_household'] if c['objective_per_household'] is not None else float('inf'),c['objective_value'],c['building_count'],c['floors']))
    # A transparent capacity alternative, not an unexplained weighted "optimal" score.
    balance=max([c for c in candidates if c['objective_value']<=lowest['objective_value']*1.2],key=lambda c:(c['households'],-c['objective_value'],-c['building_count']))
    alternatives=[]
    for label,row in [('탄소 최소' if complete_carbon else '확보 에너지 최소',lowest),('세대당 탄소 최소' if complete_carbon else '세대당 확보 에너지 최소',per_household),('20% 목적값 범위 내 수용량 최대',balance)]:
        alternatives.append(dict(row,label=label,explanation=f"세대수 {params.get('min_households',0)} 이상·인구 {params.get('min_population',0)} 이상 조건을 만족하는 {len(candidates)}개 후보 중 선택. 목적함수: {objective}."))
    return dict(status='ENERGY_OPTIMAL',method='DETERMINISTIC_GRID_SEARCH',objective=objective,alternatives=alternatives,evaluated=evaluated,feasible=len(candidates),legal_status='입력된 검증 상한만 적용 / 법적 적합성 종합판정 아님' if legal else '법적 상한 미확정',assumptions=['평균 세대면적은 공용면적을 포함하는 수용량 계산용 연면적 가정입니다.','선형 원단위 모델에서는 세대당 에너지 목적값이 동률일 수 있습니다. 동률은 총량·동수·층수 순으로 결정합니다.','각 후보의 녹지면적과 건축면적 합계가 개발가능 부지를 초과하지 않도록 제한합니다.','누락된 에너지원은 목적함수에서 제외되며 전체 운영탄소 최적이라는 의미가 아닙니다.'])
