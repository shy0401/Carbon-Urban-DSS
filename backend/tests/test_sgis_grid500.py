"""SGIS 500m 격자 통계 (자료제공 신청분) 읽기·적용."""
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models import DataSource
from app.sgis_grid500 import (SgisGrid500Value, _CACHE, change_pct, code500_for, code500_origin, grid500_properties, import_sgis_grid500,
                              missing_files, missing_text, pivot, project_code, read_rows, scan, series, small_flags)


def make_db():
    engine = create_engine('sqlite+pysqlite:///:memory:')
    for table in (DataSource.__table__, SgisGrid500Value.__table__):
        table.create(engine)
    _CACHE.clear()
    return sessionmaker(bind=engine)()


def write(root, name, lines, encoding='cp949'):
    folder = root / '_census_reqdoc_1'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(('\n'.join(lines) + '\n').encode(encoding))


def sample(root):
    write(root, '2024년_인구_다사_500M.csv', ['2024,다사50a19a,to_in_001,120', '2024,다사50a19a,to_in_007,61', '2024,다사50a19a,to_in_008,59',
                                           '2024,다사50b19a,to_in_001,5', '2024,다사50b19a,to_in_007,0'])
    write(root, '2024년_가구_다사_500M.csv', ['2024,다사50a19a,to_ga_001,48'])
    write(root, '2024년_주택_다사_500M.csv', ['2024,다사50a19a,to_ho_001,40'])
    write(root, '2024년_사업체_다사_500M.csv', ['2024,다사50a19a,to_fa_010,3'])
    write(root, '2024년_종사자_다사_500M.csv', ['2024,다사50a19a,to_em_020,17'])
    write(root, '2024년_인구_다마_500M.csv', ['2024,다마62a48a,to_in_001,900'])
    write(root, '2024년_가구_다마_500M.csv', ['2024,다마62a48a,to_ga_001,400'])  # 다마 주택·사업체·종사자 없음
    write(root, '2015년_인구_다사_500M.csv', ['2015,다사50a19a,to_in_001,100'])
    write(root, '2010년_인구_다사_500M.csv', ['2010,다사50a19a,to_in_001,90'])
    write(root, '9023년_인구_다사_500M.csv', ['9023,다사50a19a,to_in_001,77'])  # 이용안내에 없는 연도 표기
    write(root, '2024년_인구_다사_1K.csv', ['2024,다사50a19,to_in_001,999'])  # 1km는 읽지 않음


def test_codes_match_project_cells():
    assert code500_origin('다사50a19a') == (950000, 1919000)
    assert code500_origin('다마62b48b') == (962500, 1748500)
    assert code500_for(950000, 1919000) == '다사50a19a' and code500_for(950499, 1919499) == '다사50a19a'
    assert project_code('cell_962500_1748000') == '다마62b48a'
    for x, y in ((700000, 1300000), (962500, 1748500), (1199500, 2099500)):
        assert code500_origin(code500_for(x, y)) == (x, y)
    assert code500_origin('다사5019') is None and code500_origin('다사50c19a') is None and code500_for(0, 0) is None
    assert project_code('grid-1') is None


def test_scan_reads_500m_files_of_real_years_only(tmp_path):
    sample(tmp_path)
    years, ignored = scan(tmp_path)
    assert sorted(years) == [2010, 2015, 2024] and len(years[2024]) == 7
    assert ignored == ['9023년_인구_다사_500M.csv']


def test_rows_cp949_and_pivot(tmp_path):
    sample(tmp_path)
    rows = list(read_rows(tmp_path / '_census_reqdoc_1' / '2024년_인구_다사_500M.csv'))
    assert rows[0] == (2024, '다사50a19a', 'to_in_001', 120.0)
    write(tmp_path, 'x.csv', ['2024,다사50a19a,to_in_001,N/A', '2023,다사50a19a,to_in_001,1', '2024,bad,to_in_001,3', '2024,다사50a19a,to_in_002,4',
                              '2024,다사50a19a,to_in_001,7'], encoding='utf-8')
    cells, skipped = pivot([tmp_path / '_census_reqdoc_1' / 'x.csv'], 2024)
    assert cells == {'다사50a19a': {'population': 7.0}}
    assert skipped == {'other_year': 1, 'bad_code': 1, 'other_item': 1}


def test_change_needs_enough_people_and_small_values_are_flagged():
    assert change_pct(100, 120) == 20.0
    assert change_pct(10, 120) is None and change_pct(None, 50) is None and change_pct(50, 5) is None
    assert small_flags({'population': 5.0, 'households': 12.0, 'businesses': 0.0, 'workers': 17.0}) == ['businesses', 'population']


def test_missing_files_are_named_per_theme_and_block(tmp_path):
    sample(tmp_path)
    gaps = missing_files(tmp_path)
    assert {'theme': '주택', 'block': '다마', 'years': [2024]} in gaps
    assert {'theme': '가구', 'block': '다사', 'years': [2015]} in gaps  # 2015~ all five themes
    assert not any(g['years'] == [2010] for g in gaps)  # 2010 has population only
    assert '사업체 다마 블록 2024년' in missing_text(gaps)


def test_import_properties_and_series(tmp_path):
    sample(tmp_path)
    db = make_db()
    logs = []
    result = import_sgis_grid500(db, tmp_path, log=logs.append)
    assert result['years'] == [2010, 2015, 2024] and result['rows'][2024] == 3 and result['ignored_count'] == 1
    assert db.get(SgisGrid500Value, '2024:다사50a19a').workers == 17.0
    assert db.get(SgisGrid500Value, '2024:다마62a48a').housing is None  # 파일 없음 = 통계 없음, 0 아님
    source = db.get(DataSource, 'sgis_grid_500m_stats')
    assert source.status == 'COLLECTED' and source.reference_period == '2010~2024년' and '사업체 다마' in source.quality
    props = grid500_properties(db, ['cell_950000_1919000', 'cell_950500_1919000', 'cell_962000_1748000', 'cell_100000_100000'])
    first = props['cell_950000_1919000']
    assert first['sgis500_population'] == 120 and first['sgis500_pop_density'] == 480 and first['sgis500_base_year'] == 2015
    assert first['sgis500_pop_change_pct'] == 20.0 and first['sgis500_small'] == ['businesses']
    assert props['cell_950500_1919000']['sgis500_small'] == ['population'] and props['cell_950500_1919000']['sgis500_pop_change_pct'] is None
    assert props['cell_962000_1748000']['sgis500_housing'] is None and props['cell_962000_1748000']['sgis500_workers'] is None
    assert props['cell_100000_100000'] == {'sgis500_year': 2024, 'sgis500_status': 'NO_STAT'}
    assert [s['year'] for s in series(db, '다사50a19a')] == [2010, 2015, 2024]
    # unchanged files: nothing reloaded; force reloads
    again = import_sgis_grid500(db, tmp_path, log=logs.append)
    assert again['years'] == [] and again['skipped'] == [2010, 2015, 2024]
    assert import_sgis_grid500(db, tmp_path, force=True, log=logs.append)['years'] == [2010, 2015, 2024]
    assert db.scalar(select(SgisGrid500Value.population).where(SgisGrid500Value.id == '2024:다사50a19a')) == 120


def test_manual_list_asks_only_for_missing_files(tmp_path):
    from app.history import MANUAL_SOURCES, manual_sources
    assert manual_sources(tmp_path) == list(MANUAL_SOURCES)
    sample(tmp_path / 'raw' / 'sgis_grid_500m')
    items = manual_sources(tmp_path)
    grid = next(i for i in items if i['id'] == 'sgis_grid')
    assert '재신청' in grid['label'] and '종사자 다마 블록 2024년' in grid['why'] and grid['missing']
    assert len(items) == len(MANUAL_SOURCES)
