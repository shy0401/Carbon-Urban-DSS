"""Disk-backed response cache. Credentials are never written, returned or logged."""
import hashlib,json,time,os
from pathlib import Path
import httpx

SECRET_PARAM_NAMES={
    'servicekey','apikey','key','authkey','consumer_key','consumer_secret',
    'accesstoken','access_token','token',
}

ERROR_CACHE_SECONDS = 3600

def _is_secret(name):
    return str(name).replace('-','_').casefold() in SECRET_PARAM_NAMES

def recent_credential_error(root, credential, max_age=ERROR_CACHE_SECONDS, match=None):
    """Return a sanitized recent error recorded for this exact credential.

    ``match`` optionally narrows the check to cached requests whose public
    metadata still applies (e.g. the same VWorld domain).
    """
    if not credential:
        return None
    auth_hash=hashlib.sha256(str(credential).encode()).hexdigest()
    for meta in _recent_error_metas(root,max_age):
        try:
            if (meta.get('auth_hash')==auth_hash
                    and time.time()-float(meta.get('timestamp',0))<max_age
                    and (match is None or match(meta))):
                return str(meta['error'])
        except (ValueError,TypeError):
            continue
    return None

_ERROR_SCAN={}
_ERROR_SCAN_TTL=60

def _recent_error_metas(root,max_age):
    """Error metadata written within ``max_age`` seconds.

    The cache folders hold tens of thousands of responses on a slow Windows bind mount, so
    files are first filtered by modification time (a stat, no read) and the result is reused
    for a minute. A new error written by this process clears the memo (see CachedClient).
    """
    key=(str(Path(root)),max_age)
    hit=_ERROR_SCAN.get(key)
    if hit and time.monotonic()-hit[0]<_ERROR_SCAN_TTL:
        return hit[1]
    cutoff=time.time()-max_age
    found=[]
    try:
        entries=list(os.scandir(root))
    except OSError:
        entries=[]
    for entry in entries:
        if not entry.name.endswith('.json'):
            continue
        try:
            if entry.stat().st_mtime<cutoff:
                continue
            meta=json.loads(Path(entry.path).read_text(encoding='utf-8'))
        except (OSError,ValueError,TypeError,json.JSONDecodeError):
            continue
        if isinstance(meta,dict) and meta.get('error'):
            found.append(meta)
    _ERROR_SCAN[key]=(time.monotonic(),found)
    return found

def _forget_error_scan(root):
    for key in [k for k in _ERROR_SCAN if k[0]==str(Path(root))]:
        _ERROR_SCAN.pop(key,None)

def record_credential_error(root, credential, message):
    """Persist only a credential digest and sanitized error for short cooldowns."""
    target=Path(root);target.mkdir(parents=True,exist_ok=True)
    meta={
        'timestamp':time.time(),
        'error':str(message),
        'auth_hash':hashlib.sha256(str(credential).encode()).hexdigest(),
    }
    (target/'credential-error.json').write_text(json.dumps(meta,ensure_ascii=False),encoding='utf-8')
    _forget_error_scan(target)

def clear_credential_error(root, credential):
    target=Path(root)/'credential-error.json'
    if not target.exists():return
    try:meta=json.loads(target.read_text(encoding='utf-8'))
    except (OSError,ValueError,TypeError,json.JSONDecodeError):return
    if meta.get('auth_hash')==hashlib.sha256(str(credential).encode()).hexdigest():
        target.unlink(missing_ok=True);_forget_error_scan(Path(root))

class ExternalError(RuntimeError):
    def __init__(self,message,asset=None):
        super().__init__(message);self.asset=asset

class CachedClient:
    def __init__(self,root,client=None,min_interval=1.1):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self._own_client=client is None
        self.client=client or self._new_client()
        self.min_interval=min_interval;self.last_request=0

    @staticmethod
    def _new_client():
        return httpx.Client(timeout=60,follow_redirects=True,headers={'User-Agent':'CarbonUrbanDSS/0.1 educational capstone'})

    def reset_connection(self):
        """Open a new connection for the next request.

        The data.go.kr gateway keeps a connection on one backend node; when that node answers
        "04 HTTP_ERROR" every request on the connection fails (measured 2026-09-26: 0/20 on one
        kept-alive connection, 20/20 on another, about half on fresh ones). A retry on a new
        connection can reach a healthy node."""
        if not self._own_client:
            return
        try:
            self.client.close()
        except Exception:  # noqa: BLE001
            pass
        self.client=self._new_client()

    def get(self,provider,operation,url,params=None,api=True):
        """``api=False`` for a plain web page (e.g. a data.go.kr API description page): only the HTTP
        status decides failure. Such pages list the provider error codes (SERVICE_KEY_IS_NOT_REGISTERED,
        LIMITED_NUMBER...) in their text, which must not be read as an answer from the API itself."""
        params=params or {}
        public={k:v for k,v in params.items() if not _is_secret(k)}
        identity=dict(provider=provider,operation=operation,url=url,params=public)
        digest=hashlib.sha256(json.dumps(identity,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        meta_path=self.root/(digest+'.json');body_path=self.root/(digest+'.body')
        # Error cache is tied to a non-reversible credential digest; replacing a key permits a fresh probe.
        credential_values=[str(value) for key,value in sorted(params.items()) if _is_secret(key)]
        credential_fingerprint='|'.join(credential_values)
        auth_hash=hashlib.sha256(credential_fingerprint.encode()).hexdigest()
        if meta_path.exists() and body_path.exists():
            meta=json.loads(meta_path.read_text(encoding='utf-8'))
            same_credential=not credential_values or meta.get('auth_hash')==auth_hash
            if same_credential and (not meta.get('error') or (api and time.time()-meta['timestamp']<ERROR_CACHE_SECONDS)):
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
                    if _is_secret(k) and v:
                        body=body.replace(str(v).encode(),b'[REDACTED]')
                status=response.status_code
                error=None
                if status in (401,403) or (api and (b'SERVICE_KEY_IS_NOT_REGISTERED' in body or b'SERVICE_ACCESS_DENIED' in body)):
                    error='API 인증 실패: 서비스 승인 및 DATA_GO_KR_SERVICE_KEY 확인 필요 (30/20)'
                elif status==429 or (api and b'LIMITED_NUMBER' in body): error='공공데이터 호출 제한'
                elif status>=400: error=f'외부 데이터 HTTP {status}'
                if status>=500 and attempt<2:
                    time.sleep(2**(attempt+1));continue
                meta=dict(identity,timestamp=time.time(),status=status,error=error,auth_hash=auth_hash)
                body_path.write_bytes(body);meta_path.write_text(json.dumps(meta,ensure_ascii=False),encoding='utf-8')
                if error:_forget_error_scan(self.root)
                result=dict(meta,body=body,cached=False,path=str(body_path),id=digest)
                if error: raise ExternalError(error,result)
                return result
            except httpx.RequestError:
                if attempt<2: time.sleep(2**(attempt+1));continue
                raise ExternalError('외부 서비스 연결 실패 또는 시간 초과') from None

    def forget(self,result):
        """Drop one cached response (used to retry a temporary provider failure)."""
        ident=result.get('id') if isinstance(result,dict) else None
        if not ident:return
        for suffix in ('.json','.body'):
            (self.root/(str(ident)+suffix)).unlink(missing_ok=True)

    def record_error(self,result,message):
        ident=result.get('id') if isinstance(result,dict) else None
        if not ident:return
        meta_path=self.root/(str(ident)+'.json')
        if not meta_path.exists():return
        try:meta=json.loads(meta_path.read_text(encoding='utf-8'))
        except (OSError,ValueError,TypeError,json.JSONDecodeError):return
        meta['timestamp']=time.time();meta['error']=str(message)
        meta_path.write_text(json.dumps(meta,ensure_ascii=False),encoding='utf-8')
        _forget_error_scan(self.root)

def parse_cached_response(client,result,parser):
    try:return parser(result['body'])
    except (ExternalError,ValueError) as exc:
        recorder=getattr(client,'record_error',None)
        if recorder:recorder(result,str(exc))
        raise
