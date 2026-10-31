import { useEffect, useState } from 'react';
import type { Row } from '../lib/panel';
import { catalogItemName, catalogOffers, catalogKindLabel } from '../lib/catalog';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from './ui/card';
import { Button } from './ui/button';
import { Badge } from './ui/badge';
import { Input } from './ui/input';
import { Label } from './ui/label';
import { Alert, AlertDescription } from './ui/alert';
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from './ui/sheet';
import { FormSelect } from './form-select';
import { ChangeForm, Details, empty, type List } from './management-widgets';
import { ItemRecords } from './item-records';
import { CatalogPreview } from './catalog-workspace';

const types = [
  { value: '0', label: 'Clothing & customization' },
  { value: '1', label: 'Companions' },
  { value: '2', label: 'Furniture' },
  { value: '3', label: 'Locomotions' },
];
const visibility = [
  { value: 'true', label: 'Available in game' },
  { value: 'false', label: 'Hidden from sale' },
];
const yesNo = [
  { value: 'true', label: 'Yes' },
  { value: 'false', label: 'No' },
];
const kinds = ['wardrobe', 'companions', 'housing', 'locomotions'];
function price(value: string) {
  if (!/^(0|[1-9][0-9]*)$/.test(value) || Number(value) > 2147483647)
    throw new Error('Prices must be whole numbers from 0 to 2,147,483,647.');
  return Number(value);
}

export function StoresWorkspace({
  actor,
  api,
  revision,
  selectedId,
  mutate,
  saving,
}: {
  actor: { role: string };
  api: (path: string) => Promise<any>;
  revision: number;
  selectedId: string;
  mutate: (path: string, body: Row) => Promise<boolean>;
  saving: boolean;
}) {
  const canEdit = ['owner', 'admin'].includes(actor.role);
  const [stores, setStores] = useState<List>(empty),
    [storeCursor, setStoreCursor] = useState(''),
    [storeHistory, setStoreHistory] = useState<string[]>([]),
    [storeSearch, setStoreSearch] = useState(''),
    [storeQuery, setStoreQuery] = useState(''),
    [detail, setDetail] = useState<Row | null>(null),
    [error, setError] = useState(''),
    [loading, setLoading] = useState(false),
    [createId, setCreateId] = useState('');
  const [offers, setOffers] = useState<List>(empty),
    [cursor, setCursor] = useState(''),
    [history, setHistory] = useState<string[]>([]),
    [search, setSearch] = useState(''),
    [query, setQuery] = useState(''),
    [editing, setEditing] = useState<Row | null>(null),
    [adding, setAdding] = useState(false),
    [assets, setAssets] = useState<List>(empty),
    [assetQuery, setAssetQuery] = useState(''),
    [assetSearch, setAssetSearch] = useState(''),
    [assetCursor, setAssetCursor] = useState(''),
    [assetHistory, setAssetHistory] = useState<string[]>([]);
  const id = selectedId || String(stores.items[0]?.shop_id || '');
  const kind = String(detail?.kind || kinds[Number(detail?.type_shop)] || 'wardrobe');
  useEffect(() => {
    let current = true;
    setError('');
    api(
      'stores?' + new URLSearchParams({ limit: '100', cursor: storeCursor || '0', q: storeSearch }),
    )
      .then((data) => {
        if (current) setStores(data);
      })
      .catch((e) => {
        if (current) setError(e.message);
      });
    return () => {
      current = false;
    };
  }, [api, revision, storeCursor, storeSearch]);
  useEffect(() => {
    setCursor('');
    setHistory([]);
    setSearch('');
    setQuery('');
    setEditing(null);
    setAdding(false);
  }, [id]);
  useEffect(() => {
    let current = true;
    setDetail(null);
    setError('');
    if (id)
      api('stores/' + encodeURIComponent(id))
        .then((data) => {
          if (current) setDetail(data);
        })
        .catch((e) => {
          if (current) setError(e.message);
        });
    return () => {
      current = false;
    };
  }, [api, id, revision]);
  useEffect(() => {
    let current = true;
    setLoading(true);
    setError('');
    if (!id) {
      setOffers(empty);
      setLoading(false);
      return;
    }
    api(
      'catalog?' +
        new URLSearchParams({
          kind: 'offer',
          store_id: id,
          limit: '25',
          q: search,
          cursor: cursor || '0',
        }),
    )
      .then((data) => {
        if (current) setOffers(data);
      })
      .catch((e) => {
        if (current) setError(e.message);
      })
      .finally(() => {
        if (current) setLoading(false);
      });
    return () => {
      current = false;
    };
  }, [api, id, revision, search, cursor]);
  useEffect(() => {
    let current = true;
    if (adding && detail)
      api(
        'catalog?' +
          new URLSearchParams({ kind, q: assetSearch, limit: '5', cursor: assetCursor || '0' }),
      )
        .then((data) => {
          if (current) setAssets(data);
        })
        .catch((e) => {
          if (current) setError(e.message);
        });
    return () => {
      current = false;
    };
  }, [api, adding, kind, detail, assetSearch, assetCursor]);
  const navigate = (target: string) => {
    window.location.hash = '#stores/' + encodeURIComponent(target);
  };
  const storeOptions = stores.items.map((row) => ({
    value: String(row.shop_id),
    label: String(row.name),
  }));
  if (id && !storeOptions.some((row) => row.value === id))
    storeOptions.unshift({ value: id, label: String(detail?.name || id) });
  const destinationOptions = stores.items
    .filter((row) => Number(row.type_shop) === Number(detail?.type_shop))
    .map((row) => ({ value: String(row.shop_id), label: String(row.name) }));
  if (detail && !destinationOptions.some((row) => row.value === id))
    destinationOptions.unshift({ value: id, label: String(detail.name) });
  return (
    <div className="min-w-0 space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>Stores & listings</CardTitle>
          <CardDescription>
            These are the stores the game loads from this server. Changes are saved immediately and
            appear when players next reopen or refresh the shop. Hiding a listing keeps ownership
            and purchase history.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <form
            className="flex flex-wrap gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              setStoreSearch(storeQuery);
              setStoreCursor('');
              setStoreHistory([]);
            }}
          >
            <Label className="sr-only" htmlFor="store-search">
              Find stores
            </Label>
            <Input
              id="store-search"
              className="min-h-9 min-w-0 flex-1"
              value={storeQuery}
              onChange={(e) => setStoreQuery(e.target.value)}
              placeholder="Search store names"
              maxLength={128}
            />
            <Button variant="outline" className="min-h-9">
              Find stores
            </Button>
            {canEdit && (
              <Button
                type="button"
                className="min-h-9"
                onClick={() => setCreateId('store-' + crypto.randomUUID())}
              >
                Create store
              </Button>
            )}
          </form>
          <Label htmlFor="managed-store">Store</Label>
          {storeOptions.length ? (
            <FormSelect
              id="managed-store"
              value={id}
              options={storeOptions}
              onValueChange={navigate}
            />
          ) : (
            <p className="text-sm text-muted-foreground">No stores match this search.</p>
          )}
          {(storeHistory.length > 0 || stores.next_cursor) && (
            <div className="flex flex-wrap gap-2">
              <Button
                variant="outline"
                disabled={!storeHistory.length}
                onClick={() => {
                  setStoreCursor(storeHistory.at(-1)!);
                  setStoreHistory((h) => h.slice(0, -1));
                }}
              >
                Previous stores
              </Button>
              <Button
                variant="outline"
                disabled={!stores.next_cursor}
                onClick={() => {
                  setStoreHistory((h) => [...h, storeCursor]);
                  setStoreCursor(stores.next_cursor!);
                }}
              >
                More stores
              </Button>
            </div>
          )}
          {detail && (
            <div className="flex flex-wrap gap-2">
              <Badge variant={detail.active ? 'default' : 'secondary'}>
                {detail.active ? 'Visible in game' : 'Store hidden'}
              </Badge>
              <Badge variant="outline">{catalogKindLabel(kind)}</Badge>
              <Badge variant="secondary">
                {Number(detail.total_offers || 0).toLocaleString()} listings
              </Badge>
            </div>
          )}
        </CardContent>
      </Card>
      {error && (
        <Alert variant="destructive" role="alert">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      {detail && canEdit ? (
        <ChangeForm
          key={id + ':' + revision}
          title="Save store"
          busy={saving}
          description="Names and descriptions are operator labels, not recovered historical metadata. A store's collection cannot change while it has listings."
          confirmationLabel="I checked this store and change."
          defaults={{
            name: String(detail.name),
            description: String(detail.description || ''),
            active: String(Boolean(detail.active)),
          }}
          fields={[
            { name: 'name', label: 'Store name' },
            { name: 'description', label: 'Description', optional: true },
            { name: 'active', label: 'Availability', options: visibility },
          ]}
          submit={(data) =>
            mutate('stores/' + encodeURIComponent(id), {
              name: data.name,
              description: data.description,
              active: data.active === 'true',
              reason: data.reason,
            })
          }
        />
      ) : detail ? (
        <Card>
          <CardHeader>
            <CardTitle>{String(detail.name)}</CardTitle>
            <CardDescription>Only admins and owners can change stores.</CardDescription>
          </CardHeader>
          <CardContent>
            <Details
              data={{ description: detail.description, collection: catalogKindLabel(kind) }}
            />
          </CardContent>
        </Card>
      ) : null}
      {detail && (
        <Card>
          <CardHeader>
            <CardTitle>
              Store listings <Badge variant="secondary">{offers.total}</Badge>
            </CardTitle>
            <CardDescription>
              Current server prices and availability. Original commercial names and prices may be
              unrecovered.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <form
              className="flex flex-wrap gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                setSearch(query);
                setCursor('');
                setHistory([]);
              }}
            >
              <Label className="sr-only" htmlFor="listing-search">
                Search listings
              </Label>
              <Input
                id="listing-search"
                className="min-h-9 min-w-0 flex-1"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Listing name or item ID"
                maxLength={128}
              />
              <Button variant="outline" className="min-h-9">
                Search listings
              </Button>
              {canEdit && (
                <Button
                  type="button"
                  className="min-h-9"
                  onClick={() => {
                    setAssetCursor('');
                    setAssetHistory([]);
                    setAssetSearch('');
                    setAssetQuery('');
                    setAdding(true);
                  }}
                >
                  Add item
                </Button>
              )}
            </form>
            {loading ? (
              <p role="status">Loading listings...</p>
            ) : (
              <ItemRecords
                items={offers.items}
                action={
                  canEdit
                    ? (row) => (
                        <Button
                          variant="outline"
                          className="min-h-9"
                          onClick={() => setEditing({ ...row, existing: true })}
                        >
                          Edit listing
                        </Button>
                      )
                    : undefined
                }
              />
            )}
            <div className="flex justify-between gap-2">
              <Button
                variant="outline"
                disabled={loading || !history.length}
                onClick={() => {
                  setCursor(history.at(-1)!);
                  setHistory((h) => h.slice(0, -1));
                }}
              >
                Previous listings
              </Button>
              <Button
                variant="outline"
                disabled={loading || !offers.next_cursor}
                onClick={() => {
                  setHistory((h) => [...h, cursor]);
                  setCursor(offers.next_cursor!);
                }}
              >
                Next listings
              </Button>
            </div>
          </CardContent>
        </Card>
      )}
      <Sheet
        open={Boolean(createId)}
        onOpenChange={(open) => {
          if (!open && !saving) setCreateId('');
        }}
      >
        <SheetContent className="w-full overflow-y-auto sm:max-w-xl">
          <SheetHeader>
            <SheetTitle>Create store</SheetTitle>
            <SheetDescription>
              Choose a game collection. Only matching recovered items can be listed.
            </SheetDescription>
          </SheetHeader>
          <div className="p-4">
            <ChangeForm
              key={createId}
              title="Create store"
              busy={saving}
              confirmationLabel="I checked this store and change."
              description="This creates a preservation store, not an original historical store."
              defaults={{ type_shop: '0', active: 'false' }}
              fields={[
                { name: 'name', label: 'Store name' },
                { name: 'type_shop', label: 'Collection', options: types },
                { name: 'description', label: 'Description', optional: true },
                { name: 'active', label: 'Availability', options: visibility },
              ]}
              submit={async (data) => {
                const ok = await mutate('stores/' + createId, {
                  type_shop: Number(data.type_shop),
                  name: data.name,
                  description: data.description,
                  active: data.active === 'true',
                  reason: data.reason,
                });
                if (ok) {
                  navigate(createId);
                  setCreateId('');
                }
                return ok;
              }}
            />
          </div>
        </SheetContent>
      </Sheet>
      <Sheet
        open={adding}
        onOpenChange={(open) => {
          if (!saving) setAdding(open);
        }}
      >
        <SheetContent className="w-full overflow-y-auto sm:max-w-2xl">
          <SheetHeader>
            <SheetTitle>Add an item to {String(detail?.name || 'this store')}</SheetTitle>
            <SheetDescription>
              Choose a recovered {catalogKindLabel(kind).toLowerCase()} item. Set its listing name,
              price and availability next.
            </SheetDescription>
          </SheetHeader>
          <div className="space-y-3 p-4">
            <form
              className="flex flex-wrap gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                setAssetSearch(assetQuery);
                setAssetCursor('');
                setAssetHistory([]);
              }}
            >
              <Label className="sr-only" htmlFor="store-asset-search">
                Find recovered items
              </Label>
              <Input
                id="store-asset-search"
                className="min-h-9 min-w-0 flex-1"
                value={assetQuery}
                onChange={(e) => setAssetQuery(e.target.value)}
                maxLength={128}
                placeholder="Category or exact item ID"
              />
              <Button variant="outline" className="min-h-9">
                Find items
              </Button>
            </form>
            <ItemRecords
              items={assets.items}
              action={(row) => {
                const listed = catalogOffers(row).some((offer) => offer.shop_id === id);
                return (
                  <Button
                    variant="outline"
                    className="min-h-9"
                    disabled={listed || saving}
                    onClick={() => {
                      setAdding(false);
                      setEditing({
                        ...row,
                        offer_id: 'offer-' + crypto.randomUUID(),
                        name: catalogItemName(row),
                        shop_id: id,
                        active: false,
                        featured: false,
                        crystals: '',
                        np: '',
                      });
                    }}
                  >
                    {listed ? 'Already listed here' : 'Set listing details'}
                  </Button>
                );
              }}
            />
            <div className="flex justify-between gap-2">
              <Button
                variant="outline"
                disabled={!assetHistory.length}
                onClick={() => {
                  setAssetCursor(assetHistory.at(-1)!);
                  setAssetHistory((h) => h.slice(0, -1));
                }}
              >
                Previous items
              </Button>
              <Button
                variant="outline"
                disabled={!assets.next_cursor}
                onClick={() => {
                  setAssetHistory((h) => [...h, assetCursor]);
                  setAssetCursor(assets.next_cursor!);
                }}
              >
                Next items
              </Button>
            </div>
          </div>
        </SheetContent>
      </Sheet>
      <Sheet
        open={Boolean(editing)}
        onOpenChange={(open) => {
          if (!open && !saving) setEditing(null);
        }}
      >
        <SheetContent className="w-full overflow-y-auto sm:max-w-xl">
          <SheetHeader>
            <SheetTitle>{editing?.existing ? 'Edit listing' : 'Create listing'}</SheetTitle>
            <SheetDescription>
              Changes affect the next store fetch. Saved ownership and past purchases remain intact.
            </SheetDescription>
          </SheetHeader>
          {editing && (
            <div className="space-y-3 p-4">
              <div className="mx-auto w-28">
                <CatalogPreview row={editing} />
              </div>
              <ChangeForm
                key={String(editing.offer_id)}
                title="Save listing"
                description="This name is your server's listing label. It does not establish the item's original commercial name. Zero is a free price; enter both currency prices explicitly."
                busy={saving}
                confirmationLabel="I checked this listing, prices and availability."
                defaults={{
                  name: String(editing.name),
                  shop_id: String(editing.shop_id),
                  crystals: String(editing.crystals ?? ''),
                  np: String(editing.np ?? ''),
                  active: String(Boolean(editing.active)),
                  featured: String(Boolean(editing.featured)),
                }}
                fields={[
                  { name: 'name', label: 'Listing name' },
                  { name: 'shop_id', label: 'Store', options: destinationOptions },
                  { name: 'crystals', label: 'Crystal price', type: 'number' },
                  { name: 'np', label: 'Nebula Points price', type: 'number' },
                  { name: 'active', label: 'Availability', options: visibility },
                  { name: 'featured', label: 'Featured', options: yesNo },
                ]}
                submit={async (data) => {
                  const body: Row = {
                    name: data.name,
                    shop_id: data.shop_id,
                    crystals: price(data.crystals),
                    np: price(data.np),
                    active: data.active === 'true',
                    featured: data.featured === 'true',
                    reason: data.reason,
                  };
                  if (!editing.existing)
                    Object.assign(body, {
                      kind: editing.kind,
                      item_id: editing.item_id,
                      ...(editing.kind === 'wardrobe'
                        ? { gender: editing.gender, category: editing.category }
                        : {}),
                    });
                  const ok = await mutate(
                    'store-offers/' + encodeURIComponent(String(editing.offer_id)),
                    body,
                  );
                  if (ok) setEditing(null);
                  return ok;
                }}
              />
              <Details
                data={{
                  item_id: editing.item_id,
                  collection: catalogKindLabel(editing.kind),
                  offer_id: editing.offer_id,
                }}
              />
            </div>
          )}
        </SheetContent>
      </Sheet>
    </div>
  );
}
