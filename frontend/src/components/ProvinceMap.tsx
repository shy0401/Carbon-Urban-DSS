import * as maplibregl from 'maplibre-gl';
import { ChevronDown, Layers3, MapPinned, X } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { setBasemapStatus } from '../hooks/useBasemapStatus';
import { useApi } from '../hooks/useApi';
import { formatMetric } from '../lib/format';
import { classify, rangeLabel, stepColor, type Classification } from '../lib/mapMetrics';
import { DEFAULT_PROVINCE_METRIC, PROVINCE_METRICS, rowValue, type ProvinceMetric } from '../lib/provinceMetrics';
import { cellRing } from '../lib/tm5179';
import { LINE_ON_BASEMAP, TOKENS } from '../theme/palette';
import type { ProvinceGrid, ProvinceList, ProvinceSummary } from '../types';
import { LayerGroupTitle, LayerToggle } from './LayerToggle';
import { ErrorState, LoadingState } from './Status';

type Layer = 'cells' | 'sigungu' | 'prepared';
const LAYER_IDS: Record<Layer, string[]> = { cells: ['pv-fill', 'pv-line'], sigungu: ['pv-sgg'], prepared: ['pv-prepared-halo', 'pv-prepared'] };
/** Same test as the detail map: the OSM raster source failed (not our data). */
function isBasemapError(event: { sourceId?: string; error?: { message?: string } }) { return event.sourceId === 'basemap' || !!event.error?.message?.includes('tile.openstreetmap.org'); }
const EMPTY: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features: [] };
const KIND_LABEL: Record<ProvinceSummary['kind'], string> = { PROVINCE: '도', METRO: '특별시·광역시' };

/** Row → map feature: a 500m square (EPSG:5179 lower-left × 500) with every indicator under its field name. */
export function provinceFeatures(grid: ProvinceGrid): GeoJSON.FeatureCollection<GeoJSON.Polygon> {
  const fx = grid.fields.indexOf('x'), fy = grid.fields.indexOf('y');
  return {
    type: 'FeatureCollection',
    features: grid.cells.map((row, i) => {
      const properties: Record<string, number | null> = { i };
      grid.fields.forEach((field, k) => { if (k !== fx && k !== fy) properties[field] = row[k] as number | null; });
      return { type: 'Feature', id: i, geometry: { type: 'Polygon', coordinates: [cellRing(Number(row[fx]) * 500, Number(row[fy]) * 500)] }, properties };
    }),
  };
}

export function cellId(grid: ProvinceGrid, row: Array<number | null>): string {
  return `cell_${Number(row[grid.fields.indexOf('x')]) * 500}_${Number(row[grid.fields.indexOf('y')]) * 500}`;
}

/** Group the 시·도 menu: 도 first, then 특별시·광역시 (server order inside each group). */
export function menuGroups(provinces: ProvinceSummary[]): Array<[ProvinceSummary['kind'], ProvinceSummary[]]> {
  return (['PROVINCE', 'METRO'] as const).map((kind) => [kind, provinces.filter((p) => p.kind === kind && !p.excluded)] as [ProvinceSummary['kind'], ProvinceSummary[]]).filter(([, items]) => items.length);
}

export function ProvinceMap({ provinceCode, onProvince, onOpenRegion, offline }: {
  provinceCode: string; onProvince: (code: string) => void; onOpenRegion: (regionCode: string, gridId: string | null) => void; offline: boolean | null;
}) {
  const list = useApi<ProvinceList>('/map/provinces');
  const grid = useApi<ProvinceGrid>(`/map/province/${provinceCode}`);
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const popup = useRef<maplibregl.Popup | null>(null);
  const [ready, setReady] = useState(0);
  const [metricKey, setMetricKey] = useState(DEFAULT_PROVINCE_METRIC);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [layersOpen, setLayersOpen] = useState(false);
  const [legendOpen, setLegendOpen] = useState(() => typeof window === 'undefined' || window.innerWidth > 720);
  const [visible, setVisible] = useState<Record<Layer, boolean>>({ cells: true, sigungu: true, prepared: true });
  const [basemap, setBasemap] = useState(true);
  const [basemapFailed, setBasemapFailed] = useState(false);
  const [selected, setSelected] = useState<number | null>(null);
  const data = grid.data && grid.data.code === provinceCode ? grid.data : null;
  const metric = PROVINCE_METRICS.find((m) => m.key === metricKey) ?? PROVINCE_METRICS[0];
  const features = useMemo(() => (data ? provinceFeatures(data) : null), [data]);
  const classification = useMemo<Classification>(() => (data ? classify(data.cells.map((row) => rowValue(data.fields, row, metric.key)), metric.breaks, metric.ramp) : { classes: [], lowerBounds: [], valued: 0, missing: 0, min: null, max: null }), [data, metric]);
  const refs = useRef({ data, metric, classification }); refs.current = { data, metric, classification };
  const showBasemap = offline === false && basemap && !basemapFailed;
  const summary = list.data?.provinces.find((p) => p.code === provinceCode);

  useEffect(() => { setSelected(null); }, [provinceCode]);
  useEffect(() => { if (offline !== null) setBasemapStatus(showBasemap ? 'shown' : 'none'); }, [offline, showBasemap]);

  // One map for the page; the 시·도 only swaps the sources.
  useEffect(() => {
    if (!container.current || offline === null) return;
    const withBasemap = !offline && basemap;
    setBasemapFailed(false);
    const map = new maplibregl.Map({
      container: container.current, center: [127.8, 36.3], zoom: 6.4, attributionControl: false,
      style: { version: 8, sources: withBasemap ? { basemap: { type: 'raster', tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'], tileSize: 256, attribution: '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap contributors</a>' } } : {}, layers: [{ id: 'background', type: 'background', paint: { 'background-color': TOKENS.canvas } }, ...(withBasemap ? [{ id: 'basemap', type: 'raster' as const, source: 'basemap', paint: { 'raster-opacity': 0.55, 'raster-saturation': -0.7 } }] : [])] },
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'bottom-right');
    map.addControl(new maplibregl.ScaleControl({ maxWidth: 96, unit: 'metric' }), 'bottom-left');
    map.addControl(new maplibregl.AttributionControl({ compact: true, customAttribution: '격자·통계 SGIS, 단지 K-apt' }), 'bottom-right');
    map.on('error', (e) => { if (isBasemapError(e as { sourceId?: string; error?: { message?: string } })) { setBasemapFailed(true); if (map.getLayer('basemap')) map.removeLayer('basemap'); } });
    map.on('load', () => {
      map.addSource('pv-cells', { type: 'geojson', data: EMPTY, promoteId: 'i' });
      map.addSource('pv-bounds', { type: 'geojson', data: EMPTY });
      map.addLayer({ id: 'pv-fill', type: 'fill', source: 'pv-cells', paint: { 'fill-color': TOKENS['prov-missing-bg'], 'fill-opacity': 0.82 } });
      // 격자선은 확대했을 때만 (도 전체에서는 선이 면을 덮어 복잡해 보임).
      map.addLayer({ id: 'pv-line', type: 'line', source: 'pv-cells', minzoom: 10.5, paint: { 'line-color': withBasemap ? LINE_ON_BASEMAP : TOKENS['line-strong'], 'line-width': 0.5 } });
      map.addLayer({ id: 'pv-sgg', type: 'line', source: 'pv-bounds', paint: { 'line-color': TOKENS['ink-2'], 'line-width': ['interpolate', ['linear'], ['zoom'], 7, 0.6, 11, 1.4] } });
      map.addLayer({ id: 'pv-prepared-halo', type: 'line', source: 'pv-bounds', filter: ['==', ['get', 'prepared'], true], paint: { 'line-color': TOKENS['select-halo'], 'line-width': 5 } });
      map.addLayer({ id: 'pv-prepared', type: 'line', source: 'pv-bounds', filter: ['==', ['get', 'prepared'], true], paint: { 'line-color': TOKENS.primary, 'line-width': 2.5 } });
      map.addLayer({ id: 'pv-hover', type: 'line', source: 'pv-cells', filter: ['==', ['get', 'i'], -1], paint: { 'line-color': TOKENS['select-line'], 'line-width': 1.5 } });
      map.addLayer({ id: 'pv-selected-halo', type: 'line', source: 'pv-cells', filter: ['==', ['get', 'i'], -1], paint: { 'line-color': TOKENS['select-halo'], 'line-width': 4.5 } });
      map.addLayer({ id: 'pv-selected', type: 'line', source: 'pv-cells', filter: ['==', ['get', 'i'], -1], paint: { 'line-color': TOKENS['select-line'], 'line-width': 2.5 } });
      popup.current = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 12, maxWidth: '260px' });
      map.on('mousemove', 'pv-fill', (e) => {
        const p = e.features?.[0]?.properties as Record<string, number | null> | undefined; const current = refs.current;
        if (!p || !current.data) return;
        map.getCanvas().style.cursor = 'pointer';
        map.setFilter('pv-hover', ['==', ['get', 'i'], Number(p.i)]);
        popup.current?.setLngLat(e.lngLat).setHTML(cellTooltip(current.data, Number(p.i), current.metric)).addTo(map);
      });
      map.on('mouseleave', 'pv-fill', () => { map.getCanvas().style.cursor = ''; map.setFilter('pv-hover', ['==', ['get', 'i'], -1]); popup.current?.remove(); });
      map.on('click', 'pv-fill', (e) => { const i = e.features?.[0]?.properties?.i; if (i !== undefined) setSelected(Number(i)); });
      map.on('idle', () => { const el = container.current; if (el && map.getLayer('pv-fill')) el.dataset.renderedFeatures = String(map.queryRenderedFeatures({ layers: ['pv-fill'] }).length); });
      setReady((n) => n + 1);
    });
    mapRef.current = map;
    return () => { popup.current?.remove(); map.remove(); mapRef.current = null; };
  }, [offline, basemap]);

  // 시·도 자료 → 도형
  useEffect(() => {
    const map = mapRef.current; if (!map || !ready || !map.getSource('pv-cells')) return;
    (map.getSource('pv-cells') as maplibregl.GeoJSONSource).setData(features ?? EMPTY);
    const prepared = new Set((data?.regions ?? []).map((r) => r.code));
    const bounds = data ? { ...data.boundaries, features: data.boundaries.features.map((f) => ({ ...f, properties: { ...f.properties, prepared: prepared.has(String(f.properties?.region ?? '')) } })) } : EMPTY;
    (map.getSource('pv-bounds') as maplibregl.GeoJSONSource).setData(bounds);
    if (data?.bbox) map.fitBounds(data.bbox, { padding: { top: 40, bottom: 40, left: map.getContainer().clientWidth > 760 ? 320 : 30, right: 40 }, duration: 0 });
  }, [features, data, ready]);
  useEffect(() => {
    const map = mapRef.current; if (!map?.getLayer('pv-fill')) return;
    map.setPaintProperty('pv-fill', 'fill-color', stepColor(metric.key, classification) as unknown as maplibregl.ExpressionSpecification);
  }, [metric.key, classification, ready]);
  useEffect(() => {
    const map = mapRef.current; if (!map?.getLayer('pv-selected')) return;
    const filter: maplibregl.FilterSpecification = ['==', ['get', 'i'], selected ?? -1];
    map.setFilter('pv-selected', filter); map.setFilter('pv-selected-halo', filter);
  }, [selected, ready]);
  useEffect(() => {
    const map = mapRef.current; if (!map?.getLayer('pv-fill')) return;
    for (const [key, ids] of Object.entries(LAYER_IDS) as [Layer, string[]][]) ids.forEach((id) => map.getLayer(id) && map.setLayoutProperty(id, 'visibility', visible[key] ? 'visible' : 'none'));
  }, [visible, ready]);

  const selectedRow = data && selected !== null ? data.cells[selected] : null;
  return <div className={`province-workspace${selectedRow ? ' has-detail' : ''}`}>
    <nav className="province-menu" aria-label="시·도 선택">
      <header><MapPinned size={16} aria-hidden="true" /><strong>시·도 선택</strong></header>
      {list.loading && !list.data ? <p className="muted">불러오는 중…</p> : list.error ? <ErrorState message={list.error} onRetry={list.reload} /> : menuGroups(list.data?.provinces ?? []).map(([kind, items]) => <div className="province-group" key={kind}>
        <span>{KIND_LABEL[kind]}</span>
        <ul>{items.map((p) => <li key={p.code}><button type="button" className={p.code === provinceCode ? 'active' : ''} aria-current={p.code === provinceCode ? 'true' : undefined} onClick={() => onProvince(p.code)} disabled={!p.cells}>
          <span>{p.name}</span>
          <small>{p.cells ? `${formatMetric(p.cells, '')}격자` : '격자 미수집'}{p.prepared.length ? ` · 분석 ${p.prepared.length}` : ''}</small>
        </button></li>)}</ul>
      </div>)}
      {list.data?.excluded.length ? <p className="province-note">{list.data.excluded.map((e) => e.reason).join(' ')}</p> : null}
    </nav>
    <div className="map-stage">
      <div ref={container} className={`map-canvas${showBasemap ? '' : ' no-basemap'}`} aria-label={`${summary?.name ?? '시·도'} 500m 격자 지도`} />
      {grid.loading && <div className="map-loading" role="status"><LoadingState label={`${summary?.name ?? '시·도'} 500m 격자를 불러오는 중입니다${summary?.cells ? ` (${formatMetric(summary.cells, '')}개)` : ''}. 처음 여는 시·도는 30초 안팎 걸립니다`} /></div>}
      {grid.error && !grid.loading && <div className="map-loading"><ErrorState message={grid.error} onRetry={grid.reload} /></div>}
      <div className="map-rail">
        <div className="province-title"><strong>{summary?.name ?? data?.name ?? ''}</strong><span>500m 격자 {formatMetric(data?.meta.cells ?? summary?.cells ?? null, '개')}</span></div>
        {summary && <div className="province-prepared" aria-label="분석 준비 지역">
          <span>분석 준비 지역</span>
          {summary.prepared.length ? summary.prepared.map((r) => <button key={r.code} type="button" onClick={() => onOpenRegion(r.code, null)} title={`${r.name}: 에너지·탄소·건물·용도지역 상세 (${r.grid_count.toLocaleString('ko-KR')}격자)`}>{r.short_name} 상세 →</button>) : <Link to="/regions">없음 · 전국 지역에서 준비</Link>}
        </div>}
        <div className="metric-picker">
          <button className="metric-trigger" aria-haspopup="listbox" aria-expanded={pickerOpen} onClick={() => setPickerOpen(!pickerOpen)}>
            <span><small>격자 색 (지표 하나)</small><strong>{metric.label}</strong></span><em>{metric.unit}</em><ChevronDown size={16} aria-hidden="true" />
          </button>
          {pickerOpen && <section className="map-metrics map-popover" aria-label="지도 지표">
            <header><strong>전국 공통 지표</strong><small>모든 시·도에 있는 자료</small></header>
            {(['1km', '500m'] as const).map((res) => <div className="metric-group" key={res}><span>{res === '1km' ? '인구·주택 (SGIS, 소속 1km 격자 값)' : '공동주택 (K-apt, 500m 격자 안)'}</span>
              {PROVINCE_METRICS.filter((m) => m.resolution === res).map((m) => <button key={m.key} className={`metric-option${m.key === metric.key ? ' active' : ''}`} aria-pressed={m.key === metric.key} onClick={() => { setMetricKey(m.key); setPickerOpen(false); }}><span>{m.label} <small>{m.unit}</small></span><em>{m.resolution}</em></button>)}
            </div>)}
          </section>}
        </div>
        <section className={`map-legend${legendOpen ? '' : ' collapsed'}`} aria-label="지표 범례">
          <div className="legend-head"><strong>{metric.label}</strong><span className="unit">{metric.unit}</span><button type="button" className="legend-toggle" aria-expanded={legendOpen} onClick={() => setLegendOpen((open) => !open)}>{legendOpen ? '범례 접기' : '범례 펼치기'}</button></div>
          <p className={`resolution-tag res-${metric.resolution}`}>{metric.resolution === '1km' ? '1km 격자 값 (같은 1km 안 500m 격자 4개는 같은 값)' : '500m 격자 안에서 센 값'}</p>
          {classification.classes.length ? <ul className="legend-classes">{classification.classes.map((c, i) => <li key={i}><i style={{ background: c.color }} /><span>{rangeLabel(c, metric.digits, i === classification.classes.length - 1)}</span><em>{c.count.toLocaleString('ko-KR')}격자</em></li>)}</ul> : <p className="map-empty-hint">{data ? '이 시·도에는 이 지표 값이 없습니다.' : '격자를 불러오면 표시합니다.'}</p>}
          {classification.missing > 0 && <div className="legend-missing"><i className="is-missing" /><span>{metric.resolution === '1km' ? '통계 없음·비공개 (0 아님)' : '값 없음 (0 아님)'}</span><em>{classification.missing.toLocaleString('ko-KR')}격자</em></div>}
          <ul className="layer-key" aria-label="선 기호">
            {visible.sigungu && <li><i className="key-line" />시·군·구 경계</li>}
            {visible.prepared && <li><i className="key-line prepared" />분석 준비 지역 (상세 지표 있음){data?.regions.length ? `: ${data.regions.map((r) => r.short_name).join(', ')}` : ': 없음'}</li>}
          </ul>
          <details className="legend-def"><summary>정의·출처·활용</summary><p>{metric.definition}</p><p className="legend-use"><b>활용</b> {metric.use}</p><p className="legend-source">출처: {metric.source}{data ? ` · ${metric.resolution === '1km' ? data.meta.stats_source : data.meta.complex_source}` : ''}</p></details>
        </section>
      </div>
      <div className="map-tools">
        <button className="tool-button" aria-expanded={layersOpen} onClick={() => setLayersOpen(!layersOpen)}><Layers3 size={16} aria-hidden="true" />레이어<b>{Object.values(visible).filter(Boolean).length}</b></button>
        {layersOpen && <section className="map-layers map-popover" aria-label="레이어">
          <LayerGroupTitle title="격자 색" note="지표 하나" />
          <LayerToggle label="500m 격자" hint={`지도 지표: ${metric.label}`} swatch="fill" checked={visible.cells} onChange={(v) => setVisible({ ...visible, cells: v })} />
          <LayerGroupTitle title="경계선" />
          <LayerToggle label="시·군·구 경계" swatch="line" checked={visible.sigungu} onChange={(v) => setVisible({ ...visible, sigungu: v })} />
          <LayerToggle label="분석 준비 지역" hint="에너지·탄소·건물·용도지역 상세 지표가 있는 시·군·구" swatch="prepared" checked={visible.prepared} onChange={(v) => setVisible({ ...visible, prepared: v })} />
          <LayerGroupTitle title="바탕" />
          <LayerToggle label="배경지도 (OpenStreetMap)" swatch="base" checked={basemap && !offline} disabled={!!offline} onChange={setBasemap} hint={offline ? '오프라인 모드: 외부 타일을 요청하지 않음' : basemapFailed ? '연결 실패. 도면지 바탕으로 표시' : undefined} />
        </section>}
      </div>
    </div>
    {selectedRow && data && <CellDetail grid={data} index={selected as number} row={selectedRow} metric={metric} onClose={() => setSelected(null)} onOpenRegion={onOpenRegion} />}
  </div>;
}

function CellDetail({ grid, index, row, metric, onClose, onOpenRegion }: { grid: ProvinceGrid; index: number; row: Array<number | null>; metric: ProvinceMetric; onClose: () => void; onOpenRegion: (regionCode: string, gridId: string | null) => void }) {
  const sgg = grid.sigungu[Number(rowValue(grid.fields, row, 'sgg'))];
  const regionIndex = rowValue(grid.fields, row, 'region');
  const region = regionIndex !== null && regionIndex >= 0 ? grid.regions[regionIndex] : null;
  const id = cellId(grid, row);
  const value = (key: string) => rowValue(grid.fields, row, key);
  return <aside className="map-detail" aria-label="선택 격자 상세">
    <header className="detail-head"><div><h2>{sgg?.name ?? '시·군·구 미상'}</h2><code className="grid-id">{id}</code></div><button type="button" className="icon-link" aria-label="상세 닫기" onClick={onClose}><X size={16} /></button></header>
    <section className="detail-section current-metric" aria-label="지도 지표 값">
      <h3>{metric.label} <small className={`resolution-tag res-${metric.resolution}`}>{metric.resolution}</small></h3>
      <p className="detail-figure">{value(metric.key) === null ? <span className="muted">값 없음 (0 아님)</span> : <>{formatMetric(value(metric.key), '', metric.digits)}<span className="unit">{metric.unit}</span></>}</p>
    </section>
    <section className="detail-section" aria-label="인구와 주택">
      <h3>인구·주택 <small className="resolution-tag res-1km">SGIS {grid.meta.sgis_year ?? ''} 1km 격자</small></h3>
      <dl className="fact-list">
        {PROVINCE_METRICS.filter((m) => m.resolution === '1km').map((m) => <div className="fact" key={m.key}><dt>{m.label}</dt><dd>{value(m.key) === null ? <span className="muted">없음</span> : <>{formatMetric(value(m.key), '', m.digits)}<span className="unit">{m.unit}</span></>}</dd></div>)}
      </dl>
      <p className="muted">이 500m 격자를 품은 1km 격자 전체 값이며 500m로 나누지 않았습니다(500m 통계는 자료신청 대상).</p>
    </section>
    <section className="detail-section" aria-label="공동주택">
      <h3>공동주택 <small className="resolution-tag res-500m">500m 격자 안</small></h3>
      <dl className="fact-list">
        <div className="fact"><dt>K-apt 단지</dt><dd>{formatMetric(value('complexes') ?? 0, '단지')}</dd></div>
        <div className="fact"><dt>평균 사용승인연도</dt><dd>{value('complex_year') === null ? <span className="muted">단지 없음</span> : `${value('complex_year')}년`}</dd></div>
      </dl>
    </section>
    <section className="detail-section" aria-label="분석 상태">
      <h3>에너지·탄소 상세</h3>
      {region ? <>
        <p>{region.short_name}은 분석 준비 지역입니다. 이 격자의 에너지 관측·탄소·건물·용도지역·법적 상한을 시·군·구 상세 지도에서 볼 수 있습니다.</p>
        <button type="button" className="button primary" onClick={() => onOpenRegion(region.code, id)}>{region.short_name} 상세 지도에서 보기</button>
      </> : <>
        <p className="muted">{sgg?.name ?? '이 시·군·구'}는 아직 분석 지역으로 준비하지 않았습니다. 준비하면 에너지·탄소·건물·용도지역 지표를 이 격자까지 봅니다.</p>
        <Link className="button secondary" to="/regions">전국 지역에서 준비하기</Link>
      </>}
    </section>
    <p className="muted small">격자 {index + 1} / {grid.cells.length.toLocaleString('ko-KR')} · SGIS 공식 500m 격자</p>
  </aside>;
}

function escapeHtml(value: unknown): string { return String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] ?? c); }

function cellTooltip(grid: ProvinceGrid, index: number, metric: ProvinceMetric): string {
  const row = grid.cells[index]; if (!row) return '';
  const sgg = grid.sigungu[Number(rowValue(grid.fields, row, 'sgg'))];
  const value = rowValue(grid.fields, row, metric.key);
  const regionIndex = rowValue(grid.fields, row, 'region');
  const region = regionIndex !== null && regionIndex >= 0 ? grid.regions[regionIndex] : null;
  return `<div class="map-tip"><strong>${escapeHtml(sgg?.name ?? '시·군·구 미상')}</strong><span>${escapeHtml(metric.label)} (${metric.resolution})</span><b>${value === null ? '값 없음' : escapeHtml(formatMetric(value, metric.unit, metric.digits))}</b>${region ? `<span>분석 준비 지역 · 눌러서 상세</span>` : ''}</div>`;
}
