> Historical research: this file records an earlier investigation, not current feature acceptance. The root [PROGRESS report](../PROGRESS.md) is authoritative. Local evidence and extracted game code are intentionally omitted. See [research index](README.md).

# Rewards, cinema and liveness: native second pass

This is a static source-vs-native review. It did not run the game, open a listener, attach to a process, or make a connection. All original reward and commercial policy remains unknown unless explicitly labeled as local preservation policy.

## Outcome

All nine current response shapes have the field count, order and parse type consumed by the reviewed client. The five concrete over-broad acceptance surfaces found in this pass are now closed. This still is not semantic parity: generic ownership semantics and cinema policy remain authored or unresolved.

| ID | Severity | Route | Finding |
|---|---|---|---|
| RSP-001 | high | `RewardClothServlet` | configuration and stored-definition readback now require canonical trigger0 and a wardrobe target. |
| RSP-002 | medium | `checkRewardAvailableServlet` | configuration and dispatch now whitelist the exact 12 enum names; enabling each remains administrator policy. |
| RSP-003 | high | `SKLPromoServlet` | UnityPy extraction recovered promo IDs0..5 and six 12-entry arrays; configuration/readback validate both promo ID and sprite-pair index0..5 against that catalog. |
| RSP-004 | medium | `CinemaInteractionNPServlet` | both are represented as durable generic cinema capabilities and every configured/repeated claim returns success; no price, charge, 10-use prop state or admission rule is modeled. |
| RSP-005 | high | `CheckIfSpaceStillExistServlet` | the allocation query and ready descriptor now match both instance_id and psidglobal. |
| RSP-006 | medium | `CinemaInteractionNPServlet and numeric reward routes` | integer() now requires value == str(parsed_int), so aliases such as `-0` and `00` fail closed. |
| RSP-007 | medium | `CheckOwnGenericReward / GenericReward` | ownership is only the local route claim marker. An entitlement acquired through another local source reports false; a first route claim can report newly granted true even when the idasset entitlement already existed. |
| RSP-008 | medium | `all nine routes` | dispatch now requires request.platform to equal the profile's stored platform after GUID/account validation. |

## Concrete corrections

### RSP-001 — `RewardClothServlet`

Native: Send_rewardBeachTShirt writes request reward=0 unconditionally; callback UI success is additionally gated on request reward==0.

Required: implemented

### RSP-002 — `checkRewardAvailableServlet`

Native: request uses Utils.RewardType.ToString over a closed 12-name enum.

Required: implemented

### RSP-003 — `SKLPromoServlet`

Native: response[3] is Int32.Parse; SetSprites indexes aSprites[2*id] and aSprites[2*id+1], throwing when either index is outside the serialized array.

Required: implemented with protocol/skl-promo-catalog.json

### RSP-005 — `CheckIfSpaceStillExistServlet`

Native: true#true loads SpaceParams.scene locally; false/error calls LoadSpace for that scene. Request field3 is SpaceParams.id_instance.

Required: implemented; freshness/protocol completeness remains stricter local policy

### RSP-006 — `CinemaInteractionNPServlet and numeric reward routes`

Native: Int32.ToString emits canonical decimal text; the cinema client can emit only `0` or `1`.

Required: implemented

## Cinema acceptance transitions

The request enum is exactly `Ticket=0` and `PopCorn=1`. A generic `OnSend` success must be `true#<local GUID>#<local PS4ID>#<Boolean>`. Callback `false` performs no mutation. Callback `true` sets the corresponding in-memory flag. Ticket then displays the purchase popup. PopCorn instantiates the prefab and initializes `ConsumablePopCorn` with 10 uses. The reviewed `CinemaSpaceTrigger.Interact` loads the cinema without checking the ticket flag; therefore server-side price, ticket lifetime and admission enforcement must not be claimed as recovered.

## Space liveness

The request is `SessionGUID#PS4ID#SpaceParams.id_instance`; the callback consumes `true#Boolean`. True loads `SpaceParams.scene` locally, while false or network failure calls `LoadSpace` for that scene. The backend's freshness rule is compatible local policy, but its ready descriptor must match both allocation instance ID and `psidglobal`. Bounded disassembly proves `Start` tail-jumps `loadScene`, whose successful unload callback starts the liveness coroutine; this is static reachability, not runtime observation.

## Residual unknowns

- reward eligibility, schedules, cooldowns and historical claims.
- asset-to-entitlement mappings and repeat-claim behavior.
- cinema prices, currency deductions, ticket lifetime and admission policy.
- original SKL eligibility and server rule selecting the returned sprite-pair index.

Machine-readable findings and verified source hashes are in `rewards-second-pass.json`.
