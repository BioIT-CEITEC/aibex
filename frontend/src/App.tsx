import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';

type Health = { status?: string; llm_provider?: string } | null;

// Scaffold page (T16a). The real dashboard (bundle selector, grid, chat) arrives in T16c/T17*.
export default function App() {
  const [health, setHealth] = useState<Health>(null);
  const [error, setError] = useState<string | null>(null);

  const load = () =>
    fetch('/api/health')
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((h: Health) => {
        setHealth(h);
        setError(null);
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));

  const check = () => {
    setHealth(null);
    setError(null);
    void load();
  };

  useEffect(() => void load(), []);

  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col gap-4 p-8">
      <h1 className="text-2xl font-semibold">Aibex View</h1>
      <p className="text-muted-foreground">
        Assistant for Integrated Bioinformatics EXecution – interactive results dashboard. Frontend scaffold; the
        dashboard is not built yet.
      </p>
      <div className="flex items-center gap-3 rounded-lg border p-4 text-sm" data-testid="backend-status">
        <span className="font-medium">Backend:</span>
        {error ? (
          <span className="text-destructive">unreachable ({error})</span>
        ) : health ? (
          <span>
            {health.status ?? 'ok'} · LLM provider: {health.llm_provider ?? 'unknown'}
          </span>
        ) : (
          <span className="text-muted-foreground">checking…</span>
        )}
        <Button variant="outline" size="sm" className="ml-auto" onClick={check}>
          Retry
        </Button>
      </div>
    </main>
  );
}
