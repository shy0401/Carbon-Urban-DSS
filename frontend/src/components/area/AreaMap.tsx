import * as maplibregl from 'maplibre-gl';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import { useEffect, useRef, useState } from 'react';
import { api } from '../../lib/api';
import { COHORT_COLOR, complexFeatures, draftFeature, type AreaAnalysis, type AreaMode } from '../../lib/area';
import { TOKENS } from '../../theme/palette';

maplibregl.setWorkerUrl(workerUrl);

const EMPTY: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features: [] };

/** Display-only circle outline for the radius being chosen (the server builds its own geometry). */
export function circleOutline(center: [number, number], radius: number, steps = 64): GeoJSON.FeatureCollection {
  const [lon, lat] = center;
  const dLat = radius / 111_320;
  const dLon = radius / (111_320 * Math.cos((lat * Math.PI) / 180));
  const ring = Array.from({ length: steps + 1 }, (_, i) => { const a = (i / steps) * 2 * Math.PI; return [lon + dLon * Math.cos(a), lat + dLat * Math.sin(a)]; });
  return { type: 'FeatureCollection', features: [{ type: 'Feature', geometry: { type: 'Polygon', coordinates: [ring] }, properties: {} }] };
}

function fit(map: maplibregl.Map, collection: GeoJSON.FeatureCollection | GeoJSON.Geometry | null | undefined, maxZoom = 15) {
  if (!collection) return;
  const bounds = new maplibregl.LngLatBounds();
  const visit = (v: unknown) => { if (Array.isArray(v) && typeof v[0] === 'number' && typeof v[1] === 'number') bounds.extend(v as [number, number]); else if (Array.isArray(v)) v.forEach(visit); };
  if ('features' in collection) collection.features.forEach((f) => f.geometry && visit((f.geometry as { coordinates: unknown }).coordinates));
  else visit((collection as { coordinates?: unknown }).coordinates);
  if (!bounds.isEmpty()) map.fitBounds(bounds, { padding: 40, maxZoom, duration: 0 });
}

/**
 * 지역 선택·개발 시점 지도. 행정동 경계는 맥락, 분석 구역 외곽선, 구역 격자(점선), 단지 원(연도 슬라이더에 따라 준공 전은 빈 원).
 * 클릭: 행정동 방식이면 그 동 선택, 반경 방식이면 중심점, 그리기 방식이면 꼭짓점 추가.
 */
export function AreaMap({ adminGeojson, mode, adminCode, center, radius, vertices, analysis, sliderYear, eventYear, onPickAdmin, onPickPoint }: {
  adminGeojson: GeoJSON.FeatureCollection;
  mode: AreaMode;
  adminCode: string;
  center: [number, number] | null;
  radius: number;
  vertices: Array<[number, number]>;
  analysis: AreaAnalysis | null;
  sliderYear: number;
  eventYear: number | null;
  onPickAdmin: (code: string) => void;
  onPickPoint: (lngLat: [number, number]) => void;
}) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const [ready, setReady] = useState(0);
  const [offline, setOffline] = useState<boolean | null>(null);
  const [mapError, setMapError] = useState<string | null>(null);
  const handlers = useRef({ mode, onPickAdmin, onPickPoint });
  handlers.current = { mode, onPickAdmin, onPickPoint };

  useEffect(() => { api<{ offline_mode: boolean }>('/system').then((s) => setOffline(s.offline_mode)).catch(() => setOffline(true)); }, []);

  useEffect(() => {
    if (!container.current || offline === null) return;
    const withBasemap = !offline;
    const map = new maplibregl.Map({
      container: container.current, center: [127.13, 35.83], zoom: 11, attributionControl: false,
      style: { version: 8, sources: withBasemap ? { basemap: { type: 'raster', tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'], tileSize: 256, attribution: '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap contributors</a>' } } : {}, layers: [{ id: 'background', type: 'background', paint: { 'background-color': TOKENS.canvas } }, ...(withBasemap ? [{ id: 'basemap', type: 'raster' as const, source: 'basemap', paint: { 'raster-opacity': 0.5, 'raster-saturation': -0.7 } }] : [])] },
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'bottom-right');
    map.addControl(new maplibregl.ScaleControl({ maxWidth: 96, unit: 'metric' }), 'bottom-left');
    map.addControl(new maplibregl.AttributionControl({ compact: true, customAttribution: '경계 SGIS, 단지 K-apt, 지표 Carbon Urban DSS' }), 'bottom-right');
    map.on('error', (e) => {
      if ((e as { sourceId?: string }).sourceId === 'basemap' || String((e as { error?: { message?: string } }).error?.message ?? '').includes('tile.openstreetmap.org')) {
        if (map.getLayer('basemap')) map.removeLayer('basemap');
        if (map.getSource('basemap')) map.removeSource('basemap');
      } else setMapError('지도 도형을 불러오지 못했습니다.');
    });
    map.on('load', () => {
      for (const id of ['admin', 'area', 'grids', 'complexes', 'draft', 'circle']) map.addSource(id, { type: 'geojson', data: id === 'admin' ? adminGeojson : EMPTY });
      map.addLayer({ id: 'admin-fill', type: 'fill', source: 'admin', paint: { 'fill-color': TOKENS.primary, 'fill-opacity': ['case', ['==', ['get', 'adm_code'], ''], 0.12, 0] } });
      map.addLayer({ id: 'admin-line', type: 'line', source: 'admin', paint: { 'line-color': withBasemap ? TOKENS['ink-3'] : TOKENS['line-strong'], 'line-width': 0.8 } });
      map.addLayer({ id: 'area-fill', type: 'fill', source: 'area', paint: { 'fill-color': TOKENS.primary, 'fill-opacity': 0.08 } });
      map.addLayer({ id: 'grids-line', type: 'line', source: 'grids', paint: { 'line-color': TOKENS.primary, 'line-width': 1, 'line-opacity': 0.55, 'line-dasharray': [2, 2] } });
      map.addLayer({ id: 'area-halo', type: 'line', source: 'area', paint: { 'line-color': TOKENS['select-halo'], 'line-width': 4.5 } });
      map.addLayer({ id: 'area-line', type: 'line', source: 'area', paint: { 'line-color': TOKENS['select-line'], 'line-width': 2 } });
      map.addLayer({ id: 'circle-line', type: 'line', source: 'circle', paint: { 'line-color': TOKENS['select-line'], 'line-width': 1.5, 'line-dasharray': [3, 2] } });
      map.addLayer({ id: 'draft-fill', type: 'fill', source: 'draft', filter: ['==', ['geometry-type'], 'Polygon'], paint: { 'fill-color': TOKENS['plan-a'], 'fill-opacity': 0.1 } });
      map.addLayer({ id: 'draft-line', type: 'line', source: 'draft', filter: ['!=', ['geometry-type'], 'Point'], paint: { 'line-color': TOKENS['select-line'], 'line-width': 1.5, 'line-dasharray': [3, 2] } });
      map.addLayer({ id: 'draft-point', type: 'circle', source: 'draft', filter: ['==', ['geometry-type'], 'Point'], paint: { 'circle-radius': 4, 'circle-color': TOKENS.surface, 'circle-stroke-color': TOKENS['select-line'], 'circle-stroke-width': 1.5 } });
      const built = ['!=', ['get', 'state'], 'future'];
      map.addLayer({
        id: 'complexes-circle', type: 'circle', source: 'complexes',
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 11, ['max', 3, ['/', ['sqrt', ['coalesce', ['get', 'households'], 1]], 5]], 16, ['max', 6, ['/', ['sqrt', ['coalesce', ['get', 'households'], 1]], 1.8]]],
          'circle-color': ['match', ['get', 'state'], 'before', COHORT_COLOR.before, 'event', COHORT_COLOR.event, 'after', COHORT_COLOR.after, 'future', 'rgba(0,0,0,0)', TOKENS['prov-missing-bg']],
          'circle-opacity': ['case', built, 0.9, 1],
          'circle-stroke-color': ['case', ['get', 'just_built'], TOKENS['select-line'], ['==', ['get', 'state'], 'future'], TOKENS['ink-3'], ['==', ['get', 'state'], 'unknown'], TOKENS['ink-3'], TOKENS.surface],
          'circle-stroke-width': ['case', ['get', 'just_built'], 2.5, ['==', ['get', 'state'], 'future'], 1, 1],
          'circle-stroke-opacity': ['case', ['==', ['get', 'state'], 'future'], 0.55, 1],
        } as unknown as maplibregl.CircleLayerSpecification['paint'],
      });
      fit(map, adminGeojson, 12);
      const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 10, maxWidth: '260px' });
      map.on('mousemove', 'complexes-circle', (e) => {
        const p = e.features?.[0]?.properties; if (!p) return;
        map.getCanvas().style.cursor = 'pointer';
        const state = p.state === 'future' ? '아직 준공 전' : p.approval_year ? `${p.approval_year}년 사용승인` : '승인일 미상';
        popup.setLngLat(e.lngLat).setHTML(`<strong>${escapeHtml(String(p.name ?? ''))}</strong><br>${state} · ${Number(p.households ?? 0).toLocaleString('ko-KR')}세대`).addTo(map);
      });
      map.on('mouseleave', 'complexes-circle', () => { map.getCanvas().style.cursor = ''; popup.remove(); });
      // 행정동 방식에서는 동 이름을 따라다니는 이름표로 보여 준다(글꼴 타일 없이).
      map.on('mousemove', 'admin-fill', (e) => {
        if (handlers.current.mode !== 'admin' || map.queryRenderedFeatures(e.point, { layers: ['complexes-circle'] }).length) return;
        const p = e.features?.[0]?.properties; if (!p) return;
        map.getCanvas().style.cursor = 'pointer';
        const pop = typeof p.population === 'number' ? ` · 인구 ${Number(p.population).toLocaleString('ko-KR')}명` : '';
        popup.setLngLat(e.lngLat).setHTML(`<strong>${escapeHtml(String(p.name ?? ''))}</strong>${pop}<br><small>눌러서 이 동을 분석</small>`).addTo(map);
      });
      map.on('mouseleave', 'admin-fill', () => { if (handlers.current.mode === 'admin') { map.getCanvas().style.cursor = ''; popup.remove(); } });
      map.on('click', (e) => {
        const h = handlers.current;
        if (h.mode === 'admin') {
          const hit = map.queryRenderedFeatures(e.point, { layers: ['admin-fill'] })[0];
          const code = hit?.properties?.adm_code; if (code) h.onPickAdmin(String(code));
        } else if (h.mode === 'circle' || h.mode === 'polygon') h.onPickPoint([e.lngLat.lng, e.lngLat.lat]);
      });
      setReady((n) => n + 1);
    });
    mapRef.current = map;
    return () => { map.remove(); mapRef.current = null; };
  }, [offline, adminGeojson]);

  // Selected dong highlight (admin mode only)
  useEffect(() => {
    const m = mapRef.current; if (!m?.getLayer('admin-fill')) return;
    m.setPaintProperty('admin-fill', 'fill-opacity', ['case', ['==', ['get', 'adm_code'], mode === 'admin' ? adminCode : '__none__'], 0.12, 0.001]);
    m.getCanvas().style.cursor = mode === 'circle' || mode === 'polygon' ? 'crosshair' : '';
  }, [adminCode, mode, ready]);

  useEffect(() => {
    const m = mapRef.current; if (!m?.getSource('circle')) return;
    (m.getSource('circle') as maplibregl.GeoJSONSource).setData(mode === 'circle' && center ? circleOutline(center, radius) : EMPTY);
    (m.getSource('draft') as maplibregl.GeoJSONSource).setData(mode === 'polygon' ? draftFeature(vertices) : EMPTY);
  }, [mode, center, radius, vertices, ready]);

  useEffect(() => {
    const m = mapRef.current; if (!m?.getSource('area')) return;
    const geometry = analysis?.history.area.geometry;
    (m.getSource('area') as maplibregl.GeoJSONSource).setData(geometry ? { type: 'FeatureCollection', features: [{ type: 'Feature', geometry, properties: {} }] } : EMPTY);
    (m.getSource('grids') as maplibregl.GeoJSONSource).setData(analysis?.grid_features ?? EMPTY);
    if (geometry) fit(m, geometry);
    else if (analysis?.grid_features.features.length) fit(m, analysis.grid_features);
  }, [analysis, ready]);

  useEffect(() => {
    const m = mapRef.current; if (!m?.getSource('complexes')) return;
    (m.getSource('complexes') as maplibregl.GeoJSONSource).setData(analysis ? complexFeatures(analysis.history.complexes, sliderYear, eventYear) : EMPTY);
  }, [analysis, sliderYear, eventYear, ready]);

  return <div className="area-map" data-testid="area-map">
    <div ref={container} className="map-canvas" />
    {mapError && <div className="area-map-error" role="alert">{mapError}</div>}
    <ol className="area-map-legend" aria-label="단지 범례">
      <li><i style={{ background: COHORT_COLOR.before }} />기존 단지</li>
      <li><i style={{ background: COHORT_COLOR.event }} />개발 연도 단지</li>
      <li><i style={{ background: COHORT_COLOR.after }} />이후 단지</li>
      <li><i className="hollow" />슬라이더 연도에 아직 준공 전</li>
      <li><i className="ring" />그 해 준공</li>
      <li><i className="dash" />분석 구역 격자</li>
    </ol>
  </div>;
}

function escapeHtml(text: string) { return text.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] as string); }

