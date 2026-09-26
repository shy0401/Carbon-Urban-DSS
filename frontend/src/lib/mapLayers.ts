/** 지도 레이어 설명 (사용 방법 화면의 "지도 정보와 활용" 표와 함께 쓴다). */
export interface LayerInfo {
  key: string;
  label: string;
  what: string;
  use: string;
  source: string;
}

export const MAP_LAYERS: LayerInfo[] = [
  {
    key: 'grids', label: '분석 격자 (500m)',
    what: 'EPSG:5179에 맞춘 500×500m 격자 916개입니다. 색은 왼쪽 위에서 고른 지표의 값이고, 빗금은 자료가 없는 격자입니다(0이 아님). SGIS 공식 500m 격자와 모서리가 같아 상세에 공식 격자 코드(예: 다마62a48a)를 함께 표시합니다.',
    use: '모든 지표를 같은 공간 단위로 비교합니다. 격자를 누르면 상세가 열리고, 그 격자가 대시보드·분석·시뮬레이션의 대상이 됩니다. 공식 코드는 SGIS 자료신청·결합에 씁니다.',
    source: '프로젝트 생성 격자 + SGIS OpenAPI 500m 격자 경계(코드)',
  },
  {
    key: 'buildings', label: '건물 (도로명주소 건물)',
    what: '공식 건물 윤곽과 지상층수입니다. 확대 14 이상에서 화면 범위만 불러옵니다. 이 레이어에는 용도코드가 없어 용도는 "미상"으로 칠합니다.',
    use: '실제 건물 배치를 보고, 건폐율·추정 용적률이 어떤 건물에서 나왔는지 확인합니다.',
    source: 'VWorld LT_C_SPBD (행정안전부·국토교통부)',
  },
  {
    key: 'complexes', label: '공동주택 단지 (K-apt)',
    what: '의무관리 공동주택 단지의 공표 위치입니다. 원 크기는 세대수입니다.',
    use: '에너지 관측이 어느 단지에서 왔는지, 새로 준공된 단지가 어디인지 확인합니다.',
    source: 'K-apt 공동주택 기본정보',
  },
  {
    key: 'boundary', label: '전주시 경계',
    what: 'SGIS 2024 행정동 경계 35개를 합친 전주시 경계입니다.',
    use: '분석 범위를 확인합니다.',
    source: 'SGIS 행정구역 경계',
  },
  {
    key: 'zoning', label: '용도지역 (VWorld)',
    what: '법정 용도지역(주거·상업·공업·녹지·관리) 도형의 외곽선입니다.',
    use: '어떤 개발이 허용되는 땅인지 1차로 확인합니다. 법적 허용 상한 판정은 아닙니다.',
    source: 'VWorld LT_C_UQ111',
  },
  {
    key: 'admin', label: '행정동 인구 (SGIS)',
    what: '행정동별 인구밀도 채색입니다. 행정동 전체 통계이며 격자에 나누지 않습니다.',
    use: '동 단위 인구 규모를 비교하고, 보고서에 지역 맥락으로 씁니다.',
    source: 'SGIS 행정구역 통계 (2024)',
  },
  {
    key: 'basemap', label: '배경지도 (OpenStreetMap)',
    what: '위치를 가늠하기 위한 흐린 배경지도입니다. 연결이 안 되거나 오프라인이면 도면지 바탕과 1km 참조 격자로 대신합니다.',
    use: '위치 확인용이며 분석 값에는 쓰이지 않습니다.',
    source: 'OpenStreetMap contributors',
  },
];
