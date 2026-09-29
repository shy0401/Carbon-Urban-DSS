/**
 * D안 「도시계획 도면」 색 — MapLibre·ECharts처럼 CSS 변수를 읽지 못하는 곳에서 쓴다.
 * 값과 키는 src/styles/tokens.css와 같아야 한다(palette.test.ts가 확인).
 */
export const TOKENS = {
  canvas: '#F3F3EE',
  surface: '#FFFFFF',
  'surface-sunk': '#ECEBE4',
  line: '#D9D7CE',
  'line-strong': '#BDBAAE',
  ink: '#1C2622',
  'ink-2': '#505B55',
  'ink-3': '#6B746E',
  primary: '#2F5D50',
  'primary-hover': '#264C42',
  'on-primary': '#FFFFFF',
  'nav-bg': '#1F3A33',
  'nav-ink': '#E6EEEA',
  'nav-ink-2': '#9FB5AB',
  'nav-active': '#2F5D50',
  focus: '#2E5A87',
  'select-line': '#111A16',
  'select-halo': '#FFFFFF',

  danger: '#B42318', 'danger-bg': '#FCEBE9',
  warning: '#8A5A00', 'warning-bg': '#FBF1DC',
  success: '#2F6B45', 'success-bg': '#E6F1E8',
  info: '#2E5A87', 'info-bg': '#E6EDF5',

  'prov-observed': '#1F5E4A', 'prov-observed-bg': '#E2EEE8',
  'prov-computed': '#2E5A87', 'prov-computed-bg': '#E5ECF4',
  'prov-estimated': '#7A5418', 'prov-estimated-bg': '#F4EBDA',
  'prov-scenario': '#4A5568', 'prov-scenario-bg': '#E8EBF0',
  'prov-missing': '#6B746E', 'prov-missing-bg': '#F1F0EA',
  hatch: '#CFCBBF',

  'load-1': '#F1EAD9', 'load-2': '#E2C58F', 'load-3': '#CC9350', 'load-4': '#A65B2B', 'load-5': '#6A2E17',
  'gain-1': '#E6EFE2', 'gain-2': '#BCD6B1', 'gain-3': '#88B783', 'gain-4': '#568F60', 'gain-5': '#2C6343',
  'diff-neg-2': '#2C6343', 'diff-neg-1': '#9CC495', 'diff-zero': '#F3F1EA', 'diff-pos-1': '#D9A56A', 'diff-pos-2': '#8A3F1E',
  'seq-1': '#E8EBF0', 'seq-2': '#C3CAD6', 'seq-3': '#97A3B6', 'seq-4': '#6B7A92', 'seq-5': '#4A5568',

  'zone-r1e': '#FFF4B8', 'zone-r2e': '#FFEC99', 'zone-r1': '#FBE07A', 'zone-r2': '#F6CF5A', 'zone-r3': '#EDB940', 'zone-rq': '#E39B3A',
  'zone-cn': '#F2B8C0', 'zone-cg': '#E8848F', 'zone-cc': '#D65A68', 'zone-cd': '#B8577A',
  'zone-iq': '#CFC3EA', 'zone-ig': '#A898D8', 'zone-ie': '#7F6CC0',
  'zone-gn': '#CFE6B8', 'zone-gp': '#B5D99A', 'zone-gc': '#93C47D',
  'zone-m': '#E4DEC3', 'zone-ag': '#D5DDB8', 'zone-ne': '#8FB88A',
  'use-public': '#9DB4CF', 'use-other': '#BDBAAE',

  'plan-a': '#2F5D50', 'plan-b': '#B8862B', 'plan-c': '#6E5C99',
  'series-electricity': '#2F5D50', 'series-gas': '#A65B2B',
} as const;

export type TokenName = keyof typeof TOKENS;

/** Non-hex tokens used by the map (same strings as tokens.css). */
export const LINE_ON_BASEMAP = 'rgba(255, 255, 255, .6)';
export const POPOVER_SHADOW = '0 4px 16px rgba(28, 38, 34, .12)';
export const FONT_STACK = '"Pretendard Variable", Pretendard, -apple-system, "Apple SD Gothic Neo", "Malgun Gothic", sans-serif';

const t = TOKENS;
/** 부하: 높을수록 나쁨 (에너지 사용량, 운영탄소). */
export const LOAD_RAMP = [t['load-1'], t['load-2'], t['load-3'], t['load-4'], t['load-5']];
/** 편익: 높을수록 좋음 (관측 완전성, 감축량). */
export const GAIN_RAMP = [t['gain-1'], t['gain-2'], t['gain-3'], t['gain-4'], t['gain-5']];
/** 중립 순차: 좋고 나쁨이 없는 도시 형태·토지이용·인구 지표. */
export const SEQ_RAMP = [t['seq-1'], t['seq-2'], t['seq-3'], t['seq-4'], t['seq-5']];
/** 증감: 음수(감소) → 0 → 양수(증가). */
export const DIFF_RAMP = [t['diff-neg-2'], t['diff-neg-1'], t['diff-zero'], t['diff-pos-1'], t['diff-pos-2']];
export const PLAN_COLORS = [t['plan-a'], t['plan-b'], t['plan-c']];

/** diff: 증감(음수 ↔ 0 ↔ 양수), 가운데는 중립 회색. */
export type RampName = 'load' | 'gain' | 'seq' | 'diff';
export const RAMPS: Record<RampName, string[]> = { load: LOAD_RAMP, gain: GAIN_RAMP, seq: SEQ_RAMP, diff: DIFF_RAMP };

/** 용도지역 세부 이름(공식 명칭) → 토큰. 이름에 포함된 핵심어로 찾고, 없으면 null(해치). */
const ZONE_RULES: Array<[string, TokenName]> = [
  ['제1종전용주거', 'zone-r1e'], ['제2종전용주거', 'zone-r2e'], ['제1종일반주거', 'zone-r1'], ['제2종일반주거', 'zone-r2'], ['제3종일반주거', 'zone-r3'], ['준주거', 'zone-rq'],
  ['근린상업', 'zone-cn'], ['일반상업', 'zone-cg'], ['중심상업', 'zone-cc'], ['유통상업', 'zone-cd'],
  ['준공업', 'zone-iq'], ['일반공업', 'zone-ig'], ['전용공업', 'zone-ie'],
  ['자연녹지', 'zone-gn'], ['생산녹지', 'zone-gp'], ['보전녹지', 'zone-gc'],
  ['계획관리', 'zone-m'], ['생산관리', 'zone-m'], ['보전관리', 'zone-m'], ['농림', 'zone-ag'], ['자연환경보전', 'zone-ne'],
];
export const ZONE_DETAIL: ReadonlyArray<readonly [string, TokenName]> = ZONE_RULES;
export function zoneToken(zoneName: string | null | undefined): TokenName | null {
  const name = String(zoneName ?? '');
  return ZONE_RULES.find(([keyword]) => name.includes(keyword))?.[1] ?? null;
}

/** 용도지역 대분류(서버 category) → 대표 색. 미분류·이름 없음은 null(해치). */
export const ZONE_GROUP_COLOR: Record<string, string | null> = {
  RESIDENTIAL: t['zone-r2'], COMMERCIAL: t['zone-cg'], INDUSTRIAL: t['zone-ig'], GREEN: t['zone-gp'], OTHER: t['zone-m'], UNKNOWN: null,
};

/** 건물 용도 대분류(서버 use_category) → 색. 용도 미상은 null(해치). */
export const USE_GROUP_COLOR: Record<string, string | null> = {
  RESIDENTIAL: t['zone-r2'], COMMERCIAL: t['zone-cg'], INDUSTRIAL: t['zone-ig'], PUBLIC: t['use-public'], OTHER: t['use-other'], UNKNOWN: null,
};
