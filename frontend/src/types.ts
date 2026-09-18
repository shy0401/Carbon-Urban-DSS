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
}

export interface MapData {
  grids: GeoJSON.FeatureCollection;
  buildings: GeoJSON.FeatureCollection;
  boundary: GeoJSON.FeatureCollection;
  selected_sector: Sector | null;
  center?: [number, number];
  crs?: string;
  grid_size_m?: number;
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
  credentials: Array<{ name: string; configured: boolean }>;
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
  total_footprint?: number | null;
  gross_floor_area?: number | null;
  far?: number | null;
  bcr?: number | null;
  baseline_floor_area_m2?: number | null;
  assumptions?: string[];
}
