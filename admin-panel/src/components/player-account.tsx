import { useEffect, useState } from 'react';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from './ui/card';
import { Button } from './ui/button';
import { Badge } from './ui/badge';
import { Tabs, TabsList, TabsTrigger, TabsContent } from './ui/tabs';
import { Input } from './ui/input';
import { FormSelect } from './form-select';
import { ItemRecords, PurchaseRecords } from './item-records';
import { catalogKinds } from '../lib/catalog';
import { PaginatedRecords, Pager, Stat, empty, asList, type List } from './management-widgets';
import { ModerationPanel } from './moderation-panel';
import { AdminActions } from './admin-actions';
import { CharacterPanel, RevokeItem } from './player-character';
import { SessionsPanel } from './player-sessions';
import {
  formatCell,
  playerHref,
  playerTabs,
  relative,
  sceneLabel,
  isPublicScene,
  type PlayerTab,
  type Row,
} from '../lib/panel';

const grantKinds = catalogKinds.filter((kind) => kind.value !== 'shop_artwork');
type Api = (path: string, body?: Row) => Promise<any>;
type Mutate = (path: string, body: Row) => Promise<boolean>;
const truthy = (value: unknown) => value === true || value === 1;

function GiveItems({
  accountId,
  api,
  mutate,
  saving,
}: {
  accountId: string;
  api: Api;
  mutate: Mutate;
  saving: boolean;
}) {
  const [kind, setKind] = useState('all'),
    [query, setQuery] = useState(''),
    [search, setSearch] = useState(''),
    [cursor, setCursor] = useState(''),
    [history, setHistory] = useState<string[]>([]),
    [records, setRecords] = useState<List>(empty),
    [busy, setBusy] = useState(true),
    [error, setError] = useState(''),
    [given, setGiven] = useState<Set<string>>(new Set());
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
      'catalog?' +
        new URLSearchParams({ kind, q: search, limit: '8', ...(cursor ? { cursor } : {}) }),
    )
      .then((data) => current && setRecords(asList(data)))
      .catch((failure) => current && setError(failure.message))
      .finally(() => current && setBusy(false));
    return () => {
      current = false;
    };
  }, [api, kind, search, cursor]);
  const key = (row: Row) =>
    [row.kind, row.offer_id, row.item_id, row.gender, row.category].join(':');
  async function give(row: Row) {
    const offer = row.kind === 'offer' || (!row.item_id && row.offer_id);
    const body: Row = offer
      ? { kind: 'offer', offer_id: row.offer_id }
      : {
          kind: row.kind,
          item_id: row.item_id,
          ...(row.kind === 'wardrobe' ? { gender: row.gender, category: row.category } : {}),
        };
    if (await mutate('users/' + encodeURIComponent(accountId) + '/items', body))
      setGiven((value) => new Set(value).add(key(row)));
  }
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Give items</CardTitle>
        <CardDescription>
          Search the catalog and click Give. Free for the player; recorded in the audit log.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid gap-2 sm:grid-cols-[12rem_1fr]">
          <FormSelect
            id="give-kind"
            value={kind}
            options={grantKinds.map((k) => ({ value: k.value, label: k.label }))}
            onValueChange={(next) => {
              setKind(next);
              setCursor('');
              setHistory([]);
            }}
          />
          <Input
            value={query}
            maxLength={128}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search item name or category…"
            className="min-h-9"
            aria-label="Search items to give"
          />
        </div>
        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : busy && !records.items.length ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : (
          <ItemRecords
            items={records.items}
            action={(row) =>
              given.has(key(row)) ? (
                <Badge variant="secondary">Given</Badge>
              ) : (
                <Button
                  size="sm"
                  disabled={saving || row.grantable === false}
                  onClick={() => give(row)}
                >
                  Give
                </Button>
              )
            }
          />
        )}
        <Pager
          history={history}
          next={records.next_cursor}
          busy={busy}
          back={() => {
            setCursor(history.at(-1)!);
            setHistory((h) => h.slice(0, -1));
          }}
          forward={() => {
            setHistory((h) => [...h, cursor]);
            setCursor(records.next_cursor!);
          }}
        />
      </CardContent>
    </Card>
  );
}

function Credits({ base, mutate, saving }: { base: string; mutate: Mutate; saving: boolean }) {
  const [currency, setCurrency] = useState('crystals'),
    [amount, setAmount] = useState(''),
    [note, setNote] = useState(''),
    [error, setError] = useState('');
  async function change(sign: 1 | -1, value = Number(amount)) {
    setError('');
    if (!Number.isSafeInteger(value) || value <= 0)
      return setError('Enter a whole number above zero.');
    const body: Row = {
      currency,
      delta: sign * value,
      ...(note.trim() ? { reason: note.trim() } : {}),
    };
    if (await mutate(base + '/wallet-adjustments', body)) {
      setAmount('');
      setNote('');
    }
  }
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Change credits</CardTitle>
        <CardDescription>Balances can't go below zero.</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3">
        <div className="grid gap-2 sm:grid-cols-[10rem_8rem_1fr]">
          <FormSelect
            id="credit-currency"
            value={currency}
            options={[
              { value: 'crystals', label: 'Crystals' },
              { value: 'np', label: 'Nebula Points' },
            ]}
            onValueChange={setCurrency}
          />
          <Input
            type="number"
            min={1}
            step={1}
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
            placeholder="Amount"
            className="min-h-9"
            aria-label="Amount"
          />
          <Input
            value={note}
            maxLength={512}
            onChange={(event) => setNote(event.target.value)}
            placeholder="Note (optional)"
            className="min-h-9"
            aria-label="Note"
          />
        </div>
        {error && <p className="text-sm text-destructive">{error}</p>}
        <div className="flex flex-wrap gap-2">
          <Button size="sm" disabled={saving} onClick={() => change(1)}>
            Add
          </Button>
          <Button size="sm" variant="outline" disabled={saving} onClick={() => change(-1)}>
            Remove
          </Button>
          <span className="mx-1 self-center text-xs text-muted-foreground">Quick add:</span>
          {[100, 1000, 10000].map((value) => (
            <Button
              key={value}
              size="sm"
              variant="secondary"
              disabled={saving}
              onClick={() => change(1, value)}
            >
              +{value.toLocaleString()}
            </Button>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

export function PlayerAccount({
  id,
  detail,
  tab,
  actor,
  api,
  mutate,
  saving,
  revision,
  refresh,
}: {
  id: string;
  detail: Row;
  tab: PlayerTab;
  actor: { role: string };
  api: Api;
  mutate: Mutate;
  saving: boolean;
  revision: number;
  refresh: () => void;
}) {
  const base = 'users/' + encodeURIComponent(id),
    canEdit = ['owner', 'admin'].includes(actor.role),
    wallet = (detail.wallet || {}) as Row,
    [copied, setCopied] = useState(false);
  const names: Record<PlayerTab, string> = {
    summary: 'Overview',
    character: 'Character',
    inventory: 'Inventory',
    purchases: 'Purchases',
    credits: 'Credits',
    sessions: 'Sessions',
    moderation: 'Moderation',
    activity: 'History',
  };
  const gender =
    detail.gender === 'MALE' ? 'Male' : detail.gender === 'FEMALE' ? 'Female' : detail.gender;
  return (
    <div className="min-w-0 space-y-3">
      <Card>
        <CardContent className="grid gap-3">
          <a href="#users" className="w-fit text-xs text-muted-foreground hover:underline">
            ← Players
          </a>
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="min-w-0 break-words text-lg font-semibold [overflow-wrap:anywhere]">
              {String(detail.username || 'Unnamed player')}
            </h2>
            {truthy(detail.online) ? (
              <Badge>Online</Badge>
            ) : (
              <Badge variant="outline">Offline</Badge>
            )}
            {truthy(detail.online) && (
              <Badge variant="secondary">
                {detail.current_scene
                  ? 'In ' +
                    (isPublicScene(detail.current_scene) || !detail.current_scene_owner
                      ? sceneLabel(detail.current_scene)
                      : String(detail.current_scene_owner) +
                        "'s " +
                        sceneLabel(detail.current_scene))
                  : 'In menus / loading'}
              </Badge>
            )}
            {truthy(detail.banned) && <Badge variant="destructive">Banned</Badge>}
            {truthy(detail.muted) && <Badge variant="secondary">Muted</Badge>}
            {typeof detail.staff_label === 'string' && detail.staff_label && (
              <Badge variant="outline">{detail.staff_label}</Badge>
            )}
          </div>
          <button
            type="button"
            className="w-fit font-mono text-xs text-muted-foreground hover:text-foreground"
            title="Copy Steam ID"
            onClick={() => {
              void navigator.clipboard?.writeText(id).then(() => {
                setCopied(true);
                setTimeout(() => setCopied(false), 1500);
              });
            }}
          >
            Steam ID {id} {copied ? '· copied' : '· copy'}
          </button>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <Stat
              label="Crystals"
              value={typeof wallet.crystals === 'number' ? wallet.crystals.toLocaleString() : '—'}
            />
            <Stat
              label="Nebula Points"
              value={typeof wallet.np === 'number' ? wallet.np.toLocaleString() : '—'}
            />
            <Stat
              label="Last login"
              value={<span className="text-sm">{relative(detail.last_login_at)}</span>}
            />
            <Stat
              label="Joined"
              value={<span className="text-sm">{relative(detail.created_at)}</span>}
            />
          </div>
        </CardContent>
      </Card>
      <Tabs
        value={tab}
        onValueChange={(next) => {
          window.location.hash = playerHref(id, next as PlayerTab);
        }}
        className="min-w-0 gap-3"
      >
        <TabsList
          className="h-auto w-full flex-wrap justify-start gap-1 p-1"
          aria-label="Player sections"
        >
          {playerTabs.map((value) => (
            <TabsTrigger key={value} value={value} className="flex-none px-3 text-xs sm:text-sm">
              {names[value]}
            </TabsTrigger>
          ))}
        </TabsList>
        <TabsContent value="summary" className="grid gap-3 xl:grid-cols-2">
          <CharacterPanel
            accountId={id}
            api={api}
            mutate={mutate}
            saving={saving}
            revision={revision}
            canEdit={canEdit}
            compact
          />
          <div className="grid content-start gap-3">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Account</CardTitle>
              </CardHeader>
              <CardContent>
                <dl className="grid grid-cols-2 gap-2">
                  {[
                    ['Platform', detail.platform],
                    ['Character', gender],
                    ['Joined', formatCell('created_at', detail.created_at)],
                    ['Last login', formatCell('last_login_at', detail.last_login_at)],
                    [
                      'Last outfit save',
                      formatCell('last_avatar_save_at', detail.last_avatar_save_at),
                    ],
                    [
                      'Ban',
                      truthy(detail.banned)
                        ? detail.ban_expires_at
                          ? 'Until ' + formatCell('ban_expires_at', detail.ban_expires_at)
                          : 'Permanent'
                        : 'No',
                    ],
                  ].map(([label, value]) => (
                    <div key={String(label)}>
                      <dt className="text-xs text-muted-foreground">{String(label)}</dt>
                      <dd className="font-medium">{String(value ?? '—')}</dd>
                    </div>
                  ))}
                </dl>
              </CardContent>
            </Card>
            <PaginatedRecords
              title="Recent purchases"
              path={base + '/purchases'}
              revision={revision}
              load={api}
              params={{ limit: '5' }}
              renderItems={(items) => <PurchaseRecords items={items} compact />}
              headerAction={
                <a
                  href={playerHref(id, 'purchases')}
                  className="text-xs font-normal text-muted-foreground hover:underline"
                >
                  All →
                </a>
              }
            />
          </div>
        </TabsContent>
        <TabsContent value="character">
          <CharacterPanel
            accountId={id}
            api={api}
            mutate={mutate}
            saving={saving}
            revision={revision}
            canEdit={canEdit}
          />
        </TabsContent>
        <TabsContent value="inventory" className="grid gap-3 xl:grid-cols-2">
          <PaginatedRecords
            title="Owned items"
            path={base + '/owned'}
            revision={revision}
            load={api}
            renderItems={(items) => (
              <ItemRecords
                items={items}
                granted
                emptyText="This player owns no items yet."
                action={
                  canEdit
                    ? (row) => (
                        <RevokeItem row={row} accountId={id} mutate={mutate} saving={saving} />
                      )
                    : undefined
                }
              />
            )}
          />
          {canEdit && <GiveItems accountId={id} api={api} mutate={mutate} saving={saving} />}
        </TabsContent>
        <TabsContent value="purchases">
          <PaginatedRecords
            title="Purchases"
            path={base + '/purchases'}
            revision={revision}
            load={api}
            description="Store purchases and staff-given store offers. Prices are today's store prices."
            renderItems={(items) => <PurchaseRecords items={items} />}
          />
        </TabsContent>
        <TabsContent value="credits" className="grid gap-3">
          {canEdit && <Credits base={base} mutate={mutate} saving={saving} />}
          <PaginatedRecords
            title="Credit history"
            path={base + '/transactions'}
            revision={revision}
            load={api}
            columns={['delta', 'after_balance', 'actor_id', 'reason', 'created_at']}
            emptyText="No staff credit changes for this player."
          />
        </TabsContent>
        <TabsContent value="sessions">
          <SessionsPanel accountId={id} api={api} revision={revision} />
        </TabsContent>
        <TabsContent value="moderation" className="grid gap-3">
          <LiveState accountId={id} api={api} revision={revision} />
          <AdminActions
            actor={actor}
            api={api}
            mutate={mutate}
            saving={saving}
            target={id}
            kinds={['player']}
            online={detail.online === 1 || detail.online === true}
            exclude={['ban', 'unban', 'mute', 'unmute', 'kick', 'staff_label']}
          />
          <ModerationPanel
            accountId={id}
            actor={actor}
            api={api}
            revision={revision}
            onCommitted={refresh}
          />
        </TabsContent>
        <TabsContent value="activity">
          <PaginatedRecords
            title="Staff actions on this player"
            path={base + '/audit'}
            revision={revision}
            load={api}
            columns={['operation', 'actor_id', 'reason', 'created_at']}
            emptyText="No staff actions yet."
          />
        </TabsContent>
      </Tabs>
    </div>
  );
}

/** Where the player is right now, according to the running scene. */
function LiveState({
  accountId,
  api,
  revision,
}: {
  accountId: string;
  api: Api;
  revision: number;
}) {
  const [live, setLive] = useState<Row | null>(null);
  useEffect(() => {
    let current = true;
    api('users/' + encodeURIComponent(accountId) + '/live')
      .then((value) => current && setLive(value))
      .catch(() => current && setLive(null));
    return () => {
      current = false;
    };
  }, [api, accountId, revision]);
  if (!live) return null;
  const position = live.position as Row | null;
  const redirect = live.pending_redirect as Row | null;
  return (
    <Card>
      <CardContent className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
        <span>
          <span className="text-muted-foreground">Now: </span>
          <strong>
            {live.in_world ? String(live.scene_label || sceneLabel(live.scene)) : 'Not in a world'}
          </strong>
        </span>
        {position && typeof position.x === 'number' && (
          <span className="font-mono text-xs text-muted-foreground">
            {['x', 'y', 'z'].map((k) => k + ' ' + Number(position[k]).toFixed(1)).join('  ')}
            {live.position_source === 'last_saved' ? ' (last saved)' : ''}
          </span>
        )}
        {redirect && (
          <Badge variant="secondary">
            Moving to {sceneLabel(redirect.scene ?? redirect.redirect_scene)}
          </Badge>
        )}
        {typeof live.server_status === 'string' && live.server_status !== 'normal' && (
          <Badge variant="destructive">Server: {String(live.server_status)}</Badge>
        )}
      </CardContent>
    </Card>
  );
}
