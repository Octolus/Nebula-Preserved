import { useEffect, useState } from 'react';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from './ui/card';
import { Badge } from './ui/badge';
import { Input } from './ui/input';
import { RecordList } from './record-list';
import { PaginatedRecords, Stat } from './management-widgets';
import { describe, type FeedEvent } from './live-feed';
import { GeoText } from './player-sessions';
import { AdminActions } from './admin-actions';
import { duration, isPublicScene, playerHref, relative, sceneLabel, type Row } from '../lib/panel';

type Api = (path: string) => Promise<any>;
const list = (value: unknown) => (Array.isArray(value) ? (value as Row[]) : []);
const n = (value: unknown) => (typeof value === 'number' ? value.toLocaleString() : '—');

function ActivityStream({ events }: { events: FeedEvent[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          Live activity
          <span className="size-2 animate-pulse rounded-full bg-foreground" aria-hidden />
        </CardTitle>
        <CardDescription>
          Logins, purchases, reports and staff actions as they happen.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {!events.length ? (
          <p className="py-6 text-center text-sm text-muted-foreground">Waiting for activity…</p>
        ) : (
          <ul className="divide-y rounded-md border">
            {events.slice(0, 60).map((event, index) => {
              const { text, href } = describe(event);
              return (
                <li key={index} className="flex items-center gap-2 px-3 py-1.5 text-sm">
                  <Badge variant="outline" className="w-20 justify-center capitalize">
                    {event.type}
                  </Badge>
                  {href ? (
                    <a href={href} className="min-w-0 flex-1 truncate hover:underline">
                      {text}
                    </a>
                  ) : (
                    <span className="min-w-0 flex-1 truncate">{text}</span>
                  )}
                  <span className="shrink-0 text-xs text-muted-foreground">
                    {relative(event.at)}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function Geo({ geo }: { geo: unknown }) {
  const g = (geo && typeof geo === 'object' ? geo : {}) as Row;
  const place = [g.city, g.region, g.country].filter(Boolean).join(', ');
  return (
    <span className="text-xs text-muted-foreground">
      {place || 'Unknown location'}
      {g.isp ? ' · ' + String(g.isp) : ''}
    </span>
  );
}

/** Live players grouped by the scene (world instance) they are in. */
function Scenes({
  online,
  worlds,
  act,
}: {
  online: Row[];
  worlds: Row[];
  act?: (instanceId: string) => React.ReactNode;
}) {
  const groups = new Map<string, { world: Row | null; scene: unknown; players: Row[] }>();
  for (const world of worlds)
    groups.set(String(world.instance_id), { world, scene: world.world, players: [] });
  for (const player of online) {
    const key = player.instance_id ? String(player.instance_id) : 'lobby';
    if (!groups.has(key))
      groups.set(key, { world: null, scene: key === 'lobby' ? null : player.world, players: [] });
    const group = groups.get(key)!;
    group.scene = group.scene || player.world;
    group.players.push(player);
  }
  const ordered = [...groups.entries()].sort(([a, x], [b, y]) =>
    a === 'lobby' ? 1 : b === 'lobby' ? -1 : y.players.length - x.players.length,
  );
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          Scenes <Badge variant="secondary">{online.length} online</Badge>
        </CardTitle>
        <CardDescription>Who is where right now. Apartments show their owner.</CardDescription>
      </CardHeader>
      <CardContent>
        {!ordered.length ? (
          <p className="py-6 text-center text-sm text-muted-foreground">
            Nobody is online and no scenes are running.
          </p>
        ) : (
          <div className="grid gap-2">
            {ordered.map(([key, group]) => {
              const owner = group.world?.owner_account_name || group.world?.owner_account_id;
              const title =
                key === 'lobby'
                  ? 'Menus / loading'
                  : !isPublicScene(group.scene) && owner
                    ? String(owner) + "'s " + sceneLabel(group.scene)
                    : group.scene
                      ? sceneLabel(group.scene)
                      : 'Unnamed scene';
              return (
                <div key={key} className="rounded-md border p-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">{title}</span>
                    <Badge variant="outline">
                      {key === 'lobby'
                        ? 'Not in a scene'
                        : isPublicScene(group.scene)
                          ? 'Public'
                          : 'Apartment'}
                    </Badge>
                    {group.world && (
                      <span className="text-xs text-muted-foreground">
                        {String(group.world.players ?? group.players.length)}/
                        {String(group.world.maxusers ?? '—')} players
                        {typeof group.world.started_at === 'number'
                          ? ' · up ' + duration(Date.now() / 1000 - group.world.started_at)
                          : ''}
                        {group.world.process_state ? ' · ' + String(group.world.process_state) : ''}
                      </span>
                    )}
                  </div>
                  {key !== 'lobby' && act && <div className="mt-2">{act(key)}</div>}
                  {group.players.length ? (
                    <ul className="mt-2 flex flex-wrap gap-1.5">
                      {group.players.map((player) => (
                        <li key={String(player.account_id)}>
                          <a
                            href={playerHref(String(player.account_id))}
                            className="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs hover:bg-accent"
                            title={
                              (player.ip_country ? String(player.ip_country) + ' · ' : '') +
                              (typeof player.since === 'number'
                                ? 'online for ' + duration(Date.now() / 1000 - player.since)
                                : '')
                            }
                          >
                            <span className="size-1.5 rounded-full bg-foreground" aria-hidden />
                            {String(player.account_name || player.account_id)}
                            {!player.in_world && (
                              <span className="text-muted-foreground">loading</span>
                            )}
                            {player.ip_country_code ? (
                              <span className="text-muted-foreground">
                                {String(player.ip_country_code)}
                              </span>
                            ) : null}
                          </a>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="mt-1 text-xs text-muted-foreground">Empty — stops when idle.</p>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export function IpLink({ ip }: { ip: unknown }) {
  if (typeof ip !== 'string' || !ip) return <span className="text-muted-foreground">—</span>;
  return <span className="font-mono text-xs">{ip}</span>;
}

export function MonitorWorkspace({
  api,
  revision,
  events = [],
  mutate,
  saving = false,
}: {
  api: Api;
  revision: number;
  events?: FeedEvent[];
  mutate?: (path: string, body: Row) => Promise<boolean>;
  saving?: boolean;
}) {
  const [data, setData] = useState<Row | null>(null),
    [error, setError] = useState(''),
    [query, setQuery] = useState(''),
    [search, setSearch] = useState('');
  useEffect(() => {
    let current = true;
    api('monitor')
      .then((value) => current && (setData(value), setError('')))
      .catch((failure) => current && setError(failure.message));
    return () => {
      current = false;
    };
  }, [api, revision]);
  useEffect(() => {
    const timer = setTimeout(() => setSearch(query.trim()), 300);
    return () => clearTimeout(timer);
  }, [query]);
  const stats = (data?.last_24h || {}) as Row;
  const worlds = list((data?.instances as Row | undefined)?.items),
    queue = list((data?.queue as Row | undefined)?.items),
    failures = (data?.failures || {}) as Row;
  return (
    <div className="grid gap-3">
      {error && <p className="text-sm text-destructive">Server monitor: {error}</p>}
      {data && (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-6">
          <Stat label="Online now" value={n(list(data.online).length)} />
          <Stat label="Worlds running" value={n((data.instances as Row | undefined)?.running)} />
          <Stat
            label="Waiting to load"
            value={n(queue.length)}
            tone={queue.length ? 'danger' : undefined}
          />
          <Stat label="Players (24h)" value={n(stats.unique_players)} />
          <Stat label="Sessions (24h)" value={n(stats.sessions)} />
          <Stat
            label="Avg session"
            value={
              typeof stats.avg_session_seconds === 'number'
                ? duration(stats.avg_session_seconds)
                : '—'
            }
          />
        </div>
      )}
      <div className="grid gap-3 xl:grid-cols-2">
        <Scenes
          online={list(data?.online)}
          worlds={worlds}
          act={
            mutate
              ? (instanceId) => (
                  <AdminActions
                    api={api}
                    mutate={mutate}
                    saving={saving}
                    target={instanceId}
                    kinds={['scene']}
                    bare
                  />
                )
              : undefined
          }
        />
        <ActivityStream events={events} />
      </div>
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Worlds</CardTitle>
          <CardDescription>
            Game world processes. Personal apartments start on demand and stop when empty.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3">
          <RecordList
            items={worlds.map((row) => ({
              ...row,
              memory:
                typeof row.memory_rss_bytes === 'number'
                  ? Math.round(row.memory_rss_bytes / 1048576) + ' MB'
                  : '—',
            }))}
            columns={[
              'world',
              'owner_account_id',
              'players',
              'process_state',
              'memory',
              'started_at',
            ]}
            render={{
              owner_account_id: (row) =>
                row.owner_account_id ? (
                  <a href={playerHref(String(row.owner_account_id))} className="hover:underline">
                    {String(row.owner_account_name || row.owner_account_id)}
                  </a>
                ) : (
                  <span className="text-muted-foreground">Public</span>
                ),
              players: (row) => (
                <span className="tabular-nums">
                  {String(row.players ?? 0)}/{String(row.maxusers ?? '—')}
                </span>
              ),
              started_at: (row) => relative(row.started_at),
            }}
            emptyText="No worlds running."
          />
          {queue.length > 0 && (
            <RecordList
              items={queue}
              columns={['account_id', 'world', 'state', 'waiting_seconds']}
              render={{ waiting_seconds: (row) => duration(Number(row.waiting_seconds)) }}
            />
          )}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            Server errors (last hour){' '}
            <Badge variant={Number(failures.total) ? 'destructive' : 'secondary'}>
              {n(failures.total)}
            </Badge>
          </CardTitle>
          <CardDescription>
            Failed game requests and dropped connections from the server's failure logs.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3">
          {failures.available === false ? (
            <p className="text-sm text-muted-foreground">
              Failure logs aren't available on this server yet.
            </p>
          ) : (
            <>
              <div className="flex flex-wrap gap-1">
                {list(failures.by_reason).map((row) => (
                  <Badge key={String(row.reason)} variant="outline">
                    {String(row.reason)} · {String(row.count)}
                  </Badge>
                ))}
              </div>
              <RecordList
                items={list(failures.recent).slice(0, 20)}
                columns={['event', 'route', 'reason', 'message', 'timestamp']}
                emptyText="No errors in the last hour."
              />
            </>
          )}
        </CardContent>
      </Card>
      <PaginatedRecords
        title="Login history"
        path="monitor/logins"
        revision={revision}
        load={api}
        params={search ? { q: search } : {}}
        headerAction={
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Filter by name or IP…"
            className="h-8 w-48 font-normal"
            aria-label="Filter logins"
          />
        }
        columns={['account_id', 'result', 'ip', 'geo', 'created_at']}
        render={{
          geo: (row) => <GeoText geo={row.geo} status={row.geo_status} />,
          ip: (row) => <IpLink ip={row.ip} />,
        }}
        emptyText="No logins recorded yet."
      />
    </div>
  );
}
