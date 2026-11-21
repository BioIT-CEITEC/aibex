// App state (zustand): bundles, the current session, its spec/version/history and the error banner.
// The spec is the single source of truth for what the dashboard shows (CLAUDE.md, contract 1); every change goes
// through the backend (patch/undo/redo) and the store takes the returned spec – it never edits the spec locally.
import { create } from 'zustand';
import { api, errorMessage } from '@/lib/api';
import type { BundleInfo, HistoryEntry, PatchOp, Spec, SpecVersion } from '@/lib/types';

export interface AppError {
  message: string;
  /** Re-runs the failed action (shown as "Retry" in the banner). */
  retry?: () => void;
}

interface AppState {
  bundles: BundleInfo[];
  bundleId: string | null;
  sessionId: string | null;
  spec: Spec | null;
  version: number | null;
  history: HistoryEntry[];
  /** True while a session is being created (bootstrap or bundle switch). */
  loading: boolean;
  /** True while a patch/undo/redo request is in flight. */
  busy: boolean;
  error: AppError | null;
  /**
   * Linked selection (T17e): values of `spec.selection.key` selected in any panel. View state, not part of the spec
   * (no new version); cleared when a new session starts.
   */
  selection: string[];

  /** Replace the selection, or toggle `keys` in/out of it (shift/ctrl/cmd-click). */
  select: (keys: string[], mode?: 'replace' | 'toggle') => void;
  /** Load the bundle list and start a session for `requested` (or the first bundle). */
  bootstrap: (requested: string | null) => Promise<void>;
  /** Switch bundle: new session (version 0), URL `?bundle=` updated. */
  selectBundle: (bundleId: string) => Promise<void>;
  /** Apply a JSON Patch as a user change; returns false when the backend rejected it. */
  applyPatch: (patch: PatchOp[], summary?: string) => Promise<boolean>;
  undo: () => Promise<void>;
  redo: () => Promise<void>;
  /** Take a spec/version that arrived from elsewhere (e.g. a chat `spec` event) and refresh the history. */
  receiveSpec: (update: SpecVersion) => Promise<void>;
  setError: (error: AppError | null) => void;
}

// Each bootstrap/selectBundle call gets a number; results of older calls are dropped (StrictMode runs effects
// twice, and a user may switch bundles quickly).
let sessionSeq = 0;

function setBundleParam(bundleId: string) {
  const url = new URL(window.location.href);
  if (url.searchParams.get('bundle') === bundleId) return;
  url.searchParams.set('bundle', bundleId);
  window.history.replaceState(null, '', url);
}

export const useAppStore = create<AppState>()((set, get) => {
  const startSession = async (bundleId: string) => {
    const seq = ++sessionSeq;
    set({ loading: true, error: null, bundleId, selection: [] });
    try {
      const created = await api.createSession(bundleId);
      if (seq !== sessionSeq) return;
      set({
        sessionId: created.session_id,
        spec: created.spec,
        version: created.version,
        history: [{ version: created.version, summary: 'initial view', source: 'init' }],
        loading: false,
      });
      setBundleParam(bundleId);
      void refreshHistory(created.session_id);
    } catch (e) {
      if (seq !== sessionSeq) return;
      set({
        loading: false,
        sessionId: null,
        spec: null,
        version: null,
        history: [],
        error: { message: `Could not open bundle "${bundleId}": ${errorMessage(e)}`, retry: () => void startSession(bundleId) },
      });
    }
  };

  const refreshHistory = async (sid: string) => {
    try {
      const s = await api.getSession(sid);
      if (get().sessionId !== sid) return;
      const current = get().version ?? -1;
      // never let a slow refresh roll the spec back past a newer version
      set(s.version >= current ? { history: s.history, spec: s.spec, version: s.version } : { history: s.history });
    } catch {
      // history is informative; a failed refresh keeps the last known list
    }
  };

  const change = async (label: string, run: (sid: string) => Promise<SpecVersion>): Promise<boolean> => {
    const sid = get().sessionId;
    if (!sid) return false;
    set({ busy: true });
    try {
      const res = await run(sid);
      if (get().sessionId !== sid) return false;
      set({ spec: res.spec, version: res.version, busy: false, error: null });
      void refreshHistory(sid);
      return true;
    } catch (e) {
      set({ busy: false, error: { message: `${label} failed: ${errorMessage(e)}` } });
      return false;
    }
  };

  return {
    bundles: [],
    bundleId: null,
    sessionId: null,
    spec: null,
    version: null,
    history: [],
    loading: true,
    busy: false,
    error: null,
    selection: [],

    select: (keys, mode = 'replace') => {
      const unique = [...new Set(keys)];
      if (mode === 'replace') return set({ selection: unique });
      const current = new Set(get().selection);
      // toggle as a group: if every key is already selected remove them, else add the missing ones
      const allIn = unique.length > 0 && unique.every((k) => current.has(k));
      for (const k of unique) {
        if (allIn) current.delete(k);
        else current.add(k);
      }
      set({ selection: [...current] });
    },

    bootstrap: async (requested) => {
      set({ loading: true, error: null });
      let bundles: BundleInfo[];
      try {
        bundles = await api.bundles();
      } catch (e) {
        set({
          loading: false,
          error: {
            message: `Could not load the bundle list: ${errorMessage(e)}`,
            retry: () => void get().bootstrap(requested),
          },
        });
        return;
      }
      set({ bundles });
      const usable = bundles.filter((b) => !b.error);
      const target = requested ?? usable[0]?.id ?? null;
      if (!target) {
        set({ loading: false, error: { message: 'No bundles found in the data directory (AIBEX_DATA_DIR).' } });
        return;
      }
      await startSession(target);
    },

    selectBundle: async (bundleId) => {
      if (bundleId === get().bundleId && get().sessionId) return;
      await startSession(bundleId);
    },

    applyPatch: (patch, summary) => change('Change', (sid) => api.patch(sid, patch, summary)),
    undo: async () => void (await change('Undo', (sid) => api.undo(sid))),
    redo: async () => void (await change('Redo', (sid) => api.redo(sid))),

    receiveSpec: async ({ spec, version }) => {
      const sid = get().sessionId;
      set({ spec, version });
      if (sid) await refreshHistory(sid);
    },

    setError: (error) => set({ error }),
  };
});
