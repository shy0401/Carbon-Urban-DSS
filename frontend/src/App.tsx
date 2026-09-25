import { lazy, Suspense, type ReactNode } from 'react';
import { BrowserRouter, Route, Routes } from 'react-router-dom';
import { Layout } from './components/Layout';
import { LoadingState } from './components/Status';
import { DashboardPage } from './pages/DashboardPage';

// Heavy pages (MapLibre, ECharts, report tools) load on demand so the first screen stays small.
const MapPage = lazy(() => import('./pages/MapPage').then((module) => ({ default: module.MapPage })));
const AnalysisPage = lazy(() => import('./pages/AnalysisPage').then((module) => ({ default: module.AnalysisPage })));
const ModelPage = lazy(() => import('./pages/ModelPage').then((module) => ({ default: module.ModelPage })));
const AreaPage = lazy(() => import('./pages/AreaPage').then((module) => ({ default: module.AreaPage })));
const GuidePage = lazy(() => import('./pages/GuidePage').then((module) => ({ default: module.GuidePage })));
const SimulationPage = lazy(() => import('./pages/SimulationPage').then((module) => ({ default: module.SimulationPage })));
const ReportsPage = lazy(() => import('./pages/ReportsPage').then((module) => ({ default: module.ReportsPage })));
const DataPage = lazy(() => import('./pages/DataPage').then((module) => ({ default: module.DataPage })));
const SourceDetailPage = lazy(() => import('./pages/SourceDetailPage').then((module) => ({ default: module.SourceDetailPage })));

function Deferred({ children }: { children: ReactNode }) {
  return <Suspense fallback={<div className="page"><LoadingState label="화면을 불러오는 중입니다" /></div>}>{children}</Suspense>;
}

export default function App() {
  return <BrowserRouter><Routes><Route element={<Layout />}><Route index element={<DashboardPage />} /><Route path="map" element={<Deferred><MapPage /></Deferred>} /><Route path="analysis" element={<Deferred><AnalysisPage /></Deferred>} /><Route path="model" element={<Deferred><ModelPage /></Deferred>} /><Route path="area" element={<Deferred><AreaPage /></Deferred>} /><Route path="simulation" element={<Deferred><SimulationPage /></Deferred>} /><Route path="reports" element={<Deferred><ReportsPage /></Deferred>} /><Route path="data" element={<Deferred><DataPage /></Deferred>} /><Route path="data/sources/:id" element={<Deferred><SourceDetailPage /></Deferred>} /><Route path="guide" element={<Deferred><GuidePage /></Deferred>} /><Route path="*" element={<DashboardPage />} /></Route></Routes></BrowserRouter>;
}
