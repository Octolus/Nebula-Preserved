"""Produce static TCP contracts from manually reviewed IL2CPP native evidence.

This program reads evidence and writes documentation only. It does not load the
game DLL, run game code, open sockets, encrypt sample packets, or test a client.
"""

from _research_paths import workspace, output_root, game_path
from pathlib import Path
import hashlib
import json
import re

ROOT = workspace()
OUT = ROOT / "results/protocol"
GHIDRA = ROOT / "work/evidence/ghidra/functions"


def field(name, kind="string", **extra):
    return {"name": name, "type": kind, **extra}


def contract(op, fields, notes, refs, **extra):
    return {"opcode": op, "fields": fields, "behavior": notes,
            "evidence_rvas": [f"0x{x:x}" for x in refs],
            "basis": "statically observed native body and IL2CPP declarations", **extra}


F = field
CLIENTBOUND = [
    contract(0, [], "Ignores incoming fields. Starts async local-player/avatar initialization. See handshake sequence; send only after Mirror local player spawn.", [0x5e0570, 0x5ea6e0, 0x5dfdc0], ignores_all_fields=True),
    contract(1, [F("netId", "uint32"), F("guid"), F("username"), F("platform", "int32:PS4Info.Platform")], "Ignores existing guid. Requires remotePlayersToBuild[netId] populated by a prior Mirror spawn. Removes pending object, sets guid/identity, adds Memory remote, loads HTTP label/avatar. Callback requests locomotion/companion/position/animation.", [0x5e4660, 0x5e43c0, 0x5e42d0]),
    contract(2, [F("netId", "int32"), F("transform", "json:NebulaPlayerTransform.TransformData")], "Looks up player by netId, deserializes JSON and sets Transform.position and rotation directly. Unknown player ignored.", [0x5e7ed0]),
    contract(5, [F("guid"), F("typeanim", "int32:NebulaPlayerAnim.TypeAnim"), F("typecycle", "int32:NebulaPlayerAnim.TypeCycle"), F("anim"), F("originalNamesCount", "int32"), F("originalNames", "string[]", start=5, count_field=4)], "Looks up guid and calls SetAnim. Count controls exact array slice; the platform suffix must not become an animation name.", [0x5d6fb0]),
    contract(9, [F("requesterGuid"), F("occupableId", "int32"), F("occupantGuid")], "Empty occupant ignored. If requesterGuid equals occupantGuid, local NebulaInteractor.SetOccupable(id, occupantGuid). Otherwise updates local interactable[id] with occupantGuid. Semantic names inferred from this comparison and C2S seat request.", [0x5dfa40, 0x6159f0], naming_inference=True),
    contract(10, [F("unused0", used=False), F("occupableId", "int32")], "Clears occupantGuid to empty on local occupable list[id]; token0 not read.", [0x5dc440]),
    contract(11, [F("guid"), F("groupName")], "Known player and existing chat tab required; applies player relationship/platform display checks, invokes typing bubble path.", [0x5e70c0]),
    contract(12, [F("guid")], "Known player required; applies relationship/platform checks and deletes typing bubble.", [0x5e7580]),
    contract(13, [F("guid"), F("groupName"), F("platform", "int32"), F("message"), F("chatType", "int32:Chat.ChatType")], "ChatType 0 uses group/presence/relationship/platform filtering. Nonzero type bypasses those normal space-chat filters. Nonempty group delivered through pooled Chat.ChatMessageData and Chat.OnMessageReceived. No CustomDecrypt in this receive path.", [0x5d7790, 0x5d7a70]),
    contract(14, [F("guid")], "Removes Memory remote/interactable and can append disconnected message to private chat. In personal space, owner departure starts HTTPCheckIsInWardrobe before kick decision. Mirror destroy is a separate transport event.", [0x5e0c60, 0x5e0dd0]),
    contract(15, [F("guid"), F("locomotionName")], "Known player.UpdateLocomotion; empty string represents removal in C2S sources.", [0x5ec4d0, 0x5f3c60]),
    contract(17, [F("guid"), F("companionName")], "Known player.UpdateCompanion. Registration uses opcode17 UpdateCompanion; enum7 Companion has no client receive registration.", [0x5d7c20, 0x439f60]),
    contract(18, [F("guid"), F("key", "int32:PlayerPrefsManager.PlayerPrefsKeys"), F("value")], "Applies if guid is in Memory or local SessionGUID. Receiver implements mood0/status1/label-display2,3,4/color15/platformOnly21; other keys no effect in reviewed branch body. See preference details.", [0x5e4670, 0x5e4780]),
    contract(19, [F("playerName"), F("platform", "int32"), F("type", "int32:NotificationsManager.NotificationType"), F("arguments"), F("ticks", "int64")], "Constructs NotificationData(type, playerName, platform, ticks, arguments) and Push. Chat notification type0 suppressed when isChatRestricted. Direction differs from C2S19 request shape.", [0x5df8a0]),
    contract(21, [F("username"), F("platform", "int32")], "Resolves guid from username/platform and calls SetRemoteRelation(false). Shares native body with op22/23.", [0x5d6db0]),
    contract(22, [F("username"), F("platform", "int32")], "Resolves guid from username/platform and calls SetRemoteRelation(false). Shares native body with op21/23.", [0x5d6db0]),
    contract(23, [F("username"), F("platform", "int32")], "Resolves guid from username/platform and calls SetRemoteRelation(false). Shares native body with op21/22.", [0x5d6db0]),
    contract(24, [F("username"), F("platform", "int32")], "Resolves guid from username/platform and refreshes relation/avatar visibility; exact child callback effect remains to audit.", [0x5d6bc0], semantic_gaps=["child visibility callback"]),
    contract(25, [F("username"), F("platform", "int32")], "Resolves guid from username/platform and refreshes relation/avatar visibility; exact child callback effect remains to audit.", [0x5e55e0], semantic_gaps=["child visibility callback"]),
    contract(27, [F("unread0", used=False), F("unread1", used=False), F("unread2", used=False)], "Only checks field count: <3 => CannotConnectIsFull and reset Pad input; >=3 => HTTPSpaceLoading(IsFromNotification=true), request local SessionGUID#PS4ID. Does not inspect values. Extra trailing platform tokens would influence this count gate.", [0x5e7db0], fields_are_length_gate_only=True),
    contract(28, [F("guid"), F("relationType", "int32")], "Nonempty known guid -> UpdateRemoteRelation(relationType).", [0x5e54d0]),
    contract(29, [F("guid")], "Remote guid enters wardrobe ghost/deactivation; local guid switches CharacterEditor and adds wardrobe checker. No Boolean field read.", [0x5e6530]),
    contract(30, [F("unused0", used=False), F("isDay", "System.Boolean.Parse string")], "Reads token1 only; calls DayNightCycle.StartCycle(!isDay). C2S request has only bool payload, so echo is wrong.", [0x5d7650]),
    contract(31, [F("guid"), F("allowed", "System.Boolean.Parse string"), F("boatToken", "int32")], "If allowed and player exists, sets HarbourEnter/BoatTripManager token, starts delayed boat instantiate/seat paths, removes coffee prop if present.", [0x5d72a0]),
    contract(92, [F("guid"), F("parameter"), F("type", "int32:AnimatorControllerParameterType"), F("value")], "Known player animation.SetParameter(parameter,type,value).", [0x5d6e90]),
    contract(93, [F("guid"), F("layerName"), F("weight", "int32 converted to float")], "Finds animation layer by name and SetLayerWeight((float)weight). Native 0x5ec49b MOVD and0x5ec4a2 CVTDQ2PS preserve integer conversion omitted by Ghidra signature.", [0x5ec380]),
    contract(94, [F("guid"), F("interactableId", "int32"), F("state", "System.Boolean.Parse string"), F("extension", "string[]", start=3)], "Finds APITPInteractables with matching id; only on state change invokes state-true/state-false virtual callback with entire field array, then updates current state. Extension is subtype dependent and not generically decoded here.", [0x5d91b0], semantic_gaps=["APITPInteractables subtype extension schemas"]),
    contract(96, [F("unused0", used=False), F("instanceId")], "If token1 equals current instance id: owner-disconnected UI, disables input and RedirectToNexus. Token0 ignored.", [0x5dbd80]),
]

SERVERBOUND = [
    contract(1, [F("netId", "uint32"), F("sessionGuid"), F("username"), F("platform", "int32:PS4Info.Platform")], "Stored on OnConnected; actually sent only from local OnAvatarLoaded after HTTP label/avatar and scene-interactable initialization. Numeric platform precedes global platform-name suffix.", [0x5ea6e0, 0x5dfdc0]),
    contract(2, [F("netId", "uint32"), F("transform", "json:NebulaPlayerTransform.TransformData")], "SendData uses local Mirror identity.netId and JsonUtility.ToJson. Position-distance gate can suppress send; typeTCP initialized to2. Separate Mirror NetworkTransform also exists.", [0x615000, 0x6156b0]),
    contract(3, [F("requesterGuid"), F("targetGuid")], "Sent after remote avatar loaded to request current animation.", [0x5f2070, 0x5e42d0]),
    contract(4, [F("guid"), F("netId", "int32:-1 or signed local Mirror netId"), F("typeanim", "int32:NebulaPlayerAnim.TypeAnim"), F("typecycle", "int32:NebulaPlayerAnim.TypeCycle"), F("anim"), F("originalNamesCount", "int32"), F("originalNames", "string[]", start=6, count_field=5)],
             "SetCurrentAnim removes locomotion first, sets/loads local animation then sends4. Field1 is the metadata Int32 netId parameter. Seat/emote callers pass -1; RandomIdle.Initialize0x43e740 instead passes PlayerInfo.get_NetId0x616a70, preserving the UInt32 Mirror identity bits as signed Int32 decimal text. OnConnectedProcessor.OnAvatarLoaded0x5dfdc0 calls RandomIdle.Initialize at0x5e0223 before sending the stored C2S1 announcement at0x5e024f, so an own-netId animation can precede announcement. Preservation admission checks -1 or unchecked((int)peer.netId), retains GUID ownership validation and does not require announcement; this is a reconstruction policy, not proof of retired server rules. Names are joined with #. For no names, the final string field is empty after count0. Clientbound animation uses5 and omits field1.",
             [0x44aed0,0x5f4500,0x6157c0,0x5dfdc0],
             direct_caller_audit={
                 "scope": "Static scan of all executable-section E8 instructions targeting SetCurrentAnim0x5f4500; 22 direct calls, 21 passing0xffffffff and one passing the local Mirror netId. Indirect and inlined callers are not exhaustively established by this count.",
                 "own_netid_producer": "RandomIdle.Initialize0x43e740; only its local-player branch sends this update",
                 "signed_conversion": "The getter returns UInt32 in EAX; the caller writes those bits to the Int32 fifth parameter; SetCurrentAnim calls Int32.ToString. UInt32 values at or above0x80000000 therefore appear as negative decimal Int32 values.",
                 "native_ranges": [
                     {"rva": "0x43e740", "end_rva_exclusive": "0x43e810", "sha256": "7958c62275e2cdb1b21379031dc51941089c1c6940850368b2bf0b7e6adcc55e"},
                     {"rva": "0x616a70", "end_rva_exclusive": "0x616aa0", "sha256": "789b398707e27783f96e5565012f0c3ea7d17fbc2ce6184f304f5c13dddfb0f5"}],
                 "native_instructions": [
                     {"rva": "0x43e7cb", "bytes": "e8a0821d00", "observation": "CALL PlayerInfo.get_NetId0x616a70"},
                     {"rva": "0x43e7e6", "bytes": "89442420", "observation": "MOV [RSP+0x20],EAX: fifth argument before CALL"},
                     {"rva": "0x43e7f0", "bytes": "e80b5d1b00", "observation": "CALL SetCurrentAnim0x5f4500; EDX=1 and R8D=1"},
                     {"rva": "0x5e0223", "bytes": "e818e5e5ff", "observation": "CALL RandomIdle.Initialize0x43e740"},
                     {"rva": "0x5e024f", "bytes": "e8cc750000", "observation": "Later CALL TCPClient.Send0x5e7820 for stored announcement"}],
                 "getter_path": "PlayerInfo+0x30 -> NebulaPlayer+0xf8 -> NetworkIdentity+0x28",
                 "binary": "work/evidence/GameAssembly.dll; SHA256 in top-level binary record",
                 "runtime_observed_field_value": None}),
    contract(6, [F("requesterGuid"), F("targetGuid")], "GetCurrentCompanion request after remote avatar loaded. Response behavior cannot be proven from absent server source; client receiver is opcode17.", [0x5e3b10, 0x5e42d0]),
    contract(8, [F("requesterGuid"), F("occupableId", "int32")], "Each NebulaOccupable.Initialize registers itself with local interactor and requests occupancy state.", [0x612380]),
    contract(9, [F("guid"), F("occupableId", "int32")], "Seat/animation selection requests occupancy. Server must resolve occupant/race and generate S2C9 third field; response cannot be a raw echo.", [0x6159f0, 0x44b2f0]),
    contract(10, [F("guid"), F("occupableId", "int32")], "NebulaOccupable.LeaveInteract sends before local cleanup.", [0x612700]),
    contract(11, [F("guid"), F("groupName")], "Sent when input starts for active chat tab; tab Notifications excluded.", [0x5f0320]),
    contract(12, [F("guid")], "Sent by both PC OnMessageWritten and PS4 dialog result before sending chat.", [0x463310, 0x4625b0]),
    contract(13, [F("guid"), F("groupName"), F("platform", "int32"), F("message"), F("chatType", "int32:Chat.ChatType")], "SendMessage strips literal '<', '>', '#' to empty then keeps only first space in each consecutive ASCII-space run. No CR/LF sanitizer observed here. Does not apply CustomEncrypt. Platform is the passed ChatTab platform; global suffix is sender platform name.", [0x4640c0, 0x463310, 0x4625b0]),
    contract(15, [F("guid"), F("locomotionName")], "Locomotion UI sends selected resource or empty. RemoveLocomotion sends trailing # for empty name. Empty field must be preserved before AES suffix.", [0x4b9be0, 0x5f3c60]),
    contract(16, [F("requesterGuid"), F("targetGuid")], "GetCurrentLocomotion request after remote avatar loaded; client receiver is15.", [0x5e3d80, 0x5e42d0]),
    contract(17, [F("guid"), F("companionName")], "Pet UI sends selected resource or empty; boat paths also remove companion with empty string.", [0x4c0b00, 0x451e00]),
    contract(18, [F("guid"), F("key", "int32:PlayerPrefsManager.PlayerPrefsKeys"), F("value")], "HTTPSavePlayerPref.OnResponse sends only when HTTP result first token equals lowercase true and returned guid equals local SessionGUID; key limited to0,1,15,21. Other preference saves do not send in this callback.", [0x6399f0]),
    contract(19, [F("senderUsername"), F("targetUsername"), F("notificationType", "int32:NotificationsManager.NotificationType"), F("targetPlatform", "int32")], "Observed private-chat request(type0), friend request(type1), invite(type6) constructors. Unlike clientbound19, no arguments/ticks in these reviewed request constructors; other paths may extend.", [0x6e8f80, 0x4c6a60], variant_scope="reviewed private-chat/friend/invite constructors"),
    contract(20, [F("requesterGuid"), F("targetGuid")], "GetCurrentPosition request after remote avatar loaded; response schema inferred to use transform receiver2, not established from server source.", [0x5e3ff0, 0x5e42d0]),
    contract(29, [F("guid")], "ManagerInstance.OnSetIsWardrobe sends local SessionGUID; HTTP wardrobe flow precedes callback.", [0x4393e0]),
    contract(30, [F("newState", "System.Boolean.ToString string")], "DayNightTrigger.Interact sends logical inverse of local state; no guid in request. S2C format differs.", [0x44f580]),
    contract(31, [F("guid"), F("requested", "System.Boolean.ToString string"), F("boatToken", "int32")], "HarbourEnter.Callback observed requested=True and token field from HarbourEnter+0x20; other boat source also needs authority review.", [0x451640]),
    contract(92, [F("guid"), F("parameter"), F("type", "int32:AnimatorControllerParameterType"), F("value")], "NebulaPlayerAnim.SendParameter forwards parameter update.", [0x5f3ee0]),
    contract(94, [F("guid"), F("interactableId", "int32"), F("newState", "System.Boolean.ToString string"), F("extension", "string[]", start=3)], "GenericInteractable.SendData emits inverse of current state then appends every strings[] parameter separated by #. Extension subtype dependent.", [0x451100], semantic_gaps=["APITPInteractables subtype extension schemas"]),
]

CLIENTBOUND.extend([
    contract(44, [F("guid"), F("unused1", used=False), F("tag", literal="coffee"), F("numberOfConsumables", "int32")], "Only tag coffee accepted; FoodTruckManager.Set(guid,count). Token1 is unread. Server response needs one extra field compared with reviewed C2S44.", [0x5dbcc0, 0x404da0]),
    contract(45, [F("guid"), F("unused1", used=False), F("tag", literal="coffee"), F("numberOfConsumables", "int32")], "Same effective parsing as44; tag coffee then FoodTruckManager.Set(guid,count).", [0x5dbc00, 0x404da0]),
    contract(46, [F("guid"), F("unused1", used=False), F("tag", literal="oktoberfest"), F("numberOfConsumables", "int32")], "Only tag oktoberfest accepted; OktoberFestManager.Set(guid,count). Token1 is unread.", [0x5dbfb0, 0x4087f0]),
    contract(47, [F("guid"), F("tag", literal="oktoberfest"), F("numberOfConsumables", "int32")], "OneWay variant removes unused token1: checks tag at1 and count at2. Do not reuse normal46 layout.", [0x5dbef0, 0x4087f0]),
])

SERVERBOUND.extend([
    contract(21, [F("guid"), F("targetUsername"), F("targetPlatform", "int32", optional=True)], "Standard callbacks emit guid, target username, platform; SocialOptionsSpaceUsers.OnAddFriend branch emits guid,target username with platform OMITTED. Preserve variant distinction; sender platform suffix remains global.", [0x4c5db0, 0x6ed5a0, 0x4c9530], variants=[{"source_rva":"0x4c9530","fields":["guid","targetUsername"]}]),
    contract(22, [F("guid"), F("targetUsername"), F("targetPlatform", "int32")], "RemoveSilenced callbacks emit these three fields; receiver echo shape differs (username,platform only).", [0x4c6140, 0x6ed8e0]),
    contract(23, [F("guid"), F("targetUsername"), F("targetPlatform", "int32")], "AddSilenced confirmation callback.", [0x6edc20]),
    contract(24, [F("guid"), F("targetUsername"), F("targetPlatform", "int32")], "Block confirmation callbacks. Client local relation visibility refresh accompanies the command.", [0x4cbf60, 0x6ed260]),
    contract(25, [F("guid"), F("targetUsername"), F("targetPlatform", "int32")], "RemoveBlock callback emits guid,target username,platform.", [0x4c64d0]),
    contract(26, [F("guid"), F("notificationPlayerName"), F("notificationType", "int32:NotificationsManager.NotificationType"), F("notificationPlatform", "int32", optional=True)], "AcceptNotification: type11 SpaceGame sends only guid,playerName,11 (platform OMITTED); ordinary branch includes type/platform. Type6 InviteToJoin instead resolves identity through HTTP and calls NETGcloudLogin.LoadSpace; type2 FullGame parses arguments and hands off to FullGameManager.LaunchMultiScene. See transitive findings. No receive registration for26.", [0x47e050,0x488fe0,0x439ad0,0x4499b0,0x449250], variants=[{"notification_type":11,"fields":["guid","notificationPlayerName","11"]}], semantic_gaps=["downstream FullGame/GCloud networking and original notification persistence"]),
    contract(44, [F("guid"), F("tag", literal="coffee"), F("consumableValue")], "UiFoodTruckMenuInit.GetConsumable sends after HTTP callback matches local guid, coffee tag, Boolean success. Last payload copied from HTTP field6, meaning not inferred beyond consumableValue. HTTP field7 updates UI integer separately. Literal #coffee# inserts delimiters.", [0x4190b0]),
    contract(46, [F("guid"), F("tag", literal="oktoberfest"), F("consumableValue")], "Same UI/HTTP gating as coffee; literal #oktoberfest# then HTTP field6 copied. S2C46 uses four fields, S2C47 three.", [0x419ba0]),
    contract(95, [F("guid"), F("notificationPlayerName"), F("notificationPlatform", "int32"), F("declineType", "int32:NotificationsManager.NotificationType")], "DismissNotification and DeclineAll emit only for incoming FullGame2 or SpaceGame11. declineType=10 FullGame_Declined or12 SpaceGame_Declined. No receive registration for95.", [0x47fa70, 0x47f160]),
])

BOWLING_PANEL = [F("actorGuid"), F("laneId", "int32"), F("panel", "EntryData:BowlingGameManager.BowlingPanelData")]
BOWLING_SHOT = [F("laneId", "int32"), F("positionOrAck", "float32-invariant or literal OK"), F("angle", "float32-invariant", optional_when_ack=True), F("strength", "float32-invariant", optional_when_ack=True), F("spin", "float32-invariant", optional_when_ack=True)]
BOWLING_PINS = [F("laneId", "int32"), F("pinCountOrAck", "int32 or literal OK"), F("pins", "repeated 7 fields: BinaryConverter float32 position x/y/z, Euler x/y/z, unread string", start=2, stride=7, count_field=1, optional_when_ack=True)]

CLIENTBOUND.extend([
    contract(64, BOWLING_PANEL, "Marks lane.imIn=true then Get_InitializeGame. Panel is EntryData, not JSON. Actor guid selects playerDataPublic[i].GUID; PS4ID comparison identifies local seat. Free0/Awaiting2 initialize and seat; Playing4 closes local join menu and clears imIn; Rejected1/Ready3 return. See tcp-bowling.md.", [0x5d9d30,0x552bd0,0x547a10]),
    contract(72, BOWLING_PANEL, "Activates lane GameObject then same initialize consumer as64; does not mark imIn=true.", [0x5d9c70,0x552bd0,0x547a10]),
    contract(65, BOWLING_PANEL, "Marks lane.imOut=true then Get_LeaveGame. Compares previous and new panel players to stand/remove departed players, refresh score UI, deactivate on local/last departure, and request ChangeTurn15 if current player departed.", [0x5da230,0x552c40,0x547eb0]),
    contract(73, BOWLING_PANEL, "If local lane State.Inactive0, sends C2S71 sync request and returns without caching this leave packet. Otherwise handles leave only for existing panel LaneState2/3/4. Same EntryData payload as65.", [0x5d9de0,0x552c40,0x547eb0]),
    contract(66, BOWLING_PANEL, "Inactive lane: caches message with action74 and requests C2S71. Active lane: only when previous panel state Awaiting2, re-initializes with new panel; if new state Ready3 invokes Get_StartGame. The latter sets panel Playing4 and requests local State.StartGame3. Opcode67 BowlingStart has no receive registration.", [0x5da760,0x547a10,0x548740]),
    contract(74, BOWLING_PANEL, "Same ready/start state path as66; cache action74 on inactive lane. Get_StartGame counts nonempty names, seats non-turn players, stands turnIndex player, sets turn index and resets frame.", [0x5da2e0,0x547a10,0x548740]),
    contract(68, BOWLING_SHOT, "OK sets gotMoveShot=true and doMoveShot=false, without parsing floats. Otherwise copies four InvariantCulture floats, resets/repositions ball, prepares remote player shot animation and marks doMoveShot/gotMoveShot=true.", [0x5d9c30,0x552af0,0x5473b0]),
    contract(76, BOWLING_SHOT, "Inactive lane: caches message with action76 and requests C2S71. Otherwise forwards to same ball-shot consumer as68.", [0x5d98b0,0x552af0,0x5473b0]),
    contract(69, BOWLING_PINS, "OK sets gotMovePins=true/doMovePins=false. Otherwise parses pinCount, decodes six two-UTF16-unit float strings per pin into net positions/Euler arrays; advances7 tokens per pin and ignores seventh. No score or turn index read here.", [0x5daf60,0x552d20,0x548ea0,0x4d4140]),
    contract(77, BOWLING_PINS, "Inactive lane: caches message with action77 and requests C2S71. Otherwise same pins consumer as69.", [0x5dabe0,0x552d20,0x548ea0]),
    contract(70, [F("laneId", "int32")], "Requests local State.ChangeTurn15. No server-supplied next-turn index read by receiver; local state machine handles turn progression.", [0x5db7e0,0x552b60,0x5479f0]),
    contract(78, [F("laneId", "int32")], "Inactive lane: caches message with action78 and requests C2S71. Otherwise same ChangeTurn consumer as70.", [0x5db460,0x552b60,0x5479f0]),
    contract(71, BOWLING_PANEL, "Ignored if existing panel Playing4 or no cached synchronization message. Otherwise activates lane, Get_StartGame using full panel field2, schedules cached-message replay, clears cache. Shipped replay reads cached lane at field3 despite modern layouts using0/1 and coroutine expects old actions3211/3212/3214/3215 rather than74/76/77/78; unresolved compatibility gap.", [0x5dafa0,0x548740,0x5534b0,0x5618c0], semantic_gaps=["stale cached-message field index and old action numbers"]),
    contract(79, [F("guid"), F("laneId", "int32"), F("seatIndex", "int32")], "Finds player and disables capsule collider if not already disabled. Negative seatIndex returns after disabling; nonnegative seat teleports position/rotation to lane scene seat. Already disabled collider returns before teleport.", [0x5db1f0]),
])

SERVERBOUND.extend([
    contract(64, [F("guid"),F("PS4ID"),F("laneId", "int32")], "BowlingGameManager.Send_InitializeGame sends local SessionGUID, PS4ID and trigger/lane id.", [0x552ea0]),
    contract(65, [F("guid"),F("PS4ID"),F("laneId", "int32")], "Lane.Send_LeaveGame sends local SessionGUID, PS4ID and tableId. Server must produce updated panel, not echo these fields.", [0x54c3d0]),
    contract(66, [F("guid"),F("laneId", "int32")], "UIBowlingMain.OnSelect sends ready/select command. No C2S67 construction observed in reviewed paths.", [0x5634e0]),
    contract(68, [F("guid"),F("laneId", "int32"),F("position", "float32-invariant"),F("angle", "float32-invariant"),F("strength", "float32-invariant"),F("spin", "float32-invariant")], "Send_BallShot formats four ordinary decimal floats using InvariantCulture; these are not BinaryConverter strings. Clientbound shot omits guid or uses OK acknowledgement.", [0x54b8b0]),
    contract(69, [F("guid"),F("laneId", "int32"),F("declaredLength", "int32", expression="7*pinCount+1"),F("pinCount", "int32"),F("pins", "repeated7: BinaryConverter float32 local position x/y/z, local Euler x/y/z, literal0", start=4, stride=7, count_field=3)], "Send_StrikePins builds declaredLength and count then seven tokens per pin. BinaryConverter float strings are raw low/high16-bit UTF16 code units; no escaping observed. Receiver format omits guid and declaredLength.", [0x54c750,0x4d4260]),
    contract(70, [F("guid"),F("laneId", "int32"),F("nextTurnIndex", "int32")], "Send_ChangeTurn computes increment/wrap and skips empty player GUID slots, then sends candidate next index. Receiver only reads lane id; retired server authority/validation not recoverable here.", [0x54bff0]),
    contract(71, [F("guid"),F("laneId", "int32")], "Emitted from inactive-lane OneWay/ready handlers. Receiver requires a full panel snapshot with additional actor and EntryData fields, not an echo.", [0x5d98b0,0x5da760,0x5dabe0,0x5db460,0x5d9de0]),
])

TRANSITIVE_FINDINGS = [
    {"feature":"InviteToJoin notification acceptance", "evidence_rvas":["0x47e050","0x488fe0"], "observed":"Type6 uses HTTP identity-resolution callback rather than modern TCP26. Callback checks resolved psidglobal nonempty, then NETGcloudLogin.LoadSpace(psidglobal, empty noIdSpace, true, resolvedGuid, null). Empty psidglobal shows CannotConnectIsNotInSpace and clears pad lock."},
    {"feature":"FullGame notification acceptance", "evidence_rvas":["0x439ad0","0x4499b0","0x449250"], "observed":"Type2 passes notification.arguments to ManagerInstance.Send_AcceptFullGameNotification. Splits at first !, retains prefix through ! for EntryData.Deserialize, uses suffix to instantiate FullGameNETGCloud.OpenGameEntry subtype. Disconnect callback selects scene by FullGameManager.Type enum name, loads if absent, waits then calls FullGameManager.LaunchMultiScene(openGame). No modern TCP26 send in reviewed continuations; downstream FullGame/GCloud mode is a separate dependency."},
    {"feature":"FoodTruck/OktoberFest receiver effect", "evidence_rvas":["0x404da0","0x4087f0"], "observed":"Resolve guid through Memory; missing player ignored. Find existing PlayerCoffee(Clone) or PlayerOktoberFest(Clone) child. If absent, instantiate configured prefab under player transform and InitPlayerCoffee/InitPlayerOktoberFest(received count, player). Existing consumable refresh sets current times field0x18 to maximum field0x1c, ignoring new received count in that branch. Local player also receives drink/help UI. This packet equips/refills a consumable prop; it is not proof of account inventory persistence."},
]


def enum_block(text, full_name):
    m = re.search(r"public enum " + re.escape(full_name) + r"\s*//[^\n]+\n\{(.*?)\n\}", text, re.S)
    if not m:
        m = re.search(r"public enum " + re.escape(full_name.rsplit('.',1)[-1]) + r"\s*//[^\n]+\n\{(.*?)\n\}", text, re.S)
    if not m:
        return {}
    return {k: int(v) for k, v in re.findall(r"public const \S+ (\w+) = (-?\d+);", m[1])}


def main():
    dispatch = json.loads((OUT / "tcp-dispatch-map.json").read_text())
    c2s = {c["opcode"]: c for c in SERVERBOUND}
    s2c = {c["opcode"]: c for c in CLIENTBOUND}
    independent_path = OUT / "minigame-contracts.json"
    independent_scope = None
    if independent_path.exists():
        independent = json.loads(independent_path.read_text(encoding="utf-8"))
        independent_scope = {"path":str(independent_path.relative_to(ROOT)), "sha256":hashlib.sha256(independent_path.read_bytes()).hexdigest(), "coverage":independent["coverage"], "basis":"Independent static BoardGames/Darts/Pool audit; original contract preserved in source document."}
        for source in independent["contracts"]:
            dest = s2c if source["direction"] == "S2C" else c2s
            if source["opcode"] in dest:
                raise ValueError(f"Overlapping independent contract {source['direction']} {source['opcode']}")
            dest[source["opcode"]] = {"opcode":source["opcode"], "fields":source["fields"], "behavior":source["client_effects"], "client_validation":source.get("client_validation",[]), "notes":source.get("notes",[]), "original_server_policy":source.get("original_server_policy"), "evidence_rvas":source["evidence_rvas"], "basis":"independent static minigame audit", "external_contract_source":str(independent_path.relative_to(ROOT))}
    for registration in dispatch["registrations"]:
        op = registration["opcode"]
        s2c.setdefault(op, {"opcode": op, "fields": None, "behavior": "Registered receive handler; wire fields and transitive game-state semantics not yet audited.", "basis": "registration only", "evidence_rvas": [registration["process_rva"]], "status": "incomplete"})
        s2c[op].update({"enum_name": registration["enum_name"], "handler": registration["handler"]})
    names = {r["opcode"]: r["enum_name"] for r in dispatch["registrations"]}
    for r in dispatch.get("opcodes_without_client_handler", []):
        names[r["opcode"]] = r.get("enum_name", r.get("name"))
    for op, c in c2s.items():
        c["enum_name"] = names.get(op)

    dump = (ROOT / "work/decompiled/dump.cs").read_text(encoding="utf-8-sig")
    enums = {n: enum_block(dump, n) for n in ["TCPs.TypeTCP", "PS4Info.Platform", "Chat.ChatType", "NotificationsManager.NotificationType", "PlayerPrefsManager.PlayerPrefsKeys", "NebulaPlayerAnim.TypeAnim", "NebulaPlayerAnim.TypeCycle", "UnityEngine.AnimatorControllerParameterType", "BowlingGameManager.LaneState", "BowlingGameManager.State"]}
    rvas = {int(r,16) for c in list(s2c.values())+list(c2s.values()) for r in c["evidence_rvas"]}
    rvas.update(int(r,16) for f in TRANSITIVE_FINDINGS for r in f["evidence_rvas"])
    rvas.update([0x5e7820,0x5e7690,0x5e4f40,0x5e5010,0x5e5240,0x5e54c0,0x439f60,0x6a35a0,0x6a32c0,0x6a2f80,0x6a34d0,0x5d7f90,0x5d7e90,0x5d8800,0x5d8090,0x5d9010,0x5d90d0,0x4d3ea0,0x4d4020,0x4d4140,0x4d4260,0x6a59f0,0x6a5020,0x6a5d10])
    evidence = []
    for r in sorted(rvas):
        f = GHIDRA / f"{r:x}.c"
        evidence.append({"rva": f"0x{r:x}", "path": str(f.relative_to(ROOT)), "sha256": hashlib.sha256(f.read_bytes()).hexdigest() if f.exists() else None})
    obj = {
        "scope": "Static reconstruction of modern TCPs.TCPClient over Mirror. No game/client/server launch, connection, packet capture, or protocol execution test was performed for this analysis.",
        "binary": {"path": "work/evidence/GameAssembly.dll", "sha256": "c4dd5db599e5e5ce4adf25f09ffe70ad10e0928adf6a2e862176d537026b44ac", "preferred_image_base": "0x180000000"},
        "notation": "Field indices are zero based AFTER ProcessorQueue removes opcode. C2S fields listed BEFORE AES.Encrypt globally appends '#' + platform enum NAME. S2C field lists describe client requirements, not proof of the retired server implementation.",
        "transport": {"carrier": "global NebulaMessage : Mirror.NetworkMessage { string data; }", "channel": 0, "application_delimiter": "#", "split_options": "None; preserve empty entries", "opcode": "decimal Int32 in first decrypted token", "client_send_suffix": "# + PS4Info.Platform.ToString()", "cipher": "AES-128-ECB, PKCS7, UTF8 plaintext, standard Base64 ciphertext", "key_derivation": "first16bytes(SHA1(UTF8('a56Bhg2Fbg789Lmk')))", "key_hex": hashlib.sha1(b"a56Bhg2Fbg789Lmk").digest()[:16].hex(), "application_length_prefix": None, "outer_framing": "Mirror/Telepathy; see Mirror compatibility findings. # is an application delimiter, not a TCP packet boundary."},
        "enums": enums,
        "json_shapes": {"NebulaPlayerTransform.TransformData": {"position": {"x": "float32", "y": "float32", "z": "float32"}, "rotation": {"x": "float32", "y": "float32", "z": "float32", "w": "float32"}}, "PlayerPrefsManager.ColorData": {"x": "float32", "y": "float32", "z": "float32"}},
        "entry_data_shapes": {"BowlingGameManager.BowlingPanelData": [{"name":"playerDataPublic","type":"BowlingGameManager.BowlingPlayerDataPublic[]"},{"name":"currentTime","type":"int64"},{"name":"state","type":"enum:BowlingGameManager.LaneState; canonical lexical name"},{"name":"turnIndex","type":"int32"}], "BowlingGameManager.BowlingPlayerDataPublic": [{"name":"name","type":"string"},{"name":"PS4ID","type":"string"},{"name":"GUID","type":"string"},{"name":"ready","type":"bool; True/False"},{"name":"color","type":"string"}]},
        "binary_converter_float": {"encode":"float32 bits -> two UTF16 code units: low16, high16 on this little-endian build", "decode":"first2UTF16 code units ->4little-endian bytes -> float32", "escaping_observed":False, "evidence_rvas":["0x4d3ea0","0x4d4260","0x4d4020","0x4d4140"], "runtime_tested":False},
        "transitive_findings": TRANSITIVE_FINDINGS,
        "independent_minigame_scope": independent_scope,
        "serverbound": sorted(c2s.values(), key=lambda c: c["opcode"]),
        "clientbound": sorted(s2c.values(), key=lambda c: c["opcode"]),
        "unregistered_clientbound_enum_values": dispatch.get("opcodes_without_client_handler", []),
        "ghidra_evidence": evidence,
        "completeness": {"registered_clientbound_opcodes": len(s2c), "reviewed_clientbound_contracts":sum(c["fields"] is not None for c in s2c.values()), "locally_reviewed_clientbound_contracts":len(CLIENTBOUND), "reviewed_serverbound_contracts": len(c2s), "locally_reviewed_serverbound_contracts":len(SERVERBOUND), "server_source_available": False, "runtime_validated": False, "ready_for_1_to_1_server": False, "remaining": ["authoritative minigame rules, ownership and transitions absent from shipped server source", "FullGame/GCloud mode downstream handoff and social persistence", "APITPInteractables subtype extensions", "retired server authoritative selection/ordering, recipient routing, occupancy arbitration and persistence", "Mirror spawn/authority/SyncVars/commands must be joined with application state", "HTTP login/session/space/avatar/inventory contracts owned by separate investigation"]}
    }
    (OUT / "tcp-contracts.json").write_text(json.dumps(obj, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
    lines = ["# Modern TCP application protocol contracts", "", "Static evidence only. No client or server was launched. This is not a claim that networking is restored 1:1. `tcp-contracts.json` carries typed fields and evidence hashes; `tcp-dispatch-map.json` lists all 80 receive registrations.", "", "All fields below follow the opcode. `guid` denotes the game's session/player identifier, not a Mirror asset Guid. Every client `TCPClient.Send` additionally appends `#StandaloneWindows` (Windows) or `#PS4` during AES encryption. Empty tokens are significant.", "", "## Serverbound commands recovered", "", "| Opcode | Fields before platform-name suffix | Native RVA(s) | Behavior |", "|---|---|---|---|"]
    for c in obj["serverbound"]:
        fields = ", ".join(f"{i}:{f['name']} ({f['type']})" for i,f in enumerate(c["fields"]))
        lines.append(f"| {c['opcode']} {c.get('enum_name') or ''} | {fields} | {', '.join(c['evidence_rvas'])} | {c['behavior']} |")
    lines.extend(["", "## Clientbound commands recovered", "", "| Opcode | Fields after opcode removal | Native RVA(s) | Behavior |", "|---|---|---|---|"])
    for c in obj["clientbound"]:
        if c["fields"] is None:
            continue
        fields = ", ".join(f"{i}:{f['name']} ({f['type']})" for i,f in enumerate(c["fields"])) or "No fields read"
        lines.append(f"| {c['opcode']} {c['enum_name']} | {fields} | {', '.join(c['evidence_rvas'])} | {c['behavior']} |")
    lines.extend(["", "## Coverage boundary", "", f"{obj['completeness']['reviewed_clientbound_contracts']} receive contracts and {len(c2s)} send contracts are reviewed across this audit and the independent BoardGames/Darts/Pool audit. The latter is imported with explicit source provenance and its source hash. The local audit contributes {len(CLIENTBOUND)} receive contracts and {len(SERVERBOUND)} send contracts. Registration is proof of clientbound handling; the absence of a registration is not proof of serverbound direction. Client handlers constrain valid responses but cannot recover unshipped server policy by themselves.", ""])
    (OUT / "tcp-contracts.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
