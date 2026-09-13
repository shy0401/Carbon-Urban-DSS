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
    sid='weather_kma'
    if not db.get(DataSource,sid):
        db.add(DataSource(id=sid,category='기타 수집 데이터',name='ASOS 전주146 일별 관측',organization='기상청',source_url='https://www.data.go.kr/data/15059093/openapi.do',status='NEEDS_API_APPROVAL',limitation='별도 ASOS 활용 승인 필요. 일별 자료가 완전한 월만 ERA5-Land 월 집계를 대체합니다.'));db.commit()
    spec=official_spec('15059093','kma-asos');url=verified_operation(spec,'getWthrDataList')
    key=unquote(os.getenv('DATA_GO_KR_SERVICE_KEY','').strip())
    params=dict(serviceKey=key,dataType='JSON',dataCd='ASOS',dateCd='DAY',startDt=f'{year}0101',endDt=f'{year}1231',stnIds='146',numOfRows=1,pageNo=1)
    try:
        result=client.get('KMA','ASOS_daily',url,params);rows,total=parse_energy(result['body']);record_asset(db,sid,result,len(rows),str(year))
        if total>1:
            result=client.get('KMA','ASOS_daily',url,dict(params,numOfRows=999));rows,total=parse_energy(result['body']);record_asset(db,sid,result,len(rows),str(year))
        def num(value):
            try:return float(value) if value not in (None,'') else None
            except ValueError:return None
        daily={'time':[r['tm'] for r in rows]}
        for output,field in [('temperature_2m_mean','avgTa'),('temperature_2m_min','minTa'),('temperature_2m_max','maxTa'),('precipitation_sum','sumRn')]:daily[output]=[num(r.get(field)) for r in rows]
        normalized=monthly_weather({'daily':daily})
        replaced=0
        for row in normalized:
            if row['days_observed']==row['expected_days'] and row['precipitation'] is not None:
                db.merge(WeatherMonthly(**row,provider='KMA ASOS station146',source_type='OFFICIAL',latitude=35.84092,longitude=127.11718));replaced+=1
        update_source(db,sid,len(rows),status='COLLECTED' if len(rows)>=365 else 'PARTIAL',quality=f'{replaced}개 완전한 월을 공식 관측으로 대체')
        return replaced
    except ExternalError as exc:
        if exc.asset:record_asset(db,sid,exc.asset,0,str(year),'FAILED',str(exc))
        s=db.get(DataSource,sid);s.status='NEEDS_API_APPROVAL' if '인증' in str(exc) else 'FAILED';s.quality=str(exc);db.commit();raise
