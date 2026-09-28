/** 레이어 켜고 끄기 한 줄: 체크박스 + 지도 위 모양을 닮은 기호(면·선·점·해치) + 이름·설명. */
export type LayerSwatch = 'fill' | 'line' | 'dong' | 'prepared' | 'base' | 'building' | 'dot' | 'zoning' | 'admin';

/** ``colors``: the fill swatch shows the current metric classes (same colors as the map and legend). */
export function swatchGradient(colors: string[]): string | undefined {
  if (!colors.length) return undefined;
  const step = 100 / colors.length;
  return `linear-gradient(90deg, ${colors.map((c, i) => `${c} ${(i * step).toFixed(1)}% ${((i + 1) * step).toFixed(1)}%`).join(', ')})`;
}

export function LayerToggle({ label, checked, onChange, disabled, hint, badge, swatch, colors }: {
  label: string; checked: boolean; onChange: (value: boolean) => void; disabled?: boolean; hint?: string; badge?: string; swatch?: LayerSwatch; colors?: string[];
}) {
  const gradient = colors ? swatchGradient(colors) : undefined;
  return <label className="layer-toggle">
    <input type="checkbox" checked={checked && !disabled} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
    {swatch && <i className={`layer-swatch swatch-${swatch}`} style={gradient ? { background: gradient } : undefined} aria-hidden="true" />}
    <span>{label}{hint && <small>{hint}</small>}</span>
    {badge && <small className="overlay-empty">{badge}</small>}
  </label>;
}

export function LayerGroupTitle({ title, note }: { title: string; note?: string }) {
  return <p className="layer-group-title">{title}{note && <small>{note}</small>}</p>;
}
