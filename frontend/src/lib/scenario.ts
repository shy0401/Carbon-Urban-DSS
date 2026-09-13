import type { ScenarioInput } from '../types';

export type ScenarioErrors = Partial<Record<keyof ScenarioInput, string>>;

export function validateScenario(input: ScenarioInput): ScenarioErrors {
  const errors: ScenarioErrors = {};
  for (const [key, value] of Object.entries(input) as Array<[keyof ScenarioInput, number]>) {
    if (!Number.isFinite(value) || value < 0) errors[key] = '0 이상의 숫자를 입력하세요.';
  }
  if (input.site_area <= 0) errors.site_area = '대지면적은 0보다 커야 합니다.';
  if (input.building_count < 1) errors.building_count = '건물 수는 1개 이상이어야 합니다.';
  for (const key of ['building_count','floors','households','population'] as const) {
    if (!Number.isInteger(input[key])) errors[key]='정수를 입력하세요.';
  }
  if (input.site_area>250000) errors.site_area='분석 셀 면적 250,000m² 이내로 입력하세요.';
  if (input.footprint_per_building<=0) errors.footprint_per_building='건축면적은 0보다 커야 합니다.';
  if (input.building_count*input.footprint_per_building+input.site_area*input.green_ratio>input.site_area) errors.green_ratio='건축면적과 녹지면적 합계가 부지를 초과합니다.';
  if(input.households*input.average_household_area>input.building_count*input.footprint_per_building*input.floors) errors.households='입력 세대수의 면적 수요가 연면적을 초과합니다.';
  if (input.floors < 3 || input.floors > 40) errors.floors = '층수는 3층부터 40층까지 입력하세요.';
  if (input.efficiency_factor <= 0 || input.efficiency_factor > 2) errors.efficiency_factor = '효율 계수는 0 초과 2 이하로 입력하세요.';
  if (input.pv_ratio < 0 || input.pv_ratio > 1) errors.pv_ratio = '태양광 비율은 0부터 1 사이여야 합니다.';
  if (input.green_ratio < 0 || input.green_ratio > 1) errors.green_ratio = '녹지 비율은 0부터 1 사이여야 합니다.';
  if (input.average_household_area <= 0) errors.average_household_area = '평균 세대면적은 0보다 커야 합니다.';
  if (input.building_count * input.footprint_per_building > input.site_area) {
    errors.footprint_per_building = '전체 건축면적이 대지면적을 초과합니다.';
  }
  return errors;
}
