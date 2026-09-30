import { useState } from 'react';
import { AlertTriangle, Play } from 'lucide-react';
import { MissingValue } from '../components/MissingValue';
import { PageHeader } from '../components/PageHeader';
import { QualityBadge } from '../components/QualityBadge';
import { EmptyState, ErrorState, LoadingState } from '../components/Status';
import { ValidationPanel } from '../components/ValidationPanel';
import { useApi } from '../hooks/useApi';
import { useAnalysisScope } from '../hooks/useAnalysisScope';
import { api } from '../lib/api';
import { formatDate, formatMetric } from '../lib/format';
interface Candidate{name:string;metrics:Record<string,number|null>}
interface ModelInfo {name:string;energy_type?:string;status?:string;training_period?:string;observations?:number;grid_count?:number;spatial_blocks?:number;months?:number;requirements?:Record<string,number>;validation_method?:string;models?:Candidate[];limitations?:string[];features?:string[];unavailable_features?:string[];scope?:string;}
interface ModelResponse {status:string;reason?:string;models:ModelInfo[];last_validation?:ModelResponse;last_run_at?:string;}
export function ModelPage(){
 const {year,regionQuery}=useAnalysisScope();const {data,loading,error,reload,setData}=useApi<ModelResponse>(`/model?year=${year}${regionQuery}`);
 const [busy,setBusy]=useState(false);const [failure,setFailure]=useState<string|null>(null);
 const validate=async()=>{setBusy(true);setFailure(null);try{setData(await api<ModelResponse>(`/model/validate?year=${year}${regionQuery}`,{method:'POST'}));}catch(e){setFailure(e instanceof Error?e.message:'검증 실패');}finally{setBusy(false);}};
 if(loading)return <div className="page"><LoadingState/></div>;
 if(error||!data)return <div className="page"><ErrorState message={error} onRetry={reload}/></div>;
 const insufficient=data.status==='INSUFFICIENT_TRAINING_DATA';
 return <div className="page"><PageHeader title="에너지 모델" description="여러 공간에 걸친 관측으로 검증하고, 수집 데이터와 모델 추정을 구분합니다." action={<button className="button primary" onClick={()=>void validate()} disabled={busy}><Play size={15}/>{busy?'검증 중…':'현재 자료로 검증'}</button>}/>
 {failure&&<p role="alert" className="inline-error">{failure}</p>}{insufficient&&<section className="model-warning" role="status"><AlertTriangle aria-hidden="true"/><div><h2>학습 데이터 부족</h2><p>{data.reason??'공간 매칭된 에너지와 동일 범위 연면적이 충분해야 모델을 평가할 수 있습니다.'}</p><strong>자료 확보 전에는 예측 성능을 제시하지 않습니다.</strong></div></section>}
 <div className="model-grid">{data.models.map((m,i)=><article className="panel model-card" key={m.energy_type??i}><div className="panel-title"><h3>{m.energy_type==='GAS'?'가스':'전력'} 원단위 모델</h3>{m.status&&<QualityBadge value={m.status}/>}</div><div className="training-progress">{[['observations','관측','건',120],['grid_count','격자','개',10],['spatial_blocks','공간 블록','개',3],['months','관측 월','개월',10]].map(([key,label,unit,target])=>{const raw=m[key as keyof ModelInfo];const n=typeof raw==='number'?raw:null;return <div key={key}><span>{label}<b>{n===null?'—':n} / {target}{unit}</b></span>{n===null?<div className="score-track is-missing" title="자료 미확보"><span className="sr-only">자료 없음</span></div>:<progress max={Number(target)} value={n}/>}</div>;})}</div><dl className="compact-list"><div><dt>학습 기간</dt><dd>{m.training_period??'기록 없음'}</dd></div><div><dt>검증 방법</dt><dd>{methodText(data,m)}</dd></div>{m.features?.length?<div><dt>사용 변수</dt><dd>{m.features.join(', ')}</dd></div>:null}{m.unavailable_features?.length?<div><dt>아직 못 쓰는 변수</dt><dd>{m.unavailable_features.join(', ')}</dd></div>:null}</dl>{m.scope&&<p className="model-scope">대상: {m.scope}</p>}{m.models?.length?<CandidateTable rows={m.models}/>:priorBest(data,m)?<PriorSummary best={priorBest(data,m)!} at={data.last_run_at}/>:<EmptyState title="검증 결과 미산출" description="최소 표본 조건은 검증 시작 기준이며 정확도를 보장하지 않습니다."/>}</article>)}</div>
 <ValidationPanel regionQuery={regionQuery}/>
 {data.last_validation&&<section className="panel prior-validation"><h3>직전 저장 검증</h3><p>{data.last_run_at?`${formatDate(data.last_run_at)} 실행 결과입니다. `:'과거 검증 실행 당시의 결과입니다. '}새로 수집한 자료는 위 버튼으로 다시 평가하세요.</p>{data.last_validation.models.map((m,i)=><div key={i}><h4>{m.energy_type==='GAS'?'가스':'전력'}</h4>{m.models?.length?<CandidateTable rows={m.models}/>:<p>해당 실행에서 검증 가능한 표본이 부족했습니다.</p>}</div>)}</section>}
 </div>;
}
const korMethod=(text:string)=>text.includes('Spatial Block')?'공간 블록 교차검증 (2km 블록)':text;
function methodText(data:ModelResponse,m:ModelInfo){const own=m.validation_method&&m.validation_method!=='미검증'?m.validation_method:null;if(own)return korMethod(own);const prior=priorModel(data,m)?.validation_method;return prior&&prior!=='미검증'?`${korMethod(prior)} · 직전 실행`:priorBest(data,m)?'공간 블록 교차검증 (2km 블록) · 직전 실행':'아직 검증하지 않음';}
/** The same energy type in the last stored validation run. */
function priorModel(data:ModelResponse,m:ModelInfo){return data.last_validation?.models.find((x)=>x.energy_type===m.energy_type);}
function priorBest(data:ModelResponse,m:ModelInfo){const rows=priorModel(data,m)?.models??[];return rows.reduce<Candidate|null>((b,r)=>typeof r.metrics?.nmae==='number'&&(!b||(r.metrics.nmae as number)<(b.metrics.nmae as number))?r:b,null);}
function PriorSummary({best,at}:{best:Candidate;at?:string}){const v=(k:string,scale=1,digits=3)=>typeof best.metrics?.[k]==='number'?formatMetric((best.metrics[k] as number)*scale,'',digits):'—';
 return <div className="prior-best"><span>직전 검증{at?` (${formatDate(at)})`:''}의 오차 최소 모델</span><strong>{best.name}</strong><dl><div><dt>nMAE</dt><dd>{v('nmae',100,1)}%</dd></div><div><dt>R² 원단위</dt><dd>{v('intensity_r2')}</dd></div><div><dt>R² 총량</dt><dd>{v('r2')}</dd></div></dl><small>전체 비교는 아래 ‘직전 저장 검증’. ‘현재 자료로 검증’을 누르면 지금 DB로 다시 계산합니다.</small></div>;}
const METRIC_COLUMNS:[string,string,number,number][]=[['mae','MAE (kWh/격자·월)',0,1],['nmae','nMAE',1,100],['r2','R² 총량',3,1],['intensity_r2','R² 원단위',3,1]];
function CandidateTable({rows}:{rows:Candidate[]}){
 const best=rows.reduce<Candidate|null>((b,r)=>typeof r.metrics?.mae==='number'&&(!b||(r.metrics.mae as number)<(b.metrics.mae as number))?r:b,null);
 return <><div className="table-wrap"><table><thead><tr><th>비교 모델</th>{METRIC_COLUMNS.map(([k,label])=><th className="num" key={k}>{label}</th>)}</tr></thead><tbody>{rows.map((r,i)=><tr key={r.name??i}><td>{r.name}{best===r&&<span className="model-best"> 오차 최소</span>}</td>{METRIC_COLUMNS.map(([k,,digits,scale])=>{const v=r.metrics?.[k];return <td className="num" key={k}>{typeof v==='number'?`${formatMetric(v*scale,'',digits)}${k==='nmae'?'%':''}`:<MissingValue inline/>}</td>;})}</tr>)}</tbody></table></div>
 <p className="model-metric-note">공간 블록(2km) 교차검증의 검증 폴드 값입니다. R² 총량은 격자 연면적 크기만으로도 높게 나오므로, 격자 사이 kWh/m² 차이를 얼마나 설명하는지는 R² 원단위로 봅니다. nMAE는 평균 월 사용량 대비 평균 오차입니다.</p></>;}
