import httpx,pytest
from app.cache import CachedClient,ExternalError

def test_offline_never_calls_network_but_reuses_verified_cache(tmp_path,monkeypatch):
    monkeypatch.setenv('DEMO_OFFLINE_MODE','false')
    monkeypatch.setattr('app.settings.DATA_DIR',tmp_path)
    calls=[]
    def handler(request):
        calls.append(request);return httpx.Response(200,content=b'{"actual":12}')
    client=CachedClient(tmp_path,httpx.Client(transport=httpx.MockTransport(handler)),min_interval=0)
    client.get('weather','historical','https://example.org',{'year':2025})
    monkeypatch.setenv('DEMO_OFFLINE_MODE','true')
    assert client.get('weather','historical','https://example.org',{'year':2025})['cached']
    with pytest.raises(ExternalError,match='오프라인'):
        client.get('weather','historical','https://example.org',{'year':2024})
    assert len(calls)==1
