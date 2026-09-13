from app.official import normalize_register,verified_operation
import pytest

def test_register_uses_assessment_area_separate_from_total_area():
    r=normalize_register({'totArea':'10000','vlRatEstmTotArea':'7000','platArea':'5000','vlRat':'140','bcRat':'20','archArea':'1000','mainPurpsCdNm':'공동주택'})
    assert r['gross_floor_area_m2']==10000
    assert r['far_assessment_floor_area_m2']==7000
    assert r['observed_current_far']==140
    assert r['legal_far_limit'] is None

def test_unverified_operation_is_not_called():
    from app.cache import ExternalError
    with pytest.raises(ExternalError):verified_operation({'host':'apis.data.go.kr','paths':{}},'inventedOperation')
