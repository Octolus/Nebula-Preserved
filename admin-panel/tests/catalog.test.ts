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
} from '../src/lib/catalog.ts';

test('catalog separates all assets from store offers and encodes exact filter values', () => {
  assert.equal(catalogKinds[0].value, 'all');
  assert.ok(catalogKinds.some((kind) => kind.value === 'offer' && kind.label === 'Store offers'));
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
  assert.equal(catalogItemName({ item_id: 'Exact-ID' }), 'Exact-ID');
  assert.deepEqual(catalogOffers({ offers: [null, false, 'bad', [], { offer_id: 'real' }] }), [
    { offer_id: 'real' },
  ]);
  assert.deepEqual(catalogOffers({ offer_id: 'offer', crystals: 25 }), [
    { offer_id: 'offer', crystals: 25 },
  ]);
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
