import pytest
from app.modeling import validation_metrics, model_eligibility, optimize
from app.domain import scenario_calculation

def test_metrics_have_known_independent_values():
    m=validation_metrics([100,200,300],[110,180,310])
    assert m['mae']==pytest.approx(40/3)
    assert m['rmse']==pytest.approx(200**0.5)
    assert m['r2']==pytest.approx(.97)
    assert m['nmae']==pytest.approx(1/15)
    assert m['smape']==pytest.approx((20/210+40/380+20/610)/3)

def test_small_single_grid_is_not_validated_ml():
    result=model_eligibility([{'grid_id':'one','use_ym':f'2025{m:02}','usage_kwh':100} for m in range(1,13)])
    assert result['status']=='INSUFFICIENT_TRAINING_DATA'
    assert result['validated'] is False

def test_identical_scenario_preserves_baseline():
    params=dict(site_area=10000,building_count=4,footprint_per_building=500,floors=10,efficiency_factor=1,pv_ratio=0)
    result=scenario_calculation(params,[{'use_ym':'202501','electricity_kwh':1000,'gas_kwh':2000,'carbon_kg':None}],20000,{})
    assert result['monthly'][0]['scenario']['electricity_kwh']==1000
    assert result['monthly'][0]['scenario']['gas_kwh']==2000
    assert result['monthly'][0]['difference']['electricity_kwh']==0

def test_optimization_missing_baseline_never_invents_ranking():
    p=dict(site_area=10000,building_count=4,footprint_per_building=500,floors=10,efficiency_factor=.8,pv_ratio=.1,average_household_area=85,green_ratio=.2,min_households=100,min_population=200,households=100,population=200)
    r=optimize(p,[],None,{})
    assert r['status']=='INSUFFICIENT_BASELINE_DATA'
    assert r['alternatives']==[]

def test_optimization_constraints_and_determinism():
    p=dict(site_area=10000,building_count=4,footprint_per_building=500,floors=10,efficiency_factor=.8,pv_ratio=.1,average_household_area=100,green_ratio=.5,min_households=200,min_population=400,households=200,population=400)
    baseline=[{'use_ym':f'2025{m:02}','electricity_kwh':1000,'gas_kwh':2000,'carbon_kg':800} for m in range(1,13)]
    factors={'ELECTRICITY':{'factor':.4,'factor_unit':'kgCO2eq/kWh'},'GAS':{'factor':.2,'factor_unit':'kgCO2eq/kWh'}}
    result=optimize(p,baseline,20000,factors,{'legal_far_limit':200,'legal_bcr_limit':40,'max_floors':20})
    assert result==optimize(p,baseline,20000,factors,{'legal_far_limit':200,'legal_bcr_limit':40,'max_floors':20})
    assert result['alternatives']
    for row in result['alternatives']:
        assert row['far']<=200
        assert row['bcr']<=40
        assert row['floors']<=20
        assert row['households']>=200
        assert row['population']>=400
    assert result['status']=='ENERGY_OPTIMAL'
