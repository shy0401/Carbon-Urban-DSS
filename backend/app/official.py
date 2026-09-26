"""Prepared official-source adapters. Service approval is tested separately."""
import json,re,os,calendar,time
from urllib.parse import unquote
from sqlalchemy import select,JSON,String,Integer
from sqlalchemy.orm import Mapped,mapped_column
from .db import Base
from .models import DataSource,Region,WeatherMonthly,now
from .collectors import client,RAW,record_asset,update_source
from .cache import ExternalError,parse_cached_response
from .domain import parse_energy,monthly_weather,number

class BuildingRegister(Base):
    """건축물대장 표제부 한 동. ``parcel_code`` is the 19-digit PNU (land type 1=일반, 2=산).

    ``grid_id`` is filled from the cadastral parcel (VWorld 연속지적) or, for apartments,
    from the matching K-apt complex; it stays null when neither is available.
    """
    __tablename__='building_register'
    id:Mapped[str]=mapped_column(String,primary_key=True)
    parcel_code:Mapped[str]=mapped_column(String)
    source:Mapped[str]=mapped_column(String)
    reference_period:Mapped[str]=mapped_column(String)
    attributes:Mapped[dict]=mapped_column(JSON)
    raw_record:Mapped[dict]=mapped_column(JSON)
    grid_id:Mapped[str|None]=mapped_column(String,nullable=True)
    approval_year:Mapped[int|None]=mapped_column(Integer,nullable=True)

def official_spec(dataset_id,name):
    path=RAW/(name+'-swagger.json')
    if path.exists():return json.loads(path.read_text(encoding='utf-8'))
    result=client.get('data.go.kr',name+'-definition',f'https://www.data.go.kr/data/{dataset_id}/openapi.do',api=False)
    html=result['body'].decode('utf-8');(RAW/(name+'-definition.html')).write_text(html,encoding='utf-8')
    match=re.search(r'const swaggerJson = `(.+?)`;',html,re.S)
    if not match:raise ExternalError('공식 API Swagger 명세를 확인할 수 없습니다')
    spec=json.loads(match.group(1).replace('\\\\','\\'));path.write_text(json.dumps(spec,ensure_ascii=False,indent=2),encoding='utf-8');return spec

def verified_operation(spec,operation):
    path=next((p for p in spec.get('paths',{}) if p.rstrip('/').split('/')[-1]==operation),None)
    if not path:raise ExternalError('요청 operation이 공식 명세에 없습니다')
    return 'https://'+spec['host'].rstrip('/')+spec.get('basePath','').rstrip('/')+path

REGISTER_NUMERIC={'site_area_m2':'platArea','building_area_m2':'archArea','gross_floor_area_m2':'totArea','far_assessment_floor_area_m2':'vlRatEstmTotArea',
    'observed_current_far':'vlRat','observed_current_bcr':'bcRat','floors':'grndFlrCnt','underground_floors':'ugrndFlrCnt','height_m':'heit',
    'households':'hhldCnt','families':'fmlyCnt','units':'hoCnt','energy_saving_rate':'engrRat','epi_score':'engrEpi'}
REGISTER_TEXT={'building_use':'mainPurpsCdNm','use_code':'mainPurpsCd','structure':'strctCdNm','roof':'roofCdNm','approval_date':'useAprDay',
    'permit_date':'pmsDay','construction_start':'stcnsDay','energy_grade':'engrGrade','green_grade':'gnBldGrade','intelligent_grade':'itgBldGrade',
    'name':'bldNm','dong':'dongNm','main_or_annex':'mainAtchGbCdNm','register_kind':'regstrKindCdNm','address':'platPlc','road_address':'newPlatPlc'}

def _text(value):
    text=str(value).strip() if value is not None else ''
    return text or None

def normalize_register(raw):
    """Register 표제부 fields that matter for floor area, age, structure and energy performance.

    Blank values stay None (never 0). Legal FAR/BCR limits are not in the register and stay None.
    """
    out={key:number(raw.get(field)) for key,field in REGISTER_NUMERIC.items()}
    out.update({key:_text(raw.get(field)) for key,field in REGISTER_TEXT.items()})
    out.update(legal_far_limit=None,legal_bcr_limit=None)
    return out

def register_pnu(raw,region=None):
    """19-digit PNU: 시군구5 + 법정동5 + 대지구분(1 일반, 2 산) + 본번4 + 부번4. 건축물대장 platGbCd: 0 대지, 1 산, 2 블록."""
    region=region or {}
    sigungu=str(raw.get('sigunguCd') or region.get('sigunguCd') or '').strip()
    bjdong=str(raw.get('bjdongCd') or region.get('bjdongCd') or '').strip()
    land='2' if str(raw.get('platGbCd') or '0').strip()=='1' else '1'
    bun=re.sub(r'\D','',str(raw.get('bun') or '')).zfill(4)[-4:]
    ji=re.sub(r'\D','',str(raw.get('ji') or '')).zfill(4)[-4:]
    return sigungu+bjdong+land+bun+ji

def approval_year_of(value):
    digits=re.sub(r'\D','',str(value or ''))
    if len(digits)<4:return None
    year=int(digits[:4])
    return year if 1900<=year<=now().year else None

REGISTER_TRANSIENT={'01','02','04','05','99'}
REGISTER_AUTH={'20','21','30','31','32'}
REGISTER_PAGE=100

def _register_request(url,params,attempts=3):
    """One 표제부 page; temporary provider failures are retried without keeping the cached failure."""
    for attempt in range(attempts):
        response=None
        try:
            response=client.get('MOLIT','getBrTitleInfo',url,params)
            return response,parse_cached_response(client,response,parse_energy)
        except (ExternalError,ValueError) as exc:
            message=str(exc);code=message.split(':',1)[0].strip()
            cached=response or getattr(exc,'asset',None)
            if code in REGISTER_AUTH or '인증 실패' in message:
                raise ExternalError('API 인증 실패: 건축HUB 건축물대장(15134735) 활용신청 승인과 DATA_GO_KR_SERVICE_KEY를 확인하세요',cached) from None
            if code=='22' or '호출 제한' in message or 'LIMITED_NUMBER' in message:
                raise ExternalError('건축물대장 일일 호출 한도 초과(22): 성공한 페이지는 캐시되므로 다음 날 이어서 수집합니다',cached) from None
            transient=code in REGISTER_TRANSIENT or '외부 데이터 HTTP 5' in message or '연결 실패' in message
            if not transient:
                raise ExternalError(f'건축물대장 응답 오류: {message[:80]}',cached) from None
            if isinstance(cached,dict):client.forget(cached)
            if attempt==attempts-1:
                raise ExternalError(f'건축물대장 제공기관 일시 오류: {message[:60]}',cached) from None
            time.sleep(2*(attempt+1))

def register_regions(db,scope='full'):
    rows=list(db.scalars(select(Region).where(Region.bjdong_code!='00000').order_by(Region.code)))
    regions=[dict(sigunguCd=r.sigungu_code,bjdongCd=r.bjdong_code,name=r.name) for r in rows]
    return regions[:{'smoke':1,'limited':3}.get(scope,len(regions))]

def collect_register(db,scope='full',progress=None):
    """건축HUB 건축물대장 표제부(getBrTitleInfo) for every 전주시 법정동, all pages.

    smoke: first 법정동, first page (10 rows) / limited: 3 법정동 / full: every 법정동.
    Successful pages are cached, so a rerun after a quota stop continues without re-requesting them.
    """
    sid='building_official'
    key=unquote(os.getenv('DATA_GO_KR_SERVICE_KEY','').strip())
    if not key:raise ExternalError('API 인증 실패: DATA_GO_KR_SERVICE_KEY 미설정')
    spec=official_spec('15134735','building-register')
    url=verified_operation(spec,'getBrTitleInfo')
    regions=register_regions(db,scope)
    if not regions:raise ExternalError('법정동 코드가 없습니다. 지역코드 수집 필요')
    client.min_interval=max(float(os.getenv('BUILDING_REGISTER_REQUEST_DELAY_MS','300'))/1000,0)
    rows_saved=0;failed=[];reference=now().date().isoformat()
    for index,region in enumerate(regions):
        page=1;size=10 if scope=='smoke' else REGISTER_PAGE
        while True:
            params=dict(serviceKey=key,sigunguCd=region['sigunguCd'],bjdongCd=region['bjdongCd'],numOfRows=size,pageNo=page,_type='json')
            try:
                response,(rows,total)=_register_request(url,params)
            except ExternalError as exc:
                if exc.asset:record_asset(db,sid,exc.asset,0,reference,'FAILED',str(exc))
                db.commit()
                if '일시 오류' not in str(exc):
                    source=db.get(DataSource,sid)
                    if source:source.status='NEEDS_API_APPROVAL' if '인증' in str(exc) else 'PARTIAL' if source.normalized_row_count else 'FAILED';source.quality=str(exc)[:200];db.commit()
                    raise
                failed.append(f"{region['name']} {page}쪽");break
            record_asset(db,sid,response,len(rows),reference)
            for raw in rows:
                raw=dict(raw);raw.pop('usage_kwh',None)
                pnu=register_pnu(raw,region)
                ident=str(raw.get('mgmBldrgstPk') or f"{pnu}-{raw.get('dongNm') or ''}-{raw.get('rnum')}")
                attributes=normalize_register(raw)
                item=db.get(BuildingRegister,ident) or BuildingRegister(id=ident)
                item.parcel_code=pnu;item.source='국토교통부 건축HUB 건축물대장';item.reference_period=reference
                item.attributes=attributes;item.raw_record=raw;item.approval_year=approval_year_of(attributes['approval_date'])
                db.merge(item);rows_saved+=1
            db.commit()
            if scope=='smoke' or not rows or page*size>=total:break
            page+=1
        if progress:progress((index+1)/len(regions),f"건축물대장 {region['name']} ({index+1}/{len(regions)})")
    linked=link_register_grids(db)
    total_rows=db.query(BuildingRegister).count()
    status='COLLECTED' if scope=='full' and not failed else 'PARTIAL'
    update_source(db,sid,total_rows,status=status,quality=f'표제부 {total_rows:,}동 / 법정동 {len(regions)}곳({scope}) / 격자 연결 {linked:,}동 / 일시 오류 {len(failed)}건')
    return {'rows':rows_saved,'regions':len(regions),'failed':len(failed),'linked':linked,'total':total_rows}

def link_register_grids(db):
    """Attach 500m grids: cadastral parcel point-on-surface first, then the K-apt complex on the same parcel."""
    from sqlalchemy import text
    linked=0
    try:
        with db.begin_nested():
            result=db.execute(text(
                "UPDATE building_register b SET grid_id=g.id FROM cadastral_parcels c JOIN grid_500m g "
                "ON ST_Contains(g.geom, ST_PointOnSurface(c.geom)) WHERE b.grid_id IS NULL AND b.parcel_code=c.pnu"))
            linked+=result.rowcount or 0
    except Exception:  # noqa: BLE001 - PostGIS or the cadastral table may be missing; the K-apt fallback still runs
        pass
    try:
        from .kapt import ApartmentComplex
        by_parcel={}
        for c in db.scalars(select(ApartmentComplex).where(ApartmentComplex.grid_id.is_not(None),ApartmentComplex.bjd_code.is_not(None),ApartmentComplex.bun.is_not(None))):
            key=(c.bjd_code,re.sub(r'\D','',str(c.bun)).zfill(4)[-4:],re.sub(r'\D','',str(c.ji or '')).zfill(4)[-4:])
            by_parcel.setdefault(key,set()).add(c.grid_id)
        for b in db.scalars(select(BuildingRegister).where(BuildingRegister.grid_id.is_(None))):
            code=b.parcel_code or ''
            grids=by_parcel.get((code[:10],code[11:15],code[15:19]))
            if grids and len(grids)==1:
                b.grid_id=next(iter(grids));linked+=1
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
    return linked

def collect_kma(db,year=2025):
    from .kma_asos import collect_asos
    return collect_asos(db,year,'full')['complete_months']
