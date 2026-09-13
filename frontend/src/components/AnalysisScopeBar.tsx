import { CalendarDays, MapPin } from 'lucide-react';
import { useAnalysisScope } from '../hooks/useAnalysisScope';
export function AnalysisScopeBar(){
  const {year,gridId,setScope}=useAnalysisScope();
  return <div className="analysis-scope-bar"><label><CalendarDays size={16}/>분석연도<select aria-label="분석연도" value={year} onChange={e=>setScope({year:Number(e.target.value)})}>{Array.from({length:101},(_,i)=>2000+i).map(y=><option key={y} value={y}>{y}년</option>)}</select></label><span className="scope-grid"><MapPin size={16}/>{gridId || '예비 선정 격자 · LG동아 인근'}</span>{gridId && <button className="text-button" onClick={()=>setScope({gridId:null})}>기본 대상지</button>}<small>모든 분석 화면에 동일하게 적용</small></div>;
}
