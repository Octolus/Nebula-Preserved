import type { Row } from './panel';

export const catalogKinds = [
  { value: 'all', label: 'All game items' },
  { value: 'wardrobe', label: 'Clothing & customization' },
  { value: 'companions', label: 'Companions' },
  { value: 'locomotions', label: 'Locomotions' },
  { value: 'housing', label: 'Furniture' },
  { value: 'offer', label: 'Store offers' },
  { value: 'shop_artwork', label: 'Recovered shop artwork' },
] as const;

export type CatalogFilters = {
  kind: string;
  search: string;
  gender: string;
  category: string;
  store: string;
  cursor: string;
};

export function catalogQuery(filters: CatalogFilters) {
  const query = new URLSearchParams({ kind: filters.kind, q: filters.search, limit: '25' });
  for (const [key, value] of [
    ['gender', filters.gender],
    ['category', filters.category],
    ['store_id', filters.store],
    ['cursor', filters.cursor],
  ])
    if (value) query.set(key, value);
  return 'catalog?' + query;
}

export function catalogKindLabel(value: unknown) {
  return catalogKinds.find((kind) => kind.value === value)?.label || String(value || 'Game item');
}

export function catalogItemName(row: Row) {
  return String(row.name || row.display_name || row.item_id || row.offer_id || 'Game item');
}

export function catalogAvailability(row: Row) {
  if (row.kind === 'shop_artwork') return 'Reference only';
  if (row.active === false || row.active === 0) return 'Inactive offer';
  const offers = catalogOffers(row);
  if (
    offers.some(
      (offer) => (offer.active === true || offer.active === 1) && offer.store_active === true,
    )
  )
    return 'In store';
  if (row.offer_id && (row.store_active === false || row.store_active === 0))
    return 'Inactive store';
  if (row.grantable === false) return 'Needs review';
  if (offers.length) return 'Not listed';
  return row.shop_ready === true ? 'Ready for store' : 'Grant catalog';
}

export function catalogPrice(row: Row) {
  const options = [
    typeof row.crystals === 'number' && Number.isFinite(row.crystals)
      ? row.crystals.toLocaleString() + ' crystals'
      : '',
    typeof row.np === 'number' && Number.isFinite(row.np)
      ? row.np.toLocaleString() + ' Nebula Points'
      : '',
  ].filter(Boolean);
  return options.join(' / ') || 'Price unavailable';
}

export function catalogOffers(row: Row): Row[] {
  return Array.isArray(row.offers)
    ? row.offers.filter(
        (offer): offer is Row => !!offer && typeof offer === 'object' && !Array.isArray(offer),
      )
    : row.offer_id
      ? [row]
      : [];
}

export function provenanceLabel(value: unknown) {
  return (
    (
      {
        shipped_manifest: 'Recovered shipped manifest',
        preservation_label: 'Preservation display label',
        preservation_policy: 'Preservation policy',
        unknown: 'Not recovered',
      } as Record<string, string>
    )[String(value)] || String(value || 'Not recovered').replaceAll('_', ' ')
  );
}
