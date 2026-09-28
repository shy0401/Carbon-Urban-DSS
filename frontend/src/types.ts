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
  region?: RegionRef | null;
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
  /** 적용한 배출계수 (가스는 고정 규칙의 가정 계수일 수 있음). */
  carbon_factors?: Record<string, { factor: number; unit: string; source: string; notes: string; assumed: boolean }>;
  /** 시뮬레이션 기준: 격자 관측(GRID_OBSERVED) 또는 관측이 없어 지역 평균 원단위로 추정(REGION_POOLED·ALL_REGIONS_POOLED). */
  baseline_basis?: 'GRID_OBSERVED' | 'REGION_POOLED' | 'ALL_REGIONS_POOLED' | null;
  baseline_estimate?: BaselineEstimate | null;
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
export interface BaselineEstimate { basis: 'REGION_POOLED' | 'ALL_REGIONS_POOLED'; label: string; area_m2: number; parcels: number; energy_types: string[] }

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
  /** 12개월 관측 지번의 연간 가스 × 도시가스 가정 계수 (kgCO₂eq). */
  gas_carbon_kg_annual?: number | null;
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
  /** [west, south, east, north] of the study region (EPSG:4326). */
  bbox?: [number, number, number, number] | null;
  region?: RegionRef & { status?: string; grids?: number };
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
  /** Model that writes the area summary paragraph (fine-tuned when set); evidence selection uses `model`. */
  narrative_model?: string | null;
  narrative_status?: string;
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
  /** Grid the scenario was saved for (the selected one, or the default sector). */
  grid_id?: string | null;
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
  /** '조례 기본 상한 이내 (1차 확인)' 등 서버 판정 문구. */
  legal_status?: string;
  zoning_check?: ZoningCheck | null;
  /** 이 격자 관측 기준(GRID_OBSERVED) 또는 지역 평균 원단위 추정. */
  baseline_basis?: 'GRID_OBSERVED' | 'REGION_POOLED' | 'ALL_REGIONS_POOLED' | null;
  baseline_estimate?: BaselineEstimate | null;
}

export interface ZoningZone {
  zone: string | null; zone_name?: string | null; share: number | null; bcr_limit: number | null; far_limit: number | null;
  applied_far_limit?: number | null; applied_bcr_limit?: number | null; note?: string | null;
  /** 이 용도지역에 쓴 근거: 조례 값, 시행령 상한, 또는 필드별로 섞임. */
  basis?: 'ORDINANCE' | 'DECREE' | 'MIXED';
  /** 국토계획법 제79조 등으로 가정한 경우 그 설명 (미세분·미지정·자료 없는 부분). */
  assumed?: string | null;
  /** 용도지역 자료가 없는 대지 부분 (제79조 제1항 가정). */
  gap?: boolean;
  applied_notes?: string[];
}
export interface ZoningSpecial {
  collected: boolean; zoning_other_collected?: boolean;
  greenbelt: { area_m2: number; share: number } | null;
  district_plans: Array<{ name: string | null; area_m2: number; share: number }>;
}
/** 대지와 겹치는 용도지역과 그 지역의 상한 (조례 → 시행령 → 국토계획법 제79조; GET /api/zoning/site, 시나리오 결과의 zoning_check). */
export interface ZoningCheck {
  status: 'OK' | 'PARTIAL_COVERAGE' | 'LIMIT_UNKNOWN' | 'NO_ZONING' | 'NOT_COLLECTED';
  zones: ZoningZone[];
  covered_share: number;
  bcr_limit: number | null;
  far_limit: number | null;
  mixed: boolean;
  /** 대지 전체의 근거: 조례만(ORDINANCE), 시행령만(DECREE), 섞임(MIXED). */
  basis?: 'ORDINANCE' | 'DECREE' | 'MIXED';
  /** 지역에 적용한 표: 조례를 읽은 지역(ORDINANCE) 또는 조례를 못 받은 지역(DECREE). */
  rules_kind?: 'ORDINANCE' | 'DECREE';
  ordinance_status?: string | null;
  /** 가정(제79조, 미세분)으로 둔 대지 비율 %. */
  assumed_share?: number;
  special?: ZoningSpecial;
  issuer?: { code: string; name: string; rule: string } | null;
  site_basis?: 'SITE' | 'GRID_CENTER';
  check?: {
    label: string; bcr: 'WITHIN' | 'OVER' | 'UNKNOWN'; far: 'WITHIN' | 'OVER' | 'UNKNOWN'; district_plan: boolean; notes: string[];
    basis?: 'ORDINANCE' | 'DECREE' | 'MIXED'; greenbelt?: boolean; assumed?: boolean;
    district_plan_areas?: Array<{ name: string | null; area_m2: number; share: number }>;
  };
  source?: { name: string; number?: string | null; effective?: string | null; url: string; checked?: string | null; articles?: string | null; parsed?: boolean; issuer?: string | null; issuer_rule?: string | null };
  rules?: string[];
  reason?: string;
}

/** A study region as the readers return it. */
export interface RegionRef { code: string; name: string; short_name: string }

export interface RegionStep { id: string; label: string; status: string | null; message?: string; at?: string; rows?: number; resume_at?: string }

export interface RegionSummary extends RegionRef {
  sido_name: string; status: 'NOT_PREPARED' | 'PREPARING' | 'READY' | 'PARTIAL' | string;
  legal_codes: string[]; sgis_codes?: string[]; grid_count?: number; default_grid_id?: string | null;
  center?: [number, number] | null; bbox?: [number, number, number, number] | null;
  datasets?: Record<string, { status: string; message?: string; at?: string; rows?: number }>;
  message?: string | null; updated_at?: string | null; steps?: RegionStep[]; districts?: Array<{ code: string; name: string }>;
}

export interface NationalMeta {
  admin_units: number; sigungu: number; regions: number; sgis_year: number | null; sgis_sigungu: number; sgis_emd: number;
  complexes: number; grid500_official: number; grid1k_year: number | null; grid1k_cells: number;
  sources: Record<string, { status: string; quality: string | null; collected_at: string | null; coverage: string | null } | null>;
  /** 시·군 도시·군계획 조례 수집 결과 (조례를 내는 기관 수와 상태별 개수). */
  ordinances?: { issuers: number; counts: Record<string, number> };
}

export interface RegionsResponse { default: string; regions: RegionSummary[]; national: NationalMeta; steps: Array<{ id: string; label: string }> }

export interface RegionCatalogItem { code: string; name: string; short_name: string; sido_name: string; districts: Array<{ code: string; name: string }>; study_status: string }

export interface NationalRegionProps {
  code: string; name: string; sido_name: string; districts: Array<{ code: string; name: string }>;
  population: number | null; households: number | null; density: number | null; area_km2: number | null;
  complexes: number; study_status: string; sgis_codes: string[];
}

export interface NationalOverview extends GeoJSON.FeatureCollection<GeoJSON.Geometry | null, NationalRegionProps> {
  meta: { year: number | null; regions: number; with_geometry?: number; complexes?: number; sources?: Record<string, string | null> };
}

/** A 시·도 of the province map (제주 제외). */
/** ``status`` only in the 시·도 list (the cached grid payload leaves it out). */
export interface ProvincePreparedRegion { code: string; name: string; short_name: string; status?: string; grid_count: number }
export interface ProvinceSummary {
  code: string; name: string; kind: 'PROVINCE' | 'METRO'; sgis_codes: string[]; cells: number; regions: number;
  prepared: ProvincePreparedRegion[]; excluded?: string | null;
}
export interface ProvinceList { provinces: ProvinceSummary[]; excluded: Array<{ code: string; reason: string }> }
/** GET /api/map/province/{code}: every SGIS 500m cell of one 시·도 as a number row (see ``fields``). */
export interface ProvinceGrid {
  code: string; name: string; kind: 'PROVINCE' | 'METRO'; sgis_codes: string[];
  fields: string[];
  cells: Array<Array<number | null>>;
  sigungu: Array<{ code: string; name: string | null; region: string | null }>;
  regions: ProvincePreparedRegion[];
  boundaries: GeoJSON.FeatureCollection;
  bbox: [number, number, number, number] | null;
  meta: {
    cells: number; sgis_year: number | null; complex_month: string | null; with_stats: number; no_stat: number; with_complexes: number; prepared: number;
    grid_source: string; stats_source: string; complex_source: string;
  };
}
