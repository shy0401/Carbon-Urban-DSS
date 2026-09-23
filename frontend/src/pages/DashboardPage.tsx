import { Building, Building2, CloudSun, Flame, Gauge, Home, Layers, Leaf, Map as MapIcon, Ruler, Zap } from 'lucide-react';
import { useMemo } from 'react';
import type { EChartsOption } from 'echarts';
import { Link } from 'react-router-dom';
import { Chart } from '../components/Chart';
import { DataClassChip } from '../components/DataClassChip';
import { MetricCard } from '../components/MetricCard';
import { PageHeader } from '../components/PageHeader';
import { QualityBadge } from '../components/QualityBadge';
import { EmptyState, ErrorState, LoadingState } from '../components/Status';
import { useAnalysisScope } from '../hooks/useAnalysisScope';
import { useApi } from '../hooks/useApi';
import { baseChart, compactAxis, lineSeries, SERIES } from '../lib/chartTheme';
import { formatMetric } from '../lib/format';
import { USE_NAME, ZONE_NAME } from '../lib/mapMetrics';
import type { DashboardData } from '../types';

const ZONE_COLORS: Record<string, string> = { RESIDENTIAL: '#f2c14e', COMMERCIAL: '#e4572e', INDUSTRIAL: '#8d6cab', GREEN: '#5aa469', OTHER: '#b8c2c0', UNKNOWN: '#d5dbe3' };

export function DashboardPage() {
  const { year, query } = useAnalysisScope();
  const { data, loading, error, reload } = useApi<DashboardData>(`/dashboard?${query}`);
  const monthly = data?.monthly ?? [];
  const chartOption = useMemo<EChartsOption>(() => baseChart({
    xAxis: { ...(baseChart().xAxis as object), data: monthly.map((row) => `${Number(String(row.use_ym).slice(-2))}월`) },
    yAxis: { ...(baseChart().yAxis as object), name: 'kWh', axisLabel: { color: '#64738a', fontSize: 12, formatter: compactAxis } },
    series: [lineSeries('전력', monthly.map((row) => row.electricity_kwh), SERIES.electricity, true), lineSeries('가스 (kWh 환산)', monthly.map((row) => row.gas_kwh), SERIES.gas)],
  }), [monthly]);

  if (loading) return <div className="page"><LoadingState /></div>;
  if (error || !data) return <div className="page"><ErrorState message={error} onRetry={reload} /></div>;
  const sector = data.selected_sector;
  const coverage = (data.coverage ?? {}) as Record<string, number | undefined>;
  const eMonths = Number(coverage.electricity_months ?? monthly.filter((r) => r.electricity_kwh !== null).length);
  const gMonths = Number(coverage.gas_months ?? monthly.filter((r) => r.gas_kwh !== null).length);
  const norm = data.normalized ?? {};
  const context = data.context;
  const buildings = context?.buildings;
  const zoning = context?.zoning;
  const complexes = context?.complexes;
  const electricityCarbonT = typeof data.electricity_carbon_kg === 'number' ? data.electricity_carbon_kg / 1000 : null;
  const areaIssues = data.floor_area_issues ?? [];
  const admins = (context?.admin ?? []).filter((row) => row.grid_share_pct >= 1);
  return <div className="page">
    <PageHeader title="도시 탄소 대시보드" description="선택 격자의 관측 에너지·전력 탄소와 도시 형태를, 값마다 산식과 근거 범위를 붙여 보여줍니다." action={<div className="header-actions"><span className="period-label">{year}.01 — {year}.12 · 공동주택 관측 범위</span><QualityBadge value={data.quality} /></div>} />
    <section className="sector-banner">
      <div className="sector-symbol"><Building size={24} /></div>
      <div><span>현재 분석 대상지</span><h2>{sector?.name ?? '선정된 섹터 없음'}</h2><p>{sector?.reason ?? '섹터 선정에 필요한 공간 자료가 없습니다.'}</p>
        <div className="hero-facts">
          {zoning && <span><MapIcon size={13} />주거지역 <b>{formatMetric(zoning.residential_pct, '%', 1)}</b></span>}
          {buildings && <span><Building2 size={13} />건물 <b>{formatMetric(buildings.building_count, '동')}</b></span>}
          {complexes && <span><Home size={13} />공동주택 <b>{complexes.count}단지 · {formatMetric(complexes.households, '세대')}</b></span>}
          {admins.slice(0, 3).map((row) => <span key={row.adm_code}>행정동 <b>{row.adm_name.split(' ').at(-1)}</b> {row.grid_share_pct.toFixed(0)}%</span>)}
        </div>
      </div>
      <dl><div><dt>격자 ID</dt><dd>{sector?.grid_id ?? '—'}</dd></div><div><dt>면적</dt><dd>{formatMetric(sector?.area_m2, 'm²')}</dd></div></dl>
    </section>

    <div className="section-label"><h2>에너지 · 탄소</h2><span>관측된 공동주택 지번 기준 · 격자 안 모든 건물의 합이 아닙니다</span></div>
    <section className="metric-grid five">
      <MetricCard title="전력 사용량" dataClass="OBSERVED" value={data.electricity_kwh} unit="kWh" icon={Zap} accent="blue" basis={<>관측 <b>{eMonths}/12개월</b>{eMonths ? ` · 월평균 ${formatMetric((data.electricity_kwh ?? 0) / Math.max(eMonths, 1), 'kWh')}` : ''}</>} />
      <MetricCard title="가스 사용량" dataClass="OBSERVED" value={data.gas_kwh} unit="kWh" icon={Flame} accent="orange" basis={<>관측 <b>{gMonths}/12개월</b> · 건축HUB kWh 환산값</>} />
      <MetricCard title="전력 탄소배출" dataClass="CALCULATED" value={electricityCarbonT} unit="tCO₂eq" digits={1} icon={Leaf} accent="teal" basis={electricityCarbonT !== null ? <>전력 × <b>0.4541</b> kgCO₂eq/kWh (GIR 2024) · 가스 탄소는 계수 확정 전</> : '전력 관측이 없어 계산하지 않음'} />
      <MetricCard title="전력 원단위" dataClass="CALCULATED" value={norm.electricity_kwh_per_m2 ?? null} unit="kWh/m²·년" digits={1} icon={Gauge} accent="blue" basis={norm.electricity_kwh_per_m2 != null ? <>지번 <b>{norm.electricity_area_parcels}곳</b> · 연면적 {formatMetric(norm.electricity_matched_floor_area_m2, 'm²')}{areaIssues.length ? ` · 연면적 이상 ${areaIssues.length}곳 제외` : ''}</> : '12개월 관측 + 연면적이 확인된 지번이 없음'} />
      <MetricCard title="세대당 전력" dataClass="CALCULATED" value={norm.electricity_kwh_per_household ?? null} unit="kWh/세대·년" icon={Home} accent="violet" basis={norm.electricity_kwh_per_household != null ? <>{formatMetric(norm.electricity_households, '세대')} 기준 · 월 <b>{formatMetric((norm.electricity_kwh_per_household ?? 0) / 12, 'kWh')}</b></> : '세대수가 확인된 12개월 관측 지번이 없음'} />
    </section>

    <div className="section-label"><h2>도시 형태 · 토지이용</h2><span>격자 250,000m² 기준 · 법정 건폐율·용적률(대지면적 기준)과 다릅니다</span></div>
    <section className="metric-grid">
      <MetricCard title="건물 수" dataClass="OBSERVED" value={buildings?.building_count ?? null} unit="동" icon={Building2} accent="slate" basis={buildings ? <>공식 도로명주소 건물 · 층수 확인 <b>{formatMetric(buildings.floors_known_pct, '%')}</b></> : '공식 건물 레이어(VWorld) 수집 전'} />
      <MetricCard title="건폐율 근사" dataClass="CALCULATED" value={buildings?.coverage_pct ?? null} unit="%" digits={1} icon={Layers} accent="teal" ratio={buildings?.coverage_pct} basis={buildings ? <>건축면적 <b>{formatMetric(buildings.footprint_m2, 'm²')}</b> ÷ 250,000 m²</> : '건물 윤곽이 있어야 계산'} />
      <MetricCard title="추정 용적률" dataClass="ESTIMATED" value={buildings?.far_est_pct ?? null} unit="%" digits={1} icon={Ruler} accent="orange" basis={buildings?.far_est_pct != null ? <>Σ건축면적×층수 <b>{formatMetric(buildings.floor_area_est_m2, 'm²')}</b> ÷ 250,000 m²</> : '층수가 있는 건물이 있어야 추정'} />
      <MetricCard title="주거지역 비율" dataClass="CALCULATED" value={zoning?.residential_pct ?? null} unit="%" digits={1} icon={MapIcon} accent="blue" ratio={zoning?.residential_pct} basis={zoning ? Object.entries(zoning.shares_pct).sort((a, b) => b[1] - a[1]).map(([k, v]) => `${ZONE_NAME[k] ?? k} ${v.toFixed(1)}%`).join(' · ') || '도시지역 용도지역 없음' : '용도지역(VWorld) 미수집'} />
    </section>

    {data.regional_totals && <section className="regional-strip"><div><span>전주시 전체 수집 합계</span><strong>공간 미매칭 자료 포함 · 전주시 전체 소비량이 아님</strong></div><dl><div><dt>전력</dt><dd>{formatMetric(data.regional_totals.electricity_kwh, 'kWh')}</dd></div><div><dt>가스</dt><dd>{formatMetric(data.regional_totals.gas_kwh, 'kWh')}</dd></div><div><dt>탄소 (전력+가스)</dt><dd>{formatMetric(data.regional_totals.carbon_kg, 'kgCO₂eq')}</dd></div></dl></section>}

    <div className="scope-notice"><span>시뮬레이션 기준: {data.baseline_scope ? `${data.baseline_scope.parcel_names.join(', ')} (연면적 ${formatMetric(data.baseline_scope.area_m2, 'm²')}, ${data.baseline_scope.energy_types.map((t) => (t === 'GAS' ? '가스' : '전력')).join('·')} 12개월)${data.baseline_scope.excluded_names.length ? ` · 제외: ${data.baseline_scope.excluded_names.join(', ')}` : ''}` : '12개월 관측과 연면적이 모두 있는 지번이 없어 기준을 만들지 않았습니다.'}</span><Link to="/analysis">이 결과의 데이터 →</Link></div>
    <section className="content-grid dashboard-grid">
      <article className="panel chart-panel"><div className="panel-title"><div><span>MONTHLY ENERGY</span><h3>월별 관측 에너지</h3></div><small>결측 월은 선을 잇지 않습니다 · 단위 kWh</small></div>
        {monthly.some((r) => r.electricity_kwh !== null || r.gas_kwh !== null) ? <Chart option={chartOption} height={300} ariaLabel="월별 전력 및 가스 사용량 차트" /> : <div className="data-gap"><CloudSun size={34} /><h3>에너지 관측 자료를 기다리고 있습니다</h3><p>이 격자에는 아직 월별 관측이 없습니다. 0으로 채우지 않습니다.</p><Link className="button secondary" to="/data">수집 상태 확인</Link></div>}
      </article>
      <aside className="panel insight-panel"><div className="panel-title"><div><span>DATA COVERAGE</span><h3>관측 범위</h3></div><CloudSun size={20} /></div>
        <div className="coverage-block"><strong>{Math.round(((eMonths + gMonths) / 24) * 100)}%</strong><span>전력·가스 24개월 중 관측 {eMonths + gMonths}개월</span></div>
        <div style={{ display: 'grid', gap: 6 }}>
          <MonthRow label="전력" months={monthly.map((r) => r.electricity_kwh !== null)} />
          <MonthRow label="가스" months={monthly.map((r) => r.gas_kwh !== null)} />
        </div>
        <dl className="compact-list" style={{ marginTop: 10 }}>
          <div><dt>수집 관측 행 (연도 전체)</dt><dd>{formatMetric(coverage.energy_records, '행')}</dd></div>
          <div><dt>격자에 공간 매칭된 행</dt><dd>{formatMetric(coverage.matched_records, '행')}{coverage.energy_records ? ` (${Math.round(((coverage.matched_records ?? 0) / coverage.energy_records) * 100)}%)` : ''}</dd></div>
          <div><dt>연결된 데이터 출처</dt><dd>{data.sources?.length ?? 0}개</dd></div>
        </dl>
        <div className="truth-note"><strong>표시 원칙</strong><p>관측이 없는 값은 0으로 채우지 않습니다. 모든 수치에 관측·계산·추정 표식과 산식을 붙이고, 공표 연면적이 비현실적이면 원단위 분모에서 뺍니다.</p></div>
      </aside>
    </section>
    {buildings && Object.keys(buildings.category_share_pct ?? {}).length > 0 && <section className="panel weather-panel"><div className="panel-title"><div><span>BUILDING USE</span><h3>건축면적 기준 건물 용도 구성</h3></div><DataClassChip value="CALCULATED" /></div><StackRow shares={buildings.category_share_pct} names={USE_NAME} colors={{ RESIDENTIAL: '#f2b705', COMMERCIAL: '#e4572e', INDUSTRIAL: '#8d6cab', PUBLIC: '#2a78d6', OTHER: '#64748b', UNKNOWN: '#b8c2c0' }} counts={buildings.category_count} /></section>}
    {zoning && Object.keys(zoning.shares_pct).length > 0 && <section className="panel weather-panel"><div className="panel-title"><div><span>ZONING</span><h3>격자 면적 중 법정 용도지역</h3></div><DataClassChip value="CALCULATED" /></div><StackRow shares={zoning.shares_pct} names={ZONE_NAME} colors={ZONE_COLORS} rest="도시지역 외·미지정" /></section>}
    <WeatherPanel data={data} />
  </div>;
}

function MonthRow({ label, months }: { label: string; months: boolean[] }) {
  const count = months.filter(Boolean).length;
  return <div className="month-strip-row"><span>{label}</span><div className="month-strip" aria-label={`${label} 관측 ${count}/12개월`}>{Array.from({ length: 12 }, (_, i) => <span key={i} className={months[i] ? 'on' : ''}>{i + 1}</span>)}</div><b>{count}/12</b></div>;
}

function StackRow({ shares, names, colors, counts, rest }: { shares: Record<string, number>; names: Record<string, string>; colors: Record<string, string>; counts?: Record<string, number>; rest?: string }) {
  const entries = Object.entries(shares).sort((a, b) => b[1] - a[1]);
  const remainder = rest ? Math.max(0, 100 - entries.reduce((s, [, v]) => s + v, 0)) : 0;
  return <div style={{ marginTop: 14 }}><div className="stack-bar" style={{ height: 16 }} role="img" aria-label={entries.map(([k, v]) => `${names[k] ?? k} ${v.toFixed(1)}%`).join(', ')}>{entries.map(([k, v]) => <span key={k} style={{ width: `${v}%`, background: colors[k] ?? '#b8c2c0' }} />)}{remainder > 0.05 && <span style={{ width: `${remainder}%`, background: 'rgba(14,26,43,.08)' }} />}</div><div className="stack-legend">{entries.map(([k, v]) => <span key={k}><i style={{ background: colors[k] ?? '#b8c2c0' }} />{names[k] ?? k} <b>{v.toFixed(1)}%</b>{counts?.[k] !== undefined && <>({counts[k].toLocaleString('ko-KR')}동)</>}</span>)}{remainder > 0.05 && <span><i style={{ background: 'rgba(14,26,43,.12)' }} />{rest} <b>{remainder.toFixed(1)}%</b></span>}</div></div>;
}

function WeatherPanel({ data }: { data: DashboardData }) {
  const rows = data.weather ?? [];
  const provider = String(rows[0]?.provider ?? rows[0]?.source ?? '');
  const official = rows.filter((r) => String(r.source_type ?? '') === 'OFFICIAL').length;
  const option = useMemo<EChartsOption>(() => baseChart({
    grid: { left: 48, right: 20, top: 40, bottom: 28 },
    xAxis: { ...(baseChart().xAxis as object), data: rows.map((r) => `${Number(String(r.use_ym).slice(-2))}월`) },
    yAxis: { ...(baseChart().yAxis as object), name: '°C' },
    series: [lineSeries('월평균 기온', rows.map((r) => (typeof r.mean_temperature === 'number' ? Number(r.mean_temperature.toFixed(1)) : null)), SERIES.temperature)],
  }), [rows]);
  const hdd = rows.reduce((s, r) => s + (typeof r.hdd === 'number' ? r.hdd : 0), 0);
  const cdd = rows.reduce((s, r) => s + (typeof r.cdd === 'number' ? r.cdd : 0), 0);
  return <section className="panel weather-panel"><div className="panel-title"><div><span>LOCAL WEATHER</span><h3>월별 기상과 냉난방 수요 조건</h3></div><DataClassChip value={rows.length ? (official === rows.length ? 'OBSERVED' : 'FALLBACK') : 'MISSING'} /></div>
    {rows.length ? <><Chart height={230} ariaLabel="월평균 기온 차트" option={option} /><div className="chart-note"><span>자료: <b>{official === rows.length ? 'KMA ASOS 전주(146) 관측' : official ? `KMA ASOS ${official}개월 + ERA5-Land 대체 ${rows.length - official}개월` : provider || 'ERA5-Land 재분석(대체)'}</b></span><span>{rows.length}/12개월</span><span>난방도일 HDD <b>{formatMetric(hdd, '°C·일')}</b></span><span>냉방도일 CDD <b>{formatMetric(cdd, '°C·일')}</b></span><span>기준온도 18°C</span></div></> : <EmptyState description="이 연도의 기상 자료가 없습니다." />}
  </section>;
}
