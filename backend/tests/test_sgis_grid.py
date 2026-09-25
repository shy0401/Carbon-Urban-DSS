import csv
import importlib.util
import json
import struct
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import sgis_grid
from app.models import DataSource
from app.sgis_grid import (
    SgisGridCell, SgisGridStat, area_block, cell_summary, code_for, code_origin, context_fact, grid_values,
    import_sgis_grid, parent_code,
)


def make_db():
    engine = create_engine('sqlite+pysqlite:///:memory:')
    for table in (DataSource.__table__, SgisGridCell.__table__, SgisGridStat.__table__):
        table.create(engine)
    db = sessionmaker(engine)()
    db.add(DataSource(id='sgis_grid_1k', category='인구', name='SGIS 격자 통계 1km', organization='국가데이터처', source_url='u',
                      source_type='OFFICIAL', status='MANUAL_DOWNLOAD_REQUIRED', reference_period='-', geographic_coverage='전주시',
                      raw_row_count=0, normalized_row_count=0, quality='-', limitation='-'))
    db.commit()
    return db


ROWS = [
    # 다마6862: a populated cell
    ('다마6862', 'to_in_001', 1000, 'population'), ('다마6862', 'to_ga_001', 400, 'household'), ('다마6862', 'to_ho_001', 380, 'housing'),
    ('다마6862', 'to_em_020', 120, 'worker'), ('다마6862', 'to_fa_010', 30, 'business'),
    ('다마6862', 'in_age_001', 50, 'population'), ('다마6862', 'in_age_014', 150, 'population'), ('다마6862', 'in_age_005', 800, 'population'),
    ('다마6862', 'ga_sd_005', 100, 'household'), ('다마6862', 'ga_sd_003', 10, 'household'), ('다마6862', 'ga_sd_004', 5, 'household'),
    ('다마6862', 'ho_gb_003', 300, 'housing'), ('다마6862', 'ho_gb_002', 80, 'housing'),
    ('다마6862', 'ho_yr_002', 200, 'housing'), ('다마6862', 'ho_yr_012', 180, 'housing'),
    ('다마6862', 'cp_bnu_007', 12, 'business'), ('다마6862', 'cp_bem_007', 40, 'worker'), ('다마6862', 'cp_bem_016', 60, 'worker'),
    # 다마6962: tiny cell (small values may be 0/5 replacements)
    ('다마6962', 'to_in_001', 5, 'population'), ('다마6962', 'to_ga_001', 5, 'household'),
]
CELLS = ['다마6862', '다마6962', '다마6863']  # 6863: boundary only, no statistics


def write_bundle(root: Path, year: int = 2024) -> Path:
    folder = root / str(year)
    folder.mkdir(parents=True)
    with (folder / 'cells.csv').open('w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(['grid_cd', 'x_min', 'y_min', 'x_max', 'y_max', 'size_m'])
        for code in CELLS:
            x, y = code_origin(code)
            w.writerow([code, x, y, x + 1000, y + 1000, 1000])
    with (folder / 'stats.csv').open('w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(['base_year', 'grid_cd', 'item', 'value', 'group'])
        for code, item, value, group in ROWS:
            w.writerow([year, code, item, value, group])
    (folder / 'manifest.json').write_text(json.dumps({'base_years': [year], 'cells': len(CELLS), 'stat_rows': len(ROWS), 'rules': ['잡음']}), encoding='utf-8')
    return folder


def test_grid_codes_follow_the_sgis_block_rule_and_nest_500m_cells():
    assert code_origin('다마6862') == (968000, 1762000)
    assert code_for(968999.9, 1762000) == '다마6862'
    assert code_for(969000, 1762000) == '다마6962'
    # all four project 500m cells (lower-left ids) belong to the same 1km cell
    assert {parent_code(f'cell_{x}_{y}') for x in (968000, 968500) for y in (1762000, 1762500)} == {'다마6862'}
    assert parent_code('g1') is None and code_origin('XX0000') is None and code_for(0, 0) is None


def test_import_loads_bundle_updates_source_and_skips_unchanged(tmp_path):
    db = make_db()
    write_bundle(tmp_path)
    assert import_sgis_grid(db, tmp_path) == {'years': [2024], 'skipped': []}
    source = db.get(DataSource, 'sgis_grid_1k')
    assert source.status == 'COLLECTED' and source.normalized_row_count == len(ROWS) and source.raw_row_count == len(CELLS)
    assert source.reference_period.startswith('2024년') and '잡음' in source.quality
    assert import_sgis_grid(db, tmp_path) == {'years': [], 'skipped': [2024]}
    assert import_sgis_grid(db, tmp_path, force=True)['years'] == [2024]
    year, values = grid_values(db)
    assert year == 2024 and values['다마6862']['to_in_001'] == 1000
    assert '다마6863' not in values  # a cell without rows has no statistic; nothing is filled with 0


def test_import_rejects_coordinates_that_do_not_match_the_code(tmp_path):
    import pytest
    db = make_db()
    folder = write_bundle(tmp_path)
    text = (folder / 'cells.csv').read_text(encoding='utf-8').replace('968000,1762000', '968000,1763000')
    (folder / 'cells.csv').write_text(text, encoding='utf-8')
    with pytest.raises(ValueError):
        import_sgis_grid(db, tmp_path)


def test_cell_summary_keeps_missing_items_missing_and_hides_small_shares():
    values = {code_item[1]: float(code_item[2]) for code_item in ROWS if code_item[0] == '다마6862'}
    s = cell_summary(values)
    assert s['population'] == 1000 and s['households'] == 400 and s['workers'] == 120
    assert s['elderly_pct'] == 15.0 and s['children_pct'] == 5.0
    assert s['single_household_pct'] == 25.0
    assert s['old_housing_pct'] == 52.6  # 1980s 200 of 380 dated units
    assert s['apartment_pct'] == 78.9
    assert s['household_types']['3세대 이상'] == 15  # 3세대 + 4세대
    assert s['housing_age']['2020년 이후'] is None  # no published row: missing, not 0
    assert s['housing_types']['연립주택'] is None
    assert s['sectors'][0] == {'name': '교육서비스', 'businesses': None, 'workers': 60.0}
    tiny = cell_summary({'to_in_001': 5.0, 'to_ga_001': 5.0, 'ga_sd_005': 5.0})
    assert tiny['single_household_pct'] is None  # base under 20 → too noisy to show
    assert tiny['small_flags'] == ['to_ga_001', 'to_in_001']


def test_area_block_sums_whole_cells_and_labels_the_proportional_figure(tmp_path):
    db = make_db()
    write_bundle(tmp_path)
    import_sgis_grid(db, tmp_path)
    year, values = grid_values(db)
    ids = ['cell_968000_1762000', 'cell_968500_1762000', 'cell_969000_1762000', 'cell_968000_1763000']
    block = area_block(ids, year, values)
    assert block['cells'] == 3 and block['cells_with_stats'] == 2
    assert block['coverage_pct'] == 33.3
    assert block['overlap']['population'] == 1005  # whole 1km cells, observed
    assert block['estimated'] == {'population': round(1000 * 2 / 4 + 5 / 4), 'households': round(400 * 2 / 4 + 5 / 4),
                                  'data_class': 'ESTIMATED', 'basis': '1km 격자 값 × (구역에 든 500m 격자 수 ÷ 4)'}
    assert area_block(['g1'], None, {}) is None


def test_context_fact_is_honest_about_missing_cells():
    fact = context_fact({'year': 2024, 'code': '다마6863', 'status': 'NO_STAT'})
    assert '통계가 없습니다' in fact['text'] and '0' not in fact['text'].replace('2024', '')
    fact = context_fact({'year': 2024, 'code': '다마6862', 'status': 'OBSERVED', 'population': 1000.0, 'households': 400.0, 'housing': None, 'old_housing_pct': 52.6})
    assert '인구 1,000명' in fact['text'] and '주택' not in fact['text'].split('입니다')[0].replace('준공 주택', '')
    assert '잡음' in fact['text'] and '나누지 않았습니다' in fact['text']


def test_area_facts_include_sgis_numbers_that_pass_the_checker():
    from app.area import area_facts
    from app.area_report import verify_narrative
    overlap = cell_summary({'to_in_001': 1000.0, 'to_ga_001': 400.0, 'to_ho_001': 380.0, 'to_em_020': 120.0, 'ga_sd_005': 100.0})
    history = {'years': [2020, 2024], 'area': {'label': '테스트', 'grid_ids': ['a'], 'complex_codes': []}, 'events': {}, 'energy': {},
               'coverage': {'energy_years': []}, 'register': {}, 'sgis_grid': {'year': 2024, 'cells': 1, 'cells_with_stats': 1, 'coverage_pct': 25.0, 'overlap': overlap}}
    facts = {f['id']: f for f in area_facts(history)}
    assert '인구 1,000명' in facts['sgis_grid']['text'] and '25.0%' in facts['sgis_grid']['text']
    assert '1인가구 비율은 25.0%' in facts['sgis_grid_shares']['text']
    assert verify_narrative('SGIS 2024년 1km 격자 합계 인구는 1,000명이고 1인가구 비율은 25.0%입니다.', list(facts.values())) == []
    assert verify_narrative('격자 인구는 1,200명입니다.', list(facts.values()))


def _write_dbf(path: Path, codes: list[str]) -> None:
    field = b'GRID_CD'.ljust(11, b'\0') + b'C' + b'\0' * 4 + bytes([10, 0]) + b'\0' * 14
    header_len, record_len = 32 + 32 + 1, 1 + 10
    head = struct.pack('<BBBBIHH', 3, 125, 1, 1, len(codes), header_len, record_len) + b'\0' * 20
    body = b''.join(b' ' + code.encode('utf-8').ljust(10)[:10] for code in codes)
    path.write_bytes(head + field + b'\r' + body + b'\x1a')


def _write_shp(path: Path, boxes: list[tuple[int, int]]) -> None:
    records = b''
    for i, (x, y) in enumerate(boxes, start=1):
        pts = [(x, y), (x, y + 1000), (x + 1000, y + 1000), (x + 1000, y), (x, y)]
        content = struct.pack('<i4d2i', 5, x, y, x + 1000, y + 1000, 1, 5) + struct.pack('<i', 0) + b''.join(struct.pack('<2d', *p) for p in pts)
        records += struct.pack('>2i', i, len(content) // 2) + content
    header = struct.pack('>7i', 9994, 0, 0, 0, 0, 0, (100 + len(records)) // 2) + struct.pack('<2i4d4d', 1000, 5, 0, 0, 0, 0, 0, 0, 0, 0)
    path.write_bytes(header + records)


def test_extractor_cuts_the_package_to_the_bbox_and_checks_boundaries(tmp_path):
    script = Path(__file__).resolve().parents[2] / 'scripts' / 'sgis' / 'extract_sgis_grid.py'
    if not script.exists():  # the API container mounts backend/ only
        return
    spec = importlib.util.spec_from_file_location('extract_sgis_grid', script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    src = tmp_path / 'pkg'
    (src / '1. 통계' / '인구').mkdir(parents=True)
    (src / '2. 경계' / 'grid_다마').mkdir(parents=True)
    (src / '3. 코드집').mkdir()
    codes = ['다마6862', '다마0101']  # the second is outside the Jeonju bbox
    _write_dbf(src / '2. 경계' / 'grid_다마' / 'grid_다마_1K.dbf', codes)
    _write_shp(src / '2. 경계' / 'grid_다마' / 'grid_다마_1K.shp', [code_origin(c) for c in codes])
    csv_text = '기준연도,격자코드,통계항목,통계값\n2024,다마6862,to_in_001,1000\n2024,다마0101,to_in_001,7\n'
    (src / '1. 통계' / '인구' / '2024년_인구_다마_1K.csv').write_bytes(csv_text.encode('cp949'))
    out = tmp_path / 'out'
    manifest = mod.extract(src, out, mod.JEONJU_BBOX)
    assert manifest['cells'] == 1 and manifest['stat_rows'] == 1 and manifest['base_years'] == [2024]
    rows = list(csv.DictReader((out / 'stats.csv').open(encoding='utf-8')))
    assert rows == [{'base_year': '2024', 'grid_cd': '다마6862', 'item': 'to_in_001', 'value': '1000', 'group': 'population'}]
    db = make_db()
    (tmp_path / 'bundles').mkdir()
    out.rename(tmp_path / 'bundles' / '2024')
    assert import_sgis_grid(db, tmp_path / 'bundles')['years'] == [2024]


def test_values_cache_is_cleared_on_import(tmp_path):
    db = make_db()
    write_bundle(tmp_path)
    import_sgis_grid(db, tmp_path)
    grid_values(db)
    assert sgis_grid._VALUES_CACHE
    import_sgis_grid(db, tmp_path, force=True)
    assert not sgis_grid._VALUES_CACHE
