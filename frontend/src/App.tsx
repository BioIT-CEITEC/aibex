import { useEffect } from 'react';
import { BundleSelect } from '@/components/BundleSelect';
import { Dashboard } from '@/components/Dashboard';
import { ErrorBanner } from '@/components/ErrorBanner';
import { FiltersBar } from '@/components/FiltersBar';
import { useAppStore } from '@/store';

// App shell (T16c): header with bundle selector and spec version, error banner, session bootstrap from `?bundle=`.
// The main area is the panel grid (T17a); chat (T24a) and history/undo (T24b) plug in next to it.
export default function App() {
  const bootstrap = useAppStore((s) => s.bootstrap);
  const spec = useAppStore((s) => s.spec);
  const version = useAppStore((s) => s.version);
  const loading = useAppStore((s) => s.loading);

  useEffect(() => {
    void bootstrap(new URLSearchParams(window.location.search).get('bundle'));
  }, [bootstrap]);

  return (
    <div className="flex min-h-screen flex-col">
      <header className="flex items-center gap-4 border-b px-4 py-2">
        <h1 className="text-lg font-semibold">Aibex View</h1>
        <span className="truncate text-sm text-muted-foreground">{spec?.title}</span>
        <div className="ml-auto flex items-center gap-4">
          <BundleSelect />
          <span className="text-sm text-muted-foreground">
            version <span data-testid="spec-version">{version ?? '–'}</span>
          </span>
        </div>
      </header>
      <ErrorBanner />
      <main className="flex-1 p-4">
        {loading && !spec ? (
          <p className="text-sm text-muted-foreground">Opening bundle…</p>
        ) : spec ? (
          <>
            <FiltersBar filters={spec.filters ?? []} />
            <Dashboard spec={spec} />
          </>
        ) : null}
      </main>
    </div>
  );
}
