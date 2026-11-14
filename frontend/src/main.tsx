import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import 'maplibre-gl/dist/maplibre-gl.css';
import './styles/tokens.css';
import './styles/base.css';
import './styles/shell.css';
import './styles/components.css';
import './styles/map.css';
import './styles/pages.css';
import './styles/report.css';
import './styles/area.css';
import './styles/guide.css';
import './styles/regions.css';
import './styles/themes.css';
import App from './App';
import { applyUiPrefs, readUiPrefs } from './lib/uiPrefs';

// 첫 그림이 나오기 전에 저장된 화면 설정(테마·보기 방식)을 적용한다(밝은 화면이 잠깐 번쩍이지 않게)
applyUiPrefs(readUiPrefs());

createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>);
