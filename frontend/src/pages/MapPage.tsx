import * as maplibregl from 'maplibre-gl';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import { Layers3, LocateFixed } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { PageHeader } from '../components/PageHeader';
import { ErrorState, LoadingState } from '../components/Status';
import { useApi } from '../hooks/useApi';
import { useAnalysisScope } from '../hooks/useAnalysisScope';
import { api } from '../lib/api';
import { formatMetric } from '../lib/format';
import type { DashboardData, MapData, OverlayData } from '../types';
maplibregl.setWorkerUrl(workerUrl);
const metrics: Record<string,{label:string;unit:string}>={electricity_kwh:{label:'전력 사용량',unit:'kWh'},gas_kwh:{label:'가스 사용량',unit:'kWh'},carbon_kg:{label:'탄소배출량',unit:'kgCO₂eq'},carbon_intensity:{label:'탄소집약도',unit:'kgCO₂eq/m²'},far:{label:'용적률',unit:'%'},residential_zone_ratio:{label:'주거지역 비율',unit:'%'},population_density:{label:'격자 인구밀도',unit:'명/km²'},completeness:{label:'데이터 완전성',unit:'%'}};
export const ZONE_LEGEND:ReadonlyArray<readonly [string,string,string]>=[['RESIDENTIAL','주거지역','#f2c14e'],['COMMERCIAL','상업지역','#e4572e'],['INDUSTRIAL','공업지역','#8d6cab'],['GREEN','녹지지역','#5aa469'],['OTHER','기타·미분류','#b8c2c0']];
type LayerKey='grids'|'buildings'|'boundary'|'zoning'|'admin';
const LAYER_IDS:Record<LayerKey,string[]>={grids:['grid-fill','grid-line','selected-grid'],buildings:['buildings-fill'],boundary:['boundary-line'],zoning:['zoning-fill','zoning-line'],admin:['admin-fill','admin-line']};
const DEFAULT_VISIBLE:Record<LayerKey,boolean>={grids:true,buildings:true,boundary:true,zoning:false,admin:false};
export function MapPage(){
 const {year,gridId,query,setScope}=useAnalysisScope();
 const {data,loading,error,reload}=useApi<MapData>(`/map?year=${year}`);
 const details=useApi<DashboardData>(`/dashboard?${query}`);
 const overlays=useApi<OverlayData>(`/map/overlays?year=${year}`);
 const [mapReady,setMapReady]=useState(0);const [adminInfo,setAdminInfo]=useState<Record<string,unknown>|null>(null);
 const container=useRef<HTMLDivElement>(null);const mapRef=useRef<maplibregl.Map|null>(null);
 const [offline,setOffline]=useState<boolean|null>(null);const [mapError,setMapError]=useState<string|null>(null);
 const [basemapEnabled,setBasemapEnabled]=useState(true);const [basemapFailed,setBasemapFailed]=useState(false);
 const [metric,setMetric]=useState('carbon_kg');const [visible,setVisible]=useState<Record<LayerKey,boolean>>(DEFAULT_VISIBLE);
 const visibleRef=useRef(visible);visibleRef.current=visible;
 const selectedId=gridId || String(data?.selected_sector?.grid_id || '');
 const selectedRef=useRef(selectedId);selectedRef.current=selectedId;
 const values=data?.grids.features.map(f=>f.properties?.[metric]).filter((v):v is number=>typeof v==='number'&&Number.isFinite(v))||[];
 const max=values.length?Math.max(...values):0;
 useEffect(()=>{const update=()=>{api<{offline_mode:boolean}>('/system').then(s=>setOffline(s.offline_mode)).catch(()=>setOffline(true));};update();window.addEventListener('carbon-system-change',update);return()=>window.removeEventListener('carbon-system-change',update);},[]);
 useEffect(()=>{
  if(!container.current||!data||offline===null)return;
  setMapError(null);setBasemapFailed(false);setMetric('carbon_kg');setVisible(DEFAULT_VISIBLE);setAdminInfo(null);
  const showBasemap=!offline&&basemapEnabled;
  const map=new maplibregl.Map({container:container.current,center:data.center||[127.148,35.824],zoom:11.5,attributionControl:false,style:{version:8,sources:showBasemap?{basemap:{type:'raster',tiles:['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],tileSize:256,attribution:'© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap contributors</a>'}}:{},layers:[{id:'background',type:'background',paint:{'background-color':'#edf2ef'}},...(showBasemap?[{id:'basemap',type:'raster' as const,source:'basemap',paint:{'raster-opacity':0.5}}]:[])]}});
  map.addControl(new maplibregl.NavigationControl({showCompass:false}),'bottom-right');map.addControl(new maplibregl.AttributionControl({compact:false,customAttribution:'분석 도형: © OpenStreetMap contributors'}),'bottom-left');
  map.on('error',e=>{if(isBasemapError(e)){setBasemapFailed(true);if(map.getLayer('basemap'))map.removeLayer('basemap');if(map.getSource('basemap'))map.removeSource('basemap');}else setMapError('지도 도형을 불러오지 못했습니다. 새로고침해 주세요.');});
  map.on('load',()=>{
   for(const key of ['boundary','grids','buildings'] as const)map.addSource(key,{type:'geojson',data:data[key]});
   map.addLayer({id:'boundary-line',type:'line',source:'boundary',paint:{'line-color':'#587b75','line-width':2}});
   map.addLayer({id:'grid-fill',type:'fill',source:'grids',paint:{'fill-color':metricColor('carbon_kg'),'fill-opacity':0.48}});
   map.addLayer({id:'grid-line',type:'line',source:'grids',paint:{'line-color':'#88a8a1','line-width':0.5}});
   map.addLayer({id:'buildings-fill',type:'fill',source:'buildings',paint:{'fill-color':'#526d75','fill-opacity':0.65}});
   map.addLayer({id:'selected-grid',type:'line',source:'grids',filter:selectedFilter(selectedRef.current),paint:{'line-color':'#e77824','line-width':4}});
   fitToData(map,data.boundary?.features?.length?data.boundary:data.grids);
   map.on('click','grid-fill',e=>{const id=e.features?.[0]?.properties?.id??e.features?.[0]?.properties?.grid_id;if(id)setScope({gridId:String(id)});});
   map.on('mouseenter','grid-fill',()=>{map.getCanvas().style.cursor='pointer';});map.on('mouseleave','grid-fill',()=>{map.getCanvas().style.cursor='';});
   setMapReady(n=>n+1);
  });
  map.on('idle',()=>{const el=container.current;if(!el)return;if(map.getLayer('grid-fill'))el.dataset.renderedFeatures=String(map.queryRenderedFeatures({layers:['grid-fill']}).length);for(const [key,id] of [['renderedZoning','zoning-fill'],['renderedAdmin','admin-fill']] as const){el.dataset[key]=map.getLayer(id)&&map.getLayoutProperty(id,'visibility')==='visible'?String(map.queryRenderedFeatures({layers:[id]}).length):'0';}});
  mapRef.current=map;return()=>{map.remove();mapRef.current=null;};
 },[data,offline,basemapEnabled]);
 useEffect(()=>{const m=mapRef.current;if(m?.getLayer('selected-grid'))m.setFilter('selected-grid',selectedFilter(selectedId));},[selectedId]);
 useEffect(()=>{const m=mapRef.current;if(m?.getLayer('grid-fill'))m.setPaintProperty('grid-fill','fill-color',metricColor(metric,max));},[metric,max]);
 useEffect(()=>{const m=mapRef.current;if(!m?.getLayer('grid-fill'))return;applyVisibility(m,visible);},[visible]);
 useEffect(()=>{const m=mapRef.current;const o=overlays.data;if(!m||!mapReady||!o)return;if(addOverlayLayers(m,o)){m.on('click','admin-fill',e=>setAdminInfo((e.features?.[0]?.properties as Record<string,unknown>|undefined)??null));for(const id of ['admin-fill','zoning-fill']){m.on('mouseenter',id,()=>{m.getCanvas().style.cursor='pointer';});m.on('mouseleave',id,()=>{m.getCanvas().style.cursor='';});}}applyVisibility(m,visibleRef.current);},[overlays.data,mapReady]);
 if(loading)return <div className="page"><LoadingState label="공간 레이어를 불러오는 중입니다"/></div>;
 if(error||!data)return <div className="page"><ErrorState message={error} onRetry={reload}/></div>;
 const overlayMeta=overlays.data?.meta;const adminMax=maxOf(overlays.data?.admin,'population_density');
 const detail=details.data;const selectedFeature=data.grids.features.find(f=>String(f.properties?.id)===selectedId);
 const focus=()=>{if(mapRef.current&&selectedFeature)fitToData(mapRef.current,{type:'FeatureCollection',features:[selectedFeature]},15);};
 return <div className="page map-page"><PageHeader eyebrow="SPATIAL EXPLORER" title="도시 탄소 지도" description="격자를 선택하면 다른 분석 화면에도 동일한 대상지가 적용됩니다." action={<button className="button secondary" onClick={reload}>새로고침</button>}/>
 <div className="map-workspace"><div ref={container} className="map-canvas" aria-label="전주시 탄소 공간 지도"/>
 <div className="map-metrics floating-panel" role="group" aria-label="지도 지표">{Object.entries(metrics).map(([key,item])=><button key={key} onClick={()=>setMetric(key)} className={metric===key?'active':''}>{item.label}</button>)}</div>
 <div className="map-legend floating-panel"><strong><Layers3 size={15}/>레이어</strong>{([['grids','분석 격자'],['buildings','건물'],['boundary','전주시 경계']] as const).map(([key,label])=><label key={key}><input type="checkbox" checked={visible[key]} onChange={e=>setVisible({...visible,[key]:e.target.checked})}/>{label}</label>)}{([['zoning','용도지역 (VWorld)',overlayMeta?.zoning_features??0],['admin','행정동 인구 (SGIS)',overlayMeta?.admin_features??0]] as const).map(([key,label,count])=><label key={key} title={count?`${count}개 도형`:'아직 수집되지 않았습니다'}><input type="checkbox" checked={visible[key]} disabled={!count} onChange={e=>setVisible({...visible,[key]:e.target.checked})}/>{label}{!count&&<small className="overlay-empty">{overlays.loading?'확인 중':'미수집'}</small>}</label>)}<hr/><strong>{metrics[metric].label}</strong>{values.length?<><div className="legend-ramp"/><div className="legend-range"><span>0</span><span>{formatMetric(max,metrics[metric].unit,1)}</span></div></>:<p>이 연도의 관측값 없음</p>}<span className="legend-missing">■ 회색은 결측</span><span className="legend-selected">□ 주황 테두리는 선택 격자</span>{visible.zoning&&<div className="overlay-legend" aria-label="용도지역 범례"><hr/><strong>용도지역</strong>{ZONE_LEGEND.map(([key,label,color])=><span key={key}><i style={{background:color}}/>{label}</span>)}<small>VWorld LT_C_UQ111 · {overlayMeta?.zoning_features??0}개 도형</small></div>}{visible.admin&&<div className="overlay-legend" aria-label="행정동 인구 범례"><hr/><strong>행정동 인구밀도</strong><div className="legend-ramp admin"/><div className="legend-range"><span>0</span><span>{formatMetric(adminMax,'명/km²',0)}</span></div><small>SGIS {overlayMeta?.admin_reference_year??''} 행정통계 · 공식 행정동 경계 · 격자 배분 없음</small>{adminInfo&&<dl className="admin-info"><div><dt>행정동</dt><dd>{String(adminInfo.adm_name??'—')}</dd></div><div><dt>인구</dt><dd>{statValue(adminInfo.population,adminInfo.population_status,'명')}</dd></div><div><dt>가구</dt><dd>{statValue(adminInfo.households,adminInfo.household_status,'가구')}</dd></div><div><dt>인구밀도</dt><dd>{typeof adminInfo.population_density==='number'?formatMetric(adminInfo.population_density,'명/km²',0):'자료 없음'}</dd></div></dl>}</div>}</div>
 <aside className="map-detail floating-panel"><div className="panel-title"><div><span>SELECTED GRID</span><h3>{detail?.selected_sector?.name||'대상지 확인 중'}</h3></div><button className="icon-link" aria-label="선택 격자로 확대" onClick={focus}><LocateFixed size={20}/></button></div><p className="grid-id">{selectedId}</p><dl className="compact-list"><div><dt>분석 면적</dt><dd>250,000 m²</dd></div><div><dt>건물 도형</dt><dd>{String(selectedFeature?.properties?.building_count??'—')}개</dd></div><div><dt>기준기간</dt><dd>{year}.01 ~ {year}.12</dd></div></dl>{details.error?<p role="alert">{details.error}</p>:<><div className="grid-metrics">{(['electricity_kwh','gas_kwh','carbon_kg'] as const).map(key=><div key={key}><span>{metrics[key].label}</span><strong>{details.loading?'확인 중':formatMetric(detail?.[key],metrics[key].unit)}</strong></div>)}</div><p className="muted">관측 지번 합계입니다. 결측값은 저소비를 의미하지 않습니다.</p><div className="coverage-months" aria-label="월별 전력 자료 확보">{detail?.monthly.map(r=><span key={r.use_ym} title={r.electricity_kwh===null?'전력 미확보':'전력 확보'} className={r.electricity_kwh===null?'':'available'}>{r.use_ym.slice(-2)}</span>)}</div></>}
 <div className="grid-actions"><Link className="button primary" to="/simulation">이 격자 시뮬레이션</Link><Link className="button secondary" to="/reports">보고서 작성</Link></div></aside>
 <div className="basemap-control"><label><input type="checkbox" checked={basemapEnabled&&!offline} disabled={!!offline} onChange={e=>setBasemapEnabled(e.target.checked)}/>배경지도</label>{basemapFailed&&<span role="status">배경지도 연결 실패 · 분석 도형은 이용 가능합니다.</span>}</div>
 {mapError&&<p role="alert" className="map-error">{mapError}</p>}<div className="map-source-pill">{offline||!basemapEnabled||basemapFailed?'로컬 분석 도형':'온라인 배경 지도'} · EPSG:5179 · {metrics[metric].unit} · 출처는 수집 데이터에서 확인</div></div></div>;
}
export function isBasemapError(event:{sourceId?:string;error?:{message?:string}}){return event.sourceId==='basemap'||!!event.error?.message?.includes('tile.openstreetmap.org');}
export function selectedFilter(id:string|number|undefined):maplibregl.FilterSpecification{return ['==',['to-string',['coalesce',['get','grid_id'],['get','id']]],String(id??'')];}
export function metricColor(metric:string,max=50000):maplibregl.ExpressionSpecification{return ['case',['==',['get',metric],null],'#cbd5d1',['interpolate',['linear'],['to-number',['get',metric]],0,'#e1f3ed',Math.max(max,1)/2,'#43b5a1',Math.max(max,1),'#075d53']];}
function fitToData(map:maplibregl.Map,collection:GeoJSON.FeatureCollection,maxZoom=13){const bounds=new maplibregl.LngLatBounds();const visit=(v:unknown)=>{if(Array.isArray(v)&&typeof v[0]==='number'&&typeof v[1]==='number')bounds.extend(v as [number,number]);else if(Array.isArray(v))v.forEach(visit);};collection.features.forEach(f=>visit((f.geometry as {coordinates:unknown}).coordinates));if(!bounds.isEmpty())map.fitBounds(bounds,{padding:45,maxZoom,duration:0});}
export function zoneColor():maplibregl.ExpressionSpecification{return ['match',['get','category'],...ZONE_LEGEND.slice(0,4).flatMap(([key,,color])=>[key,color]),ZONE_LEGEND[4][2]] as unknown as maplibregl.ExpressionSpecification;}
export function densityColor(max:number):maplibregl.ExpressionSpecification{return ['case',['==',['get','population_density'],null],'#d7d3de',['interpolate',['linear'],['to-number',['get','population_density']],0,'#f3eefb',Math.max(max,1)/2,'#9b7fd0',Math.max(max,1),'#4b2b86']];}
export function maxOf(collection:GeoJSON.FeatureCollection|undefined,key:string){const values=(collection?.features??[]).map(f=>f.properties?.[key]).filter((v):v is number=>typeof v==='number'&&Number.isFinite(v));return values.length?Math.max(...values):0;}
export function statValue(value:unknown,status:unknown,unit:string){if(typeof value==='number')return formatMetric(value,unit,0);return status==='SUPPRESSED'?'비공개(*)':status==='NOT_COLLECTED'?'미수집':'자료 없음';}
function applyVisibility(map:maplibregl.Map,visible:Record<LayerKey,boolean>){for(const [key,ids] of Object.entries(LAYER_IDS) as [LayerKey,string[]][])ids.forEach(id=>{if(map.getLayer(id))map.setLayoutProperty(id,'visibility',visible[key]?'visible':'none');});}
export function addOverlayLayers(map:maplibregl.Map,data:OverlayData):boolean{
 for(const key of ['zoning','admin'] as const){const source=map.getSource(key) as maplibregl.GeoJSONSource|undefined;if(source)source.setData(data[key]);else map.addSource(key,{type:'geojson',data:data[key]});}
 if(map.getLayer('zoning-fill')){map.setPaintProperty('admin-fill','fill-color',densityColor(maxOf(data.admin,'population_density')));return false;}
 const before=map.getLayer('buildings-fill')?'buildings-fill':undefined;
 map.addLayer({id:'zoning-fill',type:'fill',source:'zoning',layout:{visibility:'none'},paint:{'fill-color':zoneColor(),'fill-opacity':0.55}},before);
 map.addLayer({id:'zoning-line',type:'line',source:'zoning',layout:{visibility:'none'},paint:{'line-color':'#ffffff','line-width':0.4}},before);
 map.addLayer({id:'admin-fill',type:'fill',source:'admin',layout:{visibility:'none'},paint:{'fill-color':densityColor(maxOf(data.admin,'population_density')),'fill-opacity':0.5}},before);
 map.addLayer({id:'admin-line',type:'line',source:'admin',layout:{visibility:'none'},paint:{'line-color':'#5b3f8f','line-width':1.2}},before);
 return true;
}
