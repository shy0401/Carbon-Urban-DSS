# 이 저장소에서 일하는 사람·AI 도구 공통 규칙

**자료를 모으거나, 계산하거나, 보고서를 쓰기 전에 [docs/DATA_STANDARD.md](docs/DATA_STANDARD.md)를 읽는다.** 그 문서가 수집·계산·보고서 기준의 유일한 원본이다. 0절(작업 전 확인)은 매번 따른다.

## 꼭 지킬 것
- 없는 값은 NULL. 0으로 채우지 않는다. 제공기관이 준 0만 0이다.
- `data/raw`의 원본은 고치지 않는다. 이상한 값은 상태로 표시만 한다.
- 관측 · 계산 · 추정 · 대체 · 시나리오를 섞지 않고, 단위를 열 이름에 붙인다(`_kwh`, `_m2`, `_kgco2eq`, `_tco2e`).
- 계수·기준온도·임계값은 기준 문서 5절과 코드 상수(`backend/app/emissions.py`, `degree_days.py`, `kapt_energy.py`)가 같아야 한다. 바꿀 때는 문서와 코드를 같은 커밋에서 바꾼다.
- 보고서의 숫자는 계산 엔진 근거 문장에서만 가져온다. 감축량을 쓸 때는 기준(공동주택/건물 전체/추정)과 기준 연도를 함께 쓴다.
- 확인하지 못한 API 필드·주소·단위는 "확인 필요"로 적는다. 짐작으로 채우지 않는다.

## 올리지 않는 것
- `.env`·키·토큰, `.secrets/`, `data/`(원본·DB 덤프·백업·캐시), 개인 설정(`.idea/` 등).
- 국토통계지도(국토지리정보원) 자료: 국외 반출 금지. Git·클라우드·공개 주소에 올리지 않는다.
- 강제 푸시·기록 다시 쓰기를 하지 않는다.

## 점검과 공유
```powershell
docker compose -p carbon-urban-dss -f compose.yaml -f compose.demo.yaml exec -T api python -m app.cli check-standard
docker compose -p carbon-urban-dss -f compose.yaml -f compose.demo.yaml exec -T api python -m app.cli check-standard --csv /data/raw/<폴더>/<파일>.csv
scripts\dss.cmd ExportBundle      # 팀원에게 줄 때
scripts\dss.cmd MergeBundle -BundlePath <묶음.zip> -DryRun   # 받을 때 (먼저 세기만)
```
자세한 절차: [팀원 PC 재현](docs/TEAM_SETUP.md), 팀 자료 차이: [팀 데이터 비교](docs/TEAM_DATA_COMPARISON.md).
