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

## HTTP minigame servlets (2026-10-31)

Thirteen HTTP-only minigame routes recovered from the shipped client (GameAssembly SHA-256 `c4dd5db5…44ac`) and implemented in `backend/minigames.py` (12 routes) and `backend/rewards.py` (`checkRewardGameServlet`). Every field below comes from the sender and its callback in native pseudocode (Ghidra 12.1.3 focused decompilation; private export `work/evidence/ghidra/minigame-http-v1`), with callers found by direct `call`/`jmp` scans of the `il2cpp` section. Shipped scene bounds come from a read-only UnityPy type-tree read of the named bundles. Nothing was launched or contacted.

Requests are the usual AES `?data=` payload: fields joined with `#`, then the platform trailer. `OnSend` for Castle (0x447a80), BlueWave (0x447530), FootRace (0x577120) and XP (0x448270) requires field 0 `true` and field 1 = local SessionGUID before the callback; ArcheryCupid (0x53ad70) and the NETGCloudSpace sender additionally require field 2 = PS4ID. A body containing `Error` takes the error path. Replies therefore start `true#GUID#PS4ID` wherever field 2 is not consumed as data.

### Contracts

| Route | Sender (RVA) | Request | Response consumer (RVA) | Reply |
|---|---|---|---|---|
| AddScoreArcheryServlet | `CastleNETGCloud.Send_AddScoreArchery` 0x432f70, from `ArcheryGameManager.ApplyEndGame` 0x52afe0 / `SendScoreToServer` 0x52bd40 only when score > best | `GUID#PS4ID#score` (Int32) | `Get_Send_AddScoreArchery` = shared no-op 0x35a740 | `true#GUID#PS4ID` |
| GetBestScoreArcheryServlet | `Get_BestScoreArchery` 0x432770 (from `Initialize` 0x52b770, `UpdateBestScoreFromServer` 0x52c260) | `GUID#PS4ID` | `Get_Get_BestScoreArchery` 0x432c30: ≥4 fields, Int32.Parse field 3 → `ArcheryGameManager.bestScore`; -1 logs "Received unvalid value" | `true#GUID#PS4ID#best` (0 = none) |
| GetLeaderboardArcheryServlet | `Get_ArcheryLeaderboard` 0x4325d0 (trigger 0x52cd30, input, exit) | `GUID#PS4ID` | `Get_Get_ArcheryLeaderboard` 0x432a30 → `ArcheryGameManager.SetLeaderboardInfo` 0x52be80 (= `ArcheryLeaderboard.SetLeaderboardContent` 0x52cf70): fields 2..n each split on `!`, needs ≥2 parts, rank = index-1; `CreateEntry` 0x52ce60 Int32.Parse(score).ToString("0000") | `true#GUID#name!score#…` (`true#GUID` = empty) |
| AddScoreBoatMiniGameServlet | `BlueWaveHideoutNETGCloud.Send_AddScoreBoatMiniGame` 0x431ab0 from `BoatMiniGame.EndBoatContest` 0x543ac0 only when best == 0 or time < best | `GUID#PS4ID#ticks` (Int64 DateTime ticks, lower wins) | `Get_Send_AddScoreBoatMiniGame` 0x431850: field 2 != "" activates `RankingPosition`, field 3 is its text | `true#GUID#PS4ID#rank` |
| GetBestScoreBoatMiniGameServlet | `Get_BestScoreBoatMiniGame` 0x430f80 from `InitializeBoatContest` 0x544600 | `GUID#PS4ID` | `Get_Get_BestScoreBoatMiniGame` 0x4313e0: Int64.Parse field 3 → `bestScore`, `FormatTime` 0x544110 (≤ 1 s renders empty); -1 = error | `true#GUID#PS4ID#ticks` (0 = none) |
| GetLeaderboardBoatMiniGameServlet | `Get_BoatMiniGameLeaderboard` 0x431120 from `BoatMiniGameLeaderboardTrigger` 0x543460 | `GUID#PS4ID` | `Get_Get_BoatMiniGameLeaderboard` 0x431650 → `BoatMiniGame.SetLeaderboardInfo` 0x545170: rows only when field 2 != ""; `!` rows; `CreateEntry` 0x542fd0 Int64.Parse + FormatTime | `true#GUID#name!ticks#…` |
| GetCooldownServlet | `FootRaceManager.Send_InitializeGame` 0x56fc30 (virtual) | `GUID#PS4ID#FootRace` (`SpaceGameManager.Type` 7 name) | `Get_InitializeGame` 0x56e8a0: ≥4 fields; Int64.Parse field 3 < 0 opens the race menu, ≥ 0 starts `CoolDownTimer` 0x575cc0 with DateTime ticks (÷1e7 → h/m/s) | `true#GUID#PS4ID#-1` or `…#remainingTicks` |
| SetCooldownServlet | `Send_FinishGame` 0x56f610 (tail-called by `FootRaceRoute.NextCheckPoint` 0x570e80 at the last checkpoint); time-out variant in `FootRaceManager.Update` 0x570460 | finish `GUID#PS4ID#FootRace#routeIndex#true`; time-out `GUID#PS4ID#FootRace#false` | `Get_FinishGame` 0x56dee0: needs ≥5 fields; Boolean field 3 (false = "Time up! Try again later"), Boolean field 4 (true activates `panelRewards[routeIndex]`); success path then sends `AddXP(FootRace)` | `true#GUID#PS4ID#completed#rewardShown` |
| AddXPServlet | `XPNET.Send_AddXP` 0x44a1f0; callers include Archery 0x52afe0 (6), FootRace 0x56dee0 (8), Bowling, Darts, Pool, MiniGolf, Pinball, Memorion, NeonBike, AirRacing | `GUID#PS4ID#TypeXPGame` (numeric 0–12) | `Get_GetAddXP` 0x449fe0: ≥3 fields, Int32.Parse field 2; > 0 shows popup `"+ " + n + " NP"` | `true#GUID#np` |
| checkRewardGameServlet | `checkRewardGameCoroutine` 0x416a20 via `checkRewardGame` 0x3eead0 (stage 0: `prepareRewardPanel` 0x418860, `RewardGeneric/RewardSwords.OnSubmit`, `JG_Ghost_Minigame`, `JG_CampSilverLake_Killer_Launcher`) and `checkRewardFullGame` 0x3ee980 (ChronoRace stages) | `GUID#PS4ID#typeGame#stage` | same coroutine: true/GUID, then per typeGame Boolean.Parse field 2; false shows the reward popup (ChronoRace/Halloween also suppress at stage 1); unknown names finish | `true#GUID#alreadyOwned` |
| Get_GatherArcheryCupid | `ArcheryCupidManager.CheckIsAvailable` 0x529340 (tail of `ArcheryCupidTrigger.Interact` 0x52ac70, which sets `isGameLaunched`) | `GUID#PS4ID#DateTime.Now.Ticks` | `Get_ArcheryCupidIsActive` 0x529990: Boolean field 3 (false hides the trigger), Double field 4 cooldown seconds, Int32 field 5 fires, Int32 field 6 hearts; hearts 4 → rewarded panel, cooldown > 0 → `ShowCoolDown` 0x52a3f0, else spawns `fires` items via `SpawnFire` 0x52a7d0 (bounds-checked `aSpawnPoints[i]`) | `true#GUID#PS4ID#active#cooldownSec#fires#hearts` |
| Send_ArcheryCupidConsume | `SendConsumeArcheryCupidItem` 0x529dc0 from `ArcheryCupidItem.ConsumeItem` 0x528f90 / `ArcheryCupidArrow.OnCollisionEnter` 0x527c80 | `GUID#PS4ID#DateTime.Now.Ticks` | `Get_ArcheryCupidConsume` 0x529780: Int32 field 3 fires left, Int32 field 4 hearts, Double field 5 cooldown; only fires == 0 and cooldown > 0 stop the round, light `hearts[0..n-1]` (bounds-checked), show rewarded panel at 4 and the cooldown | `true#GUID#PS4ID#fires#hearts#cooldownSec` |
| XSpacesGamesType0Servlet | `NETGCloudSpace.Send_SKLMiniGameSuccess` 0x3edcd0 from `SKLGoalGameManager.ExitGame(true)` 0x5bdcb0 | `GUID#PS4ID#0` | `Get_SKLMiniGameSuccess` 0x3e9550 → `UISKLMenu.ShowResult` 0x5c1bd0 → `UISKLResult.ShowResult` 0x5c26b0: Int32 field 4 reward step, Boolean field 5 isInserted, Double field 6 cooldown in DateTime ticks (÷1e7, `ShowCoolDown` 0x5c23b0); `SetResult` 0x5c1fe0 fills reward images by step and at ≥ 6 shows the last one and hides the cooldown | `true#GUID#PS4ID#0#step#inserted#cooldownTicks` |

### Shipped scene bounds

| Bundle (SHA-256 prefix) | Component | Value used |
|---|---|---|
| `s/medievalvillagelogicprefab` (`47ce99a8`) | `ArcheryCupidManager.aSpawnPoints` = 6, `hearts` = 4 | fires per round 1..6, hearts 0..4 |
| `s/leafparklogicprefab` (`ff7c9b49`) | `FootRaceManager.gameRoutes` = 3, `panelRewards` = 3 (route times 60/70/40 s) | routeIndex 0..2 |
| `s/nexuslogicprefab` (`7a555fdd`), `s/skllogicprefab` (`3b6c0ff0`) | `UISKLResult.aImgRewards` = `aSpriteRewards` = 10 | reward step 0..6 |
| `s/stonelakecastlelogicprefab` (`fa32c45b`), `s/bluewavehideoutlogicprefab` (`edb0c2ae`) | leaderboards instantiate entries dynamically; no row limit | top 10 is local policy |

### Preservation choices

The original server rules for these are not in the client. Each choice is the smallest behavior the client accepts, and every grant is off until an operator configures it, matching the existing reward and gathering policies.

- **Leaderboards:** top 10 by best score (Archery highest, Boat lowest time), ties by earliest achievement. Usernames containing `#` or `!` cannot be framed and are skipped. Boat `rank` = 1 + players with a strictly better time.
- **Score bounds:** Archery 1..100000 (the client's reward threshold constant is 600). Boat 10,000,001..864,000,000,000 ticks (just over the 1 s `FormatTime` floor, up to 24 h). Best scores never get worse.
- **Cooldowns:** FootRace and SKL use `footrace_cooldown_seconds` and `skl_cooldown_seconds`, default 0. Cupid uses `cupid_cooldown_seconds`, minimum 1 because the client only ends a round when cooldown > 0, and default 86400 (the client has an unused `ShowCoolDownNextDay`). A FootRace time-out also starts the cooldown.
- **FootRace result:** field 3 echoes the client's completion flag. The client times the run, and the server cannot see the start.
- **XP:** NP per `TypeXPGame` comes from `xp_np_<0..12>`, default 0, so the reply is `0` and no popup shows. Awards credit `shop_wallets.np`, are recorded in `minigame_xp_events`, and go to `management_wallet_ledger` (actor `system:minigame-xp`, reason `AddXPServlet <Type>`) when the management schema exists.
- **Cupid:** off by default (`cupid_active` 0), so the trigger is hidden. When active, a round has `cupid_fires` (default 6) items. The last item adds a heart and starts the cooldown, and 4 hearts ends the event for that account.
- **SKL:** each counted success advances the step 1..6 at most once per cooldown. Later successes reply with `isInserted=false`.
- **Optional item grants** go through `RewardService` claims (`local_reward_definitions` / `local_reward_claims`, so entitlements show in the admin panel), configured with `rewards_admin.py`:
  - `checkRewardGameServlet` keyed `<typeGame>:<stage>`. `typeGame` is one of the 12 `Utils.RewardType` names or ChronoRace; stage is 0..9999.
  - `SetCooldownServlet` keyed by route `0`..`2`. It sets field 4 true only on the fresh claim.
  - `XSpacesGamesType0Servlet` key `0`, claimed when step 6 is reached.
  - `Send_ArcheryCupidConsume` key `4`, claimed at the fourth heart.

  Unconfigured keys grant nothing. `checkRewardGameServlet` then answers `true` (already owned), the same suppression policy as `CheckOwnGenericReward`.
- **Validation:** each request needs an existing session whose PS4ID and platform trailer match. Mutating routes also need the account's current session. Numbers must be canonical decimals within the bounds above. Policy is set with `backend/minigame_admin.py`. State lives in `minigame_settings`, `minigame_best_scores`, `minigame_footrace`, `minigame_skl_progress`, `minigame_cupid_progress` and `minigame_xp_events`.

Tests: `backend/tests/test_minigames.py` (wire shapes, persistence across reopen, validation, cooldown timing, optional grants claimed once, NP ledger, CLI).

## Scene-server relay policy (2026-10-31)

Board, Darts, Pool and Bowling TCP are implemented in
`mirror-server/UnityProject/Assets/Preservation/NebulaMinigameState.cs`
(source-fixed, awaiting Linux rebuild). The server acts as seat authority and
relay: the clients run physics, scoring and turn rotation for Darts, Pool and
Bowling, so the server acknowledges the actor and forwards the actor's values.
Board results are the exception: the client never computes them. Evidence RVAs
come from the shipped client; the private pseudocode export is not in the
repository. Lines marked [I] are inferences, not recovered server behavior.

### Who receives what

| Game | Request | Actor reply | Other recipients |
|---|---|---|---|
| Board | 32 join | `32#t#state#Data` (0 Free / 2 Awaiting / 1 Full / 4 Playing) | 39 to every other peer |
| Board | 33 select (owner) | `33#t##Rules` | 40 to the rival seat |
| Board | 34 start (either seat) | `34#t` | 41 to the rival seat |
| Board | 35 move | `35#t##GameState#mover` | 43 (with the move) to the rival seat only |
| Board | 36 leave / 37 sync | `36#guid#t` / `37##slots..#guid pairs` | 42 to the rival, 39 to others |
| Darts | 80 join / 82 select / 81 leave | unchanged lobby replies | 87, 89, 88 as before |
| Darts | 84 start (either seat) | `84#t#TableBlock` (isActive=True) | 90 to the rival seat, 87 to others |
| Darts | 85 shot | `85##t#DartShotData` echo | 91 to the rival seat |
| Pool | 51 join | `51##t#Free/Awaiting/Full/Playing#rivalName#rules` | none (no init OneWay exists) |
| Pool | 53 select (owner) | `53##t#players` | none |
| Pool | 54 start (either seat) | `54#t#playerOne/playerTwo[#rivalName]` | 60 to the other seat |
| Pool | 55 / 56 / 57 | `55#t#OK` / `56#t#OK` / `57#t#OK` | 61 / 62 (`t#N#xz..#pocket..#first#last`) / 63 to the rival |
| Pool | 52 leave | `52#t` (ignored) | 59 `##t` to the rival |
| Bowling | 64 join | `64#guid#lane#Panel` (Awaiting, or Playing when busy) | 72 to every other peer |
| Bowling | 66 ready | `66#guid#lane#Panel` (Ready when all seated are ready) | 74 to every other peer |
| Bowling | 68 shot | `68#lane#OK` | 76 `lane#position#angle#strength#spin` to every other peer |
| Bowling | 69 pins | `69#lane#OK` | 77 `lane#n#7 tokens per pin` to every other peer |
| Bowling | 70 turn | `70#lane` | 78 to every other peer |
| Bowling | 71 sync | `71#requester#lane#Panel` | none |
| Bowling | 65 leave | `65#guid#lane#Panel` | 73 to every other peer |

### Evidence for the relay choices

- **Either seat may start.** `SpaceGameManager.OnClickStartGame` and
  `OnClickJoinMatch` share 0x575790, which calls the virtual `Send_StartGame`
  (slot 26). The joining player's "Join match" button therefore sends start.
- **Darts echo.** `DartsRules.FixedUpdate` 0x569e10 sends the shot from
  Pointing(4) and does not advance itself. Only `Get_MakeMove` 0x55b950 ->
  `MakePassiveMove` 0x56c670 moves a table in Pointing(4) to Shoting(5), so the
  shooter needs its own shot back (85) and the rival gets 91. The shot already
  contains the shooter's random deflection, so both sides replay the same hit.
- **Pool acknowledgements.** The receivers 0x599a50, 0x5999e0 and 0x599c20
  treat an exact `OK` as "server accepted my move" and numeric fields as a
  rival replay. Replays omit the request GUID; 62 also omits the block-word
  count M. `PoolGameTable.Get_StartGame` 0x59bf20 compares only `playerOne`.
- **Bowling acknowledgements and turn.** `BowlingGameLane.Update` 0x54dcf0
  keeps the shooter in BallMoveSendData(10) until `gotMoveShotFromServer`
  (set by 68 `OK`). EndShot(14) in `InitState` 0x549110 sends 70 and the lane
  only enters ChangeTurn(15) from `Get_ChangeTurn` 0x5479f0, so the actor also
  receives 70. OneWay variants go to every other peer because inactive lanes
  cache 74/76/77/78 and request Sync71 (0x5da760, 0x5d98b0, 0x5dabe0,
  0x5db460).
- **Bowling panel.** `Get_InitializeGame` 0x547a10 applies Free/Awaiting,
  shows the busy menu for Playing and ignores Rejected/Ready. Ready66/74 is
  applied only over an Awaiting panel, so joins always report Awaiting.
  `Get_StartGame` 0x548740 uses array indices as seat indices; the server keeps
  four slots (four `UIBowlingMainEntry` rows) and never compacts.
  `currentTime` is an absolute `CurrentTime.Millis` ready deadline
  (`UIBowlingMain.InflatePanel` 0x562760, `Update` 0x563920, which auto-sends
  ready at zero). Its length is unrecovered, so it is sent as 0 and the
  countdown does not run (documented divergence). `color` has no recovered
  reader (the ball material follows the turn index) and is sent empty.
- **Board results.** `CheckNewMatchState` 0x53cbe0 parses the server state;
  P1Turn/P2Turn only show the Chess "Check" popup, everything else shows the
  results. No client method detects checkmate, stalemate or a blocked Draughts
  side, so the server keeps the board:
  - Chess (player0 = White, lowercase, rows 0-1): `ChessBoard.CreateAllPieces`
    0x52e3d0, pawn rules 0x535040/0x535230, en passant and Queen promotion in
    `ChessLogic.MakeMove` 0x533e80, castling availability 0x530a70 (king and
    rook unmoved, path empty, not in or through check). After each move the
    server computes whether the next side has a legal move: none while in
    check -> mover wins; none otherwise -> Draw [I].
  - Draughts (player0 = Red, uppercase, rows 0-2, moves +x):
    `CreateAllPieces` 0x536e70, Regular directions from the constructor
    0x54ffb0 (forward only), King four diagonals 0x54fa40, single-step moves,
    captures 0x54fce0/0x54f7c0, mandatory capture in `ActivatePlayerPieces`
    0x538550, promotion on x0/x7 (0x54f510). A jump whose landed piece can
    capture again keeps the turn (`SelectDestination` 0x5395c0 sets
    multipleMove); the next request must continue from that square. A side
    without any move loses [I: no draw rule exists in the client].
  - Moves are applied leniently (own origin, bounds, target not own; Draughts
    geometry). The client already restricts input to its own legal moves.

### Remaining gaps

- Bowling ready countdown (`currentTime`), see above.
- 79 SyncPositionOneWay has no recovered trigger and is not sent.
- 43 and 91 are not sent to spectators. Their replay needs an initialized
  input/rules object on the spectator side that the server cannot verify [I].
- Darts and Pool turn order is not enforced server-side (clients rotate turns
  locally after fouls/extra shots); only seated players of a started match can
  relay.
- Scene counts (shipped logic prefabs): StoneLakeCastle board 8; Bowling pool 9
  (tables 6-8 unreachable: inactive parents), bowling 12, darts 3 (the `DARTS`
  object is inactive, so darts is unreachable as shipped). Contract:
  `NebulaCoreReadiness.SceneTables`, wired through `tools/instance_supervisor.py`
  and checked by backend `allocation.MINIGAME_SCENE_TABLES`.
- Result/XP accounting for these games is client-side HTTP (`AddXPServlet`).

Tests: `mirror-server/tests/minigame-contracts` compiles the real
`NebulaMinigameState.cs` and checks 66 payload contracts (lobby, start roles,
acks, relays, Chess mate/castling/en passant/promotion, Draughts capture,
Bowling panel, disconnect cleanup). No Unity runtime, listener or game was run.

## Full-game lobby, leaderboards and Memorion (2026-10-31)

Fourteen routes recovered from the shipped client (GameAssembly SHA-256 `c4dd5db5…44ac`) and implemented in `backend/fullgame.py`. Sources: Ghidra 12.1.3 focused pseudocode (existing export plus private `work/evidence/ghidra/fullgame-lobby-v1` and `-v2`), Il2CppDumper metadata (field order, enum values, `ScriptMetadata` TypeInfo usage) and a read-only UnityPy type-tree read of `s/leafparklogicprefab`, `s/nexuslogicprefab` and `s/bowlinglogicprefab`. Nothing was launched or contacted.

Only `KartGameNETGCloud` and `MiniGolfNETGCloud` derive from `FullGameNETGCloud`, so the nine FullGame routes carry `FullGameManager.gameType` 0 (MiniGolf) or 8 (KartRace) as a decimal. `FullGameNETGCloud.OnSend` (0x4edf40) requests `HTTP_ADDRESS/<command>?data=…`, sends bodies containing `Error` and replies whose field 0 is not `true` or whose field 1 is not SessionGUID to the error callback, and otherwise passes the whole `#` split to the parser. The error callbacks retry `MAX_TRIES` (5) times and then reopen the main menu. ChronoRace, Pinball and Memorion use the legacy `NETGCloudSpace` coroutines, which check only `isNetworkError`. `FullGameManager.Type`: MiniGolf 0, ChronoRace 1, Pinball 2, KartRace 8, Memorion 9.

### Contracts

| Route | Sender (RVA) | Request | Response consumer (RVA) | Reply |
|---|---|---|---|---|
| GetActiveStagesServlet | `Send_GetActiveStages` 0x4e9300 (main menu Solo, `UIFullGameMainOption.OnClick` 0x4f4f60) | `GUID#PS4ID#type` | base 0x4e77e0 / Kart 0x500080: ≥5 fields, Int32 field 4 → `UIFullGameStages.InitPanel` 0x50a630 (0 is treated as 1; stage *i* enabled when *i* < n) | `true#GUID#PS4ID#type#3` |
| AddStatisticsServlet | `Send_AddStatistics` 0x4e89e0 from `MiniGolfManager.<SetHoleStatistic>d__30` 0x523d20 after hole index 17 of a solo round | `GUID#PS4ID#0#EntryData(InfoAddStatistic{int[] hits, int[] seconds, int totalSecs, int totalHits, int stage})` | MiniGolf 0x513de0: ≥8 fields; Boolean field 4 shows the record marker, field 5 hits text, Int32 field 6 → `FormatStringTime` 0x4e6a70, field 7 rank text. Kart 0x4ffcf0 (≥10 fields) is dead code: `KartGameNETGCloud.InfoAddStatistic` has no `ScriptMetadata` TypeInfo usage, so it is never constructed | `true#GUID#PS4ID#0#newBest#totalHits#totalSecs#rank` |
| GetFullGameLeaderboardServlet | `Send_GetLeaderboard` 0x4e9d00 (main menu option 2 sends arguments `1`) | `GUID#PS4ID#type#stage#True/False` | MiniGolf 0x514710 / Kart 0x500690: ≥7 fields; field 4 → `txtStage`, Int32 field 6 count, entries from field 7: MiniGolf `{string name, int hits, string time}` (8-character time loses its first character), Kart `{string name, int kart, string time}` (kart indexes a sprite array) | `true#GUID#PS4ID#type#stage#flag#count#entry…` |
| GetLastScoreServlet | `Send_GetLastScore` 0x4e99b0 (main menu option 3) | `GUID#PS4ID#type` | MiniGolf 0x514140 / Kart 0x500210: ≥5 fields, field 4 is MiniGolf `InfoLastScore{int[] hits, int totalHits, int stage, int rank, int bestHits, string totalTime}` or Kart `{int stage, int rank, string totalTime}`; stage indexes the per-stage par arrays (1-based) | `true#GUID#PS4ID#type#entry`, or an error when there is no result |
| GetInviteFriendList | `Send_GetInviteFriendList` 0x4e9650 | `GUID#PS4ID#type` | 0x4e7b30: ≥4 fields, field 3 is `FriendListEntries{string[] names, int[] stages, string[] guids}`; count = names.Length; zero shows "Your friend list is empty..."; stages colour three stars and gate `SetIsSelectable` 0x4f1780 | `true#GUID#PS4ID#entry` |
| GetOpenGamesServlet | `Send_GetOpenGames` 0x4ea240 | `GUID#PS4ID#type` | 0x4e83c0: ≥4 fields, Int32 field 3 count, `OpenGameEntry` from field 4; zero leaves "No open games found" | `true#GUID#PS4ID#0` |
| CreateGameServlet | `Send_CreateGame` 0x4e8e00 from `UiMenuKartCreatePanel.OnClickCreate` 0x50d5a0 / `UiMinigolfCreatePanel.OnClickCreate` 0x525750 | `GUID#PS4ID#type#totalPlayers(byte)#EntryData(OpenGameEntry)` | 0x4e7320: ≥5 fields, Byte field 3 → `InstantiateOpenGame(n)`, deserialize field 4; `port == -1` hides the lobby and reopens the create panel; otherwise `Disconnector.Clean` → `<Get_CreateGame>b__0` 0x4eee90 stores the entry in `FullGameNETInfo` and loads `<gameName>MultiPlayer` (same as `FullGameManager.LaunchMultiScene` 0x4e5c70) | `true#GUID#PS4ID#n#entry` with port `-1` |
| AddToPoolFullGameServlet | `<AddToPoolFullGame>d__32` 0x4ec1c0 from `UIFullGameOpenGamesEntry.OnClick` 0x4f5f20 | `GUID#PS4ID#type#id_game` | same coroutine: ≥4 fields, Boolean field 3 → `<OnClick>b__6_0` 0x4f6170 (false: "Game is full"; true: start `CheckIsFirstToJoin` polling) | `true#GUID#PS4ID#false` |
| CheckIsAvailableToJoinFullGameServlet | `<CheckIsFirstToJoinFullGame>d__31` 0x4ecd80 polled by `<CheckIsFirstToJoin>d__7` 0x4ed610 | `GUID#PS4ID#type#id_game` | same coroutine: Int32 field 3 (fewer than 4 fields or not `true` → 2) → lambda 0x4eeec0: 0 keep waiting, 1 disconnect and launch, 2 refresh the open-game list | `true#GUID#PS4ID#2` |
| GetLeaderboardServlet | `<send_getLeaderboardCoroutine>d__30` 0x401860 from `UIFullGameLeaderboardSpaces.OnTriggerEnter` 0x4f35d0 (stages 1..contents.Length) | `GUID#PS4ID#TypeName#stage` for MiniGolf, ChronoRace, Pinball, KartRace, Memorion; other types send empty plaintext | `Send_GetLeaderboardProcess` 0x3eb040: whole body split by `#`, every row split by `!` with ≥2 parts (MiniGolf 3), no header, count or empty skip. ChronoRace/Kart parse milliseconds as Single ÷ 1000; rank = row index + 1. A row with fewer parts throws after the board is cleared and before the loading circle is hidden | `name!value#…` (MiniGolf `name!hits!HH:mm:ss`) |
| SetLeaderboardServlet | `<send_addStatisticsLeaderBoardCoroutine>d__33` 0x401100; Kart results `UiKartRaceResults.ShowResultsOnePlayer` 0x50bf00 also call it with type 8 | ChronoRace only: `GUID#PS4ID#ChronoRace#ms#stage`; every other type sends empty plaintext (`#Platform` on the wire) | body never read | `true#GUID#PS4ID`; empty request `true#` |
| MemorionServlet | `UIMemorionGame.SendScore` 0x5ac040 (LeafPark arcade) and `GatherUIMemorionGame.SendScore` 0x691e30 (Christmas 2018) | `GUID#PS4ID#level#DateTime` | `UIMemorionGame.OnSend` 0x5a9100 (true + GUID), then 0x5aba40 / 0x691c30: Int32 field 3 level, Int32 field 4 best → `UIMemorionScore.SetScore` 0x5acfa0. The arcade then sends `AddXP(9)`; the Gather variant sends `Get_GatherChristmasGetSpacesCompleted(level)` | `true#GUID#PS4ID#level#best` |
| Get_BRAINMEMORION | `NETGcloudNPGather.Send_TriggerBRAINMEMORION` 0x3f5260 | `GUID#PS4ID#DateTime` | 0x3f08c0 (NPGather `OnSend` 0x3f5fa0: true + GUID): Int32 field 3: -1 `ShowNoMemorionChallenge`, 1 `MemorionChallengeCompletedShow`, 0 opens the challenge | `true#GUID#PS4ID#state` |
| Get_GatherChristmasGetSpacesCompleted | 0x3f1d60 from `GatherUIMemorionGame.Get_SendScore` 0x691c30 | `GUID#PS4ID#level#DateTime` | 0x3ef0c0: Int32 field 3 score, Int32 field 4 index into `GatherChristmas2018.aRewardsID`; score < threshold (unless `ISTESTING`) shows retry/exit, otherwise `Send_GatherConsume(4)` | `true#GUID#PS4ID#level#spacesCompleted` |

`GetIinitInfosNeeded` field 3 is `PS4Info.isMemorionActive` (0x608b20); `MemorionTrigger.Start` 0x595c90 activates the LeafPark arcade only when it is true. It is now `true`.

### EntryData field order (public fields, declaration order)

- `OpenGameEntry`: `string id_game, string ip, int port, byte stage, byte isPublic, byte totalPlayers, byte state, FullGameManager.Type type, EntryData extra, OpenGamePlayer[] players`. `OpenGamePlayer`: `string guid, string name, string color, int connectionId, PlayerState state` (Ready 0, Connected 1, Waiting 2, Empty 3). Kart adds `KartOpenGameExtra{byte numLaps}` and `KartOpenGamePlayer.selectedId`.
- The Kart create panel fills `players[i]` with the selected invitee GUID/name (or `0`), state 2 for invitees and 3 for empty slots, `isPublic`, `stage` and `type`.
- `FriendListEntries`: `string[] names, int[] stages, string[] guids`.

### Shipped data used

| Bundle | Component | Value |
|---|---|---|
| `s/leafparklogicprefab` | `GatherChristmas2018.aRewardsID` | `[5, 7, 9, 11, 15, 25]` (six Memorion thresholds, index = spaces completed) |
| `s/leafparklogicprefab` | `UIFullGameLeaderboardSpaces` typeGame 8 / 9 | KartRace 3 stages, Memorion 1 stage; `KartGameTrigger.fullGameID` `kartrace_01` |
| `s/nexuslogicprefab` | `UIFullGameLeaderboardSpaces` typeGame 1, `AirRacingTrigger` "Chrono Racing" | ChronoRace 3 stages |
| `s/bowlinglogicprefab` | `UIFullGameLeaderboardSpaces` typeGame 2 | Pinball 2 stages |
| `minigolfstage_1..3` | MiniGolf stage scenes | MiniGolf 3 stages, 18 holes (`SetHoleStatistic` ends at hole index 0x11) |

### Preservation choices

- **Stages:** `GetActiveStages` unlocks every shipped stage. The original unlock rule is not in the client, and a completion-gated rule could never unlock Kart stages 2 and 3, because the Kart client never reports a result. The invite list reports the same stage count for every friend.
- **Scores:** only MiniGolf (AddStatistics), ChronoRace (SetLeaderboard) and Memorion (MemorionServlet) reach the server. Kart's results go to an empty `SetLeaderboard` plaintext, and Pinball's statistics travel over the scene server (`MANAGER_MSGS.SpaceGames.Pinball`), so those boards stay empty. Personal bests: MiniGolf fewest hits, then seconds; ChronoRace lowest milliseconds; Memorion highest level. Ties go to the earliest result.
- **Validation:** MiniGolf hits and seconds arrays must have the same length (at most 18), values 0..1000 and 0..86400, and totals equal to the array sums, as `SetHoleStatistic` computes them. Stages are bounded by the shipped catalogs. ChronoRace takes 1..86,400,000 ms and Memorion levels 0..100000. Writes need the account's current session and a matching platform trailer.
- **New record flag:** `true` when the run improves the player's personal best (the first run counts). Rank is the position of that best on its stage board.
- **Boards:** top 10 rows. Usernames containing `#` or `!` cannot be framed and are skipped. The space consumer has no empty representation, so an empty board answers an error (404). The board is cleared, but the client's loading circle keeps spinning, which is the shipped client's own behaviour on any empty or failed reply. Full-game boards may be empty (`count 0`).
- **Last score:** the latest MiniGolf result; `rank` and `bestHits` describe the player's best on that stage. No result answers an error, so the client retries and returns to the menu.
- **Invite list:** accepted friends with a live session (presence plus current GUID), because the GUID is the invite address. Offline friends are omitted.
- **Multiplayer:** a created game must point at a full-game host (`ip:port`) that runs the `<Game>MultiPlayer` scene. No such host exists in this stack. `CreateGame` echoes the client's entry with `port = -1`, the client's own not-created branch. `GetOpenGames` answers 0, `AddToPool` false and `CheckIsAvailableToJoin` 2. The lobby keeps no state.
- **Christmas 2018 Memorion:** `Get_BRAINMEMORION` answers -1 unless gathering type 4 is configured active and the session's allocation is one of its five scenes (Nexus, LeafPark, Dome, Cube, Beach). It answers 1 when that scene is already completed and 0 otherwise. `GetSpacesCompleted` requires the active event and the exact level last recorded by `MemorionServlet`, and returns the number of completed type-4 scenes (0..5), which indexes `aRewardsID`. The consume itself stays in `Get_GatherConsume`. The server never invents a score.
- **No grants:** these routes grant nothing. NP for Memorion comes from the client's own `AddXP(9)` (`backend/minigames.py`).

State: `fullgame_best_scores`, `fullgame_last_results`. Tests: `backend/tests/test_fullgame.py`.

### Required scene-server change for full-game invites (not implemented)

Invites need a full-game host first: without one no game is created, so nothing is ever sent. Specification for when a host exists (the C# is owned elsewhere and was not edited):

1. **Delivery, S2C19 type 2.** `NotificationProcessor.Process` 0x5df8a0 needs 5 fields: `19#<inviterUsername>#<inviterPlatform 0/1>#2#<arguments>#<DateTime.UtcNow.Ticks>`. It stores field 3 as `NotificationData.arguments`. `ManagerInstance.Send_AcceptFullGameNotification` 0x439ad0 splits `arguments` at `!`: the tail is a `FullGameManager.Type` name passed to `InstatiateOpenGame`, and the head is the `OpenGameEntry` EntryData stream. It then disconnects the scene and loads the game scene (0x4499b0); `<LoadMulti>d__175` 0x449250 calls `LaunchMultiScene`. So `arguments` = `<OpenGameEntry EntryData with host ip/port>!<TypeName>`, with no `#` and no `!` inside the entry. Changes: `NebulaNotificationInbox.Validate` (`NebulaNotificationInbox.cs` ~172-183) must accept `notification_type == 2` with that grammar, and `notification_outbox.notification_type` must allow 2 in `backend/notifications.py`. The backend would enqueue one type-2 row per invited GUID when `CreateGameServlet` creates a private game on a real host.
2. **Acceptance, C2S26 type 2.** `26#<GUID>#<inviterName>#2#<inviterPlatform>`. `NebulaSocialState.Accept` (~line 239) rejects type 2 today. It should become an inbox acknowledgement only, like types 3 and 4: no relation change and no reply, because there is no S2C26. The client launches the multiplayer scene whatever the server answers.
3. **Decline, C2S95.** `95#<GUID>#<requesterName>#<requesterPlatform>#10` from `NotificationsManager.DismissNotification` 0x47fa70 / `DeclineAll` 0x47f160 (12 = SpaceGame_Declined). `DeclineNotification` (NIS ~1587) should, for type 10, retire the matching type-2 inbox row and send the inviter `19#<declinerName>#<declinerPlatform>#10##<ticks>` (`FullGame_Declined`), local or through the cross-instance relay that `Notification` already uses.
