# D안 「도시계획 도면」 적용 기록

기준 문서: [DESIGN.md](DESIGN.md) · 작업 지시: [CLAUDE_DESIGN_PROMPT_2026-09-23.md](CLAUDE_DESIGN_PROMPT_2026-09-23.md)

이 기록은 조사 결과, 단계별 변경, 예외와 백로그를 남긴다. 기능·API 호출·계산·데이터 의미는 바꾸지 않는다.

## 0. 조사 (코드 변경 없음)

### 0.1 저장소 상태

- 브랜치 `main`, 적용 전 HEAD `16d5c70` (클라우드 미러 `53969e7`과 파일 내용 동일).
- 작업 트리의 사용자 변경 `.idea/vcs.xml`과 `data/validation/*.png`·`overlays.json`(사용자 PC 실행 산출물)은 건드리지도 커밋하지도 않는다.

### 0.2 스타일·지도·차트·아이콘·폰트

| 항목 | 현재 방식 |
|---|---|
| 스타일 | 일반 전역 CSS 한 파일(`frontend/src/styles.css`, 933줄, 유리 효과·그라데이션 배경). CSS Modules·Tailwind·CSS-in-JS 없음. 일부 컴포넌트에 `style={{…}}` 인라인 색 |
| 지도 | MapLibre GL JS 6.9 (WebGL). 워커는 `?worker&url`로 로컬 번들. 배경지도는 OSM 래스터 타일(오프라인 모드에서는 요청하지 않음) |
| 차트 | ECharts 6.1, canvas 렌더러, `Chart.tsx`에서 동적 import(초기 번들 제외) |
| 아이콘 | `lucide-react` SVG 컴포넌트(번들 포함, CDN 없음) |
| 폰트 | CSS에 `'Pretendard Variable'` 스택만 선언, **폰트 파일은 없음** → 설치되지 않은 PC에서는 시스템 글꼴로 대체되고 있었음 |

### 0.3 화면·라우트와 사용 컴포넌트

| 라우트 | 화면 | 주요 컴포넌트 |
|---|---|---|
| `/` | 대시보드 | PageHeader, MetricCard(9개), DataClassChip, QualityBadge, Chart(월별 에너지·기온), StackRow |
| `/map` | 지도 | MapLibre, 지표 선택기, 범례(`.legend-classes`), 레이어 팝오버, GridDetail(`.map-detail`), DataClassChip |
| `/analysis` | 분석 | Chart(HDD 산점도·행정동 인구 막대·용도지역 도넛), QualityBadge, 출처 표 |
| `/model` | 모델 | QualityBadge, 표본 진행 막대, CandidateTable, EmptyState |
| `/simulation` | 시뮬레이션 | 개발 조건 폼, 층수 프리셋(5·10·20·30·40층), ScenarioMassing, Chart, 최적화 결과 |
| `/data` | 수집 데이터 | MonthRangePicker, 범위 라디오, 작업 이력, ReadinessOverview, LocalAiFlow, 출처 카드, ManualUpload |
| `/data/sources/:id` | 출처 상세 | 탭, QualityScores, 미리보기 표 |
| `/reports` | 검토 보고서 | 계획안 선택, `.report-paper`, 인쇄 CSS |
| 공통 | 앱 셸 | Layout(사이드바·모바일 드로어), AnalysisScopeBar, SystemStatus(온라인/오프라인 전환) |

### 0.4 서버 응답의 근거·상태 필드

프런트에서 새로 추론하지 않고, 아래 필드만 근거 배지·결측 표시에 매핑한다.

| 응답 | 필드 | 값 | 표시 매핑 |
|---|---|---|---|
| `/api/dashboard` | `observations_label` | `OBSERVED` | 전력·가스 사용량과 월별 관측 차트 → 실측 |
| `/api/dashboard` | `metadata_label` | `CALCULATED` | 메타데이터 파생값(`current_far`, `current_bcr`, `households`, `population`, `gross_floor_area_m2`) → 계산. 현재 화면에 이 값을 직접 보여주는 곳은 없음 |
| `/api/dashboard` | `annual_complete.{electricity,gas}`, `coverage.*_months` | bool, 0–12 | 관측 기간 합계와 완전 연간 값 구분 문구 |
| `/api/dashboard` | `weather[].source_type`, `days_observed/expected_days` | `OFFICIAL`/`FALLBACK` | 기온 차트 → 실측 / 대체 |
| `/api/dashboard` | `monthly[].electricity_kwh`·`gas_kwh` = `null` | null | 결측 월(선 끊김 + 해치 띠) |
| `/api/dashboard`·`/api/map` | 값 `null` | null | `MissingValue`("—" + 사유) |
| `/api/dashboard` | `context.zoning.status`, `context.buildings.status` | `SUCCESS`/`EMPTY_VALID`/… | 수집 여부 문구 |
| `/api/map` | `building_source` | `VWORLD`/`OSM`/null | OSM이면 대체 배지 |
| `/api/map` | `zoning_status`, `building_status` | 수집 상태 | 미수집 격자 문구 |
| `/api/map` | `complexes[].floor_area_status` | `OK`/`MISSING`/`IMPLAUSIBLE` | 연면적 제외 문구 |
| `/api/map/overlays` | 용도지역·행정동 feature `quality` | `OBSERVED` | 오버레이 범례 → 실측 |
| `/api/map/overlays` | `population_status`, `household_status` | `OBSERVED`/`OBSERVED_ZERO`/`SUPPRESSED`/`NOT_COLLECTED` | 비공개(*)·미수집 문구(0으로 표시 안 함) |
| `/api/map/buildings` | feature `quality` | `OBSERVED` | 건물 팝업 |
| `/api/scenarios` | `data_class`, `method`, `label` | `SCENARIO`, `INTENSITY_ESTIMATE` | 시뮬레이션 결과 → 시나리오 |
| `/api/model` | `status`, `validated` | `INSUFFICIENT_TRAINING_DATA`/`READY_FOR_SPATIAL_VALIDATION`/`SPATIALLY_EVALUATED` | 학습 데이터 부족 / 검증 대기 / 검증 완료 |
| `/api/optimize` | `status` | `INSUFFICIENT_BASELINE_DATA` 등 | 기준 자료 부족 |
| `/api/sources`·보고서 `sources` | `source_type`, `status` | `OFFICIAL`/`FALLBACK`/`DERIVED`/`UNVERIFIED` | 공식·대체·파생 라벨 |
| `/api/reports` | `evidence_hash`, `created_at` | SHA256 | 보고서 표제란 근거 해시 칸 |

**백로그 (서버 필드가 없어 배지를 달지 않는 곳)**

- 지도 지표 15종과 대시보드의 전력 탄소·전력 원단위·세대당 전력·건폐율 근사·추정 용적률·주거지역 비율: 지표별 근거 유형 필드가 응답에 없다. 이전 화면은 프런트 상수(`mapMetrics.ts`의 `dataClass`, 카드별 `dataClass=`)로 배지를 달고 있었으나, 이번 규칙(서버 필드만 매핑)에 따라 배지를 뗀다. 산식·분모 설명 문구는 그대로 둔다. 필요하면 백엔드에 `provenance: {지표키: 'OBSERVED'|'CALCULATED'|'ESTIMATED'}`를 추가하는 별도 작업으로 되돌린다.
- 가스 탄소: 계수 확정 전이라 값이 없다(`gas_carbon_kg=null`). 결측으로만 표시한다.

### 0.5 테스트가 의존하는 셀렉터

유지 대상(변경 시 테스트를 함께 고치고 사유 기록):

- E2E `scripts/e2e.cjs`: 라우트별 문구 `Carbon Urban`, `수집 데이터`, `기상`, `도시 탄소 지도`, `모델`, `시뮬레이션`; 버튼 `30층`, `시나리오 계산`, `최적안 탐색`; 문구 `기준 자료가 없어 추정할 수 없습니다` 또는 `해석 범위`; `.maplibregl-canvas`, `.map-canvas[data-rendered-features]`.
- `scripts/e2e-refined.cjs`: `.metric-card` **정확히 8개**(현재 9개라 불일치 — 이번 작업에서 DESIGN.md의 지표 8개로 맞춤), `getByLabel('분석연도')`+`selectOption`(네이티브 select 유지), `이 연도의 기상 자료가 없습니다.`, img `월평균 기온 차트`, 버튼 `선택 격자로 확대`, 링크 `이 격자 시뮬레이션`, `이 계획안으로 보고서 작성`, 버튼 `보고서 작성`, `.report-paper`와 그 안의 `대안 1`, 링크 `문서 내려받기`, 인쇄 시 `.sidebar` 숨김, `.pipeline-segment` 6개, `.readiness-source` 16개 이상, `로컬 LLM 운영 구조`, 390px에서 `/`·`/map`·`/simulation`·`/reports`·`/data`의 `.page-header`와 가로 넘침 0, `데이터를 불러오지 못했습니다`.
- `scripts/e2e-overlays.cjs`: `.legend-classes li, .map-empty-hint`, `.metric-trigger strong`, 버튼 `/레이어/`, 체크박스 `용도지역 (VWorld)`·`행정동 인구 (SGIS)`, 범례 문구 `용도지역`·`행정동 인구밀도`(exact), `data-rendered-zoning/admin/buildings`, 분석 화면 `행정동 인구`(exact), img `SGIS 행정동별 인구 막대 차트`, `분석 격자 내 용도지역 면적 구성 차트`.
- `scripts/verify-map-public.cjs`, `e2e-public.cjs`: `getByRole('status')`(지도), `.metric-card` 8개, 위 버튼·링크.
- Vitest: `App.test`(`123,456 kWh`, `자료 없음`, navigation `주요 메뉴`, `987,654 kWh`, `다시 시도`), `DataPage.test`(데이터셋 라벨, radio `SMOKE`, group `수집 기간`, `데이터가 의사결정으로 연결되는 과정`, `운영탄소`, `로컬 LLM 운영 구조`, `형식 오류`), `ModelPage.test`(`학습 데이터 부족`, R² 미표시), `SimulationPage.test`(`시나리오 계산`, `기준 에너지·연면적 부족`, `기준 자료가 없어 추정할 수 없습니다`), `MonthRangePicker.test`, `QualityScores.test`, `MapPage.test`(색 hex를 직접 검사 — 토큰 값으로 갱신 필요).
- `data-testid`는 앱 코드에 없음(테스트 전용 `value` 1곳).

### 0.6 하드코딩 색·폰트 집계

`rg -n "#[0-9a-fA-F]{3,8}\b" frontend/src --glob '!**/tokens.css' --glob '!**/palette.ts'` → **125줄**

| 파일 | 줄 수 |
|---|---|
| styles.css | 87 (+ `rgba()` 127) |
| pages/MapPage.tsx | 11 |
| pages/AnalysisPage.tsx | 10 |
| pages/DashboardPage.tsx | 4 |
| lib/chartTheme.ts | 4 |
| pages/SimulationPage.tsx | 3 |
| lib/mapMetrics.ts | 3 |
| 테스트(MapPage.test 2, mapMetrics.test 1) | 3 |

폰트 선언은 `styles.css`의 `--font`, `chartTheme.ts`의 `fontFamily` 두 곳. CDN 참조 없음.

### 0.7 변경 전 캡처

`data/validation/design/before/` — 미리보기 서버(실제 FastAPI 앱 + 백업 DB 사본, 배경지도 타일 차단)에서 `/tmp` 스크립트로 같은 조작을 거쳐 촬영.

- 1440px: `dashboard`, `map`, `analysis`, `model`, `simulation`(30층 → 시나리오 계산 후), `data`, `data_sources_weather`, `reports`(보고서 작성 후) `-1440.png`
- 390px: 같은 8개 `-390.png`
- 인쇄: `reports-print.png`(print 미디어, A4 폭 794px), `reports-print.pdf`(Chromium A4 PDF)
- 촬영 로그: `capture.json`(페이지 오류 0, 문서 가로 넘침 0)
- 용량을 줄이려고 PNG를 256색으로 양자화했다(판독용).

### 0.8 번들 기준값

이 작업 환경에는 Vite/rollup 네이티브 바이너리를 받을 수 없어 `npm run build`를 실행할 수 없다. 전후 비교는 같은 입력을 Bun 1.4.2로 minify한 결과로 한다(절대값은 Vite와 다르며, 전후 차이만 의미가 있다).

| 항목 | 원본 | gzip |
|---|---|---|
| 초기 JS(`main.js`, 정적 import 포함) | 312,057 B | 100,336 B |
| 전체 JS(지도·차트 지연 청크 포함) | 2,587,649 B | 797,227 B |
| CSS(`maplibre-gl.css` 포함) | 150,738 B | 23,582 B |

지시문의 "약 2.52MB / 774KB"는 Vite 기준 전체 JS 합계로 보인다.

### 0.9 적용 계획

1. 토큰·서체: `styles/tokens.css`, `theme/palette.ts`, Pretendard Variable dynamic subset을 `public/fonts/pretendard/`에 로컬 번들(OFL 사본 포함), 전역 바탕·먹·`tabular-nums`·`keep-all`, 키 일치 테스트.
2. 앱 셸: 220px 먹녹색 사이드바, 표제란(분석연도·격자·선택 격자·최근 수집일·모드), 모바일 한 줄 요약. 연도 select·기본 대상지 버튼은 기존 컨트롤 그대로.
3. 근거 체계: `ProvenanceBadge`, `MissingValue`. 0.4의 서버 필드가 있는 곳만 배지.
4. 지도: 부하/편익 램프, 결측 해치(`addImage` + `fill-pattern`), 선택 외곽선+헤일로, 범례의 자료 미확보 칩 분리, 용도지역 외곽선 오버레이, 도면지 바탕 + 1km 참조 격자, 축척·북쪽 표시. 범례 경계 계산(`classify`)은 그대로.
5. 대시보드 지표 8개, 기상 차트 결측 해치 띠, 나머지 화면, 계획안 3색.
6. 보고서 표제란 + 근거 해시, A4 인쇄 CSS.
7. 하드코딩 색 정리, 미사용 스타일 제거.
