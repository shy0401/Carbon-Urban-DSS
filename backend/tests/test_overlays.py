from app.overlays import summarize_zoning
from app.vworld import zone_category


def test_zone_category_uses_official_names_without_guessing():
    assert zone_category('제2종일반주거지역') == 'RESIDENTIAL'
    assert zone_category('일반상업지역') == 'COMMERCIAL'
    assert zone_category('준공업지역') == 'INDUSTRIAL'
    assert zone_category('자연녹지지역') == 'GREEN'
    assert zone_category('미지정') == 'OTHER'
    assert zone_category(None) == 'UNKNOWN'


def test_zoning_summary_separates_missing_empty_and_caps_overlaps():
    coverage = [('g1', 'SUCCESS'), ('g2', 'EMPTY_VALID'), ('g3', 'SUCCESS')]
    stats = [
        ('g1', '제1종일반주거지역', 0.4), ('g1', '제2종일반주거지역', 0.2), ('g1', '일반상업지역', 0.1),
        ('g3', '제3종일반주거지역', 0.8), ('g3', '제3종일반주거지역', 0.5),
        ('not-requested', '일반상업지역', 1.0),
    ]
    summary = summarize_zoning(coverage, stats)
    assert set(summary) == {'g1', 'g2', 'g3'}
    assert summary['g1']['residential_zone_ratio'] == 60.0
    assert summary['g1']['urban_zone_ratio'] == 70.0
    assert summary['g1']['dominant_zone'] == 'RESIDENTIAL'
    assert summary['g2']['residential_zone_ratio'] == 0.0 and summary['g2']['zoning_status'] == 'EMPTY_VALID'
    assert summary['g2']['dominant_zone'] is None
    assert summary['g3']['residential_zone_ratio'] == 100.0


def test_upper_zone_shapes_count_only_the_area_no_detailed_zone_covers():
    """사용성 검토 F1: 군산 칸은 '도시지역' 상위 도형 100% 위에 주거 94.4%·녹지 5.5%가 겹쳐 합이 200%였다."""
    from app.overlays import zoning_area_by_category, zoning_shares
    coverage = [('gunsan', 'SUCCESS'), ('partly', 'SUCCESS'), ('upper-only', 'SUCCESS'), ('rural', 'SUCCESS')]
    stats = [('gunsan', '도시지역', 1.0), ('gunsan', '도시지역기타', 0.6), ('gunsan', '제2종일반주거지역', 0.944), ('gunsan', '자연녹지지역', 0.055),
             ('partly', '도시지역', 0.9), ('partly', '일반상업지역', 0.5),
             ('upper-only', '도시지역미지정', 0.7),
             ('rural', '관리지역', 0.6), ('rural', '계획관리지역', 0.6), ('rural', '농림지역', 0.3)]
    s = summarize_zoning(coverage, stats)
    assert s['gunsan']['shares'] == {'RESIDENTIAL': 94.4, 'GREEN': 5.5, 'OTHER': 0.1}
    assert s['gunsan']['urban_zone_ratio'] == 100.0 and s['gunsan']['dominant_zone'] == 'RESIDENTIAL'
    assert s['partly']['shares'] == {'COMMERCIAL': 50.0, 'OTHER': 40.0}           # 상위 도형 90% 중 세부가 덮지 않은 40%만 미세분
    assert s['upper-only']['shares'] == {'OTHER': 70.0}
    assert s['rural']['shares'] == {'OTHER': 90.0}                                  # 계획관리 60% + 농림 30%, 세분 전 관리지역은 겹쳐 세지 않음
    assert sum(zoning_shares([('제1종일반주거지역', 0.7), ('일반상업지역', 0.6)]).values()) == 1.0  # 세부끼리 넘치면 칸에 맞춤
    assert callable(zoning_area_by_category)


def test_context_facts_keep_admin_totals_separate_from_grid_values():
    from app.overlays import context_facts
    facts = {f['id']: f['text'] for f in context_facts({
        'zoning': {'status': 'SUCCESS', 'shares_pct': {'RESIDENTIAL': 62.5, 'GREEN': 20.0}, 'residential_pct': 62.5, 'dominant': 'RESIDENTIAL'},
        'admin': [
            {'adm_name': '전북특별자치도 전주시 덕진구 송천1동', 'reference_year': 2024, 'grid_share_pct': 70.0, 'population': 12345.0, 'population_status': 'OBSERVED'},
            {'adm_name': '전북특별자치도 전주시 덕진구 호성동', 'reference_year': 2024, 'grid_share_pct': 30.0, 'population': None, 'population_status': 'SUPPRESSED'},
            {'adm_name': '가장자리동', 'reference_year': 2024, 'grid_share_pct': 0.2, 'population': 1.0, 'population_status': 'OBSERVED'},
        ],
        'complexes': {'count': 3, 'households': 1200.0, 'gross_floor_area_m2': 150000.0, 'with_floor_area': 2},
    })}
    assert '주거 62.5%' in facts['context_zoning'] and '녹지 20.0%' in facts['context_zoning']
    assert '송천1동(격자의 70%, 인구 12,345명)' in facts['context_admin']
    assert '호성동(격자의 30%, 인구 비공개)' in facts['context_admin']
    assert '가장자리동' not in facts['context_admin']
    assert '격자 인구가 아닙니다' in facts['context_admin']
    assert '3개 단지' in facts['context_complexes'] and '2/3개 단지 기준' in facts['context_complexes']


def test_context_facts_report_missing_zoning_honestly():
    from app.overlays import context_facts
    facts = context_facts({'zoning': None, 'admin': [], 'complexes': None})
    assert facts == [{'id': 'context_zoning', 'text': '대상 격자의 용도지역은 아직 수집되지 않았습니다.'}]


def test_bbox_parser_limits_viewport_queries():
    import pytest
    from app.overlays import parse_bbox
    assert parse_bbox('127.1,35.8,127.2,35.9') == (127.1, 35.8, 127.2, 35.9)
    for bad in ('127.2,35.8,127.1,35.9', '126,35,128,36', '1,2,3', 'x,y,z,w'):
        with pytest.raises(ValueError):
            parse_bbox(bad)
