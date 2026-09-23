import type { EChartsOption } from 'echarts';
import { useMemo } from 'react';
import { baseChart, lineSeries, missingBands, MONTH_LABELS, monthsOf, SERIES } from '../lib/chartTheme';
import { PROVENANCE, provenanceFromWeatherSource } from '../lib/provenance';
import { Chart } from './Chart';

/**
 * 월평균 기온 (DESIGN.md 5 차트): 1–12월 축을 고정하고 값이 없는 달은 선을 끊고 해치 띠 + "자료 없음".
 * 툴팁에 월별 근거(source_type: OFFICIAL 실측 / FALLBACK 대체)를 적는다.
 */
export function WeatherChart({ year, rows, height = 230, ariaLabel = '월평균 기온 차트' }: { year: number; rows: Array<Record<string, unknown>>; height?: number; ariaLabel?: string }) {
  const option = useMemo<EChartsOption>(() => {
    const temps = monthsOf(year, rows, 'mean_temperature').map((v) => (v === null ? null : Number(v.toFixed(1))));
    const source = new Map(rows.map((r) => [String(r.use_ym ?? '').replace('-', ''), provenanceFromWeatherSource(r.source_type)]));
    const base = baseChart();
    return baseChart({
      grid: { left: 44, right: 16, top: 30, bottom: 26 },
      legend: { show: false },
      tooltip: {
        ...(base.tooltip as object), trigger: 'axis',
        formatter: (params: unknown) => {
          const item = (Array.isArray(params) ? params[0] : params) as { dataIndex: number; value: number | null };
          const month = `${year}${String(item.dataIndex + 1).padStart(2, '0')}`;
          const kind = source.get(month);
          return `${year}년 ${item.dataIndex + 1}월<br/>월평균 기온 ${item.value === null || item.value === undefined ? '자료 없음' : `${item.value} °C`}${kind ? ` (${PROVENANCE[kind].label})` : ''}`;
        },
      },
      xAxis: { ...(base.xAxis as object), data: MONTH_LABELS },
      yAxis: { ...(base.yAxis as object), name: '°C' },
      series: [{ ...lineSeries('월평균 기온', temps, SERIES.temperature), markArea: missingBands(MONTH_LABELS, [temps]) }],
    });
  }, [year, rows]);
  return <Chart height={height} ariaLabel={ariaLabel} option={option} />;
}
