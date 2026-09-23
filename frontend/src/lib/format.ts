import type { Quality } from '../types';

export function formatMetric(value: number | null | undefined, unit = '', maximumFractionDigits = 0): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '자료 없음';
  const number = new Intl.NumberFormat('ko-KR', { maximumFractionDigits }).format(value);
  return unit ? `${number} ${unit}` : number;
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return '기록 없음';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('ko-KR', { dateStyle: 'medium', timeStyle: 'short' }).format(date);
}

export function qualityLabel(quality: Quality | null | undefined): string {
  const labels: Record<string, string> = {
    OBSERVED: '관측 자료',
    ESTIMATED: '추정 자료',
    FALLBACK: '대체 자료',
    MISSING: '자료 없음',
    CALCULATED: '공공데이터 계산',
    MODELED: '모델 결과',
    IMPUTED: '결측 보정',
    SCENARIO: '시나리오',
    INSUFFICIENT_TRAINING_DATA: '학습 자료 부족',
    VALIDATED: '공간 교차검증 완료',
    NOT_VALIDATED: '미검증',
  };
  return quality ? labels[quality.toUpperCase()] ?? quality : '미평가';
}

export function qualityTone(quality: Quality | null | undefined): string {
  const value = quality?.toUpperCase();
  if (value === 'OBSERVED' || value === 'CALCULATED' || value === 'COMPLETED' || value === 'SUCCESS') return 'good';
  if (value === 'VALIDATED') return 'good';
  if (value === 'INSUFFICIENT_TRAINING_DATA' || value === 'NOT_VALIDATED') return 'warn';
  if (value === 'ESTIMATED' || value === 'MODELED' || value === 'IMPUTED' || value === 'SCENARIO' || value === 'FALLBACK' || value === 'RUNNING' || value === 'PENDING') return 'warn';
  if (value === 'FAILED' || value === 'ERROR' || value === 'MISSING') return 'bad';
  return 'neutral';
}

export function asRows(value: unknown): Array<Record<string, unknown>> {
  if (Array.isArray(value)) return value.filter((item): item is Record<string, unknown> => !!item && typeof item === 'object');
  if (value && typeof value === 'object') {
    const record = value as Record<string, unknown>;
    const candidate = record.items ?? record.rows ?? record.data;
    if (Array.isArray(candidate)) return candidate.filter((item): item is Record<string, unknown> => !!item && typeof item === 'object');
    return [record];
  }
  return [];
}

/** Integer-ish values with a Korean compact suffix for large magnitudes (1.2만, 3.4억). */
export function formatCompact(value: number | null | undefined, unit = ''): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '자료 없음';
  const abs = Math.abs(value);
  const text = abs >= 1e8 ? `${trim(value / 1e8)}억` : abs >= 1e4 ? `${trim(value / 1e4)}만` : new Intl.NumberFormat('ko-KR', { maximumFractionDigits: abs < 10 ? 2 : abs < 100 ? 1 : 0 }).format(value);
  return unit ? `${text} ${unit}` : text;
}

function trim(value: number): string {
  return new Intl.NumberFormat('ko-KR', { maximumFractionDigits: Math.abs(value) < 10 ? 2 : 1 }).format(value);
}

export function formatPercent(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '자료 없음';
  return `${new Intl.NumberFormat('ko-KR', { maximumFractionDigits: digits }).format(value)}%`;
}

/** Share of a total as "x.x%" or null when the denominator is missing or zero. */
export function share(part: number | null | undefined, total: number | null | undefined): number | null {
  if (part === null || part === undefined || !total) return null;
  return (part / total) * 100;
}

export type DataClass = 'OBSERVED' | 'CALCULATED' | 'ESTIMATED' | 'SCENARIO' | 'FALLBACK' | 'MISSING';

export const DATA_CLASS: Record<DataClass, { label: string; css: string; hint: string }> = {
  OBSERVED: { label: '관측', css: 'obs', hint: '공공기관이 측정·공표한 값을 그대로 사용' },
  CALCULATED: { label: '계산', css: 'calc', hint: '관측값과 공식 계수·면적으로 계산 (산식 공개)' },
  ESTIMATED: { label: '추정', css: 'est', hint: '가정이 포함된 근사값 (예: 건축면적 × 층수)' },
  SCENARIO: { label: '시나리오', css: 'scen', hint: '계획안 입력에 따른 가정 결과' },
  FALLBACK: { label: '대체', css: 'fb', hint: '공식 자료가 없어 대체 출처를 사용' },
  MISSING: { label: '미확보', css: 'miss', hint: '자료가 없어 계산하지 않음 (0이 아님)' },
};
