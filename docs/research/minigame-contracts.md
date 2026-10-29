> Historical research: this file records an earlier investigation, not current feature acceptance. The root [PROGRESS report](../PROGRESS.md) is authoritative. Local evidence and extracted game code are intentionally omitted. See [research index](README.md).

# Board, Darts and Pool native TCP contracts

Client field-consumption and emission contracts recovered; original server state parity is unproved.

Static IL2CPP metadata plus focused Ghidra12.1.3 pseudocode; no target execution or network observations. Hashes identify source artifacts, not original C# or REA evidence IDs.

Recovered 34 registered clientbound handlers and 19 emitted request shapes. Source binary SHA256: `c4dd5db599e5e5ce4adf25f09ffe70ad10e0928adf6a2e862176d537026b44ac`.

Indices below exclude the opcode. Requests also acquire the global platform-name trailer; server replies must follow their own layouts. EntryData values use the custom reflection codec, **not JSON**.

## Payloads

### Board

| Direction | Opcode | Fields |
|---|---:|---|
| C2S | 32 | `0` sessionGUID (string); `1` PS4ID (string); `2` tableIndex (int) |
| C2S | 33 | `0` sessionGUID (string); `1` tableIndex (int); `2` selectedRules (BoardGamesManager.GameRules/int) |
| C2S | 34 | `0` sessionGUID (string); `1` myTableID (int) |
| C2S | 35 | `0` sessionGUID (string); `1` tableIndex (int); `2` move (EntryData<BoardGameLogic.Move>) |
| C2S | 36 | `0` sessionGUID (string); `1` tableID (int) |
| C2S | 37 | `0` sessionGUID (string) |
| S2C | 32 | `0` tableIndex (int); `1` tableState (SpaceGameManager.TableState/int); `2` tableData (EntryData<BoardGamesTable.Data>) |
| S2C | 33 | `0` tableIndex (int); `1` unread (opaque); `2` selectedRules (BoardGamesManager.GameRules/Enum.Parse) |
| S2C | 34 | `0` tableIndex (int) |
| S2C | 35 | `0` tableIndex (int); `1` unread (opaque); `2` newMatchState (BoardGamesManager.GameState/Enum.Parse); `3` playerIndex (int) |
| S2C | 36 | `0` departingGUID (string); `1` tableIndex (int) |
| S2C | 37 | `0` unread (opaque); `1..N-1` boardState[0..N-2] (BoardTableSnapshot); `N` unreadLastBoardStateSlot (opaque); `N+1+2*j` seat0GUID[j] (string); `N+2+2*j` seat1GUID[j] (string) |
| S2C | 39 | `0` tableIndex (int); `1` unread (opaque); `2` tableData (EntryData<BoardGamesTable.Data>) |
| S2C | 40 | `0` tableIndex (int); `1` unread (opaque); `2` selectedRules (BoardGamesManager.GameRules/Enum.Parse) |
| S2C | 41 | `0` tableIndex (int) |
| S2C | 42 | `0` departingGUID (string); `1` tableIndex (int) |
| S2C | 43 | `0` tableIndex (int); `1` unread (opaque); `2` newMatchState (BoardGamesManager.GameState/Enum.Parse); `3` playerIndex (int); `4` move (EntryData<BoardGameLogic.Move>) |

### Darts

| Direction | Opcode | Fields |
|---|---:|---|
| C2S | 80 | `0` sessionGUID (string); `1` myTableID (int) |
| C2S | 81 | `0` sessionGUID (string); `1` myTableID (int) |
| C2S | 82 | `0` sessionGUID (string); `1` tableID (int); `2` selectedRules (DartsGameManager.GameRules/int); `3` numberOfPlayers (int) |
| C2S | 84 | `0` sessionGUID (string); `1` tableID (int) |
| C2S | 85 | `0` sessionGUID (string); `1` tableIndex (int); `2` move (EntryData<DartsRules.DartShotData>) |
| C2S | 86 | `0` sessionGUID (string) |
| S2C | 80 | `0` unread (opaque); `1` tableIndex (int); `2` tableState (SpaceGameManager.TableState/Enum.Parse); `3..` tableBlock (DartsTableBlock) |
| S2C | 81 | `0` tableIndex (int); `1` tableState (SpaceGameManager.TableState/Enum.Parse) |
| S2C | 82 | `0` tableIndex (int); `1` numberOfPlayers (int); `2` selectedRules (DartsGameManager.GameRules/Enum.Parse) |
| S2C | 84 | `0` tableIndex (int); `1..` tableBlock (DartsTableBlock) |
| S2C | 85 | `0` unread (opaque); `1` tableIndex (int); `2` move (EntryData<DartsRules.DartShotData>) |
| S2C | 86 | `0` rememberedGUID (string); `1..` tableBlocks (DartsTableBlock[]) |
| S2C | 87 | `0` unread (opaque); `1` tableIndex (int); `2` tableData (EntryData<DartsGameTable.TableData>) |
| S2C | 88 | `0` departingGUID (string); `1` tableIndex (int); `2` tableState (SpaceGameManager.TableState/Enum.Parse) |
| S2C | 89 | `0` tableIndex (int); `1` unread (opaque); `2` selectedRules (DartsGameManager.GameRules/Enum.Parse) |
| S2C | 90 | `0` tableIndex (int); `1..` tableBlock (DartsTableBlock) |
| S2C | 91 | `0` unread (opaque); `1` tableIndex (int); `2` move (EntryData<DartsRules.DartShotData>) |

### Pool

| Direction | Opcode | Fields |
|---|---:|---|
| C2S | 51 | `0` sessionGUID (string); `1` myTableID (int) |
| C2S | 52 | `0` sessionGUID (string); `1` myTableID (int) |
| C2S | 53 | `0` sessionGUID (string); `1` myTableID (int); `2` selectedRules (int); `3` numberOfPlayers (int) |
| C2S | 54 | `0` sessionGUID (string); `1` tableIndex (int); `2` totalplayers (int) |
| C2S | 55 | `0` sessionGUID (string); `1` tableIndex (int); `2` cueAngleX (float/InvariantCulture); `3` cueAngleY (float/InvariantCulture); `4` spinX (float/InvariantCulture); `5` spinY (float/InvariantCulture); `6` force (float/InvariantCulture) |
| C2S | 56 | `0` sessionGUID (string); `1` tableIndex (int); `2` blockWordCount (int); `3` ballCount (int); `4+2*i` ballX[i] (float/InvariantCulture); `5+2*i` ballZ[i] (float/InvariantCulture); `4+2*N+i` pocketed[i] (int/0-or-1); `4+3*N` whiteFirstTouched (int); `5+3*N` whiteLastTouched (int) |
| C2S | 57 | `0` sessionGUID (string); `1` tableIndex (int); `2` whiteX (float/InvariantCulture); `3` whiteZ (float/InvariantCulture) |
| S2C | 51 | `0` unread (opaque); `1` tableIndex (int); `2` tableState (SpaceGameManager.TableState/Enum.Parse); `3` rivalName (string); `4` rulesID (int) |
| S2C | 52 | Payload ignored |
| S2C | 53 | `0` unread (opaque); `1` tableIndex (int); `2` numberOfPlayers (int) |
| S2C | 54 | `0` tableIndex (int); `1` role (string); `2` rivalName (optional string) |
| S2C | 55 | `0` tableIndex (int); `1` ackOrAngleX (literal OK or float/InvariantCulture); `2` cueAngleY (float/InvariantCulture); `3` spinX (float/InvariantCulture); `4` spinY (float/InvariantCulture); `5` force (float/InvariantCulture) |
| S2C | 56 | `0` tableIndex (int); `1` ackOrBallCount (literal OK or int/N); `2+2*i` ballX[i] (float/InvariantCulture); `3+2*i` ballZ[i] (float/InvariantCulture); `2+2*N+i` pocketed[i] (int/equals1); `2+3*N` whiteFirstTouched (int); `3+3*N` whiteLastTouched (int) |
| S2C | 57 | `0` tableIndex (int); `1` ackOrWhiteX (literal OK or float/InvariantCulture); `2` whiteZ (float/InvariantCulture) |
| S2C | 59 | `0` unread (opaque); `1` tableIndex (int) |
| S2C | 60 | `0` tableIndex (int); `1` role (string); `2` rivalName (optional string) |
| S2C | 61 | `0` tableIndex (int); `1` ackOrAngleX (literal OK or float/InvariantCulture); `2` cueAngleY (float/InvariantCulture); `3` spinX (float/InvariantCulture); `4` spinY (float/InvariantCulture); `5` force (float/InvariantCulture) |
| S2C | 62 | `0` tableIndex (int); `1` ackOrBallCount (literal OK or int/N); `2+2*i` ballX[i] (float/InvariantCulture); `3+2*i` ballZ[i] (float/InvariantCulture); `2+2*N+i` pocketed[i] (int/equals1); `2+3*N` whiteFirstTouched (int); `3+3*N` whiteLastTouched (int) |
| S2C | 63 | `0` tableIndex (int); `1` ackOrWhiteX (literal OK or float/InvariantCulture); `2` whiteZ (float/InvariantCulture) |

## Compatibility details

- Board35 reply checks state only; Board43 decodes/applies the move through the input component before checking state. Neither is a direct echo of request35.
- Board37 snapshot starts GUID pairs at `N+1`, but the native board-state loop consumes only state slots1 throughN-1. Preserve the skipped slotN until stronger evidence justifies a change.
- Darts init/start/sync use variable TableBlocks: serialized TableData, decimal player count, then that many serialized Player records. Darts87 instead decodes only TableData.
- Darts82 reply reads player count at field1; Darts89 ignores field1. Both parse selected rules at field2.
- Pool55/56/57 and61/62/63 accept exact `OK` at field1 as acknowledgements. Replay layouts omit request GUID and, for56, the block-word-count M.
- Pool ball positions are X/Z in local table coordinates. Reply56 consumes `N`, `2*N` position floats, `N` pocket flags and two white-ball contact integers.
- Pool start identifies seat0 by literal `playerOne`; any other non-null role text selects seat1.
- Parsing/bounds checks are client constraints, not recovered server-side authorization or validation.

## EntryData DTOs

`BoardGameLogic.Move`: originX: int, originY: int, targetX: int, targetY: int.

`BoardGamesTable.Data`: gameRules: BoardGamesManager.GameRules, userGUIDs: string[], userPS4IDs: string[].

`DartsGameTable.TableData`: gameRules: DartsGameManager.GameRules, gameState: DartsGameManager.GameState, currentTurnIndex: int, numberOfPlayers: int, isActive: bool.

`DartsGameTable.Player`: name: string, PS4ID: string, GUID: string, score: int, dartColor: int, color: string.

`DartsRules.DartShotData`: x: float, y: float, force: float, deflected_x: float, deflected_y: float.

## Nested snapshot/shot effects

Board snapshots prefix a single rules digit to concrete board text. TicTacToe reads lowercase x/o per tile; Chess/Draughts read one character per grid cell, 0 for empty. Chess p/r/n/b/q/k select Pawn/Rook/Knight/Bishop/Queen/King; lowercase is White and uppercase Black, differing from FEN. Draughts r/k select Regular/King; lowercase is White and uppercase Red. Unrecognized TicTacToe characters leave existing state untouched. Chess/Draughts clear old pieces before rebuilding.

Board replay43 dispatches through the input component. TicTacToe uses targetX*3+targetY, ignores origin and selects X/O by player0/1. Chess and Draughts call local origin/destination handlers; Draughts preserves multiple-capture continuation. Original server legal-move and result policies remain unknown.

Darts passive shots decode immediately only in Pointing(4); otherwise they queue. Immediate decode updates local dart X/Y, raycasts the board field and requests Shoting(5). A replay is therefore dependent on local scene/rules state, rather than just assigning a server score.

EntryData arrays prefix an element-count token. Nested EntryData records concatenate fields recursively without element wrappers. Null-array sentinel leaves the existing field unchanged. Consult the shared codec for exact UTF16 token framing; JSON DTO records include ready-to-use ordered schemas for its generic API.

## Evidence and remaining gaps

The JSON includes individual native RVAs/VAs, pseudocode hashes, metadata type hashes, per-message effects and client validation. Enum-only opcodes38,58 and83 have no registered receive handler in the recovered dispatch map.

Pending requested transitive decompiles: none.

- Seat ownership/authentication, GUID binding, reconnect/disconnect cleanup, timeouts and recipient visibility rules.
- Exact table transition guards, simultaneous join/start arbitration, first-player selection and when request/reply versus OneWay variants are sent.
- Board legal-move adjudication, turn progression, checkmate/draw rules and authoritative result/XP accounting. Client rules/input code may duplicate some rules but cannot prove the removed server's policy.
- Darts score adjudication, shot validation, deterministic deflection/physics agreement, round/turn authority and result/XP accounting.
- Pool rules variants, authoritative foul/win adjudication, ball-contact/physics trust, sequence/ack timing, replay recipient selection and result/XP accounting.
- Initialized asset grid dimensions and authoritative legal coordinate bounds are not recovered from snapshot parsers; concrete input replay calls into deeper local gameplay methods.
- Request35/85 send caller-provided strings; their EntryData move types are established on the receiving side. Full outbound gameplay construction and all concrete local rule algorithms are separate from the sender's field contract.

Wire compatibility does not establish original server rules, recipient policies or complete state parity. No client/server was launched or contacted to create this artifact.
