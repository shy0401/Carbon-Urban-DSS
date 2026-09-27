import hashlib
import json
import time

import httpx
import pytest
from app.cache import CachedClient,ExternalError,parse_cached_response,recent_credential_error

@pytest.fixture(autouse=True)
def isolated_online_cache(monkeypatch,tmp_path):
    monkeypatch.setenv('DEMO_OFFLINE_MODE','false')
    monkeypatch.setattr('app.settings.DATA_DIR',tmp_path)

def test_historical_response_is_reused_without_secret_in_cache(tmp_path):
    calls=[]
    def send(request):
        calls.append(request)
        return httpx.Response(200,content=b'<response/>')
    client=CachedClient(tmp_path,httpx.Client(transport=httpx.MockTransport(send)),min_interval=0)
    a=client.get('molit','electricity','https://example.org/api',{'serviceKey':'sensitive','useYm':'202501','pageNo':1})
    b=client.get('molit','electricity','https://example.org/api',{'serviceKey':'sensitive','useYm':'202501','pageNo':1})
    assert a['body']==b['body']==b'<response/>'
    assert len(calls)==1
    assert b['cached'] is True
    assert all(b'sensitive' not in f.read_bytes() for f in tmp_path.rglob('*') if f.is_file())
    client.get('molit','electricity','https://example.org/api',{'serviceKey':'sensitive','useYm':'202502','pageNo':1})
    assert len(calls)==2

def test_failure_does_not_become_empty_success_and_is_cached(tmp_path):
    calls=[]
    def send(request):
        calls.append(request)
        return httpx.Response(403,content=b'<returnReasonCode>30</returnReasonCode>')
    client=CachedClient(tmp_path,httpx.Client(transport=httpx.MockTransport(send)),min_interval=0)
    for _ in range(2):
        with pytest.raises(ExternalError,match='인증'):
            client.get('molit','electricity','https://example.org/api',{'serviceKey':'secret'})
    assert len(calls)==1

def test_all_provider_credentials_are_removed_from_cached_metadata_and_body(tmp_path):
    secrets={
        'serviceKey':'public-data-secret',
        'consumer_secret':'sgis-consumer-secret',
        'accessToken':'sgis-access-token',
        'key':'vworld-secret',
    }
    def send(request):
        echoed='&'.join(f'{name}={value}' for name,value in secrets.items())
        return httpx.Response(200,content=echoed.encode())
    client=CachedClient(tmp_path,httpx.Client(transport=httpx.MockTransport(send)),min_interval=0)
    result=client.get('provider','operation','https://example.org/api',{**secrets,'year':'2025'})
    files=b'\n'.join(path.read_bytes() for path in tmp_path.rglob('*') if path.is_file())
    for secret in secrets.values():
        assert secret.encode() not in files
        assert secret.encode() not in result['body']
    assert result['params']=={'year':'2025'}

def test_success_cache_is_bound_to_the_credential_that_created_it(tmp_path):
    calls=[]
    def send(request):
        calls.append(request)
        return httpx.Response(200,content=f'response-{len(calls)}'.encode())
    client=CachedClient(tmp_path,httpx.Client(transport=httpx.MockTransport(send)),min_interval=0)
    first=client.get('provider','operation','https://example.org/api',{'key':'old-key'})
    second=client.get('provider','operation','https://example.org/api',{'key':'new-key'})
    assert first['body']==b'response-1'
    assert second['body']==b'response-2'
    assert len(calls)==2

def test_http_200_provider_auth_error_is_recorded_for_preflight(tmp_path):
    calls=[]
    def send(request):
        calls.append(request)
        return httpx.Response(200,content=b'{"response":{"status":"ERROR.INVALID_KEY"}}')
    client=CachedClient(tmp_path,httpx.Client(transport=httpx.MockTransport(send)),min_interval=0)
    result=client.get('VWorld','zoning','https://example.org/api',{'key':'bad-key'})
    with pytest.raises(ExternalError,match='인증'):
        parse_cached_response(client,result,lambda body: (_ for _ in ()).throw(ExternalError('VWorld 인증 실패: provider_code=INVALID_KEY')))
    assert recent_credential_error(tmp_path,'bad-key')=='VWorld 인증 실패: provider_code=INVALID_KEY'
    with pytest.raises(ExternalError,match='인증'):
        client.get('VWorld','zoning','https://example.org/api',{'key':'bad-key'})
    assert len(calls)==1

def test_a_provider_description_page_listing_error_codes_is_not_an_api_failure(tmp_path):
    page=b'<html>const swaggerJson = `{}`; error codes: SERVICE_KEY_IS_NOT_REGISTERED LIMITED_NUMBER</html>'
    calls=[]
    def send(request):
        calls.append(request)
        return httpx.Response(200,content=page)
    client=CachedClient(tmp_path,httpx.Client(transport=httpx.MockTransport(send)),min_interval=0)
    assert client.get('data.go.kr','definition','https://www.data.go.kr/data/1/openapi.do',api=False)['body']==page
    with pytest.raises(ExternalError):  # the same text inside an API answer is a real failure
        client.get('data.go.kr','api','https://apis.example.org/x',{'serviceKey':'k'})


def test_error_index_replaces_the_folder_scan(tmp_path, monkeypatch):
    """Errors are found through the small index; a later success on the same request clears them."""
    import app.cache as cache
    answers = [httpx.Response(200, content=b'LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR'), httpx.Response(200, content=b'<ok/>')]
    client = CachedClient(tmp_path, httpx.Client(transport=httpx.MockTransport(lambda request: answers.pop(0))), min_interval=0)
    try:
        client.get('data.go.kr', 'op', 'https://example.org/api', {'serviceKey': 'k1'})
        raise AssertionError('the rate-limit answer must raise')
    except ExternalError as exc:
        assert '호출 제한' in str(exc)
        failed = exc.asset
    index = tmp_path / cache.ERROR_INDEX
    assert index.exists() and 'serviceKey' not in index.read_text(encoding='utf-8') and 'k1' not in index.read_text(encoding='utf-8')
    scanned = []
    monkeypatch.setattr(cache, '_scan_error_metas', lambda *a: scanned.append(a) or [])
    cache._forget_error_scan(tmp_path)
    assert recent_credential_error(tmp_path, 'k1') == '공공데이터 호출 제한'
    assert scanned == []  # the index was used, not a directory listing
    # the same request succeeds later (after forget): the stale index line must not report an error
    client.forget(failed)
    assert client.get('data.go.kr', 'op', 'https://example.org/api', {'serviceKey': 'k1'})['body'] == b'<ok/>'
    cache._forget_error_scan(tmp_path)
    assert recent_credential_error(tmp_path, 'k1') is None


def test_folder_without_index_is_scanned_once_and_indexed(tmp_path):
    import app.cache as cache
    auth = hashlib.sha256(b'k2').hexdigest()
    (tmp_path / 'abc.json').write_text(json.dumps({'timestamp': time.time(), 'error': 'API 인증 실패', 'auth_hash': auth}), encoding='utf-8')
    (tmp_path / 'ok.json').write_text(json.dumps({'timestamp': time.time(), 'error': None}), encoding='utf-8')
    cache._forget_error_scan(tmp_path)
    assert recent_credential_error(tmp_path, 'k2') == 'API 인증 실패'
    lines = (tmp_path / cache.ERROR_INDEX).read_text(encoding='utf-8').splitlines()
    assert len(lines) == 1 and json.loads(lines[0])['file'] == 'abc.json'
