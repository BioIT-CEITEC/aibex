// Typed client for the Aibex View REST API (docs/api.md). All paths are relative to `/api`
// (the Vite dev server proxies it to the backend; in production uvicorn serves both).
import type {
  BundleInfo,
  Health,
  PanelData,
  PatchOp,
  SessionCreated,
  SessionState,
  Spec,
  SpecVersion,
} from './types';

/** HTTP error with the backend's readable message (`detail`, or `detail.errors` for 422). */
export class ApiError extends Error {
  readonly status: number;
  readonly errors: string[];

  constructor(status: number, message: string, errors: string[] = []) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.errors = errors;
  }
}

function detailMessage(body: unknown): { message: string | null; errors: string[] } {
  if (!body || typeof body !== 'object' || !('detail' in body)) return { message: null, errors: [] };
  const detail = (body as { detail: unknown }).detail;
  if (typeof detail === 'string') return { message: detail, errors: [] };
  if (detail && typeof detail === 'object' && 'errors' in detail && Array.isArray(detail.errors)) {
    const errors = detail.errors.map((e: unknown) => (typeof e === 'string' ? e : JSON.stringify(e)));
    return { message: errors.join('; '), errors };
  }
  if (Array.isArray(detail)) {
    // FastAPI request validation errors: [{loc, msg, ...}]
    const errors = detail.map((e: { loc?: unknown[]; msg?: string }) =>
      [e.loc?.join('.'), e.msg].filter(Boolean).join(': '),
    );
    return { message: errors.join('; '), errors };
  }
  return { message: JSON.stringify(detail), errors: [] };
}

async function request<T>(method: 'GET' | 'POST', path: string, body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api${path}`, {
      method,
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (e) {
    throw new ApiError(0, `backend unreachable (${e instanceof Error ? e.message : String(e)})`);
  }
  const text = await res.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = null;
    }
  }
  if (!res.ok) {
    const { message, errors } = detailMessage(data);
    throw new ApiError(res.status, message ?? `${method} ${path} failed: HTTP ${res.status}`, errors);
  }
  return data as T;
}

const enc = encodeURIComponent;

export const api = {
  health: () => request<Health>('GET', '/health'),
  bundles: () => request<BundleInfo[]>('GET', '/bundles'),
  defaultView: (bundle: string) => request<Spec>('GET', `/bundles/${enc(bundle)}/default-view`),
  createSession: (bundle: string) => request<SessionCreated>('POST', '/sessions', { bundle }),
  getSession: (sid: string) => request<SessionState>('GET', `/sessions/${enc(sid)}`),
  patch: (sid: string, patch: PatchOp[], summary?: string) =>
    request<SpecVersion>('POST', `/sessions/${enc(sid)}/patch`, summary ? { patch, summary } : { patch }),
  undo: (sid: string, steps = 1) => request<SpecVersion>('POST', `/sessions/${enc(sid)}/undo`, { steps }),
  redo: (sid: string, steps = 1) => request<SpecVersion>('POST', `/sessions/${enc(sid)}/redo`, { steps }),
  panelData: (sid: string, panelId: string, selection?: string[]) =>
    request<PanelData>(
      'POST',
      `/sessions/${enc(sid)}/panel-data`,
      selection ? { panel_id: panelId, selection } : { panel_id: panelId },
    ),
};

export function errorMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}
