import { Activity, Building, CloudSun, Flame, Leaf, Zap } from 'lucide-react';
import { useMemo } from 'react';
import type { EChartsOption } from 'echarts';
import { Chart } from '../components/Chart';
import { EmptyState, ErrorState, LoadingState } from '../components/Status';
import { MetricCard } from '../components/MetricCard';
import { PageHeader } from '../components/PageHeader';
import { QualityBadge } from '../components/QualityBadge';
import { Link } from 'react-router-dom';
import { useAnalysisScope } from '../hooks/useAnalysisScope';
import { useApi } from '../hooks/useApi';
import { formatMetric } from '../lib/format';
import type { DashboardData } from '../types';

export function DashboardPage() {
  const {year,query}=useAnalysisScope();
  const { data, loading, error, reload } = useApi<DashboardData>(`/dashboard?${query}`);
  const chartOption = useMemo<EChartsOption>(() => ({
    color: ['#0f766e', '#f59e0b', '#475569'],
    tooltip: { trigger: 'axis' },
    legend: { top: 0, right: 0, textStyle: { color: '#64748b' } },
    grid: { left: 54, right: 18, top: 44, bottom: 35 },
    xAxis: { type: 'category', data: data?.monthly?.map((row) => row.use_ym) ?? [], axisLine: { lineStyle: { color: '#dbe3e7' } }, axisLabel: { color: '#64748b' } },
    yAxis: { type: 'value', name: 'kWh', nameTextStyle: { color: '#94a3b8' }, splitLine: { lineStyle: { color: '#edf2f4' } }, axisLabel: { color: '#64748b' } },
    series: [
      { name: '전력', type: 'line', smooth: true, symbolSize: 7, connectNulls: false, data: data?.monthly?.map((row) => row.electricity_kwh) ?? [], areaStyle: { opacity: 0.08 } },
      { name: '가스', type: 'line', smooth: true, symbolSize: 7, connectNulls: false, data: data?.monthly?.map((row) => row.gas_kwh) ?? [] },
    ],
  }), [data]);

  if (loading) return <div className="page"><LoadingState /></div>;
  if (error || !data) return <div className="page"><ErrorState message={error} onRetry={reload} /></div>;
  const sector = data.selected_sector;
  return <div className="page">
    <PageHeader eyebrow="CARBON OVERVIEW" title="도시 탄소 대시보드" description="수집된 관측 자료와 출처 범위를 기준으로 전주시 섹터 현황을 확인합니다." action={<div className="header-actions"><span className="period-label">{year}.01 — {year}.12 · 주거</span><QualityBadge value={data.quality} /></div>} />
    <section className="sector-banner">
      <div className="sector-symbol"><Building size={22} /></div>
      <div><span>현재 분석 대상지</span><h2>{sector?.name ?? '선정된 섹터 없음'}</h2><p>{sector?.reason ?? '섹터 선정에 필요한 공간 자료가 없습니다.'}</p></div>
      <dl><div><dt>격자 ID</dt><dd>{sector?.grid_id ?? '—'}</dd></div><div><dt>면적</dt><dd>{formatMetric(sector?.area_m2, 'm²')}</dd></div></dl>
    </section>
    <div className="scope-notice"><span>관측 범위 내 집계 · 에너지원별 12개월 확보 여부를 확인하세요.</span><Link to="/analysis">이 결과의 데이터 →</Link></div><section className="metric-grid">
      <MetricCard title="선택 섹터 전력" value={data.electricity_kwh} unit="kWh" icon={Zap} accent="teal" />
      <MetricCard title="선택 섹터 가스" value={data.gas_kwh} unit="kWh" icon={Flame} accent="orange" />
      <MetricCard title="선택 섹터 탄소" value={data.carbon_kg} unit="kgCO₂eq" icon={Leaf} accent="slate" />
      <MetricCard title="선택 섹터 용적률" value={data.current_far} unit="%" icon={Activity} accent="blue" />
      <MetricCard title="건폐율" value={data.current_bcr} unit="%" icon={Building} />
      <MetricCard title="관측 범위 연면적" value={data.baseline_floor_area_m2} unit="m²" icon={Building} />
      <MetricCard title="세대수" value={data.households} unit="세대" icon={Building} />
      <MetricCard title="인구" value={data.population} unit="명" icon={Activity} />
    </section>
    {data.regional_totals && <section className="regional-strip"><div><span>전주시 전체 수집 합계</span><strong>공간 미매칭 자료 포함</strong></div><dl><div><dt>전력</dt><dd>{formatMetric(data.regional_totals.electricity_kwh, 'kWh')}</dd></div><div><dt>가스</dt><dd>{formatMetric(data.regional_totals.gas_kwh, 'kWh')}</dd></div><div><dt>탄소</dt><dd>{formatMetric(data.regional_totals.carbon_kg, 'kgCO₂eq')}</dd></div></dl></section>}
    <section className="content-grid dashboard-grid">
      <article className="panel chart-panel"><div className="panel-title"><div><span>월별 에너지 흐름</span><h3>관측 에너지 추이</h3></div><small>결측 월은 선을 연결하지 않습니다</small></div>
        {data.monthly?.some(r=>r.electricity_kwh!==null || r.gas_kwh!==null) ? <Chart option={chartOption} ariaLabel="월별 전력 및 가스 사용량 차트" /> : <div className="data-gap"><CloudSun size={34}/><h3>에너지 관측 자료를 기다리고 있습니다</h3><p>등록된 API 키 또는 출처가 확인된 파일이 필요합니다.<br/>공간·기상 자료는 지금 확인할 수 있습니다.</p><Link className="button secondary" to="/data">수집 상태 확인</Link></div>}
      </article>
      <aside className="panel insight-panel"><div className="panel-title"><div><span>DATA COVERAGE</span><h3>데이터 상태</h3></div><CloudSun size={20} /></div>
        <div className="coverage-block"><strong>{data.sources?.length ?? 0}</strong><span>연결된 데이터 출처</span></div>
        <dl className="compact-list">
          {Object.entries(data.coverage ?? {}).slice(0, 5).map(([key, value]) => <div key={key}><dt>{coverageName(key)}</dt><dd>{renderCoverage(value)}</dd></div>)}
          {!Object.keys(data.coverage ?? {}).length && <div><dt>수집 범위</dt><dd>기록 없음</dd></div>}
        </dl>
        <div className="truth-note"><strong>표시 원칙</strong><p>관측이 없는 값은 0으로 채우지 않으며, 추정·대체 자료는 품질 표식으로 구분합니다.</p></div>
      </aside>
    </section>
    <section className="panel weather-panel"><div className="panel-title"><div><span>LOCAL WEATHER</span><h3>월별 기상과 냉난방 수요 조건</h3></div><small>{data.weather?.length ?? 0}/12개월 · 자료 출처의 관측/재분석 구분 확인</small></div>{data.weather?.length ? <Chart height={220} ariaLabel="월평균 기온 차트" option={{color:['#0f766e'],tooltip:{trigger:'axis'},grid:{left:50,right:25,top:30,bottom:25},xAxis:{type:'category',data:data.weather.map(r=>String(r.use_ym).slice(-2)+'월')},yAxis:{type:'value',name:'°C'},series:[{type:'line',name:'평균기온',data:data.weather.map(r=>typeof r.mean_temperature==='number'?r.mean_temperature:null),connectNulls:false}]}}/> : <EmptyState description="이 연도의 기상 자료가 없습니다."/>}</section>
  </div>;
}

function coverageName(key: string) {
  const names: Record<string, string> = { electricity_months: '전력 확보 월', gas_months: '가스 확보 월', total_months: '분석 대상 월', energy_records: '수집 관측 행', matched_records: '공간 매칭 행', observed_months: '관측 월', expected_months: '기대 월', energy: '에너지', weather: '기상', spatial: '공간 자료' };
  return names[key] ?? key.replaceAll('_', ' ');
}

function renderCoverage(value: unknown) {
  if (value === null || value === undefined) return '자료 없음';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}
