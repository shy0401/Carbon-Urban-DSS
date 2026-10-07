/**
 * 사례 링크: 화면 입력을 주소(쿼리)로 주고받는다. 같은 링크를 다른 PC에서 열면 같은 지역·구역·입력으로 시작하므로,
 * 같은 자료 묶음이면 같은 결과가 나온다 (docs/USER_MANUAL.md 5·9절, backend/cases/simulation_cases.json).
 *
 * 시뮬레이션: /simulation?region=52110&grid=cell_966500_1764500&site=127.13219,35.880124,0&site_area=40000&building_count=10&…
 * 지역 시뮬레이션: /area?region=52110&area=admin:35012650&from=2015&to=2025&plan=90000&target=20&basis=apartments
 */
import type { ScenarioInput } from '../types';
import type { AreaMode, AreaSpec, EffortBasis, PlanState } from './area';

/** The original study region. The analysis scope keeps it as null; a link always names a region so it opens the same place. */
export const DEFAULT_REGION = '52110';

export const SCENARIO_KEYS: Array<keyof ScenarioInput> = ['site_area', 'building_count', 'footprint_per_building', 'floors', 'households', 'population',
  'efficiency_factor', 'pv_ratio', 'green_ratio', 'average_household_area'];

export interface ScopeLink { region?: string | null; grid?: string | null; year?: number }
export interface ScenarioLink extends ScopeLink {
  input: Partial<ScenarioInput>;
  site?: { lon: number; lat: number; rotation: number };
  constraints?: { min_households?: number; min_population?: number };
}
export interface AreaLink extends ScopeLink {
  mode?: AreaMode; spec?: AreaSpec; from?: number; to?: number; event?: number | null; window?: number;
  plan?: Partial<PlanState>; target?: number; pv?: string; basis?: EffortBasis;
}

/** Commas and colons are valid in a query value; keeping them makes the link readable (127.13,35.88 / admin:35012650). */
const readable = (params: URLSearchParams) => params.toString().replace(/%2C/gi, ',').replace(/%3A/gi, ':');

const num = (value: string | null): number | undefined => {
  if (value === null || value.trim() === '') return undefined;
  const n = Number(value);
  return Number.isFinite(n) ? n : undefined;
};

function scope(params: URLSearchParams): ScopeLink {
  const out: ScopeLink = {};
  const region = params.get('region');
  if (region !== null) out.region = /^\d{5}$/.test(region) && region !== DEFAULT_REGION ? region : null;
  const grid = params.get('grid');
  if (grid !== null && /^cell_\d+_\d+$/.test(grid)) out.grid = grid;
  const year = num(params.get('year'));
  if (year && year >= 2000 && year <= 2100) out.year = year;
  return out;
}

/** null when the address carries no scenario input (the page keeps its own defaults). */
export function parseScenarioLink(search: string): ScenarioLink | null {
  const params = new URLSearchParams(search);
  const input: Partial<ScenarioInput> = {};
  for (const key of SCENARIO_KEYS) {
    const value = num(params.get(key));
    if (value !== undefined && value >= 0) input[key] = value;
  }
  const link: ScenarioLink = { ...scope(params), input };
  const site = (params.get('site') ?? '').split(',').map(Number);
  if (site.length >= 2 && site.slice(0, 2).every(Number.isFinite) && site[0] >= 124 && site[0] <= 132 && site[1] >= 33 && site[1] <= 39) {
    link.site = { lon: site[0], lat: site[1], rotation: Number.isFinite(site[2]) ? Math.min(89.9, Math.max(0, site[2])) : 0 };
  }
  const minHouseholds = num(params.get('min_households'));
  const minPopulation = num(params.get('min_population'));
  if (minHouseholds !== undefined || minPopulation !== undefined) link.constraints = { min_households: minHouseholds, min_population: minPopulation };
  const empty = !Object.keys(input).length && !link.site && !link.constraints && link.region === undefined && !link.grid;
  return empty ? null : link;
}

export function scenarioLink(input: ScenarioInput, site: { lon: number; lat: number; rotation: number } | null, at: ScopeLink,
  constraints?: { min_households: number; min_population: number }): string {
  const params = new URLSearchParams();
  params.set('region', at.region ?? DEFAULT_REGION);
  if (at.grid) params.set('grid', at.grid);
  if (at.year) params.set('year', String(at.year));
  if (site) params.set('site', `${site.lon.toFixed(6)},${site.lat.toFixed(6)},${Math.round(site.rotation * 10) / 10}`);
  for (const key of SCENARIO_KEYS) params.set(key, String(input[key]));
  if (constraints) { params.set('min_households', String(constraints.min_households)); params.set('min_population', String(constraints.min_population)); }
  return `/simulation?${readable(params)}`;
}

const MODES: AreaMode[] = ['admin', 'circle', 'zone', 'grid'];

/** `area=admin:35012650 | grid:cell_… | circle:lon,lat,radius | zone:COMMERCIAL` and the analysis inputs. */
export function parseAreaLink(search: string): AreaLink | null {
  const params = new URLSearchParams(search);
  const link: AreaLink = scope(params);
  const area = params.get('area');
  if (area) {
    const [kind, value = ''] = area.split(/:(.*)/s);
    const mode = kind as AreaMode;
    if (MODES.includes(mode)) {
      if (mode === 'admin' && /^\d{5,10}$/.test(value)) link.spec = { type: 'admin', code: value };
      if (mode === 'zone' && /^[A-Z]+$/.test(value)) link.spec = { type: 'zone', category: value };
      if (mode === 'grid' && /^cell_\d+_\d+$/.test(value)) link.spec = { type: 'grid', grid_id: value };
      if (mode === 'circle') {
        const [lon, lat, radius] = value.split(',').map(Number);
        if ([lon, lat].every(Number.isFinite) && lon >= 124 && lon <= 132 && lat >= 33 && lat <= 39) {
          link.spec = { type: 'circle', lon, lat, radius_m: Number.isFinite(radius) && radius >= 100 && radius <= 5000 ? radius : 1000 };
        }
      }
      if (link.spec) link.mode = mode;
    }
  }
  const from = num(params.get('from')); const to = num(params.get('to'));
  if (from && from >= 2000 && from <= 2100) link.from = from;
  if (to && to >= 2000 && to <= 2100) link.to = to;
  const event = params.get('event');
  if (event !== null) link.event = num(event) ?? null;
  const window = num(params.get('window'));
  if (window && window >= 1 && window <= 5) link.window = window;
  const added = num(params.get('plan')); const removed = num(params.get('removed'));
  if (added !== undefined || removed !== undefined) link.plan = { method: 'area', ...(added !== undefined ? { added_floor_area_m2: added } : {}), ...(removed !== undefined ? { removed_floor_area_m2: removed } : {}) };
  const target = num(params.get('target'));
  if (target !== undefined && target >= 0 && target <= 100) link.target = target;
  const pv = num(params.get('pv'));
  if (pv !== undefined && pv > 0) link.pv = String(pv);
  const basis = params.get('basis');
  if (basis === 'apartments' || basis === 'buildings') link.basis = basis;
  return Object.keys(link).length ? link : null;
}

export function areaLink(spec: AreaSpec | null, a: { region: string | null; from: number; to: number; event: number | null; window: number; plan: PlanState; target: number; pv: string; basis: EffortBasis }): string | null {
  if (!spec || spec.type === 'polygon') return null;   // a drawn polygon does not fit in an address
  const params = new URLSearchParams();
  params.set('region', a.region ?? DEFAULT_REGION);
  const value = spec.type === 'admin' ? spec.code : spec.type === 'zone' ? spec.category : spec.type === 'grid' ? spec.grid_id
    : `${spec.lon},${spec.lat},${spec.radius_m}`;
  params.set('area', `${spec.type}:${value}`);
  params.set('from', String(a.from)); params.set('to', String(a.to));
  if (a.event) params.set('event', String(a.event));
  params.set('window', String(a.window));
  if (a.plan.method === 'area') params.set('plan', String(a.plan.added_floor_area_m2));
  else params.set('plan', String(a.plan.floors * a.plan.building_count * a.plan.footprint_per_building));
  if (a.plan.removed_floor_area_m2 > 0) params.set('removed', String(a.plan.removed_floor_area_m2));
  params.set('target', String(a.target));
  if (a.pv && Number(a.pv) > 0) params.set('pv', a.pv);
  params.set('basis', a.basis);
  return `/area?${readable(params)}`;
}
