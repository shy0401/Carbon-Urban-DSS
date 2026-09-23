/**
 * 구성비 막대: 면 채움 조각 사이 2px 간격, 색 없는 범주(미분류·미지정·용도 미상)와 나머지는 결측 해치.
 * 범례에 항목명과 비율을 글자로 적어 색만으로 뜻을 전하지 않는다.
 */
export function ShareBar({ title, shares, colors, names, counts, rest, countUnit = '동' }: {
  title?: string;
  shares: Record<string, number>;
  colors: Record<string, string | null>;
  names: Record<string, string>;
  counts?: Record<string, number>;
  rest?: string;
  countUnit?: string;
}) {
  const entries = Object.entries(shares).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1]);
  const total = entries.reduce((sum, [, v]) => sum + v, 0);
  const remainder = rest ? Math.max(0, 100 - total) : 0;
  const label = [...entries.map(([k, v]) => `${names[k] ?? k} ${v.toFixed(1)}%`), ...(remainder > 0.05 ? [`${rest} ${remainder.toFixed(1)}%`] : [])].join(', ');
  const swatch = (key: string) => colors[key] ?? null;
  return <div className="share-bar">
    {title && <p className="share-title">{title}</p>}
    <div className="share-track" role="img" aria-label={label}>
      {entries.map(([k, v]) => <span key={k} className={swatch(k) ? undefined : 'is-missing'} style={{ width: `${v}%`, background: swatch(k) ?? undefined }} />)}
      {remainder > 0.05 && <span className="is-missing" style={{ width: `${remainder}%` }} />}
    </div>
    <ul className="share-legend">
      {entries.map(([k, v]) => <li key={k}><i className={swatch(k) ? undefined : 'is-missing'} style={{ background: swatch(k) ?? undefined }} />{names[k] ?? k} <b>{v.toFixed(1)}%</b>{counts?.[k] !== undefined && <small>{counts[k].toLocaleString('ko-KR')}{countUnit}</small>}</li>)}
      {remainder > 0.05 && <li><i className="is-missing" />{rest} <b>{remainder.toFixed(1)}%</b></li>}
    </ul>
  </div>;
}
