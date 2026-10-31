import { useEffect, useRef, useState } from 'react';
import { operationLabel, playerHref, type Row } from '../lib/panel';

export type FeedEvent = Row & { type: string; at: number };

/** Human sentence for one activity event. */
export function describe(event: FeedEvent): { text: string; href?: string } {
  const who = String(event.account_name || event.account_id || 'A player');
  const href = typeof event.account_id === 'string' ? playerHref(event.account_id) : undefined;
  if (event.type === 'login') return { text: `${who} logged in`, href };
  if (event.type === 'purchase')
    return {
      text: `${who} ${event.source === 'buy' ? 'bought' : 'received'} ${String(event.item_name || 'an item')}`,
      href,
    };
  if (event.type === 'report')
    return { text: `${who} reported ${String(event.target || 'a player')}`, href: '#moderation' };
  if (event.type === 'staff') {
    const target = String(event.target_name || event.target_id || '');
    return {
      text: `${String(event.actor_id)}: ${operationLabel(event.operation)}${target ? ' — ' + target : ''}`,
      href: event.target_type === 'player' ? playerHref(String(event.target_id)) : '#audit',
    };
  }
  return { text: String(event.type) };
}

/** Polls the server feed; calls onEvents with new events (oldest first). */
export function useLiveFeed(
  api: (path: string) => Promise<any>,
  onEvents: (events: FeedEvent[], online: number) => void,
) {
  const since = useRef<number | null>(null);
  const handler = useRef(onEvents);
  handler.current = onEvents;
  const [connected, setConnected] = useState(true);
  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      try {
        const cursor = since.current ?? Date.now() / 1000 - 1;
        const data = await api('feed?since=' + cursor.toFixed(3));
        if (stopped) return;
        const items = (data.items as FeedEvent[]).filter((e) => e.at > cursor);
        if (since.current !== null && items.length) handler.current(items, Number(data.online));
        else handler.current([], Number(data.online));
        since.current = Math.max(
          cursor,
          ...items.map((e) => e.at),
          since.current === null ? data.server_time : cursor,
        );
        setConnected(true);
      } catch {
        if (!stopped) setConnected(false);
      }
      if (!stopped) timer = setTimeout(tick, document.hidden ? 20000 : 5000);
    };
    void tick();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [api]);
  return connected;
}

export function Toasts({
  toasts,
  dismiss,
}: {
  toasts: (FeedEvent & { id: number })[];
  dismiss: (id: number) => void;
}) {
  return (
    <div
      className="pointer-events-none fixed right-3 bottom-3 z-50 grid w-[min(22rem,calc(100vw-1.5rem))] gap-2"
      aria-live="polite"
    >
      {toasts.map((toast) => {
        const { text, href } = describe(toast);
        return (
          <div
            key={toast.id}
            className="pointer-events-auto flex items-start gap-2 rounded-md border bg-popover p-3 text-sm shadow-lg"
          >
            <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-foreground" aria-hidden />
            {href ? (
              <a
                href={href}
                className="min-w-0 flex-1 hover:underline"
                onClick={() => dismiss(toast.id)}
              >
                {text}
              </a>
            ) : (
              <span className="min-w-0 flex-1">{text}</span>
            )}
            <button
              type="button"
              className="text-xs text-muted-foreground hover:text-foreground"
              onClick={() => dismiss(toast.id)}
              aria-label="Dismiss"
            >
              ✕
            </button>
          </div>
        );
      })}
    </div>
  );
}
