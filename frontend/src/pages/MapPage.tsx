import * as maplibregl from 'maplibre-gl';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import { ChevronDown, Layers3, LocateFixed, RefreshCw, X } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { DongPanel } from '../components/DongPanel';
import { LayerGroupTitle, LayerToggle } from '../components/LayerToggle';
import { MetricCard } from '../components/MetricCard';
import { MissingValue } from '../components/MissingValue';
import { PageHeader } from '../components/PageHeader';
import { ProvenanceBadge } from '../components/ProvenanceBadge';
import { ProvinceMap } from '../components/ProvinceMap';
import { ShareBar } from '../components/ShareBar';
import { ErrorState, LoadingState } from '../components/Status';
import { WeatherChart } from '../components/WeatherChart';
import { setBasemapStatus } from '../hooks/useBasemapStatus';
import { useApi } from '../hooks/useApi';
import { regionParam, useAnalysisScope } from '../hooks/useAnalysisScope';
import { refreshSystemInfo, useSystemInfo } from '../hooks/useSystemInfo';
import { api } from '../lib/api';
import { dongCells } from '../lib/dongs';
import { formatMetric } from '../lib/format';
import { referenceGrid } from '../lib/mapGrid';
import { classify, METRIC_GROUPS, METRICS, MISSING_FILL, rangeLabel, stepColor, USE_COLORS, USE_NAME, withMetricValues, ZONE_NAME, type Classification, type MetricDef } from '../lib/mapMetrics';
import { provenanceFromCode } from '../lib/provenance';
import { LINE_ON_BASEMAP, SEQ_RAMP, TOKENS, ZONE_DETAIL, ZONE_GROUP_COLOR } from '../theme/palette';
import type { BuildingViewport, DashboardData, DongData, GridProps, MapData, OverlayData, RegionSummary } from '../types';

maplibregl.setWorkerUrl(workerUrl);

/** 용도지역 대분류 범례 (서버 category). 색은 palette.ts, 미분류는 해치. */
export const ZONE_LEGEND: ReadonlyArray<readonly [string, string, string]> = [
  ['RESIDENTIAL', '주거지역', TOKENS['zone-r2']], ['COMMERCIAL', '상업지역', TOKENS['zone-cg']], ['INDUSTRIAL', '공업지역', TOKENS['zone-ig']], ['GREEN', '녹지지역', TOKENS['zone-gp']], ['OTHER', '관리·농림·기타', TOKENS['zone-m']],
];
type LayerKey = 'grids' | 'buildings' | 'complexes' | 'boundary' | 'dongs' | 'zoning' | 'admin';
const LAYER_IDS: Record<LayerKey, string[]> = { grids: ['grid-fill', 'grid-missing', 'grid-line'], buildings: ['buildings-fill', 'buildings-unknown', 'buildings-line'], complexes: ['complexes-circle'], boundary: ['boundary-line'], dongs: ['dong-line'], zoning: ['zoning-unknown', 'zoning-halo', 'zoning-line'], admin: ['admin-fill', 'admin-line'] };
/** 처음에는 격자 색과 경계선만. 겹쳐 보는 레이어(건물·단지·용도지역·행정동)는 한 번에 하나만 켠다. */
const DEFAULT_VISIBLE: Record<LayerKey, boolean> = { grids: true, buildings: false, complexes: false, boundary: true, dongs: true, zoning: false, admin: false };
export const OVERLAY_KEYS: ReadonlyArray<LayerKey> = ['buildings', 'complexes', 'zoning', 'admin'];
/** 레이어 하나를 켜고 끈다. 겹쳐 보기 레이어를 켜면 다른 겹쳐 보기 레이어는 끈다(격자·경계선은 그대로). */
export function toggleLayer(visible: Record<LayerKey, boolean>, key: LayerKey, on: boolean): Record<LayerKey, boolean> {
  const next = { ...visible, [key]: on };
  if (on && OVERLAY_KEYS.includes(key)) for (const other of OVERLAY_KEYS) if (other !== key) next[other] = false;
  return next;
}
const PROVINCE_KEY = 'carbon-map-province';
type MapView = 'province' | 'region';

/** 시·도 코드(법정 2자리): 주소의 sido → 이 브라우저에 기억한 값 → 분석 지역의 시·도. 제주(50)는 이 화면에서 제외. */
export function pickProvince(param: string | null, stored: string | null, regionCode: string | null): string {
  for (const code of [param, stored, regionCode?.slice(0, 2) ?? null]) if (code && /^\d{2}$/.test(code) && code !== '50') return code;
  return '52';
}
function storedProvince(): string | null { try { return localStorage.getItem(PROVINCE_KEY); } catch { return null; } }
function storeProvince(code: string) { try { localStorage.setItem(PROVINCE_KEY, code); } catch { /* Optional browser storage. */ } }

/** 지도 분석: 1단계 시·도 500m 격자(전국 공통 지표) → 2단계 분석 준비 시·군·구 상세(에너지·탄소·건물·용도지역). */
export function MapPage() {
  const [params, setParams] = useSearchParams();
  const view: MapView = params.get('view') === 'region' ? 'region' : 'province';
  const { region, setScope } = useAnalysisScope();
  const system = useSystemInfo();
  const defaultRegion = system?.default_region ?? '52110';
  const regionName = system?.region?.short_name ?? '전주시';
  const province = pickProvince(params.get('sido'), storedProvince(), region ?? defaultRegion);
  const [offline, setOffline] = useState<boolean | null>(null);
  useEffect(() => { const update = () => { api<{ offline_mode: boolean }>('/system').then((s) => setOffline(s.offline_mode)).catch(() => setOffline(true)); }; update(); window.addEventListener('carbon-system-change', update); return () => window.removeEventListener('carbon-system-change', update); }, []);
  useEffect(() => () => setBasemapStatus('not-on-map'), []);
  const go = (next: Record<string, string>) => setParams((old) => { const p = new URLSearchParams(old); for (const [k, v] of Object.entries(next)) p.set(k, v); return p; });
  const chooseProvince = (code: string) => { storeProvince(code); go({ view: 'province', sido: code }); };
  const openRegion = (code: string, grid: string | null) => {
    setScope({ region: code === defaultRegion ? null : code, gridId: grid });
    setParams((old) => { const p = new URLSearchParams(old); p.set('view', 'region'); p.delete('dong'); return p; });
  };
  const description = view === 'province'
    ? '시·도를 고르면 그 시·도 전체를 SGIS 공식 500m 격자로 나눠 전국 공통 지표(인구·주택·공동주택)로 칠합니다. 어느 격자든 누르면 그 시·군·구 지도(읍면동 포함)로 들어갑니다. 굵은 테두리는 에너지·건물·용도지역까지 모은 상세 자료 지역입니다.'
    : `${regionName}의 500m 분석 격자(격자당 250,000m²)와 읍면동입니다. 격자를 누르면 모든 분석 화면의 대상지가 바뀌고, 읍면동을 고르면 격자 지표를 동 단위로 모아 봅니다.`;
  return <div className="page map-page">
    <PageHeader title="도시 탄소 지도" description={description} />
    <nav className="map-views" aria-label="지도 보기">
      <Link to={`?view=province&sido=${province}`} aria-current={view === 'province' ? 'page' : undefined} onClick={() => storeProvince(province)}><strong>1. 시·도 500m 격자</strong><small>전국 공통 지표, 제주 제외</small></Link>
      <Link to="?view=region" aria-current={view === 'region' ? 'page' : undefined}><strong>2. 시·군·구 · 읍면동</strong><small>{regionName} 상세 지도</small></Link>
    </nav>
    {view === 'province'
      ? <ProvinceMap provinceCode={province} onProvince={chooseProvince} onOpenRegion={openRegion} offline={offline} />
      : <RegionDetailMap offline={offline} />}
  </div>;
}
const BUILDING_MIN_ZOOM = 14;
const EMPTY: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features: [] };
const DEFAULT_METRIC_ORDER = ['far_est_pct', 'coverage_pct', 'residential_zone_ratio', 'complex_households', 'electricity_kwh_per_m2'];
const HATCH = 'hatch-missing';
const MISSING_NOTICE: Record<'zoning' | 'admin', string> = {
  zoning: '용도지역 자료 미확보: VWorld 또는 원본 파일 승인 후 표시됩니다.',
  admin: '행정동 인구 자료 미확보: SGIS 인구·가구를 수집한 뒤 표시됩니다.',
};

function RegionDetailMap({ offline }: { offline: boolean | null }) {
  const { year, gridId, query, regionQuery, region, setScope } = useAnalysisScope();
  const { data, loading, error, reload } = useApi<MapData>(`/map?year=${year}${regionQuery}`);
  const details = useApi<DashboardData>(`/dashboard?${query}`);
  const overlays = useApi<OverlayData>(`/map/overlays?year=${year}${regionQuery}`);
  const dongs = useApi<DongData>(`/map/dongs${regionParam(region, '?')}`);
  const [params, setParams] = useSearchParams();
  const dongCode = params.get('dong');
  const dongIndex = dongs.data && dongCode ? dongs.data.dongs.findIndex((d) => d.code === dongCode) : -1;
  const [dongView, setDongView] = useState(() => !!params.get('dong'));
  const setDong = (code: string | null) => {
    setParams((old) => { const next = new URLSearchParams(old); if (code) next.set('dong', code); else next.delete('dong'); return next; });
    if (code) setDongView(true);
  };
  const opening = useOpenRegion(region, error, () => { void reload(); void details.reload(); void overlays.reload(); void dongs.reload(); });
  const regionName = data?.region?.short_name ?? '전주시';
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const hoverPopup = useRef<maplibregl.Popup | null>(null);
  const [mapReady, setMapReady] = useState(0);
  const [mapError, setMapError] = useState<string | null>(null);
  const [basemapEnabled, setBasemapEnabled] = useState(true);
  const [legendOpen, setLegendOpen] = useState(() => typeof window === 'undefined' || window.innerWidth > 720);
  const [basemapFailed, setBasemapFailed] = useState(false);
  const [metricKey, setMetricKey] = useState<string | null>(null);
  const [visible, setVisible] = useState<Record<LayerKey, boolean>>(DEFAULT_VISIBLE);
  const [adminInfo, setAdminInfo] = useState<Record<string, unknown> | null>(null);
  const [viewport, setViewport] = useState<{ total: number; shown: number; truncated: boolean; needZoom: boolean; counts: Record<string, number>; quality: unknown } | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [layersOpen, setLayersOpen] = useState(false);
  const [detailOpen, setDetailOpen] = useState(true);
  const visibleRef = useRef(visible); visibleRef.current = visible;

  const grids = useMemo(() => (data ? withMetricValues(data.grids) : null), [data]);
  const reference = useMemo(() => (grids ? referenceGrid(grids as GeoJSON.FeatureCollection) : EMPTY), [grids]);
  const classifications = useMemo(() => {
    const result: Record<string, Classification> = {};
    if (!grids) return result;
    // 범례 경계는 실제 값으로 계산한다(분위수 또는 지표별 고정 경계). 색 램프만 지표 성격을 따른다.
    for (const metric of METRICS) result[metric.key] = classify(grids.features.map((f) => (f.properties as GridProps)[metric.key] as number | null), metric.breaks, metric.ramp);
    return result;
  }, [grids]);
  const activeKey = metricKey ?? DEFAULT_METRIC_ORDER.find((key) => (classifications[key]?.valued ?? 0) >= 20) ?? METRICS.find((m) => classifications[m.key]?.valued)?.key ?? 'electricity_kwh_annual';
  const metric = METRICS.find((m) => m.key === activeKey) ?? METRICS[0];
  const classification = classifications[metric.key] ?? { classes: [], lowerBounds: [], valued: 0, missing: 0, min: null, max: null };
  const metricRef = useRef({ metric, classification }); metricRef.current = { metric, classification };
  const selectedId = gridId || String(data?.selected_sector?.grid_id || '');
  const selectedRef = useRef(selectedId); selectedRef.current = selectedId;
  const selected = grids?.features.find((f) => String((f.properties as GridProps).id) === selectedId)?.properties as GridProps | undefined;
  const showBasemap = offline === false && basemapEnabled && !basemapFailed;
  const gridProps = useMemo(() => new Map((grids?.features ?? []).map((f) => [String((f.properties as GridProps).id), f.properties as GridProps])), [grids]);
  const dongShares = useMemo(() => dongCells(dongs.data, dongIndex), [dongs.data, dongIndex]);
  const dongsRef = useRef(dongs.data); dongsRef.current = dongs.data;

  // 표제란의 모드 칸: 배경지도가 없으면(오프라인·끔·타일 실패) "배경지도 없음".
  useEffect(() => { if (offline !== null) setBasemapStatus(showBasemap ? 'shown' : 'none'); }, [offline, showBasemap]);

  useEffect(() => {
    if (!container.current || !data || !grids || offline === null) return;
    setMapError(null); setBasemapFailed(false); setVisible(DEFAULT_VISIBLE); setAdminInfo(null); setViewport(null);
    const withBasemap = !offline && basemapEnabled;
    const map = new maplibregl.Map({
      container: container.current, center: data.center || [127.148, 35.824], zoom: 11.5, attributionControl: false,
      ...(data.bbox ? { bounds: data.bbox as [number, number, number, number], fitBoundsOptions: { padding: 24 } } : {}),
      style: { version: 8, sources: withBasemap ? { basemap: { type: 'raster', tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'], tileSize: 256, attribution: '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap contributors</a>' } } : {}, layers: [{ id: 'background', type: 'background', paint: { 'background-color': TOKENS.canvas } }, ...(withBasemap ? [{ id: 'basemap', type: 'raster' as const, source: 'basemap', paint: { 'raster-opacity': 0.55, 'raster-saturation': -0.7 } }] : [])] },
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'bottom-right');
    map.addControl(new maplibregl.ScaleControl({ maxWidth: 96, unit: 'metric' }), 'bottom-left');
    map.addControl(new maplibregl.NavigationControl({ showZoom: false, showCompass: true, visualizePitch: false }), 'bottom-left');
    map.addControl(new maplibregl.AttributionControl({ compact: true, customAttribution: '지표 Carbon Urban DSS, 경계 SGIS, 용도지역·건물 VWorld, 단지 K-apt' }), 'bottom-right');
    map.on('error', (e) => { if (isBasemapError(e)) { setBasemapFailed(true); if (map.getLayer('basemap')) map.removeLayer('basemap'); if (map.getSource('basemap')) map.removeSource('basemap'); } else setMapError('지도 도형을 불러오지 못했습니다. 새로고침해 주세요.'); });
    map.on('load', () => {
      addHatchImage(map);
      map.addSource('grids', { type: 'geojson', data: grids as GeoJSON.FeatureCollection, promoteId: 'id' });
      map.addSource('reference', { type: 'geojson', data: reference });
      map.addSource('boundary', { type: 'geojson', data: data.boundary });
      map.addSource('buildings', { type: 'geojson', data: data.buildings_mode === 'viewport' ? EMPTY : data.buildings });
      map.addSource('complexes', { type: 'geojson', data: data.complexes ?? EMPTY });
      const { metric: m, classification: c } = metricRef.current;
      // 1km 참조 격자: 배경지도가 없을 때만 보인다.
      map.addLayer({ id: 'reference-grid', type: 'line', source: 'reference', layout: { visibility: withBasemap ? 'none' : 'visible' }, paint: { 'line-color': TOKENS.line, 'line-width': 1 } });
      map.addLayer({ id: 'grid-fill', type: 'fill', source: 'grids', paint: { 'fill-color': stepColor(m.key, c) as unknown as maplibregl.ExpressionSpecification, 'fill-opacity': gridOpacity() } });
      map.addLayer({ id: 'grid-missing', type: 'fill', source: 'grids', filter: missingFilter(m.key), paint: { 'fill-pattern': HATCH, 'fill-opacity': gridOpacity() } });
      map.addLayer({ id: 'grid-line', type: 'line', source: 'grids', paint: { 'line-color': withBasemap ? LINE_ON_BASEMAP : TOKENS['line-strong'], 'line-width': ['interpolate', ['linear'], ['zoom'], 11, 0.4, 15, 1] } });
      // 읍면동을 고르면 그 동 밖의 격자를 옅게 덮는다.
      map.addLayer({ id: 'grid-dim', type: 'fill', source: 'grids', filter: ['==', ['get', 'id'], '__none__'], paint: { 'fill-color': TOKENS.canvas, 'fill-opacity': 0.72 } });
      map.addLayer({ id: 'boundary-line', type: 'line', source: 'boundary', paint: { 'line-color': TOKENS['ink-2'], 'line-width': 1.5 } });
      map.addLayer({ id: 'buildings-fill', type: 'fill', source: 'buildings', filter: ['!=', ['coalesce', ['get', 'use_category'], 'RESIDENTIAL'], 'UNKNOWN'], minzoom: data.buildings_mode === 'viewport' ? BUILDING_MIN_ZOOM - 0.5 : 0, paint: { 'fill-color': useColor() as unknown as maplibregl.ExpressionSpecification, 'fill-opacity': 0.9 } });
      map.addLayer({ id: 'buildings-unknown', type: 'fill', source: 'buildings', filter: ['==', ['coalesce', ['get', 'use_category'], 'RESIDENTIAL'], 'UNKNOWN'], minzoom: data.buildings_mode === 'viewport' ? BUILDING_MIN_ZOOM - 0.5 : 0, paint: { 'fill-pattern': HATCH } });
      map.addLayer({ id: 'buildings-line', type: 'line', source: 'buildings', minzoom: 15, paint: { 'line-color': TOKENS['ink-3'], 'line-width': 0.5 } });
      map.addLayer({ id: 'complexes-circle', type: 'circle', source: 'complexes', layout: { visibility: 'none' }, paint: { 'circle-radius': ['interpolate', ['linear'], ['zoom'], 11, ['max', 2, ['/', ['sqrt', ['coalesce', ['get', 'households'], 1]], 6]], 16, ['max', 4, ['/', ['sqrt', ['coalesce', ['get', 'households'], 1]], 2.2]]], 'circle-color': TOKENS.primary, 'circle-opacity': 0.75, 'circle-stroke-color': TOKENS.surface, 'circle-stroke-width': 1 } });
      map.addLayer({ id: 'hover-grid', type: 'line', source: 'grids', filter: selectedFilter(''), paint: { 'line-color': TOKENS['select-line'], 'line-width': 1.5, 'line-opacity': 0.6 } });
      map.addLayer({ id: 'selected-halo', type: 'line', source: 'grids', filter: selectedFilter(selectedRef.current), paint: { 'line-color': TOKENS['select-halo'], 'line-width': 4.5 } });
      map.addLayer({ id: 'selected-grid', type: 'line', source: 'grids', filter: selectedFilter(selectedRef.current), paint: { 'line-color': TOKENS['select-line'], 'line-width': 2.5 } });
      fitToData(map, data.boundary?.features?.length ? data.boundary : (grids as GeoJSON.FeatureCollection));
      hoverPopup.current = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 12, maxWidth: '280px' });
      map.on('mousemove', 'grid-fill', (e) => {
        const props = e.features?.[0]?.properties as unknown as GridProps | undefined; if (!props) return;
        map.getCanvas().style.cursor = 'pointer';
        map.setFilter('hover-grid', selectedFilter(props.id));
        hoverPopup.current?.setLngLat(e.lngLat).setHTML(gridTooltip(props, metricRef.current.metric, metricRef.current.classification, dongLabel(dongsRef.current, String(props.id)))).addTo(map);
      });
      map.on('mouseleave', 'grid-fill', () => { map.getCanvas().style.cursor = ''; map.setFilter('hover-grid', selectedFilter('')); hoverPopup.current?.remove(); });
      map.on('click', 'grid-fill', (e) => { const id = e.features?.[0]?.properties?.id; if (id) { setScope({ gridId: String(id) }); setDetailOpen(true); setDongView(false); } });
      for (const layer of ['buildings-fill', 'buildings-unknown', 'complexes-circle']) {
        map.on('mouseenter', layer, () => { map.getCanvas().style.cursor = 'pointer'; });
        map.on('mouseleave', layer, () => { map.getCanvas().style.cursor = ''; });
      }
      for (const layer of ['buildings-fill', 'buildings-unknown']) map.on('click', layer, (e) => { const p = e.features?.[0]?.properties; if (p) new maplibregl.Popup({ offset: 8, maxWidth: '280px' }).setLngLat(e.lngLat).setHTML(buildingTooltip(p)).addTo(map); });
      map.on('click', 'complexes-circle', (e) => { const p = e.features?.[0]?.properties; if (p) new maplibregl.Popup({ offset: 8, maxWidth: '300px' }).setLngLat(e.lngLat).setHTML(complexTooltip(p)).addTo(map); });
      applyVisibility(map, visibleRef.current);
      setMapReady((n) => n + 1);
    });
    map.on('idle', () => {
      const el = container.current; if (!el) return;
      if (map.getLayer('grid-fill')) el.dataset.renderedFeatures = String(map.queryRenderedFeatures({ layers: ['grid-fill'] }).length);
      for (const [key, ids] of [['renderedZoning', ['zoning-line']], ['renderedAdmin', ['admin-fill']], ['renderedBuildings', ['buildings-fill', 'buildings-unknown']]] as const) {
        const shown = ids.filter((id) => map.getLayer(id) && map.getLayoutProperty(id, 'visibility') !== 'none');
        el.dataset[key] = shown.length ? String(map.queryRenderedFeatures({ layers: [...shown] }).length) : '0';
      }
    });
    mapRef.current = map;
    return () => { hoverPopup.current?.remove(); map.remove(); mapRef.current = null; };
  }, [data, grids, reference, offline, basemapEnabled, setScope]);

  useEffect(() => { const m = mapRef.current; if (!m?.getLayer('selected-grid')) return; m.setFilter('selected-grid', selectedFilter(selectedId)); m.setFilter('selected-halo', selectedFilter(selectedId)); }, [selectedId, mapReady]);
  useEffect(() => {
    const m = mapRef.current; if (!m?.getLayer('grid-fill')) return;
    m.setPaintProperty('grid-fill', 'fill-color', stepColor(metric.key, classification) as unknown as maplibregl.ExpressionSpecification);
    m.setFilter('grid-missing', missingFilter(metric.key));
  }, [metric.key, classification, mapReady]);
  // 배경지도 유무: 격자선 흰색 0.6 ↔ --line-strong, 1km 참조 격자 켜고 끄기.
  useEffect(() => {
    const m = mapRef.current; if (!m?.getLayer('grid-line')) return;
    m.setPaintProperty('grid-line', 'line-color', showBasemap ? LINE_ON_BASEMAP : TOKENS['line-strong']);
    m.setLayoutProperty('reference-grid', 'visibility', showBasemap ? 'none' : 'visible');
  }, [showBasemap, mapReady]);
  useEffect(() => {
    const m = mapRef.current; if (!m?.getLayer('grid-fill')) return;
    applyVisibility(m, visible);
    const faded = OVERLAY_KEYS.some((key) => visible[key]);
    m.setPaintProperty('grid-fill', 'fill-opacity', gridOpacity(faded)); m.setPaintProperty('grid-missing', 'fill-opacity', gridOpacity(faded));
  }, [visible, mapReady]);
  useEffect(() => {
    const m = mapRef.current; const o = overlays.data; if (!m || !mapReady || !o) return;
    if (addOverlayLayers(m, o)) {
      m.on('click', 'admin-fill', (e) => setAdminInfo((e.features?.[0]?.properties as Record<string, unknown> | undefined) ?? null));
      m.on('mouseenter', 'admin-fill', () => { m.getCanvas().style.cursor = 'pointer'; });
      m.on('mouseleave', 'admin-fill', () => { m.getCanvas().style.cursor = ''; });
    }
    applyVisibility(m, visibleRef.current);
  }, [overlays.data, mapReady]);

  // 읍면동 경계: 점선(항상), 고른 동은 굵은 선 + 그 밖 격자는 옅게.
  useEffect(() => {
    const m = mapRef.current; const d = dongs.data; if (!m || !mapReady || !d) return;
    const source = m.getSource('dongs') as maplibregl.GeoJSONSource | undefined;
    if (source) source.setData(d.boundaries);
    else {
      m.addSource('dongs', { type: 'geojson', data: d.boundaries });
      const before = m.getLayer('hover-grid') ? 'hover-grid' : undefined;
      m.addLayer({ id: 'dong-line', type: 'line', source: 'dongs', paint: { 'line-color': TOKENS['ink-2'], 'line-width': ['interpolate', ['linear'], ['zoom'], 10, 0.6, 14, 1.2], 'line-dasharray': [3, 2] } }, before);
      m.addLayer({ id: 'dong-selected-halo', type: 'line', source: 'dongs', filter: ['==', ['get', 'i'], -1], paint: { 'line-color': TOKENS['select-halo'], 'line-width': 6 } }, before);
      m.addLayer({ id: 'dong-selected', type: 'line', source: 'dongs', filter: ['==', ['get', 'i'], -1], paint: { 'line-color': TOKENS.primary, 'line-width': 3 } }, before);
    }
    applyVisibility(m, visibleRef.current);
  }, [dongs.data, mapReady]);
  useEffect(() => {
    const m = mapRef.current; if (!m || !mapReady || !m.getLayer('dong-selected')) return;
    const selectedDong: maplibregl.FilterSpecification = ['==', ['get', 'i'], dongIndex];
    m.setFilter('dong-selected', selectedDong); m.setFilter('dong-selected-halo', selectedDong);
    m.setFilter('grid-dim', dongIndex >= 0 ? ['!', ['in', ['get', 'id'], ['literal', [...dongShares.keys()]]]] : ['==', ['get', 'id'], '__none__']);
    const feature = dongIndex >= 0 ? dongs.data?.boundaries.features.find((f) => f.properties.i === dongIndex) : undefined;
    if (feature) fitToData(m, { type: 'FeatureCollection', features: [feature] }, 15, true);
  }, [dongIndex, dongShares, dongs.data, mapReady]);

  // Official buildings are served per viewport (tens of thousands of footprints city-wide).
  useEffect(() => {
    const m = mapRef.current; if (!m || !mapReady || data?.buildings_mode !== 'viewport') return;
    let controller: AbortController | null = null; let timer = 0;
    const load = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        const source = m.getSource('buildings') as maplibregl.GeoJSONSource | undefined; if (!source) return;
        if (!visibleRef.current.buildings || m.getZoom() < BUILDING_MIN_ZOOM) { source.setData(EMPTY); setViewport((old) => ({ total: old?.total ?? 0, shown: 0, truncated: false, needZoom: true, counts: {}, quality: old?.quality ?? null })); return; }
        const b = m.getBounds(); controller?.abort(); controller = new AbortController();
        api<BuildingViewport>(`/map/buildings?bbox=${[b.getWest(), b.getSouth(), b.getEast(), b.getNorth()].map((v) => v.toFixed(5)).join(',')}`, { signal: controller.signal })
          .then((fc) => { source.setData(fc); const counts: Record<string, number> = {}; for (const f of fc.features) { const k = String(f.properties?.use_category ?? 'UNKNOWN'); counts[k] = (counts[k] ?? 0) + 1; } setViewport({ total: fc.total, shown: fc.features.length, truncated: fc.truncated, needZoom: false, counts, quality: fc.features[0]?.properties?.quality ?? null }); })
          .catch(() => undefined);
      }, 250);
    };
    load(); m.on('moveend', load);
    return () => { m.off('moveend', load); window.clearTimeout(timer); controller?.abort(); };
  }, [mapReady, data?.buildings_mode, visible.buildings]);

  if (opening.state === 'opening') return <div className="map-state"><LoadingState label={`${opening.name ?? '이 시·군·구'} 지도를 만드는 중입니다. 전국 자료로 500m 격자·읍면동을 만드는 처음 한 번만 몇 초~1분 걸립니다`} /></div>;
  if (opening.state === 'failed') return <div className="map-state"><ErrorState message={opening.message} onRetry={opening.retry} /></div>;
  if (loading) return <div className="map-state"><LoadingState label="공간 레이어를 불러오는 중입니다" /></div>;
  if (error || !data || !grids) return <div className="map-state"><ErrorState message={error} onRetry={reload} /></div>;
  const overlayMeta = overlays.data?.meta; const adminMax = maxOf(overlays.data?.admin, 'population_density');
  const focus = () => { const f = grids.features.find((x) => String((x.properties as GridProps).id) === selectedId); if (mapRef.current && f) fitToData(mapRef.current, { type: 'FeatureCollection', features: [f] }, 16, true); };
  const total = grids.features.length;
  const zoningTotal = Object.values(overlayMeta?.zoning_area_km2_by_category ?? {}).reduce((a, b) => a + b, 0);
  const zoningCount = overlayMeta?.zoning_features ?? 0; const adminCount = overlayMeta?.admin_features ?? 0;
  const zoningQuality = provenanceFromCode(overlays.data?.zoning.features[0]?.properties?.quality);
  const adminQuality = provenanceFromCode(overlays.data?.admin.features[0]?.properties?.quality);
  const buildingQuality = provenanceFromCode(viewport?.quality);
  const dongShown = dongView && !!dongs.data?.dongs.length;
  const detailShown = !dongShown && !!selected && detailOpen;
  const level = data.region?.level ?? 'DETAILED';
  const selectedDongs = selected ? dongLabel(dongs.data, String(selected.id), true) : null;
  const overlayOn = OVERLAY_KEYS.some((key) => visible[key]);
  const toggle = (key: LayerKey) => (on: boolean) => setVisible((old) => toggleLayer(old, key, on));
  return <div className={`map-workspace${detailShown || dongShown ? ' has-detail' : ''}`}>
      <div className="map-stage">
        <div ref={container} className={`map-canvas${showBasemap ? '' : ' no-basemap'}`} aria-label={`${regionName} 탄소 공간 지도`} />
        <div className="map-rail">
          {level === 'BASIC' && data.region?.code && <BasicRegionNote code={data.region.code} name={regionName} />}
          <div className="metric-picker">
            <button className="metric-trigger" aria-haspopup="listbox" aria-expanded={pickerOpen} onClick={() => setPickerOpen(!pickerOpen)}>
              <span><small>지도 지표</small><strong>{metric.label}</strong></span><em>{metric.unit}</em><ChevronDown size={16} aria-hidden="true" />
            </button>
            {pickerOpen && <section className="map-metrics map-popover" aria-label="지도 지표">
              <header><strong>지표 선택</strong><small>값 있는 격자 / 전체 {total}</small></header>
              {METRIC_GROUPS.map((group) => <div className="metric-group" key={group}><span>{group}</span>{METRICS.filter((m) => m.group === group).map((m) => { const valued = classifications[m.key]?.valued ?? 0; return <button key={m.key} className={`metric-option${m.key === metric.key ? ' active' : ''}${valued ? '' : ' empty'}`} aria-pressed={m.key === metric.key} onClick={() => { setMetricKey(m.key); setPickerOpen(false); }}><span>{m.label} <small>{m.unit}</small></span><em>{valued ? `${valued}/${total}` : '자료 없음'}</em></button>; })}</div>)}
            </section>}
          </div>
          {dongs.data && dongs.data.dongs.length > 0 && <div className="dong-picker">
            <label><span>읍면동</span><span className="select-wrap"><select aria-label="읍면동" value={dongIndex >= 0 ? dongCode ?? '' : ''} onChange={(e) => setDong(e.target.value || null)}>
              <option value="">{regionName} 전체</option>
              {[...dongs.data.dongs].sort((a, b) => a.name.localeCompare(b.name, 'ko')).map((d) => <option key={d.code} value={d.code}>{d.name}</option>)}
            </select><ChevronDown size={15} aria-hidden="true" /></span></label>
            <button type="button" className="tool-button" aria-pressed={dongShown} onClick={() => setDongView(!dongShown)}>동별 비교</button>
          </div>}
          <section className={`map-legend${legendOpen ? '' : ' collapsed'}`} aria-label="지표 범례">
            <div className="legend-head"><strong>{metric.label}</strong><span className="unit">{metric.unit}</span><button type="button" className="legend-toggle" aria-expanded={legendOpen} onClick={() => setLegendOpen((open) => !open)}>{legendOpen ? '범례 접기' : '범례 펼치기'}</button></div>
            {classification.classes.length ? <ul className="legend-classes">{classification.classes.map((c, i) => <li key={i}><i style={{ background: c.color }} /><span>{rangeLabel(c, metric.digits, i === classification.classes.length - 1)}</span><em>{c.count.toLocaleString('ko-KR')}격자</em></li>)}</ul> : <p className="map-empty-hint">이 지표는 아직 계산할 관측 자료가 없습니다. 모든 격자를 자료 미확보(해치)로 표시합니다.</p>}
            {classification.missing > 0 && <div className="legend-missing"><i className="is-missing" /><span>자료 미확보 (0 아님)</span><em>{classification.missing.toLocaleString('ko-KR')}격자</em></div>}
            <div className="legend-coverage"><span>값 있는 격자 {classification.valued.toLocaleString('ko-KR')}/{total.toLocaleString('ko-KR')}</span><b>{formatMetric(classification.valued / Math.max(total, 1) * 100, '%', 1)}</b></div>
            <details className="legend-def"><summary>정의·산식·활용</summary><p>{metric.definition}</p><code>{metric.formula}</code><p className="legend-use"><b>활용</b> {metric.use}</p><p className="legend-source">출처: {metric.source}</p></details>
            <p className="legend-selected"><i aria-hidden="true" />선택 격자</p>
            {visible.zoning && <div className="overlay-legend" aria-label="용도지역 범례"><div className="overlay-head"><strong>용도지역</strong>{zoningQuality && <ProvenanceBadge kind={zoningQuality} />}</div>{zoningCount ? <><ul className="zone-legend">{ZONE_LEGEND.map(([key, label, color]) => { const km2 = overlayMeta?.zoning_area_km2_by_category?.[key]; return <li key={key}><i style={{ borderColor: color }} />{label}{km2 !== undefined && <b>{km2.toFixed(1)}km², {formatMetric(zoningTotal ? km2 / zoningTotal * 100 : null, '%', 1)}</b>}</li>; })}<li><i className="is-missing" />미분류·미지정</li></ul><small>외곽선 색은 세부 용도지역(제1·2·3종 일반주거 등)을 명도로 구분합니다. VWorld LT_C_UQ111, 도형 {zoningCount.toLocaleString('ko-KR')}개, 분석 격자 내 면적.</small></> : <p className="overlay-missing" role="status">{MISSING_NOTICE.zoning}</p>}</div>}
            {visible.admin && <div className="overlay-legend" aria-label="행정동 인구 범례"><div className="overlay-head"><strong>행정동 인구밀도</strong>{adminQuality && <ProvenanceBadge kind={adminQuality} />}</div>{adminCount ? <><ul className="legend-classes compact">{densitySteps(adminMax).map(([from, to], i) => <li key={i}><i style={{ background: SEQ_RAMP[i] }} /><span>{formatMetric(from, '', 0)} ~ {formatMetric(to, '', 0)}{i < 4 ? ' 미만' : ''}</span><em>명/km²</em></li>)}</ul><small>SGIS {overlayMeta?.admin_reference_year ?? ''} 행정통계, 공식 행정동 경계. 격자로 배분하지 않습니다.</small>{adminInfo && <dl className="admin-info"><div><dt>행정동</dt><dd>{String(adminInfo.adm_name ?? '—')}</dd></div><div><dt>인구</dt><dd>{statValue(adminInfo.population, adminInfo.population_status, '명')}</dd></div><div><dt>가구</dt><dd>{statValue(adminInfo.households, adminInfo.household_status, '가구')}</dd></div><div><dt>인구밀도</dt><dd>{typeof adminInfo.population_density === 'number' ? formatMetric(adminInfo.population_density, '명/km²', 0) : '자료 없음'}</dd></div></dl>}</> : <p className="overlay-missing" role="status">{MISSING_NOTICE.admin}</p>}</div>}
            {visible.buildings && <div className="overlay-legend" aria-label="건물 용도 범례"><div className="overlay-head"><strong>건물 용도</strong>{buildingQuality && <ProvenanceBadge kind={buildingQuality} />}</div><ul className="use-legend">{USE_COLORS.map(([key, color]) => <li key={key}><i className={color ? undefined : 'is-missing'} style={{ background: color ?? undefined }} />{USE_NAME[key]}{viewport && !viewport.needZoom && <b>{(viewport.counts[key] ?? 0).toLocaleString('ko-KR')}</b>}</li>)}</ul><small>{data.buildings_source}{data.buildings_mode === 'viewport' ? `. 확대 ${BUILDING_MIN_ZOOM} 이상에서 표시` : ''}{viewport && !viewport.needZoom && viewport.shown > 0 && (viewport.counts.UNKNOWN ?? 0) === viewport.shown ? '. 이 레이어에는 용도코드가 없어 모두 용도 미상으로 칠합니다. 용도는 격자 상세의 건축물대장 항목에서 봅니다.' : ''}</small></div>}
          </section>
        </div>
        <div className="map-tools">
          <div className="map-tool-row">
            <button className="tool-button" onClick={reload} aria-label="지도 새로고침"><RefreshCw size={15} aria-hidden="true" /></button>
            <button className="tool-button" aria-expanded={layersOpen} onClick={() => setLayersOpen(!layersOpen)}><Layers3 size={16} aria-hidden="true" />레이어<b>{Object.values(visible).filter(Boolean).length}</b></button>
          </div>
          {layersOpen && <section className="map-layers map-popover" aria-label="레이어">
            <LayerGroupTitle title="격자 색" note="지표 하나" />
            <LayerToggle swatch="fill" colors={classification.classes.map((c) => c.color)} label="분석 격자 (500m)" checked={visible.grids} onChange={toggle('grids')} hint={`지도 지표: ${metric.label}${overlayOn ? '. 겹쳐 보기 중에는 옅게' : ''}`} />
            <LayerGroupTitle title="경계선" />
            <LayerToggle swatch="line" label={`${regionName} 경계`} checked={visible.boundary} onChange={toggle('boundary')} hint={data.boundary_source} />
            <LayerToggle swatch="dong" label={`읍면동 경계${dongs.data ? ` (${dongs.data.dongs.length})` : ''}`} checked={visible.dongs} onChange={toggle('dongs')} hint={dongs.data ? `SGIS ${dongs.data.year ?? ''} 행정동 경계, 고른 동은 굵은 선` : dongs.loading ? '확인 중' : '행정동 경계 없음'} />
            <LayerGroupTitle title="겹쳐 보기" note="한 번에 하나" />
            <LayerToggle swatch="building" label={data.buildings_mode === 'viewport' ? '건물 (도로명주소 건물)' : '건물 (OSM 공동주택, 대체)'} checked={visible.buildings} onChange={toggle('buildings')} hint={data.buildings_mode === 'viewport' ? `확대 ${BUILDING_MIN_ZOOM} 이상에서 표시, 색 = 용도` : '공식 건물 수집 전 대체 자료'} />
            <LayerToggle swatch="dot" label={`공동주택 단지 (K-apt ${data.complexes?.features.length ?? 0})`} checked={visible.complexes} onChange={toggle('complexes')} hint={data.complexes?.features.some((f) => f.properties?.listed_only) ? '전국 단지 목록 위치 (세대수는 상세 자료 수집 후)' : '원 크기 = 세대수'} />
            {([['zoning', '용도지역 (VWorld)', zoningCount], ['admin', '행정동 인구 (SGIS)', adminCount]] as const).map(([key, label, count]) => <LayerToggle key={key} swatch={key} label={label} checked={visible[key]} onChange={toggle(key)} badge={!count ? (overlays.loading ? '확인 중' : '자료 미확보') : undefined} hint={key === 'zoning' ? '색 외곽선 = 용도지역' : '면 색 = 행정동 인구밀도'} />)}
            <LayerGroupTitle title="바탕" />
            <LayerToggle swatch="base" label="배경지도 (OpenStreetMap)" checked={basemapEnabled && !offline} disabled={!!offline} onChange={(v) => setBasemapEnabled(v)} hint={offline ? '오프라인 모드: 외부 타일을 요청하지 않음. 도면지 바탕과 1km 참조 격자로 표시' : basemapFailed ? '연결 실패. 도면지 바탕과 1km 참조 격자로 표시' : undefined} />
          </section>}
        </div>
        <div className="map-notices">
        {data.buildings_mode === 'viewport' && visible.buildings && viewport && <div className="building-count" role="status">{viewport.needZoom ? `건물은 확대(${BUILDING_MIN_ZOOM} 이상)하면 표시됩니다` : `화면 안 건물 ${viewport.total.toLocaleString('ko-KR')}동${viewport.truncated ? ` 중 큰 건물 ${viewport.shown.toLocaleString('ko-KR')}동 표시` : ''}`}</div>}
        {metric.group === '건물 전체 에너지 (건축HUB)' && data.building_energy?.complete === false && <div className="map-toast" role="status">{data.year}년 건축HUB 전 지번 수집이 아직 진행 중이라 일부 법정동만 채워져 있습니다.</div>}
        {basemapFailed && !offline && basemapEnabled && <div className="map-toast" role="status">배경지도를 불러오지 못했습니다. 분석 도형은 도면지 바탕 위에 그대로 표시됩니다.</div>}
        </div>
        {selected && !detailOpen && <button className="detail-tab" onClick={() => setDetailOpen(true)}>격자 상세 <code>{selected.id}</code></button>}
        {mapError && <p role="alert" className="map-error">{mapError}</p>}
      </div>
      {dongShown && dongs.data && <DongPanel data={dongs.data} index={dongIndex >= 0 ? dongIndex : null} grids={gridProps} complexes={data.complexes} metric={metric} regionName={regionName} onSelect={(i) => setDong(i === null ? null : dongs.data?.dongs[i]?.code ?? null)} onClose={() => setDongView(false)} />}
      {detailShown && <GridDetail props={selected} year={year} name={String(data.selected_sector?.grid_id) === selectedId ? data.selected_sector?.name : undefined} dongs={selectedDongs} metric={metric} classification={classification} details={details.data} detailsLoading={details.loading} onFocus={focus} onClose={() => setDetailOpen(false)} />}
    </div>;
}

/** 격자가 걸친 행정동 이름 (겹친 비율 큰 순). ``withShares``: "행정동: 효자1동 70%, 효자2동 30%". */
export function dongLabel(data: DongData | null | undefined, cell: string, withShares = false): string | null {
  const pairs = data?.weights[cell];
  if (!data || !pairs?.length) return null;
  const sorted = [...pairs].sort((a, b) => b[1] - a[1]);
  if (!withShares) return sorted.slice(0, 2).map(([i]) => data.dongs[i]?.name).filter(Boolean).join(' · ');
  return `행정동: ${sorted.map(([i, share]) => `${data.dongs[i]?.name ?? '?'} ${Math.round(share * 100)}%`).join(', ')}`;
}

/** 준비 안 된 시·군·구를 열면(404) 전국 자료로 기본 지도를 한 번 만들고 다시 읽는다. */
function useOpenRegion(region: string | null, error: string | null, onOpened: () => void) {
  const [state, setState] = useState<{ state: 'idle' | 'opening' | 'failed'; message?: string; name?: string }>({ state: 'idle' });
  const tried = useRef<string | null>(null);
  const done = useRef(onOpened); done.current = onOpened;
  const run = useCallback(async () => {
    if (!region) return;
    tried.current = region;
    setState({ state: 'opening' });
    try {
      const opened = await api<RegionSummary>(`/regions/${region}/open`, { method: 'POST', body: '{}' });
      setState({ state: 'idle', name: opened.short_name ?? opened.name });
      void refreshSystemInfo(region);
      window.dispatchEvent(new Event('carbon-regions-change'));
      done.current();
    } catch (e) { setState({ state: 'failed', message: e instanceof Error ? e.message : '지도를 만들지 못했습니다.' }); }
  }, [region]);
  useEffect(() => { if (region && error && tried.current !== region && /준비하지 않은|격자가 아직 없/.test(error)) void run(); }, [region, error, run]);
  return { ...state, retry: run };
}

/** 기본 지도(전국 공통 자료만) 안내와 상세 자료 수집 시작. */
function BasicRegionNote({ code, name }: { code: string; name: string }) {
  const [state, setState] = useState<'idle' | 'busy' | 'started' | 'failed'>('idle');
  const [message, setMessage] = useState<string | null>(null);
  const start = async () => {
    setState('busy');
    try { await api(`/regions/${code}/prepare`, { method: 'POST', body: '{}' }); setState('started'); }
    catch (e) { setState('failed'); setMessage(e instanceof Error ? e.message : '수집을 시작하지 못했습니다.'); }
  };
  return <section className="region-level-note" aria-label="지도 자료 수준">
    <strong>기본 지도</strong>
    <p>{name}은 전국 공통 자료(SGIS 격자 통계·행정동, K-apt 단지 목록, 조례)만 있습니다. 에너지·탄소·건물·용도지역은 상세 자료를 모으면 채워집니다.</p>
    {state === 'started' ? <p role="status">상세 자료 수집을 시작했습니다(지역 크기에 따라 몇 시간, 호출 한도가 있는 자료는 다음 날 이어서). <Link to={`/regions?select=${code}`}>진행 보기</Link></p>
      : <button type="button" className="button secondary small" onClick={() => void start()} disabled={state === 'busy'}>{state === 'busy' ? '시작하는 중…' : '상세 자료 수집 시작'}</button>}
    {message && <p className="muted" role="alert">{message}</p>}
  </section>;
}

function GridDetail({ props: p, year, name, dongs, metric, classification, details, detailsLoading, onFocus, onClose }: { props: GridProps; year: number; name?: string; dongs?: string | null; metric: MetricDef; classification: Classification; details: DashboardData | null; detailsLoading: boolean; onFocus: () => void; onClose: () => void }) {
  const value = p[metric.key] as number | null;
  const cls = value === null ? null : classification.classes.find((c, i) => i === classification.classes.length - 1 ? value >= c.from : value >= c.from && value < c.to);
  const detailMatches = details?.selected_sector && String(details.selected_sector.grid_id) === p.id;
  const months = detailMatches ? details?.monthly ?? [] : [];
  const weather = details?.weather ?? [];
  const osm = p.building_source === 'OSM';
  return <aside className="map-detail" aria-label="선택 격자 상세">
    <header className="detail-head"><div><h2>{name || '선택 격자'}</h2><code className="grid-id">{p.id}</code>{p.sgis500_code && <code className="grid-id official" title="SGIS 공식 500m 격자 코드 (경계 API). 통계값은 자료신청 후 결합">SGIS {p.sgis500_code}</code>}{dongs && <p className="grid-dongs">{dongs}</p>}</div><div className="detail-actions"><button className="icon-link" aria-label="선택 격자로 확대" onClick={onFocus}><LocateFixed size={17} /></button><button className="icon-link" aria-label="상세 닫기" onClick={onClose}><X size={17} /></button></div></header>
    <section className="detail-section current-metric" aria-label="지도 지표 값">
      <h3>{metric.label}</h3>
      <p className="detail-figure">{value === null ? <MissingValue reason="이 격자에는 이 지표를 계산할 관측 자료가 없습니다." /> : <>{cls && <i className="class-swatch" style={{ background: cls.color }} aria-hidden="true" />}{formatMetric(value, '', metric.digits)}<span className="unit">{metric.unit}</span></>}</p>
      {value !== null && metric.basis(p) && <p className="muted">{metric.basis(p)}</p>}
      <p className="metric-use"><b>활용</b> {metric.use}</p>
    </section>
    <section className="detail-section" aria-label="격자 지표">
      <h3>격자 지표 8개</h3>
      <div className="metric-grid dense">
        <MetricCard dense title="연간 전력" value={p.electricity_kwh_annual as number | null} unit="kWh/년" basis={p.electricity_complete_parcels ? `12개월 관측 지번 ${p.electricity_complete_parcels}곳` : undefined} missingReason={p.electricity_months ? `관측 ${p.electricity_months}/12개월. 12개월 모두 있는 지번이 없음` : '월별 전력 관측 없음'} />
        <MetricCard dense title="연간 가스" value={p.gas_kwh_annual as number | null} unit="kWh/년" basis={p.gas_complete_parcels ? `12개월 관측 지번 ${p.gas_complete_parcels}곳` : undefined} missingReason="월별 가스 관측 없음" />
        <MetricCard dense title="전력 원단위" value={p.electricity_kwh_per_m2} unit="kWh/m²·년" digits={1} basis={p.electricity_area_m2 ? `연면적 ${formatMetric(p.electricity_area_m2, 'm²')}, 지번 ${p.electricity_area_parcels}곳` : undefined} missingReason="12개월 관측과 연면적이 모두 있는 지번 없음" />
        <MetricCard dense title="세대당 전력" value={p.electricity_kwh_per_household} unit="kWh/세대·년" basis={p.electricity_households ? `${formatMetric(p.electricity_households, '세대')}, 월 ${formatMetric((p.electricity_kwh_per_household ?? 0) / 12, 'kWh')}` : undefined} missingReason="세대수가 확인된 12개월 관측 지번 없음" />
        <MetricCard dense title="전력 탄소" value={p.electricity_carbon_t as number | null} unit="tCO₂eq/년" digits={1} basis="전력 × 0.4541 kgCO₂eq/kWh (GIR 2024)" missingReason="연간 전력 관측이 없어 계산하지 않음" />
        <MetricCard dense title="건물 수" value={p.building_count} unit="동" provenance={osm ? 'fallback' : null} basis={osm ? 'OSM 공동주택 윤곽만 포함, 전체 건물 아님' : p.building_count !== null ? `밀도 ${formatMetric(p.building_density, '동/km²')}` : undefined} missingReason="건물 레이어 미수집" />
        <MetricCard dense title="건폐율 근사" value={p.coverage_pct} unit="%" digits={1} basis={p.footprint_m2 !== null ? `건축면적 ${formatMetric(p.footprint_m2, 'm²')} ÷ 250,000 m²` : undefined} missingReason="건물 윤곽이 있어야 계산" />
        <MetricCard dense title="추정 용적률" value={p.far_est_pct} unit="%" digits={1} basis={p.floor_area_est_m2 !== null ? `Σ건축면적×층수 ${formatMetric(p.floor_area_est_m2, 'm²')}, 층수 확인 ${formatMetric(p.floors_known_pct, '%')}` : undefined} missingReason="층수가 기록된 건물이 있어야 추정" />
      </div>
      <dl className="fact-list">
        <Fact label="가스 원단위" value={p.gas_kwh_per_m2} unit="kWh/m²·년" digits={1} missingText="연면적이 있는 12개월 가스 관측 지번 없음" />
        <Fact label="평균 지상층수" value={p.avg_floors} unit="층" digits={1} why={p.max_floors ? `최고 ${p.max_floors}층` : undefined} missingText="층수 기록 없음" />
        <Fact label="가스 탄소 (가정 계수)" value={typeof p.gas_carbon_kg_annual === 'number' ? p.gas_carbon_kg_annual / 1000 : null} unit="tCO₂eq/년" digits={1} why="가스 × 0.1826 kgCO₂eq/kWh (IPCC 2006, 총발열량 기준 가정)" missingText="12개월 가스 관측 지번 없음 (0 아님)" />
      </dl>
    </section>
    <section className="detail-section" aria-label="월별 관측">
      <h3>월별 관측 ({months.length ? `${String(months[0]?.use_ym).slice(0, 4)}년` : `${year}년`})</h3>
      {months.length > 0 ? <><MonthRow label="전력" months={months.map((r) => r.electricity_kwh !== null)} /><MonthRow label="가스" months={months.map((r) => r.gas_kwh !== null)} /></> : detailsLoading ? <p className="muted">월별 관측 확인 중…</p> : <MissingValue reason="이 격자에는 월별 에너지 관측이 없습니다." />}
      <h3 className="sub">월평균 기온 ({(details?.region?.short_name ?? '전주시').replace(/시$|군$/, '')}, 격자 공통)</h3>
      {weather.length ? <WeatherChart year={year} rows={weather} height={170} ariaLabel="선택 연도 월평균 기온 차트" /> : <MissingValue reason={detailsLoading ? '확인 중' : '이 연도의 기상 자료가 없습니다.'} />}
    </section>
    <section className="detail-section" aria-label="토지이용과 건물 용도">
      <h3>토지이용 (용도지역)</h3>
      {p.zone_shares && Object.keys(p.zone_shares).length ? <ShareBar shares={p.zone_shares} colors={ZONE_GROUP_COLOR} names={ZONE_NAME} rest="도시지역 외·미지정" /> : <MissingValue reason={p.zoning_status ? '조회했으나 이 격자에 도시지역 용도지역 도형이 없습니다.' : '용도지역 미수집 격자입니다.'} />}
      {p.use_share_pct && Object.keys(p.use_share_pct).length > 0 && <><h3 className="sub">건축면적 기준 건물 용도</h3><ShareBar shares={p.use_share_pct} colors={Object.fromEntries(USE_COLORS)} names={USE_NAME} /></>}
      <h3 className="sub">건물 전체 에너지 (건축HUB 전 지번)</h3>
      {p.bldg_parcels ? <dl className="fact-list">
        <Fact label="계측 지번" value={p.bldg_parcels} unit="곳" why={p.bldg_electricity_complete ? `12개월 전력 ${p.bldg_electricity_complete}곳` : undefined} />
        <Fact label="연간 전력" value={p.bldg_electricity_kwh} unit="kWh/년" missingText="12개월 계측 지번 없음" />
        <Fact label="연간 가스" value={p.bldg_gas_kwh} unit="kWh/년" missingText="12개월 계측 지번 없음" />
        <Fact label="전력 원단위 (대장 연면적)" value={p.bldg_kwh_per_m2} unit="kWh/m²·년" digits={1} missingText="대장 연면적이 있는 계측 지번 없음" />
        <Fact label="전력 탄소" value={p.bldg_carbon_t} unit="tCO₂eq/년" digits={1} missingText="연간 전력 없음" />
      </dl> : <MissingValue reason="건축HUB 전 지번 에너지를 아직 받지 않았거나, 이 격자에 계측 지번이 없습니다(단독주택 위주 등)." />}
      <h3 className="sub">건축물대장 (공식 연면적·용도)</h3>
      {p.reg_buildings ? <dl className="fact-list">
        <Fact label="대장 건물" value={p.reg_buildings} unit="동" why={p.reg_gfa_m2 != null ? `연면적 ${formatMetric(p.reg_gfa_m2, 'm²')}` : undefined} />
        <Fact label="용적률 (격자 기준)" value={p.reg_far_pct} unit="%" digits={1} missingText="용적률산정연면적 없음" />
        <Fact label="주거 연면적 비율" value={p.reg_residential_gfa_pct} unit="%" digits={1} missingText="주용도 확인 건물 없음" />
        <Fact label="2000년 이전 준공 연면적" value={p.reg_old_gfa_pct} unit="%" digits={1} missingText="사용승인일 확인 건물 없음" />
      </dl> : <MissingValue reason="건축물대장을 아직 받지 않았거나 이 격자에 연결된 대장 건물이 없습니다." />}
      <h3 className="sub">공동주택 (K-apt)</h3>
      <dl className="fact-list">
        <Fact label="단지·세대" value={p.complex_count ? p.complex_households : null} unit="세대" missingText="격자 안 단지 없음" why={p.complex_count ? `단지 ${p.complex_count}개` : undefined} />
        <Fact label="연면적 합 (공표값)" value={p.complex_gfa_m2} unit="m²" why={p.complex_gfa_excluded ? `연면적 이상값 ${p.complex_gfa_excluded}개 단지 제외` : undefined} missingText="연면적 공표값 없음" />
      </dl>
    </section>
    <SgisDetail p={p} />
    <div className="grid-actions"><Link className="button primary" to="/simulation">이 격자 시뮬레이션</Link><Link className="button secondary" to="/reports">보고서 작성</Link></div>
  </aside>;
}

/** 소속 SGIS 1km 격자 값. 500m로 나누지 않은 1km 격자 전체 값이다. */
function SgisDetail({ p }: { p: GridProps }) {
  const status = p.sgis1k_status;
  return <section className="detail-section" aria-label="인구와 주택 (SGIS 1km 격자)">
    <h3>인구·주택 (SGIS {p.sgis1k_year ? `${p.sgis1k_year}년 ` : ''}1km 격자{p.sgis1k_code ? ` ${p.sgis1k_code}` : ''})</h3>
    {!status ? <MissingValue reason="SGIS 격자 통계를 아직 가져오지 않았습니다." />
      : status === 'NO_STAT' ? <MissingValue reason="이 1km 격자에는 공표된 통계가 없습니다(인구·사업체 없음 또는 비공개). 0이 아닙니다." />
      : <>
        <dl className="fact-list">
          <Fact label="인구 (1km 격자 전체)" value={p.sgis1k_population} unit="명" missingText="통계 없음" why={p.sgis1k_households != null ? `가구 ${formatMetric(p.sgis1k_households)}` : undefined} />
          <Fact label="주택 (1km 격자 전체)" value={p.sgis1k_housing} unit="호" missingText="통계 없음" />
          <Fact label="종사자 (1km 격자 전체)" value={p.sgis1k_workers} unit="명" missingText="통계 없음" why={p.sgis1k_businesses != null ? `사업체 ${formatMetric(p.sgis1k_businesses)}곳` : undefined} />
          <Fact label="65세 이상 비율" value={p.sgis_elderly_pct} unit="%" digits={1} missingText="기준 20 미만 또는 통계 없음" />
          <Fact label="1인가구 비율" value={p.sgis_single_household_pct} unit="%" digits={1} missingText="기준 20 미만 또는 통계 없음" />
          <Fact label="2000년 이전 주택 비율" value={p.sgis_old_housing_pct} unit="%" digits={1} missingText="기준 20 미만 또는 통계 없음" />
          <Fact label="아파트 비율" value={p.sgis_apartment_pct} unit="%" digits={1} missingText="기준 20 미만 또는 통계 없음" />
        </dl>
        <p className="muted">1km 격자(1km², 이 격자의 4배) 전체 값이며 500m로 나누지 않았습니다. 비밀보호 잡음(인구 ±7)이 들어 있습니다.{p.sgis1k_small?.length ? ' 0 또는 5인 총계는 5 미만일 수 있는 대체값입니다.' : ''}</p>
      </>}
  </section>;
}

function Fact({ label, value, unit, digits = 0, why, missingText }: { label: ReactNode; value: number | null | undefined; unit: string; digits?: number; why?: string; missingText?: string }) {
  const missing = value === null || value === undefined || !Number.isFinite(value);
  return <div className={`fact${missing ? ' missing' : ''}`}><dt>{label}</dt><dd>{missing ? <MissingValue inline reason={missingText} /> : <>{formatMetric(value, '', digits)}{unit && <span className="unit">{unit}</span>}</>}</dd>{why && !missing && <span className="why">{why}</span>}</div>;
}

function MonthRow({ label, months }: { label: string; months: boolean[] }) {
  const count = months.filter(Boolean).length;
  return <div className="month-strip-row"><span>{label}</span><div className="month-strip" aria-label={`${label} 관측 ${count}/12개월`}>{months.map((on, i) => <span key={i} className={on ? 'on' : 'is-missing'} title={`${i + 1}월 ${on ? '관측' : '관측 없음'}`}>{i + 1}</span>)}</div><b>{count}/12</b></div>;
}

function escapeHtml(value: unknown): string { return String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] ?? c); }

function gridTooltip(p: GridProps, metric: MetricDef, classification: Classification, dong?: string | null): string {
  const raw = p[metric.key]; const value = typeof raw === 'number' ? raw : null;
  const cls = value === null ? null : classification.classes.find((c, i) => (i === classification.classes.length - 1 ? value >= c.from : value >= c.from && value < c.to));
  const extra = [p.residential_zone_ratio !== null ? `주거지역 ${formatMetric(p.residential_zone_ratio, '%', 1)}` : null, p.building_count !== null ? `건물 ${formatMetric(p.building_count, '동')}` : null, p.complex_count ? `공동주택 ${p.complex_count}단지` : null].filter(Boolean).join(', ');
  return `<div class="map-tip"><strong>${escapeHtml(p.id)}</strong>${dong ? `<span>${escapeHtml(dong)}</span>` : ''}<span>${escapeHtml(metric.label)}</span><b class="tip-class">${cls ? `<i style="background:${cls.color}"></i>` : '<i class="is-missing"></i>'}${value === null ? '자료 미확보 (0 아님)' : `${escapeHtml(formatMetric(value, '', metric.digits))} ${escapeHtml(metric.unit)}`}</b>${extra ? `<span>${escapeHtml(extra)}</span>` : ''}<span>클릭하면 이 격자를 선택합니다</span></div>`;
}

function buildingTooltip(p: Record<string, unknown>): string {
  const floors = [p.above_floors ? `지상 ${p.above_floors}층` : '지상층수 미상', p.below_floors ? `지하 ${p.below_floors}층` : null].filter(Boolean).join(', ');
  const kind = provenanceFromCode(p.quality);
  return `<div class="map-tip"><strong>${escapeHtml(p.name || '이름 없는 건물')}</strong><span>${escapeHtml(p.use_label || p.use_category_label || '용도 미상')}</span><b>${escapeHtml(floors)}</b><span>건축면적 ${escapeHtml(formatMetric(typeof p.footprint_m2 === 'number' ? p.footprint_m2 : null, 'm²', 0))}</span>${kind ? `<span class="prov-badge prov-${kind}">${escapeHtml(PROV_LABEL[kind])}</span>` : ''}</div>`;
}
const PROV_LABEL: Record<string, string> = { observed: '실측', computed: '계산', estimated: '추정', scenario: '시나리오', fallback: '대체', missing: '자료 미확보' };

function complexTooltip(p: Record<string, unknown>): string {
  const area = typeof p.gross_floor_area_m2 === 'number' ? p.gross_floor_area_m2 : null;
  return `<div class="map-tip"><strong>${escapeHtml(p.name)}</strong><span>K-apt ${escapeHtml(p.kapt_code)}</span><b>${escapeHtml(formatMetric(typeof p.households === 'number' ? p.households : null, '세대'))}</b><span>연면적 ${escapeHtml(formatMetric(area, 'm²'))}${p.floor_area_status !== 'OK' ? `, <em>${escapeHtml(p.floor_area_issue || '연면적 확인 필요')}</em>` : ''}</span><span>사용승인 ${escapeHtml(p.approval_date || '자료 없음')}, ${escapeHtml(p.heating_type || '난방방식 자료 없음')}</span></div>`;
}

/** 격자 면 불투명도 0.85 (DESIGN.md 6). 건물이 보이는 확대 14 이상, 또는 겹쳐 보기 레이어를 켰을 때는 옅게 한다. */
export function gridOpacity(faded = false): maplibregl.ExpressionSpecification { return faded ? ['interpolate', ['linear'], ['zoom'], 13.5, 0.3, 16, 0.15] : ['interpolate', ['linear'], ['zoom'], 13.5, 0.85, 15, 0.35, 16, 0.2]; }
function missingFilter(key: string): maplibregl.FilterSpecification { return ['==', ['get', key], null]; }

/** 해치 패턴 이미지(45°, --hatch 선 / --prov-missing-bg 바탕) — fill-pattern용. */
function addHatchImage(map: maplibregl.Map) {
  if (map.hasImage(HATCH)) return;
  const size = 16; const canvas = document.createElement('canvas'); canvas.width = size; canvas.height = size;
  const ctx = canvas.getContext('2d'); if (!ctx) return;
  ctx.fillStyle = TOKENS['prov-missing-bg']; ctx.fillRect(0, 0, size, size);
  ctx.strokeStyle = TOKENS.hatch; ctx.lineWidth = 2;
  ctx.beginPath(); ctx.moveTo(0, size); ctx.lineTo(size, 0); ctx.moveTo(-4, 4); ctx.lineTo(4, -4); ctx.moveTo(size - 4, size + 4); ctx.lineTo(size + 4, size - 4); ctx.stroke();
  map.addImage(HATCH, ctx.getImageData(0, 0, size, size), { pixelRatio: 2 });
}

function useColor(): unknown[] { return ['match', ['coalesce', ['get', 'use_category'], 'RESIDENTIAL'], ...USE_COLORS.filter(([, c]) => c).flatMap(([key, color]) => [key, color]), MISSING_FILL]; }

export function isBasemapError(event: { sourceId?: string; error?: { message?: string } }) { return event.sourceId === 'basemap' || !!event.error?.message?.includes('tile.openstreetmap.org'); }
export function selectedFilter(id: string | number | undefined): maplibregl.FilterSpecification { return ['==', ['to-string', ['coalesce', ['get', 'grid_id'], ['get', 'id']]], String(id ?? '')]; }
/** Equal-interval load-ramp color up to ``max`` with an explicit missing branch (callers without a classification). */
export function metricColor(metric: string, max = 50000): maplibregl.ExpressionSpecification { return ['case', ['==', ['get', metric], null], MISSING_FILL, ['interpolate', ['linear'], ['to-number', ['get', metric]], 0, TOKENS['load-1'], Math.max(max, 1) / 2, TOKENS['load-3'], Math.max(max, 1), TOKENS['load-5']]]; }
function fitToData(map: maplibregl.Map, collection: GeoJSON.FeatureCollection, maxZoom = 13, animate = false) {
  const bounds = new maplibregl.LngLatBounds();
  const visit = (v: unknown) => { if (Array.isArray(v) && typeof v[0] === 'number' && typeof v[1] === 'number') bounds.extend(v as [number, number]); else if (Array.isArray(v)) v.forEach(visit); };
  collection.features.forEach((f) => visit((f.geometry as { coordinates: unknown }).coordinates));
  const reduce = typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
  const wide = map.getContainer().clientWidth > 760;
  // 선택 확대만 300ms ease-out 애니메이션(DESIGN.md 8), reduced-motion이면 즉시.
  if (!bounds.isEmpty()) map.fitBounds(bounds, { padding: { top: 60, bottom: 40, left: wide ? 320 : 30, right: 40 }, maxZoom, duration: animate && !reduce ? 300 : 0, easing: (t) => 1 - (1 - t) * (1 - t) });
}
/** 용도지역 대분류 면 색 (범례·구성비 막대·세부 명칭이 없을 때의 외곽선 색). */
export function zoneColor(): maplibregl.ExpressionSpecification { return ['match', ['get', 'category'], ...ZONE_LEGEND.slice(0, 4).flatMap(([key, , color]) => [key, color]), ZONE_LEGEND[4][2]] as unknown as maplibregl.ExpressionSpecification; }
/** 용도지역 외곽선 색: 세부 명칭(제2종일반주거 등) → 토큰, 없으면 대분류 색. */
export function zoneLineColor(): maplibregl.ExpressionSpecification {
  const cases = ZONE_DETAIL.flatMap(([keyword, token]) => [['in', keyword, ['coalesce', ['get', 'zone_name'], '']], TOKENS[token]]);
  return ['case', ...cases, zoneColor()] as unknown as maplibregl.ExpressionSpecification;
}
/** 행정동 인구밀도: 중립 순차 5단계(등간격, 최대값 기준), 결측은 결측 바탕. */
export function densitySteps(max: number): Array<[number, number]> { const top = Math.max(max, 1); return Array.from({ length: 5 }, (_, i) => [Math.round((top * i) / 5), Math.round((top * (i + 1)) / 5)]); }
export function densityColor(max: number): maplibregl.ExpressionSpecification {
  const steps = densitySteps(max);
  return ['case', ['==', ['get', 'population_density'], null], MISSING_FILL, ['step', ['to-number', ['get', 'population_density']], SEQ_RAMP[0], ...steps.slice(1).flatMap(([from], i) => [from, SEQ_RAMP[i + 1]])]] as unknown as maplibregl.ExpressionSpecification;
}
export function maxOf(collection: GeoJSON.FeatureCollection | undefined, key: string) { const values = (collection?.features ?? []).map((f) => f.properties?.[key]).filter((v): v is number => typeof v === 'number' && Number.isFinite(v)); return values.length ? Math.max(...values) : 0; }
export function statValue(value: unknown, status: unknown, unit: string) { if (typeof value === 'number') return formatMetric(value, unit, 0); return status === 'SUPPRESSED' ? '비공개(*)' : status === 'NOT_COLLECTED' ? '미수집' : '자료 없음'; }
function applyVisibility(map: maplibregl.Map, visible: Record<LayerKey, boolean>) { for (const [key, ids] of Object.entries(LAYER_IDS) as [LayerKey, string[]][]) ids.forEach((id) => { if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', visible[key] ? 'visible' : 'none'); }); }
export function addOverlayLayers(map: maplibregl.Map, data: OverlayData): boolean {
  for (const key of ['zoning', 'admin'] as const) { const source = map.getSource(key) as maplibregl.GeoJSONSource | undefined; if (source) source.setData(data[key]); else map.addSource(key, { type: 'geojson', data: data[key] }); }
  if (map.getLayer('zoning-line')) { map.setPaintProperty('admin-fill', 'fill-color', densityColor(maxOf(data.admin, 'population_density'))); return false; }
  addHatchImage(map);
  // 용도지역은 면 채움이 아니라 외곽선 오버레이(1.5px 원색 + 흰 헤일로) — 지표 램프와 겹치지 않게. 미분류는 해치.
  const before = map.getLayer('hover-grid') ? 'hover-grid' : undefined;
  map.addLayer({ id: 'admin-fill', type: 'fill', source: 'admin', layout: { visibility: 'none' }, paint: { 'fill-color': densityColor(maxOf(data.admin, 'population_density')), 'fill-opacity': 0.7 } }, before);
  map.addLayer({ id: 'admin-line', type: 'line', source: 'admin', layout: { visibility: 'none' }, paint: { 'line-color': TOKENS['seq-5'], 'line-width': 1 } }, before);
  map.addLayer({ id: 'zoning-unknown', type: 'fill', source: 'zoning', filter: ['==', ['coalesce', ['get', 'category'], 'UNKNOWN'], 'UNKNOWN'], layout: { visibility: 'none' }, paint: { 'fill-pattern': HATCH, 'fill-opacity': 0.8 } }, before);
  map.addLayer({ id: 'zoning-halo', type: 'line', source: 'zoning', layout: { visibility: 'none' }, paint: { 'line-color': TOKENS['select-halo'], 'line-width': 3.5 } }, before);
  map.addLayer({ id: 'zoning-line', type: 'line', source: 'zoning', layout: { visibility: 'none' }, paint: { 'line-color': zoneLineColor(), 'line-width': 1.5 } }, before);
  return true;
}
