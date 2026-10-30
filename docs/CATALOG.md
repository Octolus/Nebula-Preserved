# Items, stores and recovered metadata

The preservation catalog contains 7,688 ordinary validated items:

| Collection | Items |
|---|---:|
| Clothing and customization | 6,210 |
| Companions | 219 |
| Locomotions | 108 |
| Furniture | 1,151 |

These counts exclude 20 wardrobe removal controls. Unresolved or conflicting
asset identities are not silently turned into products. Furniture does not
establish a personal-space SKU, and historical commercial bundles are unknown.

## In-game stores

Docker enables `preservation-catalog-v1` automatically before the backend opens
its listeners. It fills missing products through the original clothing,
companion, furniture and locomotion store routes. Clothing uses the shipped
gender/category selection. Existing offers, prices, purchases, ownership and
balances are retained. Repeating the import makes no changes.

Original shop IDs, commercial names, prices and item-to-store assignments were
supplied by the retired service and have not been recovered. New stores are named
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
card shows a readable category/gender label, current currency price options and
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

These checks exercise backend policy and recovered wire shapes. They do not
establish native loading/equipping of every asset or exact historical commercial
behavior. The expanded policy targets the default Python backend; the
experimental Rust server has a separate acceptance boundary.

The sanitized [catalog validation record](../deployment/bootstrap/catalog-validation.json)
pins the deployed images, relevant source and verification scope.
