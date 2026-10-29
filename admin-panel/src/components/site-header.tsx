import { SidebarTrigger } from './ui/sidebar';
import { Separator } from './ui/separator';
import { Button } from './ui/button';
import { IconRefresh } from '@tabler/icons-react';
export function SiteHeader({
  title,
  busy,
  refresh,
}: {
  title: string;
  busy: boolean;
  refresh: () => void;
}) {
  return (
    <header className="sticky top-0 z-30 flex min-h-14 bg-background/95 shrink-0 items-center gap-2 border-b px-3 sm:px-4">
      <SidebarTrigger aria-label="Toggle navigation" />
      <Separator orientation="vertical" className="h-5" />
      <h1 className="min-w-0 truncate text-sm font-semibold">{title}</h1>
      <Button
        variant="outline"
        size="sm"
        className="ml-auto min-h-11"
        onClick={refresh}
        disabled={busy}
      >
        <IconRefresh aria-hidden className={busy ? 'animate-spin' : ''} />
        Refresh
      </Button>
    </header>
  );
}
