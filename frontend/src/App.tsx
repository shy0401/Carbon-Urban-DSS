import { BrowserRouter, Route, Routes } from 'react-router-dom';
import { Layout } from './components/Layout';
import { AnalysisPage } from './pages/AnalysisPage';
import { DashboardPage } from './pages/DashboardPage';
import { DataPage } from './pages/DataPage';
import { MapPage } from './pages/MapPage';
import { ModelPage } from './pages/ModelPage';
import { SimulationPage } from './pages/SimulationPage';
import { SourceDetailPage } from './pages/SourceDetailPage';
import { ReportsPage } from './pages/ReportsPage';

export default function App() {
  return <BrowserRouter><Routes><Route element={<Layout />}><Route index element={<DashboardPage />} /><Route path="map" element={<MapPage />} /><Route path="analysis" element={<AnalysisPage />} /><Route path="model" element={<ModelPage />} /><Route path="simulation" element={<SimulationPage />} /><Route path="reports" element={<ReportsPage />} /><Route path="data" element={<DataPage />} /><Route path="data/sources/:id" element={<SourceDetailPage />} /><Route path="*" element={<DashboardPage />} /></Route></Routes></BrowserRouter>;
}
