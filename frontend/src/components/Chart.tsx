import type { EChartsOption } from 'echarts';
import { useEffect, useRef } from 'react';

// ECharts is loaded on first use so it is not part of the initial JavaScript bundle.
export function Chart({ option, height = 300, ariaLabel }: { option: EChartsOption; height?: number; ariaLabel: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let disposed = false;
    let cleanup = () => {};
    void import('echarts').then((echarts) => {
      if (disposed || !ref.current) return;
      const chart = echarts.init(ref.current, undefined, { renderer: 'canvas' });
      chart.setOption(option);
      const observer = new ResizeObserver(() => chart.resize());
      observer.observe(ref.current);
      cleanup = () => { observer.disconnect(); chart.dispose(); };
    });
    return () => { disposed = true; cleanup(); };
  }, [option]);
  return <div ref={ref} style={{ height }} role="img" aria-label={ariaLabel} />;
}
