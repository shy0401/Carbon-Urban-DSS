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
    READY_FOR_SPATIAL_VALIDATION: '공간 검증 준비',
    SPATIALLY_EVALUATED: '공간 교차검증 완료',
    INSUFFICIENT_BASELINE_DATA: '기준 자료 부족',
    ENERGY_OPTIMAL: '에너지 기준 후보',
    NO_FEASIBLE_CANDIDATES: '조건을 만족하는 후보 없음',
  };
  return quality ? labels[quality.toUpperCase()] ?? quality : '미평가';
}

export function qualityTone(quality: Quality | null | undefined): string {
  const value = quality?.toUpperCase();
  if (value === 'OBSERVED' || value === 'CALCULATED' || value === 'COMPLETED' || value === 'SUCCESS') return 'good';
  if (value === 'VALIDATED') return 'good';
  if (value === 'INSUFFICIENT_TRAINING_DATA' || value === 'NOT_VALIDATED' || value === 'INSUFFICIENT_BASELINE_DATA' || value === 'NO_FEASIBLE_CANDIDATES') return 'warn';
  if (value === 'SPATIALLY_EVALUATED') return 'good';
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

/** 이름 뒤 보조사: 받침이 있으면 '은', 없으면 '는' ("완주군은", "수원시는"). */
export function withTopic(name: string): string {
  const last = name.trim().slice(-1);
  const code = last.charCodeAt(0) - 0xac00;
  if (code < 0 || code > 11171) return `${name}은(는)`;
  return `${name}${code % 28 ? '은' : '는'}`;
}
