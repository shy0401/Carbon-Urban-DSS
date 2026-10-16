import { useEffect, useMemo, useState } from 'react';
import { api } from '../lib/api';
import { formatMetric } from '../lib/format';
import { kcsmClassify, kcsmClassLabel, kcsmFill, kcsmLines, kcsmValueText, KCSM_ZERO_FILL, type KcsmProps, type KcsmResponse } from '../lib/kcsm100';

/** 선택한 500m 칸 안의 100m 25칸 건물 전기 배출 (탄소공간지도, 선도소프트 제공). 5×5, 북쪽이 위. 값이 없는 칸은 비워 둔다(0 아님). */
export function Kcsm100Panel({ gridId, year, region }: { gridId: string; year: number; region: string | null }) {
  const [data, setData] = useState<KcsmResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [picked, setPicked] = useState<KcsmProps | null>(null);
  const m = /^cell_(\d+)_(\d+)$/.exec(gridId);
  useEffect(() => {
    if (!/^cell_\d+_\d+$/.test(gridId)) return undefined;
    const controller = new AbortController(); setData(null); setError(null); setPicked(null);
    api<KcsmResponse>(`/map/kcsm100?grid=${encodeURIComponent(gridId)}&year=${year}${region ? `&region=${region}` : ''}`, { signal: controller.signal })
      .then(setData).catch((e) => { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : '100m 전력 배출 자료를 불러오지 못했습니다'); });
    return () => controller.abort();
  }, [gridId, year, region]);
  const classification = useMemo(() => kcsmClassify(data?.features ?? []), [data]);
  if (!m) return null;
  const gx = Number(m[1]); const gy = Number(m[2]);
  const byXY = new Map((data?.features ?? []).map((f) => [`${f.properties.x}_${f.properties.y}`, f.properties]));
  const rows = [4, 3, 2, 1, 0].map((r) => [0, 1, 2, 3, 4].map((c) => byXY.get(`${gx + c * 100}_${gy + r * 100}`) ?? null));
  const s = data?.summary; const y = data?.meta.year ?? null;
  return <section className="detail-section grid100-panel kcsm100-panel" aria-label="100m 전력 배출 25칸" data-testid="kcsm100-panel">
    <h3>100m 전기 배출 25칸 <small>탄소공간지도 · 선도소프트{y ? ` ${y}년` : ''}</small></h3>
    {error ? <p className="muted">{error}</p> : !data ? <p className="muted">100m 전력 배출 확인 중…</p> : !y ? <p className="muted">{data.meta.reason}</p> : <>
      <div className="grid100-board">
        <div className="grid100-cells" role="grid" aria-label="100m 칸 전기 배출">{rows.map((row, r) => <div role="row" key={r}>{row.map((p, c) => {
          const fill = kcsmFill(p, classification);
          const label = !p ? '자료 없는 칸' : kcsmValueText(p);
          return <button type="button" role="gridcell" key={c} className={`grid100-cell${!p ? ' absent' : ''}${p?.drop ? ' masked' : ''}${picked && p && picked.id === p.id ? ' picked' : ''}`} style={fill ? { background: fill } : undefined} title={label} aria-label={label} onClick={() => setPicked(p)} disabled={!p} />;
        })}</div>)}</div>
        <ul className="grid100-legend">{classification.classes.map((cl, i) => <li key={i}><i style={{ background: cl.color }} />{kcsmClassLabel(classification, i)} t</li>)}<li><i style={{ background: KCSM_ZERO_FILL }} />0 (제공값)</li><li><i className="is-missing" />급감 (누락 의심)</li><li><i className="absent" />자료 없는 칸</li></ul>
      </div>
      {picked && <dl className="fact-list grid100-picked">{kcsmLines(picked, y).map(([k, v]) => <div className="fact" key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>}
      {s && <p className="muted">25칸 합 {s.total_t === null ? '값 없음' : formatMetric(s.total_t, 'tCO₂eq', 1)}{s.prev_total_t != null && data.features[0]?.properties.prev_year ? ` (${data.features[0].properties.prev_year}년 ${formatMetric(s.prev_total_t, 't', 1)})` : ''} · 값 있는 칸 {s.value_cells} · 0 {s.zero_cells}{s.drop_cells ? ` · 급감 ${s.drop_cells}칸` : ''}</p>}
      <p className="muted">선도소프트가 준 탄소공간지도 값(건물 전기, 산정 계수 확인 필요)입니다. 0은 제공값으로, 건물이 없는 칸인지 사용량이 연계되지 않은 칸인지 확인이 필요합니다. 이용 조건을 확인하기 전이라 이 PC 화면에서만 보입니다.</p>
    </>}
  </section>;
}
