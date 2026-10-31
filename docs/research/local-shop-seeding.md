> Historical research: this file records an earlier investigation, not current feature acceptance. The root [PROGRESS report](../PROGRESS.md) is authoritative. Local evidence and extracted game code are intentionally omitted. See [research index](README.md).

# Local shop seeding

This is a small, reachable preservation catalog, not a reconstruction of the
retired commercial catalog. Store names, shop IDs, labels, prices, bundle
composition, and optional account balances are explicitly local policy.

## What the shipped client establishes

The format-aware `resources.assets` inspection found the `GenderWindow.images`
array in authored order. Its seven sprite names map the integer selected by the
client exactly:

| ID | Authored sprite | Flow |
|---:|---|---|
| 0 | `Male_Icon` | clothing `TypeData`, then `ItemData` |
| 1 | `Female_Icon` | clothing `TypeData`, then `ItemData` |
| 2 | `Bundle` | direct `ItemData` |
| 3 | `Companion` | direct `ItemData` |
| 4 | `Spaces` | direct `ItemData` for type `PERSON`; apartments are seeded by the catalog policy, not here |
| 5 | `Furniture_Icon` | direct `ItemData` |
| 6 | `Locomotion` | direct `ItemData` |

The same asset contains 29 `ItemTypeWindow.images` sprites. Their names are
the actual wardrobe category IDs; the seed uses four of them:
`CLOTH_BODY_TORSO`, `CLOTH_BODY_LEGS`, `CLOTH_BODY_FEET`, and
`CLOTH_HEAD_HAIRSTYLE`.

Shop IDs are not authored constants in the shipped UI. Native
`ShopManager.OnClickClothing`/`GetShops` request a shop class first.
`GetShopData` supplies `ShopData.id`; `OnShopSelected` stores the selected
string unchanged and sends that same string to `GetGenderDataShopServlet`.
`OnTypeSelected` likewise forwards the stored shop ID, selected gender, and
returned type ID to `GetItemAssetsDataServlet`. Therefore stable local IDs are
compatible with the normal client flow and are labeled `local-preservation-*`
rather than being misrepresented as original service identifiers.

`ShopData.url` is not fetched as a network URL by this client build.
`EntryShop.Set` at `0x4ab1c0` requires a non-null string, takes the exact slice
`url.Substring(57, url.Length - 61)`, prepends `Shops/`, and passes that local
resource path to `Resources.Load<Sprite>`. An empty URL therefore throws before
the shop callback returns. The seed uses a 57-character, explicitly local
carrier prefix, a shipped `Shops` sprite ID, and the four-character `.png`
suffix. The carrier is never contacted. The original retired-service URL
prefix was not recovered and is not fabricated.

The four selected image IDs are independently present in the shipped
`resources.assets` resource table under lowercase `shops/<id>` keys. They are
presentation assets only; their use does not claim they belonged to any
historical commercial shop. Item-card thumbnails follow a different path:
`EntryItem.Set` forwards `ItemData.imagePath` to `EntryBase.setThumbnail`.
Those paths remain the existing manifest-validated wardrobe, companion,
housing, and locomotion thumbnails and do not use the fixed URL slice.

## Seed contents and policy

The deterministic seed selects the lexicographically first valid shipped asset
for each chosen wardrobe gender/category, two companions, two furniture items,
and two locomotions. `Catalog`, `ResourceCatalog`, `HousingStore`, and `Shop`
revalidate every item ID, category, gender, and thumbnail before it can be
written. One local bundle contains the first companion and locomotion and
reuses a validated shipped thumbnail.

Local prices are deliberately simple:

- Wardrobe: 25 crystals / 10 NP.
- Companion: 40 crystals / 20 NP.
- Furniture: 30 crystals / 15 NP.
- Locomotion: 35 crystals / 15 NP.
- Local bundle: 60 crystals / 25 NP.

No original price, entitlement, promotion, or Steam transaction is inferred.
The optional starter balance is written only when an account ID and explicit
amounts are supplied.

## Safe usage

Dry-run is the default and uses a disposable temporary database:

[Code/listing block omitted from the public research archive.]

Applying requires an explicit state directory. This example is illustrative;
choose the actual server state directory deliberately:

[Code/listing block omitted from the public research archive.]

The operation is idempotent. It does not launch the game, start a listener,
open a connection, attach to a process, or alter the installed game.

To repair only the four existing `local-preservation-*` shop image fields,
without recreating offers or changing balances, grants, presets, or unrelated
shops, use:

[Code/listing block omitted from the public research archive.]

The repair creates no missing shop rows. Its JSON result lists the matched and
updated local shop IDs.

Machine-readable mappings and selected shipped IDs are in
[`local-shop-seeding.json`](local-shop-seeding.json).
