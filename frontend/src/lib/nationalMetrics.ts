import type { RampName } from '../theme/palette';
import type { NationalMetrics } from '../types';

/** Indicators of the national (전국) map: only layers every 시·도 and 시·군·구 has. Energy and carbon are not national yet. */
export interface NationalMetric {
  key: keyof NationalMetrics;
  label: string;
  unit: string;
  digits: number;
  ramp: RampName;
  /** Fixed class lower bounds (after the first class); quantiles otherwise. */
  breaks?: number[];
  source: 'admin' | 'grid500' | 'complexes';
  definition: string;
  use: string;
}

export const NATIONAL_METRICS: NationalMetric[] = [
  { key: 'population', label: '인구', unit: '명', digits: 0, ramp: 'seq', source: 'admin',
    definition: 'SGIS 행정구역 통계의 총인구(시군구 합)입니다. 비공개 값이 있는 곳은 합에서 빠집니다.',
    use: '생활 에너지 수요의 규모를 시·도·시·군·구끼리 비교합니다.' },
  { key: 'density', label: '인구밀도', unit: '명/km²', digits: 0, ramp: 'seq', source: 'admin',
    definition: '행정구역 총인구 ÷ SGIS 경계 면적입니다.', use: '도시화 정도를 비교하고 고밀 지역(공동주택·상업 밀집)을 가립니다.' },
  { key: 'households', label: '가구', unit: '가구', digits: 0, ramp: 'seq', source: 'admin',
    definition: 'SGIS 행정구역 통계의 일반가구 수(시군구 합)입니다.', use: '주거 에너지 수요 단위(가구) 규모를 비교합니다.' },
  { key: 'pop_change_pct', label: '인구 증감률', unit: '%', digits: 1, ramp: 'diff', breaks: [-10, -3, 3, 10], source: 'grid500',
    definition: 'SGIS 500m 격자 인구를 시·군·구로 모아 2015년과 최근 연도를 비교한 증감률입니다. 두 해 모두 20명 이상일 때만 냅니다.',
    use: '인구가 빠지는 지역(수요 감소·빈집)과 느는 지역(신규 개발)을 가려, 에너지 사용 변화의 원인을 나눠 봅니다.' },
  { key: 'housing500', label: '주택', unit: '호', digits: 0, ramp: 'seq', source: 'grid500',
    definition: 'SGIS 500m 격자 총주택을 시·군·구로 모은 값입니다. 받은 파일에 없는 블록이 걸친 곳은 비웁니다(일부 합 아님).',
    use: '주택 재고 규모, 개보수(그린리모델링) 대상 규모를 비교합니다.' },
  { key: 'workers500', label: '종사자', unit: '명', digits: 0, ramp: 'seq', source: 'grid500',
    definition: 'SGIS 500m 격자 총종사자를 시·군·구로 모은 값입니다. 받은 파일에 없는 블록이 걸친 곳은 비웁니다(일부 합 아님).',
    use: '상업·업무·산업 활동(비주거 에너지 수요)의 규모를 비교합니다.' },
  { key: 'complexes', label: 'K-apt 공동주택 단지', unit: '단지', digits: 0, ramp: 'seq', source: 'complexes',
    definition: 'K-apt 의무관리 공동주택 단지 목록의 단지 수입니다(소규모 공동주택은 목록에 없을 수 있음).',
    use: '공동주택 에너지 관측(K-apt 월별 에너지)을 받을 수 있는 규모를 봅니다.' },
];

export const DEFAULT_NATIONAL_METRIC: NationalMetric['key'] = 'density';

export function metricValue(metrics: NationalMetrics | null | undefined, key: NationalMetric['key']): number | null {
  const value = metrics?.[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

/** Why a 시·도/시·군·구 has no value for the metric (never shown as 0). */
export function missingReason(metric: NationalMetric, notes: Record<string, string> | undefined, excluded?: string | null): string {
  if (metric.source === 'grid500') {
    const note = notes?.[metric.key === 'pop_change_pct' ? 'pop500' : metric.key];
    if (note) return note;
    if (excluded) return '500m 격자 통계를 받지 않은 지역';
    return metric.key === 'pop_change_pct' ? '두 해 중 20명 미만 또는 통계 없음' : '500m 통계 없음';
  }
  return '자료 없음';
}

/** Group 시·도: 도 first, then 특별시·광역시 (legal code order inside). */
export function provinceGroups<T extends { kind: 'PROVINCE' | 'METRO'; code: string }>(items: T[]): Array<['PROVINCE' | 'METRO', T[]]> {
  const groups: Array<['PROVINCE' | 'METRO', T[]]> = [['PROVINCE', []], ['METRO', []]];
  for (const item of [...items].sort((a, b) => a.code.localeCompare(b.code))) groups[item.kind === 'PROVINCE' ? 0 : 1][1].push(item);
  return groups.filter(([, list]) => list.length > 0);
}

/** "경상북도" → "경북", "전남광주통합특별시" → "전남광주", "서울특별시" → "서울" (map chips). */
export function shortProvince(name: string): string {
  const special: Record<string, string> = { 충청북도: '충북', 충청남도: '충남', 경상북도: '경북', 경상남도: '경남', 전라남도: '전남', 전라북도: '전북' };
  if (special[name]) return special[name];
  return name.replace(/(특별자치도|특별자치시|통합특별시|특별시|광역시|도)$/, '');
}

export function levelLabel(level: string | null | undefined): string {
  return level === 'DETAILED' ? '상세 자료' : level === 'BASIC' ? '기본 지도' : level === 'UNLINKED' ? '법정 단위 연결 안 됨' : '지도 없음 (처음 열면 몇 초)';
}
