import { useSyncExternalStore } from 'react';

/** Whether the map screen currently shows a basemap. 'none' = offline, switched off, or tiles failed. */
export type BasemapStatus = 'not-on-map' | 'shown' | 'none';
let status: BasemapStatus = 'not-on-map';
const listeners = new Set<() => void>();

export function setBasemapStatus(next: BasemapStatus) { if (next !== status) { status = next; listeners.forEach((fn) => fn()); } }
export function useBasemapStatus() { return useSyncExternalStore((fn) => { listeners.add(fn); return () => listeners.delete(fn); }, () => status, () => status); }
