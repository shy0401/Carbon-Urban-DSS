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
  // chart-canvas: 어두운 테마에서도 그림은 밝은 종이 위에 둔다(themes.css). 축·범례 글자색이 밝은 바탕 기준이라서다.
  return <div ref={ref} className="chart-canvas" style={{ height }} role="img" aria-label={ariaLabel} />;
}
