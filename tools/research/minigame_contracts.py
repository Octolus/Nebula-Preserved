"""Build evidence-linked Board, Darts and Pool TCP contracts; static files only.

Does not import, launch, connect to, or patch the game or a server. Run from the
workspace root. Payload indices exclude the opcode and generic C2S platform tail.
"""
from __future__ import annotations

from _research_paths import workspace, output_root, game_path

import hashlib
import json
import re
from pathlib import Path

ROOT = workspace()
OUT = ROOT / "results/protocol"
FUN = ROOT / "work/evidence/ghidra/functions"
METHODS = json.loads((ROOT / "work/decompiled/script.json").read_text(encoding="utf-8"))["ScriptMethod"]
DUMP = (ROOT / "work/decompiled/dump.cs").read_text(encoding="utf-8")
REGISTRATIONS = json.loads((OUT / "tcp-dispatch-map.json").read_text())["registrations"]
OPCODES = {x["value"]: x["name"] for x in json.loads((OUT / "type-tcp-opcodes.json").read_text())}
NAMES: dict[int, list[str]] = {}
for method in METHODS:
    NAMES.setdefault(method["Address"], []).append(method["Name"])


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def field(index, name, kind="string", note=""):
    return {"index": index, "name": name, "type": kind, **({"note": note} if note else {})}


F = field
contracts = []


def add(game, direction, opcodes, fields, evidence, effects, validation=(), notes=()):
    for opcode in opcodes:
        reg = next((x for x in REGISTRATIONS if x["opcode"] == opcode), None)
        sources = list(dict.fromkeys([*evidence, *([reg["process_rva"]] if reg and direction == "S2C" else [])]))
        contracts.append({
            "game": game, "direction": direction, "opcode": opcode,
            "enum_name": OPCODES.get(opcode),
            "fields": fields, "evidence_rvas": sources,
            "client_effects": effects, "client_validation": list(validation),
            "notes": list(notes),
            "original_server_policy": "unknown: request ownership, allowed transitions, recipient set, concurrency and adjudication cannot be proved from a client parser",
        })


TABLE_BOUNDS = "Table index must address an initialized local table array; out-of-range/missing fields normally throw rather than return a structured protocol error."
ENUM = "Enum.Parse is case-sensitive and accepts enum names or numeric text; parsing alone does not prove that undefined numeric values are rejected."
ENTRY = "EntryData reflection codec, not JSON. Field order/schema below is recovered from IL2CPP metadata; use the shared avatar EntryData codec reconstruction."

# BoardGamesManager requests. The two manager table-id fields are intentionally
# kept distinct: tableID+0x40 and myTableID+0x44.
add("board", "C2S", [32], [F(0,"sessionGUID"),F(1,"PS4ID"),F(2,"tableIndex","int")], ["0x53f370"], "Disable interaction colliders, activate local table/menu, request seat.")
add("board", "C2S", [33], [F(0,"sessionGUID"),F(1,"tableIndex","int","GetCurrentTableForUser(sessionGUID)"),F(2,"selectedRules","BoardGamesManager.GameRules/int")], ["0x53fd20"], "Request selected board rules.")
add("board", "C2S", [34], [F(0,"sessionGUID"),F(1,"myTableID","int")], ["0x5400c0"], "Request match start.", notes=["The managed totalplayers argument is not serialized by this implementation."])
add("board", "C2S", [35], [F(0,"sessionGUID"),F(1,"tableIndex","int","GetCurrentTableForUser(sessionGUID)"),F(2,"move","EntryData<BoardGameLogic.Move>")], ["0x53f9e0"], "Submit serialized move string.", notes=[ENTRY])
add("board", "C2S", [36], [F(0,"sessionGUID"),F(1,"tableID","int")], ["0x53f730"], "Request leave.")
add("board", "C2S", [37], [F(0,"sessionGUID")], ["0x540370","0x551d50"], "Request board-table snapshot; a delayed coroutine invokes this sender after initialization.")
add("board", "S2C", [32], [F(0,"tableIndex","int"),F(1,"tableState","SpaceGameManager.TableState/int"),F(2,"tableData","EntryData<BoardGamesTable.Data>","Consumed in Free/Awaiting branches")], ["0x53d360"], "Store tableID/tableState. Free: initialPlayer=true, reset table, decode data, mark local player, select rules and seat avatar; manager becomes Awaiting. Awaiting: initialPlayer=false, decode data, join/rival UI, seat avatar. Busy states display their branch UI.", [TABLE_BOUNDS,"Decoded GUID/PS4ID arrays are indexed as two seats by subsequent UI/seat logic; preserve both slots, using empty strings for empty seats."], [ENTRY,"State is Int32.Parse here, unlike several Enum.Parse handlers."])
add("board", "S2C", [39], [F(0,"tableIndex","int"),F(1,"unread","opaque"),F(2,"tableData","EntryData<BoardGamesTable.Data>")], ["0x53d2e0"], "Deserialize into existing tableData; no local-seat initialization.", [TABLE_BOUNDS], [ENTRY])
add("board", "S2C", [33], [F(0,"tableIndex","int"),F(1,"unread","opaque"),F(2,"selectedRules","BoardGamesManager.GameRules/Enum.Parse")], ["0x53e700"], "When manager is Awaiting(2), store gameRules and display selected-game instructions.", [TABLE_BOUNDS,ENUM])
add("board", "S2C", [40], [F(0,"tableIndex","int"),F(1,"unread","opaque"),F(2,"selectedRules","BoardGamesManager.GameRules/Enum.Parse")], ["0x53e590"], "When manager is Awaiting(2), store tableData.gameRules.", [TABLE_BOUNDS,ENUM])
add("board", "S2C", [34,41], [F(0,"tableIndex","int")], ["0x53ea60"], "If manager Awaiting, reset/activate table, select existing tableData.gameRules, activate game camera and menus. Local initialPlayer flag selects Your turn/Control versus Rival turn/Waiting UI.", [TABLE_BOUNDS], ["No player-count or match-state field is parsed."])
add("board", "S2C", [36,42], [F(0,"departingGUID"),F(1,"tableIndex","int")], ["0x53dc00"], "Clear matching GUID and PS4ID seats; local leave restores avatar controls/transform; rival leave updates table/UI and initial-player state.", [TABLE_BOUNDS])
add("board", "S2C", [35], [F(0,"tableIndex","int"),F(1,"unread","opaque"),F(2,"newMatchState","BoardGamesManager.GameState/Enum.Parse"),F(3,"playerIndex","int")], ["0x5d96d0","0x53cbe0"], "Call CheckNewMatchState without applying a move. For local table, P1Turn/P2Turn may display Chess Check; all other parsed states go to ShowMatchResults.", [TABLE_BOUNDS,ENUM], ["This is not the C2S35 layout and has no serialized move field."])
add("board", "S2C", [43], [F(0,"tableIndex","int"),F(1,"unread","opaque"),F(2,"newMatchState","BoardGamesManager.GameState/Enum.Parse"),F(3,"playerIndex","int"),F(4,"move","EntryData<BoardGameLogic.Move>")], ["0x53e430","0x53cbe0","0x5327b0","0x538ff0","0x550a10"], "Allocate/decode Move, call BoardGamesBoard.input.ApplyMove(playerIndex,move) (input virtual slot10), then CheckNewMatchState. Concrete input replay effects appear in board_move_replay below.", [TABLE_BOUNDS,ENUM], [ENTRY,"ApplyMove is dispatched through board.input+0x38, not a direct BoardGameLogic.MakeMove call."])
add("board", "S2C", [37], [F(0,"unread","opaque"),F("1..N-1","boardState[0..N-2]","BoardTableSnapshot","N=local table count; native loop stops at i<N"),F("N","unreadLastBoardStateSlot","opaque","This slot is skipped by the observed loop"),F("N+1+2*j","seat0GUID[j]","string","j=0..N-1"),F("N+2+2*j","seat1GUID[j]","string","j=0..N-1")], ["0x53ecf0","0x541310","0x540f00"], "Decode board states for tables0..N-2, then consume GUID pairs from N+1 onward; resolve avatars from Memory and place them at seats.", [TABLE_BOUNDS,"GUID pair loop continues to payload end; odd or excessive pairs can cause bounds failure."], ["Candidate full snapshot has 1+3*N fields; server's exact canonical snapshot construction remains unobserved.","Preserve the skipped slot N: silently correcting this apparent off-by-one changes the client's GUID offsets.","BoardTableSnapshot begins with one decimal rules character; rules>0 dispatches remainder to concrete board.DeserializeTable."])

# Darts requests and replies.
add("darts", "C2S", [80], [F(0,"sessionGUID"),F(1,"myTableID","int")], ["0x55c5e0"], "Request interaction/seat.")
add("darts", "C2S", [81], [F(0,"sessionGUID"),F(1,"myTableID","int")], ["0x55cb90"], "Request leave.")
add("darts", "C2S", [82], [F(0,"sessionGUID"),F(1,"tableID","int"),F(2,"selectedRules","DartsGameManager.GameRules/int"),F(3,"numberOfPlayers","int")], ["0x55d240"], "Request rules and player count.")
add("darts", "C2S", [84], [F(0,"sessionGUID"),F(1,"tableID","int")], ["0x55d730"], "Request start.", notes=["The managed totalplayers argument is not serialized."])
add("darts", "C2S", [85], [F(0,"sessionGUID"),F(1,"tableIndex","int","GetCurrentTableForUser(sessionGUID); logs and returns -1 if no seat"),F(2,"move","EntryData<DartsRules.DartShotData>")], ["0x55ce40"], "Send caller-provided serialized move.", notes=[ENTRY])
add("darts", "C2S", [86], [F(0,"sessionGUID")], ["0x55d9f0","0x561e90"], "Request snapshot; initialization schedules a delayed invocation.")
DARTS_BLOCK = "DartsTableBlock = EntryData<TableData>, playerCount:int, EntryData<Player>[playerCount]. Fields consumed are 2+playerCount. TableData.numberOfPlayers and separate playerCount are distinct wire values."
add("darts", "S2C", [80], [F(0,"unread","opaque"),F(1,"tableIndex","int"),F(2,"tableState","SpaceGameManager.TableState/Enum.Parse"),F("3..","tableBlock","DartsTableBlock","Only Free/Awaiting branches decode")], ["0x55a1d0","0x55e1b0"], "Store tableID/state; require interacting table. Free sets initialPlayer/localPlayerIndex0 and rule menu; Awaiting sets initialPlayer=false/localPlayerIndex1 and join/rival UI. Decode player/table data in these branches.", [TABLE_BOUNDS,ENUM,"Player count must fit existing players[] (constructor allocates two entries); all referenced block fields required."], [ENTRY,DARTS_BLOCK])
add("darts", "S2C", [87], [F(0,"unread","opaque"),F(1,"tableIndex","int"),F(2,"tableData","EntryData<DartsGameTable.TableData>")], ["0x55a150"], "Deserialize tableData only; this is not the full TableBlock used by Init/Start/Sync.", [TABLE_BOUNDS], [ENTRY])
add("darts", "S2C", [82], [F(0,"tableIndex","int"),F(1,"numberOfPlayers","int"),F(2,"selectedRules","DartsGameManager.GameRules/Enum.Parse")], ["0x55bbd0","0x55e470"], "Store base playerCount and tableData.numberOfPlayers, instantiate selected rules and display instructions.", [TABLE_BOUNDS,ENUM])
add("darts", "S2C", [89], [F(0,"tableIndex","int"),F(1,"unread","opaque"),F(2,"selectedRules","DartsGameManager.GameRules/Enum.Parse")], ["0x55ba60"], "When manager Awaiting(2), set rules; field1 is not parsed as player count.", [TABLE_BOUNDS,ENUM])
add("darts", "S2C", [84,90], [F(0,"tableIndex","int"),F("1..","tableBlock","DartsTableBlock")], ["0x55bed0","0x55e1b0","0x55e5c0"], "Decode TableBlock then Get_StartGame. Start uses existing rules/table state, initializes rules, positions local avatar/camera, hides other users and sets tableState=Playing(4).", [TABLE_BOUNDS,"Player count must fit allocated players[] and complete block."], [ENTRY,DARTS_BLOCK,"DartsGameTable.Get_StartGame has no additional payload field reads."])
add("darts", "S2C", [85,91], [F(0,"unread","opaque"),F(1,"tableIndex","int"),F(2,"move","EntryData<DartsRules.DartShotData>")], ["0x55b950","0x56c670"], "If rulesScript exists, call MakePassiveMove. In rules state Pointing(4), deserialize shot, set dart local X/Y while preserving Z, raycast from dart position/forward to resolve DartboardField/target marker, request next state Shoting(5). In other states queue the raw shot string. Rival-active UI timer is adjusted separately.", [TABLE_BOUNDS,"MakePassiveMove relies on initialized shot/dart/table objects and uses Unity raycast results; it is not a server score parser."], [ENTRY,"No OK acknowledgement sentinel or server score field is checked by this manager."])
add("darts", "S2C", [81], [F(0,"tableIndex","int"),F(1,"tableState","SpaceGameManager.TableState/Enum.Parse")], ["0x55b1e0","0x55ee30"], "Set manager tableState; remove manager's remembered GUID/PS4ID from selected table; restore local avatar or update rival/rules state as applicable.", [TABLE_BOUNDS,ENUM], ["Departure identity is not in this reply; remembered manager.GUID/PS4ID is used."])
add("darts", "S2C", [88], [F(0,"departingGUID"),F(1,"tableIndex","int"),F(2,"tableState","SpaceGameManager.TableState/Enum.Parse")], ["0x55aa60","0x55ee30"], "Set manager state; remove supplied departingGUID with manager's remembered PS4ID; local/rival branches restore controls or signal rival gone and award local game-related XP.", [TABLE_BOUNDS,ENUM])
add("darts", "S2C", [86], [F(0,"rememberedGUID"),F("1..","tableBlocks","DartsTableBlock[]","Sequential local table order; no table index/count prefix")], ["0x55bff0","0x55e1b0","0x55ea00"], "Remember field0 GUID; deserialize each table block advancing by playerCount+2. Active nonempty tables set rules and InitRules.", [TABLE_BOUNDS,"No extra trailing field: payload-end drives the next-table loop.","Each player count must fit allocated array; number of blocks must fit local tables."], [ENTRY,DARTS_BLOCK])

# Pool requests are coroutine/table methods, not inferred symmetric replies.
add("pool", "C2S", [51], [F(0,"sessionGUID"),F(1,"myTableID","int")], ["0x5a98c0"], "After one coroutine yield, activate table/menu and request initialization.")
add("pool", "C2S", [52], [F(0,"sessionGUID"),F(1,"myTableID","int")], ["0x5a9af0"], "After one coroutine yield, request leave.")
add("pool", "C2S", [53], [F(0,"sessionGUID"),F(1,"myTableID","int"),F(2,"selectedRules","int"),F(3,"numberOfPlayers","int","(selectedRules != 0)+1")], ["0x5a9e70"], "Set rules locally before sending. Rules0 chooses one player; other values choose two.")
add("pool", "C2S", [54], [F(0,"sessionGUID"),F(1,"tableIndex","int"),F(2,"totalplayers","int")], ["0x5aa3c0","0x59f180"], "Forward after coroutine yield; record player count and busy flag.")
add("pool", "C2S", [55], [F(0,"sessionGUID"),F(1,"tableIndex","int"),F(2,"cueAngleX","float/InvariantCulture"),F(3,"cueAngleY","float/InvariantCulture"),F(4,"spinX","float/InvariantCulture"),F(5,"spinY","float/InvariantCulture"),F(6,"force","float/InvariantCulture")], ["0x59a850","0x59e9c0"], "Submit cue shot parameters.")
add("pool", "C2S", [56], [F(0,"sessionGUID"),F(1,"tableIndex","int"),F(2,"blockWordCount","int","M=3*(N+1), counts fields starting at N"),F(3,"ballCount","int","N=rulesScript.balls.Length"),F("4+2*i","ballX[i]","float/InvariantCulture","i=0..N-1, localPosition.x"),F("5+2*i","ballZ[i]","float/InvariantCulture","localPosition.z, not Vector3.y"),F("4+2*N+i","pocketed[i]","int/0-or-1"),F("4+3*N","whiteFirstTouched","int"),F("5+3*N","whiteLastTouched","int")], ["0x59a810","0x59ddc0"], "Report local physics result including white-ball contact identifiers.", notes=["M is not present in the peer S2C payload. Full request has 6+3*N fields before platform tail."])
add("pool", "C2S", [57], [F(0,"sessionGUID"),F(1,"tableIndex","int"),F(2,"whiteX","float/InvariantCulture"),F(3,"whiteZ","float/InvariantCulture")], ["0x59a8a0","0x59ed60"], "Report white-ball relocation using local position X/Z.")
add("pool", "S2C", [51], [F(0,"unread","opaque"),F(1,"tableIndex","int"),F(2,"tableState","SpaceGameManager.TableState/Enum.Parse"),F(3,"rivalName","string","Only Awaiting branch"),F(4,"rulesID","int","Only Awaiting branch")], ["0x5995f0"], "Store myTableID and require table interaction. Free branch opens rule selection if local state Awaiting/Inactive; Awaiting decodes rival/rules, sets two players and join menu; Full/Playing show busy UI; Ready returns.", [TABLE_BOUNDS,ENUM], ["Only branches that read rivalName/rulesID require those final two fields."])
add("pool", "S2C", [52], [], ["0x5457f0"], "Virtual DeactivateTable call; reply payload is ignored by this body.")
add("pool", "S2C", [53], [F(0,"unread","opaque"),F(1,"tableIndex","int"),F(2,"numberOfPlayers","int")], ["0x599eb0","0x59be10"], "Use previously selected rules; initialize rule/ball state arrays and solo/multiplayer UI.", [TABLE_BOUNDS], ["Field2 is player count, not rulesID. Rules came from local selection or Init Awaiting branch."])
add("pool", "S2C", [54,60], [F(0,"tableIndex","int"),F(1,"role","string","Literal playerOne selects index0; every other non-null string selects index1"),F(2,"rivalName","optional string")], ["0x59a180","0x59bf20","0x59c050"], "Only if table currentState Awaiting(1), set localPlayerIndex and optional rival name, then InitState(StartGame2).", [TABLE_BOUNDS,"Role must be non-null; only playerOne is explicitly compared."])
add("pool", "S2C", [59], [F(0,"unread","opaque"),F(1,"tableIndex","int")], ["0x599da0"], "RivalGone: ignore Inactive/Awaiting/finished states; otherwise show rival-gone UI for local table and reset. Wrapper clears busy flag and conditionally local XP flag.", [TABLE_BOUNDS])
add("pool", "S2C", [55,61], [F(0,"tableIndex","int"),F(1,"ackOrAngleX","literal OK | float/InvariantCulture"),F(2,"cueAngleY","float/InvariantCulture","Replay branch only"),F(3,"spinX","float/InvariantCulture","Replay branch only"),F(4,"spinY","float/InvariantCulture","Replay branch only"),F(5,"force","float/InvariantCulture","Replay branch only")], ["0x599a50","0x59bb40"], "OK: doMoveShotFromServer=false, gotMoveShotFromServer=true. Replay: store five shot floats, doMoveShot=true, gotMoveShot=true.", [TABLE_BOUNDS,"ACK minimum2 fields; replay minimum6. String comparison is exact OK. Float parsing does not add range/finite checks."], ["Opcode55 and61 share receive parser; recipient policy is not proved by names."])
add("pool", "S2C", [56,62], [F(0,"tableIndex","int"),F(1,"ackOrBallCount","literal OK | int/N"),F("2+2*i","ballX[i]","float/InvariantCulture","Replay i=0..N-1"),F("3+2*i","ballZ[i]","float/InvariantCulture"),F("2+2*N+i","pocketed[i]","int/equals1"),F("2+3*N","whiteFirstTouched","int"),F("3+3*N","whiteLastTouched","int")], ["0x5999e0","0x59b8f0","0x59b540"], "OK acknowledges without replay; otherwise fill existing net position/pocket arrays and white contact IDs. Set gotMoveBall=true and doMoveBall=(not OK). Apply_MoveBalls later consumes arrays.", [TABLE_BOUNDS,"ACK minimum2 fields; replay minimum4+3*N for N>=0. N must fit existing net arrays; no semantic contact-ID/range validation observed.","Pocket flag is true only for integer1; other parsed integers become false."], ["No GUID or M block-word count is read in this direction. Direct C2S echo is incompatible."])
add("pool", "S2C", [57,63], [F(0,"tableIndex","int"),F(1,"ackOrWhiteX","literal OK | float/InvariantCulture"),F(2,"whiteZ","float/InvariantCulture","Replay only")], ["0x599c20","0x59bcd0"], "OK acknowledges without replay; otherwise write white-ball net X/Z to positions[0]. Set gotMoveFoul=true and doMoveFoul=(not OK).", [TABLE_BOUNDS,"Replay requires initialized positions[0] and3 fields; ACK2 fields. No finite/table-position bounds check observed."])


DTO_NAMES = ["BoardGameLogic.Move", "BoardGamesTable.Data", "DartsGameTable.TableData", "DartsGameTable.Player", "DartsRules.DartShotData"]
ENUM_NAMES = ["SpaceGameManager.TableState", "BoardGamesManager.GameState", "BoardGamesManager.GameRules", "DartsGameManager.GameState", "DartsGameManager.GameRules", "PoolGameManager.GameState", "ChessPiece.Type", "ChessPiece.Color", "DraughtsPiece.Type", "DraughtsPiece.Color"]


def type_block(name: str) -> str:
    m = re.search(r"^(?:public|private|internal|protected) (?:abstract )?(?:class|enum) " + re.escape(name) + r"(?:\s|:).*?^}", DUMP, re.M | re.S)
    if not m:
        raise ValueError("Missing metadata type: " + name)
    return m.group(0)


dtos = {}
for name in DTO_NAMES:
    block = type_block(name)
    fields = [{"type": t, "name": n, "offset": off} for t,n,off in re.findall(r"public ([\w.\[\]]+) (\w+); // (0x[\dA-Fa-f]+)", block)]
    dtos[name] = {"codec": "EntryData", "fields_in_metadata_order": fields, "metadata_block_sha256": hashlib.sha256(block.encode()).hexdigest(), "source": "work/decompiled/dump.cs", "note": ENTRY}
enums = {}
for name in ENUM_NAMES:
    block = type_block(name)
    enums[name] = {n:int(v) for n,v in re.findall(r"public const [\w.]+ (\w+) = (-?\d+);", block)}
for name, dto in dtos.items():
    schema = []
    for f in dto["fields_in_metadata_order"]:
        kind = f["type"]
        if kind in enums:
            kind = {"enum": list(enums[kind])}
        elif kind.endswith("[]"):
            kind = {"array": kind[:-2]}
        schema.append({"name":f["name"],"type":kind})
    dto["canonical_codec_schema"] = schema
    dto["codec_api"] = "avatar_entry_codec.decode_entry_fields(text, canonical_codec_schema) / encode_entry_fields(values, canonical_codec_schema); floating point encode values must be explicit lexical strings"

all_rvas = sorted({int(x,16) for c in contracts for x in c["evidence_rvas"]} | {0x52e910,0x5373b0,0x550550,0x5367a0,0x5383d0,0x5376a0})
evidence = []
for rva in all_rvas:
    p = FUN / (f"{rva:x}.c")
    evidence.append({"rva":hex(rva),"va":hex(0x180000000+rva),"metadata_names":NAMES.get(rva,[]),"pseudocode_path":str(p.relative_to(ROOT)).replace("\\","/"),"pseudocode_sha256":sha(p) if p.exists() else None,"status":"decompiled" if p.exists() else "pending_transitive_decompile"})

expected = {x["opcode"] for x in REGISTRATIONS if 32 <= x["opcode"] <= 43 or 51 <= x["opcode"] <= 63 or 80 <= x["opcode"] <= 91}
actual = {x["opcode"] for x in contracts if x["direction"] == "S2C"}
assert expected == actual, (expected-actual,actual-expected)
assert len(contracts) == len({(c["direction"],c["opcode"]) for c in contracts})

data = {
    "schema_version":1,
    "scope":"BoardGamesManager, DartsGameManager, PoolGameManager native client TCP payload contracts",
    "provenance":"Static IL2CPP metadata plus focused Ghidra12.1.3 pseudocode; no target execution or network observations. Hashes identify source artifacts, not original C# or REA evidence IDs.",
    "status":"Client field-consumption and emission contracts recovered; original server state parity is unproved.",
    "source_artifacts":[{"path":str(p.relative_to(ROOT)).replace("\\","/"),"sha256":sha(p)} for p in [ROOT/"work/evidence/GameAssembly.dll", ROOT/"work/decompiled/script.json", ROOT/"work/decompiled/dump.cs", OUT/"tcp-dispatch-map.json"]],
    "index_convention":"Zero-based fields after opcode removal; C2S indices before generic #platform-name trailer.",
    "transport_dependency":"See tcp-reconstruction.md and tcp-contracts.json. Mirror NebulaMessage wraps AES128ECB/PKCS7 Base64 payload; C2S AES adds #StandaloneWindows or #PS4. S2C handlers do not generically strip that tail.",
    "entrydata_dependency":"tools/avatar_entry_codec.py is the canonical shared codec reconstruction. Use its ordered-schema decode_entry_fields/encode_entry_fields API with entrydata_dtos.*.canonical_codec_schema. Floats encode from explicit lexical strings; decode null marker does not itself model initialized CLR field/reused-array skip assignment. This protocol is not JSON.",
    "entrydata_grammar":{"source_rvas":["0x6a5d10","0x6a5020","0x6a65b0","0x6a59f0"],"token":"One UTF16 code unit chr(UTF16Length(text)+0x24), followed by text; null sentinel text is nulls.","scalar":"Enum Object.ToString names then Enum.Parse; bool True/False; numeric strings, float InvariantCulture.","array":"A prefixed decimal count token, followed by elements. Primitive/string elements are tokens; EntryData subclass elements recursively concatenate their fields without outer element wrapper.","null_array":"Prefixed nulls token causes deserializer to leave the existing field unchanged; it is not equivalent to a fresh empty array.","nested_class":"EntryData fields concatenate recursively without an outer token. Deserialization relies on initialized nested objects; null nested object serialization omits fields and is not a safe stand-alone grammar.","board_table_example_shape":"token(gameRulesName)+token(GUIDcount)+token(GUID0)+...+token(PS4IDcount)+token(PS4ID0)+...", "scope_note":"Codec facts supplied by independent avatar_contracts static audit; see its source-hashed canonical deliverable for complete evidence."},
    "nested_board_snapshots":{
        "envelope":{"rva":"0x541310","format":"One rules character 0..3 followed by concrete board text; rules0 does not deserialize a body."},
        "TicTacToe":{"rva":"0x550550","format":"One character per tiles[] entry in array order. Lowercase x selects player0/X object; lowercase o selects player1/O object; other characters leave tile state untouched.","effects":"Recognized x/o activates its mark and clears tile-selectability flag. No implicit clearing for unrecognized character in this method.","validation":"Text must have at least tiles.Length UTF16 characters; extra characters are ignored."},
        "Chess":{"evidence_rvas":["0x52e910","0x5367a0"],"format":"One character per board tile in outer dimension0, inner dimension1 order. 0 is empty; p/r/n/b/q/k = Pawn/Rook/Knight/Bishop/Queen/King. Lowercase selects White(0), uppercase selects Black(1). This case convention differs from FEN.","piece_char_map":{"p":"Pawn","r":"Rook","n":"Knight","b":"Bishop","q":"Queen","k":"King"},"effects":"Destroy/clear both existing piece lists, recreate pieces at grid coordinates.","validation":"Only mapped lower/uppercase letters and0 are supported; other characters cause dictionary lookup failure; short text causes get_Chars bounds failure; extra text ignored.","unknown":"Grid dimensions depend on initialized board asset Bounds.Rows/Colums; constructor field defaults alone do not prove serialized asset dimensions."},
        "Draughts":{"evidence_rvas":["0x5373b0","0x5383d0","0x5376a0"],"format":"One character per board tile in outer dimension0, inner dimension1 order. 0 is empty; r/R=Regular, k/K=King. Lowercase selects White(1), uppercase selects Red(0).","piece_char_map":{"r":"Regular","k":"King"},"effects":"Destroy/clear both existing piece lists, recreate pieces at grid coordinates.","validation":"Only r/R/k/K and0 supported; invalid nonzero char dictionary lookup fails; short text get_Chars fails; extra text ignored.","unknown":"Grid dimensions are initialized from serialized Bounds.Rows/Colums; no authoritative server dimensions inferred."},
    },
    "board_move_replay":{
        "TicTacToe":{"rva":"0x550a10","effects":"Set isPlayersTurn=true; index tiles[targetX*3+targetY]; store playerIndex and activate X for0 or O for1; clear tile-selectability, show local pointer/control UI.","validation":"Origin coordinates unused. Array bounds checked for flattened index; no occupancy/turn/legal-move check in this ApplyMove body. Player values other than0/1 still get stored but activate neither mark."},
        "Chess":{"rva":"0x5327b0","effects":"Copy originX/Y to initialized input.moveData, call SelectDestination(targetX,targetY), set isPlayersTurn=true, activate side1-playerIndex, update selected tile/pointer/control UI.","unknown":"SelectDestination and concrete BoardGameLogic legal-move/animation behavior are transitive gameplay algorithms beyond this network wrapper; original server adjudication remains unknown."},
        "Draughts":{"rva":"0x538ff0","effects":"SelectOrigin(originX,Y), SelectDestination(targetX,Y). If multipleMove=false: isPlayersTurn=true, activate side1-playerIndex, clear activatedMoves and update pointer/control UI. If multipleMove=true, carry target coordinates into originX/Y for the next jump.","unknown":"Multiple-capture legality, promotion and termination depend on deeper local gameplay methods; no original server decision policy is established."},
    },
    "coverage":{"registered_clientbound":len(expected),"clientbound_contracts":len(actual),"clientbound_missing":[],"serverbound_emitters":sum(c["direction"]=="C2S" for c in contracts),"enum_only_unregistered":[{"opcode":op,"name":OPCODES[op]} for op in [38,58,83]],"pending_evidence_rvas":[e["rva"] for e in evidence if e["status"] != "decompiled"]},
    "unknown_original_server_semantics":[
        "Seat ownership/authentication, GUID binding, reconnect/disconnect cleanup, timeouts and recipient visibility rules.",
        "Exact table transition guards, simultaneous join/start arbitration, first-player selection and when request/reply versus OneWay variants are sent.",
        "Board legal-move adjudication, turn progression, checkmate/draw rules and authoritative result/XP accounting. Client rules/input code may duplicate some rules but cannot prove the removed server's policy.",
        "Darts score adjudication, shot validation, deterministic deflection/physics agreement, round/turn authority and result/XP accounting.",
        "Pool rules variants, authoritative foul/win adjudication, ball-contact/physics trust, sequence/ack timing, replay recipient selection and result/XP accounting.",
        "Initialized asset grid dimensions and authoritative legal coordinate bounds are not recovered from snapshot parsers; concrete input replay calls into deeper local gameplay methods.",
        "Request35/85 send caller-provided strings; their EntryData move types are established on the receiving side. Full outbound gameplay construction and all concrete local rule algorithms are separate from the sender's field contract.",
    ],
    "enums":enums,"entrydata_dtos":dtos,"contracts":sorted(contracts,key=lambda x:(x["game"],x["direction"],x["opcode"])),"native_evidence":evidence,
}
(OUT/"minigame-contracts.json").write_text(json.dumps(data,indent=2)+"\n",encoding="utf-8")

lines = ["# Board, Darts and Pool native TCP contracts", "",data["status"],"",data["provenance"],"",f"Recovered {len(actual)} registered clientbound handlers and {data['coverage']['serverbound_emitters']} emitted request shapes. Source binary SHA256: `{data['source_artifacts'][0]['sha256']}`.","","Indices below exclude the opcode. Requests also acquire the global platform-name trailer; server replies must follow their own layouts. EntryData values use the custom reflection codec, **not JSON**.","","## Payloads",""]
for game in ("board","darts","pool"):
    lines += ["### "+game.title(),"","| Direction | Opcode | Fields |","|---|---:|---|"]
    for c in data["contracts"]:
        if c["game"] != game: continue
        columns = "; ".join(f"`{f['index']}` {f['name']} ({f['type'].replace('|','or')})" for f in c["fields"]) or "Payload ignored"
        lines.append(f"| {c['direction']} | {c['opcode']} | {columns} |")
    lines.append("")
lines += ["## Compatibility details", "", "- Board35 reply checks state only; Board43 decodes/applies the move through the input component before checking state. Neither is a direct echo of request35.","- Board37 snapshot starts GUID pairs at `N+1`, but the native board-state loop consumes only state slots1 throughN-1. Preserve the skipped slotN until stronger evidence justifies a change.","- Darts init/start/sync use variable TableBlocks: serialized TableData, decimal player count, then that many serialized Player records. Darts87 instead decodes only TableData.","- Darts82 reply reads player count at field1; Darts89 ignores field1. Both parse selected rules at field2.","- Pool55/56/57 and61/62/63 accept exact `OK` at field1 as acknowledgements. Replay layouts omit request GUID and, for56, the block-word-count M.","- Pool ball positions are X/Z in local table coordinates. Reply56 consumes `N`, `2*N` position floats, `N` pocket flags and two white-ball contact integers.","- Pool start identifies seat0 by literal `playerOne`; any other non-null role text selects seat1.","- Parsing/bounds checks are client constraints, not recovered server-side authorization or validation.","","## EntryData DTOs",""]
for name, dto in dtos.items():
    lines += [f"`{name}`: "+", ".join(f"{f['name']}: {f['type']}" for f in dto['fields_in_metadata_order'])+".",""]
lines += ["## Nested snapshot/shot effects", "", "Board snapshots prefix a single rules digit to concrete board text. TicTacToe reads lowercase x/o per tile; Chess/Draughts read one character per grid cell, 0 for empty. Chess p/r/n/b/q/k select Pawn/Rook/Knight/Bishop/Queen/King; lowercase is White and uppercase Black, differing from FEN. Draughts r/k select Regular/King; lowercase is White and uppercase Red. Unrecognized TicTacToe characters leave existing state untouched. Chess/Draughts clear old pieces before rebuilding.","", "Board replay43 dispatches through the input component. TicTacToe uses targetX*3+targetY, ignores origin and selects X/O by player0/1. Chess and Draughts call local origin/destination handlers; Draughts preserves multiple-capture continuation. Original server legal-move and result policies remain unknown.","", "Darts passive shots decode immediately only in Pointing(4); otherwise they queue. Immediate decode updates local dart X/Y, raycasts the board field and requests Shoting(5). A replay is therefore dependent on local scene/rules state, rather than just assigning a server score.","", "EntryData arrays prefix an element-count token. Nested EntryData records concatenate fields recursively without element wrappers. Null-array sentinel leaves the existing field unchanged. Consult the shared codec for exact UTF16 token framing; JSON DTO records include ready-to-use ordered schemas for its generic API.","", "## Evidence and remaining gaps", "", "The JSON includes individual native RVAs/VAs, pseudocode hashes, metadata type hashes, per-message effects and client validation. Enum-only opcodes38,58 and83 have no registered receive handler in the recovered dispatch map.","", "Pending requested transitive decompiles: "+(", ".join(data['coverage']['pending_evidence_rvas']) or "none")+".",""]
for gap in data["unknown_original_server_semantics"]: lines.append("- "+gap)
lines += ["","Wire compatibility does not establish original server rules, recipient policies or complete state parity. No client/server was launched or contacted to create this artifact.",""]
(OUT/"minigame-contracts.md").write_text("\n".join(lines),encoding="utf-8")
print(json.dumps(data["coverage"]))
