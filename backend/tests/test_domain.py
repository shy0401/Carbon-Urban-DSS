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
    rows=monthly_weather({'daily':{'time':['2025-01-01','2025-01-02'],'temperature_2m_mean':[10,20],'temperature_2m_min':[2,12],'temperature_2m_max':[15,25],'precipitation_sum':[1,2]}})
    assert rows[0]['mean_temperature']==15
    assert rows[0]['hdd']==8
    assert rows[0]['cdd']==2
    assert rows[0]['precipitation']==3
    assert rows[0]['days_observed']==2

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
