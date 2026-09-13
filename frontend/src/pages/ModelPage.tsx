import { useState } from 'react';
import { AlertTriangle, Play } from 'lucide-react';
import { PageHeader } from '../components/PageHeader';
import { QualityBadge } from '../components/QualityBadge';
import { EmptyState, ErrorState, LoadingState } from '../components/Status';
import { useApi } from '../hooks/useApi';
import { useAnalysisScope } from '../hooks/useAnalysisScope';
import { api } from '../lib/api';
import { formatMetric } from '../lib/format';
interface Candidate{name:string;metrics:Record<string,number|null>}
interface ModelInfo {name:string;energy_type?:string;status?:string;training_period?:string;observations?:number;grid_count?:number;spatial_blocks?:number;months?:number;requirements?:Record<string,number>;validation_method?:string;models?:Candidate[];limitations?:string[];}
interface ModelResponse {status:string;reason?:string;models:ModelInfo[];last_validation?:ModelResponse;}
export function ModelPage(){
 const {year}=useAnalysisScope();const {data,loading,error,reload,setData}=useApi<ModelResponse>(`/model?year=${year}`);
 const [busy,setBusy]=useState(false);const [failure,setFailure]=useState<string|null>(null);
 const validate=async()=>{setBusy(true);setFailure(null);try{setData(await api<ModelResponse>(`/model/validate?year=${year}`,{method:'POST'}));}catch(e){setFailure(e instanceof Error?e.message:'검증 실패');}finally{setBusy(false);}};
 if(loading)return <div className="page"><LoadingState/></div>;
 if(error||!data)return <div className="page"><ErrorState message={error} onRetry={reload}/></div>;
 const insufficient=data.status==='INSUFFICIENT_TRAINING_DATA';
 return <div className="page"><PageHeader eyebrow="SPATIAL VALIDATION" title="에너지 모델" description="여러 공간에 걸친 관측으로 검증하고, 수집 데이터와 모델 추정을 구분합니다." action={<button className="button primary" onClick={()=>void validate()} disabled={busy}><Play size={15}/>{busy?'검증 중…':'현재 자료로 검증'}</button>}/>
 {failure&&<p role="alert" className="inline-error">{failure}</p>}{insufficient&&<section className="model-warning"><AlertTriangle/><div><h2>학습 데이터 부족</h2><p>{data.reason??'공간 매칭된 에너지와 동일 범위 연면적이 충분해야 모델을 평가할 수 있습니다.'}</p><strong>자료 확보 전에는 예측 성능을 제시하지 않습니다.</strong></div></section>}
 <div className="model-grid">{data.models.map((m,i)=><article className="panel model-card" key={m.energy_type??i}><div className="panel-title"><div><span>{m.energy_type==='GAS'?'GAS':'ELECTRICITY'}</span><h3>{m.energy_type==='GAS'?'가스':'전력'} 원단위 모델</h3></div><QualityBadge value={m.status}/></div><div className="training-progress">{[['observations','관측','건',120],['grid_count','격자','개',10],['spatial_blocks','공간 블록','개',3],['months','관측 월','개월',10]].map(([key,label,unit,target])=>{const n=Number(m[key as keyof ModelInfo]??0);return <div key={key}><span>{label}<b>{n} / {target}{unit}</b></span><progress max={Number(target)} value={n}/></div>;})}</div><p className="muted">{m.training_period} · {m.validation_method??'미검증'}</p>{m.models?.length?<CandidateTable rows={m.models}/>:<EmptyState title="검증 결과 미산출" description="최소 표본 조건은 검증 시작 기준이며 정확도를 보장하지 않습니다."/>}</article>)}</div>
 {data.last_validation&&<section className="panel prior-validation"><h3>직전 저장 검증</h3><p>과거 검증 실행 당시의 결과입니다. 새로 수집한 자료는 위 버튼으로 다시 평가하세요.</p>{data.last_validation.models.map((m,i)=><div key={i}><h4>{m.energy_type==='GAS'?'가스':'전력'}</h4>{m.models?.length?<CandidateTable rows={m.models}/>:<p>해당 실행에서 검증 가능한 표본이 부족했습니다.</p>}</div>)}</section>}
 </div>;
}
function CandidateTable({rows}:{rows:Candidate[]}){return <div className="table-wrap"><table><thead><tr><th>비교 모델</th><th>MAE</th><th>RMSE</th><th>R²</th></tr></thead><tbody>{rows.map((r,i)=><tr key={r.name??i}><td>{r.name}</td>{['mae','rmse','r2'].map(k=><td key={k}>{formatMetric(r.metrics?.[k],'',3)}</td>)}</tr>)}</tbody></table></div>;}
