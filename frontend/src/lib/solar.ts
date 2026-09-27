/** Sun position and ground shadows for the 3D concept view (pure functions).
 *
 * Solar position: NOAA general solar position equations (fractional-year form), accurate to about
 * a degree — enough for a schematic shadow, not for a legal 일조 analysis.
 * Shadows: a prism of height h over a convex footprint casts the convex hull of the footprint and
 * the footprint shifted by h / tan(altitude) away from the sun (exact for convex footprints, an
 * over-estimate for concave ones). Terrain and neighbouring roofs are ignored.
 */
const DEG = Math.PI / 180;
const M_PER_DEG_LAT = 111_320;

export interface SunPosition { altitude: number; azimuth: number }

/** Days used for the season presets (KST dates). */
export const SUN_DAYS = {
  winter: { label: '동지', month: 12, day: 22 },
  equinox: { label: '춘분', month: 3, day: 20 },
  summer: { label: '하지', month: 6, day: 21 },
} as const;
export type SunDay = keyof typeof SUN_DAYS;

/** A KST (UTC+9) wall-clock time as a Date. */
export function kst(year: number, month: number, day: number, hour: number, minute = 0): Date {
  return new Date(Date.UTC(year, month - 1, day, hour - 9, minute));
}

/** Altitude above the horizon and azimuth clockwise from north, in degrees. */
export function sunPosition(date: Date, lat: number, lon: number): SunPosition {
  const start = Date.UTC(date.getUTCFullYear(), 0, 1);
  const dayOfYear = Math.floor((date.getTime() - start) / 86_400_000) + 1;
  const hours = date.getUTCHours() + date.getUTCMinutes() / 60 + date.getUTCSeconds() / 3600;
  const g = (2 * Math.PI / 365) * (dayOfYear - 1 + (hours - 12) / 24);
  const eqTime = 229.18 * (0.000075 + 0.001868 * Math.cos(g) - 0.032077 * Math.sin(g) - 0.014615 * Math.cos(2 * g) - 0.040849 * Math.sin(2 * g));
  const decl = 0.006918 - 0.399912 * Math.cos(g) + 0.070257 * Math.sin(g) - 0.006758 * Math.cos(2 * g) + 0.000907 * Math.sin(2 * g) - 0.002697 * Math.cos(3 * g) + 0.00148 * Math.sin(3 * g);
  const trueSolarMinutes = hours * 60 + eqTime + 4 * lon;
  const hourAngle = (trueSolarMinutes / 4 - 180) * DEG;
  const phi = lat * DEG;
  const cosZenith = Math.sin(phi) * Math.sin(decl) + Math.cos(phi) * Math.cos(decl) * Math.cos(hourAngle);
  const zenith = Math.acos(Math.min(1, Math.max(-1, cosZenith)));
  const azimuth = (Math.atan2(Math.sin(hourAngle), Math.cos(hourAngle) * Math.sin(phi) - Math.tan(decl) * Math.cos(phi)) / DEG + 180 + 360) % 360;
  return { altitude: 90 - zenith / DEG, azimuth };
}

/** Ground offset (metres east, north) of a roof edge at `heightM`; null when the sun is down. */
export function shadowOffset(heightM: number, sun: SunPosition): [number, number] | null {
  if (sun.altitude <= 0.5 || heightM <= 0) return null;
  const length = heightM / Math.tan(sun.altitude * DEG);
  const direction = (sun.azimuth + 180) * DEG; // shadows point away from the sun
  return [length * Math.sin(direction), length * Math.cos(direction)];
}

export function shadowLength(heightM: number, sun: SunPosition): number | null {
  const offset = shadowOffset(heightM, sun);
  return offset ? Math.hypot(offset[0], offset[1]) : null;
}

/** Convex hull (monotone chain) of [x, y] points, counter-clockwise, closed. */
export function convexHull(points: number[][]): number[][] {
  const pts = [...new Map(points.map((p) => [`${p[0]},${p[1]}`, [p[0], p[1]]])).values()].sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  if (pts.length < 3) return pts;
  const cross = (o: number[], a: number[], b: number[]) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
  const lower: number[][] = [];
  for (const p of pts) { while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], p) <= 0) lower.pop(); lower.push(p); }
  const upper: number[][] = [];
  for (const p of [...pts].reverse()) { while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], p) <= 0) upper.pop(); upper.push(p); }
  const hull = [...lower.slice(0, -1), ...upper.slice(0, -1)];
  return [...hull, hull[0]];
}

/** Shadow of a footprint ring ([lon, lat] points) of height `heightM`; null when the sun is down. */
export function shadowRing(ring: number[][], heightM: number, sun: SunPosition): number[][] | null {
  const offset = shadowOffset(heightM, sun);
  if (!offset || ring.length < 3) return null;
  const lat = ring[0][1];
  const dLon = offset[0] / (M_PER_DEG_LAT * Math.cos(lat * DEG));
  const dLat = offset[1] / M_PER_DEG_LAT;
  return convexHull([...ring, ...ring.map(([x, y]) => [x + dLon, y + dLat])]);
}

/** Ray-casting point-in-ring test (lon/lat). */
export function pointInRing(point: number[], ring: number[][]): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i];
    const [xj, yj] = ring[j];
    if ((yi > point[1]) !== (yj > point[1]) && point[0] < ((xj - xi) * (point[1] - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}
