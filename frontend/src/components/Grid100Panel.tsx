import { useEffect, useMemo, useState } from 'react';
import { api } from '../lib/api';
import { formatMetric } from '../lib/format';
import { grid100ClassLabel, grid100Classify, grid100Fill, grid100Lines, grid100Metric, grid100Value, GRID100_METRICS, populationText, type Grid100Key, type Grid100Props, type Grid100Response } from '../lib/grid100';

/** 선택한 500m 칸 안의 100m 25칸 (국토통계지도, 팀 수집). 5×5로 그리고, 자료 없는 칸은 비워 둔다(0 아님). */
export function Grid100Panel({ gridId, year, region }: { gridId: string; year: number; region: string | null }) {
  const [data, setData] = useState<Grid100Response | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [key, setKey] = useState<Grid100Key>('population');
  const [picked, setPicked] = useState<Grid100Props | null>(null);
  const m = /^cell_(\d+)_(\d+)$/.exec(gridId);
  useEffect(() => {
    if (!/^cell_\d+_\d+$/.test(gridId)) return undefined;
    const controller = new AbortController(); setData(null); setError(null); setPicked(null);
    api<Grid100Response>(`/map/grid100?grid=${encodeURIComponent(gridId)}&year=${year}${region ? `&region=${region}` : ''}`, { signal: controller.signal })
      .then(setData).catch((e) => { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : '100m 자료를 불러오지 못했습니다'); });
    return () => controller.abort();
  }, [gridId, year, region]);
  const metric = grid100Metric(key);
  const classification = useMemo(() => grid100Classify(data?.features ?? [], metric), [data, metric]);
  if (!m) return null;
  const gx = Number(m[1]); const gy = Number(m[2]);
  const byXY = new Map((data?.features ?? []).map((f) => [`${f.properties.x}_${f.properties.y}`, f.properties]));
  // 북쪽이 위: 맨 윗줄이 y가 가장 큰 칸.
  const rows = [4, 3, 2, 1, 0].map((r) => [0, 1, 2, 3, 4].map((c) => byXY.get(`${gx + c * 100}_${gy + r * 100}`) ?? null));
  const s = data?.summary;
  return <section className="detail-section grid100-panel" aria-label="100m 격자 25칸">
    <h3>100m 격자 25칸 <small>국토통계지도{data?.meta.year ? ` ${data.meta.year}년` : ''}</small></h3>
    {error ? <p className="muted">{error}</p> : !data ? <p className="muted">100m 자료 확인 중…</p> : !data.meta.year ? <p className="muted">{data.meta.reason}</p> : <>
      <div className="grid100-metrics" role="group" aria-label="100m 지표">{GRID100_METRICS.map((g) => <button key={g.key} type="button" className={g.key === key ? 'active' : ''} aria-pressed={g.key === key} onClick={() => setKey(g.key)}>{g.label}</button>)}</div>
      <div className="grid100-board">
        <div className="grid100-cells" role="grid" aria-label={`100m 칸 ${metric.label}`}>{rows.map((row, r) => <div role="row" key={r}>{row.map((p, c) => {
          const value = p ? p[metric.key] : null; const fill = p ? grid100Fill(value, classification) : null;
          const masked = !!p && key === 'population' && p.population_status === 'masked';
          const label = !p ? '자료 없는 칸' : key === 'population' ? populationText(p) : grid100Value(value, metric);
          return <button type="button" role="gridcell" key={c} className={`grid100-cell${!p ? ' absent' : ''}${masked ? ' masked' : ''}${picked && p && picked.id === p.id ? ' picked' : ''}`} style={fill ? { background: fill } : undefined} title={label} aria-label={label} onClick={() => setPicked(p)} disabled={!p} />;
        })}</div>)}</div>
        <ul className="grid100-legend">{classification.classes.map((cl, i) => <li key={i}><i style={{ background: cl.color }} />{grid100ClassLabel(classification, i, metric)}</li>)}{key === 'population' && <li><i className="is-missing" />1~5명 비공개</li>}<li><i className="absent" />자료 없는 칸</li></ul>
      </div>
      {picked && <dl className="fact-list grid100-picked">{grid100Lines(picked).map(([k, v]) => <div className="fact" key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>}
      {s && <p className="muted">자료 있는 칸 {s.cells_with_data}/25 · 인구 {s.population_sum === null ? '공개값 없음' : `${formatMetric(s.population_sum, '명', 0)} (공개 ${s.population_cells}칸 합)`}{s.masked_cells ? ` + 비공개 ${s.masked_cells}칸(각 1~5명)` : ''} · 건물 {s.buildings_sum === null ? '값 없음' : formatMetric(s.buildings_sum, '동', 0)}</p>}
      <p className="muted">{metric.note} 국토통계지도는 이용 조건상 국외 반출이 금지되어 이 PC 화면에서만 보입니다.</p>
    </>}
  </section>;
}
