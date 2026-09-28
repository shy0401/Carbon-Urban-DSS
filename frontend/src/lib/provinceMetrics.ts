import type { RampName } from '../theme/palette';

/** Indicators the province (시·도) map can show for every SGIS 500m cell of Korea. */
export interface ProvinceMetric {
  key: string;
  label: string;
  unit: string;
  /** '500m': counted inside the cell. '1km': the value of the SGIS 1km cell that contains it (same for its 4 cells). */
  resolution: '500m' | '1km';
  digits: number;
  ramp: RampName;
  breaks?: number[];
  definition: string;
  source: string;
  use: string;
}

const SGIS = 'SGIS 격자 통계 1km (공공데이터포털 15141768)';
const KAPT = 'K-apt 공동주택 단지 목록 (국토교통부·한국부동산원)';

export const PROVINCE_METRICS: ProvinceMetric[] = [
  { key: 'pop', label: '인구 밀도', unit: '명/km²', resolution: '1km', digits: 0, ramp: 'seq', source: SGIS,
    definition: '이 500m 격자를 품은 SGIS 1km 격자의 총인구입니다. 1km 격자는 1km²라서 값이 곧 km²당 인구입니다. 비밀보호 잡음(±7)이 있습니다.',
    use: '사람이 사는 곳과 비어 있는 곳을 가르고, 분석할 시·군·구를 고르는 출발점으로 씁니다.' },
  { key: 'hh', label: '가구 밀도', unit: '가구/km²', resolution: '1km', digits: 0, ramp: 'seq', source: SGIS,
    definition: '소속 1km 격자의 총가구입니다(1km²당).', use: '주거 에너지 수요가 몰린 곳을 찾습니다.' },
  { key: 'housing', label: '주택 밀도', unit: '호/km²', resolution: '1km', digits: 0, ramp: 'seq', source: SGIS,
    definition: '소속 1km 격자의 총주택 수입니다(1km²당).', use: '주택 재고가 많은 곳, 개보수 대상이 모인 곳을 찾습니다.' },
  { key: 'workers', label: '종사자 밀도', unit: '명/km²', resolution: '1km', digits: 0, ramp: 'seq', source: SGIS,
    definition: '소속 1km 격자의 사업체 종사자 수입니다(1km²당).', use: '상업·업무·산업 활동이 몰린 곳(비주거 에너지 수요)을 찾습니다.' },
  { key: 'elderly_pct', label: '65세 이상 비율', unit: '%', resolution: '1km', digits: 1, ramp: 'seq', breaks: [10, 20, 30, 40], source: SGIS,
    definition: '소속 1km 격자의 연령별 인구 중 65세 이상 비율입니다. 연령 인구 합이 20명 미만이면 비웁니다.', use: '고령층이 많은 곳의 난방·냉방 취약성을 함께 봅니다.' },
  { key: 'old_housing_pct', label: '2000년 이전 주택 비율', unit: '%', resolution: '1km', digits: 1, ramp: 'load', breaks: [20, 40, 60, 80], source: SGIS,
    definition: '소속 1km 격자의 건축연도별 주택 중 2000년 이전(1979년 이전·1980년대·1990년대)에 지은 비율입니다. 주택 수 20호 미만이면 비웁니다.',
    use: '노후 주택이 많아 단열 개보수 효과가 클 곳을 찾습니다.' },
  { key: 'apartment_pct', label: '아파트 비율', unit: '%', resolution: '1km', digits: 1, ramp: 'seq', breaks: [20, 40, 60, 80], source: SGIS,
    definition: '소속 1km 격자의 주택 유형 중 아파트 비율입니다. 20호 미만이면 비웁니다.', use: '공동주택 관측(K-apt)으로 설명되는 곳과 단독주택 위주인 곳을 가릅니다.' },
  { key: 'complexes', label: '공동주택 단지 수', unit: '단지', resolution: '500m', digits: 0, ramp: 'seq', breaks: [1, 2, 4, 8], source: KAPT,
    definition: 'K-apt 단지 목록의 좌표가 이 500m 격자 안에 있는 공동주택 단지 수입니다. 0은 목록에 오른 단지가 없다는 뜻입니다(소규모 공동주택은 목록에 없을 수 있음).',
    use: '공동주택 에너지 관측(K-apt)을 받을 수 있는 곳을 찾습니다.' },
  { key: 'complex_year', label: '단지 평균 사용승인연도', unit: '년', resolution: '500m', digits: 0, ramp: 'gain', breaks: [1995, 2005, 2015], source: KAPT,
    definition: '격자 안 공동주택 단지의 사용승인연도 평균입니다. 단지가 없으면 비웁니다.', use: '오래된 단지가 모인 곳(재건축·리모델링 후보)을 찾습니다.' },
];

export const DEFAULT_PROVINCE_METRIC = 'pop';

/** GeoJSON features (one square per cell) from the compact rows, keyed by field name. */
export function rowValue(fields: string[], row: Array<number | null>, key: string): number | null {
  const index = fields.indexOf(key);
  const value = index >= 0 ? row[index] : null;
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}
