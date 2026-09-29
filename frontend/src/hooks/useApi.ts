import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../lib/api';

export function useApi<T>(path: string) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const request = useRef<AbortController | null>(null);

  const reload = useCallback(async () => {
    request.current?.abort();
    const controller=new AbortController();request.current=controller;
    setLoading(true);
    setError(null);
    try {
      const next=await api<T>(path,{signal:controller.signal});
      if (!controller.signal.aborted) setData(next);
    } catch (reason) {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '알 수 없는 오류가 발생했습니다.');
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    void reload();
    return ()=>request.current?.abort();
  }, [reload]);

  // A 시·군·구 map was just built (see useRegionOpen): a screen stopped on "지도를 만들지 않은 지역" reads again.
  const failed = useRef(false); failed.current = error !== null;
  useEffect(() => {
    const onOpened = () => { if (failed.current) void reload(); };
    window.addEventListener('carbon-region-opened', onOpened);
    return () => window.removeEventListener('carbon-region-opened', onOpened);
  }, [reload]);

  return { data, loading, error, reload, setData };
}
