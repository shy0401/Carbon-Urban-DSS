import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from './api';

describe('api', () => {
  afterEach(() => vi.restoreAllMocks());
  it('FastAPI 구조화 검증 오류를 읽을 수 있는 한 줄로 변환한다', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ detail: [{ loc: ['body', 'floors'], msg: 'Input should be less than or equal to 40', type: 'less_than_equal' }] }), { status: 422 }));
    await expect(api('/scenarios')).rejects.toThrow('floors: Input should be less than or equal to 40');
  });
});
