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
  };
  return quality ? labels[quality.toUpperCase()] ?? quality : '미평가';
}

export function qualityTone(quality: Quality | null | undefined): string {
  const value = quality?.toUpperCase();
  if (value === 'OBSERVED' || value === 'CALCULATED' || value === 'COMPLETED' || value === 'SUCCESS') return 'good';
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
