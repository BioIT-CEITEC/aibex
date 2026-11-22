import { cn } from '@/lib/utils';

/** Small spinning ring for loading states (T50). Decorative; the text next to it says what is loading. */
export function Spinner({ className }: { className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        'inline-block size-3.5 shrink-0 animate-spin rounded-full border-2 border-current border-t-transparent opacity-70',
        className,
      )}
    />
  );
}
