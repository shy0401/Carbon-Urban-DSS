import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.cache import ExternalError, recent_credential_error
from app.models import DataSource
from app.sgis import SgisTokenManager, collect_sgis_admin, parse_sgis_statistics


class Response:
    status_code = 200
    def __init__(self, payload):
        self.payload = payload
    def json(self):
        return self.payload


class Requester:
    def __init__(self, payloads):
        self.payloads = iter(payloads)
        self.calls = []
    def get(self, url, params):
        self.calls.append(dict(params))
        return Response(next(self.payloads))


def test_token_manager_reuses_token_until_refresh_window_then_renews():
    now = [1_700_000_000.0]
    requester = Requester([
        {'errCd': 0, 'result': {'accessToken': 'token-1', 'accessTimeout': str(int((now[0] + 3600) * 1000))}},
        {'errCd': 0, 'result': {'accessToken': 'token-2', 'accessTimeout': str(int((now[0] + 7200) * 1000))}},
    ])
    manager = SgisTokenManager('consumer', 'secret', requester=requester, now=lambda: now[0])
    assert manager.get_token() == 'token-1'
    assert manager.get_token() == 'token-1'
    assert len(requester.calls) == 1
    now[0] += 3550
    assert manager.get_token() == 'token-2'
    assert len(requester.calls) == 2


def test_population_parser_distinguishes_zero_suppressed_and_missing():
    body = json.dumps({'errCd': 0, 'errMsg': 'Success', 'result': [
        {'adm_cd': '35010', 'adm_nm': '전주시', 'population': '0'},
        {'adm_cd': '35011', 'adm_nm': '전주시 완산구', 'population': '*'},
        {'adm_cd': '35012', 'adm_nm': '전주시 덕진구', 'population': ''},
    ]}).encode()
    parsed = parse_sgis_statistics(body, 'population')
    assert parsed['rows'][0]['value'] == 0.0
    assert parsed['rows'][0]['value_status'] == 'OBSERVED_ZERO'
    assert parsed['rows'][1]['value'] is None
    assert parsed['rows'][1]['value_status'] == 'SUPPRESSED'
    assert parsed['rows'][2]['value_status'] == 'NOT_AVAILABLE'


def test_household_parser_keeps_household_and_member_counts_separate():
    body = json.dumps({'errCd': 0, 'result': [{
        'adm_cd': '35010', 'adm_nm': '전주시', 'household_cnt': '120',
        'family_member_cnt': '300', 'avg_family_member_cnt': '2.5',
    }]}).encode()
    parsed = parse_sgis_statistics(body, 'household')['rows'][0]
    assert parsed['value'] == 120.0
    assert parsed['family_member_count'] == 300.0
    assert parsed['average_family_member_count'] == 2.5


def test_rejected_token_credentials_are_recorded_for_preflight(tmp_path):
    class RejectedManager:
        consumer_key = 'consumer-key'
        consumer_secret = 'rejected-secret'
        def get_token(self):
            raise ExternalError('SGIS 인증 실패: provider_code=-401')

    engine = create_engine('sqlite+pysqlite:///:memory:')
    DataSource.__table__.create(engine)
    db = sessionmaker(engine)()
    with pytest.raises(ExternalError, match='인증 실패'):
        collect_sgis_admin(db, 2020, 'smoke', token_manager=RejectedManager(), data_dir=tmp_path)
    assert recent_credential_error(tmp_path/'cache'/'sgis-auth','consumer-key|rejected-secret') == 'SGIS 인증 실패: provider_code=-401'


def test_rejected_statistics_token_is_tied_back_to_consumer_credentials(tmp_path):
    class AcceptedManager:
        consumer_key = 'consumer-key'
        consumer_secret = 'consumer-secret'
        def get_token(self):
            return 'rejected-access-token'
    class RejectedStatisticsClient:
        def get(self, *args, **kwargs):
            return {'body': json.dumps({'errCd': -401, 'errMsg': 'Unauthorized'}).encode(), 'id': 'sgis-error'}

    engine = create_engine('sqlite+pysqlite:///:memory:')
    DataSource.__table__.create(engine)
    db = sessionmaker(engine)()
    with pytest.raises(ExternalError, match='인증 실패'):
        collect_sgis_admin(db, 2020, 'smoke', token_manager=AcceptedManager(), client=RejectedStatisticsClient(), data_dir=tmp_path)
    assert recent_credential_error(tmp_path/'cache'/'sgis-auth','consumer-key|consumer-secret') == 'SGIS 인증 실패: consumer key/secret 또는 access token을 확인하세요'


def test_boundary_parser_keeps_official_codes_repairs_geometry_and_treats_minus_100_as_empty():
    from app.sgis import parse_sgis_boundary
    bowtie = [[0, 0], [10, 10], [0, 10], [10, 0], [0, 0]]
    body = json.dumps({'errCd': 0, 'type': 'FeatureCollection', 'features': [
        {'type': 'Feature', 'properties': {'adm_cd': '3501151', 'adm_nm': '중앙동'}, 'geometry': {'type': 'Polygon', 'coordinates': [bowtie]}},
        {'type': 'Feature', 'properties': {'adm_cd': '3501152', 'adm_nm': '풍남동'}, 'geometry': {'type': 'Polygon', 'coordinates': [[[0, 0], [5, 0], [5, 5], [0, 5], [0, 0]]]}},
    ]}).encode()
    parsed = parse_sgis_boundary(body)
    assert [f['adm_code'] for f in parsed['features']] == ['3501151', '3501152']
    assert parsed['features'][0]['geometry_repaired'] is True and parsed['features'][0]['geometry'].is_valid
    assert parsed['features'][1]['geometry'].area == 25
    assert parse_sgis_boundary(json.dumps({'errCd': -100, 'errMsg': '검색결과가 존재하지 않습니다'}).encode())['status'] == 'EMPTY_VALID'
    with pytest.raises(ExternalError, match='인증 실패'):
        parse_sgis_boundary(json.dumps({'errCd': -401}).encode())


def test_candidate_years_fall_back_at_most_five_older_years():
    from app.sgis import _candidate_years
    assert _candidate_years(2024) == [2024, 2023, 2022, 2021, 2020, 2019]
    assert _candidate_years(2016) == [2016, 2015]


class _FakeDb:
    def __init__(self):
        self.rows = {}
    def get(self, model, key):
        return self.rows.get((model.__name__, key))
    def add(self, row):
        self.rows[(type(row).__name__, getattr(row, 'id', id(row)))] = row
    def commit(self):
        pass


def test_city_resolution_uses_year_specific_codes_and_skips_unpublished_year(tmp_path):
    from app.sgis import _SgisRun, _resolve_city
    payloads = {
        ('2024', None): {'errCd': -100, 'errMsg': '검색결과가 존재하지 않습니다'},
        ('2023', None): {'errCd': 0, 'result': [{'adm_cd': '11', 'adm_nm': '서울특별시', 'population': '1'}, {'adm_cd': '52', 'adm_nm': '전북특별자치도', 'population': '2'}]},
        ('2023', '52'): {'errCd': 0, 'result': [{'adm_cd': '52111', 'adm_nm': '전주시 완산구', 'population': '100'}, {'adm_cd': '52113', 'adm_nm': '전주시 덕진구', 'population': '*'}, {'adm_cd': '52130', 'adm_nm': '군산시', 'population': '50'}]},
    }
    class Session:
        def get(self, provider, operation, url, params):
            assert 'accessToken' in params
            return {'body': json.dumps(payloads[(params['year'], params.get('adm_cd'))]).encode(), 'id': operation}
    class Source:
        id = 'sgis_admin'; organization = 'SGIS'
    db = _FakeDb()
    run = _SgisRun(db, Session(), 'token', tmp_path, 'https://example.invalid', 'k|s', Source())
    assert _resolve_city(run, 2024) is None
    province, districts = _resolve_city(run, 2023)
    assert province == '52'
    assert [row['adm_code'] for row in districts] == ['52111', '52113']
    stored = {key[1]: row for key, row in db.rows.items() if key[0] == 'SgisPopulationAdmin'}
    assert stored['2023:52111'].population_count == 100.0
    assert stored['2023:52113'].population_count is None and stored['2023:52113'].value_status == 'SUPPRESSED'
    assert (tmp_path / 'raw' / 'sgis' / '2023' / 'population-52.json').exists()
