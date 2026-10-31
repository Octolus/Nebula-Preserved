# Item metadata recovery evidence

Research date: 2026-10-30. This documents offline inspection of the shipped Unity
2021.3.9f1 assets and retained native decompilation. It does not establish that
the historical production catalog or its prices have been recovered.

## What can be recovered

The canonical catalog contains 7,712 ordinary grantable assets: 6,234 wardrobe
variants, 219 companions, 108 locomotions and 1,151 furniture items. Wardrobe
identity includes gender and category; an ID alone is not a safe join key.
Twenty wardrobe removal controls are excluded from these ordinary-item counts.
Until 2026-10-30 the catalog had 7,688 items; 24 wardrobe identities were then
resolved from their own manifests (see
[category and shop navigation coverage](#category-and-shop-navigation-coverage)).

The completed item pass inspected **all 7,688 canonical bundles** of that time, verified their
manifest hashes and decoded **614,061 named typed objects** with **zero object
decoding errors**. It found zero TextAssets in those bundles and retained 1,523
MonoBehaviour records containing strings. This means complete coverage of the
selected ordinary-item bundles, not complete coverage of every shipped asset.

Hashed prefab names do **not** mean every readable name is missing. Typed Unity
objects inside bundles retain model, material, avatar and animation names.
These establish useful internal labels joined to exact item identities through
the pinned bundle manifests. They do not establish the original storefront name.

Examples from typed object reads:

| Kind | Exact item ID | Internal evidence |
| --- | --- | --- |
| Companion | `A0IQgRXmw2UMG8T5UGrVE022o7Id25GU` | Mesh `EasterBunny_Mesh`, Material `EasterBunny_Mat`, Avatar `EasterBunny_RigAvatar` |
| Companion | `ATo84oe22Ln0fG7UkgHYMOJM54FKi1R0` | Avatar `WinterJackalope_RigAvatar`, Material `WinterJackalope_Mat`; mesh only says `Jackalope_Mesh` |
| Companion | `AA5wME7djMVdc87eKIg8oldbpgv8271T` | Mesh `Rocket_Pet_Red`, Material `Rocket_Pet_Red_Mat` |
| Companion | `BO3Pa48Er77mpQ8S41Uor4wsjhmLLcb7` | Avatar `CheerbearAvatar`, Material `Cheerbear_mat`; GameObject also says `Teddy` |
| Housing | `A044fFy8Xtm2U2J1DuRolDt63P431gI8` | Mesh `SereneChair`, Material `SereneChair_Mat` |
| Housing | `A3dcS8JTIA7A88QN1vgmEJs6162tXPfe` | Mesh `OwlPumpkin`, Materials `Pumpkin_Owl_Mat`, `Pumpkin_Owl_Glow_Mat` |

For presentation, keep a derived human label separate from `original_name` and
show its provenance as an internal asset label. Preserve the raw object type,
path ID, bundle hash and manifest hash behind it. Names can disagree or be too
generic: one furniture asset uses `RainbowSofa_Mat` and a mesh called
`CloudChair`; others contain only `polySurface2`, `pPipe4`, or generic materials.
Technical suffix removal, capitalization and translations are authored display
policy rather than recovered commercial facts. Never synthesize descriptions,
historical prices or historical store membership from these names or pictures.

## Display-name backfill

`protocol/item-display-metadata.json` holds one entry per catalog identity
(`kind`, `item_id`, `gender`, `category`). It carries short text labels and their
source object references only (bundle and manifest SHA-256, Unity object type,
path ID and raw name). It contains no pixels, meshes, audio or bundle bytes. It
ships with the backend like the other `protocol/` catalogs, so Docker images
need no extra private pack.

| Field | Meaning |
| --- | --- |
| `original_name`, `description` | Only from a shipped string tied to that exact item. None was found; both stay `null`. |
| `derived_name`, `name_source: derived_asset_name` | A humanized label chosen by a weighted vote over the item's own Avatar, Material, Mesh, model GameObject, Texture and AnimationClip names. IDs, rig bones, placement markers, third-party effect assets and generic names (`normal`, `polySurface`, `Female_Root`) are rejected. Not the storefront name. |
| `derived_name_confidence` | `high`: support ≥ 4 and at least half of all candidate support. `medium`: support ≥ 2. `low`: a single texture name. |
| `derived_name_alternatives` | Up to three runner-up labels for operator review. |
| `season_hint` | Christmas, Halloween, Easter, Valentine's, Summer or Winter, matched from internal names. It is not a historical collection. |
| `interaction_labels` | Shipped `_label`, `ShowText` and `HideText` prompts from the item's own components, for example `Light On Red Rocket`. These are hints, not names. |

Coverage from the complete typed scan (7,688 rows, plus 24 rows appended for the
resolved wing identities):

| Kind | Items | Original names before / after | Derived names before / after (high, medium, low) | Descriptions | Other hints |
| --- | ---: | --- | --- | --- | --- |
| Wardrobe | 6,234 | 0 / 0 | 0 / 5,607 (1,756, 3,614, 237) | 0 | 726 season hints |
| Companions | 219 | 0 / 0 | 0 / 219 (67, 150, 2) | 0 | 27 season hints |
| Locomotions | 108 | 0 / 0 | 0 / 108 (49, 59, 0) | 0 | 11 season hints |
| Housing | 1,151 | 0 / 0 | 0 / 1,150 (650, 499, 1) | 0 | 147 season hints, 178 with interaction labels |

Before the backfill, every item was shown as `Preserved <category> <item ID>`.
The panel rendered that as, for example, `Male Top · Gnvdg5Dg`. The 628 items
without a usable internal name are 627 wardrobe items and 1 housing item. Their
bundles contain only ID-derived meshes and generic materials, so they keep that
fallback.

Example derived labels: `A0IQgRXm…` Easter Bunny (Avatar
`EasterBunny_RigAvatar`), `ATo84oe2…` Winter Jackalope, `R5YkYq5H…` Classy
Spider, `AA5wME7d…` Rocket Pet Red, `A044fFy8…` Serene Chair, `A3dcS8JT…`
Pumpkin Owl, `Wo3cT22T…` Jetpack, male legs `G6e04OL8…` Medieval Trousers,
and male hat `VHm3Y0os…` TRBL Cap. Many developer labels are Spanish (`Toalla
Voladora`, `Bicicleta`) or abbreviated (`Rs Table 02`). Translating them or
expanding abbreviations would be authored policy, so the tool does not.

### How the server uses it

`backend/catalog_inventory.py` loads the file once per file version. Each
catalog asset exposes `original_name`, `description`, `derived_name`,
`derived_name_confidence`, `derived_name_alternatives`, `season_hint`,
`interaction_labels`, `display_name`, `name_source`, `display_name_source`,
`preservation_label` and `item_metadata` (source file plus exact object
provenance) through the management catalog API. `provenance.display_name`
records the name source. Text is single-line, at most 80 characters for derived
labels and never contains the wire separator `#`.

`seed_full_catalog` (startup and `tools/seed_full_catalog.py`) creates new
preservation offers with the best available name. It also renames an existing
offer only when all of the following are true:

* The offer has this policy's deterministic ID for that exact item identity.
* `management_catalog_overrides` records no operator edit of any field for it.
* Its name is still the exact generated `Preserved <category> <item ID>` label.

Only the `name` column changes. Prices, store assignment, activity, featured
state, purchases (`shop_owned`), inventories and wallets are untouched. A
repeated run changes nothing. The result reports `relabelled_offers`. Offers
keep `name_source: preservation_label`; `listing_name_basis` shows whether the
listing name came from the item display name. Delete or rename the protocol
file to fall back to the old labels for new offers. Already renamed offers are
not reverted automatically.

### Rerun

```powershell
python tools/recover_item_asset_metadata.py `
  --game-data 'D:/SteamLibrary/steamapps/common/Nebula Realms/Nebula Realms_Data' `
  --output 'D:/Research/nebula-item-metadata.private.jsonl' --workers 4
python tools/build_item_display_metadata.py `
  --scan 'D:/Research/nebula-item-metadata.private.jsonl' `
  --output protocol/item-display-metadata.json
python -B -m unittest discover -s backend/tests -p test_item_display_metadata.py
```

The builder validates every scan identity against the current catalog. Output is
byte-identical for the same scan and catalog. The committed file was built from
the private scan with SHA-256
`5f4bd72a56eba454f3b967c1edf409be2f173fe49e1d513555579ed6f0a6b05c`. That is
the original 7,688-row scan (`c680b9c0…`) with 24 rows appended by a resumed run
for the resolved wing identities. The 7,688 earlier entries are byte-for-byte
unchanged.

### Sources searched without item names

* **Main asset files.** `resources.assets`, `globalgamemanagers.assets`,
  `sharedassets0.assets` and `level0` were scanned raw (length-prefixed strings
  in every MonoBehaviour, including the 3,516 without a typetree). No item ID
  appeared.
* **Scene and pooler bundles.** All 107 `s/` scene bundles plus `pooler`, `nav` and
  `screenloader` were scanned the same way. 24 components in `nexus`,
  `sorcererseyrie`, `thenebulian` logic prefabs and `pre` hold 14 bare item IDs
  with no other string.
* **IL2CPP string literals.** Item IDs appear only in thumbnail paths, mesh
  names and gathering-reward debug text, never beside a display name.
* **Client classes.** No localization or I2 tables exist. `Companion`,
  `Locomotion` and `HousingFurnishing` have no name or description field. Shop
  names and descriptions arrive from the server (`EntryData`).
* **Local player data.** Player logs and `LocalLow` contain only preservation
  sessions, not retired-service responses.

Rarity, tier, brand, set membership, prices and store membership remain
unrecovered.

## Category and shop navigation coverage

Research date: 2026-10-30. Static reads of the retained IL2CPP dump and
`GameAssembly.dll`, plus a read-only UnityPy pass over every item bundle of the
installed game (app 919290, build 11018722; item bundles are unpatched). The
game was not launched. Coverage is computed on a disposable database seeded by
`seed_full_catalog`. *Before* is the previous policy on the previous 7,688-row
catalog.

### What was wrong

1. **The clothing category list broke in the client.** The client shows a
   category only if `ItemTypeWindow.images` has a sprite whose name equals the
   `TypeData.typeID`. `EntryItemType.Set` (`0x4a90e0`) looks the sprite up and
   indexes the list directly. A miss throws inside `BaseWindow.Populate`
   (`0x4a5950`), and the rest of the list is never built. The server sent the
   exact slot categories `CLOTH_BODY_WRISTBANDL/R` and `CLOTH_HEAD_EARRINGL/R`,
   which have no sprite. The 29 sprites include only the merged
   `CLOTH_BODY_WRISTBAND`, `CLOTH_HEAD_EARRING` and `CLOTH_BODY_RINGS`. The
   client itself strips the L/R from `CLOTH_BODY_RINGSL/R`. Types were sorted
   alphabetically, so the list stopped at `CLOTH_BODY_WRISTBANDL`. Every
   `CLOTH_HEAD_*` category and both wristbands were unreachable for both
   genders: 1,896 of 6,210 wardrobe items.
2. **Category order was alphabetical** instead of the client's own wardrobe
   enum `AEManager.TypeContent`. Items within a category and the
   1,151-item furniture list were ordered by the hashed offer ID.
3. **24 wardrobe identities were excluded as conflicts.** The manifest decides them.
   Eight female wing items have one prefab
   (`CLOTH_BODY_TORSO_APPAREL`) and a stray thumbnail under `CLOTH_HEAD_FACEITEM`.
   Eight male wing items ship a prefab *and* a thumbnail in both
   `CLOTH_BODY_TORSO_APPAREL` and `CLOTH_HEAD_FACEITEM`. The client loads
   wardrobe items only from `Wardrobe_EAB/<gender>/<category>/<id>/FBX/<id>`
   (`SetShopBase.Init` `0x468390`, `LoadItemSelected` `0x470310`), so each such
   folder is a loadable identity.

### How it is fixed

* A wardrobe offer's `type_id` is the client icon ID (`store_category`). The two
  left/right pairs merge to their sprite (`client_type_icon_merge`). The four
  rare spellings keep the existing `preservation_compatibility_alias`.
  `ItemData.tablename` still carries the exact slot category, which the client
  uses for the preview path.
* `GetShopTypeDataShopServlet` (genders 0/1) emits only icon IDs, deduplicated
  and in `AEManager.TypeContent` order. A stored ID without an icon, such as an
  operator offer, is logged and omitted instead of crashing the list.
  `GetItemAssetsDataServlet` matches every stored ID that maps to the requested
  icon ID, so legacy `…WRISTBANDL` offers and the client's own `CLOTH_BODY_RINGS`
  request still resolve.
* Item lists are ordered by slot category, then name. Furniture follows the
  housing editor menu (`HousingUIContentManager.TypeServerElement`).
* `tools/build_item_catalog_metadata.py --apply-wardrobe-resolutions` clears
  `category_conflict` only for rows whose own folder holds both the prefab and
  the thumbnail. It records `category_conflict_resolution` on the row and
  preserves the file's exact formatting. It is idempotent.
* `seed_full_catalog` creates the 24 new offers. It moves untouched generated
  wardrobe offers still holding a left/right `type_id` to the icon ID and
  reports `retyped_offers`. It skips any offer with a
  `management_catalog_overrides` record. Names, prices, store assignment,
  activity, purchases, inventories and wallets are never written. A second run
  changes nothing.

### Coverage per kind

"Correct category" means the offer is reachable through the client menus under
the expected store type, gender tab and category. "Sub-category known" counts a
non-null `subcategory`. Before, housing exposed its placement behaviour; nothing
else had a sub-category.

| Kind | Items before / after | Correct category | Sub-category known | Store path reachable | Name: derived / fallback (original) | Own thumbnail (generic icon) |
| --- | --- | --- | --- | --- | --- | --- |
| Wardrobe | 6,210 / 6,234 | 4,314 / 6,234 | 0 / 1,755 | 4,314 / 6,234 | 5,586 / 624 → 5,607 / 627 (0) | 6,208 (2) → 6,232 (2) |
| Companions | 219 / 219 | 219 / 219 | 0 / 34 | 219 / 219 | 219 / 0 → 219 / 0 (0) | 219 → 219 |
| Locomotions | 108 / 108 | 108 / 108 | 0 / 0 | 108 / 108 | 108 / 0 → 108 / 0 (0) | 108 → 108 |
| Housing | 1,151 / 1,151 | 1,151 / 1,151 | 1,151 / 1,151 | 1,151 / 1,151 | 1,150 / 1 → 1,150 / 1 (0) | 1,151 → 1,151 |

The wardrobe sub-category is the exact slot under a merged type (489 items), or
the shipped `HighHeel` type (828 shoes), or the `HandType` grip (434 hand items).
The companion sub-category is a shipped gameplay component class
(`JG_Familiar` 27, `JG_BattleTank` 5, two others). Housing uses its
ground/wall/ceiling placement.

Other backfilled fields (after): `category_enum` 6,230 wardrobe and 1,151
housing; `slot_side` 938; `locomotion_max_speed` 108; `interaction_classes` 345
housing (`NebulaSeat`, `Bench`, `LightTrigger`); `variant_family` 11 wardrobe, 87
companions, 97 locomotions, 154 housing; bundle `dependencies` (unchanged
source) 2,906 wardrobe, 4 companions, 107 locomotions; `season_hint` 726 / 27 /
11 / 147.

### Catalog API fields

Every row of the management catalog API (`items[]`) now also has the following
fields:

| Field | Meaning and source |
| --- | --- |
| `store_category` | Client category ID used as offer `type_id` (changed for merged L/R slots) |
| `store_category_source` | `shipped_category`, `client_type_icon_merge` or `preservation_compatibility_alias` |
| `store_category_label` | Readable label of `store_category` (wardrobe) |
| `shop_path` | `{type_shop, store_type, gender_id, gender_tab, type_id, type_rank, list}`: the expected client menu path |
| `sort_order` | Dense global position in that client tree |
| `shop_reachable`, `shop_path_correct` | Whether an active offer is reachable in the client menus, and under the expected path |
| `category_group` | `body` or `head` (wardrobe) |
| `category_enum` | `{enum, name, value}` from `AEManager.TypeContent` or `HousingUIContentManager.TypeServerElement` |
| `slot_side` | `left` or `right` for L/R slots |
| `gender_variant` | `MALE`, `FEMALE` or `unisex` |
| `subcategory`, `subcategory_source` | See above |
| `heel_type` | `HighHeel0`–`HighHeel3` from the shipped `HighHeel._type` |
| `hand_type` | `HandType0`–`HandType2` from the shipped `HandType._type` |
| `locomotion_max_speed` | Shipped `Locomotion.MaxSpeed` |
| `component_classes`, `animator_controllers` | Shipped script classes and AnimatorController names in the item's own bundle |
| `housing_menu_element` | Housing editor menu element (`Chair`, `Lamp`, …) |
| `housing_group` | Derived grouping: seating, tables, storage, lighting, decor, flooring |
| `housing_placement` | `{behaviour, slot_kind, placement_cost, serialized_size, max_placement_space, component_class, type_ground, serialized_tablename, serialized_tablename_conflict}` |
| `interaction_classes` | Admitted interaction components from `housing-interaction-manifest.json` |
| `variant_family`, `variant_family_size`, `variant_basis` | Derived: identical internal mesh names in one kind/gender/category |
| `also_in_categories`, `identity_resolution` | Other categories of the same wardrobe ID, and the manifest decision |
| `catalog_metadata`, `metadata_sources` | Provenance of the fields above |

Each offer now has `client_type_id` and `client_reachable`. The `coverage`
summary has `reachable` and `reachable_expected_path`. `seed_full_catalog`
reports `retyped_offers`.

### Unrecoverable and why

* **Commercial data.** No shipped field holds original names, descriptions,
  prices, shop IDs, item-to-store membership, bundles/SKUs, rarity, tier, brand
  or seasonal collection. `ItemData` is filled by the server (`EntryData`).
* **Nine `00_CLOTHS` prefabs.** They have no gender or category evidence and
  live outside `Wardrobe_EAB`, so the client loader cannot request them. One
  carries a `HighHeel` component, which suggests shoes, but its gender is still
  unknown.
* **The original server's order.** The order of categories within a tab and of
  items within a category is not in the client. Enum order and name order are
  preservation choices.
* **Female icons.** The client also ships `FCLOTH_BODY_FEET` and
  `FCLOTH_BODY_TORSO_LEGS_FEET` icons. It never builds those IDs itself, so
  whether the retired server sent them on the female tab is unknown. The
  standard IDs stay in use; both forms display.
* **Rare categories.** `CLOTH_BODY_HAND` and `CLOTH_BODY_TORSOLEGS` (two items
  each) are not in the client enum or icon list. Their grouping stays a
  preservation alias.
* **Companions and locomotions.** 185 companions have no gameplay component in
  their bundle (181 have no MonoBehaviour at all); their behaviour is attached at
  runtime, so they have no shipped class.
  Every locomotion's `typeGender` is `MALE` and carries both male and female
  animations, so there is no gender split.
* **Housing.** Two furniture prefabs serialize a different table
  (`HOUSING_LIGHT` on a lamp, the typo `HOUUSING_CHAIR`). The manifest folder
  decides, because the client loads `Housing/<table>/<id>`. Personal-space rooms
  are not items. The `Appliance` menu has no shipped items.
* **Names and colours.** 628 items still have no usable internal name. Variant
  families do not name colours.
* **3D try-on preview (not changed).** `EntryItem.OnClick` (`0x4a9790`) passes
  `ItemData.id` to `SetShopBase.Init`. That then loads
  `Wardrobe_EAB\<player gender>\<tablename>\<ItemData.id>\FBX\<ItemData.id>`.
  The retired server's `ItemData.id` was therefore the asset ID for these 14
  preview categories. Preservation offers use offer IDs, so the shop's 3D
  preview cannot find the asset. Purchases and listings are unaffected.
  Changing this would change buy, gift and ownership keys. It is left for a
  separate decision.

### Rerun

```powershell
python -m pip install UnityPy==1.25.4
python tools/recover_item_component_metadata.py `
  --game-data 'D:/SteamLibrary/steamapps/common/Nebula Realms/Nebula Realms_Data' `
  --output 'D:/Research/nebula-item-components.private.jsonl' --workers 6
python tools/build_item_catalog_metadata.py --apply-wardrobe-resolutions `
  --components 'D:/Research/nebula-item-components.private.jsonl' `
  --names-scan 'D:/Research/nebula-item-metadata.private.jsonl'
python -B -m unittest discover -s backend/tests -p test_catalog_categories.py
```

The component scan reads every manifest-backed identity, including conflicting
and unknown rows, and verifies each manifest hash. Output is byte-identical for
the same scans. The committed `protocol/item-catalog-metadata.json` was built
from the component scan `bada731f…` and the name scan `5f4bd72a…`.

## Where store information comes from

The retained IL2CPP schema has `ShopData` fields `id`, `name`, `desciption`
(original spelling), and `url`. `TypeData` carries `shopID`, `typeID`, and
`gender`. `ItemData` carries `id`, `name`, `imagePath`, `crystals`, `np`,
`isBundle`, `gender`, and `tablename`.

The focused native decompilation of
`ShopNETGcloud.Get_GetItemAssetsData` at RVA `0x40c420` reads the item count,
creates `ItemData` instances, calls `EntryData.Deserialize` for each returned
entry and calls the shop window's `BaseWindow.Populate`. This is a custom
`EntryData` serializer, not JSON serialization. It is direct evidence that the
server supplies item listings and their commerce fields. Local resource assets
provide meshes, textures, sprites and paths; those resources alone do not
reconstruct the old server's catalog database.

The preservation server currently authors its own store policy. These configured
stores, labels and prices must remain distinguishable from historical facts.
Administrative store edits should change the same offers used by game listing
and purchase handlers, so the panel and game cannot disagree about a price or
whether an offer is enabled. Inventory grants are separate from store offers.

## Apartments (personal spaces)

The shop sold apartments in the GenderWindow `Spaces` tab (gender 4). In
`EntryGender.OnClick` (RVA `0x4a86e0`) case 4 skips `GetShopTypeData` and calls
`ShopNETGcloud.Send_GetItemAssetsData` (`0x411490`) with type `PERSON`, so the
request is `GetItemAssetsDataServlet guid#ps4#shopID#4#PERSON`. The reply is the
ordinary `ItemData` list (`0x40c420`). `EntryBase.setThumbnail` (`0x4a7f90`) loads
an `imagePath` containing `PersonalSpaces/` from shipped Resources, and
`EntryItem.OnClick` (`0x4a9790`) always calls
`WardrobeWindow.ShowScrollPersonalSpacesScreenShots` (`0x4b8030`), which loads
`PersonalSpaces\<ItemData.id>\screenshot<i>` until one is missing. After a buy
reply of `OK`, `Get_NPShopBuyItem` (`0x40f230`) marks the buttons purchased,
refreshes the wallet and re-runs `HTTPGetPurchases` (`0x6350d0`). The navigator
then enables an apartment whose `personalspacesName` matches its entry.

`resources.assets` has 31 `personalspaces/<id>/` folders (a thumbnail and 2–13
screenshots each). The client has no table from those shop IDs to navigator
names; the retired server supplied it in `GetPurchases`. The mapping in
[protocol/personal-space-shop.json](../protocol/personal-space-shop.json) was
recovered by matching each ID's shipped images to readable text (`NEBU HOUSE`,
`NEBULIAN`, `West Valley Apartment`, `Windmill Farmhouse`, `Tokyo Penthouse
Apartment`), the shipped `shops/bluewavehideout` banner, or the asset names in
the shipped `s/<scene>` bundle (for example the cliff, boat and lighthouse of
`CliffApartment` or the `Crypt_*` set of `TheCrypt`). Each entry records its
basis. Thirty IDs map one-to-one to the 30 navigator apartments other than
`Home`. `Home` has no shop ID: it is the free native default. The 31st ID shows
a haunted farmhouse that matches no shipped scene, so it is not offered.

Preservation policy (not recovered): the catalog seeds one active offer per
mapped apartment in a HOUSING-type store `preservation-catalog-v1-personal_spaces`
("Preservation Apartments", shipped `bluewavehideout` banner) at 150 crystals or
75 NP, five times the furniture price. `ItemData.id` is the shop ID,
`tablename` is `PERSON` and `gender` is the non-avatar value `PersonalSpace`, so
the client shows the screenshots instead of starting a 3D try-on. Staff change
prices or hide offers on the Stores page as for any offer. Buying, gifting or a
staff offer grant creates the apartment binding (the same path as a starter or
staff grant); an owned apartment, including a starter one, answers
`NPShopIsItemPurchased` with `True` and a buy with `ISPURCHASED`.

## Offline extraction and coverage limits

`tools/recover_item_asset_metadata.py` reads canonical catalog identities using a
fresh disposable scratch database, verifies each selected manifest against its
pinned hash, and parses the corresponding bundle with UnityPy. It records bundle
SHA-256, typed object names and path IDs, TextAssets, decoded MonoBehaviour
strings and per-object decoding errors. It never changes the game or live
service database and never fetches remote content. Output must be outside the
repository. Generated private research data and artwork are not part of this
public source tree.

The recovery run used UnityPy 1.25.4. Install it in your research environment,
then run, for example:

```powershell
python -m pip install UnityPy==1.25.4
python tools/recover_item_asset_metadata.py `
  --game-data 'D:/Games/Nebula Realms/Nebula Realms_Data' `
  --output 'D:/Research/nebula-item-metadata.private.jsonl' --workers 4
```

`--kinds companions housing` narrows extraction. Output appends and resumes by
the full canonical identity; use a new output file after updating the game or
catalog. A malformed/truncated previous JSONL file is rejected rather than
silently skipped. The tool accepts at most eight parser processes.

The main-file pass covered `resources.assets`, `globalgamemanagers.assets`,
`sharedassets0.assets`, and `level0`. Seven TextAssets decoded: `AssetBundleServerURL`,
`LICENSE`, `iso4217`, `BillingMode`, `LineBreaking Leading Characters`, `COPYING`,
and `LineBreaking Following Characters`. These are configuration, licensing,
currency and typography data, not an item name/description catalog. The main-file
pass encountered **3,528 MonoBehaviour typetree decoding failures**. That is an
explicit coverage gap: this pass does not prove that no serialized names exist
in undecoded MonoBehaviours. The companion-bundle pass decoded all 219 bundles
without object errors and found no TextAssets in them.

Decoded component strings in the item pass include object IDs, category/table
names, interaction prompts such as `Use Seat` and `Switch on`, companion sign
phrases and third-party Cartoon FX shader/help instructions. Fields named
`Title` or `HelpText` can belong to those third-party effects; their names do not
make their values item titles or commerce descriptions.

No exact historical item-name/price/store database, localization catalog, or
authenticated old store response has been recovered by this investigation. The
derived display labels above do not change that finding.
This is a bounded finding about the inspected artifacts, not proof that no
archive or other game version contains one. Minigame recovery and game runtime
testing are outside this metadata investigation.

## Evidence pins

| Evidence | SHA-256 / location |
| --- | --- |
| Existing resource path inventory | `296f82bfff1cbb1e3e3536ebb3889ea58679754a04ef83aeef4a8c797fbc618a` |
| Existing bundle manifest inventory | `d4673f1229a7b3f3ce0813081590990e16897c91988ad9ec16745d010aa5cdb5` |
| Retained focused native `40c420.c` pseudocode | `1efbc09b8e8b2d5825e44b0c5b5ae77f79ddc23dee9efc383deef4b43301b8a2` |
| Private four-main-file typed scan | `cf152f3e96c62c8e304476f9613224ace92e9596769f7078aa2f2dc621bbf07d` |
| Private complete item JSONL typed scan | `c680b9c099682d6a64e806893e2f4b7a3867d178a87b620b5337c491a475e7a4` (7,688 rows) |
| Same scan with 24 resolved wing identities appended | `5f4bd72a56eba454f3b967c1edf409be2f173fe49e1d513555579ed6f0a6b05c` |
| Private component scan (7,853 manifest rows, 7,753 bundles, 0 errors) | `bada731f3b004b9d7e4f8699b6f59028deff127e6117765abdd7a79a5b466c43` |
| Native `EntryItemType.Set` / `BaseWindow.Populate` / `EntryItemType.OnClick` | GameAssembly RVAs `0x4a90e0`, `0x4a5950`, `0x4a8de0` |
| Native `SetShopBase.Init` / `LoadItemSelected` | GameAssembly RVAs `0x468390`, `0x470310` |
| Client enums | `dump.cs`: `AEManager.TypeContent` 169, `ShopNETGcloud.TypeShop` 532, `HousingUIContentManager.TypeServerElement` 366, `HighHeel.HighHeelType` 205, `HandType.HandTypeenum` 203, `HousingAsset.TypeBehaviour` 300 |
| IL2CPP schema | `dump.cs`: `ShopData` TypeDefIndex 1176, `TypeData` 1178, `ItemData` 1179, `EntryData` 298 |

Native pseudocode is reconstructed evidence, not original C# source. Typed
bundle object reads establish internal names only; display-label derivations
are an explicitly separate interpretation.
