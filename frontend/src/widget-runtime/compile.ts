// Compiles Level 2 widget source (TSX/JSX from the LLM) to the CommonJS JavaScript the iframe runtime evaluates
// (`exports.default = Widget`). Runs in the parent with sucrase – a pure source-to-source transform, nothing is executed
// here; the result runs only inside the sandboxed iframe. Loaded lazily together with the srcdoc (see WidgetPanel).
import { transform, type Transform } from 'sucrase';

export type CompileResult = { ok: true; code: string } | { ok: false; error: string };

export function compileWidget(source: string, language: 'tsx' | 'jsx' = 'tsx'): CompileResult {
  const transforms: Transform[] = language === 'jsx' ? ['jsx', 'imports'] : ['typescript', 'jsx', 'imports'];
  try {
    const { code } = transform(source, {
      transforms,
      // classic runtime → `React.createElement`; React is a global in the iframe (and `import React` maps to it)
      jsxRuntime: 'classic',
      production: true,
      filePath: `widget.${language}`,
    });
    return { ok: true, code };
  } catch (e) {
    const message = e instanceof Error ? e.message : String(e);
    return { ok: false, error: `Compile error (${language}): ${message}` };
  }
}
