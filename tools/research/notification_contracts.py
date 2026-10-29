"""Generate bounded notification/layer contracts from local static evidence.

Reads PE bytes, IL2CPP metadata and already exported pseudocode only. Never
loads native code, attaches, opens a socket, starts the game or a service.
"""

from _research_paths import workspace, output_root, game_path
from pathlib import Path
import bisect
import hashlib
import json
import struct

import capstone
import pefile

ROOT = workspace()
OUT = ROOT / "results/protocol"
BINARY = ROOT / "work/evidence/GameAssembly.dll"
FUNCTIONS = ROOT / "work/evidence/ghidra/functions"
EXPECTED = "c4dd5db599e5e5ce4adf25f09ffe70ad10e0928adf6a2e862176d537026b44ac"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def direct_call_candidates(pe, names, targets):
    starts = sorted(names)
    runtime = [(entry.struct.BeginAddress, entry.struct.EndAddress)
               for entry in getattr(pe, "DIRECTORY_ENTRY_EXCEPTION", [])]
    runtime.sort()
    begins = [row[0] for row in runtime]
    decoder = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    rows = []
    for section in pe.sections:
        if not section.Characteristics & 0x20000000:
            continue
        raw = section.get_data()
        position = raw.find(b"\xe8")
        while position >= 0:
            if position + 5 <= len(raw):
                rva = section.VirtualAddress + position
                target = rva + 5 + struct.unpack_from("<i", raw, position + 1)[0]
                if target in targets:
                    idx = bisect.bisect_right(starts, rva) - 1
                    start = starts[idx] if idx >= 0 else None
                    ridx = bisect.bisect_right(begins, rva) - 1
                    region = runtime[ridx] if ridx >= 0 and rva < runtime[ridx][1] else None
                    aligned = False
                    if region:
                        # Check E8 is actually an instruction boundary when
                        # decoding from its PE runtime-function start.
                        for instruction in decoder.disasm(pe.get_data(region[0], rva + 5 - region[0]), region[0]):
                            if instruction.address == rva:
                                aligned = instruction.mnemonic == "call" and instruction.size == 5
                                break
                    rows.append({"target": targets[target], "target_rva": hex(target),
                        "call_rva": hex(rva), "nearest_metadata_method_rva": hex(start) if start is not None else None,
                        "method_names": names.get(start, []), "pe_runtime_function": [hex(x) for x in region] if region else None,
                        "instruction_boundary_confirmed": aligned})
            position = raw.find(b"\xe8", position + 1)
    return rows


def main():
    if digest(BINARY) != EXPECTED:
        raise ValueError("Native source hash differs from reviewed build")
    metadata_path = ROOT / "work/decompiled/script.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8-sig"))
    names = {}
    for method in metadata["ScriptMethod"]:
        names.setdefault(method["Address"], []).append(method["Name"])
    pe = pefile.PE(str(BINARY))
    calls = direct_call_candidates(pe, names, {
        0x480710: "NotificationsManager.Push", 0x1b62950: "Animator.SetLayerWeight"})
    refs = [0x5df8a0, 0x480710, 0x489160, 0x47ee90, 0x476950, 0x477470,
            0x480d80, 0x4812d0, 0x488bc0, 0x47e050, 0x47fa70, 0x47f160,
            0x488fe0, 0x5e7db0, 0x412fe0, 0x40fbb0, 0x5ec380, 0x610d40, 0x4764f0,
            0x5ea6e0, 0x5dfdc0, 0x6e82a0, 0x6e8f80, 0x4c6a60]
    evidence = []
    starts = sorted(names)
    for rva in refs:
        path = FUNCTIONS / f"{rva:x}.c"
        index = bisect.bisect_right(starts, rva)
        end = min(starts[index] if index < len(starts) else rva + 24000, rva + 24000)
        evidence.append({"rva": hex(rva), "names": names.get(rva, []),
            "native_byte_range": [hex(rva), hex(end)],
            "native_bytes_sha256": hashlib.sha256(pe.get_data(rva, end-rva)).hexdigest(),
            "pseudocode": str(path.relative_to(ROOT)), "pseudocode_available": path.is_file(),
            "pseudocode_sha256": digest(path) if path.is_file() else None})
    tcp = json.loads((OUT / "tcp-contracts.json").read_text(encoding="utf-8"))
    types = tcp["enums"]["NotificationsManager.NotificationType"]
    # These conclusions are manually reviewed from the named native bodies;
    # the tool reproduces provenance/structured output, not semantic recovery.
    known = {0:"private-chat request", 1:"friend request", 2:"empty body", 3:"gift prefix + arguments + gift suffix",
             4:"System Reward", 5:"friend-accepted text", 11:"SpaceGame Invitation EntryData -> game enum name"}
    unknown = {2:"FullGame arguments suffix after first !", 6:"invite-to-space text", 7:"ask-to-join text"}
    summaries = []
    for name, value in types.items():
        summaries.append({"type": value, "enum_name": name, "deferred_game_type": value in (2,10,11,12),
            "body_when_source_resolves": known.get(value, "empty body"),
            "body_when_source_does_not_resolve": unknown.get(value, "empty body"),
            "confirm_behavior": "HTTP resolve -> LoadSpace; no TCP26" if value == 6 else
                "Send_AcceptFullGameNotification; deferred full game" if value == 2 else
                "C2S26 guid#sourceName#11 (platform omitted)" if value == 11 else
                "C2S26 guid#sourceName#type#sourcePlatform",
            "dismiss_behavior": "C2S95 guid#sourceName#sourcePlatform#declineType" if value in (2,11) else "local remove only",
            "recovered_c2s19_producer": value in (0,1,6),
            "native_direct_local_push_producer_recovered": False,
            "local_outbox_support": value in (3,4)})
    report = {
        "format_version": 1,
        "scope": "Static client contracts and integrated authored preservation modules; no game, listener, connection, attach or native execution",
        "binary": str(BINARY), "binary_sha256": EXPECTED,
        "metadata_sha256": digest(metadata_path), "declarations_sha256": digest(ROOT / "work/decompiled/dump.cs"),
        "reused_evidence": [{"path":str((OUT/name).relative_to(ROOT)), "sha256":digest(OUT/name)} for name in
                            ("tcp-contracts.json", "tcp-callers.json", "tcp-notification-consumable-native.json")],
        "generator": str(Path(__file__).relative_to(ROOT)), "generator_sha256": digest(Path(__file__)),
        "notification_packet": {
            "c2s_opcode": 19, "c2s_fields": ["senderUsername", "targetUsername", "notificationType:Int32", "targetPlatform:Int32"],
            "c2s_reviewed_types": [0,1,6],
            "s2c_opcode": 19, "s2c_fields": ["playerName", "platform:Int32", "type:Int32", "arguments", "ticks:Int64"],
            "ticks": "System.DateTime ticks, valid range0..3155378975999999999; UI new DateTime(ticks).ToString(hh:mm)",
            "prerequisites": ["ManagerInstance.chat.notificationsManager initialized", "PS4Info and player preferences available", "Chat0 suppressed when isChatRestricted"],
            "dedupe": {"types": [0,1,5], "key": ["type","playerName","platform"], "ignored_in_key": ["ticks","arguments"]},
            "in_memory_only": True,
            "all_entries_bind_confirm_and_dismiss": True,
            "formatting_prerequisite": "Gift/Reward text requires source username/platform resolved through Memory.remotes only; local recipient identity does NOT resolve through this lookup; missing source shows timestamp+name without Gift/Reward body",
            "earliest_inbox_delivery": "C2S1 is sent by OnAvatarLoaded5dfdc0 after animator/control/companion/locomotion/randomidle setup; constructing its payload earlier5ea6e0 is not send",
        },
        "notification_types": summaries,
        "gift": {
            "http_route": "NPShopGiftItem", "request": "GUID#PS4ID#offerID#targetUsername#displayedCrystals",
            "response": "true#GUID#PS4ID#ErrorBUY_enum_name#targetUsername#offerID",
            "response_consumption": "Callback requires6 fields; checks own GUID, status field3, target field4; field5 required by length but unread",
            "callback_effect": "sender Item gifted popup or error, shop-info refresh; no local Push or C2S19",
            "grant_authority": "Existing backend Shop._gift durable entitlement/debit transaction; notification is separate bookkeeping",
            "original_notification_arguments": "UI consumes arguments as gift display text; original source mapping unknown",
        },
        "join": {
            "invite6": "HTTPGetPsidglobalAndGuidByUsernamePlatform(sourceName,sourcePlatform) -> callback488fe0 -> LoadSpace(psidglobal,empty,true,guid,null); empty psidglobal rejects",
            "ask7": "unknown-source text exists; Confirm falls through ordinary26. No recovered direct C2S19 producer, owner approval policy or allocation continuation",
            "types8_9_13": "enum-only meanings; no dedicated formatting or acceptance continuation in reviewed modern UI; Confirm falls through ordinary26",
            "opcode27": {"fields_consumed": "count only", "less_than3": "CannotConnectIsFull; unlock pad", "at_least3": "HTTPSpaceLoading IsFromNotification=true; request actual local GUID#PS4ID", "does_not_consume_values": True,
                         "original_server_producer": "unknown", "modern_invite6_does_not_need_27": True},
        },
        "animation_layer93": {
            "direction": "clientbound-only in recovered send inventory", "fields": ["guid", "layerName", "weight:Int32"],
            "prerequisites": ["Memory.GetNebulaPlayer(guid) resolves Unity object", "NebulaPlayer.avatar non-null", "PlayerAnimationEvents child and footStepAnimationEvent non-null", "avatar.Animator non-null"],
            "effects_in_order": ["footStepAnimationEvent.activated=false", "GetLayerIndex(layerName)", "SetLayerWeight(index,float(Int32.Parse(weight)))"],
            "native_conversion_rvas": ["0x5ec49b","0x5ec4a2"],
            "missing_avatar": "returns without queueing", "invalid_layer_guard": "none recovered", "weight_clamp": "none recovered",
            "recovered_c2s_producer": False, "original_server_rule": "unknown",
            "safe_integration": "no client-origin93 echo or blanket replay; use only source-bound authored effects after actual avatar build if justified",
            "local_set_layer_weight_calls_do_not_prove_tcp93": True,
        },
        "authored_outbox": {
            "types": [3,4], "ownership_is_separate": True,
            "enqueue": "must run inside existing grant Store.atomic; schema initialization must run before it",
            "reward_source": "actual recipient username/platform; truthful authored identity policy; native remotes-only lookup still degrades text until reviewed fallback-formatting patch",
            "gift_source": "actual donor username/platform; full text degrades when donor not in Memory; no fabricated presence",
            "delivery": "at-least-once across process/session restart; one inflight event per recipient/sourceName/platform/type; no packet acknowledgement evidence",
            "ack": "C2S26 only maps in-flight sender/type tuple; no event ID exists on wire; write durable receipt then MarkAccepted; never regrant or send S2C26",
            "dismissal": "gift/reward dismissal emits no wire event; unacknowledged notices may replay on reconnect",
            "retention": "no original expiry recovered; pending notices retained; accepted DB rows and immutable ack files retained",
            "export": {"filename":"instance-notifications.json", "root":"shared state root", "format_version":1,
                "fields":["generation:UnixSeconds","entries:[event_id,target_ps4_id,source_username,source_platform:Int32,notification_type:3|4,arguments,ticks:Int64]"],
                "freshness_seconds":15, "future_tolerance_seconds":5, "max_entries":10000},
            "ack_directory":"notification-acks", "ack_filename":"event_id(lowercase UUID-N)+'-'+guid(lowercase UUID-N)+.json; legacy event_id.json also accepted",
            "ack_fields":["format_version","event_id","target_ps4_id","guid","source_username","source_platform","notification_type","accepted_at"],
            "unsupported_types":[7,8,9,13],
            "integration_state":"Integrated into Service/Shop/Rewards and the compile-only Mirror instance; offline account/receipt checks only, live delivery untested",
            "offline_backend_tests_passed":9,
        },
        "authored_informational_type5": {
            "type":5, "behavior":"acknowledge only an actually sent notice for exact recipient session/sourceName/platform; retire bookkeeping without friendship mutation",
            "record":"after successful transport Send of type5", "accept":"ordinary26 must carry type5 and match pending key; do not require a live source peer",
            "ttl_seconds_default":300, "capacity_default":256,
            "duplicate_send":"refreshes one pending key, matching client unread deduplication",
            "disconnect":"removes recipient session pending entries", "durability":"in-process only; no event files or original retention claim",
            "other_types":"all rejected by dedicated helper", "pure_check_assertions":30,
            "validation":"parent owns final pure C# harness execution/compile",
        },
        "direct_call_candidates": calls, "evidence": evidence,
        "limitations": ["No original server source or runtime parity evidence", "Indirect calls are not excluded by direct E8 scan", "Gift full text when donor absent needs a narrowly reviewed client formatting change", "26 cannot distinguish multiple arbitrary simultaneously displayed notices from one sender/type", "Join7/8/9/13 policy and server producer remain unrecovered", "Animation93 has no recovered native C2S producer or original server effect policy"],
    }
    sources = ["backend/notifications.py", "backend/tests/test_notifications.py",
               "backend/service.py", "backend/server.py", "backend/shop.py", "backend/rewards.py",
               "backend/tests/test_notification_integration.py", "backend/tests/test_state_refresh.py",
               "mirror-server/UnityProject/Assets/Preservation/NebulaInstanceServer.cs",
               "mirror-server/UnityProject/Assets/Preservation/NebulaNotificationInbox.cs",
               "mirror-server/UnityProject/Assets/Preservation/NebulaInformationalNotifications.cs",
               "tools/offline-mirror-tests/InformationalChecks.cs", "tools/offline-mirror-tests/NotificationChecks.cs"]
    report["authored_sources"] = [{"path": path, "sha256": digest(OUT.parent / path)} for path in sources]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "notification-contracts.json").write_text(json.dumps(report, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
    (OUT / "notification-contracts.md").write_text(markdown(), encoding="utf-8")
    print(json.dumps({"report":"notification-contracts.json", "native_functions":len(evidence),
                      "push_direct_candidates":len([row for row in calls if row["target_rva"]=="0x480710"])}))


def markdown():
    return '''# Notifications, gifts, rewards and animation layer93

This is static evidence for the shipped Windows IL2CPP build `c4dd5db599e5e5ce4adf25f09ffe70ad10e0928adf6a2e862176d537026b44ac`. No game, listener, connection, attach or native execution was used. `notification_contracts.py` reproduces the machine-readable report, evidence hashes and bounded direct-call candidates. Existing broad TCP recovery is reused.

## Notification transport and UI

The reviewed C2S19 request is `senderUsername#targetUsername#type#targetPlatform`, produced for private chat0, friend1 and invitation6. S2C19 is **different**: `playerName#platform#type#arguments#ticks`. `NotificationProcessor.Process0x5df8a0` parses both enums as Int32 and ticks as Int64, then calls Push; restricted chat suppresses only Chat0. The manager/chat/preferences must exist first.

`Push0x480710` keeps an in-memory unread list and per-type toast count. Only Chat0, Friend1 and Friend_Accepted5 are deduplicated, by `(type, playerName, platform)`; arguments/ticks are not part of that key (`0x489160`). Gift3 and Reward4 are never deduplicated there. The direct executable-section E8 scan finds one Push candidate, the confirmed receiver call at `0x5dfa0d`; it does not exclude indirect calls.

`CreateNotification0x47ee90` binds every entry's confirm to AcceptNotification and cancel to DismissNotification. `SetAsNotification0x476950` stores/stylizes the entry. `ChatEntry.set_notification0x477470` performs text formatting. It creates `DateTime(ticks)` and formats `hh:mm`, so arbitrary Unix seconds or out-of-range ticks are wrong. The final entry contains time, colored playerName and a type-specific body.

The body has a surprising avatar lookup dependency. `GetguidByUsername0x610d40` enumerates **only Memory.remotes(+0x18)**. LocalPlayer(+0x10) is separate: SetPlayer0x6e82a0 stores the own player there. Therefore the real local recipient does not satisfy this name lookup, even after avatar loading:

| Type | Source username/platform resolves in Memory | Source does not resolve |
|---|---|---|
| Chat0 | private-chat request text | empty body |
| Friend1 | friend request text | empty body |
| Gift3 | gift prefix + **arguments** + gift suffix | empty body |
| Reward4 | `System Reward`; arguments unread | empty body |
| Friend_Accepted5 | friend acceptance text | empty body |
| InviteToJoin6 | empty body | invitation text |
| AskToJoin7 | empty body | ask-to-join text |
| AceptedToJoin8 / NewInstanceIsCreated9 / SocialToJoin13 | empty body | empty body |

All rows still contain time and playerName. Resolving an actual avatar additionally supplies its name color. The local implementation retains the actual donor identity. A separate [prepared client formatting candidate](notification-text-compatibility.md) fills only empty Gift3/Reward4 bodies through the original string helpers. It has not been exercised by the native client.

The toast is simpler: Update0x4812d0 picks a queued type and coroutine0x488bc0 shows its count and enum name (underscores replaced with spaces), plays incoming sound, extends duration when count changes and removes only the toast queue item. It neither grants an item nor acknowledges a durable notice.

## Acceptance, dismissal and joins

Ordinary confirm removes the entry locally and sends C2S26 `localGUID#sourceName#type#sourcePlatform`. This includes Gift3, Reward4 and Friend_Accepted5, despite those being informational. There is no event ID, arguments or ticks in this acceptance packet. No client receive registration exists for26, so a fabricated S2C26 success is not justified.

Invite6 is an exception: Accept0x47e050 calls HTTPGetPsidglobalAndGuidByUsernamePlatform. Callback0x488fe0 shows CannotConnectIsNotInSpace for an empty psidglobal; otherwise it calls `LoadSpace(psidglobal,"",true,guid,null)`. It sends no26. This modern path is already covered by allocation/HTTP reconstruction.

Ask7 has display text but no dedicated accept continuation: it falls through ordinary26. Types8,9,13 have neither dedicated text nor a dedicated join continuation in the reviewed modern UI. No direct native C2S19 producer for7/8/9/13 was recovered. Their enum names do not establish owner approval rules, instance creation or membership transitions; they stay unsupported rather than fabricating state.

S2C27 ToJoinNotification0x5e7db0 checks **only field count**. Fewer than3 fields shows CannotConnectIsFull and unlocks input. At least3 starts HTTPSpaceLoading with IsFromNotification=true and the actual local GUID/PS4ID. Values are unread. No original server producer/authorization rule is recovered, and modern Invite6 does not use this message.

FullGame2 and SpaceGame11 plus their decline types10/12 belong to deferred minigame/full-game flows. SpaceGame11 confirm omits sourcePlatform; FullGame2 invokes its separate manager. Dismiss/DeclineAll send95 only for2/11. Every non-game dismissal is a local remove; there is no Gift/Reward dismissal event to persist.

## Gift and reward producers

`Send_NPShopGiftItem0x412fe0` sends `GUID#PS4ID#offerID#targetUsername#displayedCrystals`. Callback0x40fbb0 requires six response fields, checks local GUID, reads ErrorBUY enum-name status at3 and target name at4; field5 is length-required but unread. It shows the sender confirmation/error, refreshes shop info and closes gift UI. It does not create a recipient notification, locally Push or send19.

The existing local `Shop._gift` transaction already validates local friendship, offer, ownership and balance, debits the sender, and grants the target. The correct local event producer is therefore inside that transaction after the grant/ownership row, using the actual donor username/platform and offer's shipped `name` as Gift.arguments. Original server display-name selection and delivery policy are unavailable.

Existing RewardService claims atomically grant configured entitlements and insert their idempotent claim marker. A fresh entitlement claim may enqueue Reward4 in the **same transaction**. Cinema capabilities and availability checks do not create item rewards. The local Reward4 policy uses the actual recipient username/platform as a truthful display identity. **It still does not reach `System Reward` through the remotes-only lookup**; complete text requires the separately reviewed client fallback-formatting correction. Reward.arguments is empty because the UI never consumes it. This identity choice is authored policy, not recovered original server behavior.

## Isolated implementation and integration

`backend/notifications.py` adds NotificationOutbox; schema initialization must precede any Store.atomic group. `enqueue_gift(target,source,item_name,dedupe_key)` and `enqueue_reward(target,dedupe_key)` require the grant's existing atomic group. They never grant, debit or inspect client-side acceptance as ownership. A stable per-grant dedupe key prevents retry duplication. A fault/reopen test proves that grant and notice roll back together.

Parent integration points:

1. Construct NotificationOutbox once in backend service setup and inject into Shop/RewardService. Enqueue only after a successful fresh gift/reward grant and claim marker, inside the current transaction. Never enqueue on an already-owned or repeated reward result.
2. Before/after normal snapshot refresh, import durable receipts and atomically export `instance-notifications.json` at the shared state root. It contains version1, generation Unix seconds and ordered entries: `{event_id,target_ps4_id,source_username,source_platform,notification_type,arguments,ticks}`. Source platform is native numeric PS4=0/StandaloneWindows=1. Event IDs are immutable lowercase UUID-N. Export caps at10000 and fails rather than truncating silently.
3. The pure C# `NebulaNotificationInbox` accepts the DTO via Replace(snapshot,nowUnix), requiring freshness15s, future tolerance5s and monotonic generation. Read the file with FileShare.ReadWrite|FileShare.Delete. InstanceServer supplies only current bound/announced account sessions with the matching instance allocation; the helper cannot authenticate or allocate. The source-backed earliest delivery point is C2S1: its payload is constructed earlier in0x5ea6e0, but is sent from OnAvatarLoaded0x5dfdc0 after animator/control/companion/locomotion/random-idle setup. There is no need to wait for a self animation query, which the native path does not send.
4. `Peek(accountId,guid,nowUnix)` prepares one notice per `(recipient,sourceName,sourcePlatform,type)` key. Send its Payload through existing AES reply delivery, then MarkQueued(delivery). It cannot mark failed sends as delivered. Per-frame polling alone must not resend in-flight events.
5. Handle26 types3/4 before the current NamedPeer lookup: Own/current session/announced checks still apply, but the source may be offline. `Accept(accountId,guid,sourceName,type,platform,nowUnix)` prepares a receipt only for an event queued to that session. Atomically persist the receipt, then MarkAccepted(receipt). Do not send S2C26, regrant, or require a live donor. Disconnect(guid) releases unacknowledged events for replay.
6. Receipt path is shared-root `notification-acks/<event_id>-<guid>.json`, with both IDs lowercase UUID-N; legacy `<event_id>.json` is also accepted. Exact fields are version1, event_id, target_ps4_id, guid, source_username, source_platform, notification_type, accepted_at Unix seconds. Backend validates filename IDs, immutable event tuple and newest account session, then updates accepted_at idempotently. UTF8 BOM is accepted. Keep receipt files immutable; duplicate imports are safe. Session-qualified filenames let a new session acknowledge an event whose previous-session receipt was not imported before login rollover, without overwriting that receipt. If a same-session receipt already exists, compare its event/account/source/type/GUID tuple and valid timestamp rather than requiring its timestamp to equal the new retry's clock.

This is explicit **at-least-once delivery**. Neither transport send nor toast display proves client consumption. Gift/reward cancel emits no event and therefore may replay on reconnect. A lost acceptance before receipt persistence may also replay. The helper remembers accepted IDs while a stale snapshot still contains them. Without event IDs in26, arbitrary simultaneous same-sender/type notices cannot be acknowledged precisely; the local serialization rule narrows that ambiguity but cannot add a native event ID.

Nine socket-forbidden backend tests cover offline durability, stable deduplication, transactional rollback/reopen, actual identities, no ownership change on acceptance, newest-session/tuple checks, snapshot/receipt handoff and session rollover with separate immutable receipts. Two integration tests verify fresh reward/gift notices, retry behavior and atomic rollback when enqueueing fails. The HTTP adapter refreshes files every two seconds; the instance polls at its five-second heartbeat after current-session reconciliation and native avatar announcement. C# inbox and informational helpers are linked into the offline harness and compiled Unity instance. [Offline validation](../offline-validation.json) and [build validation](../mirror-server/build-validation.json) bind current results; live delivery remains untested.

## Informational Friend_Accepted5 confirmation

The native client also confirms informational Type5 using26. The pure `NebulaInformationalNotifications` helper records a notice only after a successful Type5 send, keyed by exact recipient GUID/sourceName/platform. Accept additionally requires type5, consumes the key once and makes no friendship or entitlement change. It does not require a live sender. The instance routes this branch before NamedPeer lookup while retaining bound/current-session/announced validation.

Retention is authored in-process policy: default TTL300 seconds/capacity256; both are injectable and bounded. Repeated successful sends refresh one key, consistent with native unread Type5 deduplication. Expire removes at the exact expiry boundary; Disconnect removes only the recipient session. It has no clock, filesystem or event-file access. `InformationalChecks.Run()` contains30 pure assertions for unsolicited/wrong-source/platform/session acceptance, every other shipped type, one-use acknowledgement, TTL, capacity, isolation and invalid inputs.

## Animation layer93

`UpdateAnimationLayerProcessor.Process0x5ec380` consumes `guid#layerName#Int32weight`. It first resolves a Unity player, then requires its avatar, a PlayerAnimationEvents child, that child's footStepAnimationEvent and avatar Animator. A missing player returns and the event is not queued; other missing dependencies throw through the native null path.

In order it writes **footStepAnimationEvent.activated=false**, obtains Animator.GetLayerIndex(layerName), and calls SetLayerWeight(index, float(parsedInt)). Native MOVD0x5ec49b/CVTDQ2PS0x5ec4a2 prove the integer-to-float conversion omitted by Ghidra's inferred signature. No index guard or weight clamp was recovered. Emitting fractional strings would fail Int32.Parse.

No C2S93 producer was recovered in the existing direct TCP send inventory. Many local operations call Animator.SetLayerWeight (coffee, locomotion, swimming, wardrobe/hand weights, avatar masking and Mirror.NetworkAnimator); those calls do not prove a TCP93 producer or original server policy. The report lists direct native candidates so this distinction is auditable. Incoming93 stays clientbound-only. Do not blanket-clear footsteps or invent remote layer messages merely to cover the enum; a justified authored effect must be delivered after the actual actor avatar is built.

Remaining non-game limitations in this scope are native validation of the gift/reward formatting candidate and delivery timing, unrecovered legacy join7/8/9/13 server policy, and absent original animation93 producer semantics. Integration is present in source and compiles; retired-server parity remains unproven.
'''


if __name__ == "__main__":
    main()
