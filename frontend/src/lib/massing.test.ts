import { describe, expect, it } from 'vitest';
import { buildingHeight, heightClass, massingFeatures, outerRings, planBlocks, polygonBounds, ringCentroid } from './massing';

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

describe('massing 옵션 (판상형·동 간격·회전)', () => {
  it('판상형은 가로 3:1로 만들고 동 간격은 높이 × 비율(최소 6m)로 둔다', () => {
    const slab = planBlocks(10000, 4, 600, 15, { shape: 'slab', spacingRatio: 0.5 });
    expect(slab.block_width_m / slab.block_depth_m).toBeCloseTo(3, 6);
    expect(slab.block_width_m * slab.block_depth_m).toBeCloseTo(600, 6);
    expect(slab.row_gap_m).toBeCloseTo(22.5, 6); // 45 m × 0.5
    expect(slab.columns * slab.rows).toBeGreaterThanOrEqual(4);
    expect(slab.coverage_pct).toBeCloseTo(24, 6);
    expect(slab.far_pct).toBeCloseTo(360, 6);
    expect(planBlocks(10000, 4, 700, 12, { spacingRatio: 1.5 }).fits).toBe(false); // 54 m row gap: 2 × 26.5 + 54 > 100 m
  });

  it('회전해도 대지 면적과 블록 크기는 그대로다', () => {
    const turned = massingFeatures([127.15, 35.82], 10000, 4, 700, 12, { rotation: 30 });
    const area = (ring: number[][]) => {
      const lat = ring[0][1];
      const kx = 111320 * Math.cos((lat * Math.PI) / 180);
      let sum = 0;
      for (let i = 0; i < ring.length - 1; i += 1) sum += ring[i][0] * kx * ring[i + 1][1] * 111320 - ring[i + 1][0] * kx * ring[i][1] * 111320;
      return Math.abs(sum) / 2;
    };
    expect(area(turned.features[0].geometry.coordinates[0])).toBeCloseTo(10000, -1);
    expect(area(turned.features[1].geometry.coordinates[0])).toBeCloseTo(700, -1);
    const straight = massingFeatures([127.15, 35.82], 10000, 4, 700, 12);
    expect(turned.features[1].geometry.coordinates[0][0]).not.toEqual(straight.features[1].geometry.coordinates[0][0]);
  });

  it('높이 등급과 외곽 고리를 구한다', () => {
    expect([0, 9, 21, 45, 90].map(heightClass)).toEqual([0, 1, 2, 3, 4]);
    expect(outerRings({ type: 'MultiPolygon', coordinates: [[[[0, 0], [1, 0], [1, 1], [0, 0]]], [[[2, 2], [3, 2], [3, 3], [2, 2]]]] })).toHaveLength(2);
    expect(ringCentroid([[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]])).toEqual([1, 1]);
  });
});

describe('배열 선택', () => {
  it('대지에 들어가는 배열을 고르고, 없으면 가장 덜 넘치는 배열을 고른다', () => {
    const slab = planBlocks(10000, 4, 700, 12, { shape: 'slab' }); // 45.8 m × 15.3 m slabs
    expect(slab.fits).toBe(false);
    expect(slab.columns).toBe(2); // 2 × 2 overflows 0.6 m; 1 × 4 overflows 15 m
    const small = planBlocks(10000, 4, 400, 12, { shape: 'slab' });
    expect(small.fits).toBe(true);
    const six = planBlocks(20000, 6, 600, 10);
    expect(six.columns * six.rows).toBeGreaterThanOrEqual(6);
    expect(six.fits).toBe(true);
  });
});
