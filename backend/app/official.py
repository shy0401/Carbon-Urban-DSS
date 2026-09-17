"""Prepared official-source adapters. Service approval is tested separately."""
import json,re,os,calendar
from urllib.parse import unquote
from sqlalchemy import select,JSON,String,Integer
from sqlalchemy.orm import Mapped,mapped_column
from .db import Base
from .models import DataSource,Region,WeatherMonthly,now
from .collectors import client,RAW,record_asset,update_source
from .cache import ExternalError
from .domain import parse_energy,monthly_weather,number

class BuildingRegister(Base):
    __tablename__='building_register'
    id:Mapped[str]=mapped_column(String,primary_key=True)
    parcel_code:Mapped[str]=mapped_column(String)
    source:Mapped[str]=mapped_column(String)
    reference_period:Mapped[str]=mapped_column(String)
    attributes:Mapped[dict]=mapped_column(JSON)
    raw_record:Mapped[dict]=mapped_column(JSON)

def official_spec(dataset_id,name):
    path=RAW/(name+'-swagger.json')
    if path.exists():return json.loads(path.read_text(encoding='utf-8'))
    result=client.get('data.go.kr',name+'-definition',f'https://www.data.go.kr/data/{dataset_id}/openapi.do')
    html=result['body'].decode('utf-8');(RAW/(name+'-definition.html')).write_text(html,encoding='utf-8')
    match=re.search(r'const swaggerJson = `(.+?)`;',html,re.S)
    if not match:raise ExternalError('공식 API Swagger 명세를 확인할 수 없습니다')
    spec=json.loads(match.group(1).replace('\\\\','\\'));path.write_text(json.dumps(spec,ensure_ascii=False,indent=2),encoding='utf-8');return spec

def verified_operation(spec,operation):
    path=next((p for p in spec.get('paths',{}) if p.rstrip('/').split('/')[-1]==operation),None)
    if not path:raise ExternalError('요청 operation이 공식 명세에 없습니다')
    return 'https://'+spec['host'].rstrip('/')+spec.get('basePath','').rstrip('/')+path

def normalize_register(raw):
    mapping={'site_area_m2':'platArea','building_area_m2':'archArea','gross_floor_area_m2':'totArea','far_assessment_floor_area_m2':'vlRatEstmTotArea','observed_current_far':'vlRat','observed_current_bcr':'bcRat','floors':'grndFlrCnt','height_m':'heit','households':'hhldCnt'}
    return dict({key:number(raw.get(field)) for key,field in mapping.items()},building_use=raw.get('mainPurpsCdNm'),approval_date=raw.get('useAprDay'),name=raw.get('bldNm'),legal_far_limit=None,legal_bcr_limit=None)

def collect_register(db,parcels=None):
    sid='building_official';spec=official_spec('15134735','building-register')
    url=verified_operation(spec,'getBrTitleInfo')
    key=unquote(os.getenv('DATA_GO_KR_SERVICE_KEY','').strip())
    if not key:raise ExternalError('NEEDS_API_APPROVAL: 건축물대장 API 키·활용 승인 필요')
    if not parcels:
        region=db.scalar(select(Region).where(Region.bjdong_code!='00000').order_by(Region.code))
        if not region:raise ExternalError('법정동 코드 필요')
        parcels=[dict(sigunguCd=region.sigungu_code,bjdongCd=region.bjdong_code)]
    count=0
    for parcel in parcels[:8]:
        params=dict(parcel,serviceKey=key,numOfRows=1,pageNo=1)
        try:
            result=client.get('MOLIT','getBrTitleInfo',url,params);rows,total=parse_energy(result['body'])
            record_asset(db,sid,result,len(rows),'수집 시점 건축물대장')
            if total>1:
                result=client.get('MOLIT','getBrTitleInfo',url,dict(params,numOfRows=1000));rows,total=parse_energy(result['body']);record_asset(db,sid,result,len(rows),'수집 시점 건축물대장')
            for raw in rows:
                raw.pop('usage_kwh',None)
                pnu=(raw.get('sigunguCd') or parcel['sigunguCd'])+(raw.get('bjdongCd') or parcel['bjdongCd'])+str(raw.get('platGbCd') or '0')+str(raw.get('bun') or '').zfill(4)+str(raw.get('ji') or '').zfill(4)
                ident=raw.get('mgmBldrgstPk') or pnu+'-'+str(raw.get('rnum'))
                db.merge(BuildingRegister(id=ident,parcel_code=pnu,source='국토교통부 건축HUB',reference_period=now().date().isoformat(),attributes=normalize_register(raw),raw_record=raw));count+=1
            db.commit()
        except ExternalError as exc:
            if exc.asset:record_asset(db,sid,exc.asset,0,'수집 시점','FAILED',str(exc))
            source=db.get(DataSource,sid);source.status='NEEDS_API_APPROVAL' if '인증' in str(exc) else 'FAILED';source.quality=str(exc);db.commit();raise
    total=db.query(BuildingRegister).count();update_source(db,sid,total,status='PARTIAL' if count else 'CONNECTED',quality='공식 건축물대장 / 제한된 후보 지번 수집')
    return count

def collect_kma(db,year=2025):
    from .kma_asos import collect_asos
    return collect_asos(db,year,'full')['complete_months']
