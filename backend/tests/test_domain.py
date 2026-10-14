import pytest
from app.domain import parse_energy, monthly_weather, carbon_kg, scenario_calculation, nullable_sum

def test_energy_xml_preserves_zero_and_missing():
    body=b'<response><header><resultCode>00</resultCode></header><body><items><item><useQty>0</useQty><useYm>202501</useYm></item><item><useYm>202502</useYm></item></items><totalCount>2</totalCount></body></response>'
    rows,total=parse_energy(body)
    assert total==2
    assert rows[0]['usage_kwh']==0
    assert rows[1]['usage_kwh'] is None

def test_energy_json_single_item_and_gas_units():
    rows,total=parse_energy(b'{"response":{"header":{"resultCode":"00"},"body":{"items":{"item":{"useQty":"1,250.5","useYm":"202501"}},"totalCount":1}}}')
    assert rows[0]['usage_kwh']==1250.5
    assert total==1

def test_auth_error_not_empty_success():
    with pytest.raises(ValueError,match='30'):
        parse_energy(b'<OpenAPI_ServiceResponse><cmmMsgHeader><returnReasonCode>30</returnReasonCode><errMsg>SERVICE_KEY_IS_NOT_REGISTERED_ERROR</errMsg></cmmMsgHeader></OpenAPI_ServiceResponse>')

def test_missing_sum_not_zero():
    assert nullable_sum([None,None]) is None
    assert nullable_sum([0,None])==0

def test_weather_uses_daily_degree_days_and_no_filled_precipitation():
    # DATA_STANDARD 5.10: HDD base 18 °C, CDD base 24 °C, whole months only (a partial month has no degree days).
    days=[f'2025-01-{d:02d}' for d in range(1,32)]
    temps=[10.0]*30+[30.0]
    rows=monthly_weather({'daily':{'time':days,'temperature_2m_mean':temps,'temperature_2m_min':[t-5 for t in temps],'temperature_2m_max':[t+5 for t in temps],'precipitation_sum':[1.0]*31}})
    assert rows[0]['hdd']==30*8
    assert rows[0]['cdd']==6
    assert rows[0]['precipitation']==31
    assert rows[0]['days_observed']==31
    partial=monthly_weather({'daily':{'time':['2025-02-01','2025-02-02'],'temperature_2m_mean':[10,20],'temperature_2m_min':[2,12],'temperature_2m_max':[15,25],'precipitation_sum':[1,2]}})
    assert partial[0]['mean_temperature']==15 and partial[0]['hdd'] is None and partial[0]['cdd'] is None and partial[0]['days_observed']==2

def test_carbon_verified_factor_and_null():
    assert carbon_kg(1000,{'factor':0.4,'factor_unit':'kgCO2eq/kWh'})==400
    assert carbon_kg(1000,None) is None
    assert carbon_kg(None,{'factor':0.4,'factor_unit':'kgCO2eq/kWh'}) is None

def test_scenario_far_bcr_and_missing_baseline():
    result=scenario_calculation(dict(site_area=10000,building_count=4,footprint_per_building=500,floors=10,efficiency_factor=0.8,pv_ratio=0.1),[],None,{})
    assert result['bcr']==20
    assert result['far']==200
    assert result['gross_floor_area']==20000
    assert result['annual']['scenario']['electricity_kwh'] is None

def test_scenario_scales_only_observed_months():
    result=scenario_calculation(dict(site_area=10000,building_count=4,footprint_per_building=500,floors=10,efficiency_factor=0.8,pv_ratio=0.1),[{'use_ym':'202501','electricity_kwh':1000,'gas_kwh':None}],10000,{})
    assert result['monthly'][0]['scenario']['electricity_kwh']==1440
    assert result['monthly'][0]['scenario']['gas_kwh'] is None
    assert result['annual']['scenario']['electricity_kwh'] is None
    assert result['observed_period_totals']['scenario']['electricity_kwh']==1440
    assert result['coverage_months']['electricity_kwh']==1
    assert result['percent_change']['electricity_kwh'] is None

def test_scenario_reports_the_reference_plan_and_the_savings_against_it():
    """10/14: the result panel and the report compare the plan with the same floor area built at the observed intensity
    (efficiency 1.0, no PV) — the 'reference plan' — not with this grid's current use, which is a different size."""
    factors={'ELECTRICITY':{'factor':0.5,'factor_unit':'kgCO2eq/kWh'},'GAS':{'factor':0.2,'factor_unit':'kgCO2eq/kWh'}}
    baseline=[{'use_ym':f'2025{m:02d}','electricity_kwh':1000,'gas_kwh':500,'carbon_kg':600} for m in range(1,13)]   # rows as the dashboard gives them
    params=dict(site_area=10000,building_count=4,footprint_per_building=500,floors=10,efficiency_factor=0.8,pv_ratio=0.1,households=200,population=500)
    result=scenario_calculation(params,baseline,10000,factors)   # plan floor area 20,000 = 2 × baseline
    ref=result['annual']['reference']
    assert ref['electricity_kwh']==24000 and ref['gas_kwh']==12000 and ref['carbon_kg']==24000*0.5+12000*0.2
    plan=result['annual']['scenario']
    assert plan['electricity_kwh']==24000*0.8*0.9 and plan['gas_kwh']==12000*0.8
    assert result['savings_pct']['carbon_kg']==round((ref['carbon_kg']-plan['carbon_kg'])/ref['carbon_kg']*100,1)
    assert result['savings_pct']['electricity_kwh']==28.0 and result['savings_pct']['gas_kwh']==20.0
    assert result['monthly'][0]['reference']['electricity_kwh']==2000
    assert result['carbon_per_household']==plan['carbon_kg']/200
    assert result['baseline_intensity']=={'electricity_kwh_per_m2':1.2,'gas_kwh_per_m2':0.6}

def test_scenario_reference_and_savings_stay_missing_without_a_baseline():
    result=scenario_calculation(dict(site_area=10000,building_count=4,footprint_per_building=500,floors=10,efficiency_factor=0.8,pv_ratio=0.1),[{'use_ym':'202501','electricity_kwh':1000,'gas_kwh':None}],10000,{})
    assert result['annual']['reference']['electricity_kwh'] is None   # 1 observed month: no annual value
    assert result['savings_pct']=={'electricity_kwh':None,'gas_kwh':None,'carbon_kg':None}
    assert result['carbon_per_household'] is None
    assert result['baseline_intensity']=={'electricity_kwh_per_m2':None,'gas_kwh_per_m2':None}
