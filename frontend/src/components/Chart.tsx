import * as echarts from 'echarts';
import { useEffect, useRef } from 'react';

export function Chart({ option, height = 300, ariaLabel }: { option: echarts.EChartsOption; height?: number; ariaLabel: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current, undefined, { renderer: 'canvas' });
    chart.setOption(option);
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(ref.current);
    return () => { observer.disconnect(); chart.dispose(); };
  }, [option]);
  return <div ref={ref} style={{ height }} role="img" aria-label={ariaLabel} />;
}
