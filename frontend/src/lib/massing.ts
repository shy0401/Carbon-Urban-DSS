/** Concept massing for the 3D view: planned blocks placed inside a square site (pure functions).
 *
 * The layout is a schematic — equal blocks in rows inside a square site — so the picture shows scale
 * (site, footprint, height, spacing) and never a real building arrangement. All sizes are metres;
 * conversion to degrees uses the local scale at the site latitude. Rotation is clockwise (like a map bearing).
 *
 * Spacing between rows (facing walls) is `spacingRatio × height`, at least 6 m; side gaps between
 * blocks in a row are half of that, at least 6 m. The rows × columns is the one that fits the site
 * (or overflows least), closest to square. The default ratio 0.5 follows the lower bound of the
 * 채광 이격 in 건축법 시행령 제86조 (the exact value is set by the local building ordinance), so it is a
 * planning assumption to be checked, not a legal verdict.
 */
import type { Feature, FeatureCollection, Polygon } from 'geojson';

export const FLOOR_HEIGHT_M = 3.0;
const M_PER_DEG_LAT = 111_320;
const MIN_GAP_M = 6;

export type BlockShape = 'tower' | 'slab';
export interface MassingOptions { shape?: BlockShape; spacingRatio?: number; rotation?: number }

export interface BlockPlan {
  site_side_m: number;
  /** Tower: square side. Slab: the long (east-west) side. */
  block_side_m: number;
  block_width_m: number;
  block_depth_m: number;
  columns: number;
  rows: number;
  /** Side gap inside a row (east-west, before rotation). */
  gap_m: number;
  /** Gap between rows (facing walls, north-south before rotation). */
  row_gap_m: number;
  height_m: number;
  fits: boolean;
  /** Extent the blocks need (m) along the row and across rows. */
  needed_width_m: number;
  needed_depth_m: number;
  coverage_pct: number;
  far_pct: number;
  shape: BlockShape;
}

/** Square site of `siteAreaM2`; `count` blocks of `footprintM2` in a near-square arrangement. */
export function planBlocks(siteAreaM2: number, count: number, footprintM2: number, floors: number, options: MassingOptions = {}): BlockPlan {
  const shape = options.shape ?? 'tower';
  const ratio = options.spacingRatio ?? 0.5;
  const siteSide = Math.sqrt(Math.max(siteAreaM2, 1));
  const footprint = Math.max(footprintM2, 1);
  const depth = shape === 'slab' ? Math.sqrt(footprint / 3) : Math.sqrt(footprint);
  const width = shape === 'slab' ? depth * 3 : depth;
  const n = Math.max(1, Math.min(Math.round(count), 80));
  const height = Math.max(floors, 1) * FLOOR_HEIGHT_M;
  const rowGap = Math.max(ratio * height, MIN_GAP_M);
  const gap = Math.max(rowGap / 2, MIN_GAP_M);
  // Choose the rows × columns that fits the square site; if none fits, the one that overflows least.
  // Ties go to the arrangement whose extent is closest to square.
  let best = { columns: 1, rows: n, overflow: Infinity, aspect: Infinity };
  for (let c = 1; c <= n; c += 1) {
    const r = Math.ceil(n / c);
    if ((r - 1) * c >= n) continue; // an empty last row
    const w = c * width + (c - 1) * gap;
    const d = r * depth + (r - 1) * rowGap;
    const overflow = Math.max(0, w - siteSide) + Math.max(0, d - siteSide);
    const aspect = Math.abs(Math.log(w / d));
    if (overflow < best.overflow - 1e-6 || (Math.abs(overflow - best.overflow) <= 1e-6 && aspect < best.aspect)) best = { columns: c, rows: r, overflow, aspect };
  }
  const { columns, rows } = best;
  const neededWidth = columns * width + (columns - 1) * gap;
  const neededDepth = rows * depth + (rows - 1) * rowGap;
  return {
    site_side_m: siteSide, block_side_m: width, block_width_m: width, block_depth_m: depth, columns, rows, gap_m: gap, row_gap_m: rowGap, height_m: height,
    fits: neededWidth <= siteSide + 1e-6 && neededDepth <= siteSide + 1e-6, needed_width_m: neededWidth, needed_depth_m: neededDepth,
    coverage_pct: (n * footprint) / Math.max(siteAreaM2, 1) * 100, far_pct: (n * footprint * Math.max(floors, 1)) / Math.max(siteAreaM2, 1) * 100, shape,
  };
}

export function metresToDegrees(dxM: number, dyM: number, lat: number): [number, number] {
  return [dxM / (M_PER_DEG_LAT * Math.cos((lat * Math.PI) / 180)), dyM / M_PER_DEG_LAT];
}

/** Local offset (m east, m north) rotated clockwise by `rotation` degrees. */
function rotate([x, y]: [number, number], rotation: number): [number, number] {
  const t = (rotation * Math.PI) / 180;
  return [x * Math.cos(t) + y * Math.sin(t), -x * Math.sin(t) + y * Math.cos(t)];
}

/** Rectangle `widthM × depthM` centred at local offset (cx, cy) from `center`, rotated about the site centre. */
function rectangle(center: [number, number], cx: number, cy: number, widthM: number, depthM: number, rotation: number): Polygon {
  const [lon, lat] = center;
  const corners: Array<[number, number]> = [[cx - widthM / 2, cy - depthM / 2], [cx + widthM / 2, cy - depthM / 2], [cx + widthM / 2, cy + depthM / 2], [cx - widthM / 2, cy + depthM / 2]];
  const ring = corners.map((c) => { const [dx, dy] = metresToDegrees(...rotate(c, rotation), lat); return [lon + dx, lat + dy]; });
  return { type: 'Polygon', coordinates: [[...ring, ring[0]]] };
}

/** The square site polygon around `center` ([lon, lat]). */
export function sitePolygon(center: [number, number], siteAreaM2: number, rotation = 0): Polygon {
  const side = Math.sqrt(Math.max(siteAreaM2, 1));
  return rectangle(center, 0, 0, side, side, rotation);
}

/** Site outline and planned blocks around `center` ([lon, lat]) as GeoJSON with `height` (m) and `kind`. */
export function massingFeatures(center: [number, number], siteAreaM2: number, count: number, footprintM2: number, floors: number, options: MassingOptions = {}): FeatureCollection<Polygon> {
  const plan = planBlocks(siteAreaM2, count, footprintM2, floors, options);
  const rotation = options.rotation ?? 0;
  const features: Feature<Polygon>[] = [{ type: 'Feature', properties: { kind: 'site', height: 0.3, label: `대지 ${Math.round(siteAreaM2).toLocaleString('ko-KR')}m²` }, geometry: sitePolygon(center, siteAreaM2, rotation) }];
  const n = Math.max(1, Math.min(Math.round(count), 80));
  const pitchX = plan.block_width_m + plan.gap_m;
  const pitchY = plan.block_depth_m + plan.row_gap_m;
  for (let i = 0; i < n; i += 1) {
    const col = i % plan.columns;
    const row = Math.floor(i / plan.columns);
    const inRow = Math.min(plan.columns, n - row * plan.columns); // centre a short last row
    const x = (col - (inRow - 1) / 2) * pitchX;
    const y = (row - (plan.rows - 1) / 2) * pitchY;
    features.push({ type: 'Feature', properties: { kind: 'block', height: plan.height_m, floors, label: `${floors}층`, index: i + 1 }, geometry: rectangle(center, x, y, plan.block_width_m, plan.block_depth_m, rotation) });
  }
  return { type: 'FeatureCollection', features };
}

/** Centre and bounds of a GeoJSON polygon/multipolygon (lon/lat). */
export function polygonBounds(geometry: { type: string; coordinates: unknown }): { center: [number, number]; bbox: [number, number, number, number] } | null {
  const points: number[][] = [];
  const walk = (value: unknown) => {
    if (Array.isArray(value) && typeof value[0] === 'number') points.push(value as number[]);
    else if (Array.isArray(value)) value.forEach(walk);
  };
  walk(geometry.coordinates);
  if (!points.length) return null;
  const lons = points.map((p) => p[0]);
  const lats = points.map((p) => p[1]);
  const bbox: [number, number, number, number] = [Math.min(...lons), Math.min(...lats), Math.max(...lons), Math.max(...lats)];
  return { center: [(bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2], bbox };
}

/** Outer rings of a Polygon or MultiPolygon geometry. */
export function outerRings(geometry: { type?: string; coordinates?: unknown } | null | undefined): number[][][] {
  if (!geometry) return [];
  if (geometry.type === 'Polygon') return [(geometry.coordinates as number[][][])[0]].filter(Boolean);
  if (geometry.type === 'MultiPolygon') return (geometry.coordinates as number[][][][]).map((polygon) => polygon[0]).filter(Boolean);
  return [];
}

/** Mean of a ring's vertices (the closing point excluded) — a representative point for small footprints. */
export function ringCentroid(ring: number[][]): [number, number] {
  const pts = ring.length > 1 && ring[0][0] === ring[ring.length - 1][0] && ring[0][1] === ring[ring.length - 1][1] ? ring.slice(0, -1) : ring;
  return [pts.reduce((s, p) => s + p[0], 0) / pts.length, pts.reduce((s, p) => s + p[1], 0) / pts.length];
}

/** Height of an existing building from its floor count; unknown floors get no height (drawn flat). */
export function buildingHeight(aboveFloors: unknown): number {
  return typeof aboveFloors === 'number' && aboveFloors > 0 ? aboveFloors * FLOOR_HEIGHT_M : 0;
}

/** Height class used to colour existing buildings (0 = floors unknown). */
export function heightClass(heightM: number): 0 | 1 | 2 | 3 | 4 {
  if (heightM <= 0) return 0;
  if (heightM <= 15) return 1;
  if (heightM <= 30) return 2;
  if (heightM <= 60) return 3;
  return 4;
}
export const HEIGHT_CLASS_LABELS = ['층수 미상', '15m 이하 (~5층)', '15~30m (~10층)', '30~60m (~20층)', '60m 초과'];
