# 수집과 업로드

## 자동 수집

수집 데이터 화면에서 에너지/기상과 시작·종료월을 선택한다. 기본은2025년, 작업당 최대12개월이다. 장기간은 연도별로 나누어 요청한다. 현재 지원 지역은 전주시이며 전국 수집은 실행하지 않는다.

`POST /api/v1/collection-jobs`는 `source`, `start_month`, `end_month`, `region`을 받는다. `GET /api/v1/collection-jobs`와 `/{id}`는 DB 작업상태를 제공한다. 기존 `/api/collections`도 제공한다.

원본 응답은 파일 캐시에 보존한다. 성공한 과거 동일 요청은 재호출하지 않는다. 인증 실패는 짧은 오류 캐시에 보존하며, 키를 변경하면 새로운 인증으로 검사를 시도할 수 있다. 외부 오류 응답을 빈 성공으로 정규화하지 않는다.

건축물대장과 KMA 관측은 같은 포털키를 사용하더라도 **별도 서비스 활용 승인**이 필요하다. 추가 어댑터 실행:

```powershell
docker compose exec api python -m app.cli enrich
```

## 수동 파일

수집 데이터의 파일 업로드에서 CSV, XLSX, GeoJSON, SHP 구성파일 ZIP을 선택한다. 원본 CRS가 감지되지 않으면 직접 지정한다. 파일 유형·열·미리보기·경고를 확인한 뒤 대상 필드와 매핑한다. 제공기관, 공식 원문 URL, 기준기간도 입력한다.

25MB 업로드·100MB 압축 해제 상한을 적용한다. 경로 탈출 ZIP과 잘못된 도형을 거부한다. 전체 행 검증 후 하나의 DB 트랜잭션으로 가져온다. 입력 파일은 `data/uploads/`에 보존하며 `UNVERIFIED`로 구분한다. URL을 적었다는 이유만으로 공식 인증 배지를 부여하지 않는다.

## 아직 추가 자료가 필요한 출처

|자료|공식 진입점|형식/의존성|업로드 위치|
|---|---|---|---|
|GIS 건물통합정보|https://www.vworld.kr/|VWorld key 또는 GeoJSON/SHP ZIP|수집 데이터 → 건축물 정보|
|용도지역지구도|https://www.vworld.kr/|WFS key 또는 SHP ZIP|수집 데이터 → 용도지역|
|NGII 통계지도 인구100m/500m|https://map.ngii.go.kr/|포털 다운로드 SHP/GeoJSON/CSV|수집 데이터 → 인구|
|NGII 통계500m격자|https://map.ngii.go.kr/|공식 ID 포함 SHP/GeoJSON|수집 데이터 → 격자|
|건축물대장|https://www.data.go.kr/data/15134735/openapi.do|개별 API 승인|자동 어댑터|
|ASOS 일자료|https://www.data.go.kr/data/15059093/openapi.do|개별 API 승인|자동 어댑터|

포털에서 로그인·신청이 요구되는 다운로드는 자동 성공으로 표시하지 않는다.

## 재설정 상세 안내

인증키 신청, 원본 다운로드, 필수 필드와 현재 직접 수집 결과는 [DATA_SETUP_GUIDE.md](DATA_SETUP_GUIDE.md)를 확인하세요. K-apt 상세정보는 364개 단지로 확장했으며 부분 재수집 시 기존 상세자료를 보존합니다.
