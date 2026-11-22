import { Button } from '@/components/ui/button';
import { modeOf } from '@/lib/palette';
import { useAppStore } from '@/store';

/** Header button (`theme-toggle`): switches light/dark with a JSON Patch, source `user` – a new, undoable version. */
export function ThemeToggle() {
  const theme = useAppStore((s) => s.spec?.theme);
  const hasSpec = useAppStore((s) => !!s.spec);
  const busy = useAppStore((s) => s.busy || s.chatBusy || !s.sessionId);
  const applyPatch = useAppStore((s) => s.applyPatch);
  const dark = modeOf(theme) === 'dark';

  const toggle = () => {
    const next = !dark;
    const patch = theme
      ? [{ op: 'add' as const, path: '/theme/dark', value: next }]
      : [{ op: 'add' as const, path: '/theme', value: { palette: 'default', dark: next } }];
    void applyPatch(patch, `switch to the ${next ? 'dark' : 'light'} theme`);
  };

  return (
    <Button
      data-testid="theme-toggle"
      variant="outline"
      size="sm"
      aria-pressed={dark}
      title={dark ? 'Switch to the light theme (undoable)' : 'Switch to the dark theme (undoable)'}
      disabled={busy || !hasSpec}
      onClick={toggle}
    >
      {dark ? '☀ Light' : '☾ Dark'}
    </Button>
  );
}
