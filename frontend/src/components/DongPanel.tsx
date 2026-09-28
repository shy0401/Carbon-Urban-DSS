import { X } from 'lucide-react';
import { useMemo } from 'react';
import { aggregateMetric, complexesByDong, dongCells, rankDongs, type DongAggregate, type DongComplexes } from '../lib/dongs';
import { formatMetric } from '../lib/format';
import { METRICS, type MetricDef } from '../lib/mapMetrics';
import type { DongData, GridProps } from '../types';

/** 읍면동 요약에 늘 보여 주는 지표 (값이 없으면 "자료 없음"). */
const KEY_FACTS = ['electricity_kwh_annual', 'gas_kwh_annual', 'electricity_carbon_t', 'bldg_electricity_kwh', 'building_count', 'far_est_pct',
  'reg_far_pct', 'sgis_elderly_pct', 'sgis_old_housing_pct', 'sgis_apartment_pct'];
const COMPLEX_KEYS = new Set(['complex_count', 'complex_households']);

function exactComplex(key: string, c: DongComplexes | undefined): DongAggregate {
  if (!c) return { value: null, kind: 'sum', coverage: 0, valuedCells: 0 };
  if (key === 'complex_count') return { value: c.count, kind: 'sum', coverage: 1, valuedCells: c.count };
  return { value: c.withHouseholds ? c.households : null, kind: 'sum', coverage: c.count ? c.withHouseholds / c.count : 0, valuedCells: c.withHouseholds };
}

function Value({ result, metric }: { result: DongAggregate; metric: Pick<MetricDef, 'unit' | 'digits'> }) {
  if (result.value === null) return <span className="muted">자료 없음 (0 아님)</span>;
  return <>{formatMetric(result.value, '', result.kind === 'sum' ? 0 : metric.digits)}<span className="unit">{metric.unit}</span></>;
}

function coverageText(result: DongAggregate, key: string) {
  if (result.value === null) return null;
  if (key === 'complex_count') return '단지 좌표로 셈';
  if (key === 'complex_households') return `세대수 있는 단지 ${formatMetric(result.coverage * 100, '%', 0)}`;
  return `값 있는 면적 ${formatMetric(result.coverage * 100, '%', 0)}`;
}

/** 선택한 읍면동의 공식 인구·가구와 격자 지표 모음, 그리고 지금 지표로 본 동별 비교. */
export function DongPanel({ data, index, grids, complexes, metric, regionName, onSelect, onClose }: {
  data: DongData; index: number | null; grids: Map<string, GridProps>; complexes: GeoJSON.FeatureCollection | null | undefined;
  metric: MetricDef; regionName: string; onSelect: (index: number | null) => void; onClose: () => void;
}) {
  const complexCounts = useMemo(() => complexesByDong(data, complexes), [data, complexes]);
  const ranks = useMemo(() => {
    const base = rankDongs(data, metric, grids);
    if (!COMPLEX_KEYS.has(metric.key)) return base;
    return base.map((r) => ({ ...r, result: exactComplex(metric.key, complexCounts[r.index]) }))
      .sort((a, b) => (b.result.value ?? -Infinity) - (a.result.value ?? -Infinity) || a.name.localeCompare(b.name, 'ko'));
  }, [data, metric, grids, complexCounts]);
  const dong = index !== null ? data.dongs[index] : null;
  const shares = useMemo(() => dongCells(data, index ?? -1), [data, index]);
  const top = Math.max(...ranks.map((r) => r.result.value ?? 0), 0);
  const current = dong ? (COMPLEX_KEYS.has(metric.key) ? exactComplex(metric.key, complexCounts[index as number]) : aggregateMetric(metric, grids, shares)) : null;
  const coveredPct = dong?.area_km2 ? Math.min(100, (dong.cell_area_km2 / dong.area_km2) * 100) : null;
  return <aside className="map-detail dong-panel" aria-label={dong ? `${dong.name} 요약` : '읍면동 비교'}>
    <header className="detail-head"><div><h2>{dong ? dong.name : '읍면동 비교'}</h2><small className="muted">{regionName} · 행정동 {data.dongs.length}곳</small></div>
      <button type="button" className="icon-link" aria-label="읍면동 닫기" onClick={onClose}><X size={16} /></button></header>
    {dong && <>
      <section className="detail-section" aria-label="행정동 공식 통계">
        <h3>인구·가구 <small className="resolution-tag res-500m">SGIS {data.year ?? ''} 행정동 공식 값</small></h3>
        <dl className="fact-list">
          <div className="fact"><dt>인구</dt><dd>{dong.population === null ? <span className="muted">{dong.population_status === 'SUPPRESSED' ? '비공개' : '자료 없음'}</span> : formatMetric(dong.population, '명')}</dd></div>
          <div className="fact"><dt>가구</dt><dd>{dong.households === null ? <span className="muted">{dong.household_status === 'SUPPRESSED' ? '비공개' : '자료 없음'}</span> : formatMetric(dong.households, '가구')}</dd></div>
          <div className="fact"><dt>면적</dt><dd>{formatMetric(dong.area_km2, 'km²', 2)}</dd></div>
          <div className="fact"><dt>인구밀도</dt><dd>{formatMetric(dong.density, '명/km²')}</dd></div>
          <div className="fact"><dt>공동주택 (K-apt)</dt><dd>{complexCounts[index as number]?.count ? `${complexCounts[index as number].count}단지${complexCounts[index as number].withHouseholds ? `, ${formatMetric(complexCounts[index as number].households, '세대')}` : ''}` : '없음'}</dd></div>
        </dl>
        <p className="muted">분석 격자 {dong.cells.toLocaleString('ko-KR')}개가 걸칩니다{coveredPct !== null ? ` (행정동 면적의 ${formatMetric(coveredPct, '%', 0)})` : ''}. 인구·가구는 격자에서 모으지 않은 공식 값입니다.</p>
      </section>
      <section className="detail-section current-metric" aria-label="지도 지표를 행정동으로 모은 값">
        <h3>{metric.label} <small className="muted">{current?.kind === 'sum' ? '격자 값 × 겹친 비율의 합' : '겹친 비율 가중 평균'}</small></h3>
        {current && <p className="detail-figure"><Value result={current} metric={metric} /></p>}
        {current && coverageText(current, metric.key) && <p className="muted">{coverageText(current, metric.key)}{current.kind === 'sum' && current.coverage < 0.999 && !COMPLEX_KEYS.has(metric.key) ? ' · 값 없는 격자는 빼고 더했으므로 동 전체 합보다 작을 수 있습니다' : ''}</p>}
      </section>
      <section className="detail-section" aria-label="행정동 격자 지표">
        <h3>격자 지표 모음</h3>
        <dl className="fact-list">
          {KEY_FACTS.map((key) => METRICS.find((m) => m.key === key)).filter((m): m is MetricDef => !!m).map((m) => {
            const result = aggregateMetric(m, grids, shares);
            return <div className={`fact${result.value === null ? ' missing' : ''}`} key={m.key}><dt>{m.label}</dt><dd><Value result={result} metric={m} /></dd>{result.value !== null && <span className="why">{coverageText(result, m.key)}</span>}</div>;
          })}
        </dl>
      </section>
    </>}
    <section className="detail-section" aria-label="읍면동 비교">
      <h3>동별 비교: {metric.label} <small className="muted">{metric.unit}</small></h3>
      <table className="dong-rank">
        <thead><tr><th scope="col">행정동</th><th scope="col">값</th><th scope="col" title="값 있는 격자가 덮는 행정동 면적 비율">덮음</th><th scope="col"><span className="sr-only">막대</span></th></tr></thead>
        <tbody>{ranks.map((r) => <tr key={r.index} className={r.index === index ? 'active' : undefined}>
          <th scope="row"><button type="button" className="link-button" aria-current={r.index === index ? 'true' : undefined} onClick={() => onSelect(r.index)}>{r.name}</button></th>
          <td>{r.result.value === null ? <span className="muted">없음</span> : formatMetric(r.result.value, '', r.result.kind === 'sum' ? 0 : metric.digits)}</td>
          <td className="muted">{r.result.value === null || COMPLEX_KEYS.has(metric.key) ? '' : formatMetric(r.result.coverage * 100, '%', 0)}</td>
          <td className="bar-cell">{r.result.value !== null && top > 0 && <i style={{ width: `${Math.max(2, (r.result.value / top) * 100)}%` }} aria-hidden="true" />}</td>
        </tr>)}</tbody>
      </table>
      <p className="muted">합계 지표는 격자 값을 행정동과 겹친 면적 비율로 나눠 더하고("덮음" = 값 있는 격자가 덮는 동 면적 비율, 낮으면 합계가 작게 나옵니다), 비율·원단위는 겹친 비율(연면적·세대수가 있으면 그것)로 가중 평균합니다. "없음"은 0이 아니라 값 있는 격자가 없다는 뜻입니다. {data.source}</p>
    </section>
  </aside>;
}
