import { ChevronDown } from 'lucide-react';
import { useAnalysisScope } from '../hooks/useAnalysisScope';

const FIRST_YEAR = 2015;

/** 분석 범위 컨트롤: 연도 선택과 기본 대상지 복귀. 표시는 표제란(TitleBlock)이 맡는다. */
export function AnalysisScopeBar() {
  const { year, gridId, setScope } = useAnalysisScope();
  const lastYear = Math.max(new Date().getFullYear(), year);
  const years = Array.from({ length: lastYear - FIRST_YEAR + 1 }, (_, i) => lastYear - i);
  if (!years.includes(year)) years.push(year);
  return <div className="scope-controls" title="연도와 격자는 모든 분석 화면에 함께 적용됩니다">
    <label className="scope-field"><span>분석연도</span>
      <span className="select-wrap"><select aria-label="분석연도" value={year} onChange={(e) => setScope({ year: Number(e.target.value) })}>{years.map((y) => <option key={y} value={y}>{y}년</option>)}</select><ChevronDown size={15} aria-hidden="true" /></span>
    </label>
    {gridId && <button type="button" className="button secondary small" onClick={() => setScope({ gridId: null })}>기본 대상지로</button>}
  </div>;
}
