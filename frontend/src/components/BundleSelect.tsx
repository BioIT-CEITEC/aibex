import { useAppStore } from '@/store';

/** Bundle selector (`bundle-select`). Switching creates a new session (version 0) and updates `?bundle=`. */
export function BundleSelect() {
  const bundles = useAppStore((s) => s.bundles);
  const bundleId = useAppStore((s) => s.bundleId);
  const selectBundle = useAppStore((s) => s.selectBundle);
  const loading = useAppStore((s) => s.loading);

  return (
    <label className="flex items-center gap-2 text-sm">
      <span className="text-muted-foreground">Bundle</span>
      <select
        data-testid="bundle-select"
        className="h-8 rounded-md border bg-background px-2 text-sm"
        value={bundleId ?? ''}
        disabled={loading && bundles.length === 0}
        onChange={(e) => void selectBundle(e.target.value)}
      >
        {bundleId && !bundles.some((b) => b.id === bundleId) && <option value={bundleId}>{bundleId}</option>}
        {bundles.map((b) => (
          <option key={b.id} value={b.id} disabled={Boolean(b.error)} title={b.error}>
            {b.title ? `${b.title} (${b.id})` : b.id}
            {b.error ? ' – broken' : ''}
          </option>
        ))}
      </select>
    </label>
  );
}
