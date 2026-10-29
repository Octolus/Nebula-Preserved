> Historical research: this file records an earlier investigation, not current feature acceptance. The root [PROGRESS report](../PROGRESS.md) is authoritative. Local evidence and extracted game code are intentionally omitted. See [research index](README.md).

# Bowling TCP contracts and client state

This is a static reconstruction of the shipped client, not retired server source. No client, server, codec round trip or connection test was run. Typed directions and evidence hashes are in `tcp-contracts.json`; the bounded native checks are in `tcp-bowling-native.json`. All field indices exclude the opcode. Every C2S command also receives the AES layer's final platform-name token.

## Panel payload

Server replies 64, 65, 66, 71, 72, 73 and 74 use `actorGuid # laneId # panel`. `panel` is an `EntryData` serialization, not JSON. The native consumers read field2 at RVA `0x547a10` / `0x547eb0` / `0x548740` and call `EntryData.Deserialize` (`0x6a59f0`). The declaration is `BowlingGameManager.BowlingPanelData`, TypeDefIndex 1714:

| Field order in declaration | Type | Native offset |
|---|---|---|
| playerDataPublic | BowlingPlayerDataPublic[] | 0x18 |
| currentTime | Int64 | 0x20 |
| state | LaneState enum / Int32 | 0x28 |
| turnIndex | Int32 | 0x2c |

Each `BowlingPlayerDataPublic` (TypeDefIndex 1715) declares `name` string, `PS4ID` string, `GUID` string, `ready` Boolean and `color` string in that order, at offsets 0x18/0x20/0x28/0x30/0x38. The canonical EntryData audit covers reflection field enumeration and nesting: each primitive/string lexical value has a one-UTF16-unit prefix equal to its UTF16 length plus0x24; an array begins with an ordinary prefixed decimal count token, and each nonnull EntryData element concatenates its fields directly without an element wrapper. A null array emits the ordinary token `nulls` and the decoder skips assignment. Boolean lexical values are `True`/`False`; enum serialization uses names such as `Awaiting`, while Enum.Parse also accepts numeric strings. See `tools/avatar_entry_codec.py` and the avatar EntryData report for the canonical implementation boundary. Declaration order is the static reflection contract, not proof of the original server's implementation. Player arrays retain empty seats: `Get_StartGame` counts players by nonempty `name` and uses array indices as scene seat indices.

`LaneState` is Free0, Rejected1, Awaiting2, Ready3, Playing4. This is different from the lane's local animation/input state enum: Inactive0, InactiveClose1, Waiting2, StartGame3, InitTurn4, WaitTurn5, SelectBallPosition6, SelectBallDirection7, SelectBallStrength8, SelectBallSpin9, BallMoveSendData10, BallMoveAction11, BallMoveWaitServer12, CleanLane13, EndShot14, ChangeTurn15, PlayerPenalty16, ConfirmExit17, Results18.

`tcp-bowling-entry-schema.json` supplies the ordered schema accepted by the canonical `encode_entry_fields` / `decode_entry_fields` helper. It is a declaration-backed schema, not an observed server response. Native array decoding can reuse an existing larger array, and `nulls` skips assignment rather than clearing an existing value; an initially fresh panel is the simplest case.

## Join, readiness, leave and shot sequence

1. C2S64 sends `guid # PS4ID # laneId` (`0x552ea0`). S2C64 marks local `imIn` and applies the panel; S2C72 activates the lane and applies the panel without setting `imIn` (`0x5d9d30`, `0x5d9c70`). `Get_InitializeGame` matches actorGuid to panel `GUID`, identifies the local player by `PS4ID`, seats the corresponding avatar and initializes camera/UI. It processes Free/Awaiting, returns on Rejected/Ready, and closes the local menu when already Playing (`0x547a10`).
2. C2S66 sends `guid # laneId` from the ready UI (`0x5634e0`). S2C66/S2C74 with an existing Awaiting panel first apply the updated panel. If its state is then Ready, the client calls `Get_StartGame` (`0x5da760`, `0x5da2e0`). That consumer counts occupied slots, stands the turnIndex player, seats other occupied players, resets frame index, copies turnIndex, changes panel state to Playing and requests local StartGame (`0x548740`). Opcodes67/75 are declared but have no registered receiver.
3. C2S68 sends `guid # laneId # position # angle # strength # spin`; these four floats use ordinary `Single.ToString(InvariantCulture)` (`0x54b8b0`). S2C68/S2C76 use either `laneId # OK` or `laneId # position # angle # strength # spin`. The `OK` branch marks the sender's shot acknowledged without replaying it. The numeric branch stores the four float values and prepares the remote shot (`0x5473b0`). Which recipients receive acknowledgements versus numeric broadcasts is constrained by those branches but cannot be proven without server source.
4. C2S69 reports settled pin transforms using the separate encoding below. S2C69/S2C77 either acknowledge with `laneId # OK` or supply pin transforms. `Get_StrikePins` sets separate `gotMovePinsFromServer` and `doMovePinsFromServer` flags (`0x548ea0`). It does not read score or next-player state in this packet.
5. C2S70 sends `guid # laneId # nextTurnIndex` (`0x54bff0`), after incrementing/wrapping and skipping empty GUID slots. S2C70/S2C78 only read laneId and request local ChangeTurn15 (`0x5479f0`); they do not consume the candidate nextTurnIndex. Local scoring/turn animation must be joined with the separate state-machine audit to infer any server authority.
6. C2S65 sends `guid # PS4ID # laneId` (`0x54c3d0`). S2C65 marks `imOut`; S2C73 is the remote variant. `Get_LeaveGame` compares the old and new panel, detects removed players, destroys their bowling event component, refreshes the score UI, deactivates the lane for local/last departure, and requests ChangeTurn if the current player departed (`0x547eb0`). This requires an updated panel, not an echo of the request.

## Pin transform wire encoding

`Send_StrikePins` (`0x54c750`) emits:

[Code/listing block omitted from the public research archive.]

Each of the six floats goes through `BinaryConverter.GetString(float)` (`0x4d4260`), **not a decimal formatter**. It calls BitConverter.GetBytes(float), takes bytes0/1 and2/3 as two UTF16 `char` values and constructs a string of exactly two code units. On this little-endian Windows build this is the float's low16 bits followed by high16 bits. `GetFloat(string)` (`0x4d4140`) reads chars0/1, converts them to bytes and reads the resulting four bytes as a float. `GetChars` (`0x4d3ea0`) and the char-array decoder (`0x4d4020`) confirm the same layout.

S2C69/77 transform packets are `laneId # n # pin0[7] # ...`; receiver `0x548ea0` skips every seventh field without reading it. The C2S `guid` and declared length are absent from this receiver layout. Native `0x54d1bb` through `0x54d1db` confirm the C2S seventh field is integer0 converted to string and concatenated; Ghidra omitted a displayed argument in the equivalent pseudocode call.

No escaping of raw UTF16 code units is observed in these helpers. A code unit equal to `#` would collide with the outer split, and the AES layer's UTF8 conversion can replace isolated surrogate code units. These are static format limitations, not measured failures; do not silently replace this encoding with Base64 or decimal floats and call it compatible.

## Synchronization path has shipped inconsistencies

An inactive lane receiving ready66/74 or OneWay shot76/pins77/turn78 caches the entire stripped message in manager field0xe8, stores action74/76/77/78 in field0xe0, then requests C2S71 `guid # laneId`. The inactive leave73 branch requests71 without caching the leave message.

S2C71 is ignored when the existing panel is Playing or there is no cached message. Otherwise it activates the lane, calls `Get_StartGame` with its full panel payload, then calls `BowlingGameManager.SyncrhonizeMessage` with the cached packet and action before clearing the cache (`0x5dafa0`). Two independent mismatches are present:

- The manager replay method (`0x5534b0`) always parses cached field3 as laneId. Native `0x5534d4` is `mov rcx,[rbx+0x38]`, followed by Int32.Parse. Modern shot/pins/turn handlers use field0 and ready handlers use field1. This is confirmed by bounded assembly, not inferred from a decompiler type.
- The coroutine (`0x5618c0`) switches on action minus `0xc8b` (3211), with branches for3211 leave,3212 ready,3214 shot and3215 pins. The modern cached actions74/76/77/78 take the default return branch. No modern action remapping is observed in the reviewed call chain.

These appear to be stale code/layout assumptions in a path retained by the shipped client. Preserve the evidence as a compatibility gap. Server source, an earlier client version or a user-authorized later runtime investigation would be needed to determine the historically active workaround. The current analysis does not claim complete 1:1 networking.
