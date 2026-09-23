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

## 1. 토큰과 서체

- 추가: `frontend/src/styles/tokens.css`(DESIGN.md 2.1–2.6 값 그대로 + 적용 중 추가분), `frontend/src/theme/palette.ts`(같은 키·값, 램프·용도지역 이름 매핑), `frontend/src/theme/palette.test.ts`(키·값 일치, 램프 단조성, 글자 대비, 용도지역 매핑), `frontend/src/styles/base.css`(도면지 바탕, 먹 글자, `tabular-nums`, `keep-all`, 포커스 링, reduced-motion).
- 서체: Pretendard Variable 1.3.9 dynamic subset(woff2 92개, 3.1MB, 화면에 쓰인 글자 범위만 내려받음)을 `frontend/public/fonts/pretendard/`에 넣고 `index.html`에서 로컬 경로로 연결. CDN 없음. SIL OFL 1.1 사본(`LICENSE.txt`)과 출처(`SOURCE.txt`) 동봉. npm 의존성을 추가하지 않았으므로 JS 번들 변화 없음(폰트 CSS는 `public/`에서 별도 요청).
- `main.tsx`: `tokens.css` → `base.css` → 화면 CSS 순서로 한 번 import.
- `styles.css`: 유리 효과 토큰 구역을 지우고, 남은 규칙이 새 토큰을 쓰도록 임시 별칭을 둠(정리 단계에서 제거).
- DESIGN.md 개정(사유는 DESIGN.md 11): 중립 순차 램프 `--seq-*`, 건물 용도 색, 에너지원 계열 색, 대비 규칙 3가지.
- 대비 계산 결과: `--ink-3`은 흰 바탕 4.83, 도면지 4.34, 표 머리 4.04, 결측 바탕 4.23 → 흰 바탕 전용으로 제한. 결측 배지 글자 4.23 → `--ink-2`(5.9)로 대체. `--line-strong` 테두리 1.94 → 입력칸 테두리는 `--ink-3`(4.83).

## 2. 앱 셸

- `Layout.tsx`: 220px 먹녹색 사이드바(브랜드, 메뉴 7개, 하단 온라인/오프라인 칩 + 버전·기준연도). 지도 화면에서 메뉴를 아이콘으로 접던 동작(`compact-nav`)은 없앴다 — 220px 사이드바를 두고도 1440px에서 지도 65% · 상세 35% 배치가 들어간다.
- `TitleBlock.tsx`(신규): 분석연도 | 격자 | 선택 격자 | 최근 수집일 | 모드. `useAnalysisScope`는 읽기만 한다. 390~760px에서는 "연도 | 격자" 한 줄 버튼으로 접고 누르면 펼친다(`aria-expanded`).
  - "자료 기준일" 대신 **"최근 수집일"**로 표기: 값이 `/api/sources`의 `collected_at` 최대값(마지막 수집 시각)이라 자료의 기준기간(예: 2025년)과 다르기 때문. 요청 실패는 "확인 불가", 수집 기록이 없으면 "수집 기록 없음".
  - 모드 칸: `/api/system`의 `offline_mode`. 지도 화면에서 배경지도가 없으면(오프라인·끔·타일 실패) "배경지도 없음"을 덧붙인다(4단계에서 연결).
  - 격자 칸은 시스템 고정값 "500m 분석 격자", 격자를 고르지 않았으면 "기본 대상지"(예비 선정 격자).
- `AnalysisScopeBar.tsx`: 기존 연도 select(`aria-label="분석연도"`, 네이티브 select 유지)와 "기본 대상지로" 버튼만 남긴 컨트롤. 로직 변경 없음.
- `SystemStatus.tsx`: 공용 `useSystemInfo` 저장소로 `/api/system`을 한 번만 읽고 표제란과 공유. 전환 요청·이벤트(`carbon-system-change`)는 그대로.
- 신규 훅: `useSystemInfo.ts`, `useBasemapStatus.ts`.
- `PageHeader.tsx`: 영문 대문자 눈썹 라벨(`eyebrow`) 제거, 제목 20px/600.
- CSS: `styles/shell.css`, `styles/components.css`(버튼: 주 버튼 `--primary` 채움, 나머지 흰 바탕 `--line-strong`, 반경 6px). `styles.css`에서 셸·헤더·버튼 구역 삭제.
- 애니메이션: DESIGN.md 8("선택 확대 하나만")에 따라 드로어 슬라이드·화살표 회전 전환 효과를 두지 않았다.

## 3. 근거 체계

- 신규: `components/ProvenanceBadge.tsx`(실측·계산·추정·시나리오·대체·자료 미확보, 추정·대체 점선·시나리오 점 테두리, 한글 라벨 필수), `components/MissingValue.tsx`("—" + 사유, 화면 낭독기에는 "자료 없음"), `lib/provenance.ts`(서버 코드 → 배지 매핑, 모르는 값은 `null`로 배지 없음), 테스트 `lib/provenance.test.ts`, `components/Provenance.test.tsx`.
- 삭제: `components/DataClassChip.tsx`, `lib/format.ts`의 `DataClass`/`DATA_CLASS`, `mapMetrics.ts`의 지표별 `dataClass`. 모두 프런트 상수로 근거를 단정하던 것이라 0.4 백로그로 옮김. `mapMetrics.test.ts`의 "data class" 단언은 "dataClass 필드가 없다"로 바꿈(사유: 서버 필드만 매핑).
- `QualityBadge.tsx`: 근거 코드는 근거 배지로, 작업·모델 상태 코드는 상태 태그로, 서버의 자유 문장(예: "공간매칭된 관측 / 표본 범위 확인")은 중립 태그로 그대로 표시.
- `MetricCard.tsx`: 라벨 13px → 값 28px + 단위 0.85em → 근거 배지 + 기준 12px. 아이콘·강조색 띠 제거. 값이 없으면 `MissingValue`와 "자료 미확보" 배지, 카드 배경 해치(해치 위 글자는 결측 바탕을 깔아 판독성 확보).

적용 위치와 서버 필드:

| 화면 | 위치 | 서버 필드 → 표시 |
|---|---|---|
| 대시보드 | 전력·가스 사용량 카드, 월별 관측 에너지 패널 | `observations_label` → 실측. `annual_complete.*`로 "완전 연간 값"/"관측 기간 합계 N/12개월" 구분 |
| 대시보드 | 월별 기상 패널 | `weather[].source_type` → 실측 N개월 / 대체 M개월, 행이 없으면 자료 미확보 |
| 대시보드 | 나머지 카드 | 배지 없음(필드 없음). 값 `null`이면 결측 표시와 사유 |
| 지도 상세 | 도시 형태 | `building_source === 'OSM'` → 대체(OSM). `building_count === null` → 자료 미확보 |
| 지도 상세 | 선택 지표·에너지·토지이용 | 값·관측 월이 없을 때만 자료 미확보 |
| 시뮬레이션 | 결과 머리 | `data_class` → 시나리오, `quality` 문장은 중립 태그 |
| 시뮬레이션 | 최적화 | `status`가 있을 때만 상태 태그(이전의 `'CALCULATED'` 기본값 제거) |
| 보고서 | 계획안 비교 머리 | 각 계획안 `result.data_class` → 시나리오 |
| 보고서·분석 | 출처 표 | `source_type` → 공식·대체·파생·미검증 출처 표기 |

결측을 0·빈칸으로 보이던 곳을 고친 목록:

- 대시보드 기상 패널: HDD·CDD 합계가 값이 없는 달을 0으로 더했다 → 값이 있는 달만 더하고 "(N개월 합계)" 표기, 전부 없으면 "—".
- 보고서 계획안 비교: `Number(null)`이 0이 되어 결측이 "0"으로 인쇄될 수 있었다 → 결측 셀은 "—"(`title="자료 미확보"`).
- 보고서 출처 표: 정규화 행이 `null`이면 "행"만 남았다 → "—".
- 출처 상세 품질 점수: 미산정 점수의 막대가 0% 막대로 보였다 → 해치 막대 + "점수 미산정".
- 모델 표본 진행: 응답에 개수가 없으면 0으로 그렸다 → "—"와 해치 막대.
- 시뮬레이션 결과: 품질 값이 없을 때 `'ESTIMATED'`를 기본값으로 넣어 "추정"으로 보이던 것 제거.

## 4. 지도

- `pages/MapPage.tsx`
  - 램프: 지표마다 `ramp`를 둠(`mapMetrics.ts`). 에너지·탄소 7종은 부하(흙색), 관측 완전성은 편익(녹색), 건물 수·건폐율·용적률·층수·세대수·용도 비율 7종은 중립 순차(`--seq-*`). 범례 경계 계산(`classify`/`quantileBounds`, 지표별 고정 경계)은 그대로.
  - 결측 격자: `map.addImage('hatch-missing', …)`로 45° 해치 이미지를 만들고 `grid-missing` 레이어(`fill-pattern`, 현재 지표 값이 `null`인 격자만)로 칠함. 바탕색은 램프 최저색이 아닌 `--prov-missing-bg`.
  - 격자 면 불투명도 0.85(확대 14 이상에서 건물이 보이도록 옅어짐). 격자선: 배경지도 위 흰색 0.6, 배경지도가 없으면 `--line-strong`.
  - 선택 격자: `selected-halo`(흰 4.5px) 위에 `selected-grid`(`--select-line` 2.5px) — 2.5px + 바깥 1px 헤일로. 호버 1.5px 60%.
  - 범례: 순차 칸 + 실제 경계값·격자 수, 8px 띄운 "자료 미확보 (0 아님)" 해치 칩, 값 있는 격자 비율, 정의·산식은 접이식. 용도지역·행정동·건물 오버레이가 켜지면 별도 블록.
  - 용도지역: 면 채움 대신 외곽선(1.5px 세부 용도지역 색 + 흰 3.5px 헤일로), 미분류는 해치. 세부 색은 서버 `zone_name`의 공식 명칭을 `palette.ts`의 `ZONE_DETAIL`로 대응. 자료가 없을 때 토글을 끄지 않고 켜면 "용도지역 자료 미확보: VWorld 또는 원본 파일 승인 후 표시됩니다."를 표시(행정동 인구도 같은 방식).
  - 배경지도가 없을 때(오프라인·끔·타일 실패): 도면지 `--canvas` 바탕 + 1km 참조 격자(`lib/mapGrid.ts`: 격자 ID의 EPSG:5179 좌표와 도형 중심으로 국소 아핀 변환을 맞춰 1km 선 생성, 테스트 `mapGrid.test.ts`). 표제란 모드 칸에 "배경지도 없음".
  - 축척 막대(`ScaleControl`)와 북쪽 표시(나침반 버튼)를 좌하단, 확대 버튼·출처는 우하단.
  - 배치: 지도 약 65% + 선택 격자 상세 열(35%, 최소 320px). 1100px 이하는 상세를 지도 아래로, 760px 이하는 범례·지표 선택도 지도 아래로 쌓음.
  - 선택 격자 상세: 제목 아래 격자 ID 텍스트, 지표 8개 2열 밀집 카드, 월별 관측 띠(없는 달 해치), 월평균 기온 차트(격자 공통), 용도지역·건물 용도 구성비 막대, 공동주택, [이 격자 시뮬레이션]. 선택 확대만 300ms ease-out, `prefers-reduced-motion`이면 즉시.
  - 행정동 인구밀도: 중립 순차 5단계(등간격), 결측은 결측 바탕.
- 신규 공용 컴포넌트: `ShareBar.tsx`(구성비 막대, 미분류·나머지 해치), `WeatherChart.tsx`(1–12월 고정 축, 결측 월 끊김 + 해치 띠, 툴팁에 월별 근거).
- `lib/chartTheme.ts`: 토큰 색, 1.5px 선, 추정 점선(4 3)·시나리오 점선(1 3), `missingBands`(해치 띠 "자료 없음"), `monthsOf`(없는 달은 `null`). 영역 그라데이션 채움 제거. 테스트 `chartTheme.test.ts`.
- `styles/map.css`(신규), `styles.css`에서 지도 구역 삭제.
- 테스트 변경(사유: 색이 토큰으로 바뀜, 의미는 같음): `MapPage.test.ts`의 결측 색 단언을 `#cbd5d1`/`#d7d3de` → `TOKENS['prov-missing-bg']`로, 외곽선 색 테스트 추가. `mapMetrics.test.ts`에 램프 구분 테스트 추가.
- E2E 변경: `scripts/e2e-overlays.cjs`는 자료가 없는 오버레이 토글이 "비활성"이어야 한다고 검사했으나, DESIGN.md 2.5("토글을 숨기지 말고 켰을 때 미확보 안내")에 맞춰 "켜면 `.overlay-missing`에 '자료 미확보' 안내가 뜬다"로 바꿈. 이 경우 결과는 여전히 SKIP이며 PASS로 세지 않음. `renderedZoning`은 외곽선 레이어(`zoning-line`) 기준.
- 적용하지 않음: 추정 값 격자 위 "가는 사선"(DESIGN.md 2.3) — 지도 지표별 근거 유형 필드가 서버에 없어 어느 격자·지표가 추정인지 표시할 근거가 없음(0.4 백로그).

## 5. 대시보드와 나머지 화면

- 대시보드(`DashboardPage.tsx`): 지표 카드를 **8개**로 맞춤(전력 사용량, 가스 사용량, 전력 탄소배출, 전력 원단위, 세대당 전력, 건폐율 근사, 추정 용적률, 주거지역 비율). 빠진 "건물 수"는 대상지 요약의 표제란식 칸(격자 ID, 면적, 건물 수, 공동주택, 행정동)으로 옮김. 이전 9개는 `scripts/e2e-refined.cjs`·`e2e-public.cjs`의 "`.metric-card` 8개" 검사와 어긋나 있었음.
  - 월별 관측 에너지 차트: 1–12월 고정 축, 없는 달은 `null`로 선을 끊고 해치 띠 "자료 없음", 툴팁에 "(실측)"(`observations_label`). 영역 그라데이션 제거.
  - 관측 범위: 녹색 그라데이션 블록 대신 "관측 N / 24개월" 수치와 월별 띠(없는 달 해치).
  - 에너지 관측이 없을 때: "월별 에너지 관측이 없어 운영탄소를 계산하지 않았습니다." → 조건(관측 월 0 / 필요 1 이상) → [수집 상태 보기] (DESIGN.md 5 빈 상태 형식).
  - 건물 용도·용도지역 구성: `ShareBar`(용도 미상·도시지역 외는 해치). 월별 기상: `WeatherChart`(없는 달 해치 띠) + 자료·관측 월·HDD·CDD 표.
  - 전주시 전체 수집 합계의 탄소 `null`은 "— 가스 계수 확정 전".
- 분석(`AnalysisPage.tsx`): 어두운 그라데이션 카드 → 흰 패널, 결측은 `MissingValue`. HDD 산점도는 전력 원·가스 사각 표지로 모양도 구분, 툴팁에 "(실측)". 행정동 인구 막대는 `--primary`, 용도지역 도넛은 대분류 토큰 색 + 미분류 해치. 출처 표에 공식·대체·파생 출처 표기(`source_type`).
- 모델(`ModelPage.tsx`): "학습 데이터 부족" 경고(경고 바탕, `role="status"`), 모델 상태 태그에 `READY_FOR_SPATIAL_VALIDATION`(공간 검증 준비)·`SPATIALLY_EVALUATED`(공간 교차검증 완료)·`INSUFFICIENT_BASELINE_DATA`(기준 자료 부족) 한글 라벨 추가(코드 의미 그대로). 비교표 수치 오른쪽 정렬, R²는 소수 2자리(DESIGN.md 3), MAE·RMSE는 이전과 같은 3자리.
- 시뮬레이션(`SimulationPage.tsx`): 층수 프리셋 5·10·20·30·40층 유지, 개념 배치도(축척 없음, 층수 비례, 시나리오 점선 테두리). 결과 차트는 현황 `--ink` 실선, 시나리오 `--plan-a` 짧은 점선(1 3), 증감은 부호별 증감 램프 막대(감소 녹색, 증가 흙색). 화면당 주 버튼 1개 원칙에 따라 "최적안 탐색"을 보조 버튼으로.
- 수집 데이터(`DataPage.tsx`)·출처 상세(`SourceDetailPage.tsx`): 영문 눈썹 라벨 제거, 유리·그라데이션 제거, 표 결측 셀 "—"(`title="자료 미확보"`), 월 선택기의 선택 불가 달은 해치. 수집 범위 SMOKE/LIMITED/FULL 라디오·체크박스 역할과 이름은 그대로.
- CSS: `styles/pages.css`(신규). `styles.css`에는 보고서 규칙만 남김(6단계에서 이동).
- 검증: `bun test` 54건 통과, E2E(미리보기 서버) `e2e.cjs` 9, `e2e-refined.cjs` 10(8개 카드, 연도 전환, 지도 선택, 시나리오→보고서, 내려받기, 인쇄 시 사이드바 숨김, 390px 5개 화면 가로 넘침 0, 503 오류 표시), `e2e-overlays.cjs` 7 모두 통과. 미리보기 서버가 `Content-Disposition`을 넘기지 않아 내려받기 검사가 멈추던 문제는 미리보기 서버 쪽을 고쳐 해결(앱 코드 변경 아님).

## 6. 검토 보고서와 인쇄

- `ReportsPage.tsx`: 보고서 첫 장 머리에 표제란(분석연도 | 격자 | 선택 격자 | 최근 수집일 | 작성 방식 | 생성 시각) + 근거 해시(SHA256 전체) 칸. 영문 대문자 머리말(`CARBON URBAN DSS · …`)을 한글 캡션으로 바꾸고, 기존 `report-meta` 목록은 표제란으로 합침(같은 값).
- 계획안 비교: 선택 순서대로 계획안 A·B·C(`--plan-a/b/c`) — 선택 목록에 색 띠와 "계획안 A" 칩, 보고서 표의 열 머리에 색 띠 + "대안 N" + "계획안 A" + 시나리오 배지(`result.data_class`). 서버가 선택 순서를 보존함(`reporting.py`의 `dict.fromkeys`)을 확인. E2E가 보는 "대안 1" 문구는 별도 요소로 유지.
- 화면당 주 버튼 1개: "보고서 작성"만 주 버튼, "인쇄 · PDF 저장"과 "문서 내려받기"는 보조 버튼.
- `styles/report.css`(신규): A4 세로 여백 18mm, 흰 바탕, 사이드바·표제란 머리·버튼 숨김(`.no-print`, 셸 인쇄 규칙), 표제란·표·행 `break-inside: avoid`, 표 머리 반복, 배지·해치·계획안 색은 `print-color-adjust: exact`.
- `styles.css`에는 임시 별칭만 남음(7단계에서 삭제).
- 검증: `e2e-refined.cjs`의 보고서 작성·내려받기(근거 SHA256 포함)·인쇄 미리보기(사이드바 숨김) 통과. 인쇄 캡처 `after/reports-print.png`, Chromium A4 PDF `after/reports-print.pdf`.

## 7. 정리와 검증

### 하드코딩 재집계

`rg -n "#[0-9a-fA-F]{3,8}\b" frontend/src --glob '!**/tokens.css' --glob '!**/palette.ts'` → **125줄 → 6줄**. 남은 6줄은 모두 `src/theme/palette.test.ts`가 DESIGN.md의 값(도면지, 먹녹색, 추정 색, 해치, 부하 램프, 편익 램프 끝값)을 그대로 쓰는지 대조하는 단언이다(의도된 예외). 컴포넌트·페이지·CSS의 hex와 `rgba()`는 0개(`rgba`는 tokens.css의 그림자·스크림·배경지도 위 격자선, palette.ts의 같은 값만).

- `styles.css`(임시 별칭만 남았던 파일) 삭제. 새 CSS: `styles/tokens.css`, `base.css`, `shell.css`, `components.css`, `map.css`, `pages.css`, `report.css`.
- 쓰지 않는 규칙 제거(`.badge-dot`, `.text-button`). 남은 CSS 클래스는 모두 컴포넌트에서 쓰이거나 MapLibre 내부 클래스.
- 대시보드가 지도 지표 정의 전체(`mapMetrics.ts`의 `METRICS`)를 초기 번들에 끌고 오지 않도록 대분류 이름·용도 색을 `lib/labels.ts`로 분리(`mapMetrics`는 다시 내보냄).
- 그림자: 팝오버·드로어(`--shadow-popover`)만. 나머지 `box-shadow`는 1px 선택 표시(inset)와 해치 위 글자 바탕.

### 검증 결과

| 항목 | 결과 | 비고 |
|---|---|---|
| 단위 테스트 | **54건 통과**(19파일) | Bun 1.4.2 + jsdom(`vitest` API 호환 준비 파일). 사용자 PC의 `npm test`(Vitest 4)는 아직 실행 안 함 |
| 타입 검사 | 통과 | 작업 환경 `tsc`(테스트 제외 설정) + 사용자 PC 저장소에서 `tsc -p tsconfig.app.json --noEmit`(테스트 포함) 단계마다 통과 |
| `npm ci && npm run build` | **실행 못 함** | 작업 환경에서 npm 레지스트리·rollup 네이티브 바이너리를 받을 수 없음. 사용자 PC에서 `cd frontend && npm ci && npm test && npm run build` 필요 |
| E2E `scripts/e2e.cjs` | 9/9 통과 | 오프라인 전환 후 외부 요청 0 포함 |
| E2E `scripts/e2e-refined.cjs` | 10/10 통과 | 지표 카드 8개, 연도 전환·기상 없음, 지도 선택, 시나리오→보고서, 내려받기(근거 SHA256), 인쇄 시 사이드바 숨김, 390px 5개 화면 가로 넘침 0, 503 오류 표시 |
| E2E `scripts/e2e-overlays.cjs` | 7/7 통과 | 자료가 없는 경우의 새 경로(켜면 "용도지역 자료 미확보" 안내)는 오버레이 응답을 비운 별도 브라우저 확인으로 통과 |
| 오프라인 모드 | 통과 | 지도·대시보드 1440/390px에서 외부 요청 0, Pretendard 로드 확인(`document.fonts.check`), 아이콘 SVG 표시, 표제란 "오프라인 / 배경지도 없음", 가로 넘침 0 — `after/offline-check.json` |
| 대비 | 통과(규칙 내) | `palette.test.ts`: 본문·보조 글자, 근거 배지 4종, 상태 4종, 사이드바, 주 버튼 4.5:1 이상. `--ink-3`는 흰 바탕 전용(4.83). 해치 선이 지나가는 글자(선택 불가한 달, 월별 띠의 빈 달)는 선 위 4.36으로 4.5 미만 — 바탕 평균 5.9이고 해치 자체가 "없음"을 전달하므로 남김 |
| 백엔드 | 변경 없음 | `git diff 16d5c70..HEAD -- backend` 비어 있음 |

E2E는 사용자 PC의 Docker(nginx 5173)가 아니라 작업 환경의 미리보기 서버에서 돌렸다: 실제 FastAPI 앱을 그대로 쓰고 DB는 2026-09-23 백업 사본(PostGIS 대신 PostgreSQL 16, 공간 연산 일부는 대체), 번들은 Bun으로 만든 미리보기 빌드, 배경지도 타일은 차단.

### 번들 크기 (Bun minify, 전후 같은 방법)

| 항목 | 변경 전 | 변경 후 | 차이 |
|---|---|---|---|
| 초기 JS `main.js` | 312,057 B / gzip 100,336 B | **310,149 B / gzip 99,857 B** | −1,908 B / −479 B |
| 전체 JS(지연 청크 포함) | 2,587,649 B / gzip 797,227 B | 2,605,327 B / gzip 802,514 B | +17,678 B / +5,287 B (지도 화면 청크: 참조 격자·해치·상세 카드·기온 차트) |
| CSS | 150,738 B / gzip 23,582 B | 154,718 B / gzip 22,398 B | +3,980 B / −1,184 B |
| 폰트(`public/fonts`) | 없음(시스템 글꼴 대체) | woff2 92개 2,957,724 B | 화면에 쓰인 글자 범위의 파일만 내려받음. JS 번들과 별개 |

새 npm 의존성 없음. Vite 기준 수치는 사용자 PC의 `npm run build` 출력으로 확인해야 한다.

### 전후 캡처

- 변경 전 `data/validation/design/before/`, 변경 후 `data/validation/design/after/` — 같은 스크립트·같은 조작(30층 → 시나리오 계산, 보고서 작성), 같은 데이터.
- 1440px·390px 8개 화면씩, 인쇄 `reports-print.png`·`reports-print.pdf`. 변경 후에만 오프라인 캡처 `map-offline-*.png`, `dashboard-offline-*.png` 추가.

### 적용하지 못한 부분과 백로그

1. **지표별 근거 배지**(지도 15개 지표, 대시보드의 탄소·원단위·건폐율·용적률·주거지역 비율): 서버 응답에 지표별 근거 유형 필드가 없어 표시하지 않음. 백엔드에 `provenance` 필드를 추가하는 별도 작업 필요(이번 지시는 API 계약 변경 금지).
2. **추정 값 격자의 가는 사선**(DESIGN.md 2.3): 같은 이유로 미적용.
3. **`npm ci / npm test / npm run build`와 Docker E2E**: 사용자 PC에서 실행해야 함. 특히 Vitest 4가 `tokens.css?raw`를 읽는 테스트(`palette.test.ts`)와 Vite의 `public/fonts` 복사를 실제로 확인해야 함.
4. 원격 푸시: 이 작업 환경에는 저장소 쓰기 권한이 없어 커밋은 사용자 PC 저장소에만 있음(`git push origin main` 필요).
5. 다크 모드: 범위 밖(DESIGN.md 10). 토큰 구조만 둠.
