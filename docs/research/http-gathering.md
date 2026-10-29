> Historical research: this file records an earlier investigation, not current feature acceptance. The root [PROGRESS report](../PROGRESS.md) is authoritative. Local evidence and extracted game code are intentionally omitted. See [research index](README.md).

# Gathering and ordinary-event HTTP contract

Source artifact: `GameAssembly.dll` SHA-256 `c4dd5db599e5e5ce4adf25f09ffe70ad10e0928adf6a2e862176d537026b44ac`.

This document separates client-observed wire shapes from new preservation policy. It does not assert that retired schedules or rewards were recovered.

Inventory: 11 observed contracts, 10 implemented preservation routes, and 1 deferred mini-game score route.

## Observed routes

| Command | Request fields after command | Response fields consumed | Evidence |
|---|---|---|---|
| `Get_npGather` | `guid # ps4_id # name_game # max_available_items` | `success # guid # ps4_id # state # cooldown_or_current # total_if_active` | sender `0x3f4e70`, callback `0x3f0fe0` |
| `Get_npGatherProcessItem` | `guid # ps4_id # name_game # total # type` | `success # guid # ps4_id # popup_or_name # current # total # np_reward_amount` | sender `0x3f18d0`, callback `0x3f14f0` |
| `Get_GatherStatus` | `guid # ps4_id # type` | `success # guid # ps4_id # available # type # amount` | sender `0x3f4b30`, callback `0x3f0470` |
| `Send_GatherInitInSpace` | `guid # ps4_id # current_space_psid # type` | `success # guid # ps4_id # type # current_gather # rewards_earned # cooldown_seconds # nexus_complete # leaf_park_complete # dome_complete # cube_complete # beach_complete` | sender `0x3f4730`, callback `0x3f3cb0` |
| `Get_GatherPhaseGame` | `guid # ps4_id # type` | `success # guid # ps4_id # type # cooldown_seconds # current_gather # rewards_earned # nexus_complete # leaf_park_complete # dome_complete # cube_complete # beach_complete` | sender `0x3f0130`, callback `0x3efa10` |
| `Get_GatherConsume` | `guid # ps4_id # type # type_dependent_value` | `success # guid # ps4_id # type # current_gather # rewards_earned` | sender `0x3f2e90`, callback `0x3ef680` |
|  | Type variants: four fields; final field is component Int32 counter; four fields; final field is ManagerInstance.psidglobal (Nexus, LeafPark, Dome, Cube, or Beach for the five-space challenge); three fields; type is final field |  |  |
| `Get_GatherConsumeReward` | `guid # ps4_id # type # type_dependent_value` | `success # guid # ps4_id # type # current_gather # rewards_earned` | sender `0x3f2590`, callback `0x3ef240` |
|  | Type variants: four fields; final field is component Int32 counter; three fields; type is final field |  |  |
| `Get_npGatherChristmas` | `guid # ps4_id # current_space_psid # client_state` | `success # guid # ps4_id # state # start_allowed # phase_code # cooldown_seconds # current_gather` | sender `0x3f2190`, callback `0x3f0a50` |
| `Get_GatherChristmasGetSpacesCompleted` | `guid # ps4_id # level # datetime_ticks` | `success # guid # ps4_id # memorion_score # level_index` | sender `0x3f1d60`, callback `0x3ef0c0` |
| `Get_GatherMedievalVillage` | `guid # ps4_id # datetime_ticks` | `success # guid # ps4_id # available_bool # cooldown_seconds_double # amount_int32` | sender `0x690700`, callback `0x690c60` |
| `Send_GatherMedievalVillageConsume` | `guid # ps4_id # datetime_ticks` | `success # guid # ps4_id # result_code_int32 # cooldown_seconds_double # popup_string` | sender `0x691120`, callback `0x690b10` |

The five scene flags at indices 7–11 apply to type 4 (Christmas2018); other event types end after index 6. `Get_GatherChristmasGetSpacesCompleted` is the deferred Memorion score oracle and returns an explicit 501 rather than fabricated results.

## Local preservation policy

Event configuration is explicit and durable. Unconfigured or unknown content fails closed. Progress is account-bound; client counters must agree with durable progress where the shipped sender supplies them. Christmas 2018 scene completion accepts only the five client-observed PSIDs and is unique per account, so repeats are idempotent. Store.atomic uses BEGIN IMMEDIATE to group the progress recheck, entitlement grant and claim marker. Injected failure after a grant rolls everything back, including after reopening SQLite.

Original scheduling and reward definitions remain unknown and are never synthesized as historical fact. Administrators must define any replacement event and reward locally.

## Evidence boundaries

- Original event schedules and reward definitions were not present in the reviewed client artifacts.
- The retired server's Memorion score-validation rules were not present in the reviewed client artifacts; Get_GatherChristmasGetSpacesCompleted therefore fails explicitly as deferred gameplay.
- No claim is made that locally configured event content reproduces retired production data.

Mini-gameplay is deferred: archery, Memorion, and other full mini-game mechanics are outside this contract.
