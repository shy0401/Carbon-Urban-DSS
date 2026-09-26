import { describe, expect, it } from 'vitest';
import { buildingHeight, massingFeatures, planBlocks, polygonBounds } from './massing';

describe('massing (3D 개념 배치)', () => {
  it('블록을 정사각형에 가깝게 배열하고 높이는 층수 × 3m로 둔다', () => {
    const plan = planBlocks(10000, 4, 700, 12);
    expect(plan.site_side_m).toBeCloseTo(100, 3);
    expect(plan.columns).toBe(2);
    expect(plan.rows).toBe(2);
    expect(plan.height_m).toBe(36);
    expect(plan.fits).toBe(true);
    expect(planBlocks(2500, 9, 700, 5).fits).toBe(false); // 9 blocks of 26m on a 50m site do not fit
  });

  it('대지와 계획 블록을 격자 중심에 두고 미터를 위도에 맞는 도로 바꾼다', () => {
    const fc = massingFeatures([127.15, 35.82], 10000, 4, 700, 12);
    expect(fc.features).toHaveLength(5);
    const site = fc.features[0];
    expect(site.properties?.kind).toBe('site');
    const ring = site.geometry.coordinates[0];
    const widthDeg = ring[1][0] - ring[0][0];
    const heightDeg = ring[2][1] - ring[1][1];
    expect(heightDeg * 111320).toBeCloseTo(100, 1); // 100 m north-south
    expect(widthDeg * 111320 * Math.cos((35.82 * Math.PI) / 180)).toBeCloseTo(100, 1); // 100 m east-west at this latitude
    const blocks = fc.features.filter((f) => f.properties?.kind === 'block');
    expect(blocks.every((b) => b.properties?.height === 36 && b.properties?.floors === 12)).toBe(true);
    const centres = blocks.map((b) => b.geometry.coordinates[0][0]);
    expect(new Set(centres.map((c) => c.join(','))).size).toBe(4); // four distinct positions
  });

  it('격자 도형의 중심과 경계를 구하고, 층수가 없는 건물은 높이 0으로 둔다', () => {
    const bounds = polygonBounds({ type: 'Polygon', coordinates: [[[127.1, 35.8], [127.2, 35.8], [127.2, 35.9], [127.1, 35.9], [127.1, 35.8]]] });
    expect(bounds?.center[0]).toBeCloseTo(127.15, 9);
    expect(bounds?.center[1]).toBeCloseTo(35.85, 9);
    expect(bounds?.bbox).toEqual([127.1, 35.8, 127.2, 35.9]);
    expect(polygonBounds({ type: 'Polygon', coordinates: [] })).toBeNull();
    expect(buildingHeight(15)).toBe(45);
    expect(buildingHeight(null)).toBe(0);
    expect(buildingHeight(0)).toBe(0);
  });
});
