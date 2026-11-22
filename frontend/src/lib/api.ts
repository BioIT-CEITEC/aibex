// Typed client for the Aibex View REST API (docs/api.md). All paths are relative to `/api`
// (the Vite dev server proxies it to the backend; in production uvicorn serves both).
import type {
  BundleInfo,
  ChatEvent,
  Health,
  PanelData,
  PatchOp,
  SavedView,
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
  views: (bundle: string) => request<SavedView[]>('GET', `/bundles/${enc(bundle)}/views`),
  saveView: (bundle: string, name: string, spec: Spec, title?: string) =>
    request<{ name: string }>('POST', `/bundles/${enc(bundle)}/views`, title ? { name, spec, title } : { name, spec }),
  loadView: (sid: string, name: string) => request<SpecVersion>('POST', `/sessions/${enc(sid)}/load-view`, { name }),
  panelData: (sid: string, panelId: string, selection?: string[]) =>
    request<PanelData>(
      'POST',
      `/sessions/${enc(sid)}/panel-data`,
      selection ? { panel_id: panelId, selection } : { panel_id: panelId },
    ),
};

const CHAT_EVENT_TYPES = new Set(['token', 'tool', 'spec', 'error', 'done']);

/** Parse one SSE frame (`event: <type>\ndata: <json>`); unknown or malformed frames give null. */
export function parseSseFrame(frame: string): ChatEvent | null {
  let type = 'message';
  const data: string[] = [];
  for (const line of frame.split('\n')) {
    if (line.startsWith('event:')) type = line.slice(6).trim();
    else if (line.startsWith('data:')) data.push(line.slice(5).replace(/^ /, ''));
  }
  if (!CHAT_EVENT_TYPES.has(type)) return null;
  let payload: unknown = {};
  if (data.length) {
    try {
      payload = JSON.parse(data.join('\n'));
    } catch {
      return null;
    }
  }
  if (!payload || typeof payload !== 'object') return null;
  return { ...(payload as object), type } as ChatEvent;
}

/**
 * `POST /sessions/{sid}/chat` as an SSE stream: calls `onEvent` for every event as it arrives. Resolves when the
 * stream ends; throws `ApiError` for HTTP errors (e.g. 422 for an empty/too long message) or a lost connection.
 */
export async function chatStream(
  sid: string,
  message: string,
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`/api/sessions/${enc(sid)}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify({ message }),
      signal,
    });
  } catch (e) {
    throw new ApiError(0, `backend unreachable (${e instanceof Error ? e.message : String(e)})`);
  }
  if (!res.ok || !res.body) {
    const data: unknown = await res.json().catch(() => null);
    const { message: msg, errors } = detailMessage(data);
    throw new ApiError(res.status, msg ?? `chat failed: HTTP ${res.status}`, errors);
  }
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value.replace(/\r\n/g, '\n');
    let cut: number;
    while ((cut = buffer.indexOf('\n\n')) >= 0) {
      const event = parseSseFrame(buffer.slice(0, cut));
      buffer = buffer.slice(cut + 2);
      if (event) onEvent(event);
    }
  }
  const tail = buffer.trim() ? parseSseFrame(buffer) : null;
  if (tail) onEvent(tail);
}

export function errorMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}
