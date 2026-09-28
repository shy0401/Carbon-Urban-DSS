import { describe, expect, it } from 'vitest';
import { cellRing, toLonLat } from './tm5179';

// Reference values: pyproj Transformer.from_crs(5179, 4326, always_xy=True) on the PC (PROJ, 2026-09-28).
const REFERENCE: Array<[number, number, number, number]> = [
  [950000, 1919000, 126.936064, 37.2685666],
  [931000, 1746500, 126.7371866, 35.7123705],
  [1100000, 1700000, 128.599749, 35.2905122],
  [750000, 1650000, 124.7668608, 34.813933],
  [1150000, 2050000, 129.2186945, 38.438021],
  [1300000, 1850000, 130.8536766, 36.6006862],
];

describe('EPSG:5179 → WGS84', () => {
  it('matches PROJ within a metre across Korea', () => {
    for (const [x, y, lon, lat] of REFERENCE) {
      const [gotLon, gotLat] = toLonLat(x, y);
      const dx = (gotLon - lon) * 111_320 * Math.cos((lat * Math.PI) / 180);
      const dy = (gotLat - lat) * 110_574;
      expect(Math.hypot(dx, dy)).toBeLessThan(1);
    }
  });
  it('draws a closed 500m square', () => {
    const ring = cellRing(950000, 1919000);
    expect(ring).toHaveLength(5);
    expect(ring[0]).toEqual(ring[4]);
    const widthM = (ring[1][0] - ring[0][0]) * 111_320 * Math.cos((ring[0][1] * Math.PI) / 180);
    expect(Math.abs(widthM - 500)).toBeLessThan(5);
  });
});
