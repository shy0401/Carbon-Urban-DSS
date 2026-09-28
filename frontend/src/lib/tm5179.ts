/**
 * EPSG:5179 (Korea 2000 / Unified CS, GRS80 Transverse Mercator) → WGS84 lon/lat.
 *
 * The province map receives 500m cells as lower-left corners in EPSG:5179 (compact integers) and draws each
 * cell from its four projected corners. Inverse Transverse Mercator series (Snyder 1987, eq. 8-12 … 8-18):
 * sub-metre over Korea (≤ 3.5° from the central meridian 127.5°E), far below the 500m cell size.
 */
const A = 6378137;
const F = 1 / 298.257222101;
const E2 = F * (2 - F);
const EP2 = E2 / (1 - E2);
const K0 = 0.9996;
const LAT0 = (38 * Math.PI) / 180;
const LON0 = (127.5 * Math.PI) / 180;
const FE = 1_000_000;
const FN = 2_000_000;
const E4 = E2 * E2;
const E6 = E4 * E2;
const M_A = 1 - E2 / 4 - (3 * E4) / 64 - (5 * E6) / 256;

function meridian(phi: number): number {
  return A * (M_A * phi
    - ((3 * E2) / 8 + (3 * E4) / 32 + (45 * E6) / 1024) * Math.sin(2 * phi)
    + ((15 * E4) / 256 + (45 * E6) / 1024) * Math.sin(4 * phi)
    - ((35 * E6) / 3072) * Math.sin(6 * phi));
}

const M0 = meridian(LAT0);
const SQ = Math.sqrt(1 - E2);
const E1 = (1 - SQ) / (1 + SQ);

/** [lon, lat] in degrees of an EPSG:5179 point. */
export function toLonLat(x: number, y: number): [number, number] {
  const m = M0 + (y - FN) / K0;
  const mu = m / (A * M_A);
  const phi1 = mu
    + ((3 * E1) / 2 - (27 * E1 ** 3) / 32) * Math.sin(2 * mu)
    + ((21 * E1 ** 2) / 16 - (55 * E1 ** 4) / 32) * Math.sin(4 * mu)
    + ((151 * E1 ** 3) / 96) * Math.sin(6 * mu)
    + ((1097 * E1 ** 4) / 512) * Math.sin(8 * mu);
  const sin1 = Math.sin(phi1);
  const cos1 = Math.cos(phi1);
  const tan1 = Math.tan(phi1);
  const c1 = EP2 * cos1 * cos1;
  const t1 = tan1 * tan1;
  const n1 = A / Math.sqrt(1 - E2 * sin1 * sin1);
  const r1 = (A * (1 - E2)) / Math.pow(1 - E2 * sin1 * sin1, 1.5);
  const d = (x - FE) / (n1 * K0);
  const lat = phi1 - ((n1 * tan1) / r1) * (
    (d * d) / 2
    - ((5 + 3 * t1 + 10 * c1 - 4 * c1 * c1 - 9 * EP2) * d ** 4) / 24
    + ((61 + 90 * t1 + 298 * c1 + 45 * t1 * t1 - 252 * EP2 - 3 * c1 * c1) * d ** 6) / 720);
  const lon = LON0 + (d
    - ((1 + 2 * t1 + c1) * d ** 3) / 6
    + ((5 - 2 * c1 + 28 * t1 - 3 * c1 * c1 + 8 * EP2 + 24 * t1 * t1) * d ** 5) / 120) / cos1;
  return [(lon * 180) / Math.PI, (lat * 180) / Math.PI];
}

/** Closed ring of the square cell whose lower-left corner is (x, y) in EPSG:5179. */
export function cellRing(x: number, y: number, size = 500): [number, number][] {
  const ll = toLonLat(x, y);
  return [ll, toLonLat(x + size, y), toLonLat(x + size, y + size), toLonLat(x, y + size), ll];
}
