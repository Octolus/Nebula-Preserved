> Historical research: this file records an earlier investigation, not current feature acceptance. The root [PROGRESS report](../PROGRESS.md) is authoritative. Local evidence and extracted game code are intentionally omitted. See [research index](README.md).

# Rewards, cinema and space-liveness HTTP

Nine non-minigame routes now have a bounded replacement module. The client wire shapes are recovered; reward availability and mapping are explicit local preservation configuration because the retired service's prices, balances, schedules, eligibility and historical claims are unavailable.

| Route | Recovered request | Client-consumed response |
|---|---|---|
| `CheckOwnGenericReward` | `GUID#PS4ID#assetID` | fields0..2 unread, field3 already-owned Boolean |
| `GenericReward` | `GUID#PS4ID#assetID` | fields0..2 unread, field3 newly-granted Boolean |
| `RewardClothServlet` | `GUID#PS4ID#rewardInt` | fields0..1 unread, field2 reward Boolean |
| `RewardConsumeServlet` | `GUID#PS4ID#assetID` | `true#GUID#PS4ID` |
| `SKLPromoTriggerServlet` | `GUID#PS4ID#promoInt` | `true#GUID#PS4ID#alreadyConsumedBool` |
| `SKLPromoServlet` | `GUID#PS4ID#promoInt` | `true#GUID#PS4ID#spriteInt` |
| `checkRewardAvailableServlet` | `GUID#PS4ID#RewardTypeName` | `true#GUID#availableBool` |
| `CinemaInteractionNPServlet` | `GUID#PS4ID#interactionInt` | `true#GUID#PS4ID#successBool` |
| `CheckIfSpaceStillExistServlet` | `GUID#PS4ID#instanceID` | `true#existsBool` |

Shared AES appends the platform-name trailer to every logical request before encryption. Server replies do not append a platform field.

## Local reward authority

No endpoint grants from its route name or caller-supplied asset ID. An administrator configures a route/key and a target that must resolve through an existing shipped catalog. Supported targets are wardrobe, companion, locomotion, housing, coffee and Oktoberfest entitlements. Invalid or ambiguous IDs are rejected during configuration. Numeric text must be canonical `Int32.ToString` form, so aliases such as `00` and `-0` fail closed. Cinema accepts only native interaction0 Ticket and1 PopCorn and records a local durable capability; it performs no currency transaction.

The native and shipped-asset domains are enforced:

- `RewardClothServlet` accepts only trigger `0`, the only value written by `Send_rewardBeachTShirt`, and only a wardrobe target.
- `checkRewardAvailableServlet` accepts the 12 compiled `Utils.RewardType` names: `Halloween`, `ArcheryBow`, `ArcheryCarcaj`, `Chess`, `CastleSword`, `PatricksDay2018`, `Cube`, `CampSilverLake0` through `CampSilverLake3`, and `GhostWolf`.
- Static UnityPy type-tree extraction found six shipped `SKLPromoTrigger` components with IDs0 through5. Every component has a pair-aligned 12-entry `aSprites` array, so the only safe response sprite-pair indices are0 through5. Both promo ID and returned sprite index are checked against [skl-promo-catalog.json](../../protocol/skl-promo-catalog.json); this matches native `aSprites[2*i]` and `aSprites[2*i+1]` access.

Claims use `(account, route, trigger)` as their durable identity. Entitlement mutation and claim-marker insertion run in one `BEGIN IMMEDIATE` preservation transaction, after all lazy schemas have been initialized. A failure or crash between an additive consumable credit and its marker therefore rolls back both; retry grants exactly once. A repeated claim returns the response shape the client expects but does not duplicate the entitlement. Check routes inspect a corresponding claim or explicit availability definition. Missing/disabled definitions fail closed, except `checkRewardAvailableServlet`, whose recovered UI behavior naturally accepts `available=false`.

Example offline configuration:

[Code/listing block omitted from the public research archive.]

`SKLPromoServlet` additionally requires `--sprite-id`. Consumable targets require matching `--grant-kind`/`--item-id` (`coffee` or `oktoberfest`) plus positive `--units` and `--uses`. These commands only edit local SQLite state.

## Space liveness

The MITM coroutine sends the current session, account and `SpaceParams.id_instance`. It treats only `true#true` as existing. A false result re-enters `LoadSpace` for the current scene; true loads that scene locally.

The replacement returns true only when the current session allocation matches the requested instance and `InstanceDirectory` finds a fresh, unique, loopback descriptor whose `instance_id` and `psidglobal` both match that allocation, with `listening:true` and `protocol_complete:true`. Session GUID/account and stored/request platform must also agree. This is an explicit compatible local authority check. It does not fabricate readiness. Static call-context evidence shows `MITM_Space.Start` tail-jumps `loadScene`; after a successful unload its callback starts the liveness coroutine, although this remains static reachability rather than runtime observation.

Nine socket-forbidden offline tests cover configuration validation, closed enum/trigger domains, canonical numeric forms, shipped SKL sprite-pair bounds, unknown-definition rejection, durable and idempotent wardrobe/resource grants, promo check/consume pairing, cinema persistence, liveness freshness/instance/world matching, session platform identity, ownership, field counts and unsupported routes. A fault injected after additive consumable credit but before claim insertion is reopened from disk to prove that neither write survives, and that retry grants once. No game, listener or connection was started.

Machine-readable contracts and source hashes are in [http-rewards.json](http-rewards.json). Original authorization and commercial policy remain unknown.
