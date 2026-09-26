import * as maplibregl from 'maplibre-gl';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import { Camera, Box, RotateCw } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import type { FeatureCollection } from 'geojson';
import { api } from '../lib/api';
import { buildingHeight, massingFeatures, planBlocks, polygonBounds } from '../lib/massing';
import { TOKENS } from '../theme/palette';
import type { ScenarioInput } from '../types';

interface GridFeature { geojson?: { geometry?: { type: string; coordinates: unknown } } }
interface Buildings extends FeatureCollection { total?: number; truncated?: boolean; source?: string | null }

maplibregl.setWorkerUrl(workerUrl);

const EMPTY: FeatureCollection = { type: 'FeatureCollection', features: [] };

/** 3D concept massing on the selected grid: official building footprints extruded by floor count,
 *  the planned blocks in the plan-A colour. Read-only for analysis values; `onCapture` gets a PNG. */
export function Massing3D({ gridId, input, onCapture, captureLabel = '3D 장면 저장' }: { gridId: string | null; input: ScenarioInput; onCapture?: (dataUrl: string) => void; captureLabel?: string }) {
  const container = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const [ready, setReady] = useState(false);
  const [center, setCenter] = useState<[number, number] | null>(null);
  const [gridGeometry, setGridGeometry] = useState<FeatureCollection>(EMPTY);
  const [buildings, setBuildings] = useState<Buildings>(EMPTY as Buildings);
  const [note, setNote] = useState<string>('격자 정보를 불러오는 중…');
  const [captured, setCaptured] = useState(false);

  // Grid outline and the official buildings around it (one request each per grid).
  useEffect(() => {
    let cancelled = false;
    setCenter(null); setBuildings(EMPTY as Buildings); setGridGeometry(EMPTY);
    if (!gridId) { setNote('지도에서 격자를 고르면 그 격자 위에 3D 배치를 그립니다.'); return; }
    (async () => {
      try {
        const grid = await api<GridFeature>(`/grids/${encodeURIComponent(gridId)}`);
        const geometry = grid.geojson?.geometry;
        const bounds = geometry ? polygonBounds(geometry) : null;
        if (!geometry || !bounds) { if (!cancelled) setNote('격자 도형이 없습니다.'); return; }
        if (cancelled) return;
        setGridGeometry({ type: 'FeatureCollection', features: [{ type: 'Feature', properties: {}, geometry: geometry as never }] });
        setCenter(bounds.center);
        const pad = 0.002;
        const bbox = [bounds.bbox[0] - pad, bounds.bbox[1] - pad, bounds.bbox[2] + pad, bounds.bbox[3] + pad].map((v) => v.toFixed(5)).join(',');
        const found = await api<Buildings>(`/map/buildings?bbox=${bbox}&limit=4000`);
        if (cancelled) return;
        setBuildings(found);
        const known = found.features.filter((f) => typeof f.properties?.above_floors === 'number').length;
        setNote(found.features.length ? `주변 공식 건물 ${found.features.length.toLocaleString('ko-KR')}동 (층수 확인 ${known.toLocaleString('ko-KR')}동, 층당 3m로 표시)${found.truncated ? ', 큰 건물만 표시' : ''}` : '이 범위에 공식 건물 자료가 없어 계획 블록만 표시합니다.');
      } catch (e) { if (!cancelled) setNote(e instanceof Error ? e.message : '건물 자료를 불러오지 못했습니다.'); }
    })();
    return () => { cancelled = true; };
  }, [gridId]);

  // Map: no basemap (works offline), pitched camera, canvas kept for PNG capture.
  useEffect(() => {
    if (!container.current || mapRef.current) return;
    const map = new maplibregl.Map({
      container: container.current, center: [127.148, 35.824], zoom: 15.6, pitch: 58, bearing: -28, attributionControl: false,
      canvasContextAttributes: { preserveDrawingBuffer: true },
      style: { version: 8, sources: {}, layers: [{ id: 'background', type: 'background', paint: { 'background-color': TOKENS.canvas } }] },
    });
    map.addControl(new maplibregl.NavigationControl({ showZoom: true, showCompass: true, visualizePitch: true }), 'top-right');
    map.on('load', () => {
      map.addSource('grid', { type: 'geojson', data: EMPTY });
      map.addSource('buildings', { type: 'geojson', data: EMPTY });
      map.addSource('massing', { type: 'geojson', data: EMPTY });
      map.addLayer({ id: 'grid-fill', type: 'fill', source: 'grid', paint: { 'fill-color': TOKENS.surface, 'fill-opacity': 0.9 } });
      map.addLayer({ id: 'grid-line', type: 'line', source: 'grid', paint: { 'line-color': TOKENS['select-line'], 'line-width': 2 } });
      map.addLayer({ id: 'buildings-3d', type: 'fill-extrusion', source: 'buildings', paint: {
        'fill-extrusion-color': ['case', ['>', ['coalesce', ['get', 'height'], 0], 0], TOKENS['line-strong'], TOKENS.hatch],
        'fill-extrusion-height': ['coalesce', ['get', 'height'], 0], 'fill-extrusion-base': 0, 'fill-extrusion-opacity': 0.85,
      } });
      map.addLayer({ id: 'site-3d', type: 'fill-extrusion', source: 'massing', filter: ['==', ['get', 'kind'], 'site'], paint: { 'fill-extrusion-color': TOKENS['plan-a'], 'fill-extrusion-height': 0.3, 'fill-extrusion-opacity': 0.25 } });
      map.addLayer({ id: 'blocks-3d', type: 'fill-extrusion', source: 'massing', filter: ['==', ['get', 'kind'], 'block'], paint: { 'fill-extrusion-color': TOKENS['plan-a'], 'fill-extrusion-height': ['get', 'height'], 'fill-extrusion-base': 0, 'fill-extrusion-opacity': 0.92 } });
      setReady(true);
    });
    mapRef.current = map;
    return () => { map.remove(); mapRef.current = null; setReady(false); };
  }, []);

  // Data updates: grid, buildings (height from floors), planned blocks from the form.
  useEffect(() => {
    const map = mapRef.current; if (!map || !ready) return;
    (map.getSource('grid') as maplibregl.GeoJSONSource | undefined)?.setData(gridGeometry);
    const withHeight: FeatureCollection = { type: 'FeatureCollection', features: buildings.features.map((f) => ({ ...f, properties: { ...f.properties, height: buildingHeight(f.properties?.above_floors) } })) };
    (map.getSource('buildings') as maplibregl.GeoJSONSource | undefined)?.setData(withHeight);
    if (center) {
      (map.getSource('massing') as maplibregl.GeoJSONSource | undefined)?.setData(massingFeatures(center, input.site_area, input.building_count, input.footprint_per_building, input.floors));
      map.jumpTo({ center, zoom: 15.6, pitch: 58, bearing: -28 });
    } else {
      (map.getSource('massing') as maplibregl.GeoJSONSource | undefined)?.setData(EMPTY);
    }
    setCaptured(false);
  }, [ready, gridGeometry, buildings, center, input.site_area, input.building_count, input.footprint_per_building, input.floors]);

  const plan = planBlocks(input.site_area, input.building_count, input.footprint_per_building, input.floors);
  const capture = () => {
    const map = mapRef.current; if (!map || !onCapture) return;
    map.once('idle', () => { onCapture(map.getCanvas().toDataURL('image/png')); setCaptured(true); });
    map.triggerRepaint();
  };
  const reset = () => { const map = mapRef.current; if (map && center) map.easeTo({ center, zoom: 15.6, pitch: 58, bearing: -28, duration: 400 }); };

  return <div className="massing-3d" aria-label="3D 개념 배치">
    <div className="massing-3d-head"><strong><Box size={15} aria-hidden="true" /> 3D 개념 배치</strong><span>{plan.rows}×{plan.columns} 배열 · 블록 한 변 {plan.block_side_m.toFixed(0)}m · 높이 {plan.height_m.toFixed(0)}m{plan.fits ? '' : ' · 대지보다 큼(간격 축소 필요)'}</span><div className="massing-3d-actions"><button type="button" className="icon-link" aria-label="시점 초기화" onClick={reset}><RotateCw size={15} /></button>{onCapture && <button type="button" className="button ghost small" onClick={capture} disabled={!center}><Camera size={14} />{captured ? '저장됨' : captureLabel}</button>}</div></div>
    <div ref={container} className="massing-3d-canvas" />
    <small>{note} 계획 블록은 대지 중앙에 같은 크기로 늘어놓은 개념 배치이며 실제 배치안이 아닙니다. 회색은 기존 건물(VWorld 도로명주소 건물), 녹색은 계획안입니다.</small>
  </div>;
}
