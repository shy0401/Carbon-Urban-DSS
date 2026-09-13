from .models import DataSource

SOURCES=[
dict(id='energy',category='건물 에너지',name='건축HUB 지번별 월간 전기·가스 사용량',organization='국토교통부 / 한국부동산원',source_url='https://www.data.go.kr/data/15135963/openapi.do',limitation='단독주택·200세대 미만 공동주택 제외. 지번별 자료이며 격자 전체 소비량이 아닙니다.'),
dict(id='buildings',category='건축물 정보',name='OSM 공동주택 건물 윤곽 및 층수',organization='OpenStreetMap contributors',source_url='https://www.openstreetmap.org/copyright',source_type='FALLBACK',limitation='커뮤니티 매핑 자료. 공식 건축물대장·지적 경계가 아닙니다. 층수 누락 시 연면적을 추정하지 않습니다.'),
dict(id='zoning',category='용도지역',name='VWorld 용도지역 지구도',organization='국토교통부 / VWorld',source_url='https://www.vworld.kr/dev/v4dv_2ddataguide2_s002.do',status='NEEDS_API_KEY',limitation='VWORLD_API_KEY 필요. OSM residential은 법정 용도지역으로 대체하지 않습니다.'),
dict(id='population',category='인구',name='SGIS 500m 인구격자',organization='국가데이터처 / SGIS',source_url='https://sgis.kostat.go.kr/developer/html/newOpenApi/api/dataApi/census.html',status='NEEDS_API_KEY',limitation='SGIS consumer key/secret 또는 승인 다운로드 필요. 격자 인구를 임의 배분하지 않습니다.'),
dict(id='weather',category='기상',name='ERA5-Land 2025 일별 기상 → 월별 집계',organization='Copernicus C3S / ECMWF via Open-Meteo',source_url='https://open-meteo.com/en/docs/historical-weather-api',source_type='FALLBACK',limitation='약 0.1도 재분석 격자. KMA 관측소 실측이 아닙니다. HDD/CDD 기준 18°C.'),
dict(id='factors',category='배출계수',name='한국 공식 에너지 배출계수',organization='온실가스종합정보센터 / 한국에너지공단',source_url='https://www.gir.go.kr/home/board/read.do?pagerOffset=0&maxPageItems=10&maxIndexPages=10&searchKey=&searchValue=&menuId=36&boardId=72&boardMasterId=2&boardCategoryId=',status='MANUAL_DOWNLOAD_REQUIRED',limitation='공식 배출계수 확인 필요. 출처·단위·적용 연도 검증 후 계산합니다.'),
dict(id='grid',category='격자',name='EPSG:5179 정렬 500m 분석 격자',organization='Carbon Urban DSS / PyProj',source_url='https://epsg.io/5179',source_type='DERIVED',limitation='정확히 500×500m로 생성한 프로토타입 격자. NGII 공식 격자 ID가 아닙니다.'),
dict(id='regions',category='기타 수집 데이터',name='법정동 코드 전체자료 — 전주시 현행 코드',organization='행정안전부 행정표준코드관리시스템',source_url='https://www.code.go.kr/stdcode/regCodeL.do',reference_period='수집 시점 현행 코드',limitation='현재 존재하는 전주시 법정동. 코드 파일 SHA256을 버전으로 보존합니다.'),
dict(id='boundary',category='기타 수집 데이터',name='전주시 행정경계',organization='OpenStreetMap contributors',source_url='https://www.openstreetmap.org/copyright',source_type='FALLBACK',reference_period='수집 시점 OSM',limitation='공식 지적경계가 아닌 공개 지도 경계입니다.'),
dict(id='building_official',category='기타 수집 데이터',name='건축HUB 건축물대장',organization='국토교통부',source_url='https://www.data.go.kr/data/15134735/openapi.do',status='NEEDS_API_KEY',limitation='별도 서비스 활용 승인 필요. 공식 연면적·용적률이 없으면 현재 FAR를 표시하지 않습니다.'),
]

def seed_sources(db):
    for item in SOURCES:
        current=db.get(DataSource,item['id'])
        if not current: db.add(DataSource(**item))
        elif current.status=='CONNECTED' and current.normalized_row_count==0:
            current.status='NOT_COLLECTED'
    db.commit()
