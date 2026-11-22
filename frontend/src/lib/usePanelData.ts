// Fetches `POST /sessions/{sid}/panel-data` for one panel. Refetches only when something that can change the data
// changes: the session, the panel's own spec, or the filters (filters reach panels through bundle links, so any
// filter change may matter). Results of outdated requests are dropped.
import { useEffect, useState } from 'react';
import { api, errorMessage } from '@/lib/api';
import type { Filter, Panel, PanelData } from '@/lib/types';

export interface PanelDataState {
  data: PanelData | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
}

interface Result {
  key: string;
  data: PanelData | null;
  error: string | null;
}

export function usePanelData(
  sessionId: string | null,
  panel: Panel,
  filters: Filter[] | undefined,
  /** Sent with the request (and part of the refetch key) only when given – widgets whose SQL uses `$selected`. */
  selection?: string[] | null,
): PanelDataState {
  const [attempt, setAttempt] = useState(0);
  const selectionPart = selection ? `|sel:${JSON.stringify(selection)}` : '';
  const key = sessionId
    ? `${sessionId}|${attempt}|${JSON.stringify(panel)}|${JSON.stringify(filters ?? [])}${selectionPart}`
    : '';
  const [result, setResult] = useState<Result>({ key: '', data: null, error: null });
  const panelId = panel.id;
  // a string, so a new array with the same keys does not refetch
  const selectionJson = selection ? JSON.stringify(selection) : '';

  useEffect(() => {
    if (!sessionId || !key) return;
    let cancelled = false;
    const sel = selectionJson ? (JSON.parse(selectionJson) as string[]) : undefined;
    api.panelData(sessionId, panelId, sel).then(
      (data) => !cancelled && setResult({ key, data, error: null }),
      (e: unknown) => !cancelled && setResult({ key, data: null, error: errorMessage(e) }),
    );
    return () => {
      cancelled = true;
    };
  }, [sessionId, panelId, key, selectionJson]);

  const fresh = result.key === key;
  return {
    // keep showing the previous data while a refetch runs (no flicker on filter changes)
    data: result.data,
    error: fresh ? result.error : null,
    loading: !!key && !fresh,
    reload: () => setAttempt((a) => a + 1),
  };
}
