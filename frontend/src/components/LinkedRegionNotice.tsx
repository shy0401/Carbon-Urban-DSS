import { Info } from 'lucide-react';
import { dismissLinkedRegionChange, setAnalysisScope, useAnalysisScope, useLinkedRegionChange } from '../hooks/useAnalysisScope';
import { useSystemInfo } from '../hooks/useSystemInfo';
import { withTo } from '../lib/format';

/** 링크가 머리의 분석 지역을 바꿨을 때 알린다(UX 검토 F9): 다른 화면도 그 지역으로 열린다는 것과 되돌리기. */
export function LinkedRegionNotice() {
  const change = useLinkedRegionChange();
  const { region } = useAnalysisScope();
  const system = useSystemInfo();
  if (!change || change.to !== region) return null;
  const fallback = system?.default_region ?? '52110';
  const name = (code: string | null) => {
    const key = code ?? fallback;
    if (key === system?.region?.code) return system.region.short_name;
    return system?.regions?.find((r) => r.code === key)?.short_name ?? key;
  };
  return <div className="region-open-notice" role="status" data-testid="linked-region-notice"><Info size={15} aria-hidden="true" />
    <span>이 링크가 분석 지역을 <strong>{withTo(name(change.to))}</strong> 바꿨습니다. 지도·시뮬레이션·보고서·수집 화면도 이 지역으로 열립니다.</span>
    <button type="button" className="button secondary small" onClick={() => { setAnalysisScope({ region: change.from }); dismissLinkedRegionChange(); }}>{withTo(name(change.from))} 되돌리기</button>
    <button type="button" className="button ghost small" onClick={dismissLinkedRegionChange}>확인</button>
  </div>;
}
