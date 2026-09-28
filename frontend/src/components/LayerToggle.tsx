/** 레이어 켜고 끄기 한 줄: 체크박스 + 지도 위 모양을 닮은 기호(면·선·점·해치) + 이름·설명. */
export type LayerSwatch = 'fill' | 'line' | 'prepared' | 'base' | 'building' | 'dot' | 'zoning' | 'admin';

export function LayerToggle({ label, checked, onChange, disabled, hint, badge, swatch }: {
  label: string; checked: boolean; onChange: (value: boolean) => void; disabled?: boolean; hint?: string; badge?: string; swatch?: LayerSwatch;
}) {
  return <label className="layer-toggle">
    <input type="checkbox" checked={checked && !disabled} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
    {swatch && <i className={`layer-swatch swatch-${swatch}`} aria-hidden="true" />}
    <span>{label}{hint && <small>{hint}</small>}</span>
    {badge && <small className="overlay-empty">{badge}</small>}
  </label>;
}

export function LayerGroupTitle({ title, note }: { title: string; note?: string }) {
  return <p className="layer-group-title">{title}{note && <small>{note}</small>}</p>;
}
