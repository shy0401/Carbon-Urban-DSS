import type { RampName } from '../theme/palette';

/** Indicators the province (시·도) map can show for every SGIS 500m cell of Korea. */
export interface ProvinceMetric {
  key: string;
  label: string;
  unit: string;
  /** '500m': the cell's own value. '1km': the value of the SGIS 1km cell that contains it (same for its 4 cells). */
  resolution: '500m' | '1km';
  /** sgis500: SGIS 500m 격자 통계 (자료제공 신청분) · sgis1k: 소속 1km 격자 통계 · kapt: 단지 좌표로 센 값. */
  group: ProvinceGroup;
  digits: number;
  ramp: RampName;
  breaks?: number[];
  definition: string;
  source: string;
  use: string;
}

export type ProvinceGroup = 'sgis500' | 'sgis1k' | 'kapt';
export const PROVINCE_GROUPS: Array<{ key: ProvinceGroup; label: string; tag: string }> = [
  { key: 'sgis500', label: '인구·주택 (SGIS 500m 격자 자체)', tag: '500m 격자 자체의 SGIS 통계 (비밀보호 잡음 포함)' },
  { key: 'sgis1k', label: '인구·주택 (SGIS, 소속 1km 격자 값)', tag: '1km 격자 값 (같은 1km 안 500m 격자 4개는 같은 값)' },
  { key: 'kapt', label: '공동주택 (K-apt, 500m 격자 안)', tag: '500m 격자 안에서 센 값' },
];

const SGIS500 = 'SGIS 500m 격자 통계 (자료제공 신청분)';
const SGIS500_NOTE = '이 500m 격자 자체의 SGIS 공식 통계입니다. 비밀보호로 인구 부문 5 미만은 0 또는 5, 사업체 부문 3 미만은 0 또는 3으로 대체했고, 그 이상 값에도 최대 ±7(사업체 ±4) 잡음이 있습니다. 통계가 없는 격자는 0이 아니라 결측입니다.';
const SGIS = 'SGIS 격자 통계 1km (공공데이터포털 15141768)';
const KAPT = 'K-apt 공동주택 단지 목록 (국토교통부·한국부동산원)';

export const PROVINCE_METRICS: ProvinceMetric[] = [
  { key: 'pop5', label: '인구', unit: '명', resolution: '500m', group: 'sgis500', digits: 0, ramp: 'seq', breaks: [25, 250, 1250, 2500], source: SGIS500,
    definition: `${SGIS500_NOTE} 총인구입니다(500m 격자 0.25km², 명/km²로는 ×4).`,
    use: '사람이 실제로 사는 곳을 500m 단위로 가르고, 분석할 시·군·구와 동네를 고르는 출발점으로 씁니다.' },
  { key: 'hh5', label: '가구', unit: '가구', resolution: '500m', group: 'sgis500', digits: 0, ramp: 'seq', breaks: [10, 100, 500, 1000], source: SGIS500,
    definition: `${SGIS500_NOTE} 총가구입니다.`, use: '주거 에너지 수요 단위(가구)가 몰린 곳을 찾습니다.' },
  { key: 'housing5', label: '주택', unit: '호', resolution: '500m', group: 'sgis500', digits: 0, ramp: 'seq', breaks: [10, 100, 500, 1000], source: SGIS500,
    definition: `${SGIS500_NOTE} 총주택(거처) 수입니다.`, use: '주택 재고가 많은 곳, 개보수 대상이 모인 곳을 찾습니다.' },
  { key: 'workers5', label: '종사자', unit: '명', resolution: '500m', group: 'sgis500', digits: 0, ramp: 'seq', breaks: [25, 125, 500, 1250], source: SGIS500,
    definition: `${SGIS500_NOTE} 사업체 종사자 수입니다.`, use: '상업·업무·산업 활동이 몰린 곳(비주거 에너지 수요)을 찾습니다.' },
  { key: 'pop_change5', label: '인구 증감률', unit: '%', resolution: '500m', group: 'sgis500', digits: 1, ramp: 'diff', breaks: [-20, -5, 5, 20], source: SGIS500,
    definition: `${SGIS500_NOTE} 2015년 대비 최근 연도 총인구의 증감률입니다. 두 해 모두 20명 이상일 때만 내고, 그렇지 않으면 비웁니다.`,
    use: '인구가 빠지는 곳(수요 감소·빈집)과 느는 곳(신규 개발)을 가립니다.' },
  { key: 'pop', label: '인구 밀도', unit: '명/km²', resolution: '1km', group: 'sgis1k', digits: 0, ramp: 'seq', source: SGIS,
    definition: '이 500m 격자를 품은 SGIS 1km 격자의 총인구입니다. 1km 격자는 1km²라서 값이 곧 km²당 인구입니다. 비밀보호 잡음(±7)이 있습니다.',
    use: '사람이 사는 곳과 비어 있는 곳을 가르고, 분석할 시·군·구를 고르는 출발점으로 씁니다.' },
  { key: 'hh', label: '가구 밀도', unit: '가구/km²', resolution: '1km', group: 'sgis1k', digits: 0, ramp: 'seq', source: SGIS,
    definition: '소속 1km 격자의 총가구입니다(1km²당).', use: '주거 에너지 수요가 몰린 곳을 찾습니다.' },
  { key: 'housing', label: '주택 밀도', unit: '호/km²', resolution: '1km', group: 'sgis1k', digits: 0, ramp: 'seq', source: SGIS,
    definition: '소속 1km 격자의 총주택 수입니다(1km²당).', use: '주택 재고가 많은 곳, 개보수 대상이 모인 곳을 찾습니다.' },
  { key: 'workers', label: '종사자 밀도', unit: '명/km²', resolution: '1km', group: 'sgis1k', digits: 0, ramp: 'seq', source: SGIS,
    definition: '소속 1km 격자의 사업체 종사자 수입니다(1km²당).', use: '상업·업무·산업 활동이 몰린 곳(비주거 에너지 수요)을 찾습니다.' },
  { key: 'elderly_pct', label: '65세 이상 비율', unit: '%', resolution: '1km', group: 'sgis1k', digits: 1, ramp: 'seq', breaks: [10, 20, 30, 40], source: SGIS,
    definition: '소속 1km 격자의 연령별 인구 중 65세 이상 비율입니다. 연령 인구 합이 20명 미만이면 비웁니다.', use: '고령층이 많은 곳의 난방·냉방 취약성을 함께 봅니다.' },
  { key: 'old_housing_pct', label: '2000년 이전 주택 비율', unit: '%', resolution: '1km', group: 'sgis1k', digits: 1, ramp: 'load', breaks: [20, 40, 60, 80], source: SGIS,
    definition: '소속 1km 격자의 건축연도별 주택 중 2000년 이전(1979년 이전·1980년대·1990년대)에 지은 비율입니다. 주택 수 20호 미만이면 비웁니다.',
    use: '노후 주택이 많아 단열 개보수 효과가 클 곳을 찾습니다.' },
  { key: 'apartment_pct', label: '아파트 비율', unit: '%', resolution: '1km', group: 'sgis1k', digits: 1, ramp: 'seq', breaks: [20, 40, 60, 80], source: SGIS,
    definition: '소속 1km 격자의 주택 유형 중 아파트 비율입니다. 20호 미만이면 비웁니다.', use: '공동주택 관측(K-apt)으로 설명되는 곳과 단독주택 위주인 곳을 가릅니다.' },
  { key: 'complexes', label: '공동주택 단지 수', unit: '단지', resolution: '500m', group: 'kapt', digits: 0, ramp: 'seq', breaks: [1, 2, 4, 8], source: KAPT,
    definition: 'K-apt 단지 목록의 좌표가 이 500m 격자 안에 있는 공동주택 단지 수입니다. 0은 목록에 오른 단지가 없다는 뜻입니다(소규모 공동주택은 목록에 없을 수 있음).',
    use: '공동주택 에너지 관측(K-apt)을 받을 수 있는 곳을 찾습니다.' },
  { key: 'complex_year', label: '단지 평균 사용승인연도', unit: '년', resolution: '500m', group: 'kapt', digits: 0, ramp: 'gain', breaks: [1995, 2005, 2015], source: KAPT,
    definition: '격자 안 공동주택 단지의 사용승인연도 평균입니다. 단지가 없으면 비웁니다.', use: '오래된 단지가 모인 곳(재건축·리모델링 후보)을 찾습니다.' },
];

export const DEFAULT_PROVINCE_METRIC = 'pop';
/** With the SGIS 500m statistics loaded the first view shows the cells' own population. */
export const DEFAULT_PROVINCE_METRIC_500 = 'pop5';

export function groupOf(metric: Pick<ProvinceMetric, 'group'>) { return PROVINCE_GROUPS.find((g) => g.key === metric.group) ?? PROVINCE_GROUPS[1]; }

/** GeoJSON features (one square per cell) from the compact rows, keyed by field name. */
export function rowValue(fields: string[], row: Array<number | null>, key: string): number | null {
  const index = fields.indexOf(key);
  const value = index >= 0 ? row[index] : null;
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}
