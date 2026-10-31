# Items, stores and recovered metadata

The preservation catalog contains 7,712 ordinary validated items:

| Collection | Items |
|---|---:|
| Clothing and customization | 6,234 |
| Companions | 219 |
| Locomotions | 108 |
| Furniture | 1,151 |

These counts exclude 20 wardrobe removal controls. Unresolved or conflicting
asset identities are not silently turned into products. Twelve wardrobe IDs
whose manifest listed two categories were decided from their own bundle
manifest (24 identities; 8 male wing items are loadable in two categories).
Nine `00_CLOTHS` prefabs have no gender or category and cannot be loaded by the
client; they stay excluded. Furniture does not establish a personal-space SKU,
and historical commercial bundles are unknown. See the
[coverage report](ITEM-METADATA-EVIDENCE.md#category-and-shop-navigation-coverage).

## How the client navigates the shop

The original client walks store type (Clothing 0, Companions 1, Furniture 2,
Locomotions 3) → store → gender tab → category list → items. Clothing has the
Male (0) and Female (1) tabs with a category list. Companions (3), Furniture (5)
and Locomotions (6) open their item list directly. The category list only
accepts the 29 type IDs that have an icon in the client. A wardrobe offer's
`type_id` is therefore that icon ID: left/right earrings are listed under
`CLOTH_HEAD_EARRING` and left/right wristbands under `CLOTH_BODY_WRISTBAND`.
`ItemData.tablename` keeps the exact slot category. Categories follow the
client's own wardrobe enum order. Items follow category, then name. Furniture is
grouped in the housing editor's menu order.

## In-game stores

Docker enables `preservation-catalog-v1` automatically before the backend opens
its listeners. It fills missing products through the original clothing,
companion, furniture and locomotion store routes. Clothing uses the shipped
gender/category selection. Existing offers, prices, purchases, ownership and
balances are retained. Untouched generated wardrobe offers that still use a
left/right slot as their category ID are moved onto the client's icon ID;
operator-edited offers are left alone. Repeating the import makes no changes.

Original shop IDs, commercial names, prices and item-to-store assignments were
supplied by the retired service and have not been recovered. Listings use the
best available item display name instead of the item ID. This name is derived
from internal asset names in the item's own bundle, such as **Easter Bunny**,
**Serene Chair** or **Medieval Trousers**. It is not the historical storefront
name. 7,084 of 7,712 items have one. The rest keep `Preserved <category> <item ID>`.
Startup renames untouched generated offers that still carry the ID label. It
never renames an offer an operator has edited. See
[item metadata evidence](ITEM-METADATA-EVIDENCE.md#display-name-backfill). New stores are named
**Preservation Clothing**, **Preservation Companions**, **Preservation Furniture**
and **Preservation Locomotions**. They are replacement groupings, not claims of
historical brand membership.

New offers use the existing preservation price policy:

| Kind | Crystals | Nebula Points |
|---|---:|---:|
| Clothing/customization | 25 | 10 |
| Companions | 40 | 20 |
| Furniture | 30 | 15 |
| Locomotions | 35 | 15 |

An existing inactive offer or store remains an operator choice: startup does not
bypass it with a replacement offer. Set `NEBULA_CATALOG_POLICY=none` to disable
future automatic filling; this does not delete already configured products.
The standalone backend defaults to `none`; pass
`--catalog-policy preservation-catalog-v1` to enable the import explicitly.

## Dashboard

**Item catalog** opens on **All game items** with responsive photo cards. Each
card shows the derived item name, or a readable category/gender label when none
exists, current currency price options and
store availability; a compact list is also available. The collection selector separates
assets from store offers and recovered shop artwork. Search and filter by
collection, gender, category or configured store. Inspect an item for available
bundle, resource, thumbnail and placement metadata, current offers/prices,
complete recovered source fields and evidence provenance. Store links filter
the catalog to that store.

The 1,205 recovered shop artwork keys form a separate read-only collection.
A logo/resource name does not establish historical store membership. Original
artwork pixels are recovered into a separate private pack and served only to
signed-in operators; they are excluded from public source and ordinary images.
See [preview extraction and installation](CATALOG_PREVIEWS.md).

Two valid wardrobe items lack their own recovered thumbnail and use a verified
generic shipped icon. Four rare category spellings are grouped under selectable
UI categories while retaining their original asset categories. See the
[recovery evidence](research/catalog-recovery-current.md) for exact boundaries.
The private preview pack predates the 24 resolved wing identities; rerun the
extractor to add their own thumbnails to it.

Each catalog item also carries its expected client shop path, sort position,
sub-category and shipped component fields (heel type, hand grip type,
locomotion speed, housing placement and interactions). The field list is in
[item metadata evidence](ITEM-METADATA-EVIDENCE.md#catalog-api-fields).

## Operator commands and checks

Preview the complete policy using a disposable database:

```sh
python -B tools/seed_full_catalog.py
```

To fill an existing initialized database explicitly:

```sh
python -B tools/seed_full_catalog.py --state-dir /private/server-state --apply
```

The importer validates before writing and applies changes in one SQLite
transaction. Existing offer coverage is checked under the write lock. Conflicts
abort without partial changes. Back up production state before policy changes.

Run focused checks with:

```sh
python -B -m unittest discover -s backend/tests -p test_full_catalog.py
```

The category tree, identity resolutions and offer realignment are checked by
`test_catalog_categories.py`. These checks exercise backend policy and recovered wire shapes. They do not
establish native loading/equipping of every asset or exact historical commercial
behavior. The expanded policy targets the default Python backend; the
experimental Rust server has a separate acceptance boundary.

The sanitized [catalog validation record](../deployment/bootstrap/catalog-validation.json)
pins the deployed images, relevant source and verification scope.
