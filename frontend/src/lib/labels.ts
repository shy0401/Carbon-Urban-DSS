/** 대분류 이름과 건물 용도 색 — 대시보드가 지도 지표 정의 전체(mapMetrics)를 불러오지 않도록 분리. */
import { USE_GROUP_COLOR } from '../theme/palette';

export const ZONE_NAME: Record<string, string> = { RESIDENTIAL: '주거', COMMERCIAL: '상업', INDUSTRIAL: '공업', GREEN: '녹지', OTHER: '기타', UNKNOWN: '이름 없음' };
export const USE_NAME: Record<string, string> = { RESIDENTIAL: '주거', COMMERCIAL: '상업·업무', INDUSTRIAL: '공업·창고', PUBLIC: '공공·교육·의료', OTHER: '기타', UNKNOWN: '용도 미상' };
/** 건물 용도 대분류 색 (DESIGN.md 2.5.1). 용도 미상은 null = 해치. */
export const USE_ORDER = ['RESIDENTIAL', 'COMMERCIAL', 'INDUSTRIAL', 'PUBLIC', 'OTHER', 'UNKNOWN'] as const;
export const USE_COLORS: Array<[string, string | null]> = USE_ORDER.map((key) => [key, USE_GROUP_COLOR[key] ?? null]);
