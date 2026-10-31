import type { Row } from './panel';

export const catalogKinds = [
  { value: 'all', label: 'All game items' },
  { value: 'wardrobe', label: 'Clothing & customization' },
  { value: 'companions', label: 'Companions' },
  { value: 'locomotions', label: 'Locomotions' },
  { value: 'housing', label: 'Furniture' },
  { value: 'personal_spaces', label: 'Apartments' },
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
  const id = String(row.item_id || row.offer_id || '');
  for (const value of [
    row.original_name,
    row.label,
    row.derived_name,
    row.display_name,
    row.readable_name,
    row.name,
  ]) {
    const supplied = String(value || '').trim();
    if (
      supplied &&
      supplied !== id &&
      !/^(preserved|preservation|local preservation)\b/i.test(supplied) &&
      !/^[a-z0-9_-]{24,}$/i.test(supplied)
    )
      return supplied;
  }
  const type = catalogCategoryLabel(row);
  const gender = catalogGenderLabel(row.gender);
  return [gender === 'All characters' ? '' : gender, type, id ? '· ' + id.slice(0, 8) : '']
    .filter(Boolean)
    .join(' ');
}

export function catalogGenderLabel(value: unknown) {
  return (
    (
      {
        MALE: 'Male',
        FEMALE: 'Female',
        UNISEX: 'Unisex',
        ALL: 'All characters',
        NONE: 'All characters',
      } as Record<string, string>
    )[String(value)] ||
    (value
      ? String(value)
          .replaceAll('_', ' ')
          .toLowerCase()
          .replace(/^./, (c) => c.toUpperCase())
      : 'All characters')
  );
}

export function catalogCategoryLabel(row: Row) {
  const categories: Record<string, string> = {
    CLOTH_BODY_FEET: 'Footwear',
    CLOTH_BODY_HAND: 'Hand accessory',
    CLOTH_BODY_HANDS: 'Hand accessories',
    CLOTH_BODY_HANDITEML: 'Left-hand item',
    CLOTH_BODY_HANDITEMR: 'Right-hand item',
    CLOTH_BODY_LEGS: 'Bottoms',
    CLOTH_BODY_LEG_GARTER: 'Garter',
    CLOTH_BODY_LEG_ITEM: 'Leg accessory',
    CLOTH_BODY_LEG_TIGHTS: 'Tights',
    CLOTH_BODY_NAILS: 'Nails',
    CLOTH_BODY_TATTOO: 'Body tattoo',
    CLOTH_BODY_TORSO: 'Top',
    CLOTH_BODY_TORSOLEGS: 'Full outfit',
    CLOTH_BODY_TORSO_LEGS: 'Full outfit',
    CLOTH_BODY_TORSO_APPAREL: 'Upper-body accessory',
    CLOTH_BODY_WRISTBANDL: 'Left wrist accessory',
    CLOTH_BODY_WRISTBANDR: 'Right wrist accessory',
    CLOTH_HEAD_BEARD: 'Beard',
    CLOTH_HEAD_EARRINGL: 'Left earring',
    CLOTH_HEAD_EARRINGR: 'Right earring',
    CLOTH_HEAD_FACEITEM: 'Face accessory',
    CLOTH_HEAD_FULL_HEAD_DRESS: 'Full headwear',
    CLOTH_HEAD_HAIRSTYLE: 'Hairstyle',
    CLOTH_HEAD_HAT: 'Hat',
    CLOTH_HEAD_ITEMS: 'Head accessory',
    CLOTH_HEAD_NECK: 'Neck accessory',
    CLOTH_HEAD_PAINT: 'Head paint',
    CLOTH_HEAD_SUNGLASSES: 'Sunglasses',
    COMPANIONS: 'Companion',
    LOCOMOTIONS: 'Locomotion',
  };
  if (categories[String(row.category)]) return categories[String(row.category)];
  if (row.kind === 'companions') return 'Companion';
  if (row.kind === 'locomotions') return 'Locomotion';
  const label = String(row.category_label || row.category || '')
    .replace(/^(CLOTH_|CLOTHING_|FURNITURE_)/, '')
    .replaceAll('_', ' ')
    .trim();
  if (label) return label.toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase());
  return (
    (
      {
        wardrobe: 'Customization item',
        housing: 'Furniture',
        personal_spaces: 'Apartment',
        companions: 'Companion',
        locomotions: 'Locomotion',
        shop_artwork: 'Shop artwork',
        offer: 'Store item',
      } as Record<string, string>
    )[String(row.kind)] || 'Game item'
  );
}

export function catalogPreviewUrl(row: Row) {
  const value = row.preview_url;
  return typeof value === 'string' &&
    /^\/api\/catalog-preview\/[a-zA-Z0-9_-]+(?:\.(?:png|webp|jpg))?$/.test(value)
    ? value
    : null;
}

export function catalogLiveOffers(row: Row) {
  return catalogOffers(row).filter(
    (offer) =>
      (offer.active === true || offer.active === 1) &&
      (offer.store_active === true || offer.store_active === 1),
  );
}

export function catalogPriceSummary(row: Row) {
  const prices = [...new Set(catalogLiveOffers(row).map(catalogPrice))];
  return prices.length
    ? prices[0] + (prices.length > 1 ? ` · ${prices.length} price options` : '')
    : 'Not currently for sale';
}

export function catalogAvailability(row: Row) {
  if (row.kind === 'shop_artwork') return 'Reference only';
  if (row.active === false || row.active === 0) return 'Inactive offer';
  const offers = catalogOffers(row);
  if (catalogLiveOffers(row).length) return 'In store';
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
