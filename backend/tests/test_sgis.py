import json

from app.sgis import SgisTokenManager, parse_sgis_statistics


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
