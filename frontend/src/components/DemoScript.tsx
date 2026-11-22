import { DEMO_PROMPTS } from '@/lib/demoPrompts';
import { useAppStore } from '@/store';

/**
 * Demo-script panel (T52, P5.3): a collapsible list of the demo prompts above the chat. A click sends the prompt as a
 * chat message, exactly as if it had been typed. Disabled while a chat turn runs or before a session exists.
 */
export function DemoScript() {
  const sendChat = useAppStore((s) => s.sendChat);
  const disabled = useAppStore((s) => s.chatBusy || !s.sessionId);

  return (
    <details data-testid="demo-script" className="group border-b text-sm" open>
      <summary className="cursor-pointer select-none px-3 py-2 font-medium marker:text-muted-foreground">
        Demo script <span className="font-normal text-muted-foreground">· click a prompt to send it</span>
      </summary>
      <ol className="space-y-1 px-3 pb-2">
        {DEMO_PROMPTS.map((p, i) => (
          <li key={i}>
            <button
              type="button"
              data-testid={`demo-prompt-${i + 1}`}
              title="Send this prompt to the assistant"
              disabled={disabled}
              onClick={() => void sendChat(p)}
              className="flex w-full gap-2 rounded-md px-2 py-1 text-left text-xs hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <span className="w-3 shrink-0 text-muted-foreground">{i + 1}.</span>
              <span>{p}</span>
            </button>
          </li>
        ))}
      </ol>
    </details>
  );
}
