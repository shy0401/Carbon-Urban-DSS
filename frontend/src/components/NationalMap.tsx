import * as maplibregl from 'maplibre-gl';
import { ArrowLeft, ChevronDown, Layers3, MapPinned, X } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { setBasemapStatus } from '../hooks/useBasemapStatus';
import { useApi } from '../hooks/useApi';
import { api } from '../lib/api';
import { formatMetric } from '../lib/format';
import { addHatchImage, HATCH } from '../lib/mapHatch';
import { classify, rangeLabel, stepColor, type Classification } from '../lib/mapMetrics';
import { DEFAULT_NATIONAL_METRIC, levelLabel, metricValue, missingReason, NATIONAL_METRICS, provinceGroups, shortProvince, type NationalMetric } from '../lib/nationalMetrics';
import { LINE_ON_BASEMAP, TOKENS } from '../theme/palette';
import type { NationalData, NationalMetrics, NationalProvince, NationalProvinceRegions, NationalRegion } from '../types';
import { LayerGroupTitle, LayerToggle } from './LayerToggle';
import { ErrorState, LoadingState } from './Status';

const EMPTY: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features: [] };
const KOREA: [number, number, number, number] = [124.6, 33.1, 130.95, 38.62];
const NO_CLASSES: Classification = { classes: [], lowerBounds: [], valued: 0, missing: 0, min: null, max: null };
const KIND_LABEL = { PROVINCE: '도', METRO: '특별시·광역시' } as const;
function isBasemapError(event: { sourceId?: string; error?: { message?: string } }) { return event.sourceId === 'basemap' || !!event.error?.message?.includes('tile.openstreetmap.org'); }
function escapeHtml(value: unknown): string { return String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] ?? c); }

/** [west, south, east, north] of GeoJSON geometries (null when there are no coordinates). */
export function bboxOf(features: GeoJSON.Feature[]): [number, number, number, number] | null {
  let w = Infinity, s = Infinity, e = -Infinity, n = -Infinity;
  const visit = (v: unknown) => {
    if (Array.isArray(v) && typeof v[0] === 'number') { const [x, y] = v as number[]; if (x < w) w = x; if (x > e) e = x; if (y < s) s = y; if (y > n) n = y; }
    else if (Array.isArray(v)) v.forEach(visit);
  };
  for (const f of features) visit((f.geometry as { coordinates?: unknown } | null)?.coordinates);
  return Number.isFinite(w) ? [w, s, e, n] : null;
}

/** 시·도 boundaries with the metric value under ``v`` (for coloring). */
export function provinceFeatures(data: NationalData | null, metric: NationalMetric['key']): GeoJSON.FeatureCollection {
  if (!data) return EMPTY;
  const byCode = new Map(data.provinces.map((p) => [p.code, p]));
  return { type: 'FeatureCollection', features: data.boundaries.features.map((f) => ({ ...f, properties: { ...f.properties, v: metricValue(byCode.get(String(f.properties?.code))?.metrics, metric) } })) };
}

/** Regions of one 시·도, highest value first; regions without a value last (never ranked as 0). */
export function rankRegions(regions: NationalRegion[], sido: string | null, metric: NationalMetric['key']): NationalRegion[] {
  return regions.filter((r) => r.sido === sido)
    .sort((a, b) => (metricValue(b.metrics, metric) ?? -Infinity) - (metricValue(a.metrics, metric) ?? -Infinity) || a.short_name.localeCompare(b.short_name, 'ko'));
}

function fit(map: maplibregl.Map, bbox: [number, number, number, number] | null) {
  if (!bbox) return;
  const width = map.getContainer().clientWidth;
  const stacked = typeof window !== 'undefined' && !!window.matchMedia?.('(max-width: 760px)').matches;
  const left = stacked ? 16 : Math.min(320, Math.max(24, width - 240));
  map.fitBounds(bbox, { padding: { top: 32, bottom: 32, left, right: stacked ? 16 : 32 }, duration: 0 });
}

/**
 * 지도 분석 1단계: 전국. 시·도를 지도(누르기)나 왼쪽 메뉴에서 고르면 그 시·도의 시·군·구가 지도에 나오고,
 * 시·군·구를 고르면 요약과 함께 시·군·구 지도(읍면동 포함)나 시·도 500m 격자로 들어간다.
 */
export function NationalMap({ sido, sgg, onSido, onSgg, onProvinceGrid, onOpenRegion, offline }: {
  sido: string | null; sgg: string | null; onSido: (code: string | null) => void; onSgg: (code: string | null) => void;
  onProvinceGrid: (code: string) => void; onOpenRegion: (code: string) => void; offline: boolean | null;
}) {
  const national = useApi<NationalData>('/map/national');
  const [regionsGeo, setRegionsGeo] = useState<{ code: string; data: NationalProvinceRegions | null; error: string | null } | null>(null);
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const markers = useRef<maplibregl.Marker[]>([]);
  const popup = useRef<maplibregl.Popup | null>(null);
  const [ready, setReady] = useState(0);
  const [metricKey, setMetricKey] = useState<NationalMetric['key']>(DEFAULT_NATIONAL_METRIC);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [layersOpen, setLayersOpen] = useState(false);
  const [legendOpen, setLegendOpen] = useState(() => typeof window === 'undefined' || window.innerWidth > 720);
  const [basemap, setBasemap] = useState(true);
  const [basemapFailed, setBasemapFailed] = useState(false);
  const moved = useRef(false);
  const data = national.data;
  const metric = NATIONAL_METRICS.find((m) => m.key === metricKey) ?? NATIONAL_METRICS[0];
  const province = data?.provinces.find((p) => p.code === sido) ?? null;
  const region = data?.regions.find((r) => r.code === sgg) ?? null;
  const provFeatures = useMemo(() => provinceFeatures(data, metric.key), [data, metric.key]);
  const provClasses = useMemo(() => (data ? classify(data.provinces.map((p) => metricValue(p.metrics, metric.key)), metric.breaks, metric.ramp) : NO_CLASSES), [data, metric]);
  const sggData = regionsGeo && regionsGeo.code === sido ? regionsGeo.data : null;
  const sggClasses = useMemo(() => (sggData ? classify(sggData.boundaries.features.map((f) => metricValue(f.properties as NationalMetrics, metric.key)), metric.breaks, metric.ramp) : NO_CLASSES), [sggData, metric]);
  const ranked = useMemo(() => rankRegions(data?.regions ?? [], sido, metric.key), [data, sido, metric.key]);
  const classes = sido ? sggClasses : provClasses;
  const refs = useRef({ data, metric, sido, sgg, onSido, onSgg }); refs.current = { data, metric, sido, sgg, onSido, onSgg };
  const showBasemap = offline === false && basemap && !basemapFailed;

  useEffect(() => { if (offline !== null) setBasemapStatus(showBasemap ? 'shown' : 'none'); }, [offline, showBasemap]);
  // 시·도를 고르면 그 시·도의 시·군·구 경계를 읽는다.
  useEffect(() => {
    if (!sido) return undefined;
    let live = true;
    setRegionsGeo({ code: sido, data: null, error: null });
    api<NationalProvinceRegions>(`/map/national/${sido}`)
      .then((body) => { if (live) setRegionsGeo({ code: sido, data: body, error: null }); })
      .catch((e) => { if (live) setRegionsGeo({ code: sido, data: null, error: e instanceof Error ? e.message : '시·군·구 경계를 불러오지 못했습니다.' }); });
    return () => { live = false; };
  }, [sido]);

  useEffect(() => {
    if (!container.current || offline === null) return undefined;
    const withBasemap = !offline && basemap;
    setBasemapFailed(false);
    const map = new maplibregl.Map({
      container: container.current, bounds: KOREA, attributionControl: false, doubleClickZoom: false,
      style: { version: 8, sources: withBasemap ? { basemap: { type: 'raster', tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'], tileSize: 256, attribution: '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap contributors</a>' } } : {}, layers: [{ id: 'background', type: 'background', paint: { 'background-color': TOKENS.canvas } }, ...(withBasemap ? [{ id: 'basemap', type: 'raster' as const, source: 'basemap', paint: { 'raster-opacity': 0.5, 'raster-saturation': -0.8 } }] : [])] },
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'bottom-right');
    map.addControl(new maplibregl.ScaleControl({ maxWidth: 96, unit: 'metric' }), 'bottom-left');
    map.addControl(new maplibregl.AttributionControl({ compact: true, customAttribution: '경계·통계 SGIS, 단지 K-apt' }), 'bottom-right');
    map.on('movestart', (e) => { if ((e as { originalEvent?: unknown }).originalEvent) moved.current = true; });
    map.on('error', (e) => { if (isBasemapError(e as { sourceId?: string; error?: { message?: string } })) { setBasemapFailed(true); if (map.getLayer('basemap')) map.removeLayer('basemap'); } });
    map.on('load', () => {
      map.addSource('nt-prov', { type: 'geojson', data: EMPTY });
      map.addSource('nt-sgg', { type: 'geojson', data: EMPTY });
      map.addLayer({ id: 'nt-prov-fill', type: 'fill', source: 'nt-prov', paint: { 'fill-color': TOKENS['prov-missing-bg'], 'fill-opacity': 0.85 } });
      map.addLayer({ id: 'nt-sgg-fill', type: 'fill', source: 'nt-sgg', paint: { 'fill-color': TOKENS['prov-missing-bg'], 'fill-opacity': 0.88 } });
      addHatchImage(map);
      // 값 없는 곳은 해치 (램프의 가장 옅은 색과 구분, 0이 아님)
      map.addLayer({ id: 'nt-prov-missing', type: 'fill', source: 'nt-prov', filter: ['==', ['get', 'v'], null], paint: { 'fill-pattern': HATCH, 'fill-opacity': 0.9 } });
      map.addLayer({ id: 'nt-sgg-missing', type: 'fill', source: 'nt-sgg', filter: ['==', ['get', 'code'], ''], paint: { 'fill-pattern': HATCH, 'fill-opacity': 0.9 } });
      map.addLayer({ id: 'nt-sgg-line', type: 'line', source: 'nt-sgg', paint: { 'line-color': TOKENS.surface, 'line-width': 1 } });
      map.addLayer({ id: 'nt-prov-line', type: 'line', source: 'nt-prov', paint: { 'line-color': TOKENS['ink-2'], 'line-width': ['interpolate', ['linear'], ['zoom'], 5, 0.8, 9, 1.6] } });
      map.addLayer({ id: 'nt-sgg-detailed-halo', type: 'line', source: 'nt-sgg', filter: ['==', ['get', 'level'], 'DETAILED'], paint: { 'line-color': TOKENS['select-halo'], 'line-width': 5 } });
      map.addLayer({ id: 'nt-sgg-detailed', type: 'line', source: 'nt-sgg', filter: ['==', ['get', 'level'], 'DETAILED'], paint: { 'line-color': TOKENS.primary, 'line-width': 2.5 } });
      map.addLayer({ id: 'nt-hover', type: 'line', source: 'nt-sgg', filter: ['==', ['get', 'code'], ''], paint: { 'line-color': TOKENS['select-line'], 'line-width': 1.5 } });
      map.addLayer({ id: 'nt-prov-hover', type: 'line', source: 'nt-prov', filter: ['==', ['get', 'code'], ''], paint: { 'line-color': TOKENS['select-line'], 'line-width': 1.5 } });
      map.addLayer({ id: 'nt-prov-selected', type: 'line', source: 'nt-prov', filter: ['==', ['get', 'code'], ''], paint: { 'line-color': TOKENS['select-line'], 'line-width': 2.5 } });
      map.addLayer({ id: 'nt-sgg-selected-halo', type: 'line', source: 'nt-sgg', filter: ['==', ['get', 'code'], ''], paint: { 'line-color': TOKENS['select-halo'], 'line-width': 5 } });
      map.addLayer({ id: 'nt-sgg-selected', type: 'line', source: 'nt-sgg', filter: ['==', ['get', 'code'], ''], paint: { 'line-color': TOKENS['select-line'], 'line-width': 2.5 } });
      popup.current = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 10, maxWidth: '260px' });
      const onRegion = (point: maplibregl.PointLike) => map.queryRenderedFeatures(point, { layers: ['nt-sgg-fill'] })[0];
      map.on('mousemove', (e) => {
        const current = refs.current;
        const r = onRegion(e.point);
        const p = r ? null : map.queryRenderedFeatures(e.point, { layers: ['nt-prov-fill'] })[0];
        map.setFilter('nt-hover', ['==', ['get', 'code'], r ? String(r.properties?.code) : '']);
        map.setFilter('nt-prov-hover', ['==', ['get', 'code'], p ? String(p.properties?.code) : '']);
        map.getCanvas().style.cursor = r || p ? 'pointer' : '';
        if (!r && !p) { popup.current?.remove(); return; }
        const html = r ? regionTip(r.properties as Record<string, unknown>, current.metric) : provinceTip(current.data?.provinces.find((x) => x.code === String(p?.properties?.code)), current.metric, current.sido);
        popup.current?.setLngLat(e.lngLat).setHTML(html).addTo(map);
      });
      map.on('mouseout', () => { popup.current?.remove(); map.setFilter('nt-hover', ['==', ['get', 'code'], '']); map.setFilter('nt-prov-hover', ['==', ['get', 'code'], '']); });
      map.on('click', (e) => {
        const current = refs.current;
        const r = onRegion(e.point);
        if (r) { current.onSgg(String(r.properties?.code)); return; }
        const p = map.queryRenderedFeatures(e.point, { layers: ['nt-prov-fill'] })[0];
        if (p) { const code = String(p.properties?.code); if (code !== current.sido) current.onSido(code); else current.onSgg(null); }
      });
      map.on('idle', () => { const el = container.current; if (el && map.getLayer('nt-prov-fill')) el.dataset.renderedFeatures = String(map.queryRenderedFeatures({ layers: ['nt-prov-fill', 'nt-sgg-fill'] }).length); });
      setReady((n) => n + 1);
    });
    mapRef.current = map;
    return () => { popup.current?.remove(); markers.current.forEach((m) => m.remove()); markers.current = []; map.remove(); mapRef.current = null; };
  }, [offline, basemap]);

  // 시·도 면과 이름표
  useEffect(() => {
    const map = mapRef.current; if (!map || !ready || !map.getSource('nt-prov')) return;
    (map.getSource('nt-prov') as maplibregl.GeoJSONSource).setData(provFeatures);
    map.setPaintProperty('nt-prov-fill', 'fill-color', stepColor('v', provClasses) as unknown as maplibregl.ExpressionSpecification);
  }, [provFeatures, provClasses, ready]);
  useEffect(() => {
    const map = mapRef.current; if (!map || !ready) return;
    markers.current.forEach((m) => m.remove()); markers.current = [];
    if (sido || !data) return;
    for (const p of data.provinces) {
      if (!p.label) continue;
      const el = document.createElement('button');
      el.type = 'button'; el.className = `province-chip${p.kind === 'METRO' ? ' metro' : ''}`;
      const value = metricValue(p.metrics, metric.key);
      // 특별시·광역시는 작아서 이름만 (값은 메뉴와 툴팁에)
      el.innerHTML = `<b>${escapeHtml(shortProvince(p.name))}</b>${p.kind === 'METRO' ? '' : `<span>${value === null ? '—' : escapeHtml(formatMetric(value, '', metric.digits))}</span>`}`;
      el.title = `${p.name}: ${value === null ? '값 없음' : formatMetric(value, metric.unit, metric.digits)}`;
      el.setAttribute('aria-label', `${p.name} 고르기`);
      el.addEventListener('click', (ev) => { ev.stopPropagation(); refs.current.onSido(p.code); });
      markers.current.push(new maplibregl.Marker({ element: el }).setLngLat(p.label).addTo(map));
    }
  }, [data, sido, metric, ready]);
  // 고른 시·도: 다른 시·도는 옅게, 그 시·도는 시·군·구로 칠한다.
  useEffect(() => {
    const map = mapRef.current; if (!map || !ready || !map.getLayer('nt-prov-fill')) return;
    map.setPaintProperty('nt-prov-fill', 'fill-opacity', sido ? ['case', ['==', ['get', 'code'], sido], 0, 0.3] : 0.85);
    map.setFilter('nt-prov-selected', ['==', ['get', 'code'], sido ?? '']);
    (map.getSource('nt-sgg') as maplibregl.GeoJSONSource).setData(sido && sggData ? sggData.boundaries : EMPTY);
    map.setPaintProperty('nt-sgg-fill', 'fill-color', stepColor(metric.key, sggClasses) as unknown as maplibregl.ExpressionSpecification);
    map.setFilter('nt-sgg-missing', ['==', ['get', metric.key], null]);
    map.setFilter('nt-prov-missing', sido ? ['all', ['==', ['get', 'v'], null], ['!=', ['get', 'code'], sido]] : ['==', ['get', 'v'], null]);
    map.setPaintProperty('nt-prov-missing', 'fill-opacity', sido ? 0.3 : 0.9);
    map.setFilter('nt-sgg-selected', ['==', ['get', 'code'], sgg ?? '']); map.setFilter('nt-sgg-selected-halo', ['==', ['get', 'code'], sgg ?? '']);
  }, [sido, sgg, sggData, sggClasses, metric.key, ready]);
  // 화면 맞춤: 전국 ↔ 고른 시·도 (지표를 바꿔도 다시 맞추지 않는다)
  const target = useMemo(() => {
    if (!sido) return (data && bboxOf(data.boundaries.features)) ?? KOREA;
    return (data && bboxOf(data.boundaries.features.filter((f) => String(f.properties?.code) === sido))) ?? bboxOf(sggData?.boundaries.features ?? []);
  }, [data, sido, sggData]);
  const targetKey = target?.map((v) => v.toFixed(3)).join(',') ?? '';
  const targetRef = useRef(target); targetRef.current = target;
  useEffect(() => {
    const map = mapRef.current; if (!map || !ready) return;
    moved.current = false;
    map.resize();
    fit(map, targetRef.current);
  }, [targetKey, ready]);
  useEffect(() => {
    const map = mapRef.current; if (!map) return undefined;
    const onResize = () => { if (!moved.current) fit(map, targetRef.current); };
    map.on('resize', onResize);
    return () => { map.off('resize', onResize); };
  }, [ready]);

  const hasDetail = !!region;
  return <div className={`province-workspace national-workspace${hasDetail ? ' has-detail' : ''}`}>
    <nav className="province-menu" aria-label={sido ? '시·군·구 선택' : '시·도 선택'}>
      {!sido ? <>
        <header><MapPinned size={16} aria-hidden="true" /><strong>시·도 선택</strong><small className="menu-metric">{metric.label}</small></header>
        {national.loading && !data ? <p className="muted">불러오는 중…</p> : national.error ? <ErrorState message={national.error} onRetry={national.reload} /> : provinceGroups(data?.provinces ?? []).map(([kind, items]) => <div className="province-group" key={kind}>
          <span>{KIND_LABEL[kind]}</span>
          <ul>{items.map((p) => { const v = metricValue(p.metrics, metric.key); return <li key={p.code}><button type="button" onClick={() => onSido(p.code)}>
            <span>{p.name}</span>
            <small>{v === null ? '값 없음' : formatMetric(v, metric.unit, metric.digits)}{p.detailed ? ` · 상세 ${p.detailed}` : ''}</small>
          </button></li>; })}</ul>
        </div>)}
      </> : <>
        <header><button type="button" className="icon-link" aria-label="전국으로" onClick={() => onSido(null)}><ArrowLeft size={16} /></button><strong>{province?.name ?? sido}</strong></header>
        {province && <ProvinceSummaryBox province={province} metric={metric} onProvinceGrid={() => onProvinceGrid(province.code)} />}
        <p className="province-note first">시·군·구 {ranked.length}곳 · {metric.label} 순</p>
        <ul className="region-rank">{ranked.map((r) => { const v = metricValue(r.metrics, metric.key); return <li key={r.code}><button type="button" className={r.code === sgg ? 'active' : ''} aria-current={r.code === sgg ? 'true' : undefined} onClick={() => onSgg(r.code)}>
          <span><i className={`level-dot level-${r.level.toLowerCase()}`} aria-hidden="true" />{r.short_name}</span>
          <small>{v === null ? '값 없음' : formatMetric(v, metric.unit, metric.digits)}</small>
        </button></li>; })}</ul>
        <p className="province-note"><i className="level-dot level-detailed" aria-hidden="true" /> 상세 자료 <i className="level-dot level-basic" aria-hidden="true" /> 기본 지도 <i className="level-dot level-none" aria-hidden="true" /> 지도 없음</p>
      </>}
    </nav>
    <div className="map-stage">
      <div ref={container} className={`map-canvas${showBasemap ? '' : ' no-basemap'}`} aria-label={sido ? `${province?.name ?? ''} 시·군·구 지도` : '전국 시·도 지도'} data-testid="national-map" />
      {national.loading && !data && <div className="map-loading" role="status"><LoadingState label="전국 시·도 경계와 지표를 불러오는 중입니다. 처음에는 경계를 합치느라 수십 초 걸릴 수 있습니다" /></div>}
      {national.error && !national.loading && <div className="map-loading"><ErrorState message={national.error} onRetry={national.reload} /></div>}
      <div className="map-rail">
        <nav className="map-crumbs" aria-label="지도 위치">
          <button type="button" onClick={() => onSido(null)} aria-current={!sido ? 'page' : undefined}>전국</button>
          {province && <><span aria-hidden="true">›</span><button type="button" onClick={() => onSgg(null)} aria-current={sido && !sgg ? 'page' : undefined}>{province.name}</button></>}
          {region && <><span aria-hidden="true">›</span><strong aria-current="page">{region.short_name}</strong></>}
        </nav>
        {sido && regionsGeo?.code === sido && !regionsGeo.data && !regionsGeo.error && <div className="map-toast" role="status">{province?.name ?? ''} 시·군·구 경계를 불러오는 중…</div>}
        {regionsGeo?.error && <div className="map-toast" role="alert">{regionsGeo.error}</div>}
        {basemapFailed && !offline && basemap && <div className="map-toast" role="status">배경지도를 불러오지 못했습니다. 경계와 색은 그대로 보입니다.</div>}
        <div className="metric-picker">
          <button className="metric-trigger" aria-haspopup="listbox" aria-expanded={pickerOpen} onClick={() => setPickerOpen(!pickerOpen)}>
            <span><small>{sido ? '시·군·구 색 (지표 하나)' : '시·도 색 (지표 하나)'}</small><strong>{metric.label}</strong></span><em>{metric.unit}</em><ChevronDown size={16} aria-hidden="true" />
          </button>
          {pickerOpen && <section className="map-metrics map-popover" aria-label="지도 지표">
            <header><strong>전국 공통 지표</strong><small>모든 시·도·시·군·구에 있는 자료</small></header>
            {(['admin', 'grid500', 'complexes', 'ghg'] as const).map((source) => <div className="metric-group" key={source}><span>{SOURCE_GROUP[source]}</span>
              {NATIONAL_METRICS.filter((m) => m.source === source).map((m) => <button key={m.key} className={`metric-option${m.key === metric.key ? ' active' : ''}`} aria-pressed={m.key === metric.key} onClick={() => { setMetricKey(m.key); setPickerOpen(false); }}><span>{m.label} <small>{m.unit}</small></span></button>)}
            </div>)}
            <p className="muted">온실가스는 공식 지역 인벤토리 값입니다{data?.meta.ghg_year ? ` (${data.meta.ghg_year}년)` : ''}. 에너지 사용량(전력·가스 관측)은 전국 자료가 없어 시·군·구마다 모읍니다(상세 자료).</p>
          </section>}
        </div>
        <section className={`map-legend${legendOpen ? '' : ' collapsed'}`} aria-label="지표 범례">
          <div className="legend-head"><strong>{metric.label}</strong><span className="unit">{metric.unit}</span><button type="button" className="legend-toggle" aria-expanded={legendOpen} onClick={() => setLegendOpen((open) => !open)}>{legendOpen ? '범례 접기' : '범례 펼치기'}</button></div>
          <p className="resolution-tag res-1km">{sido ? `${province?.name ?? ''} 안 시·군·구끼리 나눈 구간` : '전국 시·도끼리 나눈 구간'}</p>
          {classes.classes.length ? <ul className="legend-classes">{classes.classes.map((c, i) => <li key={i}><i style={{ background: c.color }} /><span>{rangeLabel(c, metric.digits, i === classes.classes.length - 1)}</span><em>{c.count.toLocaleString('ko-KR')}곳</em></li>)}</ul> : <p className="map-empty-hint">{data ? '값이 있는 곳이 없습니다.' : '불러오면 표시합니다.'}</p>}
          {classes.missing > 0 && <div className="legend-missing"><i className="is-missing" /><span>{metric.source === 'grid500' ? '빠진 블록·통계 없음 (0 아님, 해치)' : '자료 없음 (0 아님, 해치)'}</span><em>{classes.missing}곳</em></div>}
          <ul className="layer-key" aria-label="선 기호">
            <li><i className="key-line" />시·도 경계</li>
            {sido && <li><i className="key-line prepared" />상세 자료 시·군·구 (에너지·건물·용도지역)</li>}
          </ul>
          <details className="legend-def"><summary>정의·출처·활용</summary><p>{metric.definition}</p><p className="legend-use"><b>활용</b> {metric.use}</p><p className="legend-source">출처: {data?.meta.sources[metric.source] ?? ''}</p>{metric.source === 'grid500' && <MissingBlocks data={data} />}</details>
        </section>
      </div>
      <div className="map-tools">
        <button className="tool-button" aria-expanded={layersOpen} onClick={() => setLayersOpen(!layersOpen)}><Layers3 size={16} aria-hidden="true" />레이어</button>
        {layersOpen && <section className="map-layers map-popover" aria-label="레이어">
          <LayerGroupTitle title="바탕" />
          <LayerToggle label="배경지도 (OpenStreetMap)" swatch="base" checked={basemap && !offline} disabled={!!offline} onChange={setBasemap} hint={offline ? '오프라인 모드: 외부 타일을 요청하지 않음' : basemapFailed ? '연결 실패. 도면지 바탕으로 표시' : undefined} />
        </section>}
      </div>
    </div>
    {region && <RegionDetail region={region} province={province} metric={metric} onClose={() => onSgg(null)} onOpen={() => onOpenRegion(region.code)} onProvinceGrid={() => province && onProvinceGrid(province.code)} />}
  </div>;
}

/** 500m 통계 파일이 없는 100km 블록과 그 블록에 사는 사람(1km 격자 기준): 다시 신청할 목록. */
function MissingBlocks({ data }: { data: NationalData | null }) {
  const blocks = (data?.meta.missing_blocks ?? []).filter((b) => b.people >= 1);
  if (!blocks.length && !data?.meta.gaps) return null;
  return <div className="missing-blocks">
    {blocks.length > 0 && <><p className="muted">500m 격자 통계 파일이 없는 블록 (다시 신청할 목록, 사는 사람은 2024 1km 격자 기준):</p>
      <ul>{blocks.slice(0, 12).map((b) => <li key={b.block}><b>{b.block}</b> 약 {formatMetric(b.people, '명')} · {b.provinces.map(shortProvince).join('·')}</li>)}</ul></>}
    {data?.meta.gaps && <p className="muted">받은 블록 중 빠진 주제: {data.meta.gaps}</p>}
  </div>;
}

function MetricFacts({ metrics, notes, excluded }: { metrics: NationalMetrics; notes: Record<string, string>; excluded?: string | null }) {
  return <dl className="fact-list">{NATIONAL_METRICS.map((m) => { const v = metricValue(metrics, m.key); return <div className={`fact${v === null ? ' missing' : ''}`} key={m.key}><dt>{m.label}</dt>
    <dd>{v === null ? <span className="muted">없음</span> : <>{formatMetric(v, '', m.digits)}<span className="unit">{m.unit}</span></>}</dd>
    {v === null && <span className="why">{missingReason(m, notes, excluded)}</span>}
    {m.key === 'pop_change_pct' && v !== null && metrics.pop500_base !== null && metrics.pop500 !== null && <span className="why">{formatMetric(metrics.pop500_base, '명')} → {formatMetric(metrics.pop500, '명')} (500m 격자 합)</span>}
    {v !== null && notes[m.key] && <span className="why">{notes[m.key]}</span>}
  </div>; })}</dl>;
}

/** 고른 시·도 요약 (왼쪽 메뉴 위): 지도 폭을 줄이지 않도록 오른쪽 상세 대신 여기에 둔다. */
const SOURCE_GROUP: Record<NationalMetric['source'], string> = {
  admin: '인구·가구 (SGIS 행정구역 통계)', grid500: '500m 격자 통계를 모은 값 (SGIS)', complexes: '공동주택 (K-apt 단지 목록)',
  ghg: '온실가스 (온실가스종합정보센터 지역 인벤토리)',
};

function ProvinceSummaryBox({ province, metric, onProvinceGrid }: { province: NationalProvince; metric: NationalMetric; onProvinceGrid: () => void }) {
  const keys: Array<NationalMetric['key']> = ['population', 'density', 'pop_change_pct', 'complexes'];
  if (!keys.includes(metric.key)) keys.push(metric.key);
  return <section className="menu-summary" aria-label={`${province.name} 요약`}>
    <dl>{keys.map((key) => { const m = NATIONAL_METRICS.find((x) => x.key === key) as NationalMetric; const v = metricValue(province.metrics, key);
      return <div key={key} title={v === null ? missingReason(m, province.notes, province.excluded) : province.notes[key] ?? undefined}><dt>{m.label}</dt><dd>{v === null ? <span className="muted">없음</span> : formatMetric(v, m.unit, m.digits)}</dd></div>; })}</dl>
    {metricValue(province.metrics, metric.key) === null && <p className="muted">{metric.label}: {missingReason(metric, province.notes, province.excluded)}</p>}
    {province.gas && <p className="muted" data-testid="province-gas">도시가스 판매량 {province.gas.year}년 {formatMetric(province.gas.thousand_m3 / 1000, '백만㎥', 0)}{province.gas.change_pct !== null ? ` (${province.gas.base_year}년 대비 ${province.gas.change_pct > 0 ? '+' : ''}${formatMetric(province.gas.change_pct, '%', 1)})` : ''}{province.gas.parts.length > 1 ? ` · ${province.gas.parts.join('·')} 합` : ''} · 한국가스공사</p>}
    <p className="muted">상세 자료 {province.detailed} · 기본 지도 {province.basic} · 에너지 관측 {province.energy_regions}곳</p>
    <button type="button" className="button secondary small" onClick={onProvinceGrid} disabled={!!province.excluded || !province.cells} title={province.excluded ?? undefined}>{province.excluded ? '500m 격자 지도 (제외)' : '500m 격자 지도로'}</button>
  </section>;
}

function RegionDetail({ region, province, metric, onClose, onOpen, onProvinceGrid }: { region: NationalRegion; province: NationalProvince | null; metric: NationalMetric; onClose: () => void; onOpen: () => void; onProvinceGrid: () => void }) {
  const energy = region.energy.kapt_complexes || region.energy.building_parcels;
  return <aside className="map-detail" aria-label={`${region.short_name} 요약`}>
    <header className="detail-head"><div><h2>{region.short_name}</h2><small className="muted">{province?.name ?? ''} · <span className={`level-tag level-${region.level.toLowerCase()}`}>{levelLabel(region.level)}</span></small></div>
      <button type="button" className="icon-link" aria-label="시·군·구 닫기" onClick={onClose}><X size={16} /></button></header>
    <section className="detail-section current-metric" aria-label="지도 지표 값">
      <h3>{metric.label}</h3>
      <p className="detail-figure">{metricValue(region.metrics, metric.key) === null ? <span className="muted">{missingReason(metric, region.notes)}</span> : <>{formatMetric(metricValue(region.metrics, metric.key), '', metric.digits)}<span className="unit">{metric.unit}</span></>}</p>
    </section>
    <section className="detail-section" aria-label="전국 공통 지표"><h3>전국 공통 지표</h3><MetricFacts metrics={region.metrics} notes={region.notes} /></section>
    <section className="detail-section" aria-label="에너지 관측">
      <h3>에너지 관측 (상세 자료)</h3>
      {energy ? <dl className="fact-list">
        <div className="fact"><dt>K-apt 월별 에너지</dt><dd>{region.energy.kapt_complexes ? formatMetric(region.energy.kapt_complexes, '단지') : <span className="muted">없음</span>}</dd></div>
        <div className="fact"><dt>건축HUB 건물 에너지</dt><dd>{region.energy.building_parcels ? formatMetric(region.energy.building_parcels, '지번') : <span className="muted">없음</span>}</dd></div>
      </dl> : <p className="muted">아직 모으지 않았습니다. 지도에서 '상세 자료 수집 시작'을 누르면 에너지·건물·용도지역을 모읍니다(지역 크기에 따라 몇 시간, 호출 한도가 있는 자료는 다음 날 이어서).</p>}
    </section>
    <section className="detail-section" aria-label="다음 단계">
      <h3>다음 단계</h3>
      {region.linked ? <>
        <button type="button" className="button primary" onClick={onOpen}>{region.short_name} 지도 열기 (읍면동 포함)</button>
        <p className="muted">{region.level === 'NONE' ? '처음 여는 곳은 전국 공통 자료로 500m 격자·읍면동 지도를 몇 초~1분 만에 만듭니다. ' : ''}여기서 고른 시·군·구가 대시보드·분석·시뮬레이션·보고서의 분석 지역이 됩니다.</p>
        <div className="detail-actions-row">
          {province && !province.excluded && <button type="button" className="button secondary small" onClick={onProvinceGrid}>{province.name} 500m 격자</button>}
          <Link className="button ghost small" to={`/regions?select=${region.code}`}>준비 단계·상세 자료 수집</Link>
        </div>
      </> : <p className="muted">SGIS 통계 단위이지만 법정 시·군·구(행정구역 코드)에 연결하지 못해 지도를 열 수 없습니다(2026년 행정구역 개편 등). 통계는 위 표로 봅니다.</p>}
    </section>
  </aside>;
}

function provinceTip(p: NationalProvince | undefined, metric: NationalMetric, selected: string | null): string {
  if (!p) return '';
  const v = metricValue(p.metrics, metric.key);
  return `<div class="map-tip"><strong>${escapeHtml(p.name)}</strong><span>${escapeHtml(metric.label)}</span><b>${v === null ? '값 없음' : escapeHtml(formatMetric(v, metric.unit, metric.digits))}</b><span>${p.code === selected ? '시·군·구를 누르세요' : '눌러서 시·군·구 보기'}</span></div>`;
}

function regionTip(p: Record<string, unknown>, metric: NationalMetric): string {
  const v = typeof p[metric.key] === 'number' ? (p[metric.key] as number) : null;
  return `<div class="map-tip"><strong>${escapeHtml(p.name)}</strong><span>${escapeHtml(levelLabel(String(p.level ?? '')))}</span><span>${escapeHtml(metric.label)}</span><b>${v === null ? '값 없음' : escapeHtml(formatMetric(v, metric.unit, metric.digits))}</b><span>눌러서 요약 보기</span></div>`;
}
