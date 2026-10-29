> Historical research: this file records an earlier investigation, not current feature acceptance. The root [PROGRESS report](../PROGRESS.md) is authoritative. Local evidence and extracted game code are intentionally omitted. See [research index](README.md).

# Non-minigame HTTP gap audit

This is the bounded preservation status for Steam build 11018722. It covers account, inventory, avatar, world allocation, chat/social handoff, consumables, personal-space and housing HTTP behavior. Minigames and FullGameNETGCloud match, leaderboard and reward flows are explicitly deferred. Native pseudocode is not original C# source, and no original backend policy is claimed where the evidence only proves client framing.

## Current implementation

The offline service exposes 92 allowlisted routes. Its durable state is SQLite plus atomic JSON handoff files. Importing the backend opens no socket. The 120 offline backend tests patch `socket.socket` to fail. Current per-module counts and source-bound results are in `../offline-validation.json`.

The instance registry accepts only fresh, protocol-complete, listening loopback descriptors. New instances publish `instances/<instance_id>/instance-status.json`; the root `instance-status.json` remains a single-instance compatibility fallback. Duplicate instance IDs or endpoints fail closed. Selection can constrain scene, exact instance and an excluded instance, and prefers the least populated compatible instance.

The native login callback requests literal `Login`. The local explicit default maps that request to the actual `Nexus` scene. `N2SpaceLoading` retains the recovered six-field response: GUID, ready, instance ID, actual scene bundle key, IP and port. Its endpoint comes from the fresh validated descriptor rather than a stale allocation record. Personal-space logical navigator labels are separately bound to verified actual scene keys.

Shared root handoff files contain accounts, relations, immutable friend events and consumable receipts. Status, presence, avatar state and durable poses are per instance. Only fresh, allocation-matching presence establishes online state. Account export includes only the latest session for each account. Wardrobe state is a 60-second renewable local lease, is cleared by removal, and includes the allocated instance in snapshots. A valid avatar-state capability marker `mirror_after_avatar_ready_v1` makes `GetAllInWardrobe` return `OK#`, preventing a duplicate HTTP ghost when the instance already mirrors wardrobe players after avatar readiness.

## Housing

Manifest analysis initially produced 1,153 housing candidates and 15 conflicting/malformed paths. Direct read-only prefab component inspection validates 1,151 grantable IDs. Two additional manifest-named candidates are rejected because the contained `HousingAsset` identity differs from the manifest ID. Older valid `Assets/ART/ResourcesART` paths remain accepted when their internal component identity matches. Catalog availability never implies ownership.

An administrator explicitly binds `(instance_id, actual psidglobal, owner_ps4_id)` and may optionally provide a logical navigator label. All 31 shipped navigator labels have placement metadata, so explicit alias registration covers every shipped personal-space choice without guessing an unproven scene key. Owners may save; allocated visitors may read. The multipart layout stores 100 ground entries per part and repeats wall/ceiling arrays in both parts, matching the recovered request shape. Empty reads contain all ten non-null arrays. Layouts, grants and bindings are durable in SQLite.

The client has a recovered placement-space budget of 200 (`HousingFurnishing.GetTotalSpace`/`ThereIsEnoughSpace`, RVAs `0x6BD1D0`/`0x6BF2B0`). `HousingAsset.size` is serialized as 0 or 1 in all supported shipped prefabs; all four registration methods convert zero to one before increasing occupied space (RVAs `0x6BD470`, `0x6BD510`, `0x6BD5B0`, `0x6BD650`). Thus this is a one-unit-per-wire-entry placement bound, not a currency price. Prefab components prove wall hangings use wall placement, lights use ceiling placement, and the other shipped categories use ground placement. Wall/ceiling indices are bounded by the exact arrays on the `HousingFurnishing` referenced by each shipped scene's `HousingManager`. `housing-placement-contracts.json` records the item and 31-space evidence.

Bad-position, collision, floor-area and transform interaction rules are client-side scene behavior. The save wire contains only IDs, transforms and slot indices, so the local service does not invent an original server geometry check. It validates explicit entitlement, internal prefab identity, placement class, the 200-space budget and authored slot bounds.

Implemented housing routes are `GetHousingTypeServlet`, `HousingReadPresetServlet`, its `N2HousingReadPreset` alias, `HousingSavePresetServletParts`, `GetPersonalSpacesServlet` and `N2GetUserTypeSpace`. Placement cost, per-prefab class and scene-specific slot bounds are recovered in housing-placement-contracts.json. The free-transform aidasset channel includes both ground and floor subclasses, matching SaveAtServer6bdb40.

## Other restored contracts

- `GetInfoServlet` modes 0, 1, 2 and 3 preserve their distinct request and response framing.
- Modern and legacy news paths receive complete pairs and explicit local preservation text; no retired content is fabricated.
- Modern and legacy social routes keep distinct DTO/framing contracts. Positive player lookup requires unique exact username/platform, fresh presence, a matching allocation and a ready instance.
- Companion and locomotion lists, purchases and instance snapshots use one explicit canonical entitlement source.
- Consumables use persistent balances and opaque one-use UUID receipts; minigame picnic use is rejected as deferred.
- Reports are local durable receipts only. No external moderation authority is claimed.
- PSN friend enumeration returns an explicit empty local result because this Steam preservation service has no PSN credential authority.

## Remaining non-minigame limits

1. Original server-side collision/geometry validation is unknown; the client-side authored checks cannot be reproduced from the save wire alone.
2. Navigator labels are complete, but actual retired-service scene aliases remain unproven; verified actual scene keys must be bound explicitly.
3. Multipart housing requests have no revision identifier, so cross-save interleaving cannot reproduce an unknown original transaction policy.
4. Paid shop commerce and historic rewards have no authoritative receipt or pricing source; purchase success is not fabricated.
5. Full runtime/network parity remains unproven because game, server, listener, connection and attachment tests are deferred.

The machine-readable companions contain 1,153 manifest candidates, 15 manifest-path rejections, two additional internal-component identity rejections, 1,151 verified grantable prefabs, exact housing/GetInfo/legacy variants, scene slot bounds, evidence hashes and local-policy labels.

The bounded modern task inventory contains 40 command literals. The service implements all non-commerce candidates. The only three absent task commands are `STMBuyCrystals`, `STMCompleteOrder` and `STMCompleteSucceededOrders`; these are paid-commerce operations, not mandatory non-game initialization, and cannot safely succeed without authoritative Steam receipt/order state.

## Expanded ordinary features

Shop, gifting, generic rewards/promotions, gathering/events, cinema interactions, separate space liveness and maintenance status now have handlers. Local shop offers, wallets, reward definitions and event configuration are explicit administrator policy; original commercial catalogs and event schedules are unavailable. Store.atomic groups debits, entitlement grants and claim markers. Failure-injection tests verify rollback after reopening SQLite. See http-shop.md, http-rewards.md, http-gathering.md and http-maintenance.json.
