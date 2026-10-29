> Historical research: this file records an earlier investigation, not current feature acceptance. The root [PROGRESS report](../PROGRESS.md) is authoritative. Local evidence and extracted game code are intentionally omitted. See [research index](README.md).

# Shop HTTP reconstruction

This document separates recovered client wire facts from preservation policy.
It does **not** claim recovery of the retired service's catalog, prices,
balances, eligibility rules, or Steam commerce.

## Recovered wire facts

The native client appends `#PS4` or `#StandaloneWindows` after the logical
request fields. `Request.parse` removes that trailer before `Shop.dispatch`.
Every reply below is plaintext before the existing HTTP encryption wrapper.

| Route | Logical request fields | Accepted response shape |
|---|---|---|
| `GetFeaturesServlet` | `guid, ps4ID` | list of `ItemData` |
| `GetGenderDataShopServlet` | `guid, ps4ID, shopID` | flat `genderID, Boolean` pairs |
| `GetItemAssetsDataServlet` | `guid, ps4ID, shopID, genderID, typeID` | list of `ItemData` |
| `GetShopDataShopServlet` | `guid, ps4ID, bool, bool, typeShop` | list of `ShopData` |
| `GetShopInfoPlayerShop` | `guid, ps4ID` | `true#guid#ps4ID#name#np#crystals` |
| `GetShopTypeDataShopServlet` | `guid, ps4ID, shopID, genderID` | IDs 0/1: `TypeData`; IDs 2/3/5/6: `ItemData` |
| `NPShopBundleItemsServlet` | `guid, ps4ID, itemID` | list of `ItemData` |
| `NPShopBuyItemServlet` | `guid, ps4ID, itemID, itemCrystals, itemNp, option` | `true#guid#ps4ID#STATUS` |
| `NPShopGiftItemServlet` | `guid, ps4ID, itemID, friendTarget, amountCrystals` | at least six fields; field 3 status, field 4 target |
| `NPShopIsItemPurchasedServlet` | `guid, ps4ID, itemID` | `true#guid#ps4ID#True|False` |
| `NPShopSyncCrystalsServlet` | `guid, ps4ID, idCrystals, date_owned, consumedCount:Int64` | `true#guid#ps4ID#name#np#crystals` |

EntryData list replies use `true#guid#ps4ID#count` followed by `count` serialized
`EntryData` values. Consequently, the exact client-accepted empty list is:

[Code/listing block omitted from the public research archive.]

`GetGenderData` is the exception: its field 3 is the number of following
scalar fields (`2*N`), followed by flat `genderID#Boolean` pairs. Its exact
empty form is still `true#guid#ps4ID#0`.

DTO field order is recovered as follows:

- `ShopData`: `id:string`, `name:string`, `desciption:string`, `url:string`.
  `desciption` is the compiled client's spelling.
- `GenderData`: `genderID:int`, `show:bool`.
- `TypeData`: `shopID:string`, `typeID:string`, `gender:string`.
- `ItemData`: `id:string`, `name:string`, `imagePath:string`,
  `crystals:int`, `np:int`, `isBundle:bool`, `gender:string`,
  `tablename:string`.

The buy receiver compares field 3 with the literal enum names `OK`,
`NOCRYSTALS`, `NOXP`, and `ISPURCHASED`. The gift receiver requires six
fields, compares the same status names, and reads field 4 as the target when
reporting `ISPURCHASED`; its required field 5 is not read in the inspected
receiver. The replacement returns the offer ID in field 5, an authored
compatibility choice rather than a recovered meaning.

The ShopManager field layout proves the three ShopInfo/Sync values are
`name`, `np`, and `crystals`, in that order. The replacement uses the
authenticated local profile name and local wallet balances.

## Local preservation policy

- The shop starts empty. No original offer, name, image, price, balance, or
  promotion is fabricated.
- An administrator explicitly configures shop presentation, offers, and
  balances with `shop_admin.py`.
- Every non-bundle offer and thumbnail is derived from a shipped, unambiguous
  wardrobe, companion, locomotion, or housing manifest entry. Bundles can
  contain only configured, non-bundle offers and require explicit reuse of a
  configured shipped thumbnail; this does not claim original bundle artwork.
- Configured server prices are authoritative. The displayed prices echoed by
  Buy/Gift must match the current offer but never determine the debit.
- Native call sites prove buy option `0` is the crystal button and option `1`
  is the NP button. The replacement spends the corresponding configured local
  balance and uses the client's `NOXP` status on NP insufficiency.
- Buy and gift retry after ownership returns `ISPURCHASED` without another
  debit. The native gift wire carries the displayed friend name but no platform;
  the replacement requires exactly one matching local friend across platforms.
- Ownership is rechecked under `BEGIN IMMEDIATE`. The conditional debit, every
  entitlement in a bundle, and the ownership claim share one `Store.atomic()`
  group. Nested grant helpers cannot commit early; any failure rolls the whole
  group back. Offline fault tests cover failure after a single entitlement
  insert and failure on a later bundle child, including close/reopen checks.
- Crystal sync fields are untrusted receipt observations. They are validated
  syntactically (including the native signed 64-bit consumed count) but cannot
  mint, overwrite, or spend a local balance.
- `STMBuyCrystals`, `STMCompleteOrder`, and `STMCompleteSucceededOrders` remain
  disconnected. No response from this module represents a real purchase.

## Static evidence

The machine-readable companion records sender/receiver RVAs, native evidence
hashes, and implementation/test hashes: [http-shop.json](http-shop.json).
Decompiled C is treated as native pseudocode evidence, not original source. No
game, server, listener, connection, process attachment, or UI automation was
used for this work.

