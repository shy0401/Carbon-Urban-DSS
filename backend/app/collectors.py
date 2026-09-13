"""Real-source ingestion and idempotent normalization, with durable provenance."""
import calendar,hashlib,io,json,os,re,zipfile
from pathlib import Path
from urllib.parse import unquote
from datetime import datetime,timezone
from sqlalchemy import select,func
from shapely.geometry import shape
from shapely.ops import transform
from pyproj import Transformer
from geoalchemy2.shape import from_shape
from .models import *
from .cache import CachedClient,ExternalError
from .domain import parse_energy,monthly_weather,month_range

DATA=Path(os.getenv('DATA_DIR','data'));RAW=DATA/'raw';RAW.mkdir(parents=True,exist_ok=True)
client=CachedClient(DATA/'cache')

def record_asset(db,source_id,result,count,period,status='COLLECTED',error=None):
    ident=result.get('id') or hashlib.sha256(str(result['path']).encode()).hexdigest()
    source=db.get(DataSource,source_id)
    asset=db.get(RawDataAsset,ident) or RawDataAsset(id=ident,source_id=source_id,provider=source.organization,source_url=result.get('url',source.source_url),reference_period=period,storage_location=result['path'])
    asset.row_count=count;asset.collection_status=status;asset.error=error
    asset.request_parameters=result.get('params',{})
    if result.get('timestamp'): asset.collected_at=datetime.fromtimestamp(result['timestamp'],timezone.utc)
    db.add(asset);db.flush()
    return asset

def downloaded(db,source_id,name,url,params=None,period='수집 시점'):
    path=RAW/name
    if path.exists(): result=dict(body=path.read_bytes(),path=str(path),url=url,timestamp=path.stat().st_mtime)
    else:
        result=client.get(source_id,name,url,params)
        path.write_bytes(result['body'])
    return result

def update_source(db,sid,count,raw_count=None,status='COLLECTED',quality=None,missing=None):
    s=db.get(DataSource,sid);s.status=status;s.normalized_row_count=count;s.raw_row_count=raw_count if raw_count is not None else count
    s.collected_at=now();s.missing_count=missing;s.quality=quality or ('사용 가능' if count else '자료 없음')
    db.commit()

def collect_regions(db):
    result=downloaded(db,'regions','legal-dong.zip','https://www.code.go.kr/etc/codeFullDown.do',{'codeseId':'법정동코드'})
    z=zipfile.ZipFile(io.BytesIO(result['body']));text=z.read(z.namelist()[0]).decode('cp949')
    version=hashlib.sha256(result['body']).hexdigest();rows=[]
    for line in text.splitlines()[1:]:
        cols=line.split('\t')
        if len(cols)>=3 and '전주시' in cols[1] and cols[2].strip()=='존재':
            code,name,status=cols[:3]
            row=Region(code=code,sigungu_code=code[:5],bjdong_code=code[5:],name=name,source='MOIS',version=version,raw_record={'code':code,'name':name,'status':status})
            db.merge(row);rows.append(row)
    record_asset(db,'regions',result,len(rows),'현행 코드 SHA256:'+version)
    update_source(db,'regions',len(rows),len(rows),quality='공식 코드 / 파일 버전 보존',missing=0)

def collect_spatial(db):
    from .spatial import build_spatial
    query='[out:json][timeout:50];(way["building"="apartments"](35.77,127.03,35.90,127.19);relation["building"="apartments"](35.77,127.03,35.90,127.19);way["landuse"="residential"]["name"](35.77,127.03,35.90,127.19););out tags center geom;'
    result=downloaded(db,'buildings','osm-jeonju.json','https://overpass-api.de/api/interpreter',{'data':query})
    osm=json.loads(result['body'])
    boundary_path=RAW/'osm-boundary.geojson'
    boundary=json.loads(boundary_path.read_text(encoding='utf-8')) if boundary_path.exists() else None
    spatial=build_spatial(osm,boundary)
    transformer=Transformer.from_crs(4326,5179,always_xy=True).transform
    for feature in spatial['grids']['features']:
        p=feature['properties'];db.merge(Grid(id=p['id'],geom=from_shape(transform(transformer,shape(feature['geometry'])),srid=5179),area_m2=250000,properties=p,geojson=feature))
    for feature in spatial['buildings']['features']:
        p=feature['properties'];db.merge(Building(id=str(p['id']),grid_id=p.get('grid_id'),name=p.get('name') or '이름 없는 공동주택',source='OSM',source_type='FALLBACK',footprint_m2=p.get('footprint_m2'),floor_area_m2=p.get('floor_area_m2'),properties=p,geojson=feature))
    (DATA/'spatial.json').write_text(json.dumps(spatial,ensure_ascii=False),encoding='utf-8')
    record_asset(db,'buildings',result,len(osm['elements']),'OSM 수집 시점')
    record_asset(db,'grid',{'path':str(DATA/'spatial.json')},len(spatial['grids']['features']),'EPSG:5179 500m')
    if spatial['candidates']:
        top=spatial['candidates'][0]
        db.merge(TestbedSector(id='prototype',grid_id=top['grid_id'],name=top['name'],reason=top['reason']+' / 에너지 확인 후 후보 재평가',candidates=spatial['candidates'][:8],metadata_json={'selection_status':'SPATIAL_ONLY','baseline_floor_area_m2':None}))
    update_source(db,'buildings',len(spatial['buildings']['features']),len(osm['elements']),status='PARTIAL',quality='OSM 공간자료 / 층수 일부 누락')
    update_source(db,'grid',len(spatial['grids']['features']),quality='500×500m / 250,000m²',missing=0)
    if boundary:
        record_asset(db,'boundary',{'path':str(boundary_path)},len(spatial['boundary']['features']),'OSM 수집 시점')
        update_source(db,'boundary',len(spatial['boundary']['features']),quality='OSM 행정경계 / 비공식')
    else:
        s=db.get(DataSource,'boundary');s.status='PARTIAL';s.quality='연구영역 범위만 표시';s.limitation='행정경계 미확보. 지도에는 OSM 수집 연구영역을 표시합니다.';db.commit()

def collect_weather(db,start='2025-01',end='2025-12'):
    last=calendar.monthrange(int(end[:4]),int(end[5:]))[1]
    params=dict(latitude=35.8242,longitude=127.1480,start_date=start+'-01',end_date=end+f'-{last}',daily='temperature_2m_mean,temperature_2m_min,temperature_2m_max,precipitation_sum',timezone='Asia/Seoul',models='era5_land')
    result=downloaded(db,'weather',f'weather-{start[:4]}.json','https://archive-api.open-meteo.com/v1/archive',params) if start=='2025-01' and end=='2025-12' else client.get('weather','archive','https://archive-api.open-meteo.com/v1/archive',params)
    payload=json.loads(result['body']);rows=monthly_weather(payload)
    for row in rows:
        db.merge(WeatherMonthly(**row,provider='Open-Meteo / ERA5-Land',source_type='FALLBACK',latitude=payload.get('latitude',35.8242),longitude=payload.get('longitude',127.1480)))
    record_asset(db,'weather',result,len(payload['daily']['time']),start+' ~ '+end)
    db.flush();count=db.scalar(select(func.count()).select_from(WeatherMonthly))
    allrows=db.scalars(select(WeatherMonthly)).all();missing=sum(max(r.expected_days-r.days_observed,0) for r in allrows)
    update_source(db,'weather',count,sum(r.days_observed for r in allrows),status='COLLECTED' if missing==0 else 'PARTIAL',quality=f'{count}개월 / HDD·CDD 기준 18°C',missing=missing)

def energy_candidates(db):
    """Prioritize legal dongs actually represented by residential OSM buildings."""
    weights={}
    for b in db.scalars(select(Building)):
        tags=b.properties.get('tags',{})
        dong=tags.get('addr:subdistrict','')
        if dong: weights[dong]=weights.get(dong,0)+1
    regions=[r for r in db.scalars(select(Region)) if r.bjdong_code!='00000']
    regions.sort(key=lambda r:(-weights.get(r.name.split()[-1],0),r.code))
    return regions[:3]

def collect_energy(db,start='2025-01',end='2025-12',progress=None):
    key=unquote(os.environ.get('DATA_GO_KR_SERVICE_KEY','').strip())
    if not key: raise ExternalError('API 인증 실패: DATA_GO_KR_SERVICE_KEY 미설정')
    operations={'ELECTRICITY':'getBeElctyUsgInfo','GAS':'getBeGasUsgInfo'}
    # Only declared operations in the downloaded official Swagger may be used.
    spec_path=RAW/'energy-swagger.json'
    if not spec_path.exists():
        definition=client.get('molit','definition','https://www.data.go.kr/data/15135963/openapi.do')
        match=re.search(r'const swaggerJson = `(.+?)`;',definition['body'].decode(),re.S)
        if not match: raise ExternalError('공식 API 명세 검증 실패')
        spec=json.loads(match.group(1).replace('\\\\','\\'));spec_path.write_text(json.dumps(spec,ensure_ascii=False),encoding='utf-8')
    spec=json.loads(spec_path.read_text(encoding='utf-8'))
    if not all('/'+o in spec['paths'] for o in operations.values()): raise ExternalError('공식 API operation 불일치')
    from .kapt import candidate_energy_parcels
    candidates=candidate_energy_parcels(db,limit=3)
    if not candidates: raise ExternalError('법정동 코드가 없습니다. 지역코드 수집 필요')
    periods=month_range(start,end);done=0;errors=[]
    for region in candidates:
        for ym in periods:
            for energy_type,operation in operations.items():
                params=dict(serviceKey=key,**{key:region[key] for key in ('sigunguCd','bjdongCd','bun','ji')},useYm=ym,numOfRows=1000,pageNo=1)
                # Initial smallest possible probe. No duplicate identical historical requests.
                probe=dict(params,numOfRows=1)
                if done==0:
                    try:
                        response=client.get('molit',operation,'https://apis.data.go.kr/1613000/BldEngyHubService/'+operation,probe)
                        rows,total=parse_energy(response['body'])
                        record_asset(db,'energy',response,len(rows),ym)
                        if total==0:
                            done+=1;continue
                    except ExternalError as exc:
                        if exc.asset: record_asset(db,'energy',exc.asset,0,ym,'FAILED',str(exc));db.commit()
                        raise
                page=1
                while page<=5:
                    params['pageNo']=page
                    try:
                        response=client.get('molit',operation,'https://apis.data.go.kr/1613000/BldEngyHubService/'+operation,params)
                        rows,total=parse_energy(response['body'])
                        record_asset(db,'energy',response,len(rows),ym)
                    except ExternalError as exc:
                        if exc.asset: record_asset(db,'energy',exc.asset,0,ym,'FAILED',str(exc))
                        db.commit();raise
                    for raw in rows:
                        values=dict(source='국토교통부 건축HUB',sigungu_code=raw.get('sigunguCd') or region['sigunguCd'],bjdong_code=raw.get('bjdongCd') or region['bjdongCd'],lot_type=raw.get('platGbCd') or '0',bun=str(raw.get('bun') or region['bun']).zfill(4),ji=str(raw.get('ji') or region['ji']).zfill(4),use_ym=raw.get('useYm') or ym,energy_type=energy_type)
                        existing=db.scalar(select(EnergyMonthly).filter_by(**{k:v for k,v in values.items() if k!='source'}))
                        if not existing: existing=EnergyMonthly(**values);db.add(existing)
                        existing.usage_kwh=raw['usage_kwh'];existing.raw_record={k:v for k,v in raw.items() if k!='usage_kwh'}
                    db.commit()
                    if page*1000>=total: break
                    page+=1
                if page>5: errors.append(f'{region.get("name",region["bjdongCd"])} {ym}: 페이지 제한 5 도달')
                done+=1
                if progress: progress(done/(len(candidates)*len(periods)*2),f'{region.get("name",region["bjdongCd"])} {ym} {energy_type}')
    count=db.scalar(select(func.count()).select_from(EnergyMonthly))
    null_count=db.scalar(select(func.count()).select_from(EnergyMonthly).where(EnergyMonthly.usage_kwh.is_(None)))
    update_source(db,'energy',count,status='PARTIAL' if count else 'CONNECTED',quality=f'{count} 관측 / 지번 좌표 매칭 확인 필요',missing=null_count)
    return errors
