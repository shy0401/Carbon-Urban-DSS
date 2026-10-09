# 업체·지자체·정부의 활용 방식과 이 도구의 대응 (2026-10-10 조사)

건축·도시 탄소 도구를 실제로 쓰는 곳이 **어떤 결정에, 어떤 숫자를, 어떤 형식으로** 쓰는지 공개 자료로 확인하고, 지역 시뮬레이션(`/area`)을 그 방식에 맞게 고쳤습니다. 제도 설명은 공개 자료 요약이며 법적 해석이 아닙니다. 발표자료: `docs/presentation/Carbon-Urban-DSS-업계활용-사용성개선.pptx`(PDF 같은 이름).

## 1. 누가 어떤 결정에 쓰나

| 사용자 | 결정 | 필요한 숫자 | 근거 제도·도구 |
|---|---|---|---|
| 지자체 도시계획 | 도시·군기본계획 5년 단위 감축목표, 탄소중립 도시계획 요소 | 구역 배출 현황, 수단별 예상 감축량 합계, 목표 달성 여부 | 도시·군기본계획수립지침, 탄소공간지도 |
| 개발사업자·평가 대행사 | 기후변화영향평가(온실가스) 협의 | 배출원·배출량 산정, 감축목표, 감축방안 | 탄소중립기본법(환경영향평가 병합) |
| 건물주·관리자 | 에너지 신고·등급, 그린리모델링, ZEB 인증 | 단위면적당 사용량, 동종 비교, 개선 전후 절감량 | 서울 건물에너지 신고·등급제, ENERGY STAR, 그린리모델링 |
| 설계사·엔지니어링 | 초기 설계 대안 선택 | 대안별 운영탄소, 비교표·공유 | Autodesk Forma, One Click LCA, ArcGIS Urban |
| 데이터·컨설팅 | 기준 인벤토리, 품질 관리 | 출처·가공 규칙, 이상치, 재현 | 건물에너지 데이터 통합관리(딥뷰·I-BED), Google EIE |

## 2. 국내 제도·사업

- **기후변화영향평가**(탄소중립기본법): 일정 개발사업과 전략환경영향평가 대상 계획. 온실가스 항목은 배출원·흡수원, 배출량 산정방안, 감축목표·감축방안. 평가준비서 → 초안 → 의견수렴 → 평가서(환경영향평가서와 별책).
- **도시·군기본계획수립지침**(국토부): 기초조사에 온실가스 배출·흡수 현황, 5년 단위 감축목표, 온실가스 현황지도·건물 에너지 수요 지도, 감축수단별 예상 감축량을 합산해 목표 달성 여부 확인.
- **탄소공간지도**(국토부, 2023-06-30 운영): 건물·수송·토지이용 배출과 흡수원, 격자·행정구역(읍면동)·용도지역 단위 조회·비교. 지자체 탄소중립 도시계획 기초조사와 감축목표 설정.
- **서울 건물에너지 신고·등급제**: 민간 3천㎡·공공 1천㎡ 이상 비주거, 전기·가스·지역난방 신고, 용도·규모별 단위면적당 사용량 A~E. 2024년 4,281곳(A 4.4%, B 46.9%, C 38.5%, D 7.7%, E 2.5%), D~E 382곳 컨설팅. 에너지다소비건물(2천TOE 이상) 2025년 506곳은 건물 수의 0.1%로 건물 배출의 약 15%.
- **건물에너지 데이터 통합관리**(2025-10-30 설명회): 서울 총량제 시범(유형별 표준배출량, 5년 단위), 지도+대시보드(딥뷰: 출처·가공 규칙·품질 오류 신고), 업로드·유효성 검증·이상치 모듈(I-BED). 2030 NDC 건물 부문 32.8%.
- **그린리모델링·ZEB**: 민간 컨설팅(2026-06-30 모집)의 결과물은 개선 전후 절감량·비용 절감·회수기간. 공공 2025년 261동 지원(신청 796). ZEB 민간 의무(2025-06, 30세대 이상 공동주택·1천㎡ 이상, 5등급).

## 3. 해외 도구

| 도구 | 누가 | 어떻게 쓰나 |
|---|---|---|
| ArcGIS Urban (Esri) | 도시계획가 | 용적률·높이로 3D 시나리오, 시나리오 비교 보고서(Excel: 지표·용도면적) |
| One Click LCA Carbon Designer 3D | 설계사·컨설턴트 | 건물 유형·연면적으로 기준안, 설계 대안 최대 4개 비교 |
| Autodesk Forma (Carbon Insights) | 건축가·MEP | 초기 설계 운영·내재 탄소, 공유 대시보드 |
| CityBES (LBNL), umi (MIT), City Energy Analyst (ETH) | 도시·전력회사·컨설턴트 | 도시 건물 재고 개조·태양광 시나리오, 벤치마킹 |
| ENERGY STAR Portfolio Manager | 건물주·도시 | 1~100 동종 백분위(50 중앙, 75 이상 인증), 12개월 연속 전 연료 자료 |
| Google EIE, NYC LL97 계산기 | 도시·건물 이사회 | 도시 기준 인벤토리·계수 조정, 2030 배출·벌금 예측 |

## 4. 공통 패턴 → 이 도구에서 바꾼 것

| 쓰는 방식 | 바꾼 것 (커밋 2026-10-10) | 화면 위치 |
|---|---|---|
| 결과를 한눈에 보며 단계 이동 (Forma) | 결과 요약 막대: 기준 배출·계획 반영·필요 감축량·수단 조합·행정동 순위 + 5단계 이동 | 구역 띠 아래(고정) |
| 근거 없는 칸을 비워 두지 않음 (평가서) | 기준 자동 전환(공동주택↔건물 전체) + 실제 수집 연도 표시 | 감축 노력, 구역 띠 |
| 수단별 감축량 합산 → 목표 확인 (도시기본계획) | 감축 수단 조합: 신축·기존 절감률 + 태양광 kW → 합계·남는 양, 링크 `mx=` | ③ 감축 수단 |
| 동종 비교 (서울 등급, ENERGY STAR) | 같은 시·군·구 행정동 원단위 분포 속 위치(순위·5분위), 등급 아님 | 감축 노력 아래, 보고서 |
| 대안 비교표·내보내기 (ArcGIS Urban, One Click LCA) | 시나리오 저장 최대 4개 + CSV(엑셀) | ④ 시나리오 비교 |
| 평가서 항목 순서 (기후변화영향평가) | 인쇄·PDF 보고서: 핵심 결과 표 + 현황→영향→목표→방안→한계 | ⑤ 보고서 |
| 출처·품질 확인 (딥뷰·I-BED) | 개발 전후 문장에 관측 연도, 관측 범위 주의, 같은 단지 변화 | 개발 전후, 보고서 |

하지 않은 것: 비용·회수기간(단가 근거 없음), 가스 탄소의 감축 계산(가스 kWh 환산 기준 확인 전), 용도 보정 등급, 팀 공유 시나리오 저장. 자세한 한계는 [LIMITATIONS.md](LIMITATIONS.md) 2026-10-10.

## 출처 (조회 2026-10-10)

- 기후변화영향평가 고시안: https://www.shinkim.com/kor/media/newsletter/1871
- 도시·군기본계획수립지침 개정: https://www.smarttoday.co.kr/ko-kr/articles/22182
- 탄소공간지도: https://www.newsis.com/view/NISX20230628_0002356224 , https://www.discoverynews.kr/news/articleView.html?idxno=1028725 , https://www.dailian.co.kr/news/view/1154189/
- 서울 건물에너지 신고·등급제: https://news.seoul.go.kr/env/archives/563115 · 에너지다소비건물: https://news.seoul.go.kr/env/eco/eco-building/energy-building
- 건물에너지 데이터 통합관리 설명회: https://www.kharn.kr/mobile/article.html?no=29132 · 정보체계 민간 개방: https://www.smarttoday.co.kr/ko-kr/articles/23488
- ZEB 민간 의무화: https://www.sankun.com/blog/detail/837_ · 그린리모델링 컨설팅: https://www.kharn.kr/mobile/article.html?no=30978 · 공공 261동: https://newsseoul.co.kr/news/view/1065568824606918
- ArcGIS Urban: https://www.esri.com/arcgis-blog/products/urban/design-planning/compare-arcgis-urban-planning-scenarios-in-excel , https://www.esri.com/en-us/arcgis/products/arcgis-urban/features/3d-scenario-modeling
- Autodesk Forma: https://www.autodesk.com/products/insight/overview · One Click LCA: https://oneclicklca.com/en/resources/articles/carbon-designer-3d-guide
- ENERGY STAR: https://www.energystar.gov/ENERGYSTARscore , https://www.energystar.gov/buildings/benchmark/understand-metrics/score-criteria
- CityBES: https://bies.lbl.gov/urban-science/tools · umi: https://web.mit.edu/SustainableDesignLab/projects/umi/index.html · City Energy Analyst: https://pypi.org/project/cityenergyanalyst
- Google EIE: https://sustainability.google/stories/environmental-insights-explorer/ · LL97 계산기: https://www.bdcnetwork.com/sustainability/news/55297088/emissions-calculator-to-understand-new-york-citys-local-law-97-launched
