# Catalog recovery: assets and commercial metadata

The expanded catalog can expose **7,688 ordinary grantable items**: 6,210 wardrobe items, 219 companions, 108 locomotions and 1,151 housing furniture items. The 6,230 validated wardrobe IDs also contain 20 removal controls; those controls are not products. Furniture IDs do not establish personal-space offers.

The shipped client establishes asset identity, category, gender, bundle membership, dependencies, resource paths and some placement information. It does **not** establish a complete historical price list, item display names/descriptions, original shop IDs or item-to-shop membership. Those commercial records were supplied by HTTP. Preservation shop grouping, readable fallback labels and prices are explicitly operator policy. They must not be described as the original catalog restored exactly.

Machine-readable evidence and field availability are in [catalog-recovery-provenance.json](../../protocol/catalog-recovery-provenance.json). Earlier native contract evidence is in [http-shop.md](http-shop.md), [shop-second-pass.md](shop-second-pass.md) and [local-shop-seeding.md](local-shop-seeding.md).

## Item thumbnails

The validated wardrobe manifests use both `Assets/ResourcesART/Wardrobe_EAB/` and `Assets/ART/ResourcesART/Wardrobe_EAB/`. Rejecting the second exact prefix hid 77 ordinary items with their own matching thumbnails. Keep exact Unicode item identities and case when matching; do not normalize an item ID to guess an asset.

Two validated wardrobe IDs lack a recovered matching thumbnail: `O08f1sQQOR6VVuRpIXAdCria00L0r33b` and `sL0D2k3asbB756Yb2qJ0LchSiLsKw5Cf`. The former has prefab evidence; the latter is also referenced by the native default male preset. Both remain valid catalog items. An explicitly labeled generic `Shops/shop.png` icon avoids showing another item's preview. The native `EntryBase.setThumbnail` handler (RVA `0x4a7f90`) accepts the `Shops/` resource route and strips the four-character extension; retained resource pointers establish `shops/shop` exists. This establishes a compatible resource contract, not a visual test of every item.

## Native category selection

The original `ItemTypeWindow` component (path ID 16353) contains 29 Sprite references. Its exact raw array has count 29 at offset 108, followed by 29 twelve-byte pointers at offset 112, ending at the component's 460-byte boundary. All pointers resolve to Sprite objects. The sprite names include `CLOTH_BODY_HANDS` and `CLOTH_BODY_TORSO_LEGS`, but do not include the rare asset categories `CLOTH_BODY_HAND` and `CLOTH_BODY_TORSOLEGS` (two items each).

Group those four items under the corresponding selectable canonical UI categories as a **preservation compatibility policy**. Preserve the original asset category separately for item identity/loading. The historical server's spelling/alias behavior has not been recovered. The source `resources.assets` SHA-256 and all 29 resolved names/path IDs are retained in the public provenance JSON; no Sprite pixels are included.

## Shop response size and paging

`ShopNETGcloud.Get_GetItemAssetsData` (RVA `0x40c420`) reads the declared Int32 count from token 3, allocates that many `ItemData` entries, then consumes tokens 4 through count+3. It computes local UI pages as `ceil(count / 10)`. There is no small item-count cap or server pagination parameter in this receiver. `Get_GetShopTypeDataMale` (RVA `0x40d630`) similarly handles complete returned arrays. This is bounded static evidence, not a claim of unlimited allocation or transport capacity.

The preservation remote transport limits an HTTP response to 8 MiB (`RESPONSE_LIMIT` in `experimental/remote-transport/client/src/main.rs`). Keep lists category-scoped and measure the actual encoded/encrypted wire response against that limit. Gender 4 has no recovered deserialization branch in this receiver, so do not turn furniture IDs into invented personal-space offers.

## Shop artwork is not store membership

Retained resource paths contain **1,205 distinct `shops/` keys** (2,408 Sprite/Texture pointer rows). Of these, 76 have readable resource labels; most others are opaque identifiers. The public provenance file records every exact resource key and pointer, including raw trailing spaces. These are useful metadata, but an artwork filename such as `hardcandy` does not prove a historical ShopData ID, commercial title, price, or which products belonged to that store. No original artwork has been added to the repository.

## Bounded public research

On 2026-10-30, official-domain searches covered `nebularealms.com`, `xalocstudios.com`, the Steam store/news for app 919290 and its Steam announcements. Search terms combined Nebula Realms with shop, store, catalog/catalogue, items, Hard Candy and Kawaii. The [publisher's Steam product page](https://store.steampowered.com/app/919290/) describes a large shopping catalog and home decorations, but supplies no exact item-ID/store/price mapping. The [Steam news endpoint](https://store.steampowered.com/news/app/919290) returned a navigation shell; game/studio sites and the announcements endpoint were inaccessible to the research tool. No exact historical SKU mapping was recovered in this bounded search. This does not establish that no historical catalog exists elsewhere.

## Reproducibility and limits

The provenance file records SHA-256 digests of the retained resource-path and asset-bundle-manifest extracts, plus the original resource asset/component used for category sprites. Native behavior above reuses retained function evidence from the existing protocol investigation. A format-aware UnityPy 1.25.4 read resolved the bounded Sprite pointers because REA does not advertise a Unity serialized-asset parser. This work did not launch the game or observe live purchase/equip behavior. Runtime validation and deployment are tracked separately.
