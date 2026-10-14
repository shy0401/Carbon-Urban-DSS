"""지도 분석 3단계 속도(2026-10-14): 지역 화면이 그 지역 격자만 읽는지."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def test_zoning_summary_reads_only_the_asked_cells(monkeypatch):
    from app import overlays
    from app.vworld import GridZoningStat, VworldGridCoverage
    engine = create_engine('sqlite+pysqlite:///:memory:')
    for table in (GridZoningStat.__table__, VworldGridCoverage.__table__):
        table.create(engine)
    db = sessionmaker(engine)()
    monkeypatch.setattr(overlays, '_table_exists', lambda db, name: True)
    for grid in ('a', 'b'):
        db.add(VworldGridCoverage(id=f'zoning:{grid}', dataset='zoning', grid_id=grid, status='DONE'))
        db.add(GridZoningStat(id=f's:{grid}', grid_id=grid, zoning_feature_id='f', zone_name='제2종일반주거지역', intersection_area_m2=1.0,
                              grid_area_ratio=0.5, source='VWorld'))
    db.commit()
    assert set(overlays.grid_zoning_summary(db)) == {'a', 'b'}
    one = overlays.grid_zoning_summary(db, ['a'])
    assert set(one) == {'a'} and one['a']['residential_zone_ratio'] == 50.0


def test_the_original_region_gets_zoning_polygons_of_its_own_cells_only():
    """전주(기본 지역)는 모든 지역의 용도지역 도형을 받았다(8개 지역 준비 뒤 36.8MB). 이제 자기 격자 범위만."""
    from app.overlays import cells_extent
    assert cells_extent(['cell_1000_2000', 'cell_1500_2500', 'not-a-cell']) == (1000.0, 2000.0, 2000.0, 3000.0)
    assert cells_extent(['legacy-id']) is None


def test_place_label_names_the_region_and_its_dongs_never_the_cell_id():
    """Reports and the simulation screen name the place (전주시 송천1동 일대), not cell_<x>_<y>."""
    from app.overlays import place_label
    rows = [{'adm_name': '전북특별자치도 전주시 덕진구 송천1동', 'grid_share_pct': 86.0}, {'adm_name': '전북특별자치도 전주시 덕진구 송천2동', 'grid_share_pct': 14.0},
            {'adm_name': '전북특별자치도 전주시 덕진구 조촌동', 'grid_share_pct': 0.4}]
    assert place_label(rows, '전주시') == '전주시 송천1동·송천2동 일대'
    assert place_label(rows[:1], '전주시') == '전주시 송천1동 일대'
    assert place_label([], '전주시') == '전주시 (500m 격자)'
    assert place_label([], None) == '500m 분석 격자'
    assert 'cell_' not in place_label(rows, None)
