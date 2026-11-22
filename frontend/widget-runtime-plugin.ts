// Vite plugin: `import runtime from 'virtual:aibex-widget-runtime'` gives the widget iframe runtime
// (src/widget-runtime/runtime.tsx + React) as one minified IIFE *string*, to be inlined into the iframe srcdoc.
// React 19 ships no UMD build, so the runtime is bundled here with a nested Vite build (no extra dependency).
import path from 'node:path';
import { build, type Plugin } from 'vite';

const ID = 'virtual:aibex-widget-runtime';
const RESOLVED = '\0' + ID;

export function widgetRuntimePlugin(): Plugin {
  const entry = path.resolve(import.meta.dirname, 'src/widget-runtime/runtime.tsx');
  let cached: string | null = null;

  async function bundle(): Promise<string> {
    const result = await build({
      configFile: false,
      logLevel: 'warn',
      mode: 'production',
      define: { 'process.env.NODE_ENV': '"production"' },
      build: {
        write: false,
        emptyOutDir: false,
        minify: true,
        lib: { entry, formats: ['iife'], name: 'AibexWidgetRuntime', fileName: () => 'runtime.js' },
      },
    });
    const outputs = Array.isArray(result) ? result : [result];
    for (const out of outputs) {
      if (!('output' in out)) continue;
      const chunk = out.output.find((o) => o.type === 'chunk');
      if (chunk && chunk.type === 'chunk') return chunk.code;
    }
    throw new Error('widget runtime build produced no chunk');
  }

  return {
    name: 'aibex-widget-runtime',
    resolveId(id) {
      return id === ID ? RESOLVED : null;
    },
    async load(id) {
      if (id !== RESOLVED) return null;
      this.addWatchFile(entry);
      this.addWatchFile(path.resolve(import.meta.dirname, 'src/widget-runtime/protocol.ts'));
      cached ??= await bundle();
      return `export default ${JSON.stringify(cached)};`;
    },
    watchChange(id) {
      if (id.includes(`${path.sep}widget-runtime${path.sep}`)) cached = null;
    },
    handleHotUpdate({ file, server }) {
      if (!file.includes(`${path.sep}widget-runtime${path.sep}`)) return;
      cached = null;
      const mod = server.moduleGraph.getModuleById(RESOLVED);
      if (mod) server.moduleGraph.invalidateModule(mod);
    },
  };
}
