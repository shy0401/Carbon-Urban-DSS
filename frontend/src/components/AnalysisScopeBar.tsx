import { ChevronDown, Globe2 } from 'lucide-react';
import { Link, useNavigate } from 'react-router-dom';
import { useAnalysisScope } from '../hooks/useAnalysisScope';
import { useSystemInfo } from '../hooks/useSystemInfo';

const FIRST_YEAR = 2015;
const MORE = '__more__';
const CURRENT = '__current__';

/** 분석 범위 컨트롤: 분석 지역·연도 선택과 기본 대상지 복귀. 표시는 표제란(TitleBlock)이 맡는다. */
export function AnalysisScopeBar() {
  const { year, gridId, region, setScope } = useAnalysisScope();
  const system = useSystemInfo();
  const navigate = useNavigate();
  const lastYear = Math.max(new Date().getFullYear(), year);
  const years = Array.from({ length: lastYear - FIRST_YEAR + 1 }, (_, i) => lastYear - i);
  if (!years.includes(year)) years.push(year);
  const defaultRegion = system?.default_region ?? '52110';
  const prepared = system?.regions ?? [];
  const current = region ?? defaultRegion;
  const options = prepared.length ? prepared : [{ code: defaultRegion, short_name: system?.region?.short_name ?? '전주시', name: system?.region?.name ?? '전북특별자치도 전주시' }];
  const known = options.some((option) => option.code === current);
  const pick = (value: string) => {
    if (value === MORE) { navigate('/regions'); return; }
    setScope({ region: value === defaultRegion ? null : value });
  };
  return <div className="scope-controls" title="지역·연도·격자는 모든 분석 화면에 함께 적용됩니다">
    <label className="scope-field"><span>분석 지역</span>
      <span className="select-wrap"><select aria-label="분석 지역" data-testid="region-select" value={known ? current : CURRENT} onChange={(e) => pick(e.target.value)}>
        {options.map((option) => <option key={option.code} value={option.code} title={option.name}>{option.short_name}</option>)}
        {!known && <option value={CURRENT} disabled>{system?.region?.short_name ?? current}</option>}
        <option value={MORE}>전국에서 고르기…</option>
      </select><ChevronDown size={15} aria-hidden="true" /></span>
    </label>
    <label className="scope-field"><span>분석연도</span>
      <span className="select-wrap"><select aria-label="분석연도" value={year} onChange={(e) => setScope({ year: Number(e.target.value) })}>{years.map((y) => <option key={y} value={y}>{y}년</option>)}</select><ChevronDown size={15} aria-hidden="true" /></span>
    </label>
    {gridId && <button type="button" className="button secondary small" onClick={() => setScope({ gridId: null })}>기본 대상지로</button>}
    <Link className="button ghost small scope-national" to="/regions" title="전국 시·군·구 개요와 지역 준비"><Globe2 size={15} aria-hidden="true" /><span>전국</span></Link>
  </div>;
}
