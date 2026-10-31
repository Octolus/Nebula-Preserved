import { test } from 'node:test';
import assert from 'node:assert/strict';
import { managementQuery } from '../src/lib/manage-policy.ts';
import {
  catalogAvailability,
  catalogItemName,
  catalogKinds,
  catalogOffers,
  catalogPrice,
  catalogQuery,
  provenanceLabel,
  catalogCategoryLabel,
  catalogGenderLabel,
  catalogPreviewUrl,
  catalogPriceSummary,
} from '../src/lib/catalog.ts';

test('catalog separates all assets from store offers and encodes exact filter values', () => {
  assert.equal(catalogKinds[0].value, 'all');
  assert.ok(catalogKinds.some((kind) => kind.value === 'offer' && kind.label === 'Store offers'));
  assert.ok(
    catalogKinds.some((kind) => kind.value === 'personal_spaces' && kind.label === 'Apartments'),
  );
  const query = catalogQuery({
    kind: 'housing',
    search: 'lamp & chair',
    gender: '',
    category: 'TABLE',
    store: 'store/one',
    cursor: '25',
  });
  const params = new URLSearchParams(query.slice('catalog?'.length));
  assert.equal(params.get('q'), 'lamp & chair');
  assert.equal(params.get('store_id'), 'store/one');
  assert.equal(params.get('category'), 'TABLE');
  assert.equal(params.get('cursor'), '25');
  assert.equal(params.get('limit'), '25');
  assert.equal(params.has('gender'), false);
});

test('catalog does not mistake a grantable asset for a configured store offer', () => {
  assert.equal(catalogAvailability({ grantable: true }), 'Grant catalog');
  assert.equal(catalogAvailability({ grantable: false }), 'Needs review');
  assert.equal(catalogAvailability({ shop_ready: true }), 'Ready for store');
  assert.equal(catalogAvailability({ offer_id: 'offer', active: 0 }), 'Inactive offer');
  assert.equal(catalogAvailability({ offer_id: 'offer', active: true }), 'Not listed');
  assert.equal(
    catalogAvailability({ shop_ready: true, offers: [{ active: true, store_active: true }] }),
    'In store',
  );
  assert.equal(
    catalogAvailability({ shop_ready: true, offers: [{ active: true, store_active: false }] }),
    'Not listed',
  );
  assert.equal(
    catalogAvailability({ shop_ready: true, offers: [{ active: false, store_active: true }] }),
    'Not listed',
  );
  assert.equal(
    catalogAvailability({ offer_id: 'offer', active: true, store_active: false }),
    'Inactive store',
  );
  assert.equal(catalogAvailability({ kind: 'shop_artwork', grantable: false }), 'Reference only');
});

test('catalog preserves zero prices and distinguishes unknown historical metadata', () => {
  assert.equal(catalogPrice({ crystals: 0, np: 0 }), '0 crystals / 0 Nebula Points');
  assert.equal(catalogPrice({ crystals: null, np: Infinity }), 'Price unavailable');
  assert.equal(provenanceLabel('unknown'), 'Not recovered');
  assert.equal(provenanceLabel('preservation_label'), 'Preservation display label');
  assert.equal(provenanceLabel('shipped_manifest'), 'Recovered shipped manifest');
});

test('catalog details use available labels and ignore malformed offer-list entries', () => {
  assert.equal(catalogItemName({ item_id: 'Exact-ID', name: 'Local label' }), 'Local label');
  assert.equal(catalogItemName({ item_id: 'Exact-ID' }), 'Game item · Exact-ID');
  assert.deepEqual(catalogOffers({ offers: [null, false, 'bad', [], { offer_id: 'real' }] }), [
    { offer_id: 'real' },
  ]);
  assert.deepEqual(catalogOffers({ offer_id: 'offer', crystals: 25 }), [
    { offer_id: 'offer', crystals: 25 },
  ]);
});

test('catalog human labels replace generated asset names without inventing commercial names', () => {
  assert.equal(
    catalogItemName({
      item_id: 'abcdefghijklmnop',
      kind: 'wardrobe',
      gender: 'FEMALE',
      category_label: 'Hat',
      name: 'Preserved Clothing abcdefghijklmnop',
    }),
    'Female Hat · abcdefgh',
  );
  assert.equal(
    catalogItemName({
      item_id: 'asset-id',
      display_name: 'Recovered Cotton Hat',
      name: 'Preserved item',
    }),
    'Recovered Cotton Hat',
  );
  assert.equal(catalogCategoryLabel({ category: 'CLOTH_HEAD_HAT' }), 'Hat');
  assert.equal(
    catalogCategoryLabel({ category: 'CLOTH_BODY_HANDITEML', category_label: 'Handiteml' }),
    'Left-hand item',
  );
  assert.equal(
    catalogCategoryLabel({ category: 'CLOTH_BODY_WRISTBANDR' }),
    'Right wrist accessory',
  );
  assert.equal(catalogCategoryLabel({ category: 'CLOTH_BODY_TORSO_LEGS' }), 'Full outfit');
  assert.equal(
    catalogCategoryLabel({ kind: 'companions', category_label: 'Companions' }),
    'Companion',
  );
  assert.equal(catalogGenderLabel('UNISEX'), 'Unisex');
});

test('catalog previews only accept opaque authenticated same-origin image routes', () => {
  assert.equal(
    catalogPreviewUrl({ preview_url: '/api/catalog-preview/' + 'a'.repeat(64) }),
    '/api/catalog-preview/' + 'a'.repeat(64),
  );
  for (const preview_url of [
    'https://external.invalid/photo.png',
    '//external.invalid/photo',
    '/api/catalog-preview/../secret',
    '/api/catalog-preview/key?token=secret',
    'C:/private/image.png',
  ])
    assert.equal(catalogPreviewUrl({ preview_url }), null);
});

test('catalog summary only shows actual active store offers and preserves currency alternatives', () => {
  const offers = [
    { active: true, store_active: true, crystals: 25, np: 10 },
    { active: false, store_active: true, crystals: 1, np: 0 },
    { active: true, store_active: false, crystals: 2, np: 0 },
  ];
  assert.equal(catalogPriceSummary({ offers }), '25 crystals / 10 Nebula Points');
  assert.equal(catalogPriceSummary({ offers: offers.slice(1) }), 'Not currently for sale');
  assert.equal(
    catalogPriceSummary({ offers: [offers[0], { ...offers[0], crystals: 50 }] }),
    '25 crystals / 10 Nebula Points · 2 price options',
  );
});

test('SSR proxy forwards catalog filters only on the catalog route and keeps its query allowlist', () => {
  const input = new URLSearchParams({
    gender: 'FEMALE',
    store_id: 'exact-store',
    category: 'CLOTH_HEAD_HAT',
    q: 'hat',
    password: 'must-not-forward',
    role: 'owner',
  });
  const catalog = managementQuery('catalog', input);
  assert.equal(catalog.get('gender'), 'FEMALE');
  assert.equal(catalog.get('store_id'), 'exact-store');
  assert.equal(catalog.get('category'), 'CLOTH_HEAD_HAT');
  assert.equal(catalog.get('q'), 'hat');
  assert.equal(catalog.has('password'), false);
  assert.equal(catalog.has('role'), false);
  const users = managementQuery('users', input);
  assert.equal(users.has('gender'), false);
  assert.equal(users.has('store_id'), false);
  assert.equal(
    managementQuery('catalog', new URLSearchParams({ q: 'x'.repeat(300) })).get('q')?.length,
    256,
  );
});

test('ownership IDs cannot hide a recovered label and companion fallbacks stay honest', () => {
  assert.equal(
    catalogItemName({ item_id: 'opaque-item', display_name: 'opaque-item', name: 'Recovered hat' }),
    'Recovered hat',
  );
  assert.equal(
    catalogItemName({
      item_id: 'opaque-item',
      original_name: 'Original hat',
      display_name: 'Local hat',
    }),
    'Original hat',
  );
  assert.equal(
    catalogItemName({
      kind: 'companions',
      item_id: 'abcdefgh12345678',
      display_name: 'Preserved Companions abcdefgh12345678',
    }),
    'Companion \u00b7 abcdefgh',
  );
});
