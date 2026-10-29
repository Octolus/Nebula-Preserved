> Historical research: this file records an earlier investigation, not current feature acceptance. The root [PROGRESS report](../PROGRESS.md) is authoritative. Local evidence and extracted game code are intentionally omitted. See [research index](README.md).

# Gathering branch audit

Static source artifact: `GameAssembly.dll` SHA-256 `c4dd5db599e5e5ce4adf25f09ffe70ad10e0928adf6a2e862176d537026b44ac`.

This audit corrects field semantics using client sender/callback pseudocode and IL2CPP managed metadata. It does not claim runtime observation.

Route inventory: 10 implemented gathering routes; `Get_GatherChristmasGetSpacesCompleted` remains documented but is deferred and is not advertised by `Gathering.ROUTES`.

## Recovered branches

### Send_GatherInitInSpace callback

Indices 4, 5 and 6 are parsed as Int32; index 4 drives count/reward thresholds, index 5 drives completion and SetThumbnails, and index 6 is passed to ShowCoolDown.

Wire suffix following `guid#ps4_id` (and `success` for responses): `type#current_gather#rewards_earned#cooldown_seconds`.

Evidence: `0x3f3cb0`, `work/decompiled/dump.cs`.

### Get_GatherPhaseGame callback

The same values use a different order: index 4 is passed to ShowCoolDown, index 5 is rendered/threshold-tested as the gather count, and index 6 selects the reward stage.

Wire suffix following `guid#ps4_id` (and `success` for responses): `type#cooldown_seconds#current_gather#rewards_earned`.

Evidence: `0x3efa10`, `work/decompiled/dump.cs`.

### Christmas2018 extended response

Each value is parsed as Int32 and stored as a bool. PhaseGame compares the corresponding flag with ManagerInstance.typePsidglobal before showing SpaceCompleted.

Indices 7–11: `isNexus#isLeafPark#isDome#isCube#isBeach`.

Evidence: `0x3f3cb0`, `0x3efa10`, `work/decompiled/dump.cs`.

### Christmas2018 consume request

The sender loads ManagerInstance+0x250; managed metadata names that field psidglobal. It is not an unknown counter.

Wire suffix following `guid#ps4_id` (and `success` for responses): `type#psidglobal`.

Evidence: `0x3f2e90`, `work/decompiled/dump.cs`.

### Gather consume operation

Christmas and Easter item-trigger collisions call Send_GatherConsume after an item is collected. Halloween2018 increments its local round counter and calls the same route when the round completes. The consume callback displays returned index 4 and opens reward collection at observed thresholds. Therefore this route advances collection progress; it does not decrement inventory.

Evidence: `0x68f920`, `0x68fbd0`, `0x68fe80`, `0x6901b0`, `0x3ef680`.

### ConsumeReward response

Index 4 updates the displayed gather count and index 5 is passed to ShowRewardGathered or used to select the reward sprite.

Wire suffix following `guid#ps4_id` (and `success` for responses): `type#current_gather#rewards_earned`.

Evidence: `0x3ef240`.

### Get_GatherChristmasGetSpacesCompleted

The callback compares score against a level threshold array and continues into the Memorion challenge. This is mini-game score validation, not an ordinary spaces-completed counter.

Wire suffix following `guid#ps4_id` (and `success` for responses): `memorion_score#level_index`.

Evidence: `0x3ef0c0`, `work/decompiled/dump.cs`.

## Preservation decisions

- Init and phase replies preserve their distinct observed field order.
- Current gather and rewards earned are separate durable per-account values.
- The five Christmas2018 PSIDs use unique durable rows; repeated scenes are idempotent and any other PSID fails closed.
- Gather consume increments progress, bounded by the explicitly configured local threshold.
- Reward grant, progress reset/increment and claim marker remain in Store.atomic().
- The Memorion score endpoint returns an explicit deferred-gameplay error instead of fabricating a score oracle.

## Remaining evidence boundaries

- The retired service's schedules, reward item definitions and Memorion score-validation policy were not recovered.
- Static client evidence establishes how fields are consumed, not historical production account values.
