/** Concept massing for the 3D view: planned blocks placed inside the selected grid (pure functions).
 *
 * The layout is a schematic — equal square blocks in rows inside a square site at the grid centre —
 * so the picture shows scale (site, footprint, height) and never a real building arrangement.
 * All sizes are metres; conversion to degrees uses the local scale at the grid latitude.
 */
import type { Feature, FeatureCollection, Polygon } from 'geojson';

export const FLOOR_HEIGHT_M = 3.0;
const M_PER_DEG_LAT = 111_320;

export interface BlockPlan { site_side_m: number; block_side_m: number; columns: number; rows: number; gap_m: number; height_m: number; fits: boolean }

/** Square site of `siteAreaM2`; `count` square blocks of `footprintM2` in a near-square arrangement. */
export function planBlocks(siteAreaM2: number, count: number, footprintM2: number, floors: number): BlockPlan {
  const siteSide = Math.sqrt(Math.max(siteAreaM2, 1));
  const blockSide = Math.sqrt(Math.max(footprintM2, 1));
  const n = Math.max(1, Math.min(count, 80));
  const columns = Math.ceil(Math.sqrt(n));
  const rows = Math.ceil(n / columns);
  const gap = Math.max(blockSide * 0.6, 6);
  const needed = columns * blockSide + (columns - 1) * gap;
  const neededRows = rows * blockSide + (rows - 1) * gap;
  return { site_side_m: siteSide, block_side_m: blockSide, columns, rows, gap_m: gap, height_m: Math.max(floors, 1) * FLOOR_HEIGHT_M, fits: needed <= siteSide && neededRows <= siteSide };
}

function metresToDegrees(dxM: number, dyM: number, lat: number): [number, number] {
  return [dxM / (M_PER_DEG_LAT * Math.cos((lat * Math.PI) / 180)), dyM / M_PER_DEG_LAT];
}

function square(cx: number, cy: number, sideM: number, lat: number): Polygon {
  const [dx, dy] = metresToDegrees(sideM / 2, sideM / 2, lat);
  return { type: 'Polygon', coordinates: [[[cx - dx, cy - dy], [cx + dx, cy - dy], [cx + dx, cy + dy], [cx - dx, cy + dy], [cx - dx, cy - dy]]] };
}

/** Site outline and planned blocks around `center` ([lon, lat]) as GeoJSON with `height` (m) and `kind`. */
export function massingFeatures(center: [number, number], siteAreaM2: number, count: number, footprintM2: number, floors: number): FeatureCollection<Polygon> {
  const plan = planBlocks(siteAreaM2, count, footprintM2, floors);
  const [lon, lat] = center;
  const features: Feature<Polygon>[] = [{ type: 'Feature', properties: { kind: 'site', height: 0.3, label: `대지 ${Math.round(siteAreaM2).toLocaleString('ko-KR')}m²` }, geometry: square(lon, lat, plan.site_side_m, lat) }];
  const n = Math.max(1, Math.min(count, 80));
  const pitch = plan.block_side_m + plan.gap_m;
  const spanX = (plan.columns - 1) * pitch;
  const spanY = (plan.rows - 1) * pitch;
  for (let i = 0; i < n; i += 1) {
    const col = i % plan.columns;
    const row = Math.floor(i / plan.columns);
    const [dx, dy] = metresToDegrees(col * pitch - spanX / 2, row * pitch - spanY / 2, lat);
    features.push({ type: 'Feature', properties: { kind: 'block', height: plan.height_m, floors, label: `${floors}층` }, geometry: square(lon + dx, lat + dy, plan.block_side_m, lat) });
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

/** Height of an existing building from its floor count; unknown floors get no height (drawn flat). */
export function buildingHeight(aboveFloors: unknown): number {
  return typeof aboveFloors === 'number' && aboveFloors > 0 ? aboveFloors * FLOOR_HEIGHT_M : 0;
}
