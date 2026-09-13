"""Pure calculations. Unknown values remain unknown throughout the pipeline."""
import calendar
import json
import math
import xml.etree.ElementTree as ET
from collections import defaultdict

def number(value):
    if value is None or str(value).strip() in ('','-','null','None'):
        return None
    try:
        n=float(str(value).replace(',',''))
        return n if math.isfinite(n) and n>=0 else None
    except (ValueError,TypeError):
        return None

def parse_energy(body: bytes):
    text=body.decode('utf-8-sig').strip()
    if not text:
        raise ValueError('EMPTY_RESPONSE: API 빈 응답')
    if text.startswith('{'):
        root=json.loads(text)
        root=root.get('response',root)
        header=root.get('header',{})
        code=str(header.get('resultCode','00'))
        if code not in ('00','0','000'):
            raise ValueError(f"{code}: {header.get('resultMsg','API 오류')}")
        data=root.get('body',{})
        items=data.get('items') or {}
        rows=items if isinstance(items,list) else items.get('item',[])
        if isinstance(rows,dict): rows=[rows]
        total=int(data.get('totalCount',len(rows or [])))
    else:
        root=ET.fromstring(text)
        code=root.findtext('.//returnReasonCode') or root.findtext('.//resultCode') or '00'
        if code not in ('00','0','000'):
            raise ValueError(f"{code}: {root.findtext('.//errMsg') or root.findtext('.//resultMsg') or 'API 오류'}")
        rows=[{child.tag:child.text for child in item} for item in root.findall('.//item')]
        total=int(root.findtext('.//totalCount') or len(rows))
        if root.tag not in ('response','OpenAPI_ServiceResponse'):
            raise ValueError('INVALID_RESPONSE: 예상하지 못한 XML 응답')
    return [dict(r,usage_kwh=number(r.get('useQty'))) for r in rows or []],total

def nullable_sum(values):
    known=[v for v in values if v is not None]
    return sum(known) if known else None

def month_range(start,end):
    a=int(start.replace('-',''));b=int(end.replace('-',''))
    result=[]
    while a<=b:
        result.append(str(a));y,m=divmod(a,100)
        a=(y+1)*100+1 if m==12 else a+1
    return result

def monthly_weather(payload):
    daily=payload['daily'];groups=defaultdict(list)
    for i,date in enumerate(daily['time']): groups[date[:7]].append(i)
    result=[]
    for ym,indexes in sorted(groups.items()):
        def vals(key): return [daily[key][i] for i in indexes if daily[key][i] is not None]
        means=vals('temperature_2m_mean');mins=vals('temperature_2m_min');maxs=vals('temperature_2m_max');rain=vals('precipitation_sum')
        result.append(dict(use_ym=ym.replace('-',''),mean_temperature=sum(means)/len(means) if means else None,min_temperature=min(mins) if mins else None,max_temperature=max(maxs) if maxs else None,precipitation=sum(rain) if len(rain)==len(indexes) else None,hdd=sum(max(18-t,0) for t in means) if len(means)==len(indexes) else None,cdd=sum(max(t-18,0) for t in means) if len(means)==len(indexes) else None,days_observed=len(means),expected_days=calendar.monthrange(int(ym[:4]),int(ym[5:]))[1]))
    return result

def carbon_kg(kwh,factor):
    if kwh is None or not factor: return None
    if factor['factor_unit']!='kgCO2eq/kWh': raise ValueError('Unsupported factor unit')
    return kwh*factor['factor']

def scenario_calculation(params,baseline,baseline_floor_area,factors):
    footprint=params['building_count']*params['footprint_per_building']
    gfa=footprint*params['floors']
    monthly=[]
    for row in baseline:
        current={k:row.get(k) for k in ['electricity_kwh','gas_kwh','carbon_kg']}
        sc={}
        for key in ['electricity_kwh','gas_kwh']:
            ratio=gfa/baseline_floor_area if baseline_floor_area and baseline_floor_area>0 else None
            value=current[key]
            sc[key]=value*ratio*params['efficiency_factor']*(1-params['pv_ratio'] if key=='electricity_kwh' else 1) if value is not None and ratio is not None else None
        e=carbon_kg(sc['electricity_kwh'],factors.get('ELECTRICITY'));g=carbon_kg(sc['gas_kwh'],factors.get('GAS'))
        sc['carbon_kg']=e+g if e is not None and g is not None else None
        monthly.append(dict(use_ym=row['use_ym'],current=current,scenario=sc,difference={k:sc[k]-current[k] if sc[k] is not None and current[k] is not None else None for k in sc}))
    annual={side:{k:nullable_sum(row[side][k] for row in monthly) for k in ['electricity_kwh','gas_kwh','carbon_kg']} for side in ['current','scenario','difference']}
    decomposition={}
    for key in ['electricity_kwh','gas_kwh']:
        value=annual['current'][key]
        if value is not None and baseline_floor_area:
            scaled=value*gfa/baseline_floor_area
            efficient=scaled*params['efficiency_factor']
            decomposition[key]={'area_change':scaled-value,'efficiency_change':efficient-scaled,'pv_change':-efficient*params['pv_ratio'] if key=='electricity_kwh' else 0,'weather_change':0,'scope':'관측 월별 계절성 유지. 독립 기상 인과효과로 해석할 수 없음.'}
    percent_change={key:(annual['difference'][key]/annual['current'][key]*100 if annual['current'][key] not in (None,0) and annual['difference'][key] is not None else None) for key in annual['current']}
    # Partial observed-period totals remain useful but must not masquerade as annual totals.
    coverage={k:sum(row['current'][k] is not None for row in monthly) for k in annual['current']}
    period_totals={side:dict(values) for side,values in annual.items()}
    for key,count in coverage.items():
        if count<12:
            for side in annual:annual[side][key]=None
            percent_change[key]=None
    return dict(label='원단위 기반 1차 추정',method='INTENSITY_ESTIMATE',data_class='SCENARIO',total_footprint=footprint,gross_floor_area=gfa,far=gfa/params['site_area']*100,bcr=footprint/params['site_area']*100,households=params.get('households'),population=params.get('population'),green_area_m2=params['site_area']*params.get('green_ratio',0),monthly=monthly,annual=annual,observed_period_totals=period_totals,coverage_months=coverage,percent_change=percent_change,decomposition=decomposition,baseline_floor_area_m2=baseline_floor_area,carbon_per_person=annual['scenario']['carbon_kg']/params['population'] if annual['scenario']['carbon_kg'] is not None and params.get('population') else None,carbon_per_m2=annual['scenario']['carbon_kg']/gfa if annual['scenario']['carbon_kg'] is not None and gfa else None,assumptions=['FAR 산정 연면적은 입력 지상층 연면적으로 가정합니다. 지하층·법정 제외면적 미반영.','기준 월별 실측 원단위의 계절성을 그대로 적용합니다. 별도 기상 회귀·AI 학습 없음.','PV 비율은 전기 수요 상쇄율 가정이며 설비 발전량 예측이 아닙니다.','기준 면적과 에너지의 지번 매칭이 확보된 경우에만 추정합니다.','녹지비율은 공간 제약에 적용하며 검증되지 않은 냉방 저감 효과를 에너지에 곱하지 않습니다.'])
