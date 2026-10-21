import { formatMetric } from './format';

/** 팀 변화 모델(urban-carbon 7차) — 500m 칸 개발 계획의 건물 배출 변화(tCO₂e/년) 추정. 이 PC 화면에서만 쓴다. */

export type TeamUse = 'residential' | 'commercial' | 'large_retail' | 'office' | 'officetel' | 'industrial' | 'knowledge_industry' | 'education' | 'medical_welfare' | 'other';

export const TEAM_USES: Array<[TeamUse, string]> = [
  ['residential', '주거'], ['commercial', '상업'], ['office', '업무'], ['officetel', '오피스텔'], ['large_retail', '대형 판매'],
  ['knowledge_industry', '지식산업센터'], ['education', '교육'], ['medical_welfare', '의료·복지'], ['industrial', '공업 (범위 밖)'], ['other', '기타 비주거'],
];

export const USE_CLASS_LABEL: Record<string, string> = { residential: '주거', mixed: '복합', commercial: '상업·업무', industrial: '공업·물류', other_nonres: '기타 비주거', all: '전체' };

/** 팀 결과의 '1천 tCO₂e 미만은 방향만 읽는다' 기준. */
export const SMALL_CHANGE_T = 1000;

export interface TeamCaseScore { set: 'train_cv' | 'test'; actual_tco2e: number | null; pred_tco2e: number | null; pred_other_regions_tco2e?: number | null; years_from?: string | null; model?: string }
export interface TeamCase {
  grid_id: string; grid_code: string; before_year: number; after_year: number;
  dong_name?: string | null; floor_area_added_m2?: number | null; reg_floor_area_added_m2?: number | null; reg_dwellings_added?: number | null;
  buildings_tco2e_before?: number | null; buildings_tco2e_after?: number | null; buildings_tco2e_change?: number | null;
  pair_usable?: boolean | string | null; site_kind?: string | null; use_kind?: string | null; development_id?: string | null;
  case_start_year?: number | null; case_approval_year?: number | null; model?: TeamCaseScore | null;
}
export interface TeamCellResponse { region: string | null; dataset: string | null; grid: string; cases: TeamCase[]; scored: number }

export interface TeamAccuracyRow { band: string; cases: number; median_error: number; within_50pct: number; sum_ratio: number; note?: string }
export interface TeamStatus {
  status: 'starting' | 'training' | 'ready' | 'unavailable' | 'error' | 'off' | 'restricted';
  reason?: string | null; snapshot?: string | null; train?: string | null; ready_at?: string | null; train_seconds?: number | null; error?: string | null;
  versions?: Record<string, string>; regions?: string[];
  accuracy?: { model: string; train: string; test: TeamAccuracyRow[]; by_use: string; band_coverage: string; source: string };
}

export interface TeamPrediction {
  grid?: string; cell: string; region: string | null; before_year: number; after_year: number;
  emission_before_tco2e: number; floor_area_before_m2: number; floor_area_after_m2: number; site_kind: string; use_class: string;
  change_tco2e: number; band: Record<string, number>; sources_tco2e: Record<string, number>; filled: string[]; factors: string[];
  warnings: string[]; out_of_range: string[]; attribution: Record<string, number>; describe?: string;
}
export interface TeamPredictResponse { dataset: string; train: string; snapshot: string | null; results: TeamPrediction[]; combined: unknown; data_class: 'SCENARIO'; note: string }

export const SOURCE_LABEL: Record<string, string> = { elec_tco2e_total: '전기', gas_tco2e_total: '가스', heat_tco2e_total: '지역난방' };

export function signed(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  const text = formatMetric(Math.abs(value), '', digits);
  return value > 0 ? `+${text}` : value < 0 ? `−${text}` : text;
}

/** 예측 크기에 따른 읽는 법: 1천 미만은 방향만. */
export function readingOf(change: number): 'direction' | 'value' {
  return Math.abs(change) < SMALL_CHANGE_T ? 'direction' : 'value';
}

export function bandText(band: Record<string, number>): string | null {
  const lo = band.q10; const hi = band.q90;
  if (lo === undefined || hi === undefined) return null;
  const [a, b] = lo <= hi ? [lo, hi] : [hi, lo];
  return `${signed(a)} ~ ${signed(b)} tCO₂e (80% 구간)`;
}

/** 사례 점수: |예측 − 실제| ÷ |실제| (실제 100 tCO₂e 이상만). */
export function caseError(score: TeamCaseScore | null | undefined): number | null {
  if (!score || score.actual_tco2e === null || score.pred_tco2e === null || Math.abs(score.actual_tco2e) < 100) return null;
  return Math.abs(score.pred_tco2e - score.actual_tco2e) / Math.abs(score.actual_tco2e);
}

export function siteLabel(kind: string | null | undefined): string {
  return kind === 'new_site' ? '빈 땅 신축' : kind === 'built_up' ? '기존 시가지' : '—';
}

export function statusText(s: TeamStatus | null): string {
  if (!s) return '모델 상태 확인 중…';
  switch (s.status) {
    case 'ready': return `학습 완료${s.train_seconds ? ` (${Math.round(s.train_seconds)}초)` : ''} · ${s.train ?? ''}`;
    case 'training': return '변화 모델을 학습하는 중입니다(1~3분). 잠시 뒤 예측할 수 있습니다.';
    case 'starting': return '모델 서비스를 시작하는 중입니다.';
    case 'restricted': return s.reason ?? '공개 시연 주소에서는 쓸 수 없습니다.';
    case 'unavailable': return s.reason ?? '팀 인계 묶음이 없어 모델을 쓸 수 없습니다.';
    case 'error': return `모델 오류: ${s.error ?? '알 수 없음'}`;
    default: return s.reason ?? '모델 서비스가 꺼져 있습니다.';
  }
}
