import type { EChartsOption } from 'echarts';
import { useMemo } from 'react';
import { at, COHORT_COLOR, COHORT_LABEL, cohortSeries, REGISTER_GROUPS, type AreaHistory, type BeforeAfter, type Cohort, type EffortResult } from '../../lib/area';
import { baseChart, compactAxis, lineSeries, missingBands } from '../../lib/chartTheme';
import { formatMetric } from '../../lib/format';
import { TOKENS } from '../../theme/palette';
import { Chart } from '../Chart';

const COHORTS: Cohort[] = ['before', 'event', 'after', 'unknown'];

function axis(base: EChartsOption, categories: string[], unit: string, extra: Record<string, unknown> = {}): EChartsOption {
  return {
    xAxis: { ...(base.xAxis as object), data: categories },
    yAxis: { ...(base.yAxis as object), name: unit, axisLabel: { ...((base.yAxis as { axisLabel?: object }).axisLabel ?? {}), formatter: compactAxis }, ...extra },
  };
}

/** 관측이 없는 해: 해치 띠 + "관측 없음"(추정선은 그 위에 따로 그린다). */
function observedGaps(years: string[], observed: Array<number | null>) {
  const band = missingBands(years, [observed]);
  return band ? { ...band, label: { ...band.label, formatter: '관측 없음' } } : undefined;
}

function eventLine(eventYear: number | null | undefined) {
  if (!eventYear) return undefined;
  return { silent: true, symbol: 'none', lineStyle: { color: TOKENS['plan-b'], type: [4, 3] as number[], width: 1.5 }, label: { formatter: `개발 ${eventYear}`, color: TOKENS.ink, fontSize: 12, position: 'end' as const }, data: [{ xAxis: String(eventYear) }] };
}

/** 연도별 전력: 관측(12개월 완전 지번) 막대를 단지 준공 시기별로 쌓고, 관측이 없는 해는 해치 + 추정선(점선). */
export function ElectricityChart({ history, eventYear }: { history: AreaHistory; eventYear: number | null | undefined }) {
  const option = useMemo<EChartsOption>(() => {
    const years = history.years.map(String);
    const s = cohortSeries(history, eventYear);
    const base = baseChart();
    const observed = COHORTS.filter((c) => s[c].some((v) => (v ?? 0) > 0));
    const bars = observed.map((c, i) => ({
      name: `관측 · ${COHORT_LABEL[c]}`, type: 'bar' as const, stack: 'observed', barMaxWidth: 28,
      data: s[c].map((v) => (v === null ? null : v)),
      itemStyle: { color: COHORT_COLOR[c], borderColor: TOKENS.surface, borderWidth: 1, borderRadius: i === observed.length - 1 ? [4, 4, 0, 0] : 0 },
      ...(i === 0 ? { markArea: observedGaps(years, s.before), markLine: eventLine(eventYear) } : {}),
    }));
    const est = lineSeries('추정 (연면적 × 전주 원단위)', s.estimated, TOKENS['prov-estimated'], 'estimated');
    const seriesList: unknown[] = [...bars, bars.length ? est : { ...est, markArea: observedGaps(years, s.before), markLine: eventLine(eventYear) }];
    return baseChart({
      grid: { left: 64, right: 20, top: 48, bottom: 30 },
      legend: { ...(base.legend as object), itemWidth: 12, itemHeight: 8 },
      tooltip: { ...(base.tooltip as object), valueFormatter: (v: unknown) => (typeof v === 'number' ? formatMetric(v, 'kWh') : '자료 없음') },
      ...axis(base, years, 'kWh/년'),
      series: seriesList as EChartsOption['series'],
    });
  }, [history, eventYear]);
  return <Chart option={option} height={300} ariaLabel="연도별 전력 사용량: 관측 막대(단지 준공 시기별)와 추정선" />;
}

/** 사용승인(준공) 세대수: 개발 연도 막대만 plan-b, 나머지는 중립. 도움말에 단지명. */
export function DevelopmentChart({ history, eventYear }: { history: AreaHistory; eventYear: number | null | undefined }) {
  const option = useMemo<EChartsOption>(() => {
    const years = history.years.map(String);
    const base = baseChart();
    const data = history.years.map((y) => {
      const e = at(history.events, y);
      const value = e?.households ?? 0;
      return { value, itemStyle: { color: y === eventYear ? TOKENS['plan-b'] : TOKENS['seq-4'], borderRadius: [4, 4, 0, 0] }, names: e?.names ?? [], complexes: e?.complexes ?? 0 };
    });
    return baseChart({
      legend: { show: false },
      grid: { left: 64, right: 20, top: 30, bottom: 30 },
      tooltip: {
        ...(base.tooltip as object), trigger: 'item',
        formatter: (p: unknown) => {
          const item = p as { name: string; data: { value: number; names: string[]; complexes: number } };
          const names = item.data.names.slice(0, 4).join(', ') + (item.data.names.length > 4 ? ` 외 ${item.data.names.length - 4}곳` : '');
          return `${item.name}년 사용승인<br><b>${item.data.value.toLocaleString('ko-KR')}세대</b> · ${item.data.complexes}개 단지${names ? `<br><small>${names}</small>` : ''}`;
        },
      },
      ...axis(base, years, '세대'),
      series: [{ name: '사용승인 세대', type: 'bar', barMaxWidth: 28, data: data as never }],
    });
  }, [history, eventYear]);
  return <Chart option={option} height={220} ariaLabel="연도별 사용승인(준공) 세대수" />;
}

/** 난방도일·냉방도일: 12개월이 모두 있는 해만 값, 나머지는 자료 없음. 같은 단위(°C·일)라 한 축. */
export function WeatherYearsChart({ history }: { history: AreaHistory }) {
  const option = useMemo<EChartsOption>(() => {
    const years = history.years.map(String);
    const hdd = history.years.map((y) => at(history.weather, y)?.hdd ?? null);
    const cdd = history.years.map((y) => at(history.weather, y)?.cdd ?? null);
    const base = baseChart();
    return baseChart({
      grid: { left: 64, right: 20, top: 40, bottom: 30 },
      tooltip: { ...(base.tooltip as object), valueFormatter: (v: unknown) => (typeof v === 'number' ? formatMetric(v, '°C·일') : '자료 없음') },
      ...axis(base, years, '°C·일'),
      series: [{ ...lineSeries('난방도일', hdd, TOKENS['series-gas']), markArea: missingBands(years, [hdd, cdd]) }, lineSeries('냉방도일', cdd, TOKENS['info'])] as EChartsOption['series'],
    });
  }, [history]);
  return <Chart option={option} height={220} ariaLabel="연도별 난방도일과 냉방도일" />;
}

/** 전후 연평균 비교: 관측과 추정을 따로 묶는다(같은 kWh 한 축). */
export function BeforeAfterChart({ comparison }: { comparison: BeforeAfter }) {
  const option = useMemo<EChartsOption>(() => {
    const m = comparison.metrics;
    const base = baseChart();
    const before = [m?.electricity.before_total_kwh ?? null, m?.estimated?.before_kwh ?? null];
    const after = [m?.electricity.after_total_kwh ?? null, m?.estimated?.after_kwh ?? null];
    const empty = (i: number) => (before[i] === null && after[i] === null ? '\n자료 없음' : '');
    const groups = [`관측 (12개월 완전)${empty(0)}`, `추정 (연면적 × 원단위)${empty(1)}`];
    return baseChart({
      grid: { left: 72, right: 20, top: 40, bottom: 44 },
      legend: { ...(base.legend as object), icon: 'rect', itemWidth: 10, itemHeight: 10, itemGap: 18 },
      tooltip: { ...(base.tooltip as object), trigger: 'axis', axisPointer: { type: 'shadow' }, valueFormatter: (v: unknown) => (typeof v === 'number' ? formatMetric(v, 'kWh/년') : '자료 없음') },
      ...axis(base, groups, 'kWh/년'),
      series: [
        { name: `개발 전 (${(comparison.before_years ?? []).join('·') || '—'})`, type: 'bar', barMaxWidth: 36, barGap: '10%', data: before, itemStyle: { color: TOKENS['seq-3'], borderRadius: [4, 4, 0, 0] } },
        { name: `개발 후 (${(comparison.after_years ?? []).join('·') || '—'})`, type: 'bar', barMaxWidth: 36, data: after, itemStyle: { color: TOKENS['seq-5'], borderRadius: [4, 4, 0, 0] } },
      ] as EChartsOption['series'],
    });
  }, [comparison]);
  return <Chart option={option} height={240} ariaLabel="개발 전후 연평균 전력 비교" />;
}

/** 감축 노력: 기준·개발 후(BAU)·목표 탄소를 한 줄 막대로. tCO₂eq = 엔진 kg ÷ 1,000. */
export function EffortBars({ effort }: { effort: EffortResult }) {
  const option = useMemo<EChartsOption>(() => {
    const t = (v: number | undefined) => (typeof v === 'number' ? Math.round(v / 100) / 10 : null);
    const rows = [
      { name: `기준 ${effort.baseline_year}년`, value: t(effort.baseline_kgco2eq), color: TOKENS['seq-4'] },
      { name: '개발 후 (추가 대책 없음)', value: t(effort.bau_kgco2eq), color: TOKENS['load-4'] },
      { name: `목표 (−${effort.target_pct}%)`, value: t(effort.target_kgco2eq), color: TOKENS['gain-4'] },
    ];
    const base = baseChart();
    return baseChart({
      legend: { show: false },
      grid: { left: 150, right: 90, top: 10, bottom: 24 },
      tooltip: { ...(base.tooltip as object), trigger: 'item', valueFormatter: (v: unknown) => (typeof v === 'number' ? formatMetric(v, 'tCO₂eq/년', 1) : '자료 없음') },
      xAxis: { type: 'value', splitLine: { lineStyle: { color: TOKENS.line } }, axisLabel: { color: TOKENS['ink-3'], fontSize: 12, formatter: compactAxis } },
      yAxis: { type: 'category', inverse: true, data: rows.map((r) => r.name), axisLine: { lineStyle: { color: TOKENS['line-strong'] } }, axisTick: { show: false }, axisLabel: { color: TOKENS.ink, fontSize: 12 } },
      series: [{ type: 'bar', barMaxWidth: 20, data: rows.map((r) => ({ value: r.value, itemStyle: { color: r.color, borderRadius: [0, 4, 4, 0] } })), label: { show: true, position: 'right', color: TOKENS.ink, fontSize: 12, formatter: (p: { value: unknown }) => (typeof p.value === 'number' ? `${p.value.toLocaleString('ko-KR')} t` : '자료 없음') } }] as EChartsOption['series'],
    });
  }, [effort]);
  return <Chart option={option} height={150} ariaLabel="기준·개발 후·목표 탄소 비교" />;
}

/** 목표 감축률(가로)별 필요한 효율 개선률(세로). 신축만 방식은 100% 이하 구간만 그린다. */
export function EffortCurve({ effort }: { effort: EffortResult }) {
  const option = useMemo<EChartsOption>(() => {
    const curve = effort.curve ?? [];
    const labels = curve.map((c) => `${c.target_pct}%`);
    const all = curve.map((c) => (c.all_buildings_efficiency_pct === null ? null : Math.max(0, c.all_buildings_efficiency_pct)));
    const newOnly = curve.map((c) => (c.new_only_efficiency_pct === null || c.new_only_efficiency_pct > 100 ? null : Math.max(0, c.new_only_efficiency_pct)));
    const base = baseChart();
    const chosen = `${Math.round((effort.target_pct ?? 0) / 10) * 10}%`;
    return baseChart({
      grid: { left: 56, right: 20, top: 40, bottom: 44 },
      tooltip: { ...(base.tooltip as object), valueFormatter: (v: unknown) => (typeof v === 'number' ? `${v.toLocaleString('ko-KR')}%` : '100% 초과 (불가)') },
      xAxis: { ...(base.xAxis as object), data: labels, name: '목표 감축률 (기준 연도 대비)', nameLocation: 'middle', nameGap: 28, nameTextStyle: { color: TOKENS['ink-3'], fontSize: 12 } },
      yAxis: { ...(base.yAxis as object), name: '필요 효율 개선률 %', max: 100, min: 0 },
      series: [
        { ...lineSeries('지역 전체 건물', all, TOKENS.primary), markLine: { silent: true, symbol: 'none', lineStyle: { color: TOKENS['ink-2'], type: [1, 3] as number[] }, label: { formatter: '입력 목표', color: TOKENS.ink, fontSize: 12 }, data: [{ xAxis: chosen }] } },
        ...(newOnly.filter((v) => v !== null).length >= 2 ? [lineSeries('신축 건물만', newOnly, TOKENS['plan-b'], 'scenario')] : []),
      ] as EChartsOption['series'],
    });
  }, [effort]);
  const zero = effort.curve?.[0]?.new_only_efficiency_pct;
  const newOnlyPoints = (effort.curve ?? []).filter((c) => c.new_only_efficiency_pct !== null && c.new_only_efficiency_pct <= 100).length;
  return <>
    <Chart option={option} height={240} ariaLabel="목표 감축률별 필요 효율 개선률" />
    {newOnlyPoints < 2 && zero != null && <p className="muted">신축 건물만 개선하는 방식은 그래프에서 뺐습니다. 기준 연도 수준을 유지(목표 0%)하는 데에도 신축 전력을 {zero.toLocaleString('ko-KR')}% 줄여야 해서, 100%를 넘는 목표는 신축만으로 달성할 수 없습니다.</p>}
  </>;
}

/** 건축물대장 사용승인 연면적을 용도군별로 쌓은 막대 (모든 건물, m²). 기타·미상은 해치. */
export function RegisterChart({ history, eventYear }: { history: AreaHistory; eventYear: number | null | undefined }) {
  const option = useMemo<EChartsOption>(() => {
    const years = history.years.map(String);
    const base = baseChart();
    const colors: Record<string, unknown> = { '주거': TOKENS['seq-4'], '상업·업무': TOKENS['plan-b'], '공공·교육·의료': TOKENS.info, '공업·창고·물류': TOKENS['load-4'], '기타·미상': TOKENS.hatch };
    const series = REGISTER_GROUPS.map((group, i) => ({
      name: group, type: 'bar' as const, stack: 'gfa', barMaxWidth: 28,
      data: history.years.map((y) => { const v = at(history.register?.years, y)?.by_use?.[group]; return v ? v : 0; }),
      itemStyle: { color: colors[group] as string, borderColor: TOKENS.surface, borderWidth: 1, borderRadius: i === REGISTER_GROUPS.length - 1 ? [4, 4, 0, 0] : 0 },
      ...(i === 0 ? { markLine: eventLine(eventYear) } : {}),
    }));
    return baseChart({
      grid: { left: 64, right: 20, top: 48, bottom: 30 },
      legend: { ...(base.legend as object), itemWidth: 12, itemHeight: 8 },
      tooltip: { ...(base.tooltip as object), trigger: 'axis', axisPointer: { type: 'shadow' }, valueFormatter: (v: unknown) => (typeof v === 'number' ? formatMetric(v, 'm²') : '자료 없음') },
      ...axis(base, years, 'm² (연면적)'),
      series: series as EChartsOption['series'],
    });
  }, [history, eventYear]);
  return <Chart option={option} height={240} ariaLabel="건축물대장 기준 연도별 사용승인 연면적(용도군별)" />;
}
