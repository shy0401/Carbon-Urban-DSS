/**
 * 1km 참조 격자 (DESIGN.md 6): 배경지도가 없을 때 도형이 허공에 뜨지 않도록 도면지 위에 긋는 선.
 * 분석 격자 ID(cell_{x}_{y}, EPSG:5179 좌하단 m)와 그 도형 중심(WGS84)으로 국소 아핀 변환을
 * 최소제곱으로 맞춘 뒤 1km 간격 선을 만든다. 표시용 보조선이며 분석 값에는 쓰지 않는다.
 */
type Affine = { lon: [number, number, number]; lat: [number, number, number]; xm: number; ym: number };

const CELL = /^cell_(\d+)_(\d+)$/;

function ringCenter(geometry: GeoJSON.Geometry | null | undefined): [number, number] | null {
  const ring = (geometry as { type?: string; coordinates?: number[][][] } | null)?.type === 'Polygon' ? (geometry as { coordinates: number[][][] }).coordinates[0] : null;
  if (!ring || ring.length < 4) return null;
  const points = ring.slice(0, ring.length - (ring[0][0] === ring[ring.length - 1][0] && ring[0][1] === ring[ring.length - 1][1] ? 1 : 0));
  const sum = points.reduce((acc, [lon, lat]) => [acc[0] + lon, acc[1] + lat], [0, 0]);
  return [sum[0] / points.length, sum[1] / points.length];
}

function solve3(m: number[][], v: number[]): [number, number, number] | null {
  const det = (a: number[][]) => a[0][0] * (a[1][1] * a[2][2] - a[1][2] * a[2][1]) - a[0][1] * (a[1][0] * a[2][2] - a[1][2] * a[2][0]) + a[0][2] * (a[1][0] * a[2][1] - a[1][1] * a[2][0]);
  const d = det(m);
  if (!Number.isFinite(d) || Math.abs(d) < 1e-12) return null;
  const col = (i: number) => m.map((row, r) => row.map((value, c) => (c === i ? v[r] : value)));
  return [det(col(0)) / d, det(col(1)) / d, det(col(2)) / d];
}

export function fitAffine(samples: Array<{ x: number; y: number; lon: number; lat: number }>): Affine | null {
  if (samples.length < 3) return null;
  const xm = samples.reduce((s, p) => s + p.x, 0) / samples.length;
  const ym = samples.reduce((s, p) => s + p.y, 0) / samples.length;
  const n = [[0, 0, 0], [0, 0, 0], [0, 0, 0]]; const bl = [0, 0, 0]; const bt = [0, 0, 0];
  for (const p of samples) {
    const row = [1, p.x - xm, p.y - ym];
    for (let i = 0; i < 3; i++) { bl[i] += row[i] * p.lon; bt[i] += row[i] * p.lat; for (let j = 0; j < 3; j++) n[i][j] += row[i] * row[j]; }
  }
  const lon = solve3(n, bl); const lat = solve3(n, bt);
  return lon && lat ? { lon, lat, xm, ym } : null;
}

export function toLonLat(affine: Affine, x: number, y: number): [number, number] {
  const dx = x - affine.xm; const dy = y - affine.ym;
  return [affine.lon[0] + affine.lon[1] * dx + affine.lon[2] * dy, affine.lat[0] + affine.lat[1] * dx + affine.lat[2] * dy];
}

export function referenceGrid(grids: GeoJSON.FeatureCollection, step = 1000, margin = 5000, cell = 500): GeoJSON.FeatureCollection {
  const samples: Array<{ x: number; y: number; lon: number; lat: number }> = [];
  for (const feature of grids.features) {
    const match = CELL.exec(String((feature.properties as { id?: unknown } | null)?.id ?? ''));
    const center = ringCenter(feature.geometry);
    if (match && center) samples.push({ x: Number(match[1]) + cell / 2, y: Number(match[2]) + cell / 2, lon: center[0], lat: center[1] });
  }
  const affine = fitAffine(samples);
  if (!affine) return { type: 'FeatureCollection', features: [] };
  const xs = samples.map((p) => p.x); const ys = samples.map((p) => p.y);
  const x0 = Math.floor((Math.min(...xs) - margin) / step) * step; const x1 = Math.ceil((Math.max(...xs) + margin) / step) * step;
  const y0 = Math.floor((Math.min(...ys) - margin) / step) * step; const y1 = Math.ceil((Math.max(...ys) + margin) / step) * step;
  const features: GeoJSON.Feature[] = [];
  const line = (a: [number, number], b: [number, number], axis: string, value: number) => features.push({ type: 'Feature', properties: { axis, value }, geometry: { type: 'LineString', coordinates: [a, b] } as unknown as GeoJSON.Geometry });
  for (let x = x0; x <= x1; x += step) line(toLonLat(affine, x, y0), toLonLat(affine, x, y1), 'x', x);
  for (let y = y0; y <= y1; y += step) line(toLonLat(affine, x0, y), toLonLat(affine, x1, y), 'y', y);
  return { type: 'FeatureCollection', features };
}
