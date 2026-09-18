# Carbon Urban DSS 구현·외부 API 연동 현황

- 확인일: 2026-09-18
- 기준 범위: 전주시, 기본 분석연도 2025년, EPSG:5179
- 주의: `0행`은 사용량 0이 아니라 아직 유효한 관측을 확보하지 못했다는 뜻이다.

이 문서는 코드 구현, 실제 적재, 외부 키·승인 상태를 구분한다. 키 원문과 SGIS access token은 문서·Git·브라우저에 저장하지 않는다.

## 1. 현재까지 구현한 부분

### 서비스와 공통 수집 구조

- PostGIS, Redis, FastAPI, Celery worker, React/Nginx를 Docker Compose로 실행한다. 기존 DB 볼륨과 `data/raw` 원본을 유지한다.
- 수집 작업은 `SMOKE → LIMITED → FULL` 범위를 지원한다. 성공한 K-apt 월은 다시 호출하지 않으며 K-apt와 VWorld의 FULL은 같은 출처의 SMOKE 성공 후에만 허용한다.
- 원본 응답, 출처 URL, 기준기간, 안전한 요청 파라미터, HTTP/제공기관 상태, 수집시각, 정규화 행 수와 오류를 기록한다.
- `serviceKey`, VWorld key, SGIS consumer key/secret/access token은 캐시 메타데이터와 원본 응답에서 마스킹한다. 키가 바뀌면 과거 인증 오류 캐시를 재사용하지 않는다.
- 숫자 0, 결측, 비공개, 정상 빈 응답을 구분한다. 단위가 다른 값을 임의로 합산하지 않는다.

### 외부 API별 구현

| 출처 | 구현된 흐름 | 현재 실제 상태 |
|---|---|---|
| K-apt 공동주택 기본정보 | 전주시 목록·상세 → 원본 → 정규화 → 격자 연결 | 단지 364개 적재 |
| K-apt 월별 에너지 | `getHsmpApHusUsgQtyInfoSearchV2` → 단지·월 원본 → 전기/가스/난방/급탕/수도 사용량·요금 분리 → PostGIS → 전기 관측·탄소 연결 | 코드·모의 테스트 완료, 실제 0행. 현재 키 오류 30/20 |
| KMA ASOS | 전주 146 일자료 → 일별 원본 → 월 집계 → 완전한 공식 월 우선, ERA5-Land 대체자료 별도 보존 | 코드·모의 테스트 완료, 공식 일자료 0행. 현재 키 오류 30/20 |
| SGIS | 토큰 발급·만료 전 재사용 → 행정구역 인구/가구 분리 적재 → 0/비공개/결측 상태 저장 | 코드·모의 테스트 완료, 키 미설정으로 0행 |
| SGIS 공식 500m 격자 | 행정통계와 분리된 출처·상태, 수동 원본 업로드 경로 | 공식 경계·통계 파일 미확보 |
| VWorld 용도지역 | 공식 `LT_C_UQ111` 설정 → 2km² 이하 bbox·페이지 수집 → geometry 검증/보정 → EPSG:5179 → 격자별 다중 용도지역 교차 | 코드·모의 테스트 완료, 키 미설정으로 0행 |
| VWorld 연속지적 | 공식 `LP_PA_CBND_BUBUN` 설정 → 원본 → PNU/법정동/본번/부번 → geometry 검증 → EPSG:5179 | 코드·모의 테스트 완료, 키 미설정으로 0행 |

VWorld 레이어 ID와 CRS는 `backend/config/vworld_layers.yaml`에서 관리한다. 현재 대장 용적률·건폐율을 법정 허용 상한으로 사용하지 않는다.

### 현재 DB 실측 수량

| 데이터 | 행 수 | 비고 |
|---|---:|---|
| 프로젝트 500m 분석격자 | 916 | 자체 생성 격자, SGIS/NGII 공식 격자 ID가 아님 |
| OSM 건물 | 2,171 | 공식 건축물 모집단을 대체하지 않음 |
| K-apt 공동주택 | 364 | 기본정보 확보 |
| 유효 기상 월자료 | 22 | 보존 자료 전체; 2025년 분석에는 완전한 12개월 사용 |
| 월별 에너지 관측 | 0 | K-apt/건축HUB 모두 실제 승인 키 필요 |
| KMA 공식 ASOS 일자료 | 0 | 현재 키 승인 실패 |
| SGIS 인구·가구 | 각 0 | consumer key/secret 미설정 |
| VWorld 용도지역·지적 | 각 0 | key/domain 미설정 |

2026-09-18 실제 작업 큐에서 K-apt `SMOKE` 1단지×2025-01과 KMA `SMOKE` 전주 146×2025-01을 호출했다. 두 요청 모두 `API 인증 실패 (30/20)`로 종료됐고 기존 데이터는 유지됐다.

### 화면과 분석

- 대시보드, 지도 분석, 모델, 시뮬레이션, 수집 데이터, 검토 보고서 화면이 백엔드와 연결된다.
- 지도는 로컬 GeoJSON 경계·건물·격자를 표시한다. 외부 배경 타일 장애가 있어도 분석 도형과 선택 기능은 유지한다.
- 수집 화면에서 18개 출처의 상태, 원본·정규화 수량, 키 설정 여부, 실패 이유, 수집 정보의 실제 활용처와 `SMOKE/LIMITED/FULL` 요청을 확인할 수 있다.
- `/api/readiness`는 수집→원본→정규화→공간→분석→의사결정 계보를 현재 DB 수량으로 제공하며 키 값 자체는 반환하지 않는다.
- 로컬 Ollama `qwen2.5:1.5b`는 검증된 근거 ID 선택과 한국어 요약에만 사용한다. 2026-09-18 실제 보고서 생성에서 `LOCAL_SLM`과 근거 원문 일치 검증 통과를 확인했다.
- 월별 관측이 없으면 탄소·모델 성능을 만들어내지 않고 `자료 없음`으로 표시한다.
- PC, Docker Desktop, 네트워크가 켜져 있는 동안 Cloudflare Quick Tunnel로 HTTPS 시연한다. Quick Tunnel 주소는 재시작 시 바뀔 수 있다.
- 바탕화면의 `Carbon Urban DSS 서버 실행.cmd`는 Docker Desktop, 전체 컨테이너, 모델, 인증 gateway와 터널을 준비하고 외부 상태를 검증한 뒤 브라우저를 연다.

## 2. 앞으로 구현하거나 확보해야 할 부분

| 우선순위 | 남은 작업 | 완료 조건 |
|---:|---|---|
| 1 | 유효한 K-apt 활용 승인·키 적용과 단계 수집 | 1단지×1개월 성공 후 3단지×12개월, 이후 성공 월을 건너뛰며 전주시 전체 수집 |
| 2 | KMA ASOS 활용 승인·키 적용 | 전주 146의 2025년 365일과 완전한 12개월을 적재하고 ERA5 우선순위 검증 |
| 3 | SGIS 키 적용 및 공식 500m 파일 확보 | 행정구역 통계를 적재하고, 별도 다운로드한 경계·인구·비밀보호 플래그를 공식 격자 ID로 통합 |
| 4 | VWorld 키·등록 도메인 적용 | 한 격자 SMOKE 성공 후 전주시 용도지역·지적을 수집하고 geometry/교차 통계를 검수 |
| 5 | 공식 건축물대장 전주시 전수화 | 페이지·증분·재시도 가능한 전수 수집과 PNU/건물/단지 매칭 품질 확보 |
| 6 | 가스 운영탄소 방법 확정 | 가스 단위, 발열량 기준, 공식 CO₂·CH₄·N₂O 계수와 GWP를 검증한 뒤 계산 연결 |
| 7 | 선도소프트 100m 탄소격자 통합 | 원본·CRS·단위·포함 부문·산정식·이용조건 확보 후 500m 집계와 독립 비교 |
| 8 | 실데이터 모델 검증 | 충분한 월별 관측과 설명변수로 시간·공간 누수 없는 검증, 표본 수·오차·한계 표시 |
| 9 | 고정 운영 배포 | 고정 서버/도메인, DB 백업·복구, 마이그레이션, 사용자별 인증과 감사 로그 |

행정구역 SGIS API 결과를 프로젝트 500m 격자에 임의 분배하지 않는다. VWorld 도형도 법적 인허가 판정이 아니라 분석 보조자료로 사용한다.

## 3. 키만 적용하면 작동할 부분

### 공공데이터포털 공통 키

`.env`의 `DATA_GO_KR_SERVICE_KEY`를 사용한다. 다음 서비스는 각각 별도 활용신청·승인이 필요하다.

- K-apt 공동주택 에너지 사용정보 `15012964`
- KMA ASOS 일자료 `15059093`
- 기존 건축HUB 건물에너지 `15135963`
- 기존 건축HUB 건축물대장 `15134735`

현재 14자리 값은 실제 키가 아니거나 서비스 승인이 없어 오류 30/20으로 거부된다. 새 키 적용 후 컨테이너를 재생성해야 한다.

```powershell
docker compose up -d --force-recreate api worker
docker compose exec -T api python -m app.cli online
docker compose exec -T api python -m app.cli collect --year 2025 --source kapt-energy --scope smoke
docker compose exec -T api python -m app.cli collect --year 2025 --source kapt-energy --scope limited
docker compose exec -T api python -m app.cli collect --year 2025 --source kapt-energy --scope full
docker compose exec -T api python -m app.cli collect --year 2025 --source kma --scope smoke
docker compose exec -T api python -m app.cli collect --year 2025 --source kma --scope full
```

K-apt 호출량은 SMOKE 1회, LIMITED 최대 36회, FULL 최초 최대 4,368회다. FULL은 이미 성공한 월을 건너뛰므로 앞 단계 성공분은 다시 호출하지 않는다.

### SGIS

`.env`에 `SGIS_CONSUMER_KEY`, `SGIS_CONSUMER_SECRET`, `SGIS_BASE_YEAR`를 설정한다. 현재 공식 API 문서에서 확인된 통계 기준연도 때문에 기본값은 2020이다. 토큰은 메모리/Redis TTL로만 재사용한다.

```powershell
docker compose up -d --force-recreate api worker
docker compose exec -T api python -m app.cli collect --year 2020 --source sgis --scope smoke
docker compose exec -T api python -m app.cli collect --year 2020 --source sgis --scope limited
```

이 키로 행정구역 인구·가구는 작동하지만 공식 500m 격자 경계·인구는 SGIS 자료제공에서 별도로 받아야 한다.

### VWorld

`.env`에 `VWORLD_API_KEY`와 키 발급 시 등록한 `VWORLD_DOMAIN`을 설정한다. 현재 설정 레이어는 용도지역 `LT_C_UQ111`, 연속지적 `LP_PA_CBND_BUBUN`이다.

```powershell
docker compose up -d --force-recreate api worker
docker compose exec -T api python -m app.cli collect --source vworld-zoning --scope smoke
docker compose exec -T api python -m app.cli collect --source vworld-cadastral --scope smoke
docker compose exec -T api python -m app.cli collect --source vworld-zoning --scope full
docker compose exec -T api python -m app.cli collect --source vworld-cadastral --scope full
```

SMOKE 결과의 속성명, 좌표계, 페이지 수와 이용조건을 먼저 확인한 뒤 FULL을 실행한다.

## 후속 수정용 프롬프트

```text
Carbon Urban DSS의 외부 실데이터 연동을 이어서 진행해줘.

저장소: C:\Users\ggg\Documents\4학년\캡스톤\선도소프트
우선 확인 문서:
- docs/PROJECT_IMPLEMENTATION_STATUS.md
- docs/DATA_SETUP_GUIDE.md
- docs/TESTING.md

이번에 제공한 키/원본: {{KEY_OR_FILE_DESCRIPTION}}
목표 범위와 연도: {{예: 전주시 K-apt 2025년}}

현재 DB 볼륨과 data/raw를 삭제하지 말고 다음 순서로 실제 작업을 수행해줘.
1. 키 원문을 출력하지 말고 .env에만 적용한다. API/worker를 재생성한 뒤 온라인 모드를 확인한다.
2. 대상 출처의 SMOKE를 실행하고 HTTP 상태, 제공기관 코드, 원본 저장, 정규화 행, 0/결측/비공개, 단위와 CRS를 검증한다.
3. SMOKE 성공 시에만 LIMITED를 실행한다. 결과 수량과 호출량을 확인한 뒤 FULL을 실행하며 이미 성공한 월·페이지는 재호출하지 않는다.
4. K-apt 전기는 kWh만 분석 관측과 0.4541 kgCO2eq/kWh 계산에 연결한다. 가스 m3, 난방 Mcal, 급탕 tonne은 검증된 변환계수 없이 합산하지 않는다.
5. KMA는 전주 146의 완전한 공식 월만 유효 기상값으로 우선하고 ERA5 원본은 보존한다.
6. SGIS 행정통계를 500m 격자에 임의 배분하지 않는다. 공식 격자는 경계·ID·기준연도·비밀보호 플래그 원본을 별도 통합한다.
7. VWorld는 backend/config/vworld_layers.yaml의 현재 공식 레이어를 사용하고 bbox 2km², 페이지, geometry 유효성, EPSG:5179 변환과 다중 용도지역 교차를 검증한다. 법정 FAR/BCR을 추정하지 않는다.
8. 백엔드 전체 테스트, 프런트엔드 전체 테스트·운영 빌드, API/화면 흐름, DB 행 수와 공개 시연 주소를 검증한다.
9. 실제 확보 행 수, 실패 코드, 남은 승인·파일, 다음 한 작업을 docs/PROJECT_IMPLEMENTATION_STATUS.md에 갱신하고 변경을 커밋·푸시한다.
```

세부 신청·다운로드 방법은 [데이터 재설정·수집 안내](DATA_SETUP_GUIDE.md), 검증 명령은 [테스트 안내](TESTING.md), 배포 방법은 [배포 안내](DEPLOYMENT.md)를 따른다.
