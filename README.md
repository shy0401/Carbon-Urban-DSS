# Carbon Urban DSS

전주시 500m 주거 섹터를 위한 공공데이터 기반 에너지·운영탄소 의사결정 프로토타입입니다. **실측, 공공데이터 계산, 추정, 시나리오를 분리**하며, 결측값을 0으로 만들지 않습니다.

## 실행

Docker Desktop Linux 엔진을 켜고 이 폴더에서 실행합니다. 기존 `.env`는 보존하세요.

```powershell
docker compose up --build -d
```

- 웹: [http://localhost:5173](http://localhost:5173)
- API 문서: [http://localhost:8000/docs](http://localhost:8000/docs)
- 상태: [http://localhost:8000/api/health](http://localhost:8000/api/health)

첫 실행은 로컬 `data/raw`를 정규화합니다. 파일이 없으면 사용 가능한 공개 소스를 수집하며, 필요한 인증이 없으면 해당 소스의 실패만 기록합니다. 공공데이터 서비스키는 **백엔드 환경변수 `DATA_GO_KR_SERVICE_KEY`**에만 둡니다. `.env`를 Git이나 채팅에 공유하지 마세요.

키를 변경했다면 다음 명령으로 API·worker의 환경을 갱신한 뒤 수집 데이터 화면에서 다시 수집합니다.

```powershell
docker compose up -d --force-recreate api worker
```

## 데이터와 한계

현재 확보한 실데이터, 정확한 개수, 실패한 API는 [DATA_SOURCE_DISCOVERY](docs/DATA_SOURCE_DISCOVERY.md)와 [검증 보고서](docs/FINAL_REPORT.md)에 기록합니다. API 화면은 문서의 숫자를 복제하지 않고 **현재 DB**를 조회합니다.

초기 제공된 서비스키로 건물에너지 API가 등록되지 않은 키 오류(30)를 반환했습니다. 이 상태에서는 월별 에너지, 전체 운영탄소, 에너지 최적안을 계산 완료했다고 표시하지 않습니다. 원단위 추정과 최적화 코드는 매칭된 관측 데이터가 확보되면 사용 가능합니다.

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

- [현재 구현·미구현·API 키 연동 현황](docs/PROJECT_IMPLEMENTATION_STATUS.md)
- [요구사항](docs/SRS.md), [구조](docs/ARCHITECTURE.md), [데이터 사전](docs/DATA_DICTIONARY.md)
- [수집 및 수동 업로드](docs/DATA_COLLECTION.md), [후보 선정](docs/TESTBED_SELECTION.md)
- [탄소 계산](docs/CARBON_METHOD.md), [모델 검증](docs/MODEL_VALIDATION.md), [시뮬레이션](docs/SIMULATION_METHOD.md)
- [알려진 한계](docs/LIMITATIONS.md), [5분 시연](docs/DEMO_SCRIPT.md)

## 계획서 기반 최신 보완

지도 배경 타일의 출처 헤더 차단을 수정하고 타일 장애 시 분석 도형을 유지하도록 보완했습니다. K-apt 상세정보 364개 단지를 확보했으며, 추가 자료의 신청·설정 절차는 [데이터 재설정·수집 안내](docs/DATA_SETUP_GUIDE.md)를 확인하세요.

무료 HTTPS 시연 배포를 추가했습니다. Docker Desktop 실행 후 `powershell -ExecutionPolicy Bypass -File scripts/prototype.ps1 Start`로 시작합니다. 현재 주소·비밀번호는 로컬 `.secrets/prototype-access.md`에 저장됩니다. PC가 켜진 동안 DB·수집 작업·로컬 AI까지 연결되며 접속에는 비밀번호가 필요합니다. [배포와 중지 방법](docs/DEPLOYMENT.md)을 확인하세요.

2026-09-14 보완: 분석 범위 공유, 지도·모바일 UI, 동일 범위 계획안 비교, 한국어 보고서 저장·출력, 선택형 로컬 AI를 추가했습니다. [구현 결과와 남은 작업](docs/IMPLEMENTATION_UPDATE.md)에서 최신 검증과 실행법을 확인하세요. 웹 메뉴의 **검토 보고서**에서 사용할 수 있습니다.
