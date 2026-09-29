import { Info, Loader2, TriangleAlert } from 'lucide-react';
import { useEffect, useRef } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useAnalysisScope } from '../hooks/useAnalysisScope';
import { openRegion, useRegionOpening } from '../hooks/useRegionOpen';
import { useSystemInfo } from '../hooks/useSystemInfo';
import { withTopic } from '../lib/format';

/**
 * 고른 시·군·구에 아직 지도가 없으면(전국 어디든 고를 수 있으므로) 전국 공통 자료로 기본 지도를 만들고 진행을 알린다.
 * 대시보드·분석·모델 등 어느 화면에서 골라도 같은 요청 하나로 만들고, 끝나면 멈춘 화면이 다시 읽는다.
 */
export function RegionOpenNotice() {
  const { region } = useAnalysisScope();
  const system = useSystemInfo();
  const opening = useRegionOpening();
  const location = useLocation();
  const tried = useRef<string | null>(null);
  const ready = !region || !system || region === system.default_region || (system.regions ?? []).some((r) => r.code === region && r.grid_count > 0);
  useEffect(() => {
    if (ready || !region || tried.current === region) return;
    tried.current = region;
    openRegion(region).catch(() => undefined);
  }, [ready, region]);
  if (opening.state === 'opening' && opening.code === region) {
    return <div className="region-open-notice" role="status"><Loader2 size={15} className="spin" aria-hidden="true" />
      <span><strong>{opening.name ?? region}</strong> 지도를 만드는 중입니다. 전국 공통 자료(SGIS 격자 통계·행정동, K-apt 단지 목록, 조례)로 500m 격자와 읍면동을 만드는 처음 한 번만 몇 초~1분 걸립니다.</span></div>;
  }
  if (opening.state === 'failed' && opening.code === region && region) {
    return <div className="region-open-notice bad" role="alert"><TriangleAlert size={15} aria-hidden="true" />
      <span>{opening.name ?? region} 지도를 만들지 못했습니다: {opening.message}</span>
      <button type="button" className="button secondary small" onClick={() => { openRegion(region).catch(() => undefined); }}>다시 시도</button></div>;
  }
  const entry = region ? system?.regions?.find((r) => r.code === region) : undefined;
  if (entry?.level === 'BASIC' && region && !/^\/(map|regions|data|guide)/.test(location.pathname)) {
    return <div className="region-open-notice basic" role="note"><Info size={15} aria-hidden="true" />
      <span><strong>{withTopic(entry.short_name)}</strong> 기본 지도(전국 공통 자료: SGIS 인구·주택, K-apt 단지 목록, 조례)만 있습니다. 에너지·탄소·건물·용도지역 값은 비어 있으며 0이 아닙니다.</span>
      <Link className="button secondary small" to={`/regions?select=${region}`}>상세 자료 수집</Link></div>;
  }
  return null;
}
