import { useEffect } from 'react';
import { modeOf } from '@/lib/palette';
import { useAppStore } from '@/store';

/**
 * Keeps `<html class="dark">` in step with the spec's `theme.dark` (T53). The spec is the single source of truth, so
 * a dark dashboard is part of the view: saved with it, undoable, and something the assistant can change on request.
 */
export function useDocumentTheme() {
  const mode = useAppStore((s) => modeOf(s.spec?.theme));
  useEffect(() => {
    document.documentElement.classList.toggle('dark', mode === 'dark');
  }, [mode]);
}
