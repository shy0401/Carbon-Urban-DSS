from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.zoning_limits import LIMITS, check_plan, limits_for, normalize_zone, site_zoning, weighted_limits


def test_ordinance_values_and_names():
    assert normalize_zone('제2종일반주거지역') == '제2종일반주거지역' and normalize_zone('제2종일반주거') == '제2종일반주거지역'
    assert normalize_zone('없는지역') is None and normalize_zone(None) is None
    second = limits_for('제2종일반주거지역')
    assert (second['bcr_limit'], second['far_limit'], second['far_limit_housing']) == (60, 250, 250)
    # 상업지역: 주거복합건축물·오피스텔은 낮은 상한, 준공업: 공동주택 200
    assert limits_for('일반상업지역')['far_limit'] == 900 and limits_for('일반상업지역')['far_limit_housing'] == 600
    assert limits_for('준공업지역')['far_limit_housing'] == 200
    # 조례에 없는 칸은 비워 둔다(추정하지 않음)
    assert limits_for('자연환경보전지역')['bcr_limit'] is None and limits_for('자연환경보전지역')['known'] is False
    assert len(LIMITS) == 21


def test_single_zone_site_within_limits():
    limits = weighted_limits([{'zone_name': '제2종일반주거지역', 'area_m2': 10000}], 10000)
    assert limits['status'] == 'OK' and limits['bcr_limit'] == 60 and limits['far_limit'] == 250 and not limits['mixed']
    check = check_plan(limits, bcr=28.0, far=240.0, site_area_m2=10000, households=240)
    assert check['label'] == '조례 기본 상한 이내 (1차 확인)' and check['far'] == 'WITHIN'
    assert check['district_plan'] is True  # 1만㎡ 이상은 지구단위계획 수립 대상
    over = check_plan(limits, bcr=28.0, far=336.0, site_area_m2=9000, households=240)
    assert over['label'] == '조례 기본 상한 초과' and over['far'] == 'OVER' and over['district_plan'] is False


def test_mixed_zones_are_area_weighted_and_gaps_are_not_guessed():
    mixed = weighted_limits([{'zone_name': '제2종일반주거지역', 'area_m2': 7500}, {'zone_name': '자연녹지지역', 'area_m2': 2500}], 10000)
    assert mixed['mixed'] and mixed['far_limit'] == 212.5 and mixed['bcr_limit'] == 50.0
    assert [z['zone'] for z in mixed['zones']] == ['제2종일반주거지역', '자연녹지지역']
    partial = weighted_limits([{'zone_name': '제2종일반주거지역', 'area_m2': 6000}], 10000)
    assert partial['status'] == 'PARTIAL_COVERAGE' and partial['far_limit'] is None
    assert check_plan(partial, bcr=20, far=100, site_area_m2=10000, households=10)['label'] == '법적 상한 판단 보류'
    industrial = weighted_limits([{'zone_name': '일반공업지역', 'area_m2': 10000}], 10000)
    assert industrial['status'] == 'LIMIT_UNKNOWN'  # 공동주택 허용 여부 확인 필요
    assert weighted_limits([], 10000)['status'] == 'NO_ZONING'


def test_site_zoning_without_postgis_reports_not_collected():
    db = sessionmaker(create_engine('sqlite+pysqlite:///:memory:'))()
    result = site_zoning(db, 127.15, 35.82, 10000)
    assert result['status'] == 'NOT_COLLECTED' and result['far_limit'] is None and result['source']['url'].startswith('https://www.law.go.kr')
