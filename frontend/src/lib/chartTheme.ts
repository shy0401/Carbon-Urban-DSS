import type { EChartsOption } from 'echarts';

/** Shared chart styling: thin 2px lines, hairline grid, legend on top, crosshair tooltip. */
export const SERIES = { electricity: '#2a78d6', gas: '#eb6834', temperature: '#1baf7a', neutral: '#64738a' };
const INK = '#64738a';
const GRID_LINE = 'rgba(14,26,43,.07)';

export function baseChart(overrides: EChartsOption = {}): EChartsOption {
  return {
    textStyle: { fontFamily: "'Pretendard Variable','Pretendard','Apple SD Gothic Neo','Malgun Gothic','Noto Sans KR',sans-serif" },
    grid: { left: 64, right: 20, top: 44, bottom: 30, containLabel: false },
    legend: { top: 0, right: 0, icon: 'roundRect', itemWidth: 12, itemHeight: 4, textStyle: { color: INK, fontSize: 12 } },
    tooltip: { trigger: 'axis', axisPointer: { type: 'line', lineStyle: { color: 'rgba(14,26,43,.25)' } }, backgroundColor: 'rgba(255,255,255,.94)', borderColor: 'rgba(14,26,43,.08)', textStyle: { color: '#0e1a2b', fontSize: 12 }, extraCssText: 'border-radius:12px;box-shadow:0 18px 36px -18px rgba(16,34,60,.45);backdrop-filter:blur(12px);' },
    xAxis: { type: 'category', axisLine: { lineStyle: { color: GRID_LINE } }, axisTick: { show: false }, axisLabel: { color: INK, fontSize: 12 } },
    yAxis: { type: 'value', nameTextStyle: { color: INK, fontSize: 11, align: 'right' }, splitLine: { lineStyle: { color: GRID_LINE } }, axisLabel: { color: INK, fontSize: 12 } },
    ...overrides,
  };
}

export function lineSeries(name: string, data: Array<number | null>, color: string, area = false) {
  return { name, type: 'line' as const, data, smooth: 0.25, symbol: 'circle', symbolSize: 8, showSymbol: true, connectNulls: false, lineStyle: { width: 2, color }, itemStyle: { color, borderColor: '#fff', borderWidth: 2 }, ...(area ? { areaStyle: { color: { type: 'linear' as const, x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: color + '33' }, { offset: 1, color: color + '00' }] } } } : {}) };
}

export const compactAxis = (value: number) => (Math.abs(value) >= 1e8 ? `${value / 1e8}억` : Math.abs(value) >= 1e4 ? `${value / 1e4}만` : String(value));
