> Historical research: this file records an earlier investigation, not current feature acceptance. The root [PROGRESS report](../PROGRESS.md) is authoritative. Local evidence and extracted game code are intentionally omitted. See [research index](README.md).

# Remaining world interactions

This is static client reconstruction plus explicit replacement-server policy. It is not recovered server source or proof of original-server parity. No game, client, server, listener or connection was started. Minigame gameplay is deferred at the user's request. The companion JSON contains 82 hashed native pseudocode sources and a read-only inventory of all 48 modern logic prefabs, including object ancestry and active flags.

## Boats31

`HarbourEnter.Callback451640` first calls `InstantiateBoatAndSeatPlayer451a10` for the local avatar, then sends `31#guid#True#boatIndex`. `BoatTripManager.Callback545860` likewise instantiates locally; its local branch in `545c50` sends `31#guid#True#0`. This is a report of local entry. Sending the accepted True back to the sender would instantiate another boat.

The client receiver `5d72a0` reads `guid,bool,int32`. With True and an existing avatar it assigns the token to the scene HarbourEnter/BoatTripManager, then starts a delayed remote instantiate at the avatar's transform. Both delayed bodies are recovered (`5e8020`,`5e8140`). The token indexes the manager's actual `boatPrefab` array; it is a variant index, not an exclusive boat resource or a globally unique seat.

The default Nexus has no boat manager. LeafPark has a verified three-entry HarbourEnter array:

| Token | Referenced prefab name | Serialized component path ID |
|---|---|---|
| 0 | Leaf Park Boat | -2324118105054757748 |
| 1 | Swan Boat | 2072375922925621194 |
| 2 | Flamingo Boat | 3483699390274241163 |

The path IDs identify the shipped Unity objects. Only array positions0..2 are wire tokens. Their raw hashes and complete fields are in the JSON. The Nexus registry is empty; the LeafPark registry accepts exactly these tokens. Greenhouse has paddleboat token0. Beach, BlueWaveHideout and TheNebulian have rapid-boat token0. These additional arrays were inspected individually; no global token registry is inferred.

`Boat.FixedUpdate44ce10` sends `31#guid#False#index` before local HarbourExit. The S2C31 processor explicitly does nothing with False. Both Boat and BoatRapid FixedUpdate return immediately for remote avatars. `Vehicle.SetAsRemote474470` only reparents, adjusts seat offsets and sets kinematic state. `StopControl44db70/44c830` disables control/components; neither destroys the prop nor clears `NebulaPlayer.vehicle`. The destruction and pointer clear are in local `HarbourExit.Exit452400` / `BoatTripManager.Exit545920`.

Consequently, a False echo cannot restore remote boat exit. The pure module removes its retained boat record and emits no invented cleanup packet. The parent selected a server compatibility refresh: only after an accepted False for a recorded active boat, retire the remote actor for ready other viewers with14/Mirror destroy, clear its stale seating animation and visibility marker, wait at least two server Unity frames, then spawn the same netId and send PlayerJoined1 again. The owner connection/local entity remains in place. Pending refreshes must revalidate actor/session/viewer and suppress other actor updates until the reseed. This reuses the wardrobe retirement/rebuild mechanism. The two-frame boundary is authored timing policy to separate Unity destruction/rebuild, not recovered original-server behavior or runtime proof. A managed False hook was an alternative design and is not selected or installed.

Rapid-boat exit has a separate gap. `BoatRapid.FixedUpdate44bab0` calls local `BoatTripManager.Exit545920`; that exit destroys and clears the local vehicle but contains no TCP send. Its recovered StopControl path also sends nothing. Consequently the server refresh has no exit trigger in Beach, BlueWaveHideout or TheNebulian. A preservation client hook that emits False after the proven local exit, or another proven native trigger, is still required. No such hook is installed by this module. Rapid entry and late-viewer snapshots are implemented; rapid exit synchronization remains incomplete.

There is no reviewed boat query command. A retained True may be sent to a newcomer only after its target avatar has finished building. `SnapshotActor` provides this and suppresses repeated snapshots for the same viewer/actor activation. Broadcasting before the avatar exists loses the packet; sending the same True repeatedly creates duplicates.

## Generic interactables94

`OnConnected5ea6e0` enumerates `FindObjectsOfType<GenericInteractable>` and calls `Initialize451060`. That calls `NebulaInteractor.AddGenericInteractable5deab0`, preincrements the local counter at0x3c and writes the assigned Id through its setter. The ID is not serialized and is not a prefab path ID. Loaded active objects and Unity enumeration order determine the mapping. A static component count can bound IDs0..N-1 under a stated local policy; it does not prove which subtype owns each number.

`SendData451100` sends `94#localGUID#Id#!_isActive`, followed by every `data[]` string. The metadata has no derived SendData override. `Generic.Interact4510c0` invokes this send but does not locally apply the new state, so an accepted update must reach its sender as well as other initialized viewers.

The receiver `5d91b0` finds APITPInteractables by matching Id. Only when the Boolean differs does it invoke the matching active/inactive callback with the entire opcode-stripped field array and then store the new Boolean. The `36ea00/36ea20` APITP bridges forward the same arguments; neither copies extensions into `component.data`.

All 44 requested non-game callback bodies were reviewed. None reads packet fields3 or later. Jacuzzi's inactive callback reads **field2**, the state string, and passes it into its local-GUID comparison; moving a GUID into that position would violate the processor's Boolean parser. Hollyridge decoration instead parses and increments its **own** `data[0]`. Incoming extension values do not set that value. A last-Boolean snapshot cannot reproduce the number of past decoration cycles for late joiners. The Hollyridge replacement policy therefore retains every accepted transition and replays them in order after scene initialization, allowing the same native callbacks to advance the local cycle. History is capped at4096 scene events; further changes are rejected explicitly. The snapshot is idempotent per connected session so duplicate scene announcements cannot advance the cycle twice. This is an authored compatibility policy, with no runtime validation yet.

Every successfully parsed active generic baseline in the48 scanned logic prefabs has `_isActive=false`. Nexus has no generic subtype and zero class-resolution errors. The bounded re-audit in `mixed-world-registries.json` explains all495 earlier class errors in Bowling449, TheNebulian21, TheNebulianOpenHouse21 and LeafPark4: every record has a null `m_Script`, script type index−1, zero script/type hashes and exactly32bytes of base MonoBehaviour fields. These are missing-script placeholders, not unresolved external MonoScript references. No recoverable subtype remains hidden in those failures. Excluding a null-script placeholder from typed GenericInteractable enumeration is a source-based inference rather than a runtime observation. Historical parser errors remain in the inventory with the resolution audit attached.

`SceneInventory` accepts only trusted host configuration: object count and exact allowed extension counts, with input bounds. The default factory explicitly classifies all48 inspected modern logic-prefab names. These case-insensitive names are local host configuration identifiers, not recovered commercial server space IDs. Unlisted names remain closed. The JSON retains each scene's evidence, inventory confidence and admission decision.

| Generic count | Enabled scene names |
|---|---|
| 1 | GreekSummerHouse, NebuHouse, NebuHouseOpenHouse, SereneGarden, WoodlandClearing, TheNebulian |
| 2 | WestValleyApartment, WestValleyApartmentOpenHouse, WinterSnowGlobe |
| 3 | TokyoApartment |
| 4 | LeChalet, WhisperingHillsMansion, HollyridgeEstate |
| 6 | LakeApartment |
| 9 | Waterfall |

These15 registries admit only their static active ID range. Hollyridge permits zero or one extension token; the others permit zero. TheNebulian has one active ordinary DayNightBasicCycle, so its baseline ID is0. Bowling, TheNebulianOpenHouse and LeafPark have verified empty active generic baselines; OpenHouse's DayNightBasicCycle GameObject is initially inactive. The null-script audit removes the earlier class-uncertainty closures without inventing any new script behavior.

CampSilverLake has8 ordinary active components and1 deferred Killer launcher. CutteridgeEstate has2 ordinary active components and1 deferred Ghost game, with7 deferred candles initially inactive. SorcerersEyrie has1 ordinary Time component and11 deferred ingredient/potion/recipe components. Count-only admission cannot identify their subtype numbers: every ordinary component shares opcode94's GUID/ID/Boolean shape, and both Sorcerers Time and Potion have zero extension tokens. Their ordinary interactions remain an explicit unresolved requirement despite minigame deferral. A host-audited per-ID allowlist can separate them; the new offline binding validator requires every active component fingerprint and an independent enumeration-evidence artifact, and never attests its supplied order automatically. It does not derive IDs from sorted serialized path IDs. See `mixed-world-registries.md` for the exact design.

Initialize registers IDs without a state query. `SnapshotScene` is a host-triggered replay after the recipient's world initialization. It contains recorded Boolean changes, or Hollyridge's complete accepted history, not a fabricated original-server query response. `HousingFurnishing.SaveAtServer6bdb40` also enumerates placed children and calls Generic.Initialize, incrementing the same counter; repeated registration can change IDs as well as newly placed objects. Neither Initialize5decf0 nor ResetOccupables5df300 resets the generic counter. Such registration history requires an explicit mapping epoch and trusted expansion. Static baseline counts do not establish later IDs.

## Consumables44..47

The HTTP contracts are also in `http-legacy-contracts.json` and the durable replacement implementation is documented in `http-consumables.md`. Both GETs logically send `SessionGUID#PS4ID#tag#tableID`, then shared AES.Encrypt appends `#platformName` before encryption. Coffee and Oktoberfest callers use tableID0.

Price response for coffee/oktoberfest is:

`true#GUID#PS4ID#tag#unused#priceDisplay#priceTypeDisplay#userAmountDisplay#rewardedBool`

Successful grant response is:

`true#GUID#PS4ID#tag#unused#successBool#opaqueTCPValue#giveRewardIndexInt`

Callbacks `4190b0/419ba0` check GUID/tag, parse fields5 and7, and copy field6 verbatim into C2S44/46. They do **not** parse field6 numerically. It can therefore carry the local service's opaque durable receipt. Field7 is `giveRewardIndex`, not evidence of a visible-prop use counter or a wallet balance.

| Direction | Opcode | Opcode-stripped fields |
|---|---|---|
| C2S | 44 | guid, coffee, opaque HTTP field6 |
| C2S | 46 | guid, oktoberfest, opaque HTTP field6 |
| S2C | 44,45 | guid, unread, coffee, Int32 uses |
| S2C | 46 | guid, unread, oktoberfest, Int32 uses |
| S2C | 47 | guid, oktoberfest, Int32 uses |

These are not symmetric echoes. The module replies44/46 to the sender and routes45/47 to other ready viewers, preserving the extra unread token for Coffee45 and omitting it for Oktoberfest47. It rejects client-sent45/47 because no C2S emit path was recovered.

`FoodTruckManager.Set404da0` and `OktoberFestManager.Set4087f0` create the prop if absent and pass the received integer to its initializer. If already present, they reset current uses to the existing maximum and ignore the newly supplied integer. The original server's use count is not shipped. A local deployment must choose a stable, explicit count per tag. Replayed receipts must not generate fresh refills.

The callback API is `Func<Identity,string tag,string opaqueReceipt,int?>`: atomically claim a durable HTTP-issued receipt bound to current session, account, tag and instance/space, then return authoritative positive prop uses. Missing callback, null result or a nonpositive result denies the update. The world module performs no filesystem or database work and never treats a client integer as authorization.

LeafPark's FOODTRUCK manager is active. Its three OktoberFest groups are inactive in the shipped prefab hierarchy. Nexus contains neither. The default scene registry therefore admits coffee in LeafPark only. Explicitly activating another verified manager requires changing the trusted registry as well. Account grants alone do not establish a compatible active scene.

Current visible use counters/removal are not established by retaining the original receipt's maximum. `SnapshotActor` deliberately does not invent consumable snapshots for late joiners.

## Animation layer93 and remaining coverage

`UpdateAnimationLayerProcessor5ec380` consumes `guid#layerName#Int32Weight`, resolves the avatar and sets its Animator layer weight after an integer-to-float conversion (native MOVD/CVTDQ2PS at5ec49b/5ec4a2). No C2S93 emitter was recovered among the direct TCP send callsites. The enum and registered receiver do not justify accepting arbitrary client writes to animation layers. Incoming93 is rejected until an actual emitter or server-generated trigger is proven.

The typed C2S inventory has no additional non-minigame opcode omitted by the current core plus world dispatcher. This is command-surface coverage, not full restoration: paddleboat remote exit depends on the selected server refresh; rapid-boat exit lacks a native report;94 retains explicit closures and does not admit dynamically placed objects;44..47 require durable receipt claims and still lack current-use snapshots;93's original server emission policy remains unknown. The JSON lists these limitations with exact source evidence. No claim of complete networking reconstruction or a playable restored game is made.

The pure implementation exposes the same Identity/Delivery/Rejected and Handle/Disconnect pattern as the minigame state helper. Compilation and offline state checks are owned by the parent; none of this report is a runtime success claim.

## Per-space interaction restoration status

These rows classify this module's interaction scope only. A closed interaction registry does not reject core space loading. No row is a runtime playability claim. All configured registries still require the host's existing avatar/scene readiness checks.

| Shipped scene key | Generic94 range | Boat31 tokens | Consumable tags | Outstanding interaction limit |
|---|---|---|---|---|
| beach | none | 0 | none | rapid exit report missing |
| bluewavehideout | none | 0 | none | rapid exit report missing |
| bowling | none | none | none | verified empty generic baseline;449 null-script placeholders |
| campsilverlake | none | none | none |8 ordinary +1 deferred active component; exact numeric map still required |
| cinema | none | none | none | No extra interaction known in the inspected static baseline |
| cliffapartment | none | none | none | No extra interaction known in the inspected static baseline |
| cube | none | none | none | No extra interaction known in the inspected static baseline |
| cutteridgeestate | none | none | none |2 ordinary +1 deferred active component;7 deferred candles initially inactive; exact numeric map required |
| deadquarters | none | none | none | No extra interaction known in the inspected static baseline |
| dome | none | none | none | No extra interaction known in the inspected static baseline |
| dressingroom | none | none | none | No extra interaction known in the inspected static baseline |
| flyingdevice | none | none | none | No extra interaction known in the inspected static baseline |
| forgottenstation | none | none | none | No extra interaction known in the inspected static baseline |
| ghosttown | none | none | none | No extra interaction known in the inspected static baseline |
| gingerbreadhouse | none | none | none | No extra interaction known in the inspected static baseline |
| greeksummerhouse | 0..0 | none | none | static baseline IDs only |
| greenhouse | none | 0 | none | remote exit uses server refresh |
| hollyridgeestate | 0..3 | none | none | 4096-event history cap; static baseline IDs only |
| home | none | none | none | No extra interaction known in the inspected static baseline |
| lakeapartment | 0..5 | none | none | static baseline IDs only |
| leafpark | none | 0,1,2 | coffee | remote exit uses server refresh;4 null-script placeholders; coffee late-join use state unavailable |
| lechalet | 0..3 | none | none | static baseline IDs only |
| medievalvillage | none | none | none | No extra interaction known in the inspected static baseline |
| mountainhideout | none | none | none | No extra interaction known in the inspected static baseline |
| nebuhouse | 0..0 | none | none | static baseline IDs only |
| nebuhouseopenhouse | 0..0 | none | none | static baseline IDs only |
| nexus | none | none | none | No extra interaction known in the inspected static baseline |
| serenegarden | 0..0 | none | none | static baseline IDs only |
| skl | none | none | none | No extra interaction known in the inspected static baseline |
| sorcererseyrie | none | none | none |1 ordinary +11 deferred active components; exact numeric map still required |
| starcrawlers | none | none | none | No extra interaction known in the inspected static baseline |
| steampunk | none | none | none | No extra interaction known in the inspected static baseline |
| stonelakecastle | none | none | none | No extra interaction known in the inspected static baseline |
| thecrypt | none | none | none | No extra interaction known in the inspected static baseline |
| themoonlightroom | none | none | none | No extra interaction known in the inspected static baseline |
| thenebulian |0..0 | 0 | none |21 null-script placeholders; ordinary Time baseline ID0 admitted; rapid exit report missing |
| thenebulianopenhouse | none | none | none | verified empty active generic baseline;TimeControl inactive;21 null-script placeholders |
| tokyoapartment | 0..2 | none | none | static baseline IDs only |
| tokyoapartmentopenhouse | none | none | none | No extra interaction known in the inspected static baseline |
| waterfall | 0..8 | none | none | static baseline IDs only |
| westvalleyapartment | 0..1 | none | none | static baseline IDs only |
| westvalleyapartmentopenhouse | 0..1 | none | none | static baseline IDs only |
| whisperinghillsmansion | 0..3 | none | none | static baseline IDs only |
| windmillfarmhouse | none | none | none | No extra interaction known in the inspected static baseline |
| wintersnowglobe | 0..1 | none | none | static baseline IDs only |
| woodlandclearing | 0..0 | none | none | static baseline IDs only |
| zerodistrictden | none | none | none | No extra interaction known in the inspected static baseline |
| zerodistrict | none | none | none | No extra interaction known in the inspected static baseline |

Offline test guidance is retained in the JSON: ownership and scene bounds, boat entry/exit and snapshot idempotence, generic sender echo and history replay, receipt denial and asymmetric44..47 fields. Parent owns compilation and pure state tests.

**Native counter correction:** `NebulaInteractor.ctor5df620` initializes both Int32 counters to -1 with one UInt64 write at+0x38. `AddGenericInteractable5deab0` preincrements the counter at+0x3c. The first wire ID is therefore0, and a static N-object registry accepts0..N-1. `Initialize5decf0` does not reset the counter. Placed housing components can register later through `HousingFurnishing.SaveAtServer6bdb40`; static bounds do not authorize those dynamic IDs.
