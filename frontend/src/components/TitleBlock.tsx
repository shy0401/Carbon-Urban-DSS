import { ChevronDown } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useAnalysisScope } from '../hooks/useAnalysisScope';
import { useBasemapStatus } from '../hooks/useBasemapStatus';
import { useSystemInfo } from '../hooks/useSystemInfo';
import { api } from '../lib/api';

/**
 * 표제란 (DESIGN.md 4.2): 분석 범위를 도면 표제란처럼 항상 보여준다. 표시 전용 —
 * 연도·격자 변경은 기존 컨트롤(AnalysisScopeBar, 지도 클릭)이 한다.
 * 최근 수집일은 /api/sources의 collected_at 최대값이며 자료의 기준기간이 아니다.
 */
/** Place name of a cell from /api/grids/{id}/place; null while loading or when the cell is not known. */
function useGridPlace(gridId: string | null): string | null {
  const [place, setPlace] = useState<string | null>(null);
  useEffect(() => {
    setPlace(null);
    if (!gridId) return;
    let alive = true;
    api<{ place: string }>(`/grids/${encodeURIComponent(gridId)}/place`).then((r) => { if (alive && r?.place) setPlace(r.place); }).catch(() => undefined);
    return () => { alive = false; };
  }, [gridId]);
  return place;
}

export function TitleBlock() {
  const { year, gridId } = useAnalysisScope();
  const system = useSystemInfo();
  const regionName = system?.region?.short_name ?? '전주시';
  const basemap = useBasemapStatus();
  const latest = useLatestCollection(year);
  const [open, setOpen] = useState(false);
  const mode = system ? (system.offline_mode ? '오프라인' : '온라인') : '확인 중';
  // The selected cell is named by its place (송천1동 일대); the cell id is only a tooltip.
  const place = useGridPlace(gridId);
  const gridLabel = gridId ? (place ?? '선택한 격자') : '기본 대상지';
  return <div className={`title-block-wrap${open ? ' open' : ''}`}>
    <button type="button" className="title-block-summary" aria-expanded={open} aria-controls="title-block" onClick={() => setOpen(!open)}>
      <span className="tb-summary-region">{regionName}</span><span className="tb-sep" aria-hidden="true" /><span><b>{year}</b>년</span><span className="tb-sep" aria-hidden="true" /><span className="tb-summary-grid" title={gridId ?? undefined}>{gridLabel}</span><ChevronDown size={16} aria-hidden="true" />
      <span className="sr-only">분석 범위 {open ? '접기' : '펼치기'}</span>
    </button>
    <dl className="title-block" id="title-block" aria-label="분석 범위 표제란">
      <div><dt>분석 지역</dt><dd title={system?.region?.name}>{regionName}</dd></div>
      <div><dt>분석연도</dt><dd>{year}</dd></div>
      <div className="tb-const"><dt>격자</dt><dd>500m 분석 격자</dd></div>
      <div className="tb-grid"><dt>선택 격자</dt><dd>{gridId ? <span title={gridId}>{gridLabel}</span> : <span title={system?.region && system.region.code !== system.default_region ? '격자를 고르지 않으면 지역 준비 때 정한 기본 대상지(K-apt 세대수가 가장 많은 격자)를 씁니다' : '격자를 고르지 않으면 예비 선정 격자(LG동아 인근)를 씁니다'}>기본 대상지</span>}</dd></div>
      <div><dt>최근 수집일</dt><dd>{latest === undefined ? '확인 중' : latest ?? '수집 기록 없음'}</dd></div>
      <div><dt>모드</dt><dd>{mode}{basemap === 'none' && <small>배경지도 없음</small>}</dd></div>
    </dl>
  </div>;
}

function useLatestCollection(year: number): string | null | undefined {
  const [value, setValue] = useState<string | null | undefined>(undefined);
  useEffect(() => {
    const controller = new AbortController();
    setValue(undefined);
    api<unknown>(`/sources?year=${year}`, { signal: controller.signal })
      .then((rows) => {
        const list = Array.isArray(rows) ? rows : [];
        const dates = list.map((row) => (row && typeof row === 'object' ? (row as { collected_at?: unknown }).collected_at : null)).filter((v): v is string => typeof v === 'string' && v.length >= 10).sort();
        setValue(dates.length ? dates[dates.length - 1].slice(0, 10) : null);
      })
      .catch(() => { if (!controller.signal.aborted) setValue('확인 불가'); });
    return () => controller.abort();
  }, [year]);
  return value;
}
