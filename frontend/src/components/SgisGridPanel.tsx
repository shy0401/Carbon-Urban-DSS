/**
 * SGIS 1km 격자 통계 (공공데이터포털 '국가데이터처_SGIS 격자 통계 및 경계', 2024년 6월 30일 기준).
 * 값은 서버가 준 공식 격자 값 그대로이며 여기서는 고르고 묶기만 한다.
 * - null은 공표 값이 없는 것(인구가 없거나 비공개)이라 0이 아니라 "통계 없음"으로 적는다.
 * - 비밀보호 잡음(인구 부문 5 미만은 0 또는 5로 확률 대체, 그 이상 ±7)이 있어 구성비는 항목 합 기준이다.
 */
import type { ReactNode } from 'react';
import { MissingValue } from './MissingValue';
import { formatMetric } from '../lib/format';
import type { SgisGridSummary } from '../types';

export const SGIS_RULE = '공식 격자 통계이며 비밀보호를 위해 5 미만 값은 0 또는 5로 확률 대체되고, 그 이상은 최대 ±7(사업체 ±4)의 잡음이 들어 있습니다. 세부 항목의 합은 총계와 다를 수 있습니다.';

const SHARES: Array<[keyof SgisGridSummary, string, string]> = [
  ['elderly_pct', '65세 이상 인구', '연령별 인구 합 기준'],
  ['children_pct', '14세 이하 인구', '연령별 인구 합 기준'],
  ['single_household_pct', '1인가구', '총가구 기준'],
  ['old_housing_pct', '2000년 이전 준공 주택', '건축연도별 주택 합 기준'],
  ['apartment_pct', '아파트', '주택 유형별 합 기준'],
];

/** 한 분포의 항목들. 순서를 그대로 두고, 값이 없는 항목은 "통계 없음"으로 남긴다. */
export function Distribution({ title, rows, unit }: { title: string; rows: Array<[string, number | null]>; unit: string }) {
  const present = rows.filter((r): r is [string, number] => r[1] !== null);
  const total = present.reduce((sum, [, v]) => sum + v, 0);
  const max = Math.max(0, ...present.map(([, v]) => v));
  return <div className="sgis-dist">
    <h4>{title}</h4>
    {present.length === 0 ? <MissingValue reason="공표 값 없음" /> : <ul>
      {rows.map(([label, value]) => <li key={label} className={value === null ? 'no-stat' : undefined}>
        <span className="sgis-dist-label" title={label}>{label}</span>
        <span className="sgis-dist-track" aria-hidden="true">{value !== null && max > 0 && <i style={{ width: `${(value / max) * 100}%` }} />}</span>
        <span className="sgis-dist-value">{value === null ? '통계 없음' : <>{formatMetric(value, unit)}{total > 0 && <small>{((value / total) * 100).toFixed(1)}%</small>}</>}</span>
      </li>)}
    </ul>}
  </div>;
}

export function SgisGridSummaryView({ summary, scope, extra }: { summary: SgisGridSummary; scope: ReactNode; extra?: ReactNode }) {
  const s = summary;
  const baseMissing = (key: keyof SgisGridSummary) => (key === 'elderly_pct' || key === 'children_pct' ? s.population : key === 'single_household_pct' ? s.households : s.housing);
  return <div className="sgis-grid-view">
    <p className="sgis-scope">{scope}</p>
    <dl className="sgis-figures">
      {([['인구', s.population, '명'], ['가구', s.households, '가구'], ['주택', s.housing, '호'], ['사업체', s.businesses, '곳'], ['종사자', s.workers, '명']] as Array<[string, number | null, string]>).map(([label, value, unit]) =>
        <div key={label} className={value === null ? 'is-missing' : undefined}><dt>{label}</dt><dd>{value === null ? <MissingValue inline reason="통계 없음" /> : formatMetric(value, unit)}</dd></div>)}
      {extra}
    </dl>
    <dl className="sgis-shares">
      {SHARES.map(([key, label, basis]) => {
        const value = s[key] as number | null;
        return <div key={key} className={value === null ? 'is-missing' : undefined}><dt>{label}</dt><dd>{value === null ? <MissingValue inline reason={baseMissing(key) === null ? '통계 없음' : '기준 20 미만이라 잡음이 커서 계산하지 않음'} /> : <>{value.toFixed(1)}<span className="unit">%</span><small>{basis}</small></>}</dd></div>;
      })}
    </dl>
    <div className="sgis-dists">
      <Distribution title="주택 건축연도" rows={Object.entries(s.housing_age)} unit="호" />
      <Distribution title="주택 유형" rows={Object.entries(s.housing_types)} unit="호" />
      <Distribution title="주택 규모 (연면적)" rows={Object.entries(s.housing_area ?? {})} unit="호" />
      <Distribution title="가구 구성" rows={Object.entries(s.household_types)} unit="가구" />
      <Distribution title="산업별 종사자 (상위 6)" rows={s.sectors.slice(0, 6).map((row) => [row.name, row.workers])} unit="명" />
    </div>
    <p className="muted sgis-rule">{SGIS_RULE}{s.small_flags.length ? ' 0 또는 5로 표시된 총계는 5 미만일 수 있는 대체값입니다.' : ''}</p>
  </div>;
}
