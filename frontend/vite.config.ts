import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  build: {
    // MapLibre (~0.8MB) and ECharts (~1MB) are loaded only by the map/chart screens.
    // They are split into their own lazily loaded vendor chunks; the first screen does not include them.
    chunkSizeWarningLimit: 1100,
    rollupOptions: {
      output: {
        manualChunks: {
          maplibre: ['maplibre-gl'],
          echarts: ['echarts'],
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: { '/api': 'http://localhost:8000' },
  },
});
