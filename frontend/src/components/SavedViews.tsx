import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { useAppStore } from '@/store';

/** Kebab-case view name from a free-text title ("Gla editing, v2" → "gla-editing-v2"); "" when nothing usable. */
function viewName(title: string): string {
  const s = title
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 64)
    .replace(/-+$/, '');
  if (!s) return '';
  return /^[a-z]/.test(s) ? s : `view-${s}`.slice(0, 64).replace(/-+$/, '');
}

/**
 * Saved views of the current bundle (T51, P5.2), in the header: a "Views" select loads one as a new, undoable
 * version; "Save view" stores the current spec under a title (file name = kebab-case of the title, saving under an
 * existing name overwrites it).
 */
export function SavedViews() {
  const views = useAppStore((s) => s.views);
  const disabled = useAppStore((s) => s.busy || s.chatBusy || !s.sessionId);
  const loadView = useAppStore((s) => s.loadView);
  const saveView = useAppStore((s) => s.saveView);
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  const name = viewName(title);
  const overwrites = views.some((v) => v.name === name);

  const submit = async () => {
    if (!name || saving) return;
    setSaving(true);
    setError(null);
    const err = await saveView(name, title.trim());
    setSaving(false);
    if (err) return setError(err);
    setOpen(false);
    setTitle('');
    setSaved(name);
    window.setTimeout(() => setSaved((s) => (s === name ? null : s)), 3000);
  };

  return (
    <div className="relative flex items-center gap-1 text-sm">
      <select
        data-testid="view-select"
        className="h-8 max-w-48 rounded-md border bg-background px-2 text-sm"
        value=""
        disabled={disabled || views.length === 0}
        title={views.length ? 'Load a saved view (undoable)' : 'No saved views for this bundle yet'}
        onChange={(e) => {
          if (e.target.value) void loadView(e.target.value);
        }}
      >
        <option value="">{views.length ? `Views (${views.length})…` : 'No saved views'}</option>
        {views.map((v) => (
          <option key={v.name} value={v.name} data-testid="view-option">
            {v.title}
          </option>
        ))}
      </select>
      <Button
        data-testid="save-view-button"
        variant="outline"
        size="sm"
        disabled={disabled}
        title="Save the current view for this bundle"
        onClick={() => {
          setOpen((o) => !o);
          setError(null);
        }}
      >
        Save view
      </Button>
      {saved && (
        <span data-testid="view-saved" className="text-xs text-emerald-700 dark:text-emerald-400">
          saved
        </span>
      )}
      {open && (
        <form
          data-testid="save-view-form"
          className="absolute right-0 top-10 z-50 w-72 space-y-2 rounded-md border bg-background p-3 shadow-lg"
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
        >
          <label className="block text-xs font-medium">
            View title
            <input
              data-testid="view-title-input"
              autoFocus
              className="mt-1 h-8 w-full rounded-md border bg-background px-2 text-sm font-normal"
              placeholder="e.g. Editing overview"
              maxLength={200}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Escape') setOpen(false);
              }}
            />
          </label>
          <p className="text-xs text-muted-foreground">
            {name ? (
              <>
                Saved as <code>{name}</code>
                {overwrites && <span className="text-amber-700 dark:text-amber-400"> (replaces the saved view)</span>}
              </>
            ) : (
              'Type a title with letters or digits.'
            )}
          </p>
          {error && (
            <p data-testid="view-save-error" className="text-xs text-destructive">
              {error}
            </p>
          )}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" size="sm" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button data-testid="view-save-confirm" type="submit" size="sm" disabled={!name || saving}>
              {saving ? 'Saving…' : 'Save'}
            </Button>
          </div>
        </form>
      )}
    </div>
  );
}
