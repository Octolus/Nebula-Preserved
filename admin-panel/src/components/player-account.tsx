import { useEffect, useState } from 'react';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from './ui/card';
import { Button } from './ui/button';
import { Badge } from './ui/badge';
import { Tabs, TabsList, TabsTrigger, TabsContent } from './ui/tabs';
import { Input } from './ui/input';
import { Label } from './ui/label';
import { FormSelect } from './form-select';
import { RecordList } from './record-list';
import { ChangeForm, Details, PaginatedRecords, empty, type List } from './management-widgets';
import { ModerationPanel } from './moderation-panel';
import { display, playerHref, playerTabs, type PlayerTab, type Row } from '../lib/panel';

function CatalogGrant({
  accountId,
  api,
  mutate,
  saving,
}: {
  accountId: string;
  api: (path: string) => Promise<List>;
  mutate: (path: string, body: Row) => Promise<boolean>;
  saving: boolean;
}) {
  const [kind, setKind] = useState('offer'),
    [query, setQuery] = useState(''),
    [search, setSearch] = useState(''),
    [cursor, setCursor] = useState(''),
    [history, setHistory] = useState<string[]>([]),
    [records, setRecords] = useState<List>(empty),
    [chosen, setChosen] = useState<Row | null>(null),
    [busy, setBusy] = useState(true),
    [error, setError] = useState('');
  useEffect(() => {
    let current = true;
    setBusy(true);
    setError('');
    api(
      'catalog?' +
        new URLSearchParams({ kind, q: search, limit: '5', ...(cursor ? { cursor } : {}) }),
    )
      .then((data) => {
        if (current) setRecords(data);
      })
      .catch((failure) => {
        if (current) setError(failure.message);
      })
      .finally(() => {
        if (current) setBusy(false);
      });
    return () => {
      current = false;
    };
  }, [api, kind, search, cursor]);
  const defaults: Record<string, string> = chosen
    ? {
        kind,
        item: String(chosen.offer_id || chosen.item_id),
        gender: String(chosen.gender || ''),
        category: String(chosen.category || ''),
      }
    : { kind };
  return (
    <div className="space-y-3">
      <Card>
        <CardHeader>
          <CardTitle>Find an item to grant</CardTitle>
          <CardDescription>
            Search the server catalog, choose an item, then confirm the grant below. Grants do not
            charge the player.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <form
            className="grid gap-2 sm:grid-cols-[10rem_1fr_auto]"
            onSubmit={(event) => {
              event.preventDefault();
              setSearch(query);
              setCursor('');
              setHistory([]);
            }}
          >
            <div>
              <Label className="sr-only" htmlFor="grant-kind">
                Catalog type
              </Label>
              <FormSelect
                id="grant-kind"
                value={kind}
                options={['offer', 'wardrobe', 'companions', 'locomotions', 'housing']}
                onValueChange={(next) => {
                  setKind(next);
                  setCursor('');
                  setHistory([]);
                  setChosen(null);
                }}
              />
            </div>
            <div>
              <Label className="sr-only" htmlFor="grant-search">
                Find catalog items
              </Label>
              <Input
                id="grant-search"
                value={query}
                maxLength={128}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search name or exact item ID"
                className="min-h-11"
              />
            </div>
            <Button variant="outline" className="min-h-11" disabled={busy}>
              Search catalog
            </Button>
          </form>
          {error ? (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          ) : busy ? (
            <p role="status" className="text-sm">
              Loading catalog…
            </p>
          ) : (
            <RecordList
              items={records.items}
              columns={
                kind === 'offer'
                  ? ['name', 'offer_id', 'kind', 'crystals', 'np']
                  : ['item_id', 'gender', 'category']
              }
              action={(row) => (
                <Button
                  variant="outline"
                  className="min-h-11"
                  disabled={saving}
                  onClick={() => setChosen(row)}
                >
                  Choose item
                </Button>
              )}
            />
          )}
          <div className="flex justify-between gap-2">
            <Button
              variant="outline"
              className="min-h-11"
              disabled={busy || !history.length}
              onClick={() => {
                setCursor(history.at(-1)!);
                setHistory((h) => h.slice(0, -1));
              }}
            >
              Previous items
            </Button>
            <Button
              variant="outline"
              className="min-h-11"
              disabled={busy || !records.next_cursor}
              onClick={() => {
                setHistory((h) => [...h, cursor]);
                setCursor(records.next_cursor!);
              }}
            >
              Next items
            </Button>
          </div>
        </CardContent>
      </Card>
      <ChangeForm
        key={JSON.stringify(defaults)}
        title="Grant item"
        description={
          chosen
            ? 'Selected: ' +
              display(chosen.name || chosen.item_id || chosen.offer_id) +
              '. Verify the exact ID and variant before saving.'
            : 'Choose a catalog entry above or enter an exact known catalog ID. Optional variant fields must match the catalog.'
        }
        busy={saving}
        defaults={defaults}
        fields={[
          {
            name: 'kind',
            label: 'Item type',
            options: ['offer', 'wardrobe', 'companions', 'locomotions', 'housing'],
          },
          { name: 'item', label: 'Item or offer ID' },
          { name: 'gender', label: 'Gender', optional: true },
          { name: 'category', label: 'Category', optional: true },
        ]}
        submit={(data) =>
          mutate('users/' + encodeURIComponent(accountId) + '/items', {
            kind: data.kind,
            ...(data.kind === 'offer' ? { offer_id: data.item } : { item_id: data.item }),
            ...(data.gender ? { gender: data.gender } : {}),
            ...(data.category ? { category: data.category } : {}),
            reason: data.reason,
          })
        }
      />
    </div>
  );
}
export function PlayerAccount({
  id,
  detail,
  wallet,
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
  wallet: Row;
  tab: PlayerTab;
  actor: { role: string };
  api: (path: string, body?: Row) => Promise<any>;
  mutate: (path: string, body: Row) => Promise<boolean>;
  saving: boolean;
  revision: number;
  refresh: () => void;
}) {
  const base = 'users/' + encodeURIComponent(id),
    canEdit = ['owner', 'admin'].includes(actor.role);
  const names: Record<PlayerTab, string> = {
    summary: 'Summary',
    inventory: 'Inventory',
    purchases: 'Purchases',
    credits: 'Credits',
    moderation: 'Moderation',
    activity: 'Activity',
  };
  return (
    <div className="min-w-0 space-y-3">
      <Button asChild variant="outline" className="min-h-11">
        <a href="#users">Back to players</a>
      </Button>
      <Card>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="min-w-0 break-words text-lg font-semibold [overflow-wrap:anywhere]">
              {display(detail.username)}
            </h3>
            <Badge variant={detail.online === 1 ? 'default' : 'secondary'}>
              {detail.online === 1 ? 'Online' : 'Offline'}
            </Badge>
          </div>
          <p className="break-all text-xs text-muted-foreground">Account ID: {id}</p>
          <div className="grid grid-cols-2 gap-3 border-t pt-3">
            {[
              ['Crystals', wallet.crystals],
              ['Nebula Points', wallet.np],
            ].map(([label, value]) => (
              <div key={String(label)}>
                <p className="text-xs text-muted-foreground">{String(label)}</p>
                <p className="mt-1 text-xl font-semibold tabular-nums">
                  {typeof value === 'number' ? value.toLocaleString() : '—'}
                </p>
              </div>
            ))}
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
          className="grid h-auto w-full grid-cols-3 gap-1 p-1 sm:grid-cols-6"
          aria-label="Player sections"
        >
          {playerTabs.map((value) => (
            <TabsTrigger
              key={value}
              value={value}
              className="min-h-11 min-w-0 px-2 text-xs sm:text-sm"
            >
              {names[value]}
            </TabsTrigger>
          ))}
        </TabsList>
        <TabsContent value="summary" className="space-y-3">
          <Card>
            <CardHeader>
              <CardTitle>Account details</CardTitle>
              <CardDescription>
                Last login is the latest recorded session issue time; online status is the server's
                current presence flag.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Details
                data={{
                  platform: detail.platform,
                  gender: detail.gender,
                  created_at: detail.created_at,
                  last_login_at: detail.last_login_at,
                  last_avatar_save_at: detail.last_avatar_save_at,
                }}
              />
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Manage this player</CardTitle>
              <CardDescription>
                View ownership and purchases, update balances or enforce a moderation policy.
              </CardDescription>
            </CardHeader>
            <CardContent className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {(['inventory', 'purchases', 'credits', 'moderation'] as PlayerTab[]).map((value) => (
                <Button asChild key={value} variant="outline" className="min-h-11">
                  <a href={playerHref(id, value)}>{names[value]}</a>
                </Button>
              ))}
            </CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="inventory" className="space-y-3">
          <PaginatedRecords
            title="Owned items"
            path={base + '/owned'}
            revision={revision}
            load={api}
            columns={['display_name', 'kind', 'item_id', 'gender', 'category', 'granted_at']}
            description="Durable server ownership. A player may need to reopen the relevant menu or rejoin to refresh cached items."
          />
          {canEdit && <CatalogGrant accountId={id} api={api} mutate={mutate} saving={saving} />}
        </TabsContent>
        <TabsContent value="purchases">
          <PaginatedRecords
            title="Purchase history"
            path={base + '/purchases'}
            revision={revision}
            load={api}
            columns={[
              'name',
              'offer_id',
              'source',
              'created_at',
              'current_offer_crystals',
              'current_offer_np',
            ]}
            description="Includes store purchases and offer grants. Prices shown are current catalog prices; original paid prices were not retained."
          />
        </TabsContent>
        <TabsContent value="credits" className="space-y-3">
          {canEdit ? (
            <ChangeForm
              title="Adjust credits"
              description="Positive amounts add funds; negative amounts deduct them. The server saves the balance immediately and records before/after amounts. Players may need to reopen a store to see it."
              busy={saving}
              fields={[
                { name: 'currency', label: 'Currency', options: ['crystals', 'np'] },
                {
                  name: 'delta',
                  label: 'Amount to add or deduct',
                  type: 'number',
                  hint: 'A nonzero whole number. The resulting balance cannot go below zero.',
                },
              ]}
              submit={(data) => {
                const delta = Number(data.delta);
                if (!Number.isSafeInteger(delta) || !delta)
                  return Promise.reject(new Error('Enter a nonzero whole number.'));
                return mutate(base + '/wallet-adjustments', {
                  currency: data.currency,
                  delta,
                  reason: data.reason,
                });
              }}
            />
          ) : (
            <p className="text-sm text-muted-foreground">
              Only admins and owners can change balances. Credit history remains available below.
            </p>
          )}
          <PaginatedRecords
            title="Credit adjustments"
            path={base + '/transactions'}
            revision={revision}
            load={api}
            columns={[
              'currency',
              'delta',
              'before_balance',
              'after_balance',
              'actor_id',
              'reason',
              'created_at',
            ]}
            description="Only this player's operator credit adjustments; store purchases are in Purchases."
          />
        </TabsContent>
        <TabsContent value="moderation">
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
            title="Player activity"
            path={base + '/audit'}
            revision={revision}
            load={api}
            columns={['operation', 'actor_id', 'reason', 'created_at']}
            description="Audited operator changes for this account. Expand before/after to inspect the committed change. This is not a gameplay or chat log."
          />
        </TabsContent>
      </Tabs>
    </div>
  );
}
