"""Small credential-safe discovery requests; persisted responses never contain request keys."""
import json, re, urllib.request, urllib.parse, pathlib, os, sys, time
ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / 'data/raw'
OUT.mkdir(parents=True, exist_ok=True)
def fetch(name, url, params=None):
    target = OUT / name
    if target.exists():
        return target.read_bytes()
    req = urllib.request.Request(url + ('?' + urllib.parse.urlencode(params) if params else ''), headers={'User-Agent':'CarbonUrbanDSS-capstone/0.1 (local educational research)'})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read()
        target.write_bytes(body)
        print(name, 'bytes', len(body))
        return body
    except Exception as e:
        print(name, 'failed', type(e).__name__, getattr(e,'code',''))
        if hasattr(e,'read'):
            err=e.read().decode('utf-8',errors='replace')
            if params and params.get('serviceKey'): err=err.replace(params['serviceKey'],'[REDACTED]')
            (OUT/(name+'.error.txt')).write_text(err,encoding='utf-8')
            print(err[:500])
        return b''
if __name__ == '__main__':
    mode=sys.argv[1] if len(sys.argv)>1 else 'spec'
    if mode=='spec':
        page=(OUT/'energy-definition.html').read_text(encoding='utf-8')
        s=re.search(r'const swaggerJson = `(.+?)`;',page,re.S).group(1)
        spec=json.loads(s.replace('\\\\','\\'))
        (OUT/'energy-swagger.json').write_text(json.dumps(spec,ensure_ascii=False,indent=2),encoding='utf-8')
        print({k:[p['name'] for p in v['parameters']] for k,v in spec['paths'].items()})
    elif mode.startswith('energy'):
        key=os.environ.get('DATA_GO_KR_SERVICE_KEY','')
        if not key:
            for line in (ROOT/'.env').read_text(encoding='utf-8-sig').splitlines():
                if line.strip().startswith('DATA_GO_KR_SERVICE_KEY='):
                    key=line.split('=',1)[1].strip().strip('\"\'')
        print('key_present', bool(key))
        if key:
            p=dict(serviceKey=urllib.parse.unquote(key),sigunguCd='52111',bjdongCd='14000',useYm='202501',numOfRows='1',pageNo='1')
            if mode=='energy-full': p.update(bun='0000',ji='0000')
            b=fetch(mode+'-probe.xml','https://apis.data.go.kr/1613000/BldEngyHubService/getBeElctyUsgInfo',p)
            # Only response body, never request or exception URL.
            print(b.decode('utf-8',errors='replace')[:3500])
    elif mode=='spatial':
        q='[out:json][timeout:50];(way["building"="apartments"](35.77,127.03,35.90,127.19);relation["building"="apartments"](35.77,127.03,35.90,127.19);way["landuse"="residential"]["name"](35.77,127.03,35.90,127.19););out tags center geom;'
        b=fetch('osm-jeonju.json','https://overpass-api.de/api/interpreter',{'data':q})
        if b:
            j=json.loads(b);print('elements',len(j.get('elements',[])));print(json.dumps(j.get('elements',[])[:2],ensure_ascii=False)[:2500])
    elif mode=='weather':
        b=fetch('weather-2025.json','https://archive-api.open-meteo.com/v1/archive',dict(latitude=35.8242,longitude=127.1480,start_date='2025-01-01',end_date='2025-12-31',daily='temperature_2m_mean,temperature_2m_min,temperature_2m_max,precipitation_sum',timezone='Asia/Seoul',models='era5_land'))
        if b: print('days',len(json.loads(b).get('daily',{}).get('time',[])))
    elif mode=='regions':
        b=fetch('legal-dong.zip','https://www.code.go.kr/etc/codeFullDown.do',{'codeseId':'법정동코드'})
        print('signature',repr(b[:30]))
