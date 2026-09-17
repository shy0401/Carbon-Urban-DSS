import httpx
import pytest
from app.cache import CachedClient,ExternalError

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
