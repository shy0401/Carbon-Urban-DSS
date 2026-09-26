export type Quality = 'OBSERVED' | 'ESTIMATED' | 'FALLBACK' | 'MISSING' | string;

export interface Sector {
  id: string | number;
  name: string;
  grid_id: string | number;
  area_m2: number | null;
  reason: string | null;
}

export interface MonthlyObservation {
  use_ym: string;
  electricity_kwh: number | null;
  gas_kwh: number | null;
  carbon_kg: number | null;
  [key: string]: unknown;
}

export interface DataSource {
  id: string | number;
  category: string;
  name: string;
  organization: string | null;
  source_url: string | null;
  status: string;
  source_type: string | null;
  collected_at: string | null;
  reference_period: string | null;
  geographic_coverage: string | null;
  raw_row_count: number | null;
  normalized_row_count: number | null;
  missing_count: number | null;
  quality: Quality | null;
  limitation: string | null;
  license?: string | null;
  quality_scores?: QualityScores | null;
  schema?: Record<string, unknown> | null;
}

export interface QualityScores {
  coverage_score?: number | null;
  completeness_score?: number | null;
  temporal_score?: number | null;
  spatial_match_score?: number | null;
  overall: number | null;
  dimensions?: Partial<Record<'coverage' | 'completeness' | 'temporal' | 'spatial_match', { score: number | null; evidence?: string | null }>>;
}

export interface DashboardData {
  selected_sector: Sector | null;
  electricity_kwh: number | null;
  gas_kwh: number | null;
  carbon_kg: number | null;
  current_far: number | null;
  current_bcr?: number | null;
  households?: number | null;
  population?: number | null;
  quality: Quality | null;
  monthly: MonthlyObservation[];
  weather: Array<Record<string, unknown>>;
  sources: DataSource[];
  coverage: Record<string, unknown> | null;
  regional_monthly?: MonthlyObservation[];
  regional_totals?: { electricity_kwh: number | null; gas_kwh: number | null; carbon_kg: number | null };
  carbon_status?: string | null;
  baseline_floor_area_m2?: number | null;
  electricity_carbon_kg?: number | null;
  gas_carbon_kg?: number | null;
  annual_complete?: { electricity: boolean; gas: boolean };
  normalized?: {
    electricity_kwh_per_m2?: number | null;
    electricity_matched_floor_area_m2?: number | null;
    electricity_kwh_per_household?: number | null;
    electricity_households?: number | null;
    electricity_complete_parcels?: number;
    electricity_observed_parcels?: number;
    electricity_area_parcels?: number;
    electricity_household_parcels?: number;
    electricity_carbon_kg_per_m2?: number | null;
    energy_kwh_per_m2?: number | null;
  };
  baseline_scope?: { parcels: string[]; parcel_names: string[]; energy_types: string[]; excluded_parcels: string[]; excluded_names: string[]; area_m2: number } | null;
  floor_area_issues?: Array<{ kapt_code: string; name: string; status: string; reason: string | null }>;
  context?: GridContext | null;
  /** Every metered building of the selected grid (bldg_* map fields + year); null before city-wide collection. */
  building_energy?: (Partial<GridProps> & { year: number; complete?: boolean }) | null;
  /** 월별 관측 에너지의 근거 유형 코드 (서버 고정값 'OBSERVED'). */
  observations_label?: string;
  /** 메타데이터 파생값의 근거 유형 코드 (서버 고정값 'CALCULATED'). */
  metadata_label?: string;
}

export interface GridContext {
  grid_id: string | null;
  zoning: { status: string; shares_pct: Record<string, number>; residential_pct: number; dominant: string | null; source: string } | null;
  admin: Array<{ adm_code: string; adm_name: string; reference_year: number; grid_share_pct: number; population: number | null; population_status: string; households: number | null }>;
  complexes: { count: number; households: number | null; gross_floor_area_m2: number | null; with_floor_area: number; floor_area_excluded?: string[]; names: string[]; source: string } | null;
  buildings: (GridBuildings & { source: string }) | null;
  /** Parent SGIS 1km grid cell (official statistics with disclosure noise, never divided into 500m). */
  sgis_grid?: SgisGridCell | null;
}

/** SGIS 1km grid statistics for one cell or a sum of cells. null = no published value (not 0). */
export interface SgisGridSummary {
  population: number | null;
  male: number | null;
  female: number | null;
  households: number | null;
  housing: number | null;
  businesses: number | null;
  workers: number | null;
  elderly_pct: number | null;
  children_pct: number | null;
  single_household_pct: number | null;
  old_housing_pct: number | null;
  apartment_pct: number | null;
  housing_age: Record<string, number | null>;
  housing_types: Record<string, number | null>;
  housing_area: Record<string, number | null>;
  household_types: Record<string, number | null>;
  sectors: Array<{ name: string; businesses: number | null; workers: number | null }>;
  small_flags: string[];
}

export type SgisGridCell = { year: number; code: string | null; source: string } & (
  | ({ status: 'OBSERVED' } & SgisGridSummary)
  | { status: 'NO_STAT' }
);

export interface GridBuildings {
  status: string;
  building_count: number;
  footprint_m2: number;
  coverage_pct: number;
  floor_area_est_m2: number | null;
  far_est_pct: number | null;
  floors_known_count: number;
  floors_known_pct: number | null;
  avg_floors: number | null;
  max_floors: number | null;
  category_share_pct: Record<string, number>;
  category_count: Record<string, number>;
  dominant_use: string | null;
}

/** Per-grid indicators served by /api/map (every ratio comes with its basis). */
export interface GridProps {
  id: string;
  area_m2: number;
  selected: boolean;
  electricity_kwh: number | null;
  gas_kwh: number | null;
  electricity_months: number;
  gas_months: number;
  energy_parcels: number;
  electricity_complete_parcels: number;
  electricity_observed_parcels: number;
  electricity_area_parcels: number;
  electricity_household_parcels: number;
  electricity_kwh_per_m2: number | null;
  electricity_kwh_per_household: number | null;
  electricity_area_m2: number | null;
  electricity_households: number | null;
  gas_kwh_per_m2: number | null;
  gas_complete_parcels: number;
  electricity_carbon_kg: number | null;
  electricity_carbon_kg_per_m2: number | null;
  carbon_kg: number | null;
  completeness: number;
  zoning_status: string | null;
  residential_zone_ratio: number | null;
  urban_zone_ratio: number | null;
  dominant_zone: string | null;
  zone_shares: Record<string, number> | null;
  building_source: 'VWORLD' | 'OSM' | null;
  building_status: string | null;
  building_count: number | null;
  footprint_m2: number | null;
  coverage_pct: number | null;
  far_est_pct: number | null;
  floor_area_est_m2: number | null;
  avg_floors: number | null;
  max_floors: number | null;
  floors_known_pct: number | null;
  building_density: number | null;
  residential_building_share: number | null;
  dominant_use: string | null;
  use_share_pct: Record<string, number> | null;
  complex_count: number;
  complex_households: number | null;
  complex_gfa_m2: number | null;
  complex_gfa_excluded: number;
  /** Parcels left out of energy totals/ratios as implausible (partial or mixed meters). */
  electricity_suspect_parcels?: number;
  /** Share (%) of building footprint whose use is known. */
  use_known_pct?: number | null;
  /** Every metered building of the grid (건축HUB by 법정동; null until collected city-wide). */
  bldg_parcels?: number | null;
  bldg_electricity_kwh?: number | null;
  bldg_gas_kwh?: number | null;
  bldg_electricity_complete?: number | null;
  bldg_gas_complete?: number | null;
  bldg_area_m2?: number | null;
  bldg_area_parcels?: number | null;
  bldg_kwh_per_m2?: number | null;
  bldg_carbon_t?: number | null;
  bldg_suspect?: number | null;
  /** 건축물대장 표제부 linked to the grid (null until collected). */
  reg_buildings?: number | null;
  reg_area_issues?: number | null;
  reg_gfa_m2?: number | null;
  reg_far_pct?: number | null;
  reg_residential_gfa_pct?: number | null;
  reg_old_gfa_pct?: number | null;
  reg_dominant_use?: string | null;
  reg_use_gfa_pct?: Record<string, number> | null;
  /** Official SGIS 500m cell code with the same corner as this cell (API boundary; no statistics). */
  sgis500_code?: string | null;
  /** SGIS 1km parent cell (absent until the bundle is loaded). Densities are per km² of the 1km cell. */
  sgis1k_code?: string | null;
  sgis1k_year?: number;
  sgis1k_status?: 'OBSERVED' | 'NO_STAT';
  sgis1k_population?: number | null;
  sgis1k_households?: number | null;
  sgis1k_housing?: number | null;
  sgis1k_businesses?: number | null;
  sgis1k_workers?: number | null;
  sgis_pop_density?: number | null;
  sgis_housing_density?: number | null;
  sgis_worker_density?: number | null;
  sgis_elderly_pct?: number | null;
  sgis_single_household_pct?: number | null;
  sgis_old_housing_pct?: number | null;
  sgis_apartment_pct?: number | null;
  sgis1k_small?: string[];
  [key: string]: unknown;
}

export interface MapData {
  grids: GeoJSON.FeatureCollection<GeoJSON.Geometry, GridProps>;
  buildings: GeoJSON.FeatureCollection;
  buildings_mode?: 'viewport' | 'embedded';
  buildings_source?: string;
  boundary: GeoJSON.FeatureCollection;
  boundary_source?: string;
  complexes?: GeoJSON.FeatureCollection;
  complex_floor_area_issues?: number;
  factors?: { electricity: { value: number; unit: string; source: string; reference_year: number } | null; gas: { value: number; unit: string } | null };
  selected_sector: Sector | null;
  center?: [number, number];
  crs?: string;
  grid_size_m?: number;
  grid_area_m2?: number;
  year?: number;
  offline_mode?: boolean;
  sgis_grid?: { year: number | null; source: string; note: string } | null;
  register?: { grids: number; buildings: number; source: string } | null;
  building_energy?: { grids: number; parcels: number; complete: boolean; source: string } | null;
}

export interface BuildingViewport extends GeoJSON.FeatureCollection {
  total: number;
  truncated: boolean;
  source: string | null;
}

export interface OverlayData {
  zoning: GeoJSON.FeatureCollection;
  admin: GeoJSON.FeatureCollection;
  meta: {
    zoning_features: number;
    admin_features: number;
    admin_reference_year: number | null;
    zoning_area_km2_by_category?: Record<string, number>;
    zoning_grids_covered?: number;
    analysis_year?: number;
    crs?: string;
    sources?: Record<string, string>;
    truth_rules?: string[];
  };
}

export interface SourceDetail {
  source: DataSource;
  raw_preview: unknown;
  normalized_preview: unknown;
  jobs: CollectionJob[];
  errors: unknown;
  coverage: unknown;
  assets?: Array<Record<string, unknown>>;
  fields?: string[];
}

export interface CollectionJob {
  id: string | number;
  status: string;
  progress?: number | null;
  dataset?: string;
  datasets?: string[];
  created_at?: string | null;
  updated_at?: string | null;
  message?: string | null;
  error?: string | null;
  errors?: Array<{ dataset?: string | null; message?: string | null } | string>;
  resolved?: boolean;
  resolved_datasets?: string[];
}

export interface ReadinessSource {
  id: string;
  name: string;
  organization: string | null;
  source_url: string | null;
  status: string;
  state: string;
  acquisition: string;
  collection_dataset: string | null;
  collectable_now: boolean;
  credentials: Array<{ name: string; configured: boolean; format_ok?: boolean; problem?: string | null }>;
  scopes: Record<string, string>;
  products: string[];
  uses: string[];
  raw_rows: number | null;
  normalized_rows: number | null;
  reference_period?: string | null;
  limitation?: string | null;
  blocker?: string | null;
}

export interface ReadinessData {
  generated_at: string;
  offline_mode: boolean;
  summary: { total_sources: number; collectable_now: number; states: Record<string, number> };
  pipeline: Array<{ id: string; label: string; value: number; detail: string }>;
  sources: ReadinessSource[];
  truth_rules: string[];
}

export interface LocalEngineStatus {
  status: string;
  model: string | null;
  provider: string;
  privacy: string;
  allowed_tasks: string[];
  prohibited_tasks: string;
  setup?: string;
}

export interface ScenarioInput {
  site_area: number;
  building_count: number;
  footprint_per_building: number;
  floors: number;
  households: number;
  population: number;
  efficiency_factor: number;
  pv_ratio: number;
  green_ratio: number;
  average_household_area: number;
}

export interface ScenarioSeries {
  electricity_kwh?: number | null;
  gas_kwh?: number | null;
  carbon_kg?: number | null;
  energy_kwh?: number | null;
  [key: string]: unknown;
}

export interface ScenarioResult {
  id?: string;
  calculations?: Record<string, unknown>;
  monthly: Array<Record<string, unknown>>;
  annual: {
    current: ScenarioSeries | null;
    scenario: ScenarioSeries | null;
    difference: ScenarioSeries | null;
    [key: string]: unknown;
  };
  current?: ScenarioSeries | Array<Record<string, unknown>>;
  scenario?: ScenarioSeries | Array<Record<string, unknown>>;
  difference?: ScenarioSeries | Array<Record<string, unknown>>;
  quality?: Quality | null;
  limitation?: string | null;
  label?: string;
  /** 서버 근거 유형 코드 (시나리오 계산은 'SCENARIO'). */
  data_class?: string;
  total_footprint?: number | null;
  gross_floor_area?: number | null;
  far?: number | null;
  bcr?: number | null;
  baseline_floor_area_m2?: number | null;
  assumptions?: string[];
}
