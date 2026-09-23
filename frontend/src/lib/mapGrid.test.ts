import { describe, expect, it } from 'vitest';
import { fitAffine, referenceGrid, toLonLat } from './mapGrid';

// Synthetic grid with a known affine EPSG:5179 → lon/lat relation (slightly rotated, like TM near Jeonju).
const lonOf = (x: number, y: number) => 127.1 + (x - 968000) * 1.1e-5 + (y - 1762000) * 1.2e-7;
const latOf = (x: number, y: number) => 35.8 + (x - 968000) * -1.0e-7 + (y - 1762000) * 9.0e-6;
function cell(x: number, y: number) {
  const ring = [[x + 500, y], [x + 500, y + 500], [x, y + 500], [x, y], [x + 500, y]].map(([px, py]) => [lonOf(px, py), latOf(px, py)]);
  return { type: 'Feature', properties: { id: `cell_${x}_${y}` }, geometry: { type: 'Polygon', coordinates: [ring] } };
}
const grids = { type: 'FeatureCollection', features: [cell(968000, 1762000), cell(968500, 1762000), cell(968000, 1762500), cell(969000, 1763000), cell(967500, 1761500)] } as unknown as GeoJSON.FeatureCollection;

describe('1km reference grid', () => {
  it('recovers the projection from grid ids and polygon centers', () => {
    const affine = fitAffine([{ x: 0, y: 0, lon: 1, lat: 2 }, { x: 1000, y: 0, lon: 1.01, lat: 2 }, { x: 0, y: 1000, lon: 1, lat: 2.01 }, { x: 1000, y: 1000, lon: 1.01, lat: 2.01 }])!;
    expect(toLonLat(affine, 500, 500)[0]).toBeCloseTo(1.005, 9);
    expect(toLonLat(affine, 500, 500)[1]).toBeCloseTo(2.005, 9);
  });
  it('draws lines every 1km on round EPSG:5179 coordinates, beyond the grid extent', () => {
    const fc = referenceGrid(grids);
    const xs = fc.features.filter((f) => f.properties?.axis === 'x').map((f) => f.properties?.value as number);
    expect(xs.every((x) => x % 1000 === 0)).toBe(true);
    expect(Math.min(...xs)).toBeLessThanOrEqual(967500 - 5000);
    const line = fc.features.find((f) => f.properties?.axis === 'x' && f.properties?.value === 968000)!;
    const [start] = (line.geometry as unknown as { coordinates: number[][] }).coordinates;
    expect(start[0]).toBeCloseTo(lonOf(968000, 1761500 - 5000 - 500), 6);
  });
  it('returns nothing without enough recognisable cells', () => {
    expect(referenceGrid({ type: 'FeatureCollection', features: [] }).features).toHaveLength(0);
  });
});
