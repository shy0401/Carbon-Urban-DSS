# 데이터 재설정·수집 안내

확인일: 2026-09-18. 기본 분석 범위는 전주시, 2025년 1~12월, EPSG:5179의 500m 격자다. 현재 관측이 없는 전력·가스·인구는 지도에서 ‘자료 없음’으로 표시한다. 배경지도 403과 데이터 미확보는 서로 다른 문제다.

## 이번에 직접 처리한 자료

| 자료 | 처리 결과 | 해석 범위 |
|---|---|---|
| K-apt | 공개 상세정보를 추가 수집하여 **8개 → 364개 단지**로 확대. 양수 연면적이 있는 단지는 **361개** | 목록 조회 기준 2025-12. 상세는 수집 시점 공개 정보이므로 2025년 당시 건축 상태로 단정하지 않음 |
| 기상 | 보존된 ERA5-Land 원본을 재정규화. 2025년 **12개월** 확보 | 관측소 실측이 아닌 재분석 자료. DB의 다른 연도 4개월도 보존 |
| 법정동 | 검증된 행정표준코드 원본 **86개** 재정규화 | 전주시 코드 변경에 유의. 구 단위 예: 완산구 52111, 덕진구 52113 |
| 전주시 공동주택 현황 | 원본 XLS **609건** 재정규화 | 준공 595건·공사 중 14건, 지적 경계 및 좌표 미제공 |
| 전력 배출계수 | GIR 원문과 증빙 재검증, **0.4541 kgCO₂eq/kWh** 1건 유지 | 2024 승인 소비단 계수를 2025 비교에 동일 적용하는 프로젝트 선택 |
| 공간자료 | 기존 **916개 격자·2,171개 OSM 건물·행정경계** 보존 | 자체 생성 분석격자와 OSM 도형. 공식 지적·법정 용도지역을 대체하지 않음 |

K-apt를 일부 단지만 다시 수집할 때 기존 상세정보가 지워지던 문제도 수정했다. 이미 받은 정상 원본은 재사용한다. 현재 공공데이터포털 값은 K-apt와 KMA 실제 호출에서 오류 30/20으로 거부됐고, VWorld·SGIS 인증정보는 설정돼 있지 않다.

## 1. 가장 먼저: K-apt 월별 공동주택 에너지

공식 자료: [K-apt 공동주택 에너지 사용정보](https://www.data.go.kr/data/15012964/openapi.do).

1. 공공데이터포털에서 이 서비스를 별도로 활용신청하고 승인 상태를 확인한다.
2. `.env`의 `DATA_GO_KR_SERVICE_KEY`에 포털의 일반 인증키를 설정한다. 사용하는 HTTP 클라이언트가 파라미터를 인코딩하므로 Decoding 키를 사용한다.
3. API와 worker를 재생성하고 온라인 모드를 확인한다.
4. 반드시 SMOKE 1단지×1개월을 먼저 실행한다. 성공하면 LIMITED 3단지×12개월, 그다음 FULL 364단지×12개월 순서로 확대한다.

```powershell
docker compose up -d --force-recreate api worker
docker compose exec -T api python -m app.cli online
docker compose exec -T api python -m app.cli collect --year 2025 --source kapt-energy --scope smoke
docker compose exec -T api python -m app.cli collect --year 2025 --source kapt-energy --scope limited
docker compose exec -T api python -m app.cli collect --year 2025 --source kapt-energy --scope full
```

수집기는 `serviceKey`, `kaptCode`, `reqDate`만 전송한다. 전기 `helect`는 kWh, 가스 `hgas`는 m³, 난방 `hheat`는 Mcal, 급탕 `hwaterHot`은 tonne, 수도 `hwaterCool`은 m³로 각각 저장하며 비용 필드와 혼합하지 않는다. 전기만 검증된 0.4541 kgCO₂eq/kWh 계수에 연결한다. FULL 최초 상한은 약 4,368회지만 성공 월은 재호출하지 않으므로 SMOKE/LIMITED 성공분을 건너뛴다.

## 2. 건축HUB 월별 전력·가스

공식 자료: [국토교통부 건축HUB 건물에너지정보](https://www.data.go.kr/data/15135963/openapi.do).

1. 공공데이터포털에 본인 계정으로 로그인한다.
2. 위 서비스에서 **활용신청**을 누르고 캡스톤의 목적·이용 범위를 작성한다.
3. 마이페이지의 해당 API 신청이 승인 상태인지 확인한다. 발급받은 일반 인증키의 Decoding 값을 사용한다.
4. 프로젝트 루트 `.env`의 `DATA_GO_KR_SERVICE_KEY` 값을 교체한다. 웹 비밀번호와 API키는 다른 값이며 API키를 웹 입력창·GitHub·공유 문서에 넣지 않는다.
5. 아래 명령으로 API와 worker에 새 환경변수를 반영한다.

```powershell
docker compose -f compose.yaml -f compose.demo.yaml up -d --force-recreate api worker
docker compose exec -T api python -m app.cli online
```

6. 사이트 **수집 데이터 → 전력·가스 선택 → 2025-01 ~ 2025-12 → 수집 작업 시작**을 실행한다.
7. 작업 상태와 에너지 출처의 원본 응답·정규화 행수·월별 확보 범위를 확인한다. 0행은 실제 0사용량과 다르다.

필요 필드: `sigunguCd`, `bjdongCd`, `bun`, `ji`, `useYm`, `useQty`; 전력과 가스를 구분해 보관한다. 공식 제공 단위는 지번별 월간 kWh다. 산 여부가 있으면 함께 보존한다. ‘단독주택·200세대 미만 공동주택 등 제외’ 조건이 있어 API 승인 후에도 모든 격자가 채워지지는 않는다. 현재 수집기는 후보 지번·법정동을 우선하는 제한 수집이며 전주시 전체 전수조사를 보장하지 않는다.

인증 오류 30은 키 미등록, 20은 권한·키 관련 오류를 확인해야 한다. 같은 포털키여도 해당 서비스 활용신청이 필요하다. 오류 22/23이면 요청 한도를 확인한다. 승인 상태와 최신 에러 설명은 서비스 상세 페이지를 기준으로 확인한다.

## 3. 공식 건축물대장

공식 자료: [건축HUB 건축물대장정보](https://www.data.go.kr/data/15134735/openapi.do).

에너지와 **별도로 활용신청**한다. 같은 `.env` 키를 사용하되 두 서비스 모두 승인됐는지 확인한다. API/worker 재생성 후 다음 명령으로 후보 지역 건축물대장과 KMA 어댑터를 실행할 수 있다.

```powershell
docker compose exec -T api python -m app.cli enrich --year 2025
```

건축물대장은 `getBrTitleInfo` 기준 관리건축물대장 PK, 법정동·지번, 대지면적, 건축면적, 연면적, 용적률 산정용 연면적, 건폐율, 용적률, 지상층수, 높이, 용도, 세대수, 사용승인일을 받아야 한다. 대응 필드 예: `mgmBldrgstPk`, `platArea`, `archArea`, `totArea`, `vlRatEstmTotArea`, `bcRat`, `vlRat`, `grndFlrCnt`, `heit`, `mainPurpsCdNm`, `hhldCnt`, `useAprDay`.

현재 어댑터는 후보 범위를 제한해서 수집한다. 법정 허용 용적률·건폐율은 현재 건물의 실적 용적률·건폐율과 다른 자료다. 지적·용도지역·관련 조례의 검토 없이 인허가 가능 여부를 계산하지 않는다.

## 4. 공식 기상 관측

공식 자료: [ASOS 일자료 API](https://www.data.go.kr/data/15059093/openapi.do), [기상자료개방포털 다운로드](https://data.kma.go.kr/data/grnd/selectAsosRltmList.do?pgmNo=36).

- API 경로: ASOS 서비스를 별도 활용신청하고 승인 후 `docker compose exec -T api python -m app.cli collect --year 2025 --source kma --scope smoke`로 1월을 확인하고, 성공 시 `--scope full`로 확대한다.
- 파일 경로: 기상자료개방포털 로그인 → 지상관측 → 종관기상관측(ASOS) → **일자료**, 지점 **전주 146**, 기간 **2025-01-01 ~ 2025-12-31** → CSV 다운로드. 메뉴와 선택 가능한 기간은 포털 현행 화면에 따른다.
- 필요한 열: 날짜 `tm`, 평균·최저·최고기온 `avgTa/minTa/maxTa`, 일강수량 `sumRn`, 지점번호. 2025년 365일 확보 여부와 결측·품질 표식을 함께 확인한다.
- API 어댑터는 습도·일조·일사·풍속도 별도 필드로 보존하고 완전한 월만 공식 관측으로 우선한다. ERA5-Land 원본과 월자료는 삭제하지 않는다. 파일 CSV를 현재 일반 업로드에 넣는 KMA 전용 경로는 없으므로 API 사용이 불가능하면 원본을 보관하고 별도 변환·검증해야 한다.

## 5. SGIS 행정통계와 공식 500m 격자

공식 자료: [SGIS 자료제공](https://sgis.kostat.go.kr/view/pss/openDataIntrcn).

행정구역 인구·가구 API는 구현되어 있다. SGIS 개발자 사이트에서 consumer key/secret을 발급받아 `.env`의 `SGIS_CONSUMER_KEY`, `SGIS_CONSUMER_SECRET`에 넣는다. 문서에서 확인된 제공연도에 맞춰 `SGIS_BASE_YEAR`를 설정하며 기본값은 2020이다. 토큰은 만료 전까지 메모리/Redis에서 재사용하고 DB·원본 메타데이터에 기록하지 않는다.

```powershell
docker compose up -d --force-recreate api worker
docker compose exec -T api python -m app.cli collect --year 2020 --source sgis --scope smoke
docker compose exec -T api python -m app.cli collect --year 2020 --source sgis --scope limited
```

API 결과는 행정구역 통계이므로 500m 격자로 임의 분배하지 않는다. 공식 500m 자료는 다음 절차로 별도 확보한다.

1. SGIS 로그인 → **자료제공 → 자료신청**에서 소지역 통계·격자통계 항목을 확인한다.
2. 지역은 전북특별자치도 전주시, 격자 크기는 **500m**, 자료는 **인구·가구와 동일 기준 격자 경계·코드집**을 신청한다.
3. 2025 자료의 제공 여부를 확인한다. 제공되지 않으면 2024 등 제공 가능한 연도를 따로 받되 파일과 화면의 기준연도를 그대로 유지한다. 다른 연도 값을 2025 관측으로 바꾸지 않는다.
4. 승인 후 통계 CSV/TXT와 경계 SHP ZIP을 함께 다운로드한다. `.shp/.shx/.dbf/.prj`를 보존한다.
5. 필수값은 공식 격자 ID, 인구수, 기준연도, 경계 도형, 좌표계다. 앱의 인구 필드로는 `source_grid_id`, `population`, `year`를 사용한다. 가구수·비밀보호 표식도 원본에 보존한다.

공식 격자와 현재 자체 500m 격자는 ID나 원점이 같다고 가정할 수 없다. 같은 경계끼리 ID 대응을 확인하거나 공간 중첩 규칙을 검증해야 한다. SGIS 공개 자료에는 비밀보호 처리가 있을 수 있으므로 숫자 0과 결측·비공개를 임의로 통합하지 않는다. 일반 API의 행정동 인구만으로 500m 인구를 임의 분배하지 않는다.

현재 일반 업로드는 경계·인구의 검증과 정규화를 지원한다. 공식 격자 ID와 현재 자체 격자의 대응은 실제 경계 중첩으로 검증해야 한다.

## 6. VWorld 용도지역·지적과 공식 건물 도형

공식 진입점: [VWorld](https://www.vworld.kr/), [2D Data API 안내](https://www.vworld.kr/dev/v4dv_2ddataguide2_s001.do).

API 수집기는 용도지역 `LT_C_UQ111`과 연속지적 `LP_PA_CBND_BUBUN`을 설정 파일에서 사용한다. VWorld 키와 등록 도메인을 `.env`의 `VWORLD_API_KEY`, `VWORLD_DOMAIN`에 설정한다. 한 분석격자에서 SMOKE를 성공한 뒤 FULL을 실행한다.

```powershell
docker compose up -d --force-recreate api worker
docker compose exec -T api python -m app.cli collect --source vworld-zoning --scope smoke
docker compose exec -T api python -m app.cli collect --source vworld-cadastral --scope smoke
docker compose exec -T api python -m app.cli collect --source vworld-zoning --scope full
docker compose exec -T api python -m app.cli collect --source vworld-cadastral --scope full
```

수집기는 분석격자별 2km² 이하 bbox, 페이지네이션, geometry 검증·보정, EPSG:5179 저장과 격자별 다중 용도지역 교차를 처리한다. 키 등록 도메인이 Quick Tunnel의 임시 URL과 다르면 VWorld 요청이 거부될 수 있으므로 발급 화면의 등록값과 `VWORLD_DOMAIN`을 같게 유지한다.

포털 로그인 후 데이터 다운로드에서 **연속주제도(국토계획 용도지역·용도지구)**, **연속지적도**, **GIS 건물통합정보**를 검색하고 전주시 범위의 원본을 신청·다운로드한다. API를 이용한다면 개발자 인증키와 등록 서비스 URL 조건을 확인한다. 임시 시연 도메인은 바뀔 수 있어 키의 도메인 제한도 함께 확인해야 한다.

받아야 할 자료:

- 용도지역: 구역 고유 ID, 법정 코드·명칭, 고시·기준일, Polygon/MultiPolygon, CRS.
- 지적: 19자리 PNU, 지번·산 여부, 필지 경계, 기준일, CRS.
- 건물: 건물 ID, 건축물대장·PNU 연결키, 건물 도형, 층수·용도·면적, 기준일, CRS.
- 허용 밀도: 해당 구역의 현행 계획·조례와 허용 용적률·건폐율·높이 등. 현재 대장 수치를 법정 상한으로 사용하지 않는다.

다운로드한 SHP는 구성파일을 묶은 ZIP으로 보관한다. 좌표계가 EPSG:5179와 다르면 원본 CRS를 정확히 지정하고 변환한다. 파일을 확보하면 사이트 **수집 데이터 → 파일 업로드 → 용도지역/건축물/격자 → 미리보기 → 필드 매핑**으로 검증한다. 출처 URL·기준기간·기관명을 함께 기록한다. 등록만으로 법적 적합성을 판정하지 않는다.

## 7. 가스 배출계수와 기업 탄소격자

전력 근거: [GIR 국가 온실가스 배출계수](https://www.gir.go.kr/home/board/read.do?boardId=82&boardMasterId=2&menuId=36).

가스는 공식 원문에서 도시가스/LNG 연료 정의, CO₂·CH₄·N₂O 계수, 단위, GWP 버전, 발열량과 고위/저위 열량 기준, 적용 연도를 확보해야 한다. 에너지 API의 가스 kWh가 어느 열량 기준인지 제공기관에 확인한다. kgCO₂/TJ 또는 Nm³당 계수를 근거 없이 kWh당 CO₂eq 계수로 바꾸지 않는다. 원문 PDF·표·계수 적용 설명을 제공받은 뒤 계산 엔진에 등록·검증해야 한다. 웹사이트에는 임의 가스계수 입력 기능을 추가하지 않았다.

선도소프트에는 다음 원본·명세를 요청해야 한다. 연락이나 요청 메시지를 대신 발송하지는 않았다.

> 전주시 대상 100m 탄소격자 원본(2025년, 없으면 실제 제공 연도)을 GeoJSON/SHP 또는 격자 ID가 있는 CSV와 경계 파일로 요청합니다. 격자 원점·좌표계, 월/연간 구분, 탄소 단위(t 또는 kg CO₂/CO₂eq), 포함 부문·에너지원, 결측 코드, 산정식·배출계수·GWP, 이용·시연·재배포 허용 범위를 함께 부탁드립니다. 500m 집계와 독립 검증에 사용할 예정입니다.

기업 탄소격자 전용 가져오기·집계 어댑터는 원본 명세가 확정되면 구현해야 한다. 100m 값이 총량인지 면적당 집약도인지 확인하지 않은 단순 합계는 사용하지 않는다.

## 원본 전달과 우선순위

**에너지 API 승인·키 교체 → 건축물대장 승인 → 인구·용도지역 원본 → 가스계수·기업격자** 순서가 효율적이다. API키는 로컬 `.env`에만 설정한다. 파일은 제공기관 원본 이름을 유지하고 다운로드일·기준연도·단위·CRS·이용 조건을 함께 기록한다. 일반 업로드 지원 형식은 CSV/XLSX/GeoJSON/SHP ZIP, 파일당 25MiB이며 기상·계수·기업격자는 별도 처리 대상이다.

직접 수집 결과의 실행 증거는 로컬 `data/deployment/source-recovery.json`과 `data/validation/source-recovery.log`에 있다. 새로 확보한 원본은 `data/raw/research/`와 DB에 보존되며 GitHub에 자동 업로드하지 않는다.
