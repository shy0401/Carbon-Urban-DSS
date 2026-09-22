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
