import { useEffect, useState } from 'react';
import { IconPackage, IconLayoutGrid, IconList } from '@tabler/icons-react';
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
  catalogCategoryLabel,
  catalogGenderLabel,
  catalogPreviewUrl,
  catalogLiveOffers,
  catalogPriceSummary,
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

function CatalogPreview({ row, large = false }: { row: Row; large?: boolean }) {
  const url = catalogPreviewUrl(row);
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [url]);
  return (
    <div
      className={
        'relative flex aspect-square items-center justify-center overflow-hidden rounded-md bg-muted/40 ' +
        (large ? 'mx-auto w-full max-w-sm' : 'w-full')
      }
    >
      {url && !failed ? (
        <>
          <img
            src={url}
            alt={catalogItemName(row)}
            loading="lazy"
            decoding="async"
            width={320}
            height={320}
            className="size-full object-contain p-3"
            onError={() => setFailed(true)}
          />
          {row.own_thumbnail_known === false && (
            <span className="absolute inset-x-1 bottom-1 rounded bg-background/90 px-2 py-1 text-center text-xs text-muted-foreground">
              Shared category icon
            </span>
          )}
        </>
      ) : (
        <div className="flex flex-col items-center gap-2 p-4 text-center text-muted-foreground">
          <IconPackage className="size-9" aria-hidden="true" />
          <span className="text-xs">
            {failed ? 'Preview could not load' : 'Preview not recovered'}
          </span>
        </div>
      )}
    </div>
  );
}

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
      ['gender', catalogGenderLabel(row.gender)],
      ['category', catalogCategoryLabel(row)],
      ['category_id', row.category],
      ['bundle', row.bundle],
      ['asset_path', row.asset_path],
      ['resource_path', row.resource_path],
      ['thumbnail_path', row.thumbnail_path],
      ['source_catalog', row.source_catalog],
      ['manifest_sha256', row.manifest_sha256],
      ['placement_cost', row.placement_cost],
      ['placement_behaviour', row.placement_behaviour],
      [
        'display_name_source',
        row.display_name_source ||
          (catalogItemName(row) !== row.name
            ? 'Derived from recovered category, character and item ID'
            : provenance.display_name),
      ],
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
          <CatalogPreview row={row} large />
          <p className="text-xs text-muted-foreground">
            {catalogPreviewUrl(row)
              ? 'Recovered game preview. Names derived from category and item ID are descriptive labels; original commercial names may be unknown.'
              : 'No matching preview is available. Resource references remain available in the recovered metadata below.'}
          </p>
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
  const [view, setView] = useState<'cards' | 'list'>('cards');
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
  const rows: Row[] = page.items.map((row) => ({
    ...row,
    display_name: catalogItemName(row),
    collection: catalogKindLabel(row.kind),
    category_label: catalogCategoryLabel(row),
    character: catalogGenderLabel(row.gender),
    current_price: catalogPriceSummary(row),
    availability: catalogAvailability(row),
  }));
  function selectStore(id: string) {
    setKind('offer');
    setStore(id);
    setGender('');
    setCategory('');
    setQuery('');
    setSearch('');
    firstPage();
  }
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
                  label: catalogGenderLabel(value),
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
              options={[
                { value: any, label: 'All categories' },
                ...(filters.categories || []).map((entry) => ({
                  value: entry.value,
                  label: catalogCategoryLabel({
                    category_label: entry.label,
                    category: entry.value,
                  }),
                })),
              ]}
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
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-xs text-muted-foreground">
            Current server prices ·{' '}
            {kind === 'shop_artwork'
              ? 'Artwork references cannot be purchased'
              : 'Select an item for stores, currencies and recovered details'}
          </p>
          <div className="flex gap-1" aria-label="Catalog view">
            <Button
              variant={view === 'cards' ? 'secondary' : 'ghost'}
              className="min-h-11"
              aria-pressed={view === 'cards'}
              onClick={() => setView('cards')}
            >
              <IconLayoutGrid className="size-4" aria-hidden="true" />
              Cards
            </Button>
            <Button
              variant={view === 'list' ? 'secondary' : 'ghost'}
              className="min-h-11"
              aria-pressed={view === 'list'}
              onClick={() => setView('list')}
            >
              <IconList className="size-4" aria-hidden="true" />
              Compact list
            </Button>
          </div>
        </div>
        {error ? (
          <Alert variant="destructive" role="alert">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : busy ? (
          <p role="status" className="py-4 text-sm text-muted-foreground">
            Loading catalog…
          </p>
        ) : view === 'cards' ? (
          rows.length ? (
            <div
              className="grid grid-cols-1 gap-3 min-[360px]:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4"
              aria-label="Catalog item cards"
            >
              {rows.map((row) => {
                const offers = catalogLiveOffers(row);
                const stores = [
                  ...new Set(offers.map((offer) => String(offer.shop_name || 'Store'))),
                ];
                return (
                  <Card
                    key={String(row.offer_id || row.item_id)}
                    className="min-w-0 gap-3 overflow-hidden py-0 shadow-none"
                  >
                    <div className="p-2 pb-0">
                      <CatalogPreview row={row} />
                    </div>
                    <CardContent className="flex flex-1 flex-col gap-2 px-3 pb-3">
                      <div>
                        <p className="break-words text-sm font-medium leading-snug">
                          {catalogItemName(row)}
                        </p>
                        <p className="mt-1 text-xs text-muted-foreground">
                          {catalogGenderLabel(row.gender)} · {catalogCategoryLabel(row)}
                        </p>
                      </div>
                      <Badge
                        className="max-w-full whitespace-normal text-left"
                        variant={catalogAvailability(row) === 'In store' ? 'secondary' : 'outline'}
                      >
                        {catalogAvailability(row)}
                      </Badge>
                      {kind !== 'shop_artwork' && (
                        <div className="space-y-1 text-xs">
                          <p className="font-medium">{catalogPriceSummary(row)}</p>
                          <p className="break-words text-muted-foreground">
                            {stores[0] || 'No active store offer'}
                            {stores.length > 1 ? ` +${stores.length - 1} more` : ''}
                          </p>
                        </div>
                      )}
                      <div className="mt-auto pt-1 [&>button]:w-full">
                        <CatalogItem row={row} selectStore={selectStore} />
                      </div>
                    </CardContent>
                  </Card>
                );
              })}
            </div>
          ) : (
            <p className="py-6 text-sm text-muted-foreground">
              No items match these filters. Try clearing a filter or searching an exact item ID.
            </p>
          )
        ) : (
          <RecordList
            items={rows}
            columns={
              kind === 'offer'
                ? ['display_name', 'shop_name', 'current_price', 'availability']
                : kind === 'shop_artwork'
                  ? ['display_name', 'resource_path', 'availability']
                  : ['display_name', 'character', 'category_label', 'current_price', 'availability']
            }
            emptyText="No items match these filters. Try clearing a filter or searching an exact item ID."
            action={(row) => <CatalogItem row={row} selectStore={selectStore} />}
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
