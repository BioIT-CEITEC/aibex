import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import { HistoryList } from '@/components/History';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { useAppStore, type ChatMessage } from '@/store';

const TOOL_LABELS: Record<string, string> = {
  describe_bundle: 'reading the bundle schema',
  query_data: 'querying the data',
  update_view: 'changing the view',
  undo_view: 'undoing',
  create_widget: 'writing a widget',
};

function ToolLine({ name, status }: { name: string; status: string }) {
  const mark = status === 'running' ? '…' : status === 'ok' ? '✓' : '✕';
  return (
    <li className={cn('flex gap-1.5', status === 'error' && 'text-destructive')}>
      <span className="w-3 text-center">{mark}</span>
      <span>{TOOL_LABELS[name] ?? name}</span>
    </li>
  );
}

function AssistantMessage({ m }: { m: ChatMessage }) {
  const empty = !m.text && !m.error && m.changes.length === 0;
  return (
    <div data-testid="chat-message" data-pending={m.pending ? 'true' : undefined} className="max-w-[95%] self-start">
      <div className="rounded-lg border bg-muted/40 px-3 py-2 text-sm">
        {m.tools.length > 0 && (
          <ul className="mb-1 space-y-0.5 text-xs text-muted-foreground">
            {m.tools.map((t, i) => (
              <ToolLine key={i} name={t.name} status={t.status} />
            ))}
          </ul>
        )}
        {m.changes.map((c) => (
          <p key={c.version} className="text-xs text-emerald-700 dark:text-emerald-400">
            → version {c.version}
            {c.summary ? `: ${c.summary}` : ''}
          </p>
        ))}
        {m.text && <p className="whitespace-pre-wrap break-words">{m.text}</p>}
        {m.error && <p className="whitespace-pre-wrap break-words text-destructive">⚠ {m.error}</p>}
        {empty && m.pending && <p className="animate-pulse text-muted-foreground">Thinking…</p>}
      </div>
    </div>
  );
}

/**
 * Chat panel (T24a): the biologist types a prompt, the backend chat loop streams events back (SSE). Tool steps and
 * applied changes are shown as they happen; `spec` events update the dashboard at once (store.receiveSpec).
 * Errors from the LLM side are shown in the reply bubble and never change the spec.
 */
export function ChatPanel() {
  const chat = useAppStore((s) => s.chat);
  const busy = useAppStore((s) => s.chatBusy);
  const sessionId = useAppStore((s) => s.sessionId);
  const sendChat = useAppStore((s) => s.sendChat);
  const [draft, setDraft] = useState('');
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [chat]);

  const submit = async (e?: FormEvent) => {
    e?.preventDefault();
    const text = draft.trim();
    if (!text || busy || !sessionId) return;
    setDraft('');
    const ok = await sendChat(text);
    // the request itself failed (backend unreachable, 422): give the text back for a retry
    if (!ok) setDraft((d) => d || text);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void submit();
    }
  };

  return (
    <aside className="flex h-[calc(100vh-3.5rem)] w-96 shrink-0 flex-col border-l bg-background sticky top-0">
      <HistoryList />
      <div className="border-b px-3 py-2 text-sm font-medium">Assistant</div>
      <div ref={listRef} className="flex flex-1 flex-col gap-2 overflow-y-auto p-3">
        {chat.length === 0 && (
          <p className="text-sm text-muted-foreground">
            Ask for a change to the dashboard, e.g. “label the top 5 genes” or “only show padj below 0.01”. Every
            change is a new version you can undo.
          </p>
        )}
        {chat.map((m) =>
          m.role === 'user' ? (
            <div
              key={m.id}
              data-testid="chat-user-message"
              className="max-w-[90%] self-end whitespace-pre-wrap break-words rounded-lg bg-primary px-3 py-2 text-sm text-primary-foreground"
            >
              {m.text}
            </div>
          ) : (
            <AssistantMessage key={m.id} m={m} />
          ),
        )}
      </div>
      <form onSubmit={(e) => void submit(e)} className="flex items-end gap-2 border-t p-3">
        <textarea
          data-testid="chat-input"
          aria-label="Message to the assistant"
          className="max-h-40 min-h-[2.25rem] flex-1 resize-none rounded-md border bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
          rows={2}
          maxLength={8000}
          placeholder={sessionId ? 'Describe a change… (Enter to send)' : 'Open a bundle first'}
          value={draft}
          disabled={!sessionId}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
        />
        <Button type="submit" data-testid="chat-send" disabled={busy || !sessionId || !draft.trim()}>
          {busy ? 'Working…' : 'Send'}
        </Button>
      </form>
    </aside>
  );
}
