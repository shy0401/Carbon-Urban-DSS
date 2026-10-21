/** 대분류 이름과 건물 용도 색 — 대시보드가 지도 지표 정의 전체(mapMetrics)를 불러오지 않도록 분리. */
import { USE_GROUP_COLOR } from '../theme/palette';

export const ZONE_NAME: Record<string, string> = { RESIDENTIAL: '주거', COMMERCIAL: '상업', INDUSTRIAL: '공업', GREEN: '녹지', OTHER: '기타', UNKNOWN: '이름 없음' };
export const USE_NAME: Record<string, string> = { RESIDENTIAL: '주거', COMMERCIAL: '상업·업무', INDUSTRIAL: '공업·창고', PUBLIC: '공공·교육·의료', OTHER: '기타', UNKNOWN: '용도 미상' };
/** 건물 용도 대분류 색 (DESIGN.md 2.5.1). 용도 미상은 null = 해치. */
export const USE_ORDER = ['RESIDENTIAL', 'COMMERCIAL', 'INDUSTRIAL', 'PUBLIC', 'OTHER', 'UNKNOWN'] as const;
export const USE_COLORS: Array<[string, string | null]> = USE_ORDER.map((key) => [key, USE_GROUP_COLOR[key] ?? null]);

/** 건축물대장 주용도 묶음(서버 area.REGISTER_USE_GROUPS) → 대분류 색. '기타·미상'은 해치. */
export const REGISTER_USE_COLORS: Record<string, string | null> = {
  주거: USE_GROUP_COLOR.RESIDENTIAL ?? null, '상업·업무': USE_GROUP_COLOR.COMMERCIAL ?? null, '공공·교육·의료': USE_GROUP_COLOR.PUBLIC ?? null,
  '공업·창고·물류': USE_GROUP_COLOR.INDUSTRIAL ?? null, '기타·미상': null,
};
export const REGISTER_USE_NAMES: Record<string, string> = Object.fromEntries(Object.keys(REGISTER_USE_COLORS).map((k) => [k, k]));

/** 도로명주소 건물 층의 용도 몫이 실제로 알려진 값인지(전부 '용도 미상'이면 보이지 않는다). */
export function knownUseShares(shares: Record<string, number> | null | undefined): Record<string, number> | null {
  if (!shares) return null;
  const known = Object.entries(shares).filter(([k, v]) => k !== 'UNKNOWN' && v > 0);
  return known.length ? shares : null;
}
