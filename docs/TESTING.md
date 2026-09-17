# 실제 실행 검증

2026-09-18 Windows Docker Desktop Linux 엔진에서 다시 실행했다. 테스트 fixture는 계산 검증용이며 실제 관측으로 저장하지 않는다.

| 검증 | 최종 결과 |
|---|---|
| Python 단위·GIS·PostGIS API·업로드·모델·외부 수집·캐시 | 78 통과, 0 실패 |
| React/Vitest | 11파일, 19 통과, 0 실패 |
| Chromium E2E | 9 검증 통과, pageerror 0 |
| TypeScript/Vite 운영 빌드 | 성공 |
| npm 보안 검사 | 검사 시점 알려진 취약점 0 |
| 별도 신규 DB/Redis 볼륨 초기화 | 보존 실데이터 복원 성공 |

500m 변 길이·면적·투영, null/실제 0, FAR/BCR, 월 집계, 탄소계수, 시나리오 제약, 최적화, 공간 검증, 연도별 기준면적, 업로드, 과거 캐시, 오프라인 차단을 검사했다. 추가로 K-apt 직접 item 응답·단위·재실행 건너뛰기, KMA 일자료·완전월 우선순위, SGIS token TTL·0/비공개/결측, VWorld 현재 레이어·페이지·invalid geometry·다중 용도지역 교차를 검사했다.

실제 작업 큐에서는 2025년 K-apt SMOKE 1회와 KMA ASOS SMOKE 1회를 실행했다. 두 요청 모두 제공기관 인증 오류 30/20으로 실패했으며 기존 DB 수량은 보존됐다. 따라서 어댑터·오류 처리는 검증됐지만 실제 성공 응답과 신규 실데이터 적재는 유효한 활용 승인 키 적용 후 다시 검증해야 한다. 모의 HTTP 테스트는 공공 API 승인 성공을 뜻하지 않는다.

```powershell
docker compose up --build -d
docker compose exec -T api python -m pytest -q
cd frontend
npm ci
npm test
npm run build
```

현재 검증 DB의 주요 수량은 분석격자 916, 건물 2,171, K-apt 단지 364, 유효 기상 월자료 22, 월별 에너지 0, KMA 공식 일자료 0, SGIS 인구·가구 0, VWorld 용도지역·지적 0이다.

기존 볼륨을 삭제하지 않고 별도 프로젝트에서 빈 DB 복원을 수행했다. 최초 출력에서 PostgreSQL/Redis 볼륨 신규 생성을 확인했으며 빌드 캐시는 재사용했다.

```powershell
docker compose -p carbon-urban-dss-validation -f compose.yaml -f compose.validation.yaml up --build -d
docker compose -p carbon-urban-dss-validation -f compose.yaml -f compose.validation.yaml exec -T api python -m pytest -q
```

검증 프로젝트는 API 8010, 웹 5190, 오프라인 설정으로 보존된 원본을 읽는다. 실제 행수를 SQL로 비교했다. 캐시 테스트는 사용자 오프라인 플래그와 격리된 테스트 디렉터리 및 모의 HTTP를 사용한다.

E2E는 Playwright/Chromium이 준비된 Node 환경에서 실행한다. 이번에는 Codex 번들 런타임을 사용했다. 별도 도구 폴더에 Playwright를 설치했다면 `NODE_PATH`에 그 `node_modules`를 지정한다.

```powershell
$env:DSS_URL='http://127.0.0.1:5190'
node scripts/e2e.cjs
docker compose -p carbon-urban-dss-validation -f compose.yaml -f compose.validation.yaml down
```

대시보드·수집 데이터·기상 출처·지도·모델·시뮬레이션 6경로, 30층 계산, 최적화 응답, 오프라인 도형 렌더링/외부요청 차단을 검사한다. `data/validation/`에 JSON과 화면을 저장한다. 지도는 실제 렌더링된 격자 수가 양수인지 확인한다.

수정한 오류: MapLibre 6 import/worker 경로, nginx IPv6 localhost 상태검사, 연도별 기준면적 혼용, 부분 관측 탄소에 OSM 전체 추정면적 사용, 사용자 오프라인 설정에 종속된 테스트, 수집 상태 집계 누락. Worker 설정은 [공식 Vite 안내](https://maplibre.org/maplibre-gl-js/docs/)를 따랐다. 남은 경고는 라이브러리 deprecation 2건과 초기 JS 약 2.5MB(압축 약 769KB)다.

## 2026-09-14 기능 보완 및 최신 검증

최신 보완 내역과 미구현 항목은 [IMPLEMENTATION_UPDATE.md](IMPLEMENTATION_UPDATE.md)를 따른다. 이번 결과는 백엔드 63개, 프런트엔드 17개, 기존 E2E 9개와 보완 E2E 9개 통과이며 브라우저 실행 오류는 0건이다. 실제 로컬 Qwen 모델의 근거 선정 및 원문 검증도 통과했다. 이전 날짜의 신규 DB 복원 결과와 구분한다.

추가 E2E: `node scripts/e2e-refined.cjs`. 기본 웹 주소는 127.0.0.1:5173이며 결과는 `data/validation/refined/`에 저장한다. 보고서의 비교·다운로드·인쇄, 모바일 및 오류 상태를 포함한다. 실제 에너지 관측·탄소 감축·예측 성능 검증은 자료 확보 후 수행해야 한다.
