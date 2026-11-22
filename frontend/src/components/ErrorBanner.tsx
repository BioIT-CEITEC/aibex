import { Button } from '@/components/ui/button';
import { useAppStore } from '@/store';

/** Error banner (`error-banner`): shown only when something failed; never blocks the rest of the UI. */
export function ErrorBanner() {
  const error = useAppStore((s) => s.error);
  const setError = useAppStore((s) => s.setError);
  if (!error) return null;
  return (
    <div
      role="alert"
      data-testid="error-banner"
      className="flex items-start gap-3 border-b border-destructive/30 bg-destructive/10 px-4 py-2 text-sm text-destructive"
    >
      <span className="flex-1 break-words">{error.message}</span>
      {error.retry && (
        <Button
          variant="outline"
          size="sm"
          data-testid="error-retry"
          onClick={() => {
            const retry = error.retry;
            setError(null);
            retry?.();
          }}
        >
          Retry
        </Button>
      )}
      <Button variant="ghost" size="sm" aria-label="Dismiss error" onClick={() => setError(null)}>
        ✕
      </Button>
    </div>
  );
}
