> Historical research: this file records an earlier investigation, not current feature acceptance. The root [PROGRESS report](../PROGRESS.md) is authoritative. Local evidence and extracted game code are intentionally omitted. See [research index](README.md).

# Coffee and Oktoberfest HTTP consumables

Scope: bounded static recovery of the two non-minigame flows. Picnic is explicitly deferred. This document does not claim that the retired server's economy, prices, defaults, reward catalog, or receipt grammar were recovered.

## Observed client contracts

Both routes receive the logical request `SessionGUID#PS4ID#consumableID#tableID`; the common AES wrapper adds the platform trailer. The observed coffee and Oktoberfest callers always supply decimal table ID `0`.

`GetConsumablePriceServlet` must return nine fields for these callers:

`true#GUID#PS4ID#coffee|oktoberfest#unused#priceDisplay#priceTypeDisplay#userAmountsDisplay#rewardedBool`

Fields 5, 6 and 7 are copied as display strings and are not numeric-parsed. Field 8 is `Boolean.Parse`d. Therefore the preservation server uses field 7 to display its locally authored remaining-unit balance; this is policy, not proof of the old field's business meaning.

`GetConsumableServlet` must return eight fields:

`true#GUID#PS4ID#coffee|oktoberfest#unused#successBool#opaqueReceipt#giveRewardIndexInt`

On success the client copies field 6 verbatim to TCP `44#GUID#coffee#opaqueReceipt` or `46#GUID#oktoberfest#opaqueReceipt`. It does not parse that field as a balance. Field 7 is parsed separately into the UI `giveRewardIndex` integer. On failure the preservation response retains the eight-field shape and uses `false`, an empty receipt, and reward index `0`.

## Preservation policy

No account gets a default grant and no real purchase/payment is represented. The local administrator grants units and must explicitly choose the stable positive `prop_use_count`; no original default was recovered. Issuance deducts one local unit and creates a UUID-N receipt with a short expiry. The HTTP process publishes an immutable JSON file under `consumable-receipts/`. The instance validates actor GUID, account/PS4 ID, kind, timestamps and positive count, then atomically moves the file on the same volume to `consumable-claims/`. Only the first move succeeds. Numeric client-supplied counts are never accepted.

The HTTP database later imports claim files idempotently. A claim's complete payload must equal its database issuance row. The state directory is a trusted server-local boundary; the receipt is not a cryptographic authorization object for untrusted filesystem access.

The locally chosen use count maps to the native initializer's current and maximum counters. Static bodies for `InitPlayerCoffee` (`0x403280`), `InitPlayerOktoberFest` (`0x403e40`) and `Consumable.InitConsumable` (`0x404800`) establish this mapping. Existing-prop refill behavior restores the stored maximum, so changing the grant policy affects newly constructed props, not an already-present prop's maximum.

Scene authorization remains separate from HTTP balances. Static prefab inventory found an active FoodTruck manager in LeafPark; its Oktoberfest groups are inactive, and Nexus has neither. A balance alone must not bypass the instance's active compatible scene registry.

## Admin and integration API

Offline grant:

`python consumable_admin.py --state-dir <dir> grant <account> coffee 5 --uses 10`

`Consumables.price_response(ps4_id, guid, kind, table_id)` produces the exact price envelope. `Consumables.issue_response(...)` atomically deducts a local unit, publishes the receipt and produces the exact issue envelope. `Consumables.import_claims()` reconciles instance claims. The HTTP router should bind only the exact `GetConsumablePriceServlet` and `GetConsumableServlet` names and parse exactly four logical request fields.

## Evidence and remaining unknowns

Primary bounded decompilations and hashes are indexed in `http-consumables.json`. Observed facts are the request/envelope field positions, callbacks, TCP forwarding, and initializer counter behavior. Unknowns include original prices/currency strings, balance/deduction rules, reward index catalog, receipt grammar, expiry, anti-replay scheme, and authoritative per-kind use-count defaults. Every such value in this implementation is labeled local preservation policy.

