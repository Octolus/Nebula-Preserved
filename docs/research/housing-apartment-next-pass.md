> Historical research: this file records an earlier investigation, not current feature acceptance. The root [PROGRESS report](../PROGRESS.md) is authoritative. Local evidence and extracted game code are intentionally omitted. See [research index](README.md).

# Housing and apartment next pass

The safest first furnished personal space is the exact shipped `Home` scene for the existing local native account selected from controlled state. Use the explicitly authored local instance ID `linux-native-home`, with both `psidglobal` and navigator key set to `Home`. Its scene is `s/home` → `Assets/Scenes/Spaces/Home.unity`; `s/homelogicprefab` proves 6 wall slots, 6 ceiling slots, and 4 floor areas. The current world-interaction evidence gives Home a closed, empty generic registry, so this trial does not depend on unresolved dynamic interaction IDs.

The minimal verified grant set is:

| Channel | Exact ID | Native table | Local label |
|---|---|---|---|
| Ground | `A044fFy8Xtm2U2J1DuRolDt63P431gI8` | `HOUSING_CHAIR` | Serene Chair |
| Wall | `ACnfTMSTgKIQ0tgMY06575CJjCNE8M71` | `HOUSING_WALLHANGING` | Great Wave Canvas |
| Ceiling | `BVS0Nb01WuRs5xd2iFAuI1uQBprDwG1q` | `HOUSING_LIGHT` | Ceiling Fan |

Each is directly verified as the matching `HousingAssetGround`, `HousingAssetWall`, or `HousingAssetCeiling` class, selectable, and cost 1 after the native zero-size promotion. Together they consume 3 of the recovered 200-space budget. The readable labels are explicit preservation labels derived from shipped object names, not a claim about original shop metadata.

The executable HTTP flow is present: personal-space enumeration, explicit owner binding, allocation and fresh descriptor polling, ten-array layout load, category inventory, native two-part sparse save, durable reload, deletion through shorter arrays, and read-only visitor loads. Saves enforce the account grant, native placement class, 200-space cap, and authored wall/ceiling slot bounds.

This pass closes two trust defects. Bindings now accept only case-exact shipped Unity scenes for all 31 navigator keys (`SorcerersEyrie` intentionally maps to authored scene `SorcerersEyrie1`). The backend can atomically publish `instance-housing.json`, containing only exact instance/scene/owner/navigator bindings whose owner is an existing local account, without changing database state. A desired-GUID visit now requires the current, freshly present owner session; a visitor cannot become a transitive invitation target, and a stale owner session cannot authorize entry.

The owner/visitor furnishing gate is now exact. `HousingManager.Initialize` (`0x6c4080`) enters edit mode only when the local player is inside the authored house collider and the remote-player dictionary count is zero; otherwise it starts the one-user popup path. Thus an owner alone can furnish, while owner plus visitor cannot, and a visitor sees the owner as a remote player and is blocked. `LoadAssetsFromServer` remains unconditional, so visitors can view the layout. `SetUIMode` adds no owner-GUID check, and `SaveAssetsAtServer` has no client owner check, making the backend's existing owner-only write authorization mandatory.

HousingReadPreset field 4 is stored natively as `guidOwner` and later drives owner-disconnect handling. The service now accepts the owning requester's own current GUID when allocated to this exact binding even if the first read precedes presence publication. For a visitor, it requires the unique current owner GUID both allocated and fresh-present in this specific instance, never simply the account's newest unrelated session GUID.

There is no recovered `floor` behavior entitlement: all 28 `HOUSING_FLOORING` catalog entries are `HousingAssetGround`. Original prices, receipts, and commercial labels remain intentionally unclaimed, and the multipart wire has no revision ID with which to reconstruct cross-save interleaving.

`LakeApartment` is also a fully verified scene with 8 wall slots, 3 ceiling slots, and 5 floor areas, but it is a second-step target: its static generic registry contains IDs 0–5 whose subtype mapping is not yet proven.

Live furnishing is intentionally narrower than durable save/load. No furniture-layout TCP message or automatic visitor refresh was recovered. A visitor arriving after the owner entered edit mode does not stop that editor and may load the last durable snapshot; after a save, visitors must reload or re-enter before the updated layout can be claimed visible. See `housing-live-sync-next-pass.json` for the native join, popup, and deactivation evidence.
