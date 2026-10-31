import type { ReactNode } from 'react';
import type { Row } from '../lib/panel';
import { formatCell, playerHref, relative } from '../lib/panel';
import {
  catalogItemName,
  catalogCategoryLabel,
  catalogGenderLabel,
  catalogKindLabel,
  catalogPrice,
  catalogPriceSummary,
} from '../lib/catalog';
import { CatalogPreview, CatalogItem } from './catalog-workspace';

/** Shared item identity for inventory, grants and listings; opaque IDs stay in details. */
export function ItemRecords({
  items,
  action,
  granted = false,
  emptyText = 'No items found.',
}: {
  items: Row[];
  action?: (row: Row) => ReactNode;
  granted?: boolean;
  emptyText?: string;
}) {
  if (!items.length)
    return <p className="py-6 text-center text-sm text-muted-foreground">{emptyText}</p>;
  return (
    <ul aria-label={granted ? 'Owned items' : 'Items'} className="divide-y rounded-md border">
      {items.map((row, index) => (
        <li
          key={[row.kind, row.item_id, row.gender, row.category, row.offer_id, index].join(':')}
          className="grid grid-cols-[3.5rem_minmax(0,1fr)] items-center gap-3 p-2 sm:grid-cols-[3.5rem_minmax(0,1fr)_auto]"
        >
          <div className="w-14">
            <CatalogPreview row={row} />
          </div>
          <div className="min-w-0">
            <p className="truncate font-medium" title={catalogItemName(row)}>
              {catalogItemName(row)}
            </p>
            <p className="truncate text-xs text-muted-foreground">
              {catalogKindLabel(row.kind)} · {catalogGenderLabel(row.gender)} ·{' '}
              {catalogCategoryLabel(row)}
              {typeof row.subcategory === 'string' && row.subcategory
                ? ' · ' + row.subcategory
                : ''}
            </p>
            <p className="truncate text-xs text-muted-foreground">
              {granted
                ? 'Owned since ' + formatCell('granted_at', row.granted_at)
                : row.catalog_known === false
                  ? 'Not in the recovered catalog'
                  : catalogPriceSummary(row)}
            </p>
          </div>
          <div className="col-span-2 flex flex-wrap items-center justify-end gap-2 sm:col-span-1">
            <CatalogItem row={row} />
            {action?.(row)}
          </div>
        </li>
      ))}
    </ul>
  );
}

const sources: Record<string, string> = { buy: 'Bought', gift: 'Gift', admin: 'Given by staff' };

/** Purchases with item photo, buyer, store and price. */
export function PurchaseRecords({
  items,
  showBuyer = false,
  compact = false,
}: {
  items: Row[];
  showBuyer?: boolean;
  compact?: boolean;
}) {
  if (!items.length)
    return <p className="py-6 text-center text-sm text-muted-foreground">No purchases yet.</p>;
  return (
    <ul className="divide-y rounded-md border">
      {items.map((row, index) => (
        <li
          key={String(row.offer_id) + String(row.account_id) + index}
          className="grid grid-cols-[3rem_minmax(0,1fr)_auto] items-center gap-3 p-2"
        >
          <div className="w-12">
            <CatalogPreview row={row} />
          </div>
          <div className="min-w-0">
            <p className="truncate font-medium">{catalogItemName({ ...row, name: row.name })}</p>
            <p className="truncate text-xs text-muted-foreground">
              {showBuyer && (
                <>
                  <a
                    href={playerHref(String(row.account_id))}
                    className="text-foreground hover:underline"
                  >
                    {String(row.account_name || row.account_id)}
                  </a>
                  {' · '}
                </>
              )}
              {sources[String(row.source)] || String(row.source)}
              {!compact && row.store_name ? ' in ' + String(row.store_name) : ''}
            </p>
          </div>
          <div className="text-right text-xs">
            <p className="tabular-nums">
              {catalogPrice({
                crystals: row.current_offer_crystals,
                np: row.current_offer_np,
              }).replace(' / ', ' or ')}
            </p>
            <p className="text-muted-foreground" title={formatCell('created_at', row.created_at)}>
              {relative(row.created_at)}
            </p>
          </div>
        </li>
      ))}
    </ul>
  );
}
