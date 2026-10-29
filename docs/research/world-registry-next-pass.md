> Historical research: this file records an earlier investigation, not current feature acceptance. The root [PROGRESS report](../PROGRESS.md) is authoritative. Local evidence and extracted game code are intentionally omitted. See [research index](README.md).

# World registry next pass

This is a static audit of the three mixed `GenericInteractable` registries and dynamic housing re-registration. It did not run the game, UI, server, listener, or a live connection.

## Ordering narrowed to runtime InstanceID

The initial path is exact: `OnConnected.MoveNext` at `0x5ea6e0` calls `FindObjectsOfType<GenericInteractable>(false)` through `0x8951e0` and `0x1b8b0f0`, then consumes the returned array from index zero upward without sorting or copying it. Unity's 2021.3 API contract states that `FindObjectsOfType` sorts by runtime InstanceID. The first wire ID is zero because the constructor at `0x5df620` initializes the counter to -1 and `0x451060`/`0x5deab0` preincrements it before assigning the component ID.

This is narrower than “unknown engine order,” but it still does not yield numeric bindings: runtime InstanceIDs are assigned to instantiated objects and are not the serialized component path IDs. Asset-record order, hierarchy order, and the row order below are not substitutes.

## Eleven ordinary actions

All eleven components are enabled, active in the prefab hierarchy, initially false, and send zero extension strings.

| Scene | Class / object | Action text | Component path ID | Raw SHA-256 |
|---|---|---|---:|---|
| CampSilverLake | `JG_ChaletFireplaceInteractable` / `FireplaceControl` | Light Fire / Turn Off | -6645242229727984002 | `0a9f26cf77239c6ebf201811169f9e403484ba3ee54f8c4b78ac0c901cd7124d` |
| CampSilverLake | `JG_CampSilverLake_WeatherInteractable` / `WeatherInteractable` | Rain / Clear | -6218022939141632132 | `3e945e210b0249b216da3ba983acadd766ea5f13bd865c731acc62413011aa92` |
| CampSilverLake | `JG_CampSilverLake_Door` / `Door` | Open / Close | -3373250967629728049 | `314c72e578dd1a14aa185b65f3ee30e1a640b59b0b1a18671031538e9894092e` |
| CampSilverLake | `JG_CampSilverLake_Door` / `Door_Bunkhouse_C` | Open / Close | -954467687283808199 | `28c6453fdc5914ff48fd7be71f64b19c08ee6dcee79e1fe1da3a5d8890057de0` |
| CampSilverLake | `JG_CampSilverLake_Door` / `Door_Bunkhouse_D` | Open / Close | -558418029276450779 | `96bf42ff119ededa9719ed8b68b6078e74755684ca294a2ffb6597c189753521` |
| CampSilverLake | `JG_CampSilverLake_Door` / `Door_Bunkhouse_A` | Open / Close | 60058857031766015 | `a1dee3261d6fee855c86086899ff2bc9101bbfc56441f295c708af9079bfc68c` |
| CampSilverLake | `JG_CampSilverLake_TimeInteractable` / `TimeControl` | Night / Day | 1925558629401797336 | `a7a42202761e335ee22ca4ee37db4c40b96648d580d99c8b9d4ece29f703ca52` |
| CampSilverLake | `JG_CampSilverLake_Door` / `Door_Bunkhouse_B` | Open / Close | 3567107327567097474 | `d2d2c4c5d45a1e121f7436a2f35ad09fdcc0128b72999d361add2515ae6e64f2` |
| CutteridgeEstate | `JG_WeatherInteractable` / `Interactive_Weather` | Rain / Clear | -5786673133409027289 | `51bd1fa2a0f6280d9fac7c34875c597ebba68d8f12cc6fe0ffce041960f05e07` |
| CutteridgeEstate | `JG_DoorInteractable` / `Interactive_FrontDoor` | Open / Close | 7064128812764725915 | `3350072fb42a87a9ec839eb7c7615ac3ccb2af0e13d9b2fec95ff0ebc298650a` |
| SorcerersEyrie | `JG_SorcerersEyrie_TimeInteractable` / `TimeControl` | Day / Night | 7078224909408019429 | `d16264f2dc3ef7fb679904c92b624584e3ac9d9d155892b10926d9dd0573ae5d` |

The complete arrays, not just these ordinary rows, determine IDs:

- CampSilverLake has 9 active members: 8 ordinary plus deferred `KillerGameLauncher`.
- CutteridgeEstate has 3 active members: 2 ordinary plus deferred `Interactive_GhostMinigame`. Seven deferred candles are inactive and excluded.
- SorcerersEyrie has 12 active members: the ordinary time control plus 8 ingredients, 2 recipe controllers, and `Potion_Brewing`.

The smallest missing fact is therefore the runtime InstanceID-to-component binding for every member of the exact 9-, 3-, and 12-member arrays. An ordinary-only observation cannot account for IDs consumed by deferred members.

## Dynamic housing registration

Every `HousingFurnishing.SaveAtServer` call at `0x6bdb40` creates another registration epoch:

1. Find active `HousingAssetGround` components in runtime InstanceID order.
2. For each ground, initialize active `NebulaOccupable` descendants.
3. For the same ground, initialize active `GenericInteractable` descendants.

The newly exported generic wrapper at `0x865a20` passes `false` to `GetComponentsInChildren<T>`. Unity 2021.3 specifies root-first depth-first child traversal and exclusion of inactive descendants. `GenericInteractable.Initialize` has no already-registered guard: it increments the same global counter and overwrites the existing component ID on every save.

The maintained ground placement list is not registration authority; the save path performs a global object scan. The later `HousingAssetFloor` scan does not initialize generic children, and wall/ceiling assets are not dynamically scanned for them in this method. Deregistration and `ResetOccupables` do not reset or decrement the generic counter.

Exact housing IDs consequently require every prior save epoch, the active ground InstanceIDs at each save, each active depth-first child result, object lifecycle history, and the current counter. Item table/name or asset ID cannot distinguish duplicate placed copies.

## Actionable closure

Two bounded closure paths remain:

- Capture each returned array immediately after `0x8951e0` and before the `0x5ea6e0` loop. Record index, runtime InstanceID, scene, class, object name, and stable component fingerprint. Capture each housing ground/child array with a registration epoch as well.
- As explicit preservation policy, patch every compatible client to sort initial components by stable scene hierarchy path plus component slot, and housing instances by persisted placement index with children sorted by prefab hierarchy path plus component slot. Reject stale epoch IDs.

Without one of these, a server-only numeric allowlist cannot safely separate ordinary from deferred mixed-scene IDs or reconstruct session-dependent housing IDs. No guessed mapping was emitted.

Machine-readable evidence, complete hashes, and the explicit boundary are in [world-registry-next-pass.json](world-registry-next-pass.json).
