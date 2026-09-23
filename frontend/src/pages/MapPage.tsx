import * as maplibregl from 'maplibre-gl';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import { ChevronDown, Layers3, LocateFixed, RefreshCw, X } from 'lucide-react';
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { DataClassChip } from '../components/DataClassChip';
import { PageHeader } from '../components/PageHeader';
import { ErrorState, LoadingState } from '../components/Status';
import { useApi } from '../hooks/useApi';
import { useAnalysisScope } from '../hooks/useAnalysisScope';
import { api } from '../lib/api';
import { formatMetric, type DataClass } from '../lib/format';
import { classify, METRIC_GROUPS, METRICS, MISSING_COLOR, rangeLabel, stepColor, USE_COLORS, USE_NAME, withMetricValues, ZONE_NAME, type Classification, type MetricDef } from '../lib/mapMetrics';
import type { BuildingViewport, DashboardData, GridProps, MapData, OverlayData } from '../types';

maplibregl.setWorkerUrl(workerUrl);

export const ZONE_LEGEND: ReadonlyArray<readonly [string, string, string]> = [['RESIDENTIAL', '주거지역', '#f2c14e'], ['COMMERCIAL', '상업지역', '#e4572e'], ['INDUSTRIAL', '공업지역', '#8d6cab'], ['GREEN', '녹지지역', '#5aa469'], ['OTHER', '기타·미분류', '#b8c2c0']];
type LayerKey = 'grids' | 'buildings' | 'complexes' | 'boundary' | 'zoning' | 'admin';
const LAYER_IDS: Record<LayerKey, string[]> = { grids: ['grid-fill', 'grid-line'], buildings: ['buildings-fill', 'buildings-line'], complexes: ['complexes-circle'], boundary: ['boundary-line'], zoning: ['zoning-fill', 'zoning-line'], admin: ['admin-fill', 'admin-line'] };
const DEFAULT_VISIBLE: Record<LayerKey, boolean> = { grids: true, buildings: true, complexes: false, boundary: true, zoning: false, admin: false };
const BUILDING_MIN_ZOOM = 14;
const EMPTY: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features: [] };
const DEFAULT_METRIC_ORDER = ['far_est_pct', 'coverage_pct', 'residential_zone_ratio', 'complex_households', 'electricity_kwh_per_m2'];

export function MapPage() {
  const { year, gridId, query, setScope } = useAnalysisScope();
  const { data, loading, error, reload } = useApi<MapData>(`/map?year=${year}`);
  const details = useApi<DashboardData>(`/dashboard?${query}`);
  const overlays = useApi<OverlayData>(`/map/overlays?year=${year}`);
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const hoverPopup = useRef<maplibregl.Popup | null>(null);
  const [mapReady, setMapReady] = useState(0);
  const [offline, setOffline] = useState<boolean | null>(null);
  const [mapError, setMapError] = useState<string | null>(null);
  const [basemapEnabled, setBasemapEnabled] = useState(true);
  const [basemapFailed, setBasemapFailed] = useState(false);
  const [metricKey, setMetricKey] = useState<string | null>(null);
  const [visible, setVisible] = useState<Record<LayerKey, boolean>>(DEFAULT_VISIBLE);
  const [adminInfo, setAdminInfo] = useState<Record<string, unknown> | null>(null);
  const [viewport, setViewport] = useState<{ total: number; shown: number; truncated: boolean; needZoom: boolean; counts: Record<string, number> } | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [layersOpen, setLayersOpen] = useState(false);
  const [detailOpen, setDetailOpen] = useState(true);
  const visibleRef = useRef(visible); visibleRef.current = visible;

  const grids = useMemo(() => (data ? withMetricValues(data.grids) : null), [data]);
  const classifications = useMemo(() => {
    const result: Record<string, Classification> = {};
    if (!grids) return result;
    for (const metric of METRICS) result[metric.key] = classify(grids.features.map((f) => (f.properties as GridProps)[metric.key] as number | null), metric.breaks);
    return result;
  }, [grids]);
  const activeKey = metricKey ?? DEFAULT_METRIC_ORDER.find((key) => (classifications[key]?.valued ?? 0) >= 20) ?? METRICS.find((m) => classifications[m.key]?.valued)?.key ?? 'electricity_kwh_annual';
  const metric = METRICS.find((m) => m.key === activeKey) ?? METRICS[0];
  const classification = classifications[metric.key] ?? { classes: [], lowerBounds: [], valued: 0, missing: 0, min: null, max: null };
  const metricRef = useRef({ metric, classification }); metricRef.current = { metric, classification };
  const selectedId = gridId || String(data?.selected_sector?.grid_id || '');
  const selectedRef = useRef(selectedId); selectedRef.current = selectedId;
  const selected = grids?.features.find((f) => String((f.properties as GridProps).id) === selectedId)?.properties as GridProps | undefined;

  useEffect(() => { const update = () => { api<{ offline_mode: boolean }>('/system').then((s) => setOffline(s.offline_mode)).catch(() => setOffline(true)); }; update(); window.addEventListener('carbon-system-change', update); return () => window.removeEventListener('carbon-system-change', update); }, []);

  useEffect(() => {
    if (!container.current || !data || !grids || offline === null) return;
    setMapError(null); setBasemapFailed(false); setVisible(DEFAULT_VISIBLE); setAdminInfo(null); setViewport(null);
    const showBasemap = !offline && basemapEnabled;
    const map = new maplibregl.Map({
      container: container.current, center: data.center || [127.148, 35.824], zoom: 11.5, attributionControl: false,
      style: { version: 8, sources: showBasemap ? { basemap: { type: 'raster', tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'], tileSize: 256, attribution: '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap contributors</a>' } } : {}, layers: [{ id: 'background', type: 'background', paint: { 'background-color': '#e9eef3' } }, ...(showBasemap ? [{ id: 'basemap', type: 'raster' as const, source: 'basemap', paint: { 'raster-opacity': 0.55, 'raster-saturation': -0.6 } }] : [])] },
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'bottom-right');
    map.addControl(new maplibregl.AttributionControl({ compact: true, customAttribution: '지표: Carbon Urban DSS · 경계 SGIS · 용도지역·건물 VWorld · 단지 K-apt' }), 'bottom-left');
    map.on('error', (e) => { if (isBasemapError(e)) { setBasemapFailed(true); if (map.getLayer('basemap')) map.removeLayer('basemap'); if (map.getSource('basemap')) map.removeSource('basemap'); } else setMapError('지도 도형을 불러오지 못했습니다. 새로고침해 주세요.'); });
    map.on('load', () => {
      map.addSource('grids', { type: 'geojson', data: grids as GeoJSON.FeatureCollection, promoteId: 'id' });
      map.addSource('boundary', { type: 'geojson', data: data.boundary });
      map.addSource('buildings', { type: 'geojson', data: data.buildings_mode === 'viewport' ? EMPTY : data.buildings });
      map.addSource('complexes', { type: 'geojson', data: data.complexes ?? EMPTY });
      const { metric: m, classification: c } = metricRef.current;
      map.addLayer({ id: 'grid-fill', type: 'fill', source: 'grids', paint: { 'fill-color': stepColor(m.key, c) as unknown as maplibregl.ExpressionSpecification, 'fill-opacity': gridOpacity(m.key) } });
      map.addLayer({ id: 'grid-line', type: 'line', source: 'grids', paint: { 'line-color': '#ffffff', 'line-width': ['interpolate', ['linear'], ['zoom'], 11, 0.3, 15, 1.2], 'line-opacity': 0.75 } });
      map.addLayer({ id: 'boundary-line', type: 'line', source: 'boundary', paint: { 'line-color': '#0a6c5f', 'line-width': 2.2, 'line-opacity': 0.9 } });
      map.addLayer({ id: 'buildings-fill', type: 'fill', source: 'buildings', minzoom: data.buildings_mode === 'viewport' ? BUILDING_MIN_ZOOM - 0.5 : 0, paint: { 'fill-color': useColor() as unknown as maplibregl.ExpressionSpecification, 'fill-opacity': 0.85 } });
      map.addLayer({ id: 'buildings-line', type: 'line', source: 'buildings', minzoom: 15, paint: { 'line-color': 'rgba(14,26,43,.35)', 'line-width': 0.5 } });
      map.addLayer({ id: 'complexes-circle', type: 'circle', source: 'complexes', layout: { visibility: 'none' }, paint: { 'circle-radius': ['interpolate', ['linear'], ['zoom'], 11, ['max', 2, ['/', ['sqrt', ['coalesce', ['get', 'households'], 1]], 6]], 16, ['max', 4, ['/', ['sqrt', ['coalesce', ['get', 'households'], 1]], 2.2]]], 'circle-color': '#0d8a78', 'circle-opacity': 0.75, 'circle-stroke-color': '#ffffff', 'circle-stroke-width': 1.5 } });
      map.addLayer({ id: 'hover-grid', type: 'line', source: 'grids', filter: selectedFilter(''), paint: { 'line-color': '#0e1a2b', 'line-width': 2 } });
      map.addLayer({ id: 'selected-grid', type: 'line', source: 'grids', filter: selectedFilter(selectedRef.current), paint: { 'line-color': '#f97316', 'line-width': 4, 'line-blur': 0.4 } });
      fitToData(map, data.boundary?.features?.length ? data.boundary : (grids as GeoJSON.FeatureCollection));
      hoverPopup.current = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 12, maxWidth: '280px' });
      map.on('mousemove', 'grid-fill', (e) => {
        const props = e.features?.[0]?.properties as unknown as GridProps | undefined; if (!props) return;
        map.getCanvas().style.cursor = 'pointer';
        map.setFilter('hover-grid', selectedFilter(props.id));
        hoverPopup.current?.setLngLat(e.lngLat).setHTML(gridTooltip(props, metricRef.current.metric, metricRef.current.classification)).addTo(map);
      });
      map.on('mouseleave', 'grid-fill', () => { map.getCanvas().style.cursor = ''; map.setFilter('hover-grid', selectedFilter('')); hoverPopup.current?.remove(); });
      map.on('click', 'grid-fill', (e) => { const id = e.features?.[0]?.properties?.id; if (id) { setScope({ gridId: String(id) }); setDetailOpen(true); } });
      for (const layer of ['buildings-fill', 'complexes-circle']) {
        map.on('mouseenter', layer, () => { map.getCanvas().style.cursor = 'pointer'; });
        map.on('mouseleave', layer, () => { map.getCanvas().style.cursor = ''; });
      }
      map.on('click', 'buildings-fill', (e) => { const p = e.features?.[0]?.properties; if (p) new maplibregl.Popup({ offset: 8, maxWidth: '280px' }).setLngLat(e.lngLat).setHTML(buildingTooltip(p)).addTo(map); });
      map.on('click', 'complexes-circle', (e) => { const p = e.features?.[0]?.properties; if (p) new maplibregl.Popup({ offset: 8, maxWidth: '300px' }).setLngLat(e.lngLat).setHTML(complexTooltip(p)).addTo(map); });
      applyVisibility(map, visibleRef.current);
      setMapReady((n) => n + 1);
    });
    map.on('idle', () => {
      const el = container.current; if (!el) return;
      if (map.getLayer('grid-fill')) el.dataset.renderedFeatures = String(map.queryRenderedFeatures({ layers: ['grid-fill'] }).length);
      for (const [key, id] of [['renderedZoning', 'zoning-fill'], ['renderedAdmin', 'admin-fill'], ['renderedBuildings', 'buildings-fill']] as const) el.dataset[key] = map.getLayer(id) && map.getLayoutProperty(id, 'visibility') !== 'none' ? String(map.queryRenderedFeatures({ layers: [id] }).length) : '0';
    });
    mapRef.current = map;
    return () => { hoverPopup.current?.remove(); map.remove(); mapRef.current = null; };
  }, [data, grids, offline, basemapEnabled, setScope]);

  useEffect(() => { const m = mapRef.current; if (m?.getLayer('selected-grid')) m.setFilter('selected-grid', selectedFilter(selectedId)); }, [selectedId, mapReady]);
  useEffect(() => {
    const m = mapRef.current; if (!m?.getLayer('grid-fill')) return;
    m.setPaintProperty('grid-fill', 'fill-color', stepColor(metric.key, classification) as unknown as maplibregl.ExpressionSpecification);
    m.setPaintProperty('grid-fill', 'fill-opacity', gridOpacity(metric.key));
  }, [metric.key, classification, mapReady]);
  useEffect(() => { const m = mapRef.current; if (m?.getLayer('grid-fill')) applyVisibility(m, visible); }, [visible, mapReady]);
  useEffect(() => {
    const m = mapRef.current; const o = overlays.data; if (!m || !mapReady || !o) return;
    if (addOverlayLayers(m, o)) {
      m.on('click', 'admin-fill', (e) => setAdminInfo((e.features?.[0]?.properties as Record<string, unknown> | undefined) ?? null));
      for (const id of ['admin-fill', 'zoning-fill']) { m.on('mouseenter', id, () => { m.getCanvas().style.cursor = 'pointer'; }); m.on('mouseleave', id, () => { m.getCanvas().style.cursor = ''; }); }
    }
    applyVisibility(m, visibleRef.current);
  }, [overlays.data, mapReady]);

  // Official buildings are served per viewport (tens of thousands of footprints city-wide).
  useEffect(() => {
    const m = mapRef.current; if (!m || !mapReady || data?.buildings_mode !== 'viewport') return;
    let controller: AbortController | null = null; let timer = 0;
    const load = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        const source = m.getSource('buildings') as maplibregl.GeoJSONSource | undefined; if (!source) return;
        if (!visibleRef.current.buildings || m.getZoom() < BUILDING_MIN_ZOOM) { source.setData(EMPTY); setViewport((old) => ({ total: old?.total ?? 0, shown: 0, truncated: false, needZoom: true, counts: {} })); return; }
        const b = m.getBounds(); controller?.abort(); controller = new AbortController();
        api<BuildingViewport>(`/map/buildings?bbox=${[b.getWest(), b.getSouth(), b.getEast(), b.getNorth()].map((v) => v.toFixed(5)).join(',')}`, { signal: controller.signal })
          .then((fc) => { source.setData(fc); const counts: Record<string, number> = {}; for (const f of fc.features) { const k = String(f.properties?.use_category ?? 'UNKNOWN'); counts[k] = (counts[k] ?? 0) + 1; } setViewport({ total: fc.total, shown: fc.features.length, truncated: fc.truncated, needZoom: false, counts }); })
          .catch(() => undefined);
      }, 250);
    };
    load(); m.on('moveend', load);
    return () => { m.off('moveend', load); window.clearTimeout(timer); controller?.abort(); };
  }, [mapReady, data?.buildings_mode, visible.buildings]);

  if (loading) return <div className="page"><LoadingState label="공간 레이어를 불러오는 중입니다" /></div>;
  if (error || !data || !grids) return <div className="page"><ErrorState message={error} onRetry={reload} /></div>;
  const overlayMeta = overlays.data?.meta; const adminMax = maxOf(overlays.data?.admin, 'population_density');
  const focus = () => { const f = grids.features.find((x) => String((x.properties as GridProps).id) === selectedId); if (mapRef.current && f) fitToData(mapRef.current, { type: 'FeatureCollection', features: [f] }, 16); };
  const total = grids.features.length;
  const zoningTotal = Object.values(overlayMeta?.zoning_area_km2_by_category ?? {}).reduce((a, b) => a + b, 0);
  return <div className="page map-page">
    <PageHeader eyebrow="SPATIAL EXPLORER" title="도시 탄소 지도" description={`500m 분석 격자 ${total.toLocaleString('ko-KR')}개(격자당 250,000m²) · 격자를 누르면 모든 분석 화면의 대상지가 바뀝니다.`} action={<button className="button secondary" onClick={reload}><RefreshCw size={15} />새로고침</button>} />
    <div className={`map-workspace${selected && detailOpen ? ' has-detail' : ''}`}>
      <div ref={container} className="map-canvas" aria-label="전주시 탄소 공간 지도" />
      <div className="map-rail">
        <div className="metric-picker">
          <button className="metric-trigger floating-panel" aria-haspopup="listbox" aria-expanded={pickerOpen} onClick={() => setPickerOpen(!pickerOpen)}>
            <span><small>지도 지표</small><strong>{metric.label}</strong></span><em>{metric.unit}</em><ChevronDown size={17} />
          </button>
          {pickerOpen && <section className="map-metrics floating-panel" aria-label="지도 지표">
            <header><strong>지표 선택</strong><small>값 있는 격자 / 전체 {total}</small></header>
            {METRIC_GROUPS.map((group) => <div className="metric-group" key={group}><span>{group}</span>{METRICS.filter((m) => m.group === group).map((m) => { const valued = classifications[m.key]?.valued ?? 0; return <button key={m.key} className={`metric-option${m.key === metric.key ? ' active' : ''}${valued ? '' : ' empty'}`} aria-pressed={m.key === metric.key} onClick={() => { setMetricKey(m.key); setPickerOpen(false); }}><span>{m.label} <small>{m.unit}</small></span><em>{valued ? `${valued}/${total}` : '자료 없음'}</em></button>; })}</div>)}
          </section>}
        </div>
        <section className="map-legend floating-panel" aria-label="지표 범례">
          <div className="legend-head"><div><strong>{metric.label}</strong><small>{metric.unit}</small></div><DataClassChip value={classification.valued ? metric.dataClass : 'MISSING'} /></div>
          <p className="legend-def">{metric.definition}<br /><code>{metric.formula}</code></p>
          {classification.classes.length ? <ul className="legend-classes">{classification.classes.map((c, i) => <li key={i}><i style={{ background: c.color }} /><span>{rangeLabel(c, metric.digits, i === classification.classes.length - 1)}</span><em>{c.count}격자</em></li>)}<li className="missing"><i /><span>자료 없음 (0 아님)</span><em>{classification.missing}격자</em></li></ul> : <p className="map-empty-hint">이 지표는 아직 계산할 관측 자료가 없습니다. 모든 격자를 결측(회색)으로 표시합니다.</p>}
          <div className="legend-coverage"><div><span>값 있는 격자</span><b>{classification.valued}/{total} ({formatMetric(classification.valued / Math.max(total, 1) * 100, '%', 1)})</b></div><div className="ratio-track"><span style={{ width: `${classification.valued / Math.max(total, 1) * 100}%` }} /></div></div>
          <p className="legend-source"><span className="legend-selected-inline">□ 주황 테두리 = 선택 격자</span> · 출처: {metric.source}</p>
          {visible.zoning && <div className="overlay-legend" aria-label="용도지역 범례"><hr /><strong>용도지역</strong>{ZONE_LEGEND.map(([key, label, color]) => { const km2 = overlayMeta?.zoning_area_km2_by_category?.[key]; return <span key={key}><i style={{ background: color }} />{label}{km2 !== undefined && <b>{km2.toFixed(1)}km² · {formatMetric(zoningTotal ? km2 / zoningTotal * 100 : null, '%', 1)}</b>}</span>; })}<small>VWorld LT_C_UQ111 · {overlayMeta?.zoning_features ?? 0}개 도형 · 분석 격자 내 면적</small></div>}
          {visible.admin && <div className="overlay-legend" aria-label="행정동 인구 범례"><hr /><strong>행정동 인구밀도</strong><div className="legend-ramp admin" /><div className="legend-range"><span>0</span><span>{formatMetric(adminMax, '명/km²', 0)}</span></div><small>SGIS {overlayMeta?.admin_reference_year ?? ''} 행정통계 · 공식 행정동 경계 · 격자로 배분하지 않음</small>{adminInfo && <dl className="admin-info"><div><dt>행정동</dt><dd>{String(adminInfo.adm_name ?? '—')}</dd></div><div><dt>인구</dt><dd>{statValue(adminInfo.population, adminInfo.population_status, '명')}</dd></div><div><dt>가구</dt><dd>{statValue(adminInfo.households, adminInfo.household_status, '가구')}</dd></div><div><dt>인구밀도</dt><dd>{typeof adminInfo.population_density === 'number' ? formatMetric(adminInfo.population_density, '명/km²', 0) : '자료 없음'}</dd></div></dl>}</div>}
          {visible.buildings && <div className="overlay-legend" aria-label="건물 용도 범례"><hr /><strong>건물 용도</strong><div className="use-legend">{USE_COLORS.map(([key, color]) => <span key={key}><i style={{ background: color }} />{USE_NAME[key]}{viewport && !viewport.needZoom && <b>{(viewport.counts[key] ?? 0).toLocaleString('ko-KR')}</b>}</span>)}</div><small>{data.buildings_source}{data.buildings_mode === 'viewport' ? ` · 확대 ${BUILDING_MIN_ZOOM} 이상에서 표시` : ''}</small></div>}
        </section>
      </div>
      <div className="map-tools">
        <button className="tool-button floating-panel" aria-expanded={layersOpen} onClick={() => setLayersOpen(!layersOpen)}><Layers3 size={16} />레이어<b>{Object.values(visible).filter(Boolean).length}</b></button>
        {layersOpen && <section className="map-layers floating-panel" aria-label="레이어">
          <LayerToggle label="분석 격자 (500m)" checked={visible.grids} onChange={(v) => setVisible({ ...visible, grids: v })} />
          <LayerToggle label={data.buildings_mode === 'viewport' ? '건물 (도로명주소 건물)' : '건물 (OSM 공동주택, 대체)'} checked={visible.buildings} onChange={(v) => setVisible({ ...visible, buildings: v })} hint={data.buildings_mode === 'viewport' ? `확대 ${BUILDING_MIN_ZOOM} 이상에서 표시` : '공식 건물 수집 전 대체 자료'} />
          <LayerToggle label={`공동주택 단지 (K-apt ${data.complexes?.features.length ?? 0})`} checked={visible.complexes} onChange={(v) => setVisible({ ...visible, complexes: v })} hint="원 크기 = 세대수" />
          <LayerToggle label="전주시 경계" checked={visible.boundary} onChange={(v) => setVisible({ ...visible, boundary: v })} hint={data.boundary_source} />
          {([['zoning', '용도지역 (VWorld)', overlayMeta?.zoning_features ?? 0], ['admin', '행정동 인구 (SGIS)', overlayMeta?.admin_features ?? 0]] as const).map(([key, label, count]) => <LayerToggle key={key} label={label} checked={visible[key]} disabled={!count} onChange={(v) => setVisible({ ...visible, [key]: v })} badge={!count ? (overlays.loading ? '확인 중' : '미수집') : undefined} />)}
          <hr />
          <LayerToggle label="배경지도 (OpenStreetMap)" checked={basemapEnabled && !offline} disabled={!!offline} onChange={(v) => setBasemapEnabled(v)} hint={offline ? '오프라인 모드: 외부 타일을 요청하지 않음' : basemapFailed ? '연결 실패 · 분석 도형은 그대로 이용 가능' : undefined} />
        </section>}
      </div>
      {data.buildings_mode === 'viewport' && visible.buildings && viewport && <div className="building-count" role="status">{viewport.needZoom ? `건물은 확대(${BUILDING_MIN_ZOOM} 이상)하면 표시됩니다` : `화면 안 건물 ${viewport.total.toLocaleString('ko-KR')}동${viewport.truncated ? ` 중 큰 건물 ${viewport.shown.toLocaleString('ko-KR')}동 표시` : ''}`}</div>}
      {basemapFailed && !offline && basemapEnabled && <div className="map-toast" role="status">배경지도를 불러오지 못했습니다 · 분석 도형은 정상 표시</div>}
      {selected && (detailOpen ? <GridDetail props={selected} name={String(data.selected_sector?.grid_id) === selectedId ? data.selected_sector?.name : undefined} metric={metric} classification={classification} details={details.data} detailsLoading={details.loading} onFocus={focus} onClose={() => setDetailOpen(false)} /> : <button className="detail-tab floating-panel" onClick={() => setDetailOpen(true)}>격자 상세 <code>{selected.id}</code></button>)}
      {mapError && <p role="alert" className="map-error">{mapError}</p>}
    </div>
  </div>;
}

function LayerToggle({ label, checked, onChange, disabled, hint, badge }: { label: string; checked: boolean; onChange: (value: boolean) => void; disabled?: boolean; hint?: string; badge?: string }) {
  return <label className="layer-toggle" title={badge ? '아직 수집되지 않았습니다' : hint}><input type="checkbox" checked={checked && !disabled} disabled={disabled} onChange={(e) => onChange(e.target.checked)} /><span>{label}{hint && <small>{hint}</small>}</span>{badge && <small className="overlay-empty">{badge}</small>}</label>;
}

function GridDetail({ props: p, name, metric, classification, details, detailsLoading, onFocus, onClose }: { props: GridProps; name?: string; metric: MetricDef; classification: Classification; details: DashboardData | null; detailsLoading: boolean; onFocus: () => void; onClose: () => void }) {
  const value = p[metric.key] as number | null;
  const cls = value === null ? null : classification.classes.find((c, i) => i === classification.classes.length - 1 ? value >= c.from : value >= c.from && value < c.to);
  const detailMatches = details?.selected_sector && String(details.selected_sector.grid_id) === p.id;
  const months = detailMatches ? details?.monthly ?? [] : [];
  const buildingClass: DataClass = p.building_source === 'OSM' ? 'FALLBACK' : 'OBSERVED';
  return <aside className="map-detail floating-panel" aria-label="선택 격자 상세">
    <div className="panel-title"><div><span>SELECTED GRID</span><h3>{name || '선택 격자'}</h3><code className="grid-id">{p.id}</code></div><div className="detail-actions"><button className="icon-link" aria-label="선택 격자로 확대" onClick={onFocus}><LocateFixed size={18} /></button><button className="icon-link subtle" aria-label="상세 닫기" onClick={onClose}><X size={18} /></button></div></div>
    <div className="detail-section"><header><h4>{metric.label}</h4><DataClassChip value={value === null ? 'MISSING' : metric.dataClass} /></header>
      <dl className="fact-list"><Fact label={cls ? <span className="tip-class"><i style={{ background: cls.color, display: 'inline-block', width: 10, height: 10, borderRadius: 3, marginRight: 6 }} />{metric.unit}</span> : metric.unit} value={value} unit="" digits={metric.digits} why={value === null ? '이 격자에는 이 지표를 계산할 관측 자료가 없습니다.' : metric.basis(p) ?? undefined} /></dl>
    </div>
    <div className="detail-section"><header><h4>에너지 관측 ({months.length ? `${String(months[0]?.use_ym).slice(0, 4)}년` : '연간'})</h4><DataClassChip value={p.electricity_months || p.gas_months ? 'OBSERVED' : 'MISSING'} /></header>
      <dl className="fact-list">
        <Fact label="전력 (12개월 관측 지번)" value={p.electricity_kwh_annual as number | null} unit="kWh" why={p.electricity_complete_parcels ? `지번 ${p.electricity_complete_parcels}곳` : p.electricity_months ? `관측 ${p.electricity_months}/12개월 — 12개월이 모두 있는 지번이 없어 연간값을 만들지 않음` : '관측 없음'} />
        <Fact label="가스 (12개월 관측 지번)" value={p.gas_kwh_annual as number | null} unit="kWh" why={p.gas_complete_parcels ? `지번 ${p.gas_complete_parcels}곳 · 건축HUB kWh 환산` : '관측 없음'} />
      </dl>
      {months.length > 0 && <div style={{ marginTop: 10 }}><MonthRow label="전력" months={months.map((r) => r.electricity_kwh !== null)} /><MonthRow label="가스" months={months.map((r) => r.gas_kwh !== null)} /></div>}
      {!months.length && detailsLoading && <p className="muted">월별 관측 확인 중…</p>}
    </div>
    <div className="detail-section"><header><h4>원단위 · 탄소</h4><DataClassChip value={p.electricity_kwh_per_m2 !== null ? 'CALCULATED' : 'MISSING'} /></header>
      <dl className="fact-list">
        <Fact label="전력 원단위" value={p.electricity_kwh_per_m2} unit="kWh/m²·년" digits={1} why={p.electricity_area_m2 ? `연면적 ${formatMetric(p.electricity_area_m2, 'm²')} (${p.electricity_area_parcels}곳)` : undefined} />
        <Fact label="세대당 전력" value={p.electricity_kwh_per_household} unit="kWh/세대·년" why={p.electricity_households ? `${formatMetric(p.electricity_households, '세대')} · 월 ${formatMetric((p.electricity_kwh_per_household ?? 0) / 12, 'kWh')}` : undefined} />
        <Fact label="가스 원단위" value={p.gas_kwh_per_m2} unit="kWh/m²·년" digits={1} />
        <Fact label="전력 탄소" value={p.electricity_carbon_t as number | null} unit="tCO₂eq/년" digits={1} why={p.electricity_carbon_t !== null ? '전력 × 0.4541 kgCO₂eq/kWh (GIR 2024)' : undefined} />
        <Fact label="가스 탄소" value={null} unit="" missingText="계수 확정 전 (0 아님)" />
      </dl>
    </div>
    <div className="detail-section"><header><h4>도시 형태</h4><DataClassChip value={p.building_count === null ? 'MISSING' : buildingClass} /></header>
      <dl className="fact-list">
        <Fact label="건물 수" value={p.building_count} unit="동" why={p.building_source === 'OSM' ? 'OSM 공동주택 윤곽만 (전체 건물 아님)' : p.building_count !== null ? `밀도 ${formatMetric(p.building_density, '동/km²')}` : '건물 레이어 미수집'} />
        <Fact label="건폐율 근사" value={p.coverage_pct} unit="%" digits={1} why={p.footprint_m2 !== null ? `건축면적 ${formatMetric(p.footprint_m2, 'm²')} ÷ 250,000 m²` : undefined} />
        <Fact label="추정 용적률" value={p.far_est_pct} unit="%" digits={1} why={p.floor_area_est_m2 !== null ? `Σ건축면적×층수 ${formatMetric(p.floor_area_est_m2, 'm²')} ÷ 250,000 m² · 층수 확인 ${formatMetric(p.floors_known_pct, '%')}` : undefined} />
        <Fact label="평균 지상층수" value={p.avg_floors} unit="층" digits={1} why={p.max_floors ? `최고 ${p.max_floors}층` : undefined} />
      </dl>
      {p.use_share_pct && Object.keys(p.use_share_pct).length > 0 && <ShareBar title="건축면적 기준 용도 구성" shares={p.use_share_pct} colors={Object.fromEntries(USE_COLORS)} names={USE_NAME} />}
    </div>
    <div className="detail-section"><header><h4>토지이용 (용도지역)</h4><DataClassChip value={p.zone_shares ? 'CALCULATED' : 'MISSING'} /></header>
      {p.zone_shares && Object.keys(p.zone_shares).length ? <ShareBar title="격자 면적 중 용도지역 비율" shares={p.zone_shares} colors={Object.fromEntries(ZONE_LEGEND.map(([k, , c]) => [k, c]))} names={ZONE_NAME} rest="도시지역 외·미지정" /> : <p className="map-empty-hint">{p.zoning_status ? '조회했으나 이 격자에 도시지역 용도지역 도형이 없습니다.' : '용도지역 미수집 격자입니다.'}</p>}
    </div>
    <div className="detail-section"><header><h4>공동주택 (K-apt)</h4><DataClassChip value={p.complex_count ? 'OBSERVED' : 'MISSING'} /></header>
      <dl className="fact-list">
        <Fact label="단지 · 세대" value={p.complex_count ? p.complex_households : null} unit="세대" missingText="격자 안 단지 없음" why={p.complex_count ? `단지 ${p.complex_count}개` : undefined} />
        <Fact label="연면적 합 (공표값)" value={p.complex_gfa_m2} unit="m²" why={p.complex_gfa_excluded ? `연면적 이상값 ${p.complex_gfa_excluded}개 단지 제외` : undefined} />
      </dl>
    </div>
    <div className="grid-actions"><Link className="button primary" to="/simulation">이 격자 시뮬레이션</Link><Link className="button secondary" to="/reports">보고서 작성</Link></div>
  </aside>;
}

function Fact({ label, value, unit, digits = 0, why, missingText = '자료 없음' }: { label: ReactNode; value: number | null | undefined; unit: string; digits?: number; why?: string; missingText?: string }) {
  const missing = value === null || value === undefined || !Number.isFinite(value);
  return <div className={`fact${missing ? ' missing' : ''}`}><dt>{label}</dt><dd>{missing ? missingText : <>{formatMetric(value, '', digits)}{unit && <small>{unit}</small>}</>}</dd>{why && <span className="why">{why}</span>}</div>;
}

function MonthRow({ label, months }: { label: string; months: boolean[] }) {
  const count = months.filter(Boolean).length;
  return <div className="month-strip-row"><span>{label}</span><div className="month-strip" aria-label={`${label} 관측 ${count}/12개월`}>{months.map((on, i) => <span key={i} className={on ? 'on' : ''} title={`${i + 1}월 ${on ? '관측' : '미관측'}`}>{i + 1}</span>)}</div><b>{count}/12</b></div>;
}

function ShareBar({ title, shares, colors, names, rest }: { title: string; shares: Record<string, number>; colors: Record<string, string>; names: Record<string, string>; rest?: string }) {
  const entries = Object.entries(shares).sort((a, b) => b[1] - a[1]);
  const total = entries.reduce((sum, [, v]) => sum + v, 0);
  const remainder = rest ? Math.max(0, 100 - total) : 0;
  return <div style={{ marginTop: 10 }}><p className="muted" style={{ margin: '0 0 6px' }}>{title}</p><div className="stack-bar" role="img" aria-label={entries.map(([k, v]) => `${names[k] ?? k} ${v.toFixed(1)}%`).join(', ')}>{entries.map(([k, v]) => <span key={k} style={{ width: `${v}%`, background: colors[k] ?? MISSING_COLOR }} />)}{remainder > 0.05 && <span style={{ width: `${remainder}%`, background: 'rgba(14,26,43,.08)' }} />}</div><div className="stack-legend">{entries.map(([k, v]) => <span key={k}><i style={{ background: colors[k] ?? MISSING_COLOR }} />{names[k] ?? k} <b>{v.toFixed(1)}%</b></span>)}{remainder > 0.05 && <span><i style={{ background: 'rgba(14,26,43,.12)' }} />{rest} <b>{remainder.toFixed(1)}%</b></span>}</div></div>;
}

function escapeHtml(value: unknown): string { return String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] ?? c); }

function gridTooltip(p: GridProps, metric: MetricDef, classification: Classification): string {
  const raw = p[metric.key]; const value = typeof raw === 'number' ? raw : null;
  const cls = value === null ? null : classification.classes.find((c, i) => (i === classification.classes.length - 1 ? value >= c.from : value >= c.from && value < c.to));
  const extra = [p.residential_zone_ratio !== null ? `주거지역 ${formatMetric(p.residential_zone_ratio, '%', 1)}` : null, p.building_count !== null ? `건물 ${formatMetric(p.building_count, '동')}` : null, p.complex_count ? `공동주택 ${p.complex_count}단지` : null].filter(Boolean).join(' · ');
  return `<div class="map-tip"><strong>${escapeHtml(p.id)}</strong><span>${escapeHtml(metric.label)}</span><b class="tip-class">${cls ? `<i style="background:${cls.color}"></i>` : ''}${value === null ? '자료 없음' : `${escapeHtml(formatMetric(value, '', metric.digits))} ${escapeHtml(metric.unit)}`}</b>${extra ? `<span>${escapeHtml(extra)}</span>` : ''}<span>클릭하면 이 격자를 선택합니다</span></div>`;
}

function buildingTooltip(p: Record<string, unknown>): string {
  const floors = [p.above_floors ? `지상 ${p.above_floors}층` : '지상층수 미상', p.below_floors ? `지하 ${p.below_floors}층` : null].filter(Boolean).join(' · ');
  return `<div class="map-tip"><strong>${escapeHtml(p.name || '이름 없는 건물')}</strong><span>${escapeHtml(p.use_label || p.use_category_label || '용도 미상')}</span><b>${escapeHtml(floors)}</b><span>건축면적 ${escapeHtml(formatMetric(typeof p.footprint_m2 === 'number' ? p.footprint_m2 : null, 'm²', 0))}</span></div>`;
}

function complexTooltip(p: Record<string, unknown>): string {
  const area = typeof p.gross_floor_area_m2 === 'number' ? p.gross_floor_area_m2 : null;
  return `<div class="map-tip"><strong>${escapeHtml(p.name)}</strong><span>K-apt ${escapeHtml(p.kapt_code)}</span><b>${escapeHtml(formatMetric(typeof p.households === 'number' ? p.households : null, '세대'))}</b><span>연면적 ${escapeHtml(formatMetric(area, 'm²'))}${p.floor_area_status !== 'OK' ? ` · <em>${escapeHtml(p.floor_area_issue || '연면적 확인 필요')}</em>` : ''}</span><span>사용승인 ${escapeHtml(p.approval_date || '자료 없음')} · ${escapeHtml(p.heating_type || '난방방식 자료 없음')}</span></div>`;
}

/** Grid fill fades as buildings appear on zoom; missing grids stay lighter than valued ones. */
function gridOpacity(key: string): maplibregl.ExpressionSpecification { return ['interpolate', ['linear'], ['zoom'], 11, ['case', ['==', ['get', key], null], 0.28, 0.66], 14, ['case', ['==', ['get', key], null], 0.18, 0.42], 16, ['case', ['==', ['get', key], null], 0.08, 0.2]]; }

function useColor(): unknown[] { return ['match', ['coalesce', ['get', 'use_category'], 'RESIDENTIAL'], ...USE_COLORS.slice(0, 5).flatMap(([key, color]) => [key, color]), USE_COLORS[5][1]]; }

export function isBasemapError(event: { sourceId?: string; error?: { message?: string } }) { return event.sourceId === 'basemap' || !!event.error?.message?.includes('tile.openstreetmap.org'); }
export function selectedFilter(id: string | number | undefined): maplibregl.FilterSpecification { return ['==', ['to-string', ['coalesce', ['get', 'grid_id'], ['get', 'id']]], String(id ?? '')]; }
/** Equal-interval color for a metric up to ``max`` (kept for callers without a classification). */
export function metricColor(metric: string, max = 50000): maplibregl.ExpressionSpecification { return ['case', ['==', ['get', metric], null], MISSING_COLOR, ['interpolate', ['linear'], ['to-number', ['get', metric]], 0, '#b7d3f6', Math.max(max, 1) / 2, '#2a78d6', Math.max(max, 1), '#184f95']]; }
function fitToData(map: maplibregl.Map, collection: GeoJSON.FeatureCollection, maxZoom = 13) { const bounds = new maplibregl.LngLatBounds(); const visit = (v: unknown) => { if (Array.isArray(v) && typeof v[0] === 'number' && typeof v[1] === 'number') bounds.extend(v as [number, number]); else if (Array.isArray(v)) v.forEach(visit); }; collection.features.forEach((f) => visit((f.geometry as { coordinates: unknown }).coordinates)); if (!bounds.isEmpty()) map.fitBounds(bounds, { padding: { top: 60, bottom: 30, left: 330, right: map.getContainer().clientWidth > 1100 ? 400 : 40 }, maxZoom, duration: 0 }); }
export function zoneColor(): maplibregl.ExpressionSpecification { return ['match', ['get', 'category'], ...ZONE_LEGEND.slice(0, 4).flatMap(([key, , color]) => [key, color]), ZONE_LEGEND[4][2]] as unknown as maplibregl.ExpressionSpecification; }
export function densityColor(max: number): maplibregl.ExpressionSpecification { return ['case', ['==', ['get', 'population_density'], null], '#d7d3de', ['interpolate', ['linear'], ['to-number', ['get', 'population_density']], 0, '#f3eefb', Math.max(max, 1) / 2, '#9b7fd0', Math.max(max, 1), '#4b2b86']]; }
export function maxOf(collection: GeoJSON.FeatureCollection | undefined, key: string) { const values = (collection?.features ?? []).map((f) => f.properties?.[key]).filter((v): v is number => typeof v === 'number' && Number.isFinite(v)); return values.length ? Math.max(...values) : 0; }
export function statValue(value: unknown, status: unknown, unit: string) { if (typeof value === 'number') return formatMetric(value, unit, 0); return status === 'SUPPRESSED' ? '비공개(*)' : status === 'NOT_COLLECTED' ? '미수집' : '자료 없음'; }
function applyVisibility(map: maplibregl.Map, visible: Record<LayerKey, boolean>) { for (const [key, ids] of Object.entries(LAYER_IDS) as [LayerKey, string[]][]) ids.forEach((id) => { if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', visible[key] ? 'visible' : 'none'); }); }
export function addOverlayLayers(map: maplibregl.Map, data: OverlayData): boolean {
  for (const key of ['zoning', 'admin'] as const) { const source = map.getSource(key) as maplibregl.GeoJSONSource | undefined; if (source) source.setData(data[key]); else map.addSource(key, { type: 'geojson', data: data[key] }); }
  if (map.getLayer('zoning-fill')) { map.setPaintProperty('admin-fill', 'fill-color', densityColor(maxOf(data.admin, 'population_density'))); return false; }
  // Above the grid fill so the official polygons read clearly; grid lines stay on top.
  const before = map.getLayer('grid-line') ? 'grid-line' : undefined;
  map.addLayer({ id: 'zoning-fill', type: 'fill', source: 'zoning', layout: { visibility: 'none' }, paint: { 'fill-color': zoneColor(), 'fill-opacity': 0.62 } }, before);
  map.addLayer({ id: 'zoning-line', type: 'line', source: 'zoning', layout: { visibility: 'none' }, paint: { 'line-color': '#ffffff', 'line-width': 0.5 } }, before);
  map.addLayer({ id: 'admin-fill', type: 'fill', source: 'admin', layout: { visibility: 'none' }, paint: { 'fill-color': densityColor(maxOf(data.admin, 'population_density')), 'fill-opacity': 0.55 } }, before);
  map.addLayer({ id: 'admin-line', type: 'line', source: 'admin', layout: { visibility: 'none' }, paint: { 'line-color': '#5b3f8f', 'line-width': 1.2 } }, before);
  return true;
}

