import { BarChart3, ExternalLink, Landmark, ShieldCheck } from 'lucide-react';
import { useMemo } from 'react';
import type { EChartsOption } from 'echarts';
import { Chart } from '../components/Chart';
import { PageHeader } from '../components/PageHeader';
import { QualityBadge } from '../components/QualityBadge';
import { EmptyState, ErrorState, LoadingState } from '../components/Status';
import { useAnalysisScope } from '../hooks/useAnalysisScope';
import { useApi } from '../hooks/useApi';
import { baseChart, compactAxis, SERIES } from '../lib/chartTheme';
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
  // Weather sensitivity: each point is one month (x = heating degree days, y = observed kWh). One axis per measure.
  const sensitivity = useMemo(() => {
    const weather = new Map((data?.weather ?? []).map((row) => [String(row.use_ym), typeof row.hdd === 'number' ? row.hdd : null]));
    const points = (key: 'electricity_kwh' | 'gas_kwh') => (data?.monthly ?? []).flatMap((row) => { const hdd = weather.get(String(row.use_ym)); const value = row[key]; return hdd !== null && hdd !== undefined && typeof value === 'number' ? [[hdd, value, `${Number(String(row.use_ym).slice(-2))}월`]] : []; });
    return { electricity: points('electricity_kwh'), gas: points('gas_kwh') };
  }, [data]);
  const chartOption = useMemo<EChartsOption>(() => baseChart({
    grid: { left: 64, right: 24, top: 44, bottom: 44 },
    tooltip: { trigger: 'item', backgroundColor: 'rgba(255,255,255,.94)', borderColor: 'rgba(14,26,43,.08)', textStyle: { color: '#0e1a2b', fontSize: 12 }, formatter: (p: unknown) => { const item = p as { seriesName: string; value: [number, number, string] }; return `${item.value[2]} · ${item.seriesName}<br/>HDD ${item.value[0].toLocaleString('ko-KR')} °C·일<br/>${Math.round(item.value[1]).toLocaleString('ko-KR')} kWh`; } },
    xAxis: { type: 'value', name: '난방도일 HDD (°C·일)', nameLocation: 'middle', nameGap: 28, nameTextStyle: { color: '#64738a', fontSize: 11 }, splitLine: { lineStyle: { color: 'rgba(14,26,43,.07)' } }, axisLabel: { color: '#64738a', fontSize: 12 } },
    yAxis: { type: 'value', name: 'kWh', nameTextStyle: { color: '#64738a', fontSize: 11 }, splitLine: { lineStyle: { color: 'rgba(14,26,43,.07)' } }, axisLabel: { color: '#64738a', fontSize: 12, formatter: compactAxis } },
    series: [
      { name: '전력', type: 'scatter', symbolSize: 11, data: sensitivity.electricity, itemStyle: { color: SERIES.electricity, borderColor: '#fff', borderWidth: 2 } },
      { name: '가스 (kWh 환산)', type: 'scatter', symbolSize: 11, data: sensitivity.gas, itemStyle: { color: SERIES.gas, borderColor: '#fff', borderWidth: 2 } },
    ],
  }), [sensitivity]);
  const carbonT = typeof data?.electricity_carbon_kg === 'number' ? data.electricity_carbon_kg / 1000 : null;
  if (loading) return <div className="page"><LoadingState /></div>;
  if (error || !data) return <div className="page"><ErrorState message={error} onRetry={reload} /></div>;
  return <div className="page">
    <PageHeader eyebrow="EVIDENCE ANALYSIS" title="관측 데이터 분석" description="월별 관측 흐름과 데이터 출처 품질을 함께 확인해 해석의 범위를 투명하게 유지합니다." action={<QualityBadge value={data.quality} />} />
    <section className="content-grid analysis-summary">
      <article className="panel analysis-lead"><span className="eyebrow">ANNUAL SNAPSHOT · 전력 탄소</span><h2>{carbonT === null ? '자료 없음' : `${formatMetric(carbonT, '', 1)} tCO₂eq`}</h2><p>선택 격자의 관측 전력 × 0.4541 kgCO₂eq/kWh (GIR 2024). 가스 탄소는 배출계수 확정 전이라 합산하지 않습니다.</p><div className="mini-metrics"><div><span>전력 (관측)</span><strong>{formatMetric(data.electricity_kwh, 'kWh')}</strong></div><div><span>가스 (관측, kWh 환산)</span><strong>{formatMetric(data.gas_kwh, 'kWh')}</strong></div><div><span>전력 원단위</span><strong>{formatMetric(data.normalized?.electricity_kwh_per_m2 ?? null, 'kWh/m²·년', 1)}</strong></div><div><span>세대당 전력</span><strong>{formatMetric(data.normalized?.electricity_kwh_per_household ?? null, 'kWh/세대·년')}</strong></div></div></article>
      <article className="panel chart-panel"><div className="panel-title"><div><span>WEATHER SENSITIVITY</span><h3>난방도일과 월별 에너지</h3></div><BarChart3 size={20} /></div>{sensitivity.electricity.length || sensitivity.gas.length ? <><Chart option={chartOption} height={270} ariaLabel="월별 난방도일과 에너지 사용량 산점도" /><p className="muted">점 하나가 한 달입니다. 가스가 오른쪽 위로 모이면 난방 수요에 민감한 것입니다(상관관계이며 인과 추정이 아님).</p></> : <EmptyState description="같은 달의 에너지 관측과 기상(HDD)이 모두 있어야 표시합니다." />}</article>
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
