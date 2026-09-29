import { useSyncExternalStore } from 'react';
import { api } from '../lib/api';
import type { RegionSummary } from '../types';
import { refreshSystemInfo } from './useSystemInfo';

/** 시·군·구 지도가 아직 없을 때 서버가 돌려주는 404 문구. */
export const NOT_READY = /준비하지 않은|지도를 만들지 않은|격자가 아직 없/;

export type RegionOpenState = { code: string | null; state: 'idle' | 'opening' | 'failed'; name?: string; message?: string };
let state: RegionOpenState = { code: null, state: 'idle' };
const listeners = new Set<() => void>();
const pending = new Map<string, Promise<RegionSummary>>();
const set = (next: RegionOpenState) => { state = next; listeners.forEach((fn) => fn()); };

/**
 * 시·군·구의 기본 지도(전국 공통 자료로 만든 500m 격자·읍면동)를 한 번 만든다. 여러 화면이 동시에 불러도 요청은 하나다.
 * 끝나면 시스템 정보를 새로 읽고 `carbon-region-opened`를 알려, 오류로 멈춘 화면이 다시 읽게 한다.
 */
export function openRegion(code: string, name?: string): Promise<RegionSummary> {
  const existing = pending.get(code);
  if (existing) return existing;
  set({ code, state: 'opening', name });
  const request = api<RegionSummary>(`/regions/${code}/open`, { method: 'POST', body: '{}' })
    .then((opened) => {
      set({ code, state: 'idle', name: opened.short_name ?? opened.name });
      void refreshSystemInfo(code);
      if (typeof window !== 'undefined') {
        window.dispatchEvent(new window.Event('carbon-regions-change'));
        window.dispatchEvent(new window.CustomEvent('carbon-region-opened', { detail: code }));
      }
      return opened;
    })
    .catch((reason: unknown) => {
      set({ code, state: 'failed', name, message: reason instanceof Error ? reason.message : '지도를 만들지 못했습니다.' });
      throw reason;
    })
    .finally(() => { pending.delete(code); });
  pending.set(code, request);
  return request;
}

export function useRegionOpening(): RegionOpenState {
  return useSyncExternalStore((fn) => { listeners.add(fn); return () => listeners.delete(fn); }, () => state, () => state);
}
