# Carbon Urban DSS

> **팀원 공통: 자료를 모으거나 계산·보고서를 만들기 전에 [공통 데이터 기준](docs/DATA_STANDARD.md)을 먼저 읽습니다.** (앱 메뉴 사용 방법 → 데이터 기준에서도 볼 수 있고, `python -m app.cli check-standard`로 점검합니다. 팀 자료 비교: [TEAM_DATA_COMPARISON](docs/TEAM_DATA_COMPARISON.md))

500m 격자 단위 공공데이터 기반 에너지·운영탄소 의사결정 프로토타입입니다. 전주시에서 시작했고, 이제 **전국 시·군·구 어디든 골라 그 지역 자료를 직접 수집해 같은 분석**을 할 수 있습니다([전국 적용](docs/NATIONWIDE.md)). **실측, 공공데이터 계산, 추정, 시나리오를 분리**하며, 결측값을 0으로 만들지 않습니다.

## 사용 방법

![전국 지도: 시·도를 지도나 메뉴에서 고릅니다](docs/images/usage/u01-national.jpg)

**지도 분석**(`/map`)은 전국에서 500m 격자까지 다섯 걸음입니다.

| 걸음 | 화면 | 하는 일 |
|---|---|---|
| 1 | 전국 | 지도나 왼쪽 메뉴에서 시·도를 고릅니다. 시·도끼리 인구·밀도·가구·인구 증감·주택·종사자·공동주택 단지로 비교합니다. |
| 2 | 시·도 | 그 시·도의 시·군·구가 같은 지표로 칠해지고 순위가 나옵니다. 시·군·구를 누르면 요약과 **지도 열기**가 나옵니다. |
| 3 | 시·도 500m 격자 | 시·도 전체를 SGIS 500m 격자(2000~2024 인구·가구·주택·종사자)로 봅니다. 제주는 제외합니다. |
| 4 | 시·군·구 지도 | 500m 분석 격자에 에너지·탄소·건물·용도지역 등 지표 36개와 레이어 8개. 격자를 누르면 상세가 열립니다. |
| 5 | 읍면동 | 격자 지표를 행정동으로 모으고 동끼리 비교합니다. |

| 시·도 → 시·군·구 비교 | 시·군·구 지도 |
|---|---|
| ![전북의 시·군·구를 인구 증감률로 비교](docs/images/usage/u02-national-sido.jpg) | ![전주시 500m 분석 격자](docs/images/usage/u05-region-map.jpg) |

- 머리의 **시·도 → 시·군·구** 선택 상자로 어느 화면에서든 전국 어디나 고릅니다. 아직 지도가 없는 곳은 전국 공통 자료로 몇 초 만에 기본 지도를 만듭니다.
- 그 밖의 메뉴: 대시보드 · 분석 · 모델 · 지역 시뮬레이션(구역의 과거·개발 전후·목표 감축) · 시뮬레이션(계획안·3D 배치·일조) · 수집 데이터 · 검토 보고서 · 전국 지역.
- 값마다 **관측 · 계산 · 추정 · 시나리오 · 대체 · 자료 없음** 배지가 붙습니다. 빗금과 "자료 없음"은 0이 아닙니다.

자세한 안내: **[사용 안내 (화면 사진과 순서)](docs/USAGE.md)** · [사용 안내 슬라이드 22장 (.pptx)](docs/usage/Carbon-Urban-DSS-guide.pptx) · **소개와 활용 31장**([.pptx](docs/presentation/Carbon-Urban-DSS-소개와-활용.pptx) · [PDF](docs/presentation/Carbon-Urban-DSS-소개와-활용.pdf), 작업 내역·데이터 범위·사용법·업종별 활용 예시 11가지) · **소개 · 전주 사례 28장**([.pptx](docs/presentation/Carbon-Urban-DSS-소개-전주사례.pptx) · [PDF](docs/presentation/Carbon-Urban-DSS-소개-전주사례.pdf), 데이터→결과·범위, 에코시티·서부신시가지 시뮬레이션) · [정확도 점검 발표 17장](docs/presentation/Carbon-Urban-DSS-presentation.pptx) · 앱 메뉴 **사용 방법**(`/guide`) · [전국 자료 현황·보충 자료](docs/NATIONWIDE_DATA.md)

## 실행

Docker Desktop Linux 엔진을 켜고 이 폴더에서 실행합니다. 기존 `.env`는 보존하세요.

```powershell
docker compose up --build -d
```

- 웹: [http://localhost:5173](http://localhost:5173)
- API 문서: [http://localhost:8000/docs](http://localhost:8000/docs)
- 상태: [http://localhost:8000/api/health](http://localhost:8000/api/health)

외부 시연까지 한 번에 시작하려면 바탕화면의 **Carbon Urban DSS 서버 실행.cmd** 또는 다음 파일을 실행합니다. Docker Desktop이 꺼져 있어도 실행기가 시작·대기하고, 로컬 LLM과 외부 HTTPS 주소까지 검사한 뒤 브라우저를 엽니다.

```powershell
scripts\start-prototype.cmd
```

첫 실행은 로컬 `data/raw`를 정규화합니다. 파일이 없으면 현재 수집 가능한 공개 소스만 요청합니다. 인증정보가 없거나 최근 공급기관에서 거절된 소스는 수집 작업을 만들기 전에 차단 사유를 표시합니다. 공공데이터 서비스키는 **백엔드 환경변수 `DATA_GO_KR_SERVICE_KEY`**에만 둡니다. `.env`를 Git이나 채팅에 공유하지 마세요.

키를 변경했다면 다음 명령으로 API·worker의 환경을 갱신한 뒤 수집 데이터 화면에서 다시 수집합니다.

```powershell
docker compose up -d --force-recreate api worker
```

## 팀원 PC 재현·백업·검증

Git clone만으로는 DB·원본(`data/raw`)·API 키·AI 모델이 전달되지 않습니다. 새 PC 준비, 승인된 데이터 묶음 내보내기/가져오기, 백업·복원 검증은 [팀원 PC 재현 안내](docs/TEAM_SETUP.md)를 따릅니다.

```powershell
scripts\dss.cmd Doctor                 # 사전 점검(키 값은 출력하지 않음)
scripts\dss.cmd All                    # 백업 → 재빌드 → 단계 수집 → 복원 검증 → 테스트
scripts\dss.cmd ExportBundle           # 팀 공유 묶음(.env·캐시·임시 URL 제외)
scripts\dss.cmd ImportBundle -BundlePath <zip>  # 빈 DB(새 PC)
scripts\dss.cmd MergeBundle -BundlePath <zip>   # 팀원 자료를 지금 DB에 더하기(중복 없이, -DryRun으로 미리 세기)
```

결과는 `data\ops\<시각>-<작업>\summary.json`에 저장됩니다.

## 데이터와 한계

**최신 수집·정제·결과 현황과 지도 지표별 의미·활용은 [RESULTS_2026-09-26](docs/RESULTS_2026-09-26.md)** 에 있습니다(PC Docker 실측 숫자). 요약:

- 건축HUB 전 지번 월별 전력·가스 2024·2025년, 건축물대장 73,147동, VWorld 건물·용도지역·연속지적, SGIS 2015~2024 행정통계와 1km 격자(2024), ASOS 2015~2025를 수집·정제했습니다.
- 2025년 건물 전체 전력 약 2.08TWh, 전력 탄소 약 94.6만tCO₂eq(617개 격자). 도시가스 탄소는 공식 계수 대신 고정 규칙의 가정 계수(0.1826 kgCO₂eq/kWh, IPCC 2006 기본값)로 따로 계산하고 '가정'으로 표시합니다.
- 과거 에너지는 K-apt 단지 자료(2015~)를 PC에서 자동으로 수집 중입니다(일일 한도 5,000건, 00:20 자동 재개). 건축HUB는 2020-01부터 있어(2023-10까지는 옛 시·군·구 코드로 조회) 전주는 2020~2025를 받았습니다. 2020-09·10월은 대단지 일부가 빠져 2020년 합계는 비교하지 않습니다.
- **정확도·신뢰도 평가([ACCURACY](docs/ACCURACY.md))**: 건축HUB 전력은 한전 건물 전력의 76~79%를 담고 월별 상관 0.996 이상이라 지역 안 비교에 쓸 수 있고, 총량은 보정해서 읽습니다. 모델은 공간 블록 교차검증으로 전주 전력 nMAE 9%·가스 11%, 수원 전력 15%·가스 40%입니다([모델 검증](docs/MODEL_VALIDATION.md)). 화면 **모델 → 공식 통계와 맞대기**가 같은 비교를 현재 DB로 계산합니다.
- 전국: 법정 행정구역 20,560개(분석 단위 230곳), SGIS 2024 시군구 252·행정동 3,553, K-apt 단지 목록 약 2.25만, SGIS 공식 500m 격자 416,132칸, SGIS 1km 격자 10.8만 칸을 받았습니다. 두 번째 지역으로 수원시를 준비했습니다(격자 559, 건물 72,626동, 건축물대장 61,224건, 건축HUB 2025 전 지번, 전력 모델 nMAE 14.8%). K-apt 월별 에너지는 일일 한도로 이어서 받는 중입니다([전국 적용](docs/NATIONWIDE.md)).
- 전국 공식 통계(2026-09-30 추가): **한전 시군구별 전력판매량**(2015~2025 연도별, 2026년 1~7월)으로 건물 전력·가구당 주택용 전력·2018년 대비 증감률을, 온실가스종합정보센터 **지역 온실가스 인벤토리**(시·군·구 229곳, 2010~2023)로 건물 등 온실가스·증감률·총배출량을 전국 지도에 칠하고, 한국가스공사 **시·도 도시가스 판매량**(1989~2024)을 시·도 요약에 보여 줍니다. 전력 배출계수는 공표 회차별(2018·2021·2024 승인)로 등록해 2019~2024년 계산에도 계수가 붙습니다([탄소 계산](docs/CARBON_METHOD.md)).
- 지도 분석은 **전국**(시·도를 지도·메뉴에서 고르고 그 시·도의 시·군·구를 같은 지표로 비교, [전국 자료 현황·보충 자료](docs/NATIONWIDE_DATA.md))에서 시작해 **시·도 500m 격자**(제주 제외 15개 시·도, 전국 공통 지표: SGIS 500m 격자 인구·가구·주택·종사자와 2015년 대비 인구 증감(자료제공 신청분, 2000~2024), SGIS 1km 비율 지표, K-apt 단지)에서 시작해 **전국 어느 시·군·구든** 지도로 엽니다. 처음 여는 곳은 전국 기초 자료로 기본 지도를 몇 초 만에 만들고, 상세 자료(에너지·탄소·건물·용도지역)는 전주시·수원시처럼 따로 모읍니다. 시·군·구 안에서는 **읍면동(행정동)** 을 골라 격자 지표를 동 단위로 모으고 동별로 비교합니다([전국 적용 6절](docs/NATIONWIDE.md)).
- 지역마다 다른 규칙: 건폐율·용적률은 그 지역 도시·군계획 조례(law.go.kr에서 받아 읽음, 조례 기관 160곳 모두 읽음) → 조례에 없으면 국토계획법 시행령 제84·85조 → 세분·지정되지 않은 땅은 국토계획법 제79조 순서로 정하고, 개발제한구역·지구단위계획구역은 따로 표시합니다. 관측이 없는 격자의 시뮬레이션은 지역 관측 공동주택 평균 원단위로 추정합니다([전국 적용 4·5절](docs/NATIONWIDE.md)).

API 화면은 문서의 숫자를 복제하지 않고 **현재 DB**를 조회합니다. 초기 조사 기록은 [DATA_SOURCE_DISCOVERY](docs/DATA_SOURCE_DISCOVERY.md)와 [검증 보고서](docs/FINAL_REPORT.md)에 남아 있습니다.

## 오프라인 시연

최초 실데이터 수집 후 다음 명령은 원본을 보존하고 검증된 로컬 상태를 준비합니다.

```powershell
docker compose exec api python -m app.cli demo
```

DB와 원본 캐시를 사용하며 외부 API 호출을 차단합니다. 웹의 오프라인 모드 버튼으로도 전환할 수 있습니다. 온라인 복귀:

```powershell
docker compose exec api python -m app.cli online
```

환경변수 `DEMO_OFFLINE_MODE=true`가 설정되면 UI/명령으로 해제해도 환경변수를 제거하기 전까지 오프라인입니다. 지도 분석용 경계·건물·격자는 로컬 GeoJSON이며 배경 타일은 선택적으로 외부망을 사용하므로 오프라인에서는 배경 없이 분석 도형을 표시합니다.

## 검증

```powershell
docker compose exec api python -m pytest -q
cd frontend
npm ci
npm test
npm run build
```

별도 깨끗한 DB로 재현 검증하는 명령과 브라우저 E2E 결과는 [TESTING](docs/TESTING.md)에 설명합니다. `docker compose down`은 컨테이너를 내려도 DB 볼륨과 `data/`를 보존합니다. **`down -v`는 수집 DB를 삭제하므로 사용하지 마세요.**

## 구현 안내

- [디자인 시스템 D안 「도시계획 도면」](docs/DESIGN.md) · [적용 기록](docs/DESIGN_APPLY_LOG.md) — 화면 색·서체·근거 배지·결측 표시·지도 규칙의 기준
- [Claude 인수인계서](docs/CLAUDE_HANDOFF_2026-09-23.md) (0절: 2026-09-23 최신 결과) · [Claude 시작 프롬프트](docs/CLAUDE_START_PROMPT_2026-09-23.md) · [팀원 PC 재현](docs/TEAM_SETUP.md)
- [운영 준비 및 최종 Goal 로드맵](docs/FINAL_GOAL_ROADMAP_2026-09-18.md)
- [수집 실패 원인 조사 및 조치](docs/COLLECTION_FAILURE_AUDIT_2026-09-18.md)
- [현재 구현·미구현·API 키 연동 현황](docs/PROJECT_IMPLEMENTATION_STATUS.md)
- [요구사항](docs/SRS.md), [구조](docs/ARCHITECTURE.md), [데이터 사전](docs/DATA_DICTIONARY.md)
- [수집 및 수동 업로드](docs/DATA_COLLECTION.md), [후보 선정](docs/TESTBED_SELECTION.md)
- [탄소 계산](docs/CARBON_METHOD.md), [모델 검증](docs/MODEL_VALIDATION.md), [시뮬레이션](docs/SIMULATION_METHOD.md)
- [지역 개발 시뮬레이션·과거 수집·감축 노력·보고서 (/area)](docs/AREA_SIMULATION.md), [로컬 보고서 모델 학습](scripts/llm/README.md)
- [SGIS 격자 통계 1km (2024) 적용: 인구·가구·주택·사업체 격자 지표](docs/SGIS_GRID.md)
- [사용 안내](docs/USAGE.md) · [사용 안내 발표 자료 (.pptx)](docs/usage/Carbon-Urban-DSS-guide.pptx) — 화면 사진으로 본 기능과 사용 순서
- 웹 메뉴 **사용 방법**(/guide): 처음 시작, 화면별 사용법, **지도 정보와 활용**, 값 읽는 법, 빠진 자료 전부 수집, 인증키 설정, 로컬 AI, 문제 해결
- [정확도·신뢰도 평가](docs/ACCURACY.md), [알려진 한계](docs/LIMITATIONS.md), [5분 시연](docs/DEMO_SCRIPT.md)

## 계획서 기반 최신 보완

지도 배경 타일의 출처 헤더 차단을 수정하고 타일 장애 시 분석 도형을 유지하도록 보완했습니다. K-apt 상세정보 364개 단지를 확보했으며, 추가 자료의 신청·설정 절차는 [데이터 재설정·수집 안내](docs/DATA_SETUP_GUIDE.md)를 확인하세요.

무료 HTTPS 시연 배포를 추가했습니다. Docker Desktop 실행 후 `powershell -ExecutionPolicy Bypass -File scripts/prototype.ps1 Start`로 시작합니다. 현재 주소·비밀번호는 로컬 `.secrets/prototype-access.md`에 저장됩니다. PC가 켜진 동안 DB·수집 작업·로컬 AI까지 연결되며 접속에는 비밀번호가 필요합니다. [배포와 중지 방법](docs/DEPLOYMENT.md)을 확인하세요.

2026-09-14 보완: 분석 범위 공유, 지도·모바일 UI, 동일 범위 계획안 비교, 한국어 보고서 저장·출력, 선택형 로컬 AI를 추가했습니다. [구현 결과와 남은 작업](docs/IMPLEMENTATION_UPDATE.md)에서 최신 검증과 실행법을 확인하세요. 웹 메뉴의 **검토 보고서**에서 사용할 수 있습니다.
