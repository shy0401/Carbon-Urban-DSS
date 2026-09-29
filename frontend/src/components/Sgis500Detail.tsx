import { useEffect, useState } from 'react';
import { api } from '../lib/api';
import { formatMetric } from '../lib/format';
import type { GridProps, Sgis500Series, Sgis500Year } from '../types';
import { MissingValue } from './MissingValue';

const SMALL_TEXT: Record<string, string> = { population: '인구', households: '가구', housing: '주택', businesses: '사업체', workers: '종사자' };

/** Population by year as a thin line (years without a row are gaps, never 0). */
export function PopulationSpark({ rows }: { rows: Sgis500Year[] }) {
  const points = rows.filter((r) => typeof r.population === 'number');
  if (points.length < 2) return null;
  const years = rows.map((r) => r.year);
  const [y0, y1] = [Math.min(...years), Math.max(...years)];
  const values = points.map((r) => r.population as number);
  const [lo, hi] = [Math.min(...values), Math.max(...values)];
  const x = (year: number) => 8 + ((year - y0) / Math.max(1, y1 - y0)) * 224;
  const y = (v: number) => 40 - (hi === lo ? 0.5 : (v - lo) / (hi - lo)) * 32;
  const first = points[0], last = points[points.length - 1];
  return <figure className="spark" aria-label={`인구 ${first.year}년 ${formatMetric(first.population)}명에서 ${last.year}년 ${formatMetric(last.population)}명`}>
    <svg viewBox="0 0 240 48" aria-hidden="true">
      <polyline className="spark-line" points={points.map((r) => `${x(r.year).toFixed(1)},${y(r.population as number).toFixed(1)}`).join(' ')} />
      {points.map((r) => <circle key={r.year} className="spark-dot" cx={x(r.year)} cy={y(r.population as number)} r={r === last ? 3.5 : 2.5}><title>{`${r.year}년 인구 ${formatMetric(r.population)}명`}</title></circle>)}
    </svg>
    <figcaption><span>{first.year}년 {formatMetric(first.population, '명')}</span><span>{last.year}년 {formatMetric(last.population, '명')}</span></figcaption>
  </figure>;
}

/** 이 500m 격자 자체의 SGIS 통계 (자료제공 신청분): 최근 연도 값, 2015년 대비 인구 증감, 연도별 값. */
export function Sgis500Detail({ p }: { p: GridProps }) {
  const status = p.sgis500_status;
  const [series, setSeries] = useState<Sgis500Series | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (status !== 'OBSERVED') return undefined;
    let live = true;
    setSeries(null); setFailed(false);
    api<Sgis500Series>(`/sgis-grid/500m/cell/${encodeURIComponent(p.id)}`).then((s) => { if (live) setSeries(s); }).catch(() => { if (live) setFailed(true); });
    return () => { live = false; };
  }, [p.id, status]);
  if (!status) return null; // 500m 통계를 아직 받지 않음: 아래 1km 절이 설명한다
  const small = (p.sgis500_small ?? []).map((k) => SMALL_TEXT[k]).filter(Boolean);
  return <section className="detail-section" aria-label="인구와 주택 (SGIS 500m 격자)">
    <h3>인구·주택 <small className="resolution-tag res-500m">SGIS {p.sgis500_year ?? ''}년 500m 격자 자체</small></h3>
    {status === 'NO_STAT' ? <MissingValue reason="이 500m 격자에는 공표된 통계가 없습니다(인구·사업체가 없거나 받은 파일에 없음). 0이 아닙니다." /> : <>
      <dl className="fact-list">
        <Sgis500Fact label="인구" value={p.sgis500_population} unit="명" why={p.sgis500_pop_density != null ? `밀도 ${formatMetric(p.sgis500_pop_density, '명/km²')}` : undefined} />
        <Sgis500Fact label="가구" value={p.sgis500_households} unit="가구" />
        <Sgis500Fact label="주택" value={p.sgis500_housing} unit="호" />
        <Sgis500Fact label="종사자" value={p.sgis500_workers} unit="명" why={p.sgis500_businesses != null ? `사업체 ${formatMetric(p.sgis500_businesses, '곳')}` : undefined} />
        <Sgis500Fact label={`인구 증감 (${p.sgis500_base_year ?? 2015}→${p.sgis500_year ?? ''})`} value={p.sgis500_pop_change_pct} unit="%" digits={1}
          why={p.sgis500_pop_change_pct != null ? `${formatMetric(p.sgis500_base_population, '명')} → ${formatMetric(p.sgis500_population, '명')}` : undefined}
          missing="두 해 중 한 해라도 20명 미만이거나 통계 없음" />
      </dl>
      {series?.series && series.series.length > 1 && <>
        <PopulationSpark rows={series.series} />
        <details className="sgis500-years"><summary>연도별 값 ({series.series.length}개 연도)</summary>
          <table className="compact-table">
            <thead><tr><th scope="col">연도</th><th scope="col">인구</th><th scope="col">가구</th><th scope="col">주택</th><th scope="col">종사자</th></tr></thead>
            <tbody>{series.series.map((r) => <tr key={r.year}><th scope="row">{r.year}</th>{(['population', 'households', 'housing', 'workers'] as const).map((k) => <td key={k}>{r[k] == null ? <span className="muted">없음</span> : formatMetric(r[k])}</td>)}</tr>)}</tbody>
          </table>
          <p className="muted">2000·2005·2010년은 인구만 제공됩니다. "없음"은 그해 통계가 없다는 뜻이며 0이 아닙니다.</p>
        </details>
      </>}
      {failed && <p className="muted">연도별 값을 불러오지 못했습니다.</p>}
      <p className="muted">격자 자체의 공식 통계입니다. 비밀보호로 인구 부문 5 미만은 0 또는 5, 사업체 부문 3 미만은 0 또는 3으로 대체했고, 그 이상 값에도 최대 ±7(사업체 ±4)의 잡음이 있습니다.{small.length ? ` 이 격자의 ${small.join('·')}는 대체됐을 수 있는 작은 값입니다.` : ''}</p>
    </>}
  </section>;
}

function Sgis500Fact({ label, value, unit, digits = 0, why, missing = '통계 없음 (0 아님)' }: { label: string; value: number | null | undefined; unit: string; digits?: number; why?: string; missing?: string }) {
  const empty = value === null || value === undefined || !Number.isFinite(value);
  return <div className={`fact${empty ? ' missing' : ''}`}><dt>{label}</dt><dd>{empty ? <MissingValue inline reason={missing} /> : <>{formatMetric(value, '', digits)}<span className="unit">{unit}</span></>}</dd>{why && !empty && <span className="why">{why}</span>}</div>;
}
