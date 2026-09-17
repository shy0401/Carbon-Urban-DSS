# External API Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** K-apt 에너지, KMA ASOS, SGIS 행정통계, VWorld 공간자료를 재개 가능한 단계별 수집 파이프라인으로 연결한다.

**Architecture:** 기존 `DataSource`, `RawDataAsset`, `CollectionJob`, Celery 구조를 유지한다. 공급기관별 모듈은 파싱·정규화·수집을 담당하고, 기존 유효 DB와 `data/raw`는 보존한다. K-apt는 smoke 성공 없이는 full을 허용하지 않고, 기상은 공급기관별 월자료를 보존한 뒤 완전한 ASOS 월을 조회 시 우선한다.

**Tech Stack:** FastAPI, SQLAlchemy/PostGIS, Celery/Redis, httpx, React/Vitest, Docker Compose

**Spec:** 사용자 첨부 프롬프트 및 `docs/PROJECT_IMPLEMENTATION_STATUS.md`

## Global Constraints

- 실제 비밀키는 코드·문서·로그·브라우저 응답에 기록하지 않는다.
- 기존 DB 볼륨과 `data/raw`를 삭제하지 않는다.
- 0, 결측, 미수집, 빈 정상응답, 비밀보호를 구분한다.
- 공식 SGIS 행정통계를 자체 500m 격자 인구로 변환하지 않는다.
- 가스·난방·급탕을 kWh 또는 전체 탄소로 임의 변환하지 않는다.
- 라이브 호출 성공 여부와 모의 테스트 통과를 구분한다.

---

### Task 1: 공통 보안·설정·수집 상태

**Files:**
- Modify: `.env.example`
- Modify: `backend/app/cache.py`
- Test: `backend/tests/test_cache.py`

**Interfaces:**
- Consumes: 기존 `CachedClient.get(provider, operation, url, params)`
- Produces: 모든 공급기관의 비밀 파라미터 마스킹과 안전한 캐시 식별

- [ ] 비밀 파라미터가 raw metadata와 body에 남지 않는 실패 테스트를 작성한다.
- [ ] 테스트가 기존 `serviceKey` 이외 토큰에서 실패함을 확인한다.
- [ ] `consumer_secret`, `accessToken`, VWorld `key`까지 대소문자와 무관하게 마스킹한다.
- [ ] 캐시 테스트를 통과시키고 환경변수 이름만 `.env.example`에 추가한다.

### Task 2: K-apt 월별 에너지 파이프라인

**Files:**
- Create: `backend/app/kapt_energy.py`
- Modify: `backend/app/kapt.py`
- Modify: `backend/app/tasks.py`
- Modify: `backend/app/cli.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_kapt_energy.py`

**Interfaces:**
- Produces: `collect_kapt_energy(db, year, scope, client=None) -> dict`
- Produces: `ApartmentEnergyMonthly`, `ComplexGridMapping`
- Scope: `smoke=1×1`, `limited=3×12`, `full=전체×12`

- [ ] `body.item`/`body.items.item`, 숫자 0/결측, 단위, 중복 upsert 테스트를 먼저 작성하고 실패를 확인한다.
- [ ] 금액과 물리량을 분리한 정규화 테이블과 단지코드·좌표 기반 격자 매핑을 구현한다.
- [ ] 성공한 단지·월은 건너뛰고, 실패/빈 응답 상태와 원본 자산을 보존한다.
- [ ] smoke 성공 기록 없이는 full을 거부하고 요청 간격을 환경변수로 제어한다.
- [ ] Celery, API, CLI의 `source=kapt-energy`, `scope`에 연결하고 테스트를 통과시킨다.

### Task 3: KMA ASOS 공급기관별 기상 보존

**Files:**
- Create: `backend/app/kma_asos.py`
- Modify: `backend/app/collectors.py`
- Modify: `backend/app/official.py`
- Modify: `backend/app/service.py`
- Test: `backend/tests/test_kma_asos.py`

**Interfaces:**
- Produces: `collect_asos(db, year, scope, client=None) -> dict`
- Produces: `WeatherDailyObservation`, `WeatherMonthlyObservation`

- [ ] 빈 문자열/하이픈/null과 실제 0을 구분하고 월 완전성을 판단하는 실패 테스트를 작성한다.
- [ ] ASOS 페이지 전체를 읽고 일자료와 공급기관별 월 집계를 저장한다.
- [ ] ERA5-Land 월자료를 별도 보존하고 완전한 ASOS 월만 유효 조회값으로 선택한다.
- [ ] Task/API/CLI에 연결하고 2025년 전주 146 smoke/limited 모드를 제공한다.

### Task 4: SGIS 인증·행정 인구·가구

**Files:**
- Create: `backend/app/sgis.py`
- Modify: `backend/app/tasks.py`
- Modify: `backend/app/cli.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_sgis.py`

**Interfaces:**
- Produces: `SgisTokenManager`, `collect_sgis_admin(db, year, scope, client=None)`
- Produces: `SgisPopulationAdmin`, `SgisHouseholdAdmin`

- [ ] 토큰 만료·재사용, API 오류, 인구/가구 파싱의 실패 테스트를 작성한다.
- [ ] 메모리와 선택형 Redis TTL 캐시를 구현하고 토큰을 DB에 저장하지 않는다.
- [ ] `searchpopulation.json`, `household.json` 결과를 행정통계 전용 테이블에 적재한다.
- [ ] 공식 500m 격자는 자동 API 결과로 간주하지 않고 `requires_official_download`를 표시한다.

### Task 5: VWorld 용도지역·연속지적

**Files:**
- Create: `config/vworld_layers.yaml`
- Create: `backend/app/vworld.py`
- Modify: `backend/requirements.txt`
- Modify: `backend/app/tasks.py`
- Modify: `backend/app/cli.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_vworld.py`

**Interfaces:**
- Produces: `collect_vworld(db, dataset, scope, client=None)`
- Produces: `VworldZoningArea`, `CadastralParcel`, `GridZoningStat`

- [ ] GeoJSON 상태/페이지/유효 geometry/CRS 변환·교차 통계를 검사하는 실패 테스트를 작성한다.
- [ ] 공식 레퍼런스 확인값 `LT_C_UQ111`, `LP_PA_CBND_BUBUN`을 설정 파일에 기록한다.
- [ ] 2km² 미만 bbox, 페이지, 원본 보존, feature ID/geometry hash 중복 제거를 구현한다.
- [ ] 용도지역 분포를 격자별 교차면적으로 보존하고 FAR/BCR은 생성하지 않는다.

### Task 6: 화면·문서·전체 검증

**Files:**
- Modify: `frontend/src/pages/DataPage.tsx`
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/App.test.tsx`
- Modify: `docs/PROJECT_IMPLEMENTATION_STATUS.md`
- Modify: `docs/TESTING.md`

**Interfaces:**
- Consumes: 확장된 `/api/sources`, `/api/collections`
- Produces: 공급기관과 scope를 선택할 수 있는 수집 UI 및 실제 상태 표시

- [ ] 수집 데이터 UI의 공급기관·scope 선택 테스트를 먼저 실패시킨다.
- [ ] K-apt/KMA/SGIS/VWorld 상태와 공식 SGIS 격자 미확보 상태를 표시한다.
- [ ] 백엔드 전체 테스트, 프런트엔드 테스트·빌드, secret scan을 실행한다.
- [ ] 키가 있는 공급기관만 smoke 호출하고 raw/DB 수량을 직접 조회해 문서를 갱신한다.
- [ ] Docker가 가능하면 기존 볼륨을 보존한 상태로 migration/create-all과 브라우저 흐름을 확인한다.
