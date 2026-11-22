import path from 'node:path';
import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';
import { widgetRuntimePlugin } from './widget-runtime-plugin.ts';

// Dev server on 5173 proxies /api to the FastAPI backend on 8000 (see Makefile `dev`).
// The production build goes to dist/, which the backend serves at / (Settings.frontend_dist).
export default defineConfig({
  // widgetRuntimePlugin: the sandboxed Level 2 widget runtime as an inlinable string (T41a)
  plugins: [react(), tailwindcss(), widgetRuntimePlugin()],
  resolve: {
    alias: { '@': path.resolve(import.meta.dirname, 'src') },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
});
