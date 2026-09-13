"""Disk-backed response cache. Credentials are never written, returned or logged."""
import hashlib,json,time,os
from pathlib import Path
import httpx

class ExternalError(RuntimeError):
    def __init__(self,message,asset=None):
        super().__init__(message);self.asset=asset

class CachedClient:
    def __init__(self,root,client=None,min_interval=1.1):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.client=client or httpx.Client(timeout=60,follow_redirects=True,headers={'User-Agent':'CarbonUrbanDSS/0.1 educational capstone'})
        self.min_interval=min_interval;self.last_request=0

    def get(self,provider,operation,url,params=None):
        params=params or {}
        public={k:v for k,v in params.items() if k.lower() not in ('servicekey','apikey','key','authkey')}
        identity=dict(provider=provider,operation=operation,url=url,params=public)
        digest=hashlib.sha256(json.dumps(identity,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        meta_path=self.root/(digest+'.json');body_path=self.root/(digest+'.body')
        # Error cache is tied to a non-reversible credential digest; replacing a key permits a fresh probe.
        auth_hash=hashlib.sha256(str(params.get('serviceKey','')).encode()).hexdigest()
        if meta_path.exists() and body_path.exists():
            meta=json.loads(meta_path.read_text())
            if not meta.get('error') or (time.time()-meta['timestamp']<3600 and meta.get('auth_hash')==auth_hash):
                result=dict(meta,body=body_path.read_bytes(),cached=True,path=str(body_path),id=digest)
                if meta.get('error'): raise ExternalError(meta['error'],result)
                return result
        from .settings import offline_mode
        if offline_mode():
            raise ExternalError('오프라인 모드: 검증된 로컬 캐시가 없어 외부 호출을 차단했습니다.')
        for attempt in range(3):
            time.sleep(max(0,self.min_interval-(time.monotonic()-self.last_request)))
            self.last_request=time.monotonic()
            try:
                response=self.client.get(url,params=params)
                body=response.content
                for k,v in params.items():
                    if k.lower() in ('servicekey','apikey','key','authkey') and v:
                        body=body.replace(str(v).encode(),b'[REDACTED]')
                status=response.status_code
                error=None
                if status in (401,403) or b'SERVICE_KEY_IS_NOT_REGISTERED' in body or b'SERVICE_ACCESS_DENIED' in body:
                    error='API 인증 실패: 서비스 승인 및 DATA_GO_KR_SERVICE_KEY 확인 필요 (30/20)'
                elif status==429 or b'LIMITED_NUMBER' in body: error='공공데이터 호출 제한'
                elif status>=400: error=f'외부 데이터 HTTP {status}'
                if status>=500 and attempt<2:
                    time.sleep(2**(attempt+1));continue
                meta=dict(identity,timestamp=time.time(),status=status,error=error,auth_hash=auth_hash)
                body_path.write_bytes(body);meta_path.write_text(json.dumps(meta,ensure_ascii=False),encoding='utf-8')
                result=dict(meta,body=body,cached=False,path=str(body_path),id=digest)
                if error: raise ExternalError(error,result)
                return result
            except httpx.RequestError:
                if attempt<2: time.sleep(2**(attempt+1));continue
                raise ExternalError('외부 서비스 연결 실패 또는 시간 초과') from None
