import { ChevronDown, Globe2 } from 'lucide-react';
import { useEffect, useMemo, useState, useSyncExternalStore } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAnalysisScope } from '../hooks/useAnalysisScope';
import { openRegion } from '../hooks/useRegionOpen';
import { useSystemInfo } from '../hooks/useSystemInfo';
import { api } from '../lib/api';
import type { RegionCatalogEntry } from '../types';

const FIRST_YEAR = 2015;
const NATIONAL = '__national__';
const CURRENT = '__current__';
const PICK = '';

type RegionOption = { code: string; short_name: string; name: string; level?: string };
const GROUP_LABEL = { DETAILED: '상세 자료', BASIC: '기본 지도 (전국 공통 자료)', NONE: '지도 없음 (처음 열면 몇 초)' } as const;

/** 상세 자료 지역(에너지·건물·용도지역) 먼저, 기본 지도(전국 공통 자료)만 있는 지역, 아직 지도가 없는 지역 순으로 묶는다. */
export function groupRegions(options: RegionOption[]): Array<[string, RegionOption[]]> {
  const sorted = [...options].sort((a, b) => a.short_name.localeCompare(b.short_name, 'ko'));
  const level = (o: RegionOption) => (o.level === 'BASIC' || o.level === 'NONE' ? o.level : 'DETAILED');
  return (['DETAILED', 'BASIC', 'NONE'] as const)
    .map((key): [string, RegionOption[]] => [GROUP_LABEL[key], sorted.filter((o) => level(o) === key)])
    .filter(([label, items]) => items.length > 0 || label !== GROUP_LABEL.NONE);
}

/** 시·도 목록 (법정 2자리): 도 먼저, 특별시·광역시 다음. */
export function provinceOptions(entries: Array<Pick<RegionCatalogEntry, 'code' | 'sido_name'>>): Array<{ code: string; name: string; kind: 'PROVINCE' | 'METRO' }> {
  const seen = new Map<string, string>();
  for (const e of entries) if (!seen.has(e.code.slice(0, 2))) seen.set(e.code.slice(0, 2), e.sido_name);
  const kind = (name: string) => (name.endsWith('도') || name.includes('통합특별시') ? 'PROVINCE' as const : 'METRO' as const);
  return [...seen.entries()].map(([code, name]) => ({ code, name, kind: kind(name) }))
    .sort((a, b) => (a.kind === b.kind ? a.code.localeCompare(b.code) : a.kind === 'PROVINCE' ? -1 : 1));
}

// 전국 시·군·구 목록은 한 번만 읽는다 (머리 선택 상자용).
let catalog: RegionCatalogEntry[] | null = null;
let loading: Promise<void> | null = null;
const catalogListeners = new Set<() => void>();
function loadCatalog() {
  if (catalog || loading) return;
  loading = api<{ regions: RegionCatalogEntry[] }>('/regions/catalog')
    .then((body) => { catalog = body.regions; catalogListeners.forEach((fn) => fn()); })
    .catch(() => { loading = null; });
}
function useRegionCatalog(): RegionCatalogEntry[] | null {
  useEffect(loadCatalog, []);
  return useSyncExternalStore((fn) => { catalogListeners.add(fn); return () => catalogListeners.delete(fn); }, () => catalog, () => catalog);
}

/** 분석 범위 컨트롤: 시·도 → 시·군·구 → 연도. 지도가 없는 시·군·구를 고르면 전국 공통 자료로 기본 지도를 먼저 만든다. */
export function AnalysisScopeBar() {
  const { year, gridId, region, setScope } = useAnalysisScope();
  const system = useSystemInfo();
  const navigate = useNavigate();
  const entries = useRegionCatalog();
  const [sidoPick, setSidoPick] = useState<string | null>(null);
  const lastYear = Math.max(new Date().getFullYear(), year);
  const years = Array.from({ length: lastYear - FIRST_YEAR + 1 }, (_, i) => lastYear - i);
  if (!years.includes(year)) years.push(year);
  const defaultRegion = system?.default_region ?? '52110';
  const prepared = system?.regions ?? [];
  const current = region ?? defaultRegion;
  const sido = sidoPick ?? current.slice(0, 2);
  const levels = useMemo(() => new Map(prepared.map((r) => [r.code, r.level ?? (r.grid_count ? 'DETAILED' : 'NONE')])), [prepared]);
  const provinces = useMemo(() => provinceOptions(entries ?? []), [entries]);
  const options: RegionOption[] = entries
    ? entries.filter((e) => e.code.startsWith(sido)).map((e) => ({ code: e.code, short_name: e.short_name, name: e.name, level: levels.get(e.code) ?? 'NONE' }))
    : (prepared.length ? prepared : [{ code: defaultRegion, short_name: system?.region?.short_name ?? '전주시', name: system?.region?.name ?? '전북특별자치도 전주시' }]);
  const known = options.some((option) => option.code === current);
  const pickSido = (value: string) => {
    if (value === NATIONAL) { navigate('/map?view=national'); return; }
    setSidoPick(value === current.slice(0, 2) ? null : value);
  };
  const pickRegion = (value: string) => {
    if (value === NATIONAL) { navigate(`/map?view=national&sido=${sido}`); return; }
    if (!value || value === CURRENT) return;
    setSidoPick(null);
    setScope({ region: value === defaultRegion ? null : value });
    const option = options.find((o) => o.code === value);
    if (option?.level === 'NONE') openRegion(value, option.short_name).catch(() => undefined); // 머리 알림이 진행을 보여 준다
  };
  return <div className="scope-controls" title="지역·연도·격자는 모든 분석 화면에 함께 적용됩니다">
    {entries && <label className="scope-field"><span>시·도</span>
      <span className="select-wrap"><select aria-label="시·도" data-testid="sido-select" value={sido} onChange={(e) => pickSido(e.target.value)}>
        {(['PROVINCE', 'METRO'] as const).map((kind) => <optgroup key={kind} label={kind === 'PROVINCE' ? '도' : '특별시·광역시'}>
          {provinces.filter((p) => p.kind === kind).map((p) => <option key={p.code} value={p.code}>{p.name}</option>)}
        </optgroup>)}
        <option value={NATIONAL}>전국 지도에서 고르기…</option>
      </select><ChevronDown size={15} aria-hidden="true" /></span>
    </label>}
    <label className="scope-field"><span>{entries ? '시·군·구' : '분석 지역'}</span>
      <span className="select-wrap"><select aria-label="분석 지역" data-testid="region-select" value={known ? current : sidoPick ? PICK : CURRENT} onChange={(e) => pickRegion(e.target.value)}>
        {sidoPick && !known && <option value={PICK} disabled>시·군·구 고르기…</option>}
        {groupRegions(options).map(([label, items]) => items.length ? <optgroup key={label} label={label}>{items.map((option) => <option key={option.code} value={option.code} title={option.name}>{option.short_name}</option>)}</optgroup> : null)}
        {!known && !sidoPick && <option value={CURRENT} disabled>{system?.region?.short_name ?? current}</option>}
        <option value={NATIONAL}>전국 지도에서 고르기…</option>
      </select><ChevronDown size={15} aria-hidden="true" /></span>
    </label>
    <label className="scope-field"><span>분석연도</span>
      <span className="select-wrap"><select aria-label="분석연도" value={year} onChange={(e) => setScope({ year: Number(e.target.value) })}>{years.map((y) => <option key={y} value={y}>{y}년</option>)}</select><ChevronDown size={15} aria-hidden="true" /></span>
    </label>
    {gridId && <button type="button" className="button secondary small" onClick={() => setScope({ gridId: null })}>기본 대상지로</button>}
    <Link className="button ghost small scope-national" to="/regions" title="전국 시·군·구 개요와 지역 준비"><Globe2 size={15} aria-hidden="true" /><span>전국</span></Link>
  </div>;
}
