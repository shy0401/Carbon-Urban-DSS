import { useApi } from '../hooks/useApi';
import { formatMetric } from '../lib/format';
import { LoadingState } from './Status';

/** GET /api/validation: the region's totals next to independent official statistics. */
export interface ValidationYear {
  year: number; hub_gwh: number; hub_months: number; kepco_building_gwh: number | null; kepco_total_gwh: number | null;
  coverage_building: number | null; coverage_total: number | null; monthly_r: number | null; ratio_min: number | null; ratio_max: number | null;
}
export interface ValidationData {
  region: { code: string; name: string; short_name: string };
  electricity: ValidationYear[];
  kapt_vs_hub: { pairs: number; median: number; p10: number; p90: number; within_20pct: number; years?: number[] } | null;
  ghg: {
    gir_year: number; gir_total_kt: number | null; gir_building_direct_kt: number | null; gir_building_electricity_kt: number | null; gir_building_heat_kt: number | null;
    ours_year: number | null; electricity_factor: number | null; gas_factor: number | null; ours_electricity_kt: number | null; ours_gas_kt: number | null;
    electricity_ratio?: number; gas_over_direct_ratio?: number;
  } | null;
  population: { year: number | null; admin: number; grid500: number | null; ratio: number | null; note?: string | null } | null;
  grid_link: { year: number; parcels: number; linked: number; share: number } | null;
  gas_completeness?: { year: number; parcels: number; full: number; bimonthly: number; partial: number; full_gwh: number; bimonthly_gwh: number; partial_gwh: number } | null;
  notes: string[];
}

const pct = (v: number | null | undefined, digits = 0) => (v === null || v === undefined ? '—' : `${formatMetric(v * 100, '', digits)}%`);
const num = (v: number | null | undefined, unit = '', digits = 0) => (v === null || v === undefined ? '—' : formatMetric(v, unit, digits));

/** 공식 통계와 맞대기: 이 도구의 지역 합계를 다른 기관이 센 같은 양과 비교한다 (어느 쪽도 정답으로 보지 않음). */
export function ValidationPanel({ regionQuery }: { regionQuery: string }) {
  const query = regionQuery.replace(/^&/, '?');
  const { data, loading, error } = useApi<ValidationData>(`/validation${query}`);
  if (loading) return <section className="panel validation-panel"><LoadingState label="공식 통계와 맞대는 중입니다" /></section>;
  if (error || !data) return <section className="panel validation-panel"><h3>공식 통계와 맞대기</h3><p className="muted">{error ?? '비교 결과를 불러오지 못했습니다.'}</p></section>;
  const e = data.electricity;
  const k = data.kapt_vs_hub;
  const g = data.ghg;
  const gc = data.gas_completeness;
  return <section className="panel validation-panel" aria-label="공식 통계와 맞대기" data-testid="validation-panel">
    <div className="panel-title"><h3>공식 통계와 맞대기 ({data.region.short_name} 합계)</h3></div>
    <p className="muted">같은 양을 다른 기관이 센 통계와 비교합니다. 어느 한쪽을 정답으로 보지 않고, 차이와 그 까닭(포함 범위)을 함께 봅니다.</p>
    <h4>전력: 건축HUB 지번 합계 ↔ 한전 시군구 건물 전력</h4>
    {e.length ? <div className="table-wrap"><table>
      <thead><tr><th>연도</th><th className="num">건축HUB (GWh)</th><th className="num">한전 건물 (GWh)</th><th className="num">덮음</th><th className="num">월별 상관</th><th className="num">달마다 비율</th><th className="num">한전 합계 (GWh)</th></tr></thead>
      <tbody>{e.map((y) => <tr key={y.year}><td>{y.year}{y.hub_months < 12 ? ` (${y.hub_months}개월)` : ''}</td><td className="num">{num(y.hub_gwh, '', 1)}</td><td className="num">{num(y.kepco_building_gwh, '', 1)}</td>
        <td className="num">{pct(y.coverage_building, 1)}</td><td className="num">{num(y.monthly_r, '', 3)}</td>
        <td className="num">{y.ratio_min === null ? '—' : `${pct(y.ratio_min)}~${pct(y.ratio_max)}`}</td><td className="num">{num(y.kepco_total_gwh, '', 1)}</td></tr>)}</tbody>
    </table></div> : <p className="muted">이 지역에는 아직 건축HUB 지번 에너지가 없습니다. 상세 자료를 모으면 비교합니다.</p>}
    <p className="validation-note">한전 건물 전력은 주택용+일반용+교육용입니다. 건축HUB는 단독주택·소규모 공동주택 등 일부 계약을 지번에 잇지 못해 더 작습니다. 월별 모양이 거의 같고(상관 0.99 이상) 달마다 비율이 일정하면 빠진 몫이 일정하다는 뜻이라, 지역 안 비교에는 쓸 수 있고 총량은 그 비율만큼 작게 나옵니다.</p>
    {k && <><h4>K-apt 관리비 전력 ↔ 건축HUB (같은 단지·같은 해)</h4>
      <p>{formatMetric(k.pairs, '쌍')}: K-apt는 건축HUB의 중앙값 <b>{pct(k.median)}</b> (10~90%: {pct(k.p10)}~{pct(k.p90)}), ±20% 안 {pct(k.within_20pct)}.</p>
      <p className="validation-note">두 출처는 같은 단지라도 세는 범위가 달라 섞지 않습니다. 지역 시뮬레이션의 연도별 전력은 K-apt 한 출처로, 건물 전체 에너지는 건축HUB로 따로 봅니다.</p></>}
    {gc && <><h4>가스 지번의 연간 완전성 ({gc.year})</h4>
      <p>{formatMetric(gc.parcels, '곳')} 중 12개월 {formatMetric(gc.full, '곳')} ({num(gc.full_gwh, 'GWh', 1)}), 여름 격월 고지 <b>{formatMetric(gc.bimonthly, '곳')}</b> ({num(gc.bimonthly_gwh, 'GWh', 1)}), 달이 실제로 빠짐 {formatMetric(gc.partial, '곳')} ({num(gc.partial_gwh, 'GWh', 1)}).</p>
      <p className="validation-note">여름(6~9월)에 한 달을 건너뛰고 다음 달에 두 달 치를 함께 고지하는 지번은 한 해 사용량이 모두 담겨 있어 연간 합계에 넣습니다. 달이 실제로 빠진 지번은 연간 합계에서 뺍니다(0으로 채우지 않음).</p></>}
    {g && <><h4>온실가스: 지역 인벤토리 ↔ 이 도구 계산</h4>
      <dl className="compact-list">
        <div><dt>인벤토리 {g.gir_year}년 건물 등</dt><dd>연료(직접) {num(g.gir_building_direct_kt)} · 전력 {num(g.gir_building_electricity_kt)} · 열 {num(g.gir_building_heat_kt)} 천 tCO₂eq</dd></div>
        <div><dt>이 도구 {g.ours_year ?? '—'}년 (건축HUB 지번)</dt><dd>전력 {num(g.ours_electricity_kt)} (계수 {num(g.electricity_factor, '', 4)}) · 가스 {num(g.ours_gas_kt)} (가정 계수 {num(g.gas_factor, '', 4)}) 천 tCO₂eq</dd></div>
      </dl>
      <p className="validation-note">연도와 범위가 다릅니다. 인벤토리의 '건물 등'에는 농림어업과 석유·LPG가, 전력에는 한전 판매량 전체의 해당 부문이 들어 있습니다. 같은 크기인지만 봅니다{g.electricity_ratio ? ` (전력 ${pct(g.electricity_ratio)})` : ''}.</p></>}
    {(data.population || data.grid_link) && <dl className="compact-list">
      {data.population && <div><dt>인구 {data.population.year ?? ''} (행정 ↔ 500m 격자 합)</dt><dd>{num(data.population.admin, '명')} ↔ {num(data.population.grid500, '명')} ({pct(data.population.ratio, 1)})</dd></div>}
      {data.grid_link && <div><dt>건축HUB 지번의 격자 연결 ({data.grid_link.year})</dt><dd>{num(data.grid_link.linked)} / {num(data.grid_link.parcels)} 지번 ({pct(data.grid_link.share, 1)})</dd></div>}
    </dl>}
    {data.notes.map((n) => <p className="muted" key={n}>{n}</p>)}
  </section>;
}
