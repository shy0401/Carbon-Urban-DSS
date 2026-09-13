import { describe, expect, it } from 'vitest';
import { applyFloorPreset } from './capacity';

describe('applyFloorPreset', () => {
  it('층수 프리셋 적용 시 세대수와 인구 수용량을 같은 면적·가구 규모 기준으로 다시 계산한다', () => {
    expect(applyFloorPreset({ floors: 12, building_count: 4, footprint_per_building: 700, households: 240, population: 560, average_household_area: 84 }, 20)).toEqual({
      floors: 20,
      households: 667,
      population: 1556,
    });
  });
});
