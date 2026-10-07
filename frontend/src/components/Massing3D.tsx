import * as maplibregl from 'maplibre-gl';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import { Box, Camera, Crosshair, Eye, Layers, MapPin, Pause, Play, RotateCw, Sun } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import type { Feature, FeatureCollection, Polygon } from 'geojson';
import { api } from '../lib/api';
import { formatMetric } from '../lib/format';
import { buildingHeight, HEIGHT_CLASS_LABELS, heightClass, massingFeatures, outerRings, planBlocks, polygonBounds, ringCentroid, type BlockShape } from '../lib/massing';
import { kst, pointInRing, shadowLength, shadowRing, SUN_DAYS, sunPosition, type SunDay } from '../lib/solar';
import { TOKENS } from '../theme/palette';
import type { ScenarioInput, ZoningCheck } from '../types';
import { districtPlanLabel, zoneBasisLabel, zoneName, zoningSourceNote, zoningTitle, zoningTone } from '../lib/zoning';

maplibregl.setWorkerUrl(workerUrl);

export interface SitePlacement { lon: number; lat: number; rotation: number }
interface GridFeature { geojson?: { geometry?: { type: string; coordinates: unknown } }; properties?: { sgis500_code?: string | null } }
interface Buildings extends FeatureCollection { total?: number; truncated?: boolean; source?: string | null }
type View = 'bird' | 'top' | 'south';
const EMPTY: FeatureCollection = { type: 'FeatureCollection', features: [] };
const SUN_YEAR = 2026;
const HEIGHT_COLORS = [TOKENS.hatch, TOKENS['seq-2'], TOKENS['seq-3'], TOKENS['seq-4'], TOKENS['seq-5']];
const VIEWS: Record<View, { label: string; pitch: number; bearing: number; zoomDelta: number }> = {
  bird: { label: '조감', pitch: 58, bearing: -28, zoomDelta: 0 },
  top: { label: '평면', pitch: 0, bearing: 0, zoomDelta: 0.2 },
  south: { label: '남측 투시', pitch: 72, bearing: 0, zoomDelta: 0.3 },
};

/** 3D concept massing on the selected grid: official buildings extruded by floor count, the planned
 *  blocks on a movable square site, sun shadows for a chosen day and hour, and the 조례 상한 check.
 *  Read-only for analysis values; `onCapture` gets a PNG of the canvas. */
export function Massing3D({ gridId, input, site = null, onSiteChange, onCapture, captureLabel = '3D 장면 저장', captureKey = null, onZoning, region = null }: {
  gridId: string | null; input: ScenarioInput; site?: SitePlacement | null; onSiteChange?: (site: SitePlacement | null) => void;
  onCapture?: (dataUrl: string) => void; captureLabel?: string; captureKey?: string | null; onZoning?: (zoning: ZoningCheck | null) => void;
  /** Study region code: decides the legal-limit basis (전주시 조례 or 국토계획법 시행령). */
  region?: string | null;
}) {
  const container = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const placingRef = useRef(false);
  const siteRef = useRef<SitePlacement | null>(site);
  const onSiteChangeRef = useRef(onSiteChange);
  onSiteChangeRef.current = onSiteChange;
  const [ready, setReady] = useState(false);
  const [gridCenter, setGridCenter] = useState<[number, number] | null>(null);
  const [gridGeometry, setGridGeometry] = useState<FeatureCollection>(EMPTY);
  const [officialCode, setOfficialCode] = useState<string | null>(null);
  const [buildings, setBuildings] = useState<Buildings>(EMPTY as Buildings);
  const [note, setNote] = useState<string>('격자 정보를 불러오는 중…');
  const [captured, setCaptured] = useState(false);
  // A new saved result (captureKey) needs its own scene: the button reads '저장' again.
  useEffect(() => { setCaptured(false); }, [captureKey]);
  const [view, setView] = useState<View>('bird');
  const [spinning, setSpinning] = useState(false);
  const [shape, setShape] = useState<BlockShape>('tower');
  const [spacing, setSpacing] = useState(0.5);
  const [sunDay, setSunDay] = useState<SunDay>('winter');
  const [hour, setHour] = useState(12);
  const [layers, setLayers] = useState({ existing: true, shadows: true, grid: true });
  const [placing, setPlacing] = useState(false);
  const [hover, setHover] = useState<{ x: number; y: number; text: string } | null>(null);
  const [zoning, setZoning] = useState<ZoningCheck | null>(null);
  const [zoningLoading, setZoningLoading] = useState(false);
  placingRef.current = placing;
  siteRef.current = site;

  const center: [number, number] | null = site ? [site.lon, site.lat] : gridCenter;
  const rotation = site?.rotation ?? 0;
  const plan = planBlocks(input.site_area, input.building_count, input.footprint_per_building, input.floors, { shape, spacingRatio: spacing });
  const massing = useMemo(() => center ? massingFeatures(center, input.site_area, input.building_count, input.footprint_per_building, input.floors, { shape, spacingRatio: spacing, rotation }) : null,
    [center?.[0], center?.[1], input.site_area, input.building_count, input.footprint_per_building, input.floors, shape, spacing, rotation]); // eslint-disable-line react-hooks/exhaustive-deps
  const siteRing = massing ? (massing.features[0].geometry.coordinates[0] as number[][]) : null;
  const sun = center ? sunPosition(kst(SUN_YEAR, SUN_DAYS[sunDay].month, SUN_DAYS[sunDay].day, Math.floor(hour), Math.round((hour % 1) * 60)), center[1], center[0]) : null;

  // Existing buildings: height from floors, height class, and whether the site covers them.
  const existing = useMemo(() => {
    const features = buildings.features.map((f) => {
      const height = buildingHeight(f.properties?.above_floors);
      const ring = outerRings(f.geometry as Polygon)[0];
      const inside = !!(siteRing && ring && pointInRing(ringCentroid(ring), siteRing));
      return { ...f, properties: { ...f.properties, height, hclass: heightClass(height), inside: inside ? 1 : 0 } } as Feature;
    });
    return { type: 'FeatureCollection', features } as FeatureCollection;
  }, [buildings, siteRing]);
  const insideCount = existing.features.filter((f) => f.properties?.inside === 1).length;

  // Shadows of the planned blocks (and of existing buildings when shown) for the chosen day and hour.
  const shadows = useMemo(() => {
    if (!sun || !massing || sun.altitude <= 0.5) return { fc: EMPTY, hits: 0 };
    const planned: Feature[] = [];
    for (const block of massing.features.slice(1)) {
      const ring = shadowRing(block.geometry.coordinates[0] as number[][], Number(block.properties?.height) || 0, sun);
      if (ring) planned.push({ type: 'Feature', properties: { kind: 'plan' }, geometry: { type: 'Polygon', coordinates: [ring] } });
    }
    const others: Feature[] = [];
    if (layers.existing) {
      for (const f of existing.features) {
        if (f.properties?.inside === 1) continue;
        for (const ring of outerRings(f.geometry as Polygon)) {
          const shadow = shadowRing(ring, Number(f.properties?.height) || 0, sun);
          if (shadow) others.push({ type: 'Feature', properties: { kind: 'existing' }, geometry: { type: 'Polygon', coordinates: [shadow] } });
        }
      }
    }
    const planRings = planned.map((f) => (f.geometry as Polygon).coordinates[0]);
    const hits = existing.features.filter((f) => {
      if (f.properties?.inside === 1) return false;
      const ring = outerRings(f.geometry as Polygon)[0];
      return ring ? planRings.some((shadow) => pointInRing(ringCentroid(ring), shadow)) : false;
    }).length;
    return { fc: { type: 'FeatureCollection', features: [...others, ...planned] } as FeatureCollection, hits };
  }, [sun?.altitude, sun?.azimuth, massing, existing, layers.existing]); // eslint-disable-line react-hooks/exhaustive-deps

  // Grid outline, official code and the official buildings around it (one request each per grid).
  useEffect(() => {
    let cancelled = false;
    setGridCenter(null); setBuildings(EMPTY as Buildings); setGridGeometry(EMPTY); setOfficialCode(null);
    if (!gridId) { setNote('지도에서 격자를 고르면 그 격자 위에 3D 배치를 그립니다.'); return; }
    setNote('격자 정보를 불러오는 중…');
    (async () => {
      try {
        const detail = await api<{ grid?: GridFeature }>(`/grids/${encodeURIComponent(gridId)}`);
        const geometry = detail.grid?.geojson?.geometry;
        const bounds = geometry ? polygonBounds(geometry) : null;
        if (!geometry || !bounds) { if (!cancelled) setNote('격자 도형이 없습니다.'); return; }
        if (cancelled) return;
        setGridGeometry({ type: 'FeatureCollection', features: [{ type: 'Feature', properties: {}, geometry: geometry as never }] });
        setGridCenter(bounds.center);
        setOfficialCode(detail.grid?.properties?.sgis500_code ?? null);
        const pad = 0.003;
        const bbox = [bounds.bbox[0] - pad, bounds.bbox[1] - pad, bounds.bbox[2] + pad, bounds.bbox[3] + pad].map((v) => v.toFixed(5)).join(',');
        const found = await api<Buildings>(`/map/buildings?bbox=${bbox}&limit=5000`);
        if (cancelled) return;
        setBuildings(found);
        const known = found.features.filter((f) => typeof f.properties?.above_floors === 'number').length;
        setNote(found.features.length ? `주변 공식 건물 ${found.features.length.toLocaleString('ko-KR')}동 (층수 확인 ${known.toLocaleString('ko-KR')}동, 층당 3m)${found.truncated ? ', 큰 건물 위주' : ''}` : '이 범위에 공식 건물 자료가 없어 계획 블록만 표시합니다.');
      } catch (e) { if (!cancelled) setNote(e instanceof Error ? e.message : '건물 자료를 불러오지 못했습니다.'); }
    })();
    return () => { cancelled = true; };
  }, [gridId]);

  // 용도지역·조례 상한 for the site (debounced; the server intersects the square site with VWorld zoning).
  const bcr = plan.coverage_pct;
  const far = plan.far_pct;
  useEffect(() => {
    if (!center) { setZoning(null); onZoning?.(null); return; }
    let cancelled = false;
    setZoningLoading(true);
    const timer = window.setTimeout(async () => {
      try {
        const query = new URLSearchParams({ lon: center[0].toFixed(6), lat: center[1].toFixed(6), site_area: String(input.site_area), rotation: String(rotation), bcr: bcr.toFixed(2), far: far.toFixed(2), households: String(Math.max(0, Math.round(input.households))) });
        if (region) query.set('region', region);
        const next = await api<ZoningCheck>(`/zoning/site?${query}`);
        if (!cancelled) { setZoning(next); onZoning?.(next); }
      } catch { if (!cancelled) { setZoning(null); onZoning?.(null); } }
      finally { if (!cancelled) setZoningLoading(false); }
    }, 350);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [center?.[0], center?.[1], rotation, input.site_area, bcr, far, input.households, region]); // eslint-disable-line react-hooks/exhaustive-deps

  // Map: no basemap (works offline), pitched camera, canvas kept for PNG capture.
  useEffect(() => {
    if (!container.current || mapRef.current) return;
    const map = new maplibregl.Map({
      container: container.current, center: [127.148, 35.824], zoom: 15.8, pitch: 58, bearing: -28, attributionControl: false,
      canvasContextAttributes: { preserveDrawingBuffer: true },
      style: { version: 8, sources: {}, layers: [{ id: 'background', type: 'background', paint: { 'background-color': TOKENS.canvas } }] },
    });
    map.addControl(new maplibregl.NavigationControl({ showZoom: true, showCompass: true, visualizePitch: true }), 'top-right');
    map.addControl(new maplibregl.FullscreenControl({ container: container.current.parentElement ?? undefined }), 'top-right');
    map.addControl(new maplibregl.ScaleControl({ maxWidth: 90, unit: 'metric' }), 'bottom-right');
    map.on('load', () => {
      for (const id of ['grid', 'shadows', 'buildings', 'massing']) map.addSource(id, { type: 'geojson', data: EMPTY });
      map.addLayer({ id: 'grid-fill', type: 'fill', source: 'grid', paint: { 'fill-color': TOKENS.surface, 'fill-opacity': 0.85 } });
      map.addLayer({ id: 'grid-line', type: 'line', source: 'grid', paint: { 'line-color': TOKENS['ink-3'], 'line-width': 1.5, 'line-dasharray': [4, 3] } });
      map.addLayer({ id: 'site-fill', type: 'fill', source: 'massing', filter: ['==', ['get', 'kind'], 'site'], paint: { 'fill-color': TOKENS['gain-1'], 'fill-opacity': 0.9 } });
      map.addLayer({ id: 'shadow-existing', type: 'fill', source: 'shadows', filter: ['==', ['get', 'kind'], 'existing'], paint: { 'fill-color': TOKENS.ink, 'fill-opacity': 0.1 } });
      map.addLayer({ id: 'shadow-plan', type: 'fill', source: 'shadows', filter: ['==', ['get', 'kind'], 'plan'], paint: { 'fill-color': TOKENS['plan-a'], 'fill-opacity': 0.28 } });
      map.addLayer({ id: 'site-line', type: 'line', source: 'massing', filter: ['==', ['get', 'kind'], 'site'], paint: { 'line-color': TOKENS['plan-a'], 'line-width': 2 } });
      map.addLayer({ id: 'buildings-3d', type: 'fill-extrusion', source: 'buildings', paint: {
        'fill-extrusion-color': ['case', ['==', ['get', 'inside'], 1], TOKENS['load-3'], ['match', ['get', 'hclass'], 1, HEIGHT_COLORS[1], 2, HEIGHT_COLORS[2], 3, HEIGHT_COLORS[3], 4, HEIGHT_COLORS[4], HEIGHT_COLORS[0]]],
        'fill-extrusion-height': ['max', ['coalesce', ['get', 'height'], 0], 0.4], 'fill-extrusion-base': 0, 'fill-extrusion-opacity': 0.88, 'fill-extrusion-vertical-gradient': true,
      } });
      map.addLayer({ id: 'blocks-3d', type: 'fill-extrusion', source: 'massing', filter: ['==', ['get', 'kind'], 'block'], paint: { 'fill-extrusion-color': TOKENS['plan-a'], 'fill-extrusion-height': ['get', 'height'], 'fill-extrusion-base': 0, 'fill-extrusion-opacity': 0.95, 'fill-extrusion-vertical-gradient': true } });
      setReady(true);
    });
    // Hover: floors and height of the building under the pointer.
    map.on('mousemove', (event) => {
      const hit = map.queryRenderedFeatures(event.point, { layers: ['blocks-3d', 'buildings-3d'].filter((id) => map.getLayer(id)) })[0];
      map.getCanvas().style.cursor = placingRef.current ? 'crosshair' : hit ? 'pointer' : '';
      if (!hit) { setHover(null); return; }
      const p = hit.properties ?? {};
      const text = hit.layer.id === 'blocks-3d'
        ? `계획 블록 ${p.index ?? ''} · ${p.floors}층 · 높이 ${Number(p.height).toFixed(0)}m`
        : `${p.name || p.use_label || '기존 건물'} · ${typeof p.above_floors === 'number' ? `지상 ${p.above_floors}층 · 약 ${Number(p.height).toFixed(0)}m` : '층수 미상'}${p.inside === 1 ? ' · 대지 안' : ''}`;
      setHover({ x: event.point.x, y: event.point.y, text });
    });
    map.on('mouseout', () => setHover(null));
    // Click in placing mode moves the site centre (keeps the rotation).
    map.on('click', (event) => {
      if (!placingRef.current) return;
      setPlacing(false);
      onSiteChangeRef.current?.({ lon: event.lngLat.lng, lat: event.lngLat.lat, rotation: siteRef.current?.rotation ?? 0 });
    });
    mapRef.current = map;
    return () => { map.remove(); mapRef.current = null; setReady(false); };
  }, []);

  // Data updates.
  useEffect(() => {
    const map = mapRef.current; if (!map || !ready) return;
    (map.getSource('grid') as maplibregl.GeoJSONSource | undefined)?.setData(gridGeometry);
    (map.getSource('buildings') as maplibregl.GeoJSONSource | undefined)?.setData(layers.existing ? existing : EMPTY);
    (map.getSource('massing') as maplibregl.GeoJSONSource | undefined)?.setData(massing ?? EMPTY);
    (map.getSource('shadows') as maplibregl.GeoJSONSource | undefined)?.setData(layers.shadows ? shadows.fc : EMPTY);
    for (const id of ['grid-fill', 'grid-line']) map.setLayoutProperty(id, 'visibility', layers.grid ? 'visible' : 'none');
    if (sun && sun.altitude > 0) map.setLight({ anchor: 'map', position: [1.3, sun.azimuth, Math.min(80, Math.max(10, 90 - sun.altitude))], intensity: 0.45, color: '#ffffff' });
    setCaptured(false);
  }, [ready, gridGeometry, existing, massing, shadows, layers, sun?.azimuth, sun?.altitude]); // eslint-disable-line react-hooks/exhaustive-deps

  // Camera: jump to the site when it (or the grid) changes, ease for view presets.
  useEffect(() => {
    const map = mapRef.current; if (!map || !ready || !center) return;
    const v = VIEWS[view];
    map.jumpTo({ center, zoom: zoomFor(input.site_area) + v.zoomDelta, pitch: v.pitch, bearing: v.bearing });
  }, [ready, gridCenter]); // eslint-disable-line react-hooks/exhaustive-deps
  const applyView = (next: View) => {
    setView(next); setSpinning(false);
    const map = mapRef.current; if (!map || !center) return;
    const v = VIEWS[next];
    map.easeTo({ center, zoom: zoomFor(input.site_area) + v.zoomDelta, pitch: v.pitch, bearing: v.bearing, duration: 600 });
  };
  // Slow orbit around the site while spinning.
  useEffect(() => {
    const map = mapRef.current; if (!map || !spinning) return;
    let frame = 0; let last = performance.now();
    const step = (now: number) => { map.setBearing(map.getBearing() + (now - last) * 0.012); last = now; frame = requestAnimationFrame(step); };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [spinning]);

  const capture = () => {
    const map = mapRef.current; if (!map || !onCapture) return;
    map.once('idle', () => { onCapture(map.getCanvas().toDataURL('image/png')); setCaptured(true); });
    map.triggerRepaint();
  };
  const setRotation = (value: number) => { if (center) onSiteChange?.({ lon: center[0], lat: center[1], rotation: value }); };
  const planShadow = sun ? shadowLength(plan.height_m, sun) : null;
  const check = zoning?.check;
  const tone = (state?: string) => (state === 'OVER' ? 'bad' : state === 'WITHIN' ? 'good' : 'neutral');

  return <div className="massing-3d" aria-label="3D 개념 배치">
    <div className="massing-toolbar" role="toolbar" aria-label="3D 보기 설정">
      <div className="tool-group" role="group" aria-label="시점"><Eye size={14} aria-hidden="true" />{(Object.keys(VIEWS) as View[]).map((key) => <button type="button" key={key} className={view === key ? 'active' : ''} aria-pressed={view === key} onClick={() => applyView(key)}>{VIEWS[key].label}</button>)}<button type="button" aria-pressed={spinning} className={spinning ? 'active' : ''} onClick={() => setSpinning((s) => !s)} title="대지 주위를 천천히 돌기">{spinning ? <Pause size={13} /> : <Play size={13} />}회전</button></div>
      <div className="tool-group" role="group" aria-label="동 형태"><Box size={14} aria-hidden="true" />{([['tower', '탑상형'], ['slab', '판상형']] as const).map(([key, label]) => <button type="button" key={key} className={shape === key ? 'active' : ''} aria-pressed={shape === key} onClick={() => setShape(key)}>{label}</button>)}</div>
      <label className="tool-field"><span>동 간격</span><select value={spacing} onChange={(e) => setSpacing(Number(e.target.value))} aria-label="마주보는 동 간격 (높이 대비)">{[0.25, 0.5, 0.8, 1].map((v) => <option key={v} value={v}>높이 × {v}</option>)}</select></label>
      <label className="tool-field range"><span>배치 방향 {Math.round(rotation)}°</span><input type="range" min={0} max={89} step={1} value={Math.round(rotation)} disabled={!center} onChange={(e) => setRotation(Number(e.target.value))} aria-label="배치 방향 (시계 방향 각도)" /></label>
      <div className="tool-group" role="group" aria-label="대지 위치"><MapPin size={14} aria-hidden="true" /><button type="button" className={placing ? 'active' : ''} aria-pressed={placing} disabled={!center} onClick={() => setPlacing((p) => !p)}>{placing ? '지도에서 클릭…' : '대지 옮기기'}</button><button type="button" disabled={!site} onClick={() => onSiteChange?.(null)} title="격자 중심으로 되돌리기"><Crosshair size={13} />격자 중심</button></div>
    </div>
    <div className="massing-toolbar secondary" role="toolbar" aria-label="일조와 레이어">
      <div className="tool-group" role="group" aria-label="일조 날짜"><Sun size={14} aria-hidden="true" />{(Object.keys(SUN_DAYS) as SunDay[]).map((key) => <button type="button" key={key} className={sunDay === key ? 'active' : ''} aria-pressed={sunDay === key} onClick={() => setSunDay(key)}>{SUN_DAYS[key].label}</button>)}</div>
      <label className="tool-field range wide"><span>시각 {formatHour(hour)}</span><input type="range" min={8} max={17} step={0.5} value={hour} onChange={(e) => setHour(Number(e.target.value))} aria-label="일조 시각 (한국 시간)" /></label>
      <div className="tool-group checks" role="group" aria-label="레이어"><Layers size={14} aria-hidden="true" />{([['existing', '기존 건물'], ['shadows', '그림자'], ['grid', '격자']] as const).map(([key, label]) => <label key={key}><input type="checkbox" checked={layers[key]} onChange={(e) => setLayers((old) => ({ ...old, [key]: e.target.checked }))} />{label}</label>)}</div>
      <div className="massing-3d-actions"><button type="button" className="icon-link" aria-label="시점 초기화" onClick={() => applyView(view)}><RotateCw size={15} /></button>{onCapture && <button type="button" className="button secondary small" onClick={capture} disabled={!center}><Camera size={14} />{captured ? '저장됨' : captureLabel}</button>}</div>
    </div>

    <div className={`massing-stage${placing ? ' placing' : ''}`}>
      <div ref={container} className="massing-3d-canvas" />
      {hover && <div className="massing-tooltip" style={{ left: hover.x + 12, top: hover.y + 12 }} role="status">{hover.text}</div>}
      {placing && <div className="massing-hint" role="status">대지 중심으로 삼을 곳을 지도에서 클릭하세요.</div>}
      <div className="massing-legend" aria-label="범례">
        <span><i style={{ background: TOKENS['plan-a'] }} />계획 블록</span>
        <span><i className="outline" style={{ borderColor: TOKENS['plan-a'], background: TOKENS['gain-1'] }} />대지</span>
        {HEIGHT_COLORS.slice(1).map((color, i) => <span key={color}><i style={{ background: color }} />{HEIGHT_CLASS_LABELS[i + 1]}</span>)}
        <span><i style={{ background: HEIGHT_COLORS[0] }} />{HEIGHT_CLASS_LABELS[0]}</span>
        <span><i style={{ background: TOKENS['load-3'] }} />대지 안 건물</span>
        <span><i style={{ background: TOKENS['plan-a'], opacity: 0.35 }} />계획 그림자</span>
      </div>
    </div>

    <aside className="massing-hud" aria-label="계획 요약">
        <dl>
          <div><dt>대지</dt><dd>{formatMetric(input.site_area, 'm²')} <small>한 변 {plan.site_side_m.toFixed(0)}m</small></dd></div>
          <div className={tone(check?.bcr)}><dt>건폐율</dt><dd>{plan.coverage_pct.toFixed(1)}%{zoning?.bcr_limit != null && <small> / 상한 {zoning.bcr_limit}%</small>}</dd></div>
          <div className={tone(check?.far)}><dt>용적률</dt><dd>{plan.far_pct.toFixed(0)}%{zoning?.far_limit != null && <small> / 상한 {zoning.far_limit}%</small>}</dd></div>
          <div><dt>최고 높이</dt><dd>{plan.height_m.toFixed(0)}m <small>{input.floors}층</small></dd></div>
          <div className={plan.fits ? '' : 'bad'}><dt>배치</dt><dd>{plan.rows}×{plan.columns} · 동 간격 {plan.row_gap_m.toFixed(0)}m{plan.fits ? '' : <small> 대지 초과</small>}</dd></div>
          {insideCount > 0 && <div className="warn"><dt>대지 안 기존 건물</dt><dd>{insideCount}동 <small>철거·이전 전제</small></dd></div>}
          <div><dt>{SUN_DAYS[sunDay].label} {formatHour(hour)}</dt><dd>{sun && sun.altitude > 0.5 ? <>태양 고도 {sun.altitude.toFixed(0)}° · 그림자 {planShadow ? `${planShadow.toFixed(0)}m` : '-'}</> : '해가 지평선 아래'}</dd></div>
          {layers.shadows && sun && sun.altitude > 0.5 && <div className={shadows.hits ? 'warn' : ''}><dt>그림자가 닿는 기존 건물</dt><dd>{shadows.hits}동</dd></div>}
        </dl>
    </aside>
    <div className="massing-zoning" aria-live="polite">
      <strong>{zoningTitle(zoning)}</strong>
      {zoningLoading && !zoning ? <span className="muted">확인 중…</span> : zoning ? <>
        <span className={`status-tag ${zoningTone(check?.label)}`}>{check?.label ?? zoningStatusLabel(zoning.status)}</span>
        <span>{zoning.zones.length ? zoning.zones.slice(0, 3).map((z) => `${zoneName(z)} ${z.share != null ? `${z.share.toFixed(0)}%` : ''}${z.basis === 'DECREE' || z.assumed || z.gap ? ` (${zoneBasisLabel(z)})` : ''}`).join(' · ') : zoning.reason ?? '대지에 겹치는 용도지역 자료가 없습니다'}</span>
        {zoning.bcr_limit != null && zoning.far_limit != null && <span>기본 상한 건폐율 {zoning.bcr_limit}% · 용적률 {zoning.far_limit}%{zoning.mixed ? ' (면적 가중)' : ''}</span>}
        {zoning.special?.greenbelt && <span className="status-tag bad">개발제한구역 {zoning.special.greenbelt.share.toFixed(0)}%</span>}
        {zoning.special?.district_plans?.length ? <span className="status-tag warn">{districtPlanLabel(zoning.special.district_plans[0].name)}</span> : check?.district_plan && <span className="status-tag warn">지구단위계획 대상 규모</span>}
        {zoning.source && <a href={zoning.source.url} target="_blank" rel="noreferrer">{zoning.source.name} ({zoning.rules_kind === 'DECREE' || (!zoning.rules_kind && zoning.basis === 'DECREE') ? zoning.source.articles : `${zoning.source.effective} 시행`})</a>}
      </> : <span className="muted">대지 위치가 정해지면 확인합니다.</span>}
    </div>
    <small className="massing-note">{note}{officialCode ? ` · SGIS 공식 격자 ${officialCode}` : ''}. 계획 블록은 같은 크기로 규칙적으로 늘어놓은 개념 배치이며 실제 배치안이 아닙니다. 동 간격은 마주보는 벽 사이(높이 × 비율, 최소 6m)이고 옆 간격은 그 절반입니다. 그림자는 맑은 날 태양 위치로 그린 개략 그림자이며 지형·주변 지붕은 반영하지 않았습니다. {zoning ? zoningSourceNote(zoning) : '용도지역 상한은 그 지역 도시계획 조례(없으면 국토계획법 시행령)의 기본값으로 1차 확인합니다.'}</small>
  </div>;
}

function zoomFor(siteArea: number) {
  const side = Math.sqrt(Math.max(siteArea, 1));
  return Math.max(14.6, Math.min(17.2, 17.9 - Math.log2(side / 40)));
}
function formatHour(hour: number) { const h = Math.floor(hour); return `${h}:${hour % 1 ? '30' : '00'}`; }
function zoningStatusLabel(status: ZoningCheck['status']) {
  return ({ OK: '확인', PARTIAL_COVERAGE: '용도지역 자료 일부 없음', LIMIT_UNKNOWN: '상한 판단 보류', NO_ZONING: '용도지역 자료 없음', NOT_COLLECTED: '용도지역 미수집' } as const)[status] ?? status;
}
