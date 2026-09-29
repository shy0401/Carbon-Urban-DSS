import type { GridProps } from '../types';
import { RAMPS, TOKENS, type RampName } from '../theme/palette';
import { USE_NAME, ZONE_NAME } from './labels';
import { formatMetric } from './format';

/** One map indicator: what it is, how it is computed, and the basis for a given grid. */
export interface MetricDef {
  key: string;
  label: string;
  unit: string;
  group: string;
  digits: number;
  /** 램프 (DESIGN.md 2.4): load = 높을수록 나쁨, gain = 높을수록 좋음, seq = 방향성 없음. */
  ramp: RampName;
  value: (p: GridProps) => number | null;
  definition: string;
  formula: string;
  basis: (p: GridProps) => string | null;
  /** Fixed class lower bounds (after the first class). Default: quantiles of the data. */
  breaks?: number[];
  source: string;
  /** 활용: 이 지표로 무엇을 판단하고 어디에 쓰는지. */
  use: string;
  note?: string;
  /** Legend/tooltip text for cells without a value (default: 자료 미확보). */
  missingLabel?: string;
}

const n = (value: unknown): number | null => (typeof value === 'number' && Number.isFinite(value) ? value : null);
const fmt = (value: number | null | undefined, unit = '', digits = 0) => formatMetric(value, unit, digits);
const GRID = '250,000 m²';
const FACTOR_YEARS = ' 배출계수(2020~2022년 평균, 2025-03-31 공표)는 2025년 이후 연도에만 적용하므로 2024년 이전을 고르면 비어 있습니다(0 아님). 여러 해를 같은 계수로 비교하려면 지역 시뮬레이션을 씁니다.';
export const SGIS_GROUP = '인구·주택 (SGIS 1km)';
export const SGIS500_GROUP = '인구·주택 (SGIS 500m)';
const SGIS500_SOURCE = 'SGIS 500m 격자 통계 (자료제공 신청분)';
const SGIS500_NOTE = '이 500m 격자 자체의 SGIS 공식 통계입니다(총괄 항목만 제공). 비밀보호를 위해 인구 부문 5 미만은 0 또는 5, 사업체 부문 3 미만은 0 또는 3으로 대체했고, 그 이상 값에도 최대 ±7(사업체 ±4)의 잡음이 있습니다. 통계가 없는 격자는 0이 아니라 결측입니다.';
const SGIS500_MISSING = '통계 없음·비공개 (0 아님)';
const small500 = (p: GridProps, key: string) => (Array.isArray(p.sgis500_small) && p.sgis500_small.includes(key) ? ' · 작은 값(0·5 또는 0·3으로 대체될 수 있음)' : '');
const sgis500Basis = (p: GridProps, key: string, extra: string | null = null) =>
  p.sgis500_status === 'OBSERVED' && n(p[`sgis500_${key}`]) !== null ? `500m 격자 ${p.sgis500_code ?? ''} · ${p.sgis500_year}년${extra ? ` · ${extra}` : ''}${small500(p, key)}` : null;
const SGIS_SOURCE = 'SGIS 격자 통계 1km (공공데이터포털 15141768)';
const SGIS_NOTE = '이 500m 격자가 속한 1km 공식 격자의 값입니다. 같은 1km 격자의 500m 격자 4개는 같은 값이며, 500m로 나눈 값이 아닙니다. 비밀보호 잡음(인구 ±7)이 들어 있습니다.';
const suspectCount = (p: GridProps) => (typeof p.electricity_suspect_parcels === 'number' ? p.electricity_suspect_parcels : 0);
const suspectNote = (p: GridProps) => (suspectCount(p) ? ` · 이상값 지번 ${suspectCount(p)}곳 제외` : '');
const sgisBasis = (p: GridProps, extra: string | null) =>
  p.sgis1k_status === 'OBSERVED' ? `1km 격자 ${p.sgis1k_code} · ${p.sgis1k_year}년${extra ? ` · ${extra}` : ''}` : null;
export const PERCENT_BREAKS = [20, 40, 60, 80];

export const REGISTER_GROUP = '건축물대장';
export const BUILDING_ENERGY_GROUP = '건물 전체 에너지 (건축HUB)';
export const METRIC_GROUPS = ['에너지 관측', '에너지 원단위', '탄소', BUILDING_ENERGY_GROUP, '도시 형태', REGISTER_GROUP, '토지이용', SGIS500_GROUP, SGIS_GROUP, '데이터 품질'] as const;

export const METRICS: MetricDef[] = [
  {
    key: 'electricity_kwh_annual', label: '연간 전력 사용량', unit: 'kWh/년', group: '에너지 관측', ramp: 'load', digits: 0,
    value: (p) => n(p.electricity_kwh_annual),
    definition: '격자 안에서 12개월 모두 관측된 지번(공동주택 단지)의 전력 사용량 합계입니다. 격자 안 모든 건물의 합이 아닙니다. 세대당 연 600kWh 미만(공용부만 계측) 또는 18,000kWh 초과(다른 건물 포함)인 지번은 이상값으로 빼고 원자료에만 남깁니다.',
    formula: 'Σ 월별 전력(kWh), 12개월 관측 지번만',
    basis: (p) => p.electricity_complete_parcels ? `12개월 관측 지번 ${p.electricity_complete_parcels}곳 합계${suspectNote(p)}${p.electricity_observed_parcels > p.electricity_complete_parcels + suspectCount(p) ? ` · 일부 월만 관측된 ${p.electricity_observed_parcels - p.electricity_complete_parcels - suspectCount(p)}곳 제외` : ''}` : null,
    source: '건축HUB 건물에너지 · K-apt 월별 에너지',
    use: '전력 수요가 큰 격자를 찾고 격자끼리 운영탄소 규모를 비교합니다. 관측된 단지만의 합이라 격자 전체 수요가 아니므로 원단위와 함께 봅니다.',
  },
  {
    key: 'gas_kwh_annual', label: '연간 가스 사용량', unit: 'kWh/년', group: '에너지 관측', ramp: 'load', digits: 0,
    value: (p) => n(p.gas_kwh_annual),
    definition: '12개월 모두 관측된 지번의 도시가스 사용량(건축HUB kWh 환산값) 합계입니다.',
    formula: 'Σ 월별 가스(kWh), 12개월 관측 지번만',
    basis: (p) => p.gas_complete_parcels ? `12개월 관측 지번 ${p.gas_complete_parcels}곳 합계` : null,
    source: '건축HUB 건물에너지',
    use: '난방(가스) 수요가 큰 격자를 찾습니다. 가스 탄소는 도시가스 가정 계수로 따로 계산합니다.',
  },
  {
    key: 'electricity_kwh_per_m2', label: '전력 원단위', unit: 'kWh/m²·년', group: '에너지 원단위', ramp: 'load', digits: 1,
    value: (p) => n(p.electricity_kwh_per_m2),
    definition: '연면적 1m²당 연간 전력 사용량입니다. 연면적은 K-apt 공표값이며 비현실적인 값(세대당 20~400m² 밖)은 제외합니다.',
    formula: 'Σ 연간 전력 ÷ Σ 연면적 (같은 지번 집합)',
    basis: (p) => p.electricity_area_m2 ? `지번 ${p.electricity_area_parcels}곳 · 연면적 ${fmt(p.electricity_area_m2, 'm²')} 기준` : null,
    source: '에너지 관측 ÷ K-apt 연면적',
    use: '규모를 뺀 전력 효율을 비교해 개선 우선순위를 정합니다. 계획 연면적에 곱하면 신축 전력 부하가 나오며, 지역 시뮬레이션의 추정 기준값으로 쓰입니다.',
  },
  {
    key: 'electricity_kwh_per_household', label: '세대당 전력', unit: 'kWh/세대·년', group: '에너지 원단위', ramp: 'load', digits: 0,
    value: (p) => n(p.electricity_kwh_per_household),
    definition: '공동주택 1세대당 연간 전력 사용량(공용 포함)입니다. 월평균은 이 값 ÷ 12입니다.',
    formula: 'Σ 연간 전력 ÷ Σ 세대수 (같은 지번 집합)',
    basis: (p) => p.electricity_households ? `지번 ${p.electricity_household_parcels}곳 · ${fmt(p.electricity_households, '세대')} 기준 · 월평균 ${fmt((p.electricity_kwh_per_household ?? 0) / 12, 'kWh', 0)}${suspectNote(p)}` : null,
    source: '에너지 관측 ÷ K-apt 세대수',
    use: '세대 규모가 다른 단지를 같은 기준으로 비교합니다. 계획 세대수에 곱해 신규 개발의 전력 수요를 가늠합니다.',
  },
  {
    key: 'gas_kwh_per_m2', label: '가스 원단위', unit: 'kWh/m²·년', group: '에너지 원단위', ramp: 'load', digits: 1,
    value: (p) => n(p.gas_kwh_per_m2),
    definition: '연면적 1m²당 연간 가스 사용량(kWh 환산)입니다.',
    formula: 'Σ 연간 가스 ÷ Σ 연면적 (같은 지번 집합)',
    basis: (p) => p.gas_area_m2 ? `지번 ${p.gas_area_parcels}곳 · 연면적 ${fmt(n(p.gas_area_m2), 'm²')} 기준` : null,
    source: '건축HUB ÷ K-apt 연면적',
    use: '난방 효율을 비교합니다. 노후 주택 비율과 함께 보면 단열 개보수 후보를 고를 수 있습니다.',
  },
  {
    key: 'electricity_carbon_t', label: '전력 탄소배출량', unit: 'tCO₂eq/년', group: '탄소', ramp: 'load', digits: 1,
    value: (p) => { const kg = n(p.electricity_carbon_kg_annual); return kg === null ? null : kg / 1000; },
    definition: `연간 전력 사용량에 국가 승인 전력 배출계수를 곱한 운영탄소입니다. 가스 탄소는 가정 계수라 '가스 탄소배출량'으로 따로 봅니다.${FACTOR_YEARS}`,
    formula: '연간 전력(kWh) × 0.4541 kgCO₂eq/kWh ÷ 1,000',
    basis: (p) => p.electricity_kwh_annual ? `${fmt(n(p.electricity_kwh_annual), 'kWh')} × 0.4541 (GIR 2024 소비단)` : null,
    source: 'GIR 2024 승인 국가 온실가스 배출계수',
    use: '격자의 전력 운영탄소 규모입니다. 감축 목표를 세울 때 기준 배출량으로 씁니다.',
  },
  {
    key: 'gas_carbon_t', label: '가스 탄소배출량 (가정 계수)', unit: 'tCO₂eq/년', group: '탄소', ramp: 'load', digits: 1,
    value: (p) => { const kg = n(p.gas_carbon_kg_annual); return kg === null ? null : kg / 1000; },
    definition: '12개월 관측 지번의 연간 도시가스 사용량에 고정 규칙의 가정 계수를 곱한 운영탄소입니다. 계수는 IPCC 2006 천연가스 기본 배출계수(CO₂·CH₄·N₂O, AR5 GWP)를 건축HUB kWh가 총발열량 기준이라고 보고 환산한 값이며, 순발열량 기준이면 약 11% 커집니다.',
    formula: '연간 가스(kWh) × 0.1826 kgCO₂eq/kWh (가정) ÷ 1,000',
    basis: (p) => p.gas_kwh_annual ? `${fmt(n(p.gas_kwh_annual), 'kWh')} × 0.1826 (가정 계수)` : null,
    source: 'IPCC 2006 기본 배출계수 · 에너지법 시행규칙 발열량 (가정)',
    use: '난방 탄소가 큰 격자를 찾습니다. 공식 가스 계수가 아니므로 전력 탄소와 합칠 때 가정임을 함께 적습니다.',
  },
  {
    key: 'electricity_carbon_kg_per_m2', label: '전력 탄소 원단위', unit: 'kgCO₂eq/m²·년', group: '탄소', ramp: 'load', digits: 1,
    value: (p) => n(p.electricity_carbon_kg_per_m2),
    definition: `연면적 1m²당 연간 전력 탄소배출량입니다.${FACTOR_YEARS}`,
    formula: '전력 원단위(kWh/m²) × 0.4541',
    basis: (p) => p.electricity_area_m2 ? `지번 ${p.electricity_area_parcels}곳 · 연면적 ${fmt(p.electricity_area_m2, 'm²')} 기준` : null,
    source: '전력 원단위 × GIR 계수',
    use: '연면적당 탄소로 효율을 비교하고, 신축에 요구할 목표 원단위를 정할 때 참고합니다.',
  },
  {
    key: 'bldg_electricity_kwh', label: '건물 전체 연간 전력', unit: 'kWh/년', group: BUILDING_ENERGY_GROUP, ramp: 'load', digits: 0,
    value: (p) => n(p.bldg_electricity_kwh),
    definition: '격자 안에서 12개월 모두 계측된 모든 지번(상가·업무·학교·대형 공동주택 등)의 전력 합계입니다. 건축HUB가 단독주택, 200세대 미만 공동주택, 산업·수송·발전용은 제공하지 않으므로 격자 전체 소비는 아닙니다. 지번은 연속지적 필지의 대표점으로 격자에 놓습니다.',
    formula: 'Σ 월별 전력(kWh), 12개월 계측 지번, 필지 대표점이 격자 안',
    basis: (p) => (p.bldg_electricity_complete ? `12개월 계측 지번 ${p.bldg_electricity_complete}곳 · 계측 지번 전체 ${fmt(n(p.bldg_parcels), '곳')}` : null),
    source: '건축HUB 건물에너지 (법정동 단위 전 지번)',
    use: '공동주택만이 아닌 격자의 건물 전력 수요를 봅니다. 도시 탄소 지도의 기본 배출 규모이며, 상업·업무가 몰린 격자를 찾는 데 씁니다.',
  },
  {
    key: 'bldg_gas_kwh', label: '건물 전체 연간 가스', unit: 'kWh/년', group: BUILDING_ENERGY_GROUP, ramp: 'load', digits: 0,
    value: (p) => n(p.bldg_gas_kwh),
    definition: '격자 안에서 12개월 모두 계측된 모든 지번의 도시가스 사용량(kWh 환산) 합계입니다.',
    formula: 'Σ 월별 가스(kWh), 12개월 계측 지번',
    basis: (p) => (p.bldg_gas_complete ? `12개월 계측 지번 ${p.bldg_gas_complete}곳` : null),
    source: '건축HUB 건물에너지 (법정동 단위 전 지번)',
    use: '건물 난방 수요가 큰 격자를 찾습니다. 건물 전체 가스 탄소는 아직 지도 지표로 두지 않았습니다.',
  },
  {
    key: 'bldg_kwh_per_m2', label: '건물 전체 전력 원단위', unit: 'kWh/m²·년', group: BUILDING_ENERGY_GROUP, ramp: 'load', digits: 1,
    value: (p) => n(p.bldg_kwh_per_m2),
    definition: '12개월 계측 지번의 전력을 같은 필지의 건축물대장 연면적으로 나눈 값입니다. 2~1,500 kWh/m² 밖(부분 계측·면적 불일치)인 지번은 뺍니다.',
    formula: 'Σ 연간 전력 ÷ Σ 대장 연면적 (같은 지번 집합)',
    basis: (p) => (p.bldg_area_parcels ? `지번 ${p.bldg_area_parcels}곳 · 연면적 ${fmt(n(p.bldg_area_m2), 'm²')}${p.bldg_suspect ? ` · 이상값 ${p.bldg_suspect}곳 제외` : ''}` : null),
    source: '건축HUB 건물에너지 ÷ 건축물대장 연면적',
    use: '용도가 섞인 격자끼리 전력 효율을 비교합니다. 주거 연면적 비율과 함께 보면 상업 비중 때문에 높은지 알 수 있습니다.',
  },
  {
    key: 'bldg_carbon_t', label: '건물 전체 전력 탄소', unit: 'tCO₂eq/년', group: BUILDING_ENERGY_GROUP, ramp: 'load', digits: 1,
    value: (p) => n(p.bldg_carbon_t),
    definition: `건물 전체 연간 전력에 국가 승인 전력 배출계수를 곱한 운영탄소입니다. 가스 탄소는 포함하지 않습니다.${FACTOR_YEARS}`,
    formula: '건물 전체 연간 전력(kWh) × 0.4541 ÷ 1,000',
    basis: (p) => (p.bldg_electricity_kwh ? `${fmt(n(p.bldg_electricity_kwh), 'kWh')} × 0.4541` : null),
    source: 'GIR 2024 승인 국가 온실가스 배출계수',
    use: '격자별 건물 전력 운영탄소 규모입니다. 도시 단위 감축 목표와 우선 지역을 정할 때 씁니다.',
  },
  {
    key: 'building_count', label: '건물 수', unit: '동', group: '도시 형태', ramp: 'seq', digits: 0,
    value: (p) => n(p.building_count),
    definition: '대표점이 격자 안에 있는 건물 수입니다. 공식 도로명주소 건물(VWorld)이 없으면 OSM 공동주택 윤곽으로 대체합니다.',
    formula: '격자 안 건물 대표점 개수',
    basis: (p) => p.building_source === 'OSM' ? 'OSM 공동주택 윤곽만 포함 (전체 건물 아님)' : p.building_count !== null ? `밀도 ${fmt(n(p.building_density), '동/km²', 0)}` : null,
    source: 'VWorld LT_C_SPBD (대체: OSM)',
    use: '개발 밀도와 필지가 얼마나 잘게 나뉘었는지 봅니다. 건물은 많은데 에너지 관측이 없으면 소규모 건물 위주라 관측 공백입니다.',
  },
  {
    key: 'coverage_pct', label: '건폐율 근사', unit: '%', group: '도시 형태', ramp: 'seq', digits: 1,
    value: (p) => n(p.coverage_pct), breaks: [5, 10, 20, 30],
    definition: '격자 면적 중 건물이 덮은 면적의 비율입니다. 필지 대지면적 기준의 법정 건폐율과는 다릅니다.',
    formula: `Σ 건축면적 ÷ ${GRID} × 100`,
    basis: (p) => p.footprint_m2 !== null ? `건축면적 ${fmt(p.footprint_m2, 'm²')} ÷ ${GRID}` : null,
    source: 'VWorld 건물 윤곽 면적',
    use: '땅을 건물이 얼마나 덮었는지 보고 추가 개발이나 녹지 여력을 가늠합니다.',
  },
  {
    key: 'far_est_pct', label: '추정 용적률', unit: '%', group: '도시 형태', ramp: 'seq', digits: 1,
    value: (p) => n(p.far_est_pct), breaks: [25, 50, 100, 200],
    definition: '건축면적 × 지상층수로 추정한 연면적을 격자 면적으로 나눈 값입니다. 층수가 없는 건물은 빠지며 법정 용적률이 아닙니다.',
    formula: `Σ(건축면적 × 지상층수) ÷ ${GRID} × 100`,
    basis: (p) => p.floor_area_est_m2 !== null ? `추정 연면적 ${fmt(p.floor_area_est_m2, 'm²')} · 층수 확인 ${fmt(p.floors_known_pct, '%', 0)}` : null,
    source: 'VWorld 건물 윤곽 × 지상층수',
    use: '연면적 규모로 본 개발 밀도입니다. 추가 개발 여지를 가늠하는 데 씁니다. 건축물대장이 있으면 공식 연면적 기반 용적률을 우선 봅니다.',
  },
  {
    key: 'avg_floors', label: '평균 지상층수', unit: '층', group: '도시 형태', ramp: 'seq', digits: 1,
    value: (p) => n(p.avg_floors), breaks: [2, 4, 8, 15],
    definition: '층수가 기록된 건물의 지상층수 평균입니다.',
    formula: 'Σ 지상층수 ÷ 층수 확인 건물 수',
    basis: (p) => p.avg_floors !== null ? `최고 ${fmt(p.max_floors, '층')} · 층수 확인 ${fmt(p.floors_known_pct, '%', 0)}` : null,
    source: 'VWorld 건물 지상층수',
    use: '고층 공동주택 지역과 저층 주거지를 구분하고 스카이라인·일조 검토에 씁니다.',
  },
  {
    key: 'complex_households', label: '공동주택 세대수', unit: '세대', group: '도시 형태', ramp: 'seq', digits: 0,
    value: (p) => n(p.complex_households),
    definition: '위치가 격자 안에 있는 K-apt 의무관리 공동주택 단지의 세대수 합계입니다.',
    formula: 'Σ 단지 세대수',
    basis: (p) => p.complex_count ? `단지 ${p.complex_count}개` : null,
    source: 'K-apt 공동주택 기본정보',
    use: '공동주택 세대 규모를 보고, 인구 대신 세대 기준으로 부하를 추정합니다.',
  },
  {
    key: 'complex_count', label: '공동주택 단지 수', unit: '단지', group: '도시 형태', ramp: 'seq', digits: 0, breaks: [1, 2, 4, 8],
    // 단지 목록을 격자에 놓은 결과라 단지가 없는 격자의 0은 실제 0입니다.
    value: (p) => n(p.complex_count),
    definition: '좌표가 격자 안에 있는 K-apt 의무관리 공동주택 단지 수입니다. 상세 자료를 받기 전 지역은 전국 단지 목록 좌표로 셉니다.',
    formula: 'count(단지 좌표 ∈ 격자)',
    basis: () => null,
    source: 'K-apt 공동주택 기본정보·전국 단지 목록',
    use: '아파트 단지가 모인 곳을 찾고, 세대수·연면적을 받기 전 지역의 공동주택 분포를 봅니다.',
  },
  {
    key: 'reg_far_pct', label: '용적률 (건축물대장)', unit: '%', group: REGISTER_GROUP, ramp: 'seq', digits: 1,
    value: (p) => n(p.reg_far_pct), breaks: [25, 50, 100, 200],
    definition: `격자 안 건물의 공식 용적률산정연면적(건축물대장)을 격자 면적으로 나눈 값입니다. 필지 대지면적 기준의 법정 용적률과 다르지만, 층수로 추정한 용적률보다 정확합니다. 소수점이 밀린 오기처럼 건축면적×층수나 연면적과 맞지 않는 값은 빼고(0이 아님) 계산합니다.`,
    formula: `Σ 용적률산정연면적 ÷ ${GRID} × 100`,
    basis: (p) => (p.reg_buildings ? `대장 건물 ${fmt(n(p.reg_buildings), '동')} · 연면적 ${fmt(n(p.reg_gfa_m2), 'm²')}${p.reg_area_issues ? ` · 면적 오기 ${p.reg_area_issues}동 제외` : ''}` : null),
    source: '건축HUB 건축물대장 표제부',
    use: '공식 연면적으로 본 개발 밀도입니다. 추가 개발 여지와 에너지 부하 추정의 연면적 근거로 씁니다.',
  },
  {
    key: 'reg_residential_gfa_pct', label: '주거 연면적 비율', unit: '%', group: REGISTER_GROUP, ramp: 'seq', digits: 1,
    value: (p) => n(p.reg_residential_gfa_pct), breaks: PERCENT_BREAKS,
    definition: '주용도가 확인된 대장 건물의 연면적 중 단독·공동주택의 비율입니다.',
    formula: '주거 연면적 ÷ 용도 확인 연면적 × 100',
    basis: (p) => (p.reg_use_gfa_pct && typeof p.reg_use_gfa_pct === 'object' ? Object.entries(p.reg_use_gfa_pct as Record<string, number>).slice(0, 3).map(([k, v]) => `${k} ${v.toFixed(1)}%`).join(' · ') : null),
    source: '건축HUB 건축물대장 표제부',
    use: '주거와 상업·업무가 얼마나 섞였는지 봅니다. 상업이 섞인 격자는 전력 원단위가 높게 나오므로 해석할 때 함께 봅니다.',
  },
  {
    key: 'reg_old_gfa_pct', label: '2000년 이전 준공 연면적 비율', unit: '%', group: REGISTER_GROUP, ramp: 'seq', digits: 1,
    value: (p) => n(p.reg_old_gfa_pct), breaks: PERCENT_BREAKS,
    definition: '사용승인일이 확인된 대장 건물의 연면적 중 1999년 이전에 사용승인된 비율입니다(모든 용도).',
    formula: '1999년 이전 사용승인 연면적 ÷ 사용승인일 확인 연면적 × 100',
    basis: (p) => (p.reg_buildings ? `대장 건물 ${fmt(n(p.reg_buildings), '동')}` : null),
    source: '건축HUB 건축물대장 표제부',
    use: '노후 건물이 많은 곳, 곧 그린리모델링·개보수 우선 지역을 찾습니다.',
  },
  {
    key: 'residential_zone_ratio', label: '주거지역 비율', unit: '%', group: '토지이용', ramp: 'seq', digits: 1,
    value: (p) => n(p.residential_zone_ratio), breaks: PERCENT_BREAKS,
    definition: '격자 면적 중 법정 주거지역(제1·2·3종 일반주거 등) 도형과 겹치는 면적의 비율입니다.',
    formula: `주거지역 ∩ 격자 면적 ÷ ${GRID} × 100`,
    basis: (p) => p.zone_shares ? Object.entries(p.zone_shares).sort((a, b) => b[1] - a[1]).map(([k, v]) => `${ZONE_NAME[k] ?? k} ${v.toFixed(1)}%`).join(' · ') : null,
    source: 'VWorld LT_C_UQ111 용도지역',
    use: '법정 용도지역 구성으로 허용되는 개발 유형을 1차로 확인합니다(법적 판단은 별도). 주거지역인데 원단위가 높은 곳은 주거 에너지 개선 대상입니다.',
  },
  {
    key: 'residential_building_share', label: '주거용 건물 비중', unit: '%', group: '토지이용', ramp: 'seq', digits: 1,
    value: (p) => n(p.residential_building_share), breaks: PERCENT_BREAKS,
    definition: '용도가 확인된 건물의 건축면적 중 주거용(단독·공동주택)의 비율입니다. VWorld 도로명주소 건물 레이어에는 용도코드가 없어 대부분 결측이며, 건축물대장을 받으면 "주거 연면적 비율"을 대신 씁니다.',
    formula: '주거용 건축면적 ÷ 용도 확인 건축면적 × 100',
    basis: (p) => p.use_share_pct ? Object.entries(p.use_share_pct).sort((a, b) => b[1] - a[1]).slice(0, 3).map(([k, v]) => `${USE_NAME[k] ?? k} ${v.toFixed(1)}%`).join(' · ') : null,
    source: 'VWorld 건물용도코드',
    use: '실제 건물 쓰임을 용도지역과 비교합니다.',
  },
  {
    key: 'sgis500_population', label: '인구', unit: '명', group: SGIS500_GROUP, ramp: 'seq', digits: 0,
    value: (p) => (p.sgis500_status === 'OBSERVED' ? n(p.sgis500_population) : null),
    definition: `${SGIS500_NOTE} 총인구(내국인·외국인 포함, 인구주택총조사 등록센서스 기준)입니다.`,
    formula: '500m 격자 총인구(to_in_001)', missingLabel: SGIS500_MISSING,
    basis: (p) => sgis500Basis(p, 'population', n(p.sgis500_pop_density) !== null ? `밀도 ${fmt(p.sgis500_pop_density, '명/km²')}` : null),
    breaks: [25, 250, 1250, 2500], source: SGIS500_SOURCE,
    use: '사람이 실제로 사는 500m 격자를 찾고, 에너지 관측이 없는 격자의 생활 수요 규모를 가늠합니다. 1km 값보다 동네 단위 차이가 잘 드러납니다.',
  },
  {
    key: 'sgis500_households', label: '가구', unit: '가구', group: SGIS500_GROUP, ramp: 'seq', digits: 0,
    value: (p) => (p.sgis500_status === 'OBSERVED' ? n(p.sgis500_households) : null),
    definition: `${SGIS500_NOTE} 일반가구 수입니다.`,
    formula: '500m 격자 총가구(to_ga_001)', missingLabel: SGIS500_MISSING,
    basis: (p) => sgis500Basis(p, 'households'), breaks: [10, 100, 500, 1000], source: SGIS500_SOURCE,
    use: '주거 에너지 수요 단위(가구)가 몰린 곳을 봅니다. 세대당 전력과 함께 보면 관측 단지가 격자 가구의 얼마를 대표하는지 알 수 있습니다.',
  },
  {
    key: 'sgis500_housing', label: '주택', unit: '호', group: SGIS500_GROUP, ramp: 'seq', digits: 0,
    value: (p) => (p.sgis500_status === 'OBSERVED' ? n(p.sgis500_housing) : null),
    definition: `${SGIS500_NOTE} 총주택(거처) 수입니다.`,
    formula: '500m 격자 총주택(to_ho_001)', missingLabel: SGIS500_MISSING,
    basis: (p) => sgis500Basis(p, 'housing'), breaks: [10, 100, 500, 1000], source: SGIS500_SOURCE,
    use: '주택 재고가 많은 곳, 개보수 대상 주택이 모인 곳을 찾습니다.',
  },
  {
    key: 'sgis500_workers', label: '종사자', unit: '명', group: SGIS500_GROUP, ramp: 'seq', digits: 0,
    value: (p) => (p.sgis500_status === 'OBSERVED' ? n(p.sgis500_workers) : null),
    definition: `${SGIS500_NOTE} 사업체 종사자 수(사업체 부문, 잡음 ±4)입니다.`,
    formula: '500m 격자 총종사자(to_em_020)', missingLabel: SGIS500_MISSING,
    basis: (p) => sgis500Basis(p, 'workers', n(p.sgis500_businesses) !== null ? `사업체 ${fmt(p.sgis500_businesses, '곳')}` : null),
    breaks: [25, 125, 500, 1250], source: SGIS500_SOURCE,
    use: '상업·업무·산업 활동이 몰린 격자(비주거 에너지 수요)를 찾습니다. 주거 원단위에 상업이 섞였는지 판단할 때도 씁니다.',
  },
  {
    key: 'sgis500_pop_change_pct', label: '인구 증감률', unit: '%', group: SGIS500_GROUP, ramp: 'diff', digits: 1,
    value: (p) => (p.sgis500_status === 'OBSERVED' ? n(p.sgis500_pop_change_pct) : null), breaks: [-20, -5, 5, 20],
    definition: `${SGIS500_NOTE} 기준연도(2015년)와 최근 연도의 500m 격자 총인구를 비교합니다. 두 해 모두 20명 이상일 때만 내며(작은 값 대체·잡음 때문), 그렇지 않으면 결측입니다.`,
    formula: '(최근 연도 총인구 − 2015년 총인구) ÷ 2015년 총인구 × 100', missingLabel: '두 해 중 20명 미만 또는 통계 없음 (0 아님)',
    basis: (p) => (n(p.sgis500_pop_change_pct) !== null ? `${p.sgis500_base_year}년 ${fmt(p.sgis500_base_population, '명')} → ${p.sgis500_year}년 ${fmt(p.sgis500_population, '명')}` : null),
    source: SGIS500_SOURCE,
    use: '인구가 빠지는 곳(수요 감소·빈집)과 느는 곳(신규 개발)을 가려, 에너지 사용 변화가 인구 때문인지 원단위 때문인지 나눠 봅니다.',
  },
  {
    key: 'sgis_pop_density', label: '인구밀도', unit: '명/km²', group: SGIS_GROUP, ramp: 'seq', digits: 0,
    value: (p) => n(p.sgis_pop_density),
    definition: `${SGIS_NOTE} 1km 격자는 1km²이므로 총인구가 곧 인구밀도입니다. 통계가 없는 격자(인구가 없거나 비공개)는 0이 아니라 결측으로 둡니다.`,
    formula: '1km 격자 총인구(to_in_001) ÷ 1 km²',
    basis: (p) => sgisBasis(p, p.sgis1k_households != null ? `가구 ${fmt(p.sgis1k_households, '')}` : null),
    breaks: [100, 1000, 5000, 10000], source: SGIS_SOURCE,
    use: '인구가 많은 곳의 생활 에너지 수요와 공공시설 배치를 검토합니다. 에너지 관측이 없는 격자에서도 수요 규모를 가늠할 수 있습니다.',
  },
  {
    key: 'sgis_housing_density', label: '주택밀도', unit: '호/km²', group: SGIS_GROUP, ramp: 'seq', digits: 0,
    value: (p) => n(p.sgis_housing_density),
    definition: `${SGIS_NOTE} 주택은 총주택(거처) 수입니다.`,
    formula: '1km 격자 총주택(to_ho_001) ÷ 1 km²',
    basis: (p) => sgisBasis(p, null),
    breaks: [50, 500, 2000, 4000], source: SGIS_SOURCE,
    use: '주택이 얼마나 밀집했는지로 주거 에너지 수요 규모를 봅니다.',
  },
  {
    key: 'sgis_worker_density', label: '종사자밀도', unit: '명/km²', group: SGIS_GROUP, ramp: 'seq', digits: 0,
    value: (p) => n(p.sgis_worker_density),
    definition: `${SGIS_NOTE} 종사자는 사업체 종사자 수(사업체 부문 잡음 ±4)입니다. 상업·업무 활동의 크기를 봅니다.`,
    formula: '1km 격자 총종사자(to_em_020) ÷ 1 km²',
    basis: (p) => sgisBasis(p, p.sgis1k_businesses != null ? `사업체 ${fmt(p.sgis1k_businesses, '곳')}` : null),
    breaks: [100, 500, 2000, 5000], source: SGIS_SOURCE,
    use: '상업·업무 활동의 크기입니다. 주간 전력 수요, 그리고 주거 원단위에 상업이 섞였는지 판단할 때 씁니다.',
  },
  {
    key: 'sgis_elderly_pct', label: '65세 이상 비율', unit: '%', group: SGIS_GROUP, ramp: 'seq', digits: 1,
    value: (p) => n(p.sgis_elderly_pct), breaks: [15, 25, 35, 45],
    definition: `${SGIS_NOTE} 연령별 인구 합이 20명 미만이면 잡음이 커서 비율을 내지 않습니다.`,
    formula: '65세 이상 인구(in_age_014~021) ÷ 연령별 인구 합 × 100',
    basis: (p) => sgisBasis(p, null), source: SGIS_SOURCE,
    use: '냉난방 취약계층이 많은 곳을 찾아 에너지 복지 우선 지역을 정합니다.',
  },
  {
    key: 'sgis_single_household_pct', label: '1인가구 비율', unit: '%', group: SGIS_GROUP, ramp: 'seq', digits: 1,
    value: (p) => n(p.sgis_single_household_pct), breaks: [25, 35, 45, 60],
    definition: `${SGIS_NOTE} 총가구가 20 미만이면 비율을 내지 않습니다.`,
    formula: '1인가구(ga_sd_005) ÷ 총가구(to_ga_001) × 100',
    basis: (p) => sgisBasis(p, null), source: SGIS_SOURCE,
    use: '세대당 에너지를 해석할 때 참고합니다(1인가구는 세대당 사용량이 낮음). 소형 주택 수요도 봅니다.',
  },
  {
    key: 'sgis_old_housing_pct', label: '2000년 이전 주택 비율', unit: '%', group: SGIS_GROUP, ramp: 'seq', digits: 1,
    value: (p) => n(p.sgis_old_housing_pct), breaks: PERCENT_BREAKS,
    definition: `${SGIS_NOTE} 1999년 이전에 지어진 주택의 비율입니다. 노후 주택이 많은 곳은 개보수 효과를 검토할 후보입니다.`,
    formula: '건축연도 1999년 이전 주택(ho_yr_001~003) ÷ 건축연도별 주택 합 × 100',
    basis: (p) => sgisBasis(p, null), source: SGIS_SOURCE,
    use: '노후 주택이 많은 곳은 단열 개보수(그린리모델링) 우선 지역입니다.',
  },
  {
    key: 'sgis_apartment_pct', label: '아파트 비율', unit: '%', group: SGIS_GROUP, ramp: 'seq', digits: 1,
    value: (p) => n(p.sgis_apartment_pct), breaks: PERCENT_BREAKS,
    definition: `${SGIS_NOTE} K-apt 에너지 관측이 대표하는 범위(아파트)가 격자 주택의 얼마인지 볼 때 씁니다.`,
    formula: '아파트(ho_gb_003) ÷ 주택 유형별 합 × 100',
    basis: (p) => sgisBasis(p, null), source: SGIS_SOURCE,
    use: 'K-apt·건축HUB 관측(아파트)이 격자 주택을 얼마나 대표하는지 봅니다. 낮으면 관측이 격자를 잘 대표하지 못합니다.',
  },
  {
    key: 'completeness', label: '에너지 관측 완전성', unit: '%', group: '데이터 품질', ramp: 'gain', digits: 0,
    value: (p) => (p.electricity_months || p.gas_months ? n(p.completeness) : null), breaks: [25, 50, 75, 100],
    definition: '전력 12개월과 가스 12개월 중 관측이 있는 달의 비율입니다. 관측이 전혀 없는 격자는 결측(회색)으로 둡니다.',
    formula: '(전력 관측 월 + 가스 관측 월) ÷ 24 × 100',
    basis: (p) => `전력 ${p.electricity_months}/12개월 · 가스 ${p.gas_months}/12개월`,
    source: '에너지 관측 월 수',
    use: '이 격자 에너지 값의 신뢰도입니다. 낮으면 에너지 지표를 조심해서 해석합니다.',
  },
];

export { USE_COLORS, USE_NAME, USE_ORDER, ZONE_NAME } from './labels';

/** 결측 격자의 바탕색. 그 위에 해치 패턴 레이어를 겹친다(램프 최저색과 구분). */
export const MISSING_FILL = TOKENS['prov-missing-bg'];

export interface MetricClass { color: string; from: number; to: number; count: number }
export interface Classification { classes: MetricClass[]; lowerBounds: number[]; valued: number; missing: number; min: number | null; max: number | null }

/** Lower bounds for classes 2..k from quantiles of the values (distinct, increasing). */
export function quantileBounds(values: number[], classes = 5): number[] {
  const sorted = [...values].sort((a, b) => a - b);
  if (sorted.length < 2) return [];
  const bounds: number[] = [];
  for (let i = 1; i < classes; i++) {
    const q = sorted[Math.min(sorted.length - 1, Math.floor((i * sorted.length) / classes))];
    if (q > sorted[0] && (bounds.length === 0 || q > bounds[bounds.length - 1])) bounds.push(nice(q));
  }
  return [...new Set(bounds)].filter((b) => b > sorted[0]);
}

/** Two significant digits so class bounds read cleanly (1,234 → 1,200; 0.456 → 0.46). */
function nice(value: number): number {
  return value === 0 ? 0 : Number(value.toPrecision(2));
}

/** Classes for the legend and the map. Values equal to a lower bound fall in the upper class. */
export function classify(values: Array<number | null>, fixed?: number[], ramp: RampName = 'seq'): Classification {
  const valid = values.filter((v): v is number => v !== null && Number.isFinite(v));
  const missing = values.length - valid.length;
  if (!valid.length) return { classes: [], lowerBounds: [], valued: 0, missing, min: null, max: null };
  // No spread: a 시·도 has up to ~75,000 cells, more than Math.min(...values) accepts safely.
  let min = valid[0], max = valid[0];
  for (const v of valid) { if (v < min) min = v; if (v > max) max = v; }
  const lowerBounds = (fixed ?? quantileBounds(valid)).filter((b) => b > min || fixed !== undefined);
  const colors = pickColors(lowerBounds.length + 1, RAMPS[ramp]);
  const edges = [min, ...lowerBounds];
  const classes = edges.map((from, i) => ({ color: colors[i], from: i === 0 ? min : from, to: i < lowerBounds.length ? lowerBounds[i] : max, count: 0 }));
  for (const value of valid) classes[classIndex(value, lowerBounds)].count += 1;
  return { classes, lowerBounds, valued: valid.length, missing, min, max };
}

export function classIndex(value: number, lowerBounds: number[]): number {
  let index = 0;
  for (const bound of lowerBounds) if (value >= bound) index += 1;
  return index;
}

function pickColors(count: number, ramp: string[]): string[] {
  if (count >= ramp.length) return ramp.slice(0, count);
  if (count === 1) return [ramp[3]];
  const step = (ramp.length - 1) / (count - 1);
  return Array.from({ length: count }, (_, i) => ramp[Math.round(i * step)]);
}

/** MapLibre fill color: explicit missing branch (hatch layer drawn on top), then a step ramp on the class bounds. */
export function stepColor(property: string, classification: Classification): unknown[] {
  const colors = classification.classes.map((c) => c.color);
  if (!colors.length) return ['case', ['==', ['get', property], null], MISSING_FILL, MISSING_FILL];
  // 값 있는 격자가 한 구간뿐이면 경계가 없다. MapLibre step은 경계가 1개 이상 필요하므로 단색으로 칠한다.
  if (!classification.lowerBounds.length) return ['case', ['==', ['get', property], null], MISSING_FILL, colors[0]];
  const step: unknown[] = ['step', ['to-number', ['get', property]], colors[0]];
  classification.lowerBounds.forEach((bound, i) => step.push(bound, colors[i + 1]));
  return ['case', ['==', ['get', property], null], MISSING_FILL, step];
}

/** Features with derived metric values stored under their metric key (e.g. tCO₂eq). */
export function withMetricValues(collection: GeoJSON.FeatureCollection<GeoJSON.Geometry, GridProps>): GeoJSON.FeatureCollection<GeoJSON.Geometry, GridProps> {
  return {
    ...collection,
    features: collection.features.map((feature) => {
      const props = { ...(feature.properties as GridProps) };
      for (const metric of METRICS) props[metric.key] = metric.value(props);
      return { ...feature, properties: props };
    }),
  };
}

export function rangeLabel(item: MetricClass, digits: number, last: boolean): string {
  const f = (v: number) => formatMetric(v, '', digits);
  if (item.from === item.to) return f(item.from);
  // 고정 구간이 값 범위 밖이면 빈 구간: 첫 구간은 '경계 미만', 마지막 구간은 '경계 이상'으로 적는다.
  if (item.to < item.from) return last ? `${f(item.from)} 이상` : `${f(item.to)} 미만`;
  return last ? `${f(item.from)} ~ ${f(item.to)}` : `${f(item.from)} ~ ${f(item.to)} 미만`;
}
