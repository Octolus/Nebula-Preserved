import { useEffect, useState } from 'react';
import { IconPackage } from '@tabler/icons-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from './ui/card';
import { Button } from './ui/button';
import { Input } from './ui/input';
import { Label } from './ui/label';
import { Badge } from './ui/badge';
import { Alert, AlertDescription } from './ui/alert';
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
  SheetClose,
} from './ui/sheet';
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from './ui/accordion';
import { FormSelect } from './form-select';
import { RecordList } from './record-list';
import { Details } from './management-widgets';
import type { Row } from '../lib/panel';
import {
  catalogAvailability,
  catalogItemName,
  catalogKindLabel,
  catalogKinds,
  catalogOffers,
  catalogPrice,
  catalogQuery,
  provenanceLabel,
} from '../lib/catalog';

type CatalogPage = {
  items: Row[];
  total: number;
  next_cursor: string | null;
  counts?: Record<string, number>;
  filters?: {
    genders?: string[];
    categories?: { value: string; label: string }[];
    stores?: { id: string; name: string; type_shop: number }[];
  };
  metadata_note?: string;
};
const empty: CatalogPage = { items: [], total: 0, next_cursor: null };
const any = '__any__';

function CatalogItem({ row, selectStore }: { row: Row; selectStore: (id: string) => void }) {
  const offers = catalogOffers(row);
  const provenance =
    row.provenance && typeof row.provenance === 'object' ? (row.provenance as Row) : {};
  const sourceMetadata = {
    ...(row.asset_metadata &&
    typeof row.asset_metadata === 'object' &&
    !Array.isArray(row.asset_metadata)
      ? (row.asset_metadata as Row)
      : {}),
    ...Object.fromEntries(
      [
        'bundle_size',
        'dependencies',
        'category_evidence',
        'store_category',
        'store_category_source',
        'thumbnail_source',
        'own_thumbnail_known',
      ]
        .filter((key) => row[key] !== undefined)
        .map((key) => [key, row[key]]),
    ),
  };
  const details = Object.fromEntries(
    [
      ['item_id', row.item_id],
      ['offer_id', row.offer_id],
      ['kind', catalogKindLabel(row.kind)],
      ['gender', row.gender],
      ['category', row.category_label || row.category],
      ['category_id', row.category],
      ['bundle', row.bundle],
      ['asset_path', row.asset_path],
      ['resource_path', row.resource_path],
      ['thumbnail_path', row.thumbnail_path],
      ['source_catalog', row.source_catalog],
      ['manifest_sha256', row.manifest_sha256],
      ['placement_cost', row.placement_cost],
      ['placement_behaviour', row.placement_behaviour],
    ].filter(([, value]) => value !== undefined && value !== null && value !== ''),
  );
  return (
    <Sheet>
      <SheetTrigger asChild>
        <Button
          variant="outline"
          className="min-h-11"
          aria-label={'Inspect ' + catalogItemName(row)}
        >
          Inspect item
        </Button>
      </SheetTrigger>
      <SheetContent className="w-full overflow-hidden sm:w-full sm:max-w-2xl [&>button]:top-2 [&>button]:right-2 [&>button]:flex [&>button]:size-11 [&>button]:items-center [&>button]:justify-center">
        <SheetHeader className="shrink-0 border-b pr-16">
          <SheetTitle className="break-words [overflow-wrap:anywhere]">
            {catalogItemName(row)}
          </SheetTitle>
          <SheetDescription>
            {row.kind === 'shop_artwork'
              ? 'Recovered shop artwork reference. This does not establish a historical store or link any item to a brand.'
              : "Recovered asset metadata and the current server's store configuration."}
          </SheetDescription>
        </SheetHeader>
        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 pb-5">
          <div className="flex flex-wrap gap-2">
            <Badge variant="secondary">{catalogKindLabel(row.kind)}</Badge>
            <Badge variant={catalogAvailability(row) === 'In store' ? 'default' : 'outline'}>
              {catalogAvailability(row)}
            </Badge>
          </div>
          <div className="flex gap-3 rounded-md border bg-muted/30 p-3 text-sm text-muted-foreground">
            <IconPackage className="mt-0.5 size-5 shrink-0" aria-hidden="true" />
            <p>
              Item artwork remains in the player's game installation. Asset and thumbnail references
              below identify the shipped files; no preview image is published here.
            </p>
          </div>
          {row.unavailable_reason ? (
            <Alert>
              <AlertDescription>{String(row.unavailable_reason)}</AlertDescription>
            </Alert>
          ) : null}
          <Details data={details} />
          <Card className="gap-3 py-3 shadow-none">
            <CardHeader className="px-3">
              <CardTitle className="text-sm">Stores & price options</CardTitle>
              <CardDescription>
                These are this server's current offers. Historical store assignments and prices are
                shown only when recovered.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-2 px-3">
              {offers.length ? (
                offers.map((offer, index) => (
                  <div
                    key={String(offer.offer_id || index)}
                    className="space-y-1 rounded-md border p-3 text-sm"
                  >
                    <p className="break-words font-medium">
                      {String(offer.shop_name || offer.shop_id || 'Store')}
                    </p>
                    <p>{catalogPrice(offer)}</p>
                    <p className="break-all text-xs text-muted-foreground">
                      Offer: {String(offer.offer_id || 'Not supplied')}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      Assignment: {provenanceLabel(offer.store_assignment_source)} · Price:{' '}
                      {provenanceLabel(offer.price_source)}
                    </p>
                    {offer.active === false ||
                    offer.active === 0 ||
                    offer.store_active === false ? (
                      <Badge variant="outline">
                        {offer.store_active === false ? 'Store inactive' : 'Offer inactive'}
                      </Badge>
                    ) : null}
                    {typeof offer.shop_id === 'string' && (
                      <SheetClose asChild>
                        <Button
                          variant="link"
                          className="h-auto min-h-11 max-w-full justify-start whitespace-normal px-0 text-left"
                          onClick={() => selectStore(String(offer.shop_id))}
                        >
                          Browse this store
                        </Button>
                      </SheetClose>
                    )}
                  </div>
                ))
              ) : (
                <p className="text-sm text-muted-foreground">
                  {row.grantable === false
                    ? 'This is a reference record and cannot be granted or purchased.'
                    : 'No offer is currently configured for this item. Validated items can still be granted from a player account.'}
                </p>
              )}
            </CardContent>
          </Card>
          <Accordion type="single" collapsible>
            <AccordionItem value="provenance">
              <AccordionTrigger className="min-h-11">Metadata sources & limits</AccordionTrigger>
              <AccordionContent className="space-y-3">
                <Details
                  data={Object.fromEntries(
                    Object.entries(provenance).map(([key, value]) => [
                      key === 'display_name' ? 'display_name_source' : key,
                      provenanceLabel(value),
                    ]),
                  )}
                />
                <p className="text-sm text-muted-foreground">
                  An asset identifier proves that a matching resource was cataloged. It does not
                  prove its original commercial name, price, bundle contents or store brand, or that
                  it has passed native in-game testing.
                </p>
              </AccordionContent>
            </AccordionItem>
            {Object.keys(sourceMetadata).length > 0 && (
              <AccordionItem value="source">
                <AccordionTrigger className="min-h-11">Recovered source metadata</AccordionTrigger>
                <AccordionContent>
                  <Details data={sourceMetadata} />
                </AccordionContent>
              </AccordionItem>
            )}
            <AccordionItem value="record">
              <AccordionTrigger className="min-h-11">
                All available catalog metadata
              </AccordionTrigger>
              <AccordionContent>
                <Details data={row} />
              </AccordionContent>
            </AccordionItem>
          </Accordion>
          {row.grantable !== false && (
            <SheetClose asChild>
              <Button asChild variant="outline" className="min-h-11">
                <a href="#users">Find a player to grant items</a>
              </Button>
            </SheetClose>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}

export function CatalogWorkspace({
  api,
  revision,
}: {
  api: (path: string) => Promise<CatalogPage>;
  revision: number;
}) {
  const [kind, setKind] = useState('all'),
    [query, setQuery] = useState(''),
    [search, setSearch] = useState('');
  const [gender, setGender] = useState(''),
    [category, setCategory] = useState(''),
    [store, setStore] = useState('');
  const [cursor, setCursor] = useState(''),
    [history, setHistory] = useState<string[]>([]);
  const [page, setPage] = useState<CatalogPage>(empty),
    [busy, setBusy] = useState(true),
    [error, setError] = useState('');
  function firstPage() {
    setCursor('');
    setHistory([]);
  }
  useEffect(() => {
    let current = true;
    setBusy(true);
    setError('');
    api(catalogQuery({ kind, search, gender, category, store, cursor }))
      .then((data) => {
        if (current) setPage(data);
      })
      .catch((failure) => {
        if (current) setError((failure as Error).message);
      })
      .finally(() => {
        if (current) setBusy(false);
      });
    return () => {
      current = false;
    };
  }, [api, revision, kind, search, gender, category, store, cursor]);
  const filters = page.filters || {};
  const rows = page.items.map((row) => ({
    ...row,
    display_name: catalogItemName(row),
    collection: catalogKindLabel(row.kind),
    category_label: row.category_label || row.category || '—',
    availability: catalogAvailability(row),
  }));
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          Game items{' '}
          <Badge variant="secondary" aria-live="polite">
            {busy ? 'Loading…' : page.total.toLocaleString() + ' matches'}
          </Badge>
        </CardTitle>
        <CardDescription>
          Browse recovered assets separately from configured store offers. Preservation labels,
          store groupings and prices are marked; original commercial metadata may be unavailable.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap gap-2" aria-label="Catalog collections">
          {catalogKinds
            .filter(
              (entry) => entry.value !== 'shop_artwork' || page.counts?.shop_artwork !== undefined,
            )
            .map((entry) => (
              <Button
                key={entry.value}
                variant={kind === entry.value ? 'default' : 'outline'}
                className="min-h-11 max-w-full whitespace-normal"
                aria-pressed={kind === entry.value}
                onClick={() => {
                  setKind(entry.value);
                  setGender('');
                  setCategory('');
                  setStore('');
                  firstPage();
                }}
              >
                {entry.label}
                {page.counts?.[entry.value] !== undefined && (
                  <Badge variant="secondary">{page.counts[entry.value].toLocaleString()}</Badge>
                )}
              </Button>
            ))}
        </div>
        <form
          className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4"
          onSubmit={(event) => {
            event.preventDefault();
            setSearch(query.trim());
            firstPage();
          }}
        >
          <div className="space-y-1.5 sm:col-span-2">
            <Label htmlFor="catalog-search">Search items</Label>
            <Input
              id="catalog-search"
              className="min-h-11"
              maxLength={128}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Item ID, label, category or store"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="catalog-gender">Character</Label>
            <FormSelect
              id="catalog-gender"
              value={gender || any}
              options={[
                { value: any, label: 'All characters' },
                ...(filters.genders || []).map((value) => ({
                  value,
                  label: value === 'MALE' ? 'Male' : value === 'FEMALE' ? 'Female' : value,
                })),
              ]}
              onValueChange={(value) => {
                setGender(value === any ? '' : value);
                firstPage();
              }}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="catalog-category">Category</Label>
            <FormSelect
              id="catalog-category"
              value={category || any}
              options={[{ value: any, label: 'All categories' }, ...(filters.categories || [])]}
              onValueChange={(value) => {
                setCategory(value === any ? '' : value);
                firstPage();
              }}
            />
          </div>
          <div className="space-y-1.5 sm:col-span-2">
            <Label htmlFor="catalog-store">Store</Label>
            <FormSelect
              id="catalog-store"
              value={store || any}
              options={[
                { value: any, label: 'All stores' },
                ...(filters.stores || []).map((value) => ({ value: value.id, label: value.name })),
              ]}
              onValueChange={(value) => {
                setStore(value === any ? '' : value);
                firstPage();
              }}
            />
          </div>
          <div className="flex flex-wrap items-end gap-2 sm:col-span-2">
            <Button variant="outline" className="min-h-11" disabled={busy}>
              Search
            </Button>
            <Button
              type="button"
              variant="ghost"
              className="min-h-11"
              onClick={() => {
                setQuery('');
                setSearch('');
                setGender('');
                setCategory('');
                setStore('');
                firstPage();
              }}
            >
              Clear filters
            </Button>
          </div>
        </form>
        {page.metadata_note && (
          <p className="text-xs text-muted-foreground">{page.metadata_note}</p>
        )}
        {error ? (
          <Alert variant="destructive" role="alert">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : busy ? (
          <p role="status" className="py-4 text-sm text-muted-foreground">
            Loading catalog…
          </p>
        ) : (
          <RecordList
            items={rows}
            columns={
              kind === 'offer'
                ? ['display_name', 'shop_name', 'collection', 'crystals', 'np', 'availability']
                : kind === 'shop_artwork'
                  ? ['display_name', 'resource_path', 'availability']
                  : ['display_name', 'collection', 'gender', 'category_label', 'availability']
            }
            emptyText="No items match these filters. Try clearing a filter or searching an exact item ID."
            action={(row) => (
              <CatalogItem
                row={row}
                selectStore={(id) => {
                  setKind('offer');
                  setStore(id);
                  setGender('');
                  setCategory('');
                  setQuery('');
                  setSearch('');
                  firstPage();
                }}
              />
            )}
          />
        )}
        <div className="flex items-center justify-between gap-2">
          <Button
            variant="outline"
            className="min-h-11"
            disabled={busy || !history.length}
            onClick={() => {
              setCursor(history.at(-1)!);
              setHistory((values) => values.slice(0, -1));
            }}
          >
            Previous
          </Button>
          <p className="text-xs text-muted-foreground" aria-live="polite">
            {busy ? 'Loading' : page.items.length + ' shown'}
          </p>
          <Button
            variant="outline"
            className="min-h-11"
            disabled={busy || !page.next_cursor}
            onClick={() => {
              setHistory((values) => [...values, cursor]);
              setCursor(page.next_cursor!);
            }}
          >
            Next
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
