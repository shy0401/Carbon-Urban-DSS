# 팀원 PC 재현·백업·복원 안내

Git 저장소에는 **코드와 문서만** 있다. PostgreSQL/PostGIS DB, 원본 `data/raw`, API 키(`.env`), 로컬 AI 모델은 Git clone으로 전달되지 않는다. 이 문서는 새 PC에서 같은 화면·데이터를 재현하는 절차와, 그 과정을 자동으로 검사하는 `scripts/dss.ps1`(`scripts\dss.cmd`) 사용법이다.

## 1. 새 PC 준비

| 항목 | 요구 | 확인 방법 |
|---|---|---|
| Windows 10/11 | WSL2 사용 가능 | `wsl --status` |
| Docker Desktop | Linux 엔진(WSL2). 디스크 여유 25GB 이상 권장 | 트레이 고래 아이콘이 Running |
| Git for Windows | 기본 설정(`core.autocrlf=true`) | `git --version` |
| 디스크 | Docker 디스크 이미지를 C가 아닌 드라이브에 둘 수 있음(설정 → Resources → Advanced → Disk image location) | `scripts\dss.cmd Doctor`의 `docker_disk_dir` |

Node.js와 Playwright는 **필수가 아니다.** 프런트엔드 테스트와 브라우저 E2E는 실행기가 Docker 컨테이너 안에서 수행한다.

```powershell
git clone https://github.com/shy0401/Carbon-Urban-DSS.git
cd Carbon-Urban-DSS
if (-not (Test-Path .env)) { Copy-Item .env.example .env }   # 기존 .env는 덮어쓰지 않는다
scripts\dss.cmd Doctor
```

`Doctor`는 Docker 엔진, Compose, 드라이브 여유 공간, Docker 디스크 위치, 포트(5173/8000/5180/8010/5190), `.env` 변수의 **설정 여부와 형식만**(값은 출력하지 않음), Git 브랜치, `data/raw` 파일 수, 기존 볼륨을 `data/ops/<시각>-doctor/summary.json`에 기록한다.

### `.env` 키

| 변수 | 용도 | 발급처 |
|---|---|---|
| `DATA_GO_KR_SERVICE_KEY` | K-apt 월별 에너지(15012964), KMA ASOS(15059093), 건축HUB 에너지(15135963)·건축물대장(15134735) | 공공데이터포털. **서비스마다 활용신청 승인 필요**, 일반 인증키 Decoding 값 |
| `SGIS_CONSUMER_KEY`, `SGIS_CONSUMER_SECRET` | 행정동 인구·가구, 공식 행정동 경계 | SGIS 개발지원센터(서비스 ID·보안 key) |
| `VWORLD_API_KEY`, `VWORLD_DOMAIN` | 용도지역(LT_C_UQ111), 연속지적(LP_PA_CBND_BUBUN) | VWorld 인증키 관리. 도메인은 발급 시 등록한 서비스 URL(개발키는 기본 `http://localhost`) |
| `SGIS_BASE_YEAR` (선택) | 요청 기준연도. 없으면 2024부터 공표 연도를 자동 확인 | — |

키 값은 Git, 문서, 채팅, 화면 캡처에 남기지 않는다. 값이 한글·공백·예시 문구이면 수집 전에 `환경변수 형식 오류`로 차단되고 외부 요청을 보내지 않는다. 키를 바꾸면 `docker compose up -d --force-recreate api worker`로 컨테이너 환경을 갱신한다.

## 2. 데이터 가져오기

### 2.1 승인된 묶음(bundle)으로 복원 — 권장

데이터를 가진 PC에서:

```powershell
scripts\dss.cmd ExportBundle            # data\backups\bundles\carbon-dss-bundle-<시각>.zip (+ .sha256)
scripts\dss.cmd ExportBundle -IncludeUploads   # 업로드 원본까지 공유가 승인된 경우만
```

묶음 구성: `db.dump`(pg_dump custom, `public` 스키마), `table-counts.tsv`(전 테이블 행 수), `raw.zip`(`data/raw`), `raw-manifest.csv`(파일별 SHA-256), `manifest.json`, `SHA256SUMS.txt`, `README-IMPORT.txt`.
**포함하지 않는 것:** `.env`·API 키, `.secrets`, `data/cache`, `data/deployment`(임시 공개 URL), Ollama 모델. 묶음은 팀 내부의 안전한 경로로만 전달하고 각 제공기관 이용조건을 따른다.

새 PC에서(Docker Desktop 실행 후, 아직 서비스를 띄우기 **전에**):

```powershell
scripts\dss.cmd ImportBundle -BundlePath D:\share\carbon-dss-bundle-20260923-120000.zip
```

실행기는 SHA-256을 검증하고, 대상 DB에 테이블이 이미 있으면 **덮어쓰지 않고 중단**한다. `data/raw`는 없는 파일만 복사하며 내용이 다른 같은 이름 파일은 로컬 것을 유지하고 목록으로 보고한다. 복원 후 전 테이블 행 수를 묶음 기록과 비교하고 api/worker/frontend를 올려 `/api/health`를 확인한다.

### 2.2 묶음 없이 처음부터

```powershell
docker compose up -d --build
scripts\dss.cmd Collect
```

첫 기동 시 저장소에 포함된 공개 원본이 없으면 현재 키 없이 수집 가능한 공개 소스(ERA5-Land, OSM, 법정동 코드, K-apt 단지 공개 목록)를 다시 받는다. 키가 필요한 소스는 `Collect`가 SMOKE→LIMITED→FULL 순으로 진행하고 첫 실패에서 멈춘다.

## 3. 실행기 동작 요약 (`scripts\dss.cmd <Action>`)

| Action | 내용 | 산출물 |
|---|---|---|
| `Doctor` | 사전 점검 | `summary.json` |
| `Status` | DB 전 테이블 행 수, `data/raw` 수·SHA-256 집계, readiness, 키 설정 여부 | `status.json` |
| `Backup` | `pg_dump -Fc -n public` + 행 수 + raw 매니페스트 + SHA-256 | `data\backups\<시각>-manual\` |
| `Rebuild` | api/worker/frontend 재빌드·재기동(볼륨 유지) | — |
| `Probe` | SGIS·VWorld 최소 실제 요청의 구조 요약(값 비노출) | `probe-sgis.json`, `probe-vworld.json` |
| `Collect` | SGIS·VWorld 용도지역 FULL, 연속지적 LIMITED, 공공데이터포털 소스는 사전 검사 결과 | `collect-<dataset>.json` |
| `VerifyRestore` | 최신 백업을 **별도 프로젝트 `carbon-urban-dss-restoretest`**(포트 8010/5190, 오프라인)에 복원 → 행 수 전수 비교 → 웹·API·지도·오버레이 점검 → pytest → 브라우저 E2E → 이 프로젝트만 정리 | `summary.json`, `pytest-restore.log`, `e2e.log`, `data\validation\*.png` |
| `FrontendTest` | `docker build --target test frontend` (Vitest + `tsc -b` + Vite 운영 빌드) | `frontend-test.log` |
| `All` | 위 전 과정 | `data\ops\<시각>-all\` |

안전 규칙: 메인 프로젝트 볼륨은 삭제하지 않는다(`down -v` 미사용). 테스트는 복원 사본에서 실행해 실데이터 DB에 테스트 행을 남기지 않는다. E2E가 바꾸는 오프라인 플래그(`data/offline.flag`)는 실행 전 상태로 되돌린다.

## 4. 문제 해결

| 증상 | 원인·조치 |
|---|---|
| Docker 엔진이 계속 `starting`, 로그에 `ERROR_SHARING_VIOLATION` | `docker_data.vhdx`를 다른 프로세스가 열고 있음(Windows에 가상 디스크로 연결됨, 백업·백신 검사 등). Docker Desktop 종료 → `wsl --shutdown` → 그래도 같으면 재부팅. vhdx 파일을 탐색기에서 직접 옮기거나 열지 말고 Docker Desktop의 Disk image location 설정을 사용한다 |
| 수집 화면에 `환경변수 형식 오류` | `.env` 값이 발급 키가 아니라 예시 문구·한글·따옴표 포함 값. 실제 키로 교체 후 api/worker 재생성 |
| 공공데이터포털 `SERVICE_KEY_IS_NOT_REGISTERED`(30) | 해당 서비스 활용신청 미승인 또는 키 반영 전. 승인 후 1시간 캐시가 지나거나 키가 바뀌면 재시도 |
| VWorld `INCORRECT_KEY`/도메인 오류 | `VWORLD_DOMAIN`을 키 발급 시 등록한 서비스 URL과 똑같이 설정 |
| `ImportBundle`이 "already has N tables"로 중단 | 대상 DB가 비어 있지 않음. 기존 DB를 `Backup`으로 보존한 뒤 새 PC/새 볼륨에서 가져오기 |
