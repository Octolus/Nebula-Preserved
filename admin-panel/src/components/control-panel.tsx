import { useCallback, useEffect, useRef, useState } from 'react';
import { AppSidebar, sections } from './app-sidebar';
import { SiteHeader } from './site-header';
import { ModerationWorkspace } from './moderation-workspace';
import { MonitorWorkspace } from './monitor-workspace';
import { canLinkOperator } from '../lib/moderation';
import { SidebarProvider, SidebarInset } from './ui/sidebar';
import { TooltipProvider } from './ui/tooltip';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from './ui/card';
import { Button } from './ui/button';
import { Input } from './ui/input';
import { Badge } from './ui/badge';
import { RecordList } from './record-list';
import {
  ChangeForm,
  Details,
  PaginatedRecords,
  Pager,
  PlayerPicker,
  Stat,
  empty,
  asList,
  type List,
} from './management-widgets';
import { PlayerAccount } from './player-account';
import { CatalogWorkspace } from './catalog-workspace';
import { StoresWorkspace } from './stores-workspace';
import { PurchaseRecords } from './item-records';
import { Alert, AlertDescription } from './ui/alert';
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from './ui/accordion';
import { panelRoute, playerHref, type Row, type PlayerTab } from '../lib/panel';
import { Toasts, useLiveFeed, type FeedEvent } from './live-feed';

type Api = (path: string, body?: unknown) => Promise<any>;
const truthy = (value: unknown) => value === true || value === 1;
const open = (row: Row) => (window.location.hash = playerHref(String(row.account_id)));

export function StatusBadges({ row }: { row: Row }) {
  return (
    <span className="flex flex-wrap gap-1">
      {truthy(row.online) ? <Badge>Online</Badge> : <Badge variant="outline">Offline</Badge>}
      {truthy(row.banned) && <Badge variant="destructive">Banned</Badge>}
      {truthy(row.muted) && <Badge variant="secondary">Muted</Badge>}
    </span>
  );
}

function Overview({ api, revision }: { api: Api; revision: number }) {
  const [stats, setStats] = useState<Row>({}),
    [caps, setCaps] = useState<Row>({}),
    [online, setOnline] = useState<List>(empty);
  useEffect(() => {
    let current = true;
    Promise.all([api('stats'), api('capabilities'), api('users?status=online&limit=10')])
      .then(([s, c, o]) => {
        if (!current) return;
        setStats(s);
        setCaps(c);
        setOnline(o);
      })
      .catch(() => {});
    return () => {
      current = false;
    };
  }, [api, revision]);
  const n = (value: unknown) => (typeof value === 'number' ? value.toLocaleString() : '—');
  const link = (href: string, label: string) => (
    <a href={href} className="text-xs font-normal text-muted-foreground hover:underline">
      {label} →
    </a>
  );
  return (
    <div className="grid gap-3">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 xl:grid-cols-8">
        <Stat label="Players" value={n(stats.users)} href="#users" />
        <Stat label="Online now" value={n(stats.online)} href="#monitor" />
        <Stat label="Purchases" value={n(stats.purchases)} href="#purchases" />
        <Stat
          label="Banned"
          value={n(stats.banned)}
          href="#moderation"
          tone={Number(stats.banned) ? 'danger' : undefined}
        />
        <Stat label="Muted" value={n(stats.muted)} href="#moderation" />
        <Stat
          label="Open reports"
          value={n(stats.open_reports)}
          href="#moderation"
          tone={Number(stats.open_reports) ? 'danger' : undefined}
        />
        <Stat label="Crystals held" value={n(stats.crystals)} />
        <Stat label="Admin actions" value={n(stats.audit_entries)} href="#audit" />
      </div>
      <div className="grid gap-3 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              Online now <Badge variant="secondary">{online.total}</Badge>
              <span className="ml-auto">{link('#monitor', 'Live monitor')}</span>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <RecordList
              items={online.items}
              columns={['account_id', 'last_login_at', 'crystals', 'np']}
              emptyText="Nobody is online right now."
              onRowClick={open}
            />
          </CardContent>
        </Card>
        <PaginatedRecords
          title="Latest purchases"
          path="purchases"
          revision={revision}
          load={api}
          params={{ limit: '6' }}
          renderItems={(items) => <PurchaseRecords items={items} showBuyer compact />}
          headerAction={link('#purchases', 'All purchases')}
        />
      </div>
      <PaginatedRecords
        title="Latest admin actions"
        path="audit"
        revision={revision}
        load={api}
        params={{ limit: '8' }}
        columns={['operation', 'target_id', 'actor_id', 'reason', 'created_at']}
        headerAction={link('#audit', 'Audit log')}
      />
      <Accordion type="single" collapsible className="rounded-lg border px-4">
        <AccordionItem value="capabilities" className="border-0">
          <AccordionTrigger className="py-3 text-sm">Server support and limits</AccordionTrigger>
          <AccordionContent>
            <Details data={caps} />
          </AccordionContent>
        </AccordionItem>
      </Accordion>
    </div>
  );
}

function PlayersList({ api, revision }: { api: Api; revision: number }) {
  const [query, setQuery] = useState(''),
    [search, setSearch] = useState(''),
    [status, setStatus] = useState(''),
    [cursor, setCursor] = useState(''),
    [history, setHistory] = useState<string[]>([]),
    [list, setList] = useState<List>(empty),
    [busy, setBusy] = useState(true),
    [error, setError] = useState('');
  useEffect(() => {
    const timer = setTimeout(() => {
      setSearch(query.trim());
      setCursor('');
      setHistory([]);
    }, 250);
    return () => clearTimeout(timer);
  }, [query]);
  useEffect(() => {
    let current = true;
    setBusy(true);
    setError('');
    api(
      'users?' +
        new URLSearchParams({
          limit: '25',
          q: search,
          ...(status ? { status } : {}),
          ...(cursor ? { cursor } : {}),
        }),
    )
      .then((data) => current && setList(asList(data)))
      .catch((e) => current && setError(e.message))
      .finally(() => current && setBusy(false));
    return () => {
      current = false;
    };
  }, [api, search, status, cursor, revision]);
  const filters = [
    ['', 'All'],
    ['online', 'Online'],
    ['restricted', 'Banned or muted'],
  ];
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          Players <Badge variant="secondary">{Number(list.total ?? 0).toLocaleString()}</Badge>
        </CardTitle>
        <CardDescription>
          Open a player to see their character, items, sessions and history.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search by name or Steam ID…"
            className="min-h-9 min-w-48 flex-1"
            aria-label="Search players"
          />
          <div className="flex gap-1" role="group" aria-label="Filter players">
            {filters.map(([value, label]) => (
              <Button
                key={value}
                size="sm"
                variant={status === value ? 'default' : 'outline'}
                aria-pressed={status === value}
                onClick={() => {
                  setStatus(value);
                  setCursor('');
                  setHistory([]);
                }}
              >
                {label}
              </Button>
            ))}
          </div>
        </div>
        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : busy && !list.items.length ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : (
          <RecordList
            items={list.items}
            columns={['account_id', 'status', 'crystals', 'np', 'last_login_at']}
            render={{ status: (row) => <StatusBadges row={row} /> }}
            onRowClick={open}
            emptyText={search ? 'No player matches this search.' : 'No players yet.'}
          />
        )}
        <Pager
          history={history}
          next={list.next_cursor}
          busy={busy}
          back={() => {
            setCursor(history.at(-1)!);
            setHistory((h) => h.slice(0, -1));
          }}
          forward={() => {
            setHistory((h) => [...h, cursor]);
            setCursor(list.next_cursor!);
          }}
        />
      </CardContent>
    </Card>
  );
}

function Operators({
  api,
  revision,
  actor,
  mutate,
  saving,
}: {
  api: Api;
  revision: number;
  actor: { id: string; role: string };
  mutate: (path: string, body: Row) => Promise<boolean>;
  saving: boolean;
}) {
  const [caps, setCaps] = useState<Row>({}),
    [linkPlayer, setLinkPlayer] = useState<Row | null>(null);
  useEffect(() => {
    api('capabilities')
      .then(setCaps)
      .catch(() => {});
  }, [api, revision]);
  return (
    <div className="grid gap-3">
      <PaginatedRecords
        title="Panel accounts"
        path="operators"
        revision={revision}
        load={api}
        columns={['id', 'role', 'enabled', 'account_id']}
        description="Who can sign in to this panel. Panel roles are separate from in-game privileges."
      />
      {actor.role === 'owner' && (
        <ChangeForm
          title="Set panel access"
          description="Owner: everything. Admin: players, credits, items, stores and moderation. Moderator: read and moderate. Passwords are added with the credential tool."
          busy={saving}
          requireReason
          submitLabel="Save access"
          fields={[
            { name: 'id', label: 'Operator ID' },
            { name: 'role', label: 'Role', options: ['moderator', 'admin', 'owner'] },
            { name: 'enabled', label: 'Access', options: ['enabled', 'disabled'] },
          ]}
          submit={(d) =>
            mutate('operators/' + encodeURIComponent(d.id), {
              role: d.role,
              enabled: d.enabled === 'enabled',
              reason: d.reason,
            })
          }
        />
      )}
      {canLinkOperator(caps, actor.role) && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Link an operator to their player</CardTitle>
            <CardDescription>
              Ties a panel account to the player it uses in game, so moderators can't act on
              higher-ranked staff. Save without a player to unlink.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3">
            {linkPlayer ? (
              <p className="text-sm">
                Player: <strong>{String(linkPlayer.username)}</strong>{' '}
                <Button
                  variant="link"
                  size="sm"
                  className="h-auto p-0"
                  onClick={() => setLinkPlayer(null)}
                >
                  change
                </Button>
              </p>
            ) : (
              <PlayerPicker
                api={api}
                onPick={setLinkPlayer}
                placeholder="Find the operator's player…"
              />
            )}
            <ChangeForm
              bare
              title="Save link"
              busy={saving}
              requireReason
              fields={[{ name: 'operator_id', label: 'Operator ID' }]}
              submit={async (data) => {
                const ok = await mutate(
                  'operators/' + encodeURIComponent(data.operator_id.trim()) + '/player-link',
                  {
                    account_id: linkPlayer ? String(linkPlayer.account_id) : null,
                    reason: data.reason,
                  },
                );
                if (ok) setLinkPlayer(null);
                return ok;
              }}
            />
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function HeaderSearch({ api }: { api: Api }) {
  return (
    <div className="hidden w-64 md:block">
      <PlayerPicker api={api} placeholder="Jump to player…" onPick={open} />
    </div>
  );
}

export default function ControlPanel({
  actor,
  csrf,
}: {
  actor: { id: string; role: string };
  csrf: string;
}) {
  const [view, setView] = useState('overview'),
    [busy, setBusy] = useState(false),
    [saving, setSaving] = useState(false),
    [error, setError] = useState(''),
    [notice, setNotice] = useState(''),
    [revision, setRevision] = useState(0);
  const [selected, setSelected] = useState(''),
    [playerTab, setPlayerTab] = useState<PlayerTab>('summary'),
    [detail, setDetail] = useState<Row | null>(null);
  const keys = useRef(new Map<string, string>());
  const [events, setEvents] = useState<FeedEvent[]>([]),
    [toasts, setToasts] = useState<(FeedEvent & { id: number })[]>([]),
    [online, setOnline] = useState<number | null>(null),
    toastId = useRef(0),
    viewRef = useRef(view);
  viewRef.current = view;
  const api = useCallback(
    async (path: string, body?: unknown) => {
      const signature = path + JSON.stringify(body);
      let key = keys.current.get(signature);
      if (body !== undefined && !key) {
        key = crypto.randomUUID();
        keys.current.set(signature, key);
      }
      const response = await fetch('/api/manage/' + path, {
        method: body === undefined ? 'GET' : 'POST',
        headers:
          body === undefined
            ? {}
            : { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf, 'Idempotency-Key': key! },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      if (response.status === 401) {
        window.location.assign('/login');
        throw new Error('Session expired');
      }
      if (!response.headers.get('content-type')?.includes('json'))
        throw new Error(
          response.status === 404 ? 'This server does not support that yet.' : 'Request failed',
        );
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error?.message || 'Request failed');
      if (body !== undefined) keys.current.delete(signature);
      return payload.data;
    },
    [csrf],
  );
  useEffect(() => {
    const change = () => {
      if (window.location.hash === '#main-content') return;
      const route = panelRoute(window.location.hash);
      setView(route.view);
      setSelected(route.id);
      setPlayerTab(route.tab);
      setNotice('');
      setError('');
    };
    change();
    window.addEventListener('hashchange', change);
    return () => window.removeEventListener('hashchange', change);
  }, []);
  const connected = useLiveFeed(api, (fresh, count) => {
    setOnline(count);
    if (!fresh.length) return;
    setEvents((list) => [...fresh.slice().reverse(), ...list].slice(0, 200));
    setToasts((list) =>
      [...list, ...fresh.slice(-3).map((event) => ({ ...event, id: ++toastId.current }))].slice(-4),
    );
    // Refresh read-only views; never reset open edit forms in stores or panel access.
    if (!['stores', 'operators', 'catalog'].includes(viewRef.current)) setRevision((r) => r + 1);
  });
  useEffect(() => {
    if (!toasts.length) return;
    const timer = setTimeout(() => setToasts((list) => list.slice(1)), 6000);
    return () => clearTimeout(timer);
  }, [toasts]);
  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(''), 5000);
    return () => clearTimeout(timer);
  }, [notice]);
  useEffect(() => {
    if (!selected || view !== 'users') {
      setDetail(null);
      return;
    }
    let current = true;
    setBusy(true);
    setDetail((previous) => (previous?.account_id === selected ? previous : null));
    setError('');
    api('users/' + encodeURIComponent(selected))
      .then((d) => {
        if (d.account_id !== selected)
          throw new Error('Player response did not match the selected account.');
        if (current) setDetail(d);
      })
      .catch((e) => current && setError((e as Error).message))
      .finally(() => current && setBusy(false));
    return () => {
      current = false;
    };
  }, [selected, view, revision, api]);
  async function mutate(path: string, body: Row) {
    if (saving) return false;
    setSaving(true);
    setError('');
    setNotice('');
    try {
      const result = await api(path, body);
      setNotice(
        result.changed === false
          ? 'Nothing changed — it was already like that.'
          : 'Saved.' +
              (path.startsWith('users/')
                ? ' Players see it after reopening the menu or rejoining.'
                : ''),
      );
      setRevision((r) => r + 1);
      return true;
    } catch (e) {
      setError((e as Error).message);
      return false;
    } finally {
      setSaving(false);
    }
  }
  async function logout() {
    const r = await fetch('/api/logout', { method: 'POST', headers: { 'X-CSRF-Token': csrf } });
    if (r.ok) window.location.assign('/login');
    else setError('Sign out failed. Reload and try again.');
  }
  const title =
    selected && view === 'users'
      ? String(detail?.username || 'Player')
      : sections.find((s) => s.id === view)?.label || 'Overview';
  return (
    <TooltipProvider>
      <SidebarProvider style={{ '--sidebar-width': '15rem' } as React.CSSProperties}>
        <AppSidebar
          view={view}
          navigate={(v) => (window.location.hash = v)}
          actor={actor}
          logout={logout}
        />
        <SidebarInset className="min-w-0">
          <SiteHeader
            title={title}
            busy={busy}
            refresh={() => setRevision((r) => r + 1)}
            search={<HeaderSearch api={api} />}
            live={{ connected, online }}
          />
          <main id="main-content" className="@container/main flex flex-1 flex-col gap-3 p-3 sm:p-4">
            {error && (
              <Alert
                variant="destructive"
                className="sticky top-14 z-20 bg-background"
                role="alert"
              >
                <AlertDescription className="flex items-center justify-between gap-2">
                  {error}
                  <Button size="sm" variant="ghost" onClick={() => setError('')}>
                    Dismiss
                  </Button>
                </AlertDescription>
              </Alert>
            )}
            {notice && (
              <Alert role="status" className="sticky top-14 z-20 bg-background">
                <AlertDescription>{notice}</AlertDescription>
              </Alert>
            )}
            {view === 'overview' ? (
              <Overview api={api} revision={revision} />
            ) : view === 'monitor' ? (
              <MonitorWorkspace
                api={api}
                revision={revision}
                events={events}
                mutate={mutate}
                saving={saving}
              />
            ) : view === 'moderation' ? (
              <ModerationWorkspace
                actor={actor}
                api={api}
                revision={revision}
                mutate={mutate}
                saving={saving}
              />
            ) : view === 'catalog' ? (
              <CatalogWorkspace api={api} revision={revision} />
            ) : view === 'stores' ? (
              <StoresWorkspace
                actor={actor}
                api={api}
                revision={revision}
                selectedId={selected}
                mutate={mutate}
                saving={saving}
              />
            ) : view === 'purchases' ? (
              <PaginatedRecords
                title="Purchases"
                path="purchases"
                revision={revision}
                load={api}
                description="Everything bought in the game stores, newest first. Prices shown are today's store prices."
                renderItems={(items) => <PurchaseRecords items={items} showBuyer />}
              />
            ) : view === 'transactions' ? (
              <PaginatedRecords
                title="Credit changes"
                path="transactions"
                revision={revision}
                load={api}
                description="Credits added or removed by staff. Store purchases are under Purchases."
                columns={[
                  'account_id',
                  'delta',
                  'after_balance',
                  'actor_id',
                  'reason',
                  'created_at',
                ]}
              />
            ) : view === 'audit' ? (
              <PaginatedRecords
                title="Audit log"
                path="audit"
                revision={revision}
                load={api}
                description="Every change made through this panel: who, what, and the exact fields that changed."
                columns={['operation', 'target_id', 'actor_id', 'reason', 'created_at']}
              />
            ) : view === 'operators' ? (
              <Operators
                api={api}
                revision={revision}
                actor={actor}
                mutate={mutate}
                saving={saving}
              />
            ) : selected ? (
              detail?.account_id === selected ? (
                <PlayerAccount
                  key={selected}
                  id={selected}
                  detail={detail}
                  tab={playerTab}
                  actor={actor}
                  api={api}
                  mutate={mutate}
                  saving={saving}
                  revision={revision}
                  refresh={() => setRevision((value) => value + 1)}
                />
              ) : busy ? (
                <p className="text-sm text-muted-foreground">Loading player…</p>
              ) : (
                <Button asChild variant="outline" size="sm" className="self-start">
                  <a href="#users">Back to players</a>
                </Button>
              )
            ) : (
              <PlayersList api={api} revision={revision} />
            )}
          </main>
        </SidebarInset>
        <Toasts
          toasts={toasts}
          dismiss={(id) => setToasts((list) => list.filter((t) => t.id !== id))}
        />
      </SidebarProvider>
    </TooltipProvider>
  );
}
