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
