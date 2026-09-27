import { describe, expect, it } from 'vitest';
import { convexHull, kst, pointInRing, shadowLength, shadowRing, sunPosition } from './solar';

const JEONJU = { lat: 35.82, lon: 127.15 };

describe('태양 위치와 그림자', () => {
  it('전주 남중 고도: 동지 약 30.7°, 춘분 약 54°, 하지 약 77.6°', () => {
    const winter = sunPosition(kst(2026, 12, 22, 12, 30), JEONJU.lat, JEONJU.lon);
    expect(winter.altitude).toBeCloseTo(90 - 35.82 - 23.44, 0);
    expect(Math.abs(winter.azimuth - 180)).toBeLessThan(3);
    expect(sunPosition(kst(2026, 3, 20, 12, 30), JEONJU.lat, JEONJU.lon).altitude).toBeGreaterThan(53);
    expect(sunPosition(kst(2026, 6, 21, 12, 30), JEONJU.lat, JEONJU.lon).altitude).toBeCloseTo(90 - 35.82 + 23.44, 0);
  });

  it('오전에는 해가 동쪽(방위 180° 미만)에 있고 밤에는 그림자가 없다', () => {
    const morning = sunPosition(kst(2026, 12, 22, 9), JEONJU.lat, JEONJU.lon);
    expect(morning.azimuth).toBeLessThan(180);
    expect(morning.altitude).toBeGreaterThan(0);
    const night = sunPosition(kst(2026, 12, 22, 22), JEONJU.lat, JEONJU.lon);
    expect(night.altitude).toBeLessThan(0);
    expect(shadowLength(30, night)).toBeNull();
  });

  it('정오 그림자는 북쪽으로 h / tan(고도)만큼 늘어난다', () => {
    const sun = { altitude: 45, azimuth: 180 };
    expect(shadowLength(30, sun)).toBeCloseTo(30, 6);
    const ring = [[127.15, 35.82], [127.1501, 35.82], [127.1501, 35.8201], [127.15, 35.8201], [127.15, 35.82]];
    const shadow = shadowRing(ring, 30, sun)!;
    const maxLat = Math.max(...shadow.map((p) => p[1]));
    expect((maxLat - 35.8201) * 111320).toBeCloseTo(30, 1);
    expect(Math.min(...shadow.map((p) => p[1]))).toBeCloseTo(35.82, 9);
  });

  it('볼록 껍질과 점 포함 판정', () => {
    const hull = convexHull([[0, 0], [2, 0], [1, 1], [2, 2], [0, 2]]);
    expect(hull).toHaveLength(5);
    expect(pointInRing([1, 1], hull)).toBe(true);
    expect(pointInRing([3, 1], hull)).toBe(false);
  });
});
