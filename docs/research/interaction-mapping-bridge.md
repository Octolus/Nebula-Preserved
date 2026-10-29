> Historical research: this file records an earlier investigation, not current feature acceptance. The root [PROGRESS report](../PROGRESS.md) is authoritative. Local evidence and extracted game code are intentionally omitted. See [research index](README.md).

# Interaction mapping bridge: mixed scenes and saved furniture

## Result

A server-only numeric allowlist cannot safely enable the three excluded mixed scenes or persisted furniture interactions. The native IDs are session-local: initial registries follow runtime InstanceID order, while every housing save registers active ground descendants again and overwrites their IDs without resetting the counters.

The smallest safe compatibility bridge is per-client translation through audited semantic keys. A compatible client announces a complete key-to-local-ID map for an authenticated scene/layout epoch; the server stores state by semantic key and rewrites the numeric ID for every recipient. The offline prototype implements this contract and its seven focused tests pass.

## Static mixed-scene manifest

The runtime key must be the authored root-relative Transform sibling-index chain, concrete component class, and GameObject component slot, under exact binary and bundle hashes. Serialized component pathId is useful evidence but is not obtainable from a normal runtime Component. Name-only paths are unsafe: Cutteridge has two active `NebulaSeat` objects both named `Trigger (1)`, at root child indices 2 and 3.

- `CampSilverLake`: 9 active generics: 8 ordinary and the deferred Killer launcher; no occupables. The ordinary keys are Fireplace `4/0/0`, Weather `4/0/1`, five doors `4/0/5/{0..4}`, and Time `4/0/4`, all slot 1. Killer is `4/0/6`, slot 1.
- `CutteridgeEstate`: 3 active generics: Weather at root `12`, FrontDoor at `11`, and deferred Ghost at `15`, all slot 1. Its two ordinary seats are roots `2` and `3`, slot 2. Seven inactive candles do not enter `FindObjectsOfType(false)`.
- `SorcerersEyrie1`: 12 active generics and no occupables. Ordinary Time is `6/1`, slot 1. Deferred entries are PotionControl `6/0`, RecipeControl `6/0/{3,4}`, and eight Ingredient entries `6/0/6/{0..7}`, all slot 1. This is the complete active semantic set.

Deferred minigame objects remain in each complete announced registry because they consume native IDs. Their semantic keys are denied for relay.

## Saved furniture manifest

For an active `HousingAssetGround`, the semantic key is:

`layout digest | persisted ground-array index | item/prefab ID | prefab-relative sibling-index chain | component slot | generic/occupable kind`

The persisted array index distinguishes duplicate copies of the same item. Only active ground descendants registered by `SaveAtServer` are admitted. The bridge does not invent dynamic generic registration for the floor pass, walls, or ceilings.

A placement change or save is an epoch break. Interaction traffic freezes, retained generic/occupancy state is cleared, and clients reload and rebind. Unsaved objects never relay. This conservative reload is necessary because repeated save registration overwrites component IDs and `RemoveOccupable` can alter the dense list without a counter reset.

## Exact wire behavior

- Queue native automatic `8#guid#id` requests until registry-ready. Opcode 1 is not sufficient proof because 8 and 94 may precede it.
- A free opcode-8 query receives `10##recipientLocalId`; an occupied query receives `9#requesterGuid#recipientLocalId#occupantGuid`.
- Accepted opcode 9 is broadcast with each recipient's ID, including the sender. Sender inclusion sets `TargetGUID`, required before native opcode 10 leave can be sent.
- Accepted opcode 10 is likewise broadcast with each recipient's translated ID, including the sender.
- Opcode 94 validates the allowed key and exact extension arity, stores the latest value by semantic key, and relays to same-epoch ready peers including the sender. Native `Interact` does not apply the state locally.
- Snapshots wait for registry-ready, answer queued occupancy queries, then translate retained generic state.

Native seat interaction animates before authoritative acceptance. A denial packet is not proven to undo that local animation reliably. The compatibility server must serialize claims, and force a reload on a true race instead of claiming a recovered rollback behavior.

## Prototype and boundary

The offline prototype is [interaction_mapping_bridge.py](README.md#omitted-local-evidence), with tests in [test_interaction_mapping_bridge.py](README.md#omitted-local-evidence). It proves differing client IDs, sender echo, occupancy envelopes, snapshots, deferred denial, exact registry completeness, epoch rejection, extension arity, and duplicate furniture identity. It is a contract prototype, not a listener and not a game patch.

Production still requires the compatible-client descriptor/ack hook, semantic storage in the server, and trusted prefab-child manifests for placeable ground furniture. No C# or live service was changed in this pass.
