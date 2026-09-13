from types import SimpleNamespace as Row
from app.scope import matched_areas

def record(grid,month,code='A',area=100,fuel='ELECTRICITY'):
    return Row(grid_id=grid,use_ym=month,energy_type=fuel,usage_kwh=10,raw_record={'kapt_code':code,'matched_gross_floor_area_m2':area},match_method='KAPT_COMPLEX_CENTROID')

def test_all_grids_can_have_consistent_area_and_partial_sets_are_rejected():
    rows=[record('g1','202501'),record('g1','202502'),record('g2','202501','B',200),record('g2','202502','B',200)]
    assert matched_areas(rows)=={'g1':100,'g2':200}
    rows.append(record('g1','202501','C',50))
    assert matched_areas(rows)=={'g2':200}

def test_unknown_denominator_or_duplicate_complex_never_inflates_area():
    assert matched_areas([record('g','202501'),record('g','202501')])=={}
    assert matched_areas([record('g','202501',area=None)])=={}

def test_different_fuel_parcel_sets_are_not_comparable():
    assert matched_areas([record('g','202501'),record('g','202501','B',fuel='GAS')])=={}
