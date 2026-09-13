# 실제 데이터 출처

2026-09-13 별도 빈 PostGIS DB에 보존 원본을 재적재한 결과다. 서로 다른 자료의 행을 합쳐 건물 수로 해석하지 않는다.

| 자료 | 적재량 | 기간·성격 |
|---|---:|---|
| [행정안전부 법정동 코드](https://www.code.go.kr/stdcode/regCodeL.do) | 86행 | 수집 시점 전주시 현행 코드, 행정 계층 포함 |
| [OSM](https://www.openstreetmap.org/copyright) 건물 | 2,171개 | 수집 시점 아파트 중심 FALLBACK |
| OSM 전주시 경계 | 1개 | relation 7619919, 비공식 경계 |
| 파생 500m 격자 | 916개 | EPSG:5179, 각 250,000m², NGII 격자 아님 |
| [ERA5-Land/Open-Meteo](https://open-meteo.com/en/docs/historical-weather-api) | 12개월 | 2025년 일별 365일 집계, 재분석 FALLBACK |
| [K-apt](https://www.k-apt.go.kr/) | 364단지 | 목록 검색 202512, 상세 8개 확보/356개 결측 |
| [전주시](https://www.jeonju.go.kr/) 공동주택 현황 | 595+14개 | 2025-12-31, 준공/공사 중 별도 저장 |
| [GIR 승인 전력계수](https://www.gir.go.kr/home/board/read.do?boardId=82&boardMasterId=2&menuId=36) | 1개 | 2024 승인, 2025-03-31 게시 |
| [건축HUB 에너지](https://www.data.go.kr/data/15135963/openapi.do) | 0행 | 2025 요청, 제공 키 오류 30 |
| [건축물대장](https://www.data.go.kr/data/15134735/openapi.do) | 0행 | 유효 키·별도 활용 승인 필요 |
| [VWorld 용도지역](https://www.vworld.kr/dev/v4dv_2ddataguide2_s002.do) | 0행 | 키 또는 공식 원본 필요 |
| [SGIS 인구](https://sgis.kostat.go.kr/developer/html/newOpenApi/api/dataApi/census.html) | 0행 | 승인 자격 또는 공식 원본 필요 |

정확한 다운로드 경로·해시·계수 구성요소는 [SOURCE_RESEARCH](SOURCE_RESEARCH.md)에 있다. 원본 `data/raw/`, 요청 캐시 `data/cache/`, 원본 해시 목록 `data/snapshots/raw-manifest.json`을 보존한다. 웹 상세는 DB의 수집일·기간·미리보기·오류를 제공한다. 가스의 kWh 입력 열량/GWP 기준은 미확정이므로 전체 탄소 계산에 적용하지 않았다.
