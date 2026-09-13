import { describe, expect, it } from 'vitest';
import { validateScenario } from './scenario';

const valid = {
  site_area: 10000,
  building_count: 4,
  footprint_per_building: 700,
  floors: 12,
  households: 240,
  population: 560,
  efficiency_factor: 0.85,
  pv_ratio: 0.2,
  green_ratio: 0.25,
  average_household_area: 84,
};

describe('validateScenario', () => {
  it('층수 범위 3~40을 허용한다', () => {
    expect(validateScenario({ ...valid, floors: 3, households: 50 })).toEqual({});
    expect(validateScenario({ ...valid, floors: 40 })).toEqual({});
  });

  it('층수 범위를 벗어나거나 건폐면적이 대지면적을 넘으면 설명을 반환한다', () => {
    expect(validateScenario({ ...valid, floors: 41 })).toMatchObject({ floors: expect.any(String) });
    expect(validateScenario({ ...valid, building_count: 20, footprint_per_building: 700 })).toMatchObject({ footprint_per_building: expect.any(String) });
  });
});

 it('부지 녹지와 수용 세대 제약을 브라우저에서도 검사한다',()=>{
   expect(validateScenario({...valid,green_ratio:1}).green_ratio).toBeTruthy();
   expect(validateScenario({...valid,households:100000}).households).toBeTruthy();
   expect(validateScenario({...valid,floors:3.5}).floors).toBeTruthy();
 });
