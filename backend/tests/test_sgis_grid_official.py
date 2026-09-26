import json

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from app.models import DataSource, RawDataAsset
from app.sgis import SgisPopulationAdmin
from app.sgis_grid_official import SgisOfficialGridCell, collect_sgis_grid_official, official_codes, parse_grid_geojson, project_cell_id


def square(x, y, size=500):
    return [[[x, y], [x, y + size], [x + size, y + size], [x + size, y], [x, y]]]


def geojson(cells, err=0, msg='Success'):
    return json.dumps({'type': 'FeatureCollection', 'errCd': err, 'errMsg': msg, 'features': [
        {'type': 'Feature', 'properties': {'adm_cd': code, 'adm_nm': code}, 'geometry': {'type': 'Polygon', 'coordinates': square(x, y)}}
        for code, x, y in cells]}).encode()


class FakeClient:
    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def get(self, provider, operation, url, params):
        assert 'accessToken' in params and params['grid_level_div'] == '500m'
        self.calls.append(params['adm_cd'])
        return {'body': self.answers[params['adm_cd']], 'status': 200, 'id': operation}


class FakeTokens:
    consumer_key, consumer_secret = 'k', 's'

    def get_token(self):
        return 'tok'


def make_db():
    engine = create_engine('sqlite+pysqlite:///:memory:')
    for table in (DataSource.__table__, RawDataAsset.__table__, SgisPopulationAdmin.__table__, SgisOfficialGridCell.__table__):
        table.create(engine)
    with engine.begin() as connection:  # the real table has a PostGIS geometry column; only ids are read here
        connection.execute(text('CREATE TABLE grid_500m (id TEXT PRIMARY KEY)'))
    return sessionmaker(engine)()


def test_parse_keeps_only_squares_and_reports_no_data():
    parsed = parse_grid_geojson(geojson([('다마62a48a', 962000, 1748000)]))
    assert parsed['status'] == 'SUCCESS' and parsed['cells'] == [{'grid_cd': '다마62a48a', 'x_min': 962000.0, 'y_min': 1748000.0, 'size_m': 500}]
    assert parse_grid_geojson(geojson([], err=-100, msg='검색결과가 존재하지 않습니다.'))['status'] == 'EMPTY_VALID'


def test_official_cells_link_to_project_cells_with_the_same_corner(tmp_path):
    db = make_db()
    for grid_id in ('cell_962000_1748000', 'cell_962500_1748000', 'cell_900000_1700000'):
        db.execute(text('INSERT INTO grid_500m (id) VALUES (:id)'), {'id': grid_id})
    db.add(SgisPopulationAdmin(id='p1', adm_code='3501153', adm_name='동', reference_year=2024, value_status='OK', source='SGIS', raw_record={}))
    db.add(SgisPopulationAdmin(id='p2', adm_code='3501256', adm_name='동', reference_year=2024, value_status='OK', source='SGIS', raw_record={}))
    db.commit()
    client = FakeClient({'35011': geojson([('다마62a48a', 962000, 1748000), ('다마62b48a', 962500, 1748000)]),
                         '35012': geojson([('다마70a53b', 970000, 1753500)])})
    result = collect_sgis_grid_official(db, client=client, token_manager=FakeTokens(), data_dir=tmp_path)
    assert client.calls == ['35011', '35012']
    assert result == {'requests': 2, 'districts': ['35011', '35012'], 'cells': 3, 'linked': 2, 'project_cells': 3, 'code_mismatch': 0}
    assert official_codes(db) == {'cell_962000_1748000': '다마62a48a', 'cell_962500_1748000': '다마62b48a'}
    source = db.get(DataSource, 'sgis_grid')
    assert source.status == 'PARTIAL' and '자료신청' in source.quality and source.normalized_row_count == 3
    assert (tmp_path / 'raw' / 'sgis_grid_official' / 'grid-500m-35011.geojson').exists()
    # a project cell without an official twin keeps no code (nothing is guessed)
    assert db.scalar(select(SgisOfficialGridCell.grid_id).where(SgisOfficialGridCell.grid_cd == '다마70a53b')) is None
    assert project_cell_id(962000.0, 1748000.0) == 'cell_962000_1748000'


def test_sub_cell_letters_that_disagree_with_the_geometry_are_counted(tmp_path):
    db = make_db()
    db.add(SgisPopulationAdmin(id='p1', adm_code='3501153', adm_name='동', reference_year=2024, value_status='OK', source='SGIS', raw_record={}))
    db.commit()
    client = FakeClient({'35011': geojson([('다마62b48a', 962000, 1748000)])})  # 'b' but the x offset is 0
    result = collect_sgis_grid_official(db, client=client, token_manager=FakeTokens(), data_dir=tmp_path)
    assert result['code_mismatch'] == 1 and '불일치 1개' in db.get(DataSource, 'sgis_grid').quality
