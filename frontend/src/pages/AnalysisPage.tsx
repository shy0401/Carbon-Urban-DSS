import { BarChart3, ExternalLink, ShieldCheck } from 'lucide-react';
import { useMemo } from 'react';
import type { EChartsOption } from 'echarts';
import { Chart } from '../components/Chart';
import { PageHeader } from '../components/PageHeader';
import { QualityBadge } from '../components/QualityBadge';
import { EmptyState, ErrorState, LoadingState } from '../components/Status';
import { useAnalysisScope } from '../hooks/useAnalysisScope';
import { useApi } from '../hooks/useApi';
import { formatMetric } from '../lib/format';
import type { DashboardData } from '../types';

export function AnalysisPage() {
  const {query}=useAnalysisScope();
  const { data, loading, error, reload } = useApi<DashboardData>(`/dashboard?${query}`);
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
    <section className="panel source-panel"><div className="panel-title"><div><span>PROVENANCE</span><h3>분석에 포함된 출처</h3></div><ShieldCheck size={20} /></div>
      {data.sources?.length ? <div className="table-wrap"><table><thead><tr><th>데이터</th><th>기관</th><th>기준 기간</th><th>공간 범위</th><th>품질</th><th>정규화 행</th><th /></tr></thead><tbody>{data.sources.map((source) => <tr key={source.id}><td><strong>{source.name}</strong><small>{source.category}</small></td><td>{source.organization ?? '기록 없음'}</td><td>{source.reference_period ?? '기록 없음'}</td><td>{source.geographic_coverage ?? '기록 없음'}</td><td><QualityBadge value={source.quality} /></td><td>{formatMetric(source.normalized_row_count)}</td><td>{source.source_url && <a className="icon-link" href={source.source_url} target="_blank" rel="noreferrer" aria-label={`${source.name} 원문 열기`}><ExternalLink size={16} /></a>}</td></tr>)}</tbody></table></div> : <EmptyState description="대시보드 API에 연결된 출처가 없습니다." />}
    </section>
  </div>;
}
