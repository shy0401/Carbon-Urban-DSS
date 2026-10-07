import { useMemo } from 'react';
import type { EChartsOption } from 'echarts';
import { Link } from 'react-router-dom';
import { Chart } from '../components/Chart';
import { MetricCard } from '../components/MetricCard';
import { MissingValue } from '../components/MissingValue';
import { PageHeader } from '../components/PageHeader';
import { ProvenanceBadge } from '../components/ProvenanceBadge';
import { QualityBadge } from '../components/QualityBadge';
import { SgisGridSummaryView } from '../components/SgisGridPanel';
import { ShareBar } from '../components/ShareBar';
import { EmptyState, ErrorState, LoadingState } from '../components/Status';
import { WeatherChart } from '../components/WeatherChart';
import { useAnalysisScope } from '../hooks/useAnalysisScope';
import { useApi } from '../hooks/useApi';
import { baseChart, compactAxis, lineSeries, missingBands, MONTH_LABELS, monthsOf, SERIES } from '../lib/chartTheme';
import { formatMetric } from '../lib/format';
import { USE_COLORS, USE_NAME, ZONE_NAME } from '../lib/labels';
import { PROVENANCE, provenanceFromCode, provenanceFromWeatherSource } from '../lib/provenance';
import { ZONE_GROUP_COLOR } from '../theme/palette';
import type { DashboardData } from '../types';

export function DashboardPage() {
  const { year, query } = useAnalysisScope();
  const { data, loading, error, reload } = useApi<DashboardData>(`/dashboard?${query}`);
  const monthly = data?.monthly ?? [];
  const regionName = data?.region?.short_name ?? '전주시';
  // 근거 배지는 서버 필드만 쓴다: observations_label = 'OBSERVED' (월별 관측 에너지).
  const observed = provenanceFromCode(data?.observations_label);
  const chartOption = useMemo<EChartsOption>(() => {
    const electricity = monthsOf(year, monthly, 'electricity_kwh');
    const gas = monthsOf(year, monthly, 'gas_kwh');
    const base = baseChart();
    const label = observed ? ` (${PROVENANCE[observed].label})` : '';
    return baseChart({
      tooltip: { ...(base.tooltip as object), valueFormatter: (value: unknown) => (typeof value === 'number' ? `${formatMetric(value, 'kWh')}${label}` : '자료 없음') },
      xAxis: { ...(base.xAxis as object), data: MONTH_LABELS },
      yAxis: { ...(base.yAxis as object), name: 'kWh', axisLabel: { ...((base.yAxis as { axisLabel?: object }).axisLabel ?? {}), formatter: compactAxis } },
      series: [{ ...lineSeries('전력', electricity, SERIES.electricity), markArea: missingBands(MONTH_LABELS, [electricity, gas]) }, lineSeries('가스 (kWh 환산)', gas, SERIES.gas)],
    });
  }, [monthly, year, observed]);

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
  const complete = data.annual_complete ?? { electricity: false, gas: false };
  const hasEnergy = monthly.some((r) => r.electricity_kwh !== null || r.gas_kwh !== null);
  return <div className="page dashboard-page">
    <PageHeader title="도시 탄소 대시보드" description="선택 격자의 관측 에너지와 전력 탄소, 도시 형태를 값마다 산식과 근거 범위를 붙여 보여줍니다." action={<div className="header-actions"><span className="status-tag">{year}년 1–12월 공동주택 관측 범위</span><QualityBadge value={data.quality} /></div>} />

    <section className="panel site-summary" aria-label="현재 분석 대상지">
      <div className="site-name"><h2>{sector?.name ?? '선정된 섹터 없음'}</h2><p>{sector?.reason ?? '섹터 선정에 필요한 공간 자료가 없습니다.'}</p></div>
      <dl className="site-facts">
        <div><dt>격자 ID</dt><dd><code>{sector?.grid_id ?? '—'}</code></dd></div>
        <div><dt>면적</dt><dd>{formatMetric(sector?.area_m2, 'm²')}</dd></div>
        <div><dt>건물 수</dt><dd>{buildings ? formatMetric(buildings.building_count, '동') : <MissingValue inline reason="VWorld 건물 미수집" />}</dd></div>
        <div><dt>공동주택</dt><dd>{complexes ? `${complexes.count}단지, ${formatMetric(complexes.households, '세대')}` : <MissingValue inline />}</dd></div>
        <div><dt>행정동 (격자 면적 비율)</dt><dd>{admins.length ? admins.slice(0, 3).map((row) => `${row.adm_name.split(' ').at(-1)} ${row.grid_share_pct.toFixed(0)}%`).join(', ') : <MissingValue inline />}</dd></div>
      </dl>
    </section>

    <div className="section-label"><h2>핵심 지표</h2><span>에너지·탄소는 관측된 공동주택 지번 기준이며 격자 안 모든 건물의 합이 아닙니다. 도시 형태는 격자 250,000m² 기준으로 법정 건폐율·용적률(대지면적 기준)과 다릅니다.</span></div>
    <section className="metric-grid" aria-label="핵심 지표 8개">
      <MetricCard title="전력 사용량" provenance={observed} value={data.electricity_kwh} unit="kWh" basis={<>{complete.electricity ? '완전 연간 값' : '관측 기간 합계'} <b>{eMonths}/12개월</b>{eMonths ? `, 월평균 ${formatMetric((data.electricity_kwh ?? 0) / Math.max(eMonths, 1), 'kWh')}` : ''}</>} missingReason="이 격자·연도에 월별 전력 관측이 없습니다." />
      <MetricCard title="가스 사용량" provenance={observed} value={data.gas_kwh} unit="kWh" basis={<>{complete.gas ? '완전 연간 값' : '관측 기간 합계'} <b>{gMonths}/12개월</b>, 건축HUB kWh 환산값</>} missingReason="이 격자·연도에 월별 가스 관측이 없습니다." />
      <MetricCard title="전력 탄소배출" value={electricityCarbonT} unit="tCO₂eq" digits={1} basis={<>전력 × <b>{data.carbon_factors?.ELECTRICITY?.factor ?? '—'}</b> kgCO₂eq/kWh ({data.carbon_factors?.ELECTRICITY?.source ?? 'GIR 승인 계수'}). {typeof data.gas_carbon_kg === 'number' ? <>가스 탄소 <b>{formatMetric(data.gas_carbon_kg / 1000, 'tCO₂eq', 1)}</b>는 가정 계수 {data.carbon_factors?.GAS?.factor ?? 0.1826}로 따로 계산</> : '가스 탄소는 가스 관측이 없어 제외'}</>} missingReason="전력 관측이 없어 계산하지 않았습니다." />
      <MetricCard title="전력 원단위" value={norm.electricity_kwh_per_m2 ?? null} unit="kWh/m²·년" digits={1} basis={<>지번 <b>{norm.electricity_area_parcels}곳</b>, 연면적 {formatMetric(norm.electricity_matched_floor_area_m2, 'm²')}{areaIssues.length ? `, 연면적 이상 ${areaIssues.length}곳 제외` : ''}</>} missingReason="12개월 관측과 연면적이 모두 확인된 지번이 없습니다." />
      <MetricCard title="세대당 전력" value={norm.electricity_kwh_per_household ?? null} unit="kWh/세대·년" basis={<>{formatMetric(norm.electricity_households, '세대')} 기준, 월 <b>{formatMetric((norm.electricity_kwh_per_household ?? 0) / 12, 'kWh')}</b></>} missingReason="세대수가 확인된 12개월 관측 지번이 없습니다." />
      <MetricCard title="건폐율 근사" value={buildings?.coverage_pct ?? null} unit="%" digits={1} ratio={buildings?.coverage_pct} basis={<>건축면적 <b>{formatMetric(buildings?.footprint_m2, 'm²')}</b> ÷ 250,000 m²</>} missingReason="건물 윤곽이 있어야 계산합니다." />
      <MetricCard title="추정 용적률" value={buildings?.far_est_pct ?? null} unit="%" digits={1} basis={<>Σ건축면적×층수 <b>{formatMetric(buildings?.floor_area_est_m2, 'm²')}</b> ÷ 250,000 m², 층수 확인 {formatMetric(buildings?.floors_known_pct, '%')}</>} missingReason="층수가 기록된 건물이 있어야 추정합니다." />
      <MetricCard title="주거지역 비율" value={zoning?.residential_pct ?? null} unit="%" digits={1} ratio={zoning?.residential_pct} basis={zoning ? Object.entries(zoning.shares_pct).sort((a, b) => b[1] - a[1]).map(([k, v]) => `${ZONE_NAME[k] ?? k} ${v.toFixed(1)}%`).join(', ') || '도시지역 용도지역 없음' : undefined} missingReason="용도지역(VWorld)을 아직 수집하지 않았습니다." />
    </section>

    {data.regional_totals && <section className="panel regional-totals" aria-label={`${regionName} 전체 수집 합계`}><div><h3>{regionName} 전체 수집 합계</h3><p className="caveat">공간 미매칭 자료를 포함한 수집 합계이며 {regionName} 전체 소비량이 아닙니다.</p></div><dl><div><dt>전력</dt><dd>{formatMetric(data.regional_totals.electricity_kwh, 'kWh')}</dd></div><div><dt>가스</dt><dd>{formatMetric(data.regional_totals.gas_kwh, 'kWh')}</dd></div><div><dt>탄소 (전력+가스{data.carbon_factors?.GAS?.assumed ? ', 가스는 가정 계수' : ''})</dt><dd>{data.regional_totals.carbon_kg === null ? <MissingValue inline reason="전력 또는 가스 계수·관측이 빠진 달이 있음" /> : formatMetric(data.regional_totals.carbon_kg, 'kgCO₂eq')}</dd></div></dl></section>}

    <p className="scope-notice"><span>시뮬레이션 기준: {data.baseline_scope ? `${data.baseline_scope.parcel_names.join(', ')} (연면적 ${formatMetric(data.baseline_scope.area_m2, 'm²')}, ${data.baseline_scope.energy_types.map((t) => (t === 'GAS' ? '가스' : '전력')).join('·')} 12개월)${data.baseline_scope.excluded_names.length ? `. 제외: ${data.baseline_scope.excluded_names.join(', ')}` : ''}` : '12개월 관측과 연면적이 모두 있는 지번이 없어 기준을 만들지 않았습니다.'}</span><Link to="/analysis">이 결과의 데이터 보기</Link></p>
    <section className="content-grid dashboard-grid">
      <article className="panel chart-panel"><div className="panel-title"><h3>월별 관측 에너지</h3><div className="badge-row">{observed && <ProvenanceBadge kind={observed} />}<small>결측 월은 선을 잇지 않습니다. 단위 kWh</small></div></div>
        {hasEnergy ? <Chart option={chartOption} height={300} ariaLabel="월별 전력 및 가스 사용량 차트" /> : <div className="empty-block is-missing"><strong>월별 에너지 관측이 없어 운영탄소를 계산하지 않았습니다.</strong><dl><div><dt>관측 월</dt><dd>0 / 필요 1 이상</dd></div></dl><Link className="button secondary" to="/data">수집 상태 보기</Link></div>}
      </article>
      <aside className="panel coverage-panel"><div className="panel-title"><h3>관측 범위</h3></div>
        <p className="coverage-figure"><b>{eMonths + gMonths}</b><span className="unit">/ 24개월</span><small>전력·가스 관측 월 ({formatMetric(((eMonths + gMonths) / 24) * 100, '%', 0)})</small></p>
        <MonthRow label="전력" months={Array.from({ length: 12 }, (_, i) => monthsOf(year, monthly, 'electricity_kwh')[i] !== null)} />
        <MonthRow label="가스" months={Array.from({ length: 12 }, (_, i) => monthsOf(year, monthly, 'gas_kwh')[i] !== null)} />
        <dl className="compact-list">
          <div><dt>수집 관측 행 (연도 전체)</dt><dd>{formatMetric(coverage.energy_records, '행')}</dd></div>
          <div><dt>격자에 공간 매칭된 행</dt><dd>{formatMetric(coverage.matched_records, '행')}{coverage.energy_records ? ` (${Math.round(((coverage.matched_records ?? 0) / coverage.energy_records) * 100)}%)` : ''}</dd></div>
          <div><dt>연결된 데이터 출처</dt><dd>{data.sources?.length ?? 0}개</dd></div>
        </dl>
        <div className="truth-note"><strong>표시 원칙</strong><p>관측이 없는 값은 0으로 채우지 않습니다. 근거 유형은 서버가 알려준 값에만 표시하고, 공표 연면적이 비현실적이면 원단위 분모에서 뺍니다.</p></div>
      </aside>
    </section>
    <section className="content-grid two-up">
      <article className="panel"><div className="panel-title"><h3>건축면적 기준 건물 용도 구성</h3></div>{buildings && Object.keys(buildings.category_share_pct ?? {}).length > 0 ? <ShareBar shares={buildings.category_share_pct} names={USE_NAME} colors={Object.fromEntries(USE_COLORS)} counts={buildings.category_count} /> : <MissingValue reason="공식 건물 레이어(VWorld)를 아직 수집하지 않았습니다." />}</article>
      <article className="panel"><div className="panel-title"><h3>격자 면적 중 법정 용도지역</h3></div>{zoning && Object.keys(zoning.shares_pct).length > 0 ? <ShareBar shares={zoning.shares_pct} names={ZONE_NAME} colors={ZONE_GROUP_COLOR} rest="도시지역 외·미지정" /> : <MissingValue reason={zoning ? '이 격자에 도시지역 용도지역 도형이 없습니다.' : '용도지역(VWorld)을 아직 수집하지 않았습니다.'} />}</article>
    </section>
    <BuildingEnergyPanel data={data} />
    <SgisPanel context={context} />
    <WeatherPanel data={data} year={year} />
  </div>;
}

function BuildingEnergyPanel({ data }: { data: DashboardData }) {
  const b = data.building_energy;
  return <section className="panel sgis-panel" aria-label="건물 전체 에너지 (건축HUB 전 지번)">
    <div className="panel-title"><h3>건물 전체 에너지 (건축HUB 전 지번{b ? `, ${b.year}년` : ''})</h3><div className="badge-row">{b?.complete === false && <span className="status-tag warn">수집 중 · 일부 법정동</span>}<ProvenanceBadge kind="observed" detail="12개월 계측 지번" /></div></div>
    {!b ? <MissingValue reason="이 격자에는 건축HUB 계측 지번이 없거나 전 지번 수집이 아직 끝나지 않았습니다(건축HUB는 2024년부터 제공)." /> : <>
      <dl className="sgis-figures">
        <div><dt>계측 지번</dt><dd>{formatMetric(b.bldg_parcels as number | null, '곳')}<small>12개월 전력 {formatMetric(b.bldg_electricity_complete as number | null, '곳')}</small></dd></div>
        <div className={b.bldg_electricity_kwh == null ? 'is-missing' : undefined}><dt>연간 전력</dt><dd>{b.bldg_electricity_kwh == null ? <MissingValue inline reason="12개월 계측 지번 없음" /> : formatMetric(b.bldg_electricity_kwh as number, 'kWh')}</dd></div>
        <div className={b.bldg_gas_kwh == null ? 'is-missing' : undefined}><dt>연간 가스</dt><dd>{b.bldg_gas_kwh == null ? <MissingValue inline reason="12개월 계측 지번 없음" /> : formatMetric(b.bldg_gas_kwh as number, 'kWh')}</dd></div>
        <div className={b.bldg_kwh_per_m2 == null ? 'is-missing' : undefined}><dt>전력 원단위 (대장 연면적)</dt><dd>{b.bldg_kwh_per_m2 == null ? <MissingValue inline reason="연면적 있는 지번 없음" /> : formatMetric(b.bldg_kwh_per_m2 as number, 'kWh/m²·년', 1)}</dd></div>
        <div className={b.bldg_carbon_t == null ? 'is-missing' : undefined}><dt>전력 탄소</dt><dd>{b.bldg_carbon_t == null ? <MissingValue inline /> : formatMetric(b.bldg_carbon_t as number, 'tCO₂eq', 1)}</dd></div>
      </dl>
      <p className="muted">격자 안 상가·업무·학교·대형 공동주택 등 건축HUB가 계측하는 모든 지번의 합계입니다(위 핵심 지표는 공동주택 단지만). 단독주택, 200세대 미만 공동주택, 산업·수송용은 제공 범위 밖입니다.</p>
    </>}
  </section>;
}

function SgisPanel({ context }: { context: DashboardData['context'] }) {
  const cell = context?.sgis_grid;
  return <section className="panel sgis-panel" aria-label="인구·주택 (SGIS 1km 격자)">
    <div className="panel-title"><h3>인구·주택 (SGIS 1km 격자{cell ? ` ${cell.year}년` : ''})</h3><div className="badge-row"><ProvenanceBadge kind="observed" detail="공공데이터포털 격자 통계" /></div></div>
    {!cell ? <MissingValue reason="SGIS 격자 통계를 아직 가져오지 않았습니다. 사용 방법 화면의 'SGIS 격자 통계' 절차를 따라 주세요." />
      : cell.status === 'NO_STAT' ? <MissingValue reason={`이 격자가 속한 1km 격자(${cell.code})에는 공표된 통계가 없습니다. 인구·사업체가 없거나 비공개인 격자이며 0이 아닙니다.`} />
      : <SgisGridSummaryView summary={cell} scope={<>이 500m 격자가 속한 1km 공식 격자 <code>{cell.code}</code> 전체 값입니다(면적 1km², 이 격자의 4배). 500m로 나누지 않았습니다.</>} />}
  </section>;
}

function MonthRow({ label, months }: { label: string; months: boolean[] }) {
  const count = months.filter(Boolean).length;
  return <div className="month-strip-row"><span>{label}</span><div className="month-strip" aria-label={`${label} 관측 ${count}/12개월`}>{months.map((on, i) => <span key={i} className={on ? 'on' : 'is-missing'} title={`${i + 1}월 ${on ? '관측' : '관측 없음'}`}>{i + 1}</span>)}</div><b>{count}/12</b></div>;
}

function WeatherPanel({ data, year }: { data: DashboardData; year: number }) {
  const rows = data.weather ?? [];
  const provider = String(rows[0]?.provider ?? rows[0]?.source ?? '');
  const official = rows.filter((r) => provenanceFromWeatherSource(r.source_type) === 'observed').length;
  const fallback = rows.filter((r) => provenanceFromWeatherSource(r.source_type) === 'fallback').length;
  // HDD·CDD 합계는 값이 있는 달만 더하고, 몇 개월 합계인지 함께 적는다(결측 월을 0으로 더하지 않음).
  const hddRows = rows.filter((r) => typeof r.hdd === 'number');
  const cddRows = rows.filter((r) => typeof r.cdd === 'number');
  const hdd = hddRows.reduce((s, r) => s + (r.hdd as number), 0);
  const cdd = cddRows.reduce((s, r) => s + (r.cdd as number), 0);
  return <section className="panel weather-panel"><div className="panel-title"><h3>월별 기상과 냉난방 수요 조건</h3><div className="badge-row">{official > 0 && <ProvenanceBadge kind="observed" detail={`${official}개월`} />}{fallback > 0 && <ProvenanceBadge kind="fallback" detail={`${fallback}개월`} />}{!rows.length && <ProvenanceBadge kind="missing" />}</div></div>
    {rows.length ? <><WeatherChart year={year} rows={rows} /><dl className="chart-note"><div><dt>자료</dt><dd>{official === rows.length ? 'KMA ASOS 전주(146) 관측' : official ? `KMA ASOS ${official}개월, ERA5-Land 대체 ${rows.length - official}개월` : provider || 'ERA5-Land 재분석(대체)'}</dd></div><div><dt>기온 관측 월</dt><dd>{rows.length}/12개월</dd></div><div><dt>난방도일 HDD</dt><dd>{hddRows.length ? formatMetric(hdd, '°C·일') : <MissingValue inline />}{hddRows.length > 0 && hddRows.length < 12 ? ` (${hddRows.length}개월 합계)` : ''}</dd></div><div><dt>냉방도일 CDD</dt><dd>{cddRows.length ? formatMetric(cdd, '°C·일') : <MissingValue inline />}{cddRows.length > 0 && cddRows.length < 12 ? ` (${cddRows.length}개월 합계)` : ''}</dd></div><div><dt>기준온도</dt><dd>난방 18°C · 냉방 24°C</dd></div></dl></> : <EmptyState description="이 연도의 기상 자료가 없습니다." />}
  </section>;
}
