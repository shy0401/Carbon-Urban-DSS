import { afterEach, describe, expect, it, vi } from 'vitest';
import { NOT_READY, openRegion } from './useRegionOpen';

afterEach(() => { vi.restoreAllMocks(); });

describe('opening a 시·군·구 map', () => {
  it('sends one request however many screens ask, then tells stopped screens to read again', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async () => new Response(JSON.stringify({ code: '52130', name: '전북특별자치도 군산시', short_name: '군산시' }), { status: 200, headers: { 'Content-Type': 'application/json' } }));
    const opened: string[] = [];
    const listener = (e: Event) => opened.push(String((e as CustomEvent).detail));
    window.addEventListener('carbon-region-opened', listener);
    const [a, b] = await Promise.all([openRegion('52130'), openRegion('52130')]);
    window.removeEventListener('carbon-region-opened', listener);
    expect(a.short_name).toBe('군산시');
    expect(b).toBe(a);
    const posts = fetchMock.mock.calls.filter((call) => String(call[0]).includes('/regions/52130/open'));
    expect(posts).toHaveLength(1);
    expect(opened).toEqual(['52130']);
  });
  it('recognises the server messages for a region without a map', () => {
    expect(NOT_READY.test('아직 지도를 만들지 않은 지역입니다(준비하지 않은 지역): 11110.')).toBe(true);
    expect(NOT_READY.test('완주군의 분석 격자가 아직 없습니다.')).toBe(true);
    expect(NOT_READY.test('서버 오류')).toBe(false);
  });
});
