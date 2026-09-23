import { CalendarDays, ChevronDown, MapPin } from 'lucide-react';
import { useAnalysisScope } from '../hooks/useAnalysisScope';

const FIRST_YEAR = 2015;

export function AnalysisScopeBar() {
  const { year, gridId, setScope } = useAnalysisScope();
  const lastYear = Math.max(new Date().getFullYear(), year);
  const years = Array.from({ length: lastYear - FIRST_YEAR + 1 }, (_, i) => lastYear - i);
  if (!years.includes(year)) years.push(year);
  return <div className="analysis-scope-bar">
    <label className="scope-field"><CalendarDays size={17} />분석연도
      <span className="glass-select"><select aria-label="분석연도" value={year} onChange={(e) => setScope({ year: Number(e.target.value) })}>{years.map((y) => <option key={y} value={y}>{y}년</option>)}</select><ChevronDown size={15} /></span>
    </label>
    <span className="scope-chip"><MapPin size={15} />{gridId ? <>선택 격자 <code>{gridId}</code></> : '예비 선정 격자 · LG동아 인근'}</span>
    {gridId && <button className="text-button" onClick={() => setScope({ gridId: null })}>기본 대상지로</button>}
    <small>연도·격자는 모든 분석 화면에 같이 적용됩니다</small>
  </div>;
}
