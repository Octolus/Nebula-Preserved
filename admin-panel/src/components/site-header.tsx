import { SidebarTrigger } from './ui/sidebar';
import { Separator } from './ui/separator';
import { Button } from './ui/button';
import { IconRefresh } from '@tabler/icons-react';
export function SiteHeader({
  title,
  busy,
  refresh,
  search,
  live,
}: {
  title: string;
  busy: boolean;
  refresh: () => void;
  search?: React.ReactNode;
  live?: { connected: boolean; online: number | null };
}) {
  return (
    <header className="sticky top-0 z-30 flex h-12 shrink-0 items-center gap-2 border-b bg-background/95 px-3 backdrop-blur sm:px-4">
      <SidebarTrigger aria-label="Toggle navigation" />
      <Separator orientation="vertical" className="h-5" />
      <h1 className="min-w-0 truncate text-sm font-semibold">{title}</h1>
      <div className="ml-auto" />
      {live && (
        <a
          href="#monitor"
          className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground"
          title={live.connected ? 'Live updates on' : 'Reconnecting…'}
        >
          <span
            className={
              'size-2 rounded-full ' +
              (live.connected ? 'animate-pulse bg-foreground' : 'bg-destructive')
            }
            aria-hidden
          />
          <span className="hidden sm:inline">{live.connected ? 'Live' : 'Offline'}</span>
          {live.online !== null && <span className="tabular-nums">· {live.online} online</span>}
        </a>
      )}
      {search}
      <Button variant="outline" size="sm" onClick={refresh} disabled={busy}>
        <IconRefresh aria-hidden className={busy ? 'animate-spin' : ''} />
        Refresh
      </Button>
    </header>
  );
}
