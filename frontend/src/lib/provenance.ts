/**
 * 근거 유형 (DESIGN.md 2.3). 값은 서버 응답의 필드를 그대로 옮긴다 — 프런트에서 새로 추론하지 않는다.
 * 매핑 대상 필드는 docs/DESIGN_APPLY_LOG.md 0.4에 적어 둔다.
 */
export type Provenance = 'observed' | 'computed' | 'estimated' | 'scenario' | 'fallback' | 'missing';

export const PROVENANCE: Record<Provenance, { label: string; hint: string }> = {
  observed: { label: '실측', hint: '공공기관이 측정·공표한 관측값' },
  computed: { label: '계산', hint: '관측값과 공식 계수·면적으로 계산한 값' },
  estimated: { label: '추정', hint: '가정이 들어간 근사값' },
  scenario: { label: '시나리오', hint: '계획안 입력에 따른 가정 결과' },
  fallback: { label: '대체', hint: '공식 자료가 없어 대체 출처를 쓴 값' },
  missing: { label: '자료 미확보', hint: '자료가 없어 계산하지 않음 (0이 아님)' },
};

/** Server data-class codes (`observations_label`, `metadata_label`, `data_class`, feature `quality`). */
export function provenanceFromCode(code: unknown): Provenance | null {
  switch (String(code ?? '').toUpperCase()) {
    case 'OBSERVED': case 'OBSERVED_ZERO': return 'observed';
    case 'CALCULATED': return 'computed';
    case 'ESTIMATED': case 'MODELED': case 'IMPUTED': return 'estimated';
    case 'SCENARIO': return 'scenario';
    case 'FALLBACK': return 'fallback';
    case 'MISSING': case 'NOT_COLLECTED': return 'missing';
    default: return null;
  }
}

/** Weather rows carry `source_type`: OFFICIAL = KMA ASOS station observation, FALLBACK = ERA5-Land reanalysis. */
export function provenanceFromWeatherSource(sourceType: unknown): Provenance | null {
  const value = String(sourceType ?? '').toUpperCase();
  return value === 'OFFICIAL' ? 'observed' : value === 'FALLBACK' ? 'fallback' : null;
}

/** Catalog `source_type` labels (출처 성격 — 근거 유형 배지와 별개인 출처 표기). */
export function sourceTypeLabel(sourceType: unknown): string {
  return ({ OFFICIAL: '공식', FALLBACK: '대체', DERIVED: '파생', UNVERIFIED: '미검증' } as Record<string, string>)[String(sourceType ?? '').toUpperCase()] ?? String(sourceType ?? '미기록');
}
