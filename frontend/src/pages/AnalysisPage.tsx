import { BarChart3, ExternalLink, Landmark, ShieldCheck } from 'lucide-react';
import { useMemo } from 'react';
import type { EChartsOption } from 'echarts';
import { Chart } from '../components/Chart';
import { PageHeader } from '../components/PageHeader';
import { QualityBadge } from '../components/QualityBadge';
import { EmptyState, ErrorState, LoadingState } from '../components/Status';
import { useAnalysisScope } from '../hooks/useAnalysisScope';
import { useApi } from '../hooks/useApi';
import { formatMetric } from '../lib/format';
import type { DashboardData, OverlayData } from '../types';

const ZONE_LABELS: Record<string, [string, string]> = { RESIDENTIAL: ['주거지역', '#f2c14e'], COMMERCIAL: ['상업지역', '#e4572e'], INDUSTRIAL: ['공업지역', '#8d6cab'], GREEN: ['녹지지역', '#5aa469'], OTHER: ['기타·미분류', '#b8c2c0'], UNKNOWN: ['이름 없음', '#d7dcdb'] };

// SGIS returns full names such as '전북특별자치도 전주시 덕진구 송천1동'; charts show '덕진구 송천1동'.
export function shortAdminName(name: string) { return name.replace(/^.*?전주시\s*/, '').trim() || name; }

export function adminRows(overlays: OverlayData | null) {
  return (overlays?.admin.features ?? []).map((feature) => feature.properties ?? {}).map((p) => ({ name: shortAdminName(String(p.adm_name ?? p.adm_code ?? '')), population: typeof p.population === 'number' ? p.population : null, households: typeof p.households === 'number' ? p.households : null, density: typeof p.population_density === 'number' ? p.population_density : null, status: String(p.population_status ?? '') })).sort((a, b) => (b.population ?? -1) - (a.population ?? -1));
}

export function AnalysisPage() {
  const {query}=useAnalysisScope();
  const { data, loading, error, reload } = useApi<DashboardData>(`/dashboard?${query}`);
  const overlays = useApi<OverlayData>('/map/overlays');
  const admin = useMemo(() => adminRows(overlays.data), [overlays.data]);
  const zoningArea = overlays.data?.meta.zoning_area_km2_by_category ?? {};
  const populationOption = useMemo<EChartsOption>(() => ({
    color: ['#6d4fb3'],
    tooltip: { trigger: 'axis' },
    grid: { left: 90, right: 24, top: 16, bottom: 28 },
    xAxis: { type: 'value', name: '명', splitLine: { lineStyle: { color: '#edf2f4' } } },
    yAxis: { type: 'category', inverse: true, data: admin.map((row) => row.name), axisLabel: { color: '#475569', fontSize: 11 } },
    series: [{ name: '인구', type: 'bar', barMaxWidth: 14, data: admin.map((row) => row.population), itemStyle: { borderRadius: [0, 4, 4, 0] } }],
  }), [admin]);
  const zoningOption = useMemo<EChartsOption>(() => {
    const entries = Object.entries(zoningArea).filter(([, value]) => value > 0);
    return {
      tooltip: { trigger: 'item', formatter: '{b}: {c} km² ({d}%)' },
      series: [{ type: 'pie', radius: ['45%', '72%'], label: { formatter: '{b}\n{c} km²', fontSize: 11 }, data: entries.map(([key, value]) => ({ name: ZONE_LABELS[key]?.[0] ?? key, value, itemStyle: { color: ZONE_LABELS[key]?.[1] ?? '#b8c2c0' } })) }],
    };
  }, [zoningArea]);
  const chartOption = useMemo<EChartsOption>(() => ({
    color: ['#334155', '#0f766e'],
    tooltip: { trigger: 'axis' },
    legend: { right: 12, top: 4 },
    grid: { left: 58, right: 24, top: 44, bottom: 34 },
    xAxis: { type: 'category', data: data?.monthly?.map((row) => row.use_ym) ?? [], axisLabel: { color: '#64748b' } },
    yAxis: [{ type: 'value', name: 'kgCO₂eq', splitLine: { lineStyle: { color: '#edf2f4' } } }, { type: 'value', name: 'kWh' }],
    series: [
      { name: '탄소', type: 'bar', barMaxWidth: 28, data: data?.monthly?.map((row) => row.carbon_kg) ?? [], itemStyle: { borderRadius: [5, 5, 0, 0] } },
      { name: '전력', type: 'line', yAxisIndex: 1, smooth: true, data: data?.monthly?.map((row) => row.electricity_kwh) ?? [] },
    ],
  }), [data]);
  if (loading) return <div className="page"><LoadingState /></div>;
  if (error || !data) return <div className="page"><ErrorState message={error} onRetry={reload} /></div>;
  return <div className="page">
    <PageHeader eyebrow="EVIDENCE ANALYSIS" title="관측 데이터 분석" description="월별 관측 흐름과 데이터 출처 품질을 함께 확인해 해석의 범위를 투명하게 유지합니다." action={<QualityBadge value={data.quality} />} />
    <section className="content-grid analysis-summary">
      <article className="panel analysis-lead"><span className="eyebrow">ANNUAL SNAPSHOT</span><h2>{formatMetric(data.carbon_kg, 'kgCO₂eq')}</h2><p>현재 선택 섹터의 API 집계 탄소 배출량</p><div className="mini-metrics"><div><span>전력</span><strong>{formatMetric(data.electricity_kwh, 'kWh')}</strong></div><div><span>가스</span><strong>{formatMetric(data.gas_kwh, 'kWh')}</strong></div></div></article>
      <article className="panel chart-panel"><div className="panel-title"><div><span>MONTHLY PROFILE</span><h3>에너지와 탄소의 월별 관계</h3></div><BarChart3 size={20} /></div>{data.monthly?.some(r=>r.carbon_kg!==null || r.electricity_kwh!==null) ? <Chart option={chartOption} height={270} ariaLabel="월별 에너지와 탄소 배출량 복합 차트" /> : <EmptyState />}</article>
    </section>
    <section className="content-grid official-context" aria-label="공식 도시 현황">
      <article className="panel chart-panel"><div className="panel-title"><div><span>SGIS {overlays.data?.meta.admin_reference_year ?? ''}</span><h3>행정동 인구</h3></div><Landmark size={20} /></div>{admin.length ? <><Chart option={populationOption} height={Math.max(260, admin.length * 18)} ariaLabel="SGIS 행정동별 인구 막대 차트" /><p className="muted">SGIS 행정구역 통계를 공식 행정동 경계 단위로만 표시합니다. 500m 격자에 배분하지 않으며 비공개(*)·결측은 막대가 없습니다.</p></> : <EmptyState title={overlays.loading ? '확인 중' : 'SGIS 행정동 자료 미수집'} description="수집 데이터 화면에서 SGIS 인구·가구를 LIMITED 이상으로 수집하면 표시됩니다." />}</article>
      <article className="panel chart-panel"><div className="panel-title"><div><span>VWORLD LT_C_UQ111</span><h3>분석 격자 내 용도지역 면적</h3></div><BarChart3 size={20} /></div>{Object.values(zoningArea).some((value) => value > 0) ? <><Chart option={zoningOption} height={270} ariaLabel="분석 격자 내 용도지역 면적 구성 차트" /><p className="muted">VWorld에 실제 요청한 분석 격자 {formatMetric(overlays.data?.meta.zoning_grids_covered ?? 0)}개와 공식 용도지역 도형의 교차 면적 합계입니다(EPSG:5179 계산).</p></> : <EmptyState title={overlays.loading ? '확인 중' : 'VWorld 용도지역 미수집'} description="수집 데이터 화면에서 VWorld 용도지역을 수집하면 표시됩니다." />}</article>
    </section>
    <section className="panel source-panel"><div className="panel-title"><div><span>PROVENANCE</span><h3>분석에 포함된 출처</h3></div><ShieldCheck size={20} /></div>
      {data.sources?.length ? <div className="table-wrap"><table><thead><tr><th>데이터</th><th>기관</th><th>기준 기간</th><th>공간 범위</th><th>품질</th><th>정규화 행</th><th /></tr></thead><tbody>{data.sources.map((source) => <tr key={source.id}><td><strong>{source.name}</strong><small>{source.category}</small></td><td>{source.organization ?? '기록 없음'}</td><td>{source.reference_period ?? '기록 없음'}</td><td>{source.geographic_coverage ?? '기록 없음'}</td><td><QualityBadge value={source.quality} /></td><td>{formatMetric(source.normalized_row_count)}</td><td>{source.source_url && <a className="icon-link" href={source.source_url} target="_blank" rel="noreferrer" aria-label={`${source.name} 원문 열기`}><ExternalLink size={16} /></a>}</td></tr>)}</tbody></table></div> : <EmptyState description="대시보드 API에 연결된 출처가 없습니다." />}
    </section>
  </div>;
}
