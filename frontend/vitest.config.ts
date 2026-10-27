import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    css: true,
    // 2026-10-27: on the PC under bulk collection the jsdom workers took minutes to start and 11 test files never ran
    // ('Timeout waiting for worker to respond'). Fewer workers start in time; the suite itself takes ~10 s.
    maxWorkers: 3,
  },
});
