import { useCallback, useEffect, useRef, useState } from 'react';
import { AppSidebar, sections } from './app-sidebar';
import { SiteHeader } from './site-header';
import { SectionCards } from './section-cards';
import { ModerationWorkspace } from './moderation-workspace';
import { canLinkOperator } from '../lib/moderation';
import { SidebarProvider, SidebarInset } from './ui/sidebar';
import { TooltipProvider } from './ui/tooltip';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from './ui/card';
import { Button } from './ui/button';
import { Input } from './ui/input';
import { Label } from './ui/label';
import { Badge } from './ui/badge';
import { RecordList } from './record-list';
import { ChangeForm, Details, empty, type List } from './management-widgets';
import { PlayerAccount } from './player-account';
import { CatalogWorkspace } from './catalog-workspace';
import { Alert, AlertDescription } from './ui/alert';
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from './ui/accordion';
import { panelRoute, playerHref, type Row, type PlayerTab } from '../lib/panel';
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
  const [stats, setStats] = useState<Row>({}),
    [caps, setCaps] = useState<Row>({}),
    [list, setList] = useState<List>(empty),
    [query, setQuery] = useState(''),
    [search, setSearch] = useState(''),
    [cursor, setCursor] = useState(''),
    [history, setHistory] = useState<string[]>([]);
  const [selected, setSelected] = useState(''),
    [playerTab, setPlayerTab] = useState<PlayerTab>('summary'),
    [detail, setDetail] = useState<Row | null>(null),
    [wallet, setWallet] = useState<Row>({});
  const keys = useRef(new Map<string, string>());
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
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error?.message || 'Request failed');
      if (body !== undefined) keys.current.delete(signature);
      return payload.data;
    },
    [csrf],
  );
  function navigate(v: string) {
    window.location.hash = v;
  }
  useEffect(() => {
    const change = () => {
      if (window.location.hash === '#main-content') return;
      const route = panelRoute(window.location.hash);
      setView(route.view);
      setSelected(route.id);
      setPlayerTab(route.tab);
      setQuery('');
      setSearch('');
      setList(empty);
      setCursor('');
      setHistory([]);
      setNotice('');
      setError('');
    };
    change();
    window.addEventListener('hashchange', change);
    return () => window.removeEventListener('hashchange', change);
  }, []);
  useEffect(() => {
    let current = true;
    setBusy(true);
    setError('');
    (async () => {
      try {
        if (view === 'overview') {
          const [s, c] = await Promise.all([api('stats'), api('capabilities')]);
          if (current) {
            setStats(s);
            setCaps(c);
          }
        } else if (view !== 'moderation' && view !== 'catalog' && !selected) {
          const p = new URLSearchParams({
            limit: '25',
            ...(cursor ? { cursor } : {}),
            q: search,
          });
          const result = await api(view + '?' + p);
          if (current) setList(result);
          if (view === 'operators') {
            const capabilities = await api('capabilities');
            if (current) setCaps(capabilities);
          }
        }
      } catch (e) {
        if (current) setError((e as Error).message);
      } finally {
        if (current) setBusy(false);
      }
    })();
    return () => {
      current = false;
    };
  }, [view, cursor, search, revision, api, selected]);
  useEffect(() => {
    if (!selected) {
      setDetail(null);
      return;
    }
    let current = true;
    setBusy(true);
    setDetail((previous) => (previous?.account_id === selected ? previous : null));
    setError('');
    (async () => {
      try {
        const base = 'users/' + encodeURIComponent(selected);
        const [d, w] = await Promise.all([api(base), api(base + '/wallet')]);
        if (d.account_id !== selected)
          throw new Error('Player response did not match the selected account.');
        if (current) {
          setDetail(d);
          setWallet(w);
        }
      } catch (e) {
        if (current) setError((e as Error).message);
      } finally {
        if (current) setBusy(false);
      }
    })();
    return () => {
      current = false;
    };
  }, [selected, revision, api]);
  async function mutate(path: string, body: Row) {
    if (saving) return false;
    setSaving(true);
    setError('');
    setNotice('');
    try {
      const result = await api(path, body);
      setNotice(
        `Saved${path.startsWith('users/') ? ' for player ' + decodeURIComponent(path.split('/')[1]) : ''}. Audit record ${result.audit_id ?? result.request_id}.${path.startsWith('users/') ? ' Players may need to reopen a store or rejoin to refresh cached state.' : ''}`,
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
  const title = sections.find((s) => s.id === view)?.label || 'Overview';
  return (
    <TooltipProvider>
      <SidebarProvider style={{ '--sidebar-width': '16rem' } as React.CSSProperties}>
        <AppSidebar view={view} navigate={navigate} actor={actor} logout={logout} />
        <SidebarInset className="min-w-0">
          <SiteHeader title={title} busy={busy} refresh={() => setRevision((r) => r + 1)} />
          <main
            id="main-content"
            className="@container/main flex flex-1 flex-col gap-3 p-3 sm:p-4 lg:p-5"
          >
            <div>
              <p className="text-xs uppercase tracking-widest text-muted-foreground">
                Nebula Realms / preservation server
              </p>
              <h2 className="mt-1 text-xl font-semibold tracking-tight">
                {selected
                  ? 'Player account'
                  : view === 'overview'
                    ? 'Your community, connected.'
                    : title}
              </h2>
              <p className="mt-1 text-sm text-muted-foreground">
                {view === 'overview'
                  ? 'Account state and management activity from your server.'
                  : 'Changes are authorized and recorded by the server.'}
              </p>
            </div>
            {error && (
              <Alert
                variant="destructive"
                className="sticky top-16 z-20 bg-background"
                role="alert"
              >
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}
            {notice && (
              <Alert role="status" className="sticky top-16 z-20 bg-background">
                <AlertDescription>{notice}</AlertDescription>
              </Alert>
            )}
            {busy && (
              <p role="status" className="text-sm text-muted-foreground">
                Loading server records…
              </p>
            )}
            {view === 'overview' ? (
              <>
                <SectionCards stats={stats} />
                <Card>
                  <CardHeader>
                    <CardTitle>Server support</CardTitle>
                    <CardDescription>
                      Support and limits reported by the recovered backend.
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    <Accordion type="single" collapsible>
                      <AccordionItem value="capabilities" className="border-0">
                        <AccordionTrigger className="min-h-11 py-1">
                          Inspect supported features and limits
                        </AccordionTrigger>
                        <AccordionContent>
                          <Details data={caps} />
                        </AccordionContent>
                      </AccordionItem>
                    </Accordion>
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader>
                    <CardTitle>Manage your community</CardTitle>
                    <CardDescription>
                      Inspect player ownership and purchases, adjust credits or grant catalog items.
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    <Button className="min-h-11" onClick={() => navigate('users')}>
                      Find a player
                    </Button>
                  </CardContent>
                </Card>
              </>
            ) : view === 'moderation' ? (
              <ModerationWorkspace actor={actor} api={api} revision={revision} />
            ) : view === 'catalog' ? (
              <CatalogWorkspace api={api} revision={revision} />
            ) : selected ? (
              detail?.account_id === selected ? (
                <PlayerAccount
                  key={selected}
                  id={selected}
                  detail={detail}
                  wallet={wallet}
                  tab={playerTab}
                  actor={actor}
                  api={api}
                  mutate={mutate}
                  saving={saving}
                  revision={revision}
                  refresh={() => setRevision((value) => value + 1)}
                />
              ) : (
                <Button asChild variant="outline" className="min-h-11 self-start">
                  <a href="#users">Back to players</a>
                </Button>
              )
            ) : (
              <>
                <Card>
                  <CardHeader>
                    <CardTitle>
                      {title}
                      <Badge variant="secondary" className="ml-3">
                        {list.total} records
                      </Badge>
                    </CardTitle>
                    <CardDescription>
                      {view === 'transactions'
                        ? 'Audited panel credit adjustments. Store purchases are listed on each player account.'
                        : view === 'operators'
                          ? 'Panel permissions are separate from game privileges.'
                          : view === 'users'
                            ? 'Search records or open a player account.'
                            : 'Browse recorded management activity.'}
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    {view === 'users' && (
                      <form
                        className="flex flex-wrap gap-2"
                        onSubmit={(e) => {
                          e.preventDefault();
                          setSearch(query);
                          setCursor('');
                          setHistory([]);
                        }}
                      >
                        <div className="min-w-40 flex-1">
                          <Label className="sr-only" htmlFor="search">
                            Search records
                          </Label>
                          <Input
                            id="search"
                            placeholder="Search records…"
                            value={query}
                            onChange={(e) => setQuery(e.target.value)}
                            className="min-h-11"
                          />
                        </div>
                        <Button variant="outline" className="min-h-11" disabled={busy}>
                          Search
                        </Button>
                      </form>
                    )}
                    {!busy && !error && (
                      <RecordList
                        items={list.items}
                        columns={
                          view === 'users'
                            ? ['username', 'account_id', 'online', 'crystals', 'np']
                            : view === 'transactions'
                              ? [
                                  'account_id',
                                  'currency',
                                  'delta',
                                  'before_balance',
                                  'after_balance',
                                  'reason',
                                  'created_at',
                                ]
                              : view === 'audit'
                                ? ['operation', 'target_id', 'actor_id', 'reason', 'created_at']
                                : view === 'operators'
                                  ? ['id', 'role', 'enabled', 'account_id']
                                  : undefined
                        }
                        action={
                          view === 'users'
                            ? (row) => (
                                <Button asChild variant="outline" className="min-h-11">
                                  <a href={playerHref(String(row.account_id))}>Open</a>
                                </Button>
                              )
                            : undefined
                        }
                      />
                    )}
                    <div className="flex justify-between">
                      <Button
                        className="min-h-11"
                        variant="outline"
                        disabled={busy || !history.length}
                        onClick={() => {
                          setCursor(history[history.length - 1]);
                          setHistory((h) => h.slice(0, -1));
                        }}
                      >
                        Previous
                      </Button>
                      <Button
                        className="min-h-11"
                        variant="outline"
                        disabled={busy || !list.next_cursor}
                        onClick={() => {
                          setHistory((h) => [...h, cursor]);
                          setCursor(list.next_cursor!);
                        }}
                      >
                        Next
                      </Button>
                    </div>
                  </CardContent>
                </Card>
                {view === 'operators' && actor.role === 'owner' && (
                  <ChangeForm
                    title="Set panel access"
                    description="Owner: all management. Admin: accounts, credits, grants and moderation. Moderator: reads and supported player moderation. A panel role alone does not create a login password or game privileges."
                    busy={saving}
                    fields={[
                      { name: 'id', label: 'Operator ID' },
                      {
                        name: 'role',
                        label: 'Panel role',
                        options: ['moderator', 'admin', 'owner'],
                      },
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
                {view === 'operators' && canLinkOperator(caps, actor.role) && (
                  <ChangeForm
                    title="Link operator to player"
                    description="Link an existing operator to an existing player account for moderation hierarchy checks. Empty player ID removes the link. This does not create a login, assign a role or grant permissions through a display label."
                    busy={saving}
                    fields={[
                      { name: 'operator_id', label: 'Operator to link' },
                      {
                        name: 'account_id',
                        label: 'Player account ID (empty unlinks)',
                        optional: true,
                      },
                    ]}
                    submit={(data) =>
                      mutate(
                        'operators/' + encodeURIComponent(data.operator_id.trim()) + '/player-link',
                        { account_id: data.account_id.trim() || null, reason: data.reason },
                      )
                    }
                  />
                )}
              </>
            )}
            <footer className="mt-auto border-t pt-4 text-xs text-muted-foreground">
              Nebula Preserved · Independent community server · Game privileges require verified
              protocol support.
            </footer>
          </main>
        </SidebarInset>
      </SidebarProvider>
    </TooltipProvider>
  );
}
