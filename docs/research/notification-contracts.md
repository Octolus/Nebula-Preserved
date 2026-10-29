> Historical research: this file records an earlier investigation, not current feature acceptance. The root [PROGRESS report](../PROGRESS.md) is authoritative. Local evidence and extracted game code are intentionally omitted. See [research index](README.md).

# Notifications, gifts, rewards and animation layer93

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

Nine socket-forbidden backend tests cover offline durability, stable deduplication, transactional rollback/reopen, actual identities, no ownership change on acceptance, newest-session/tuple checks, snapshot/receipt handoff and session rollover with separate immutable receipts. Two integration tests verify fresh reward/gift notices, retry behavior and atomic rollback when enqueueing fails. The HTTP adapter refreshes files every two seconds; the instance polls at its five-second heartbeat after current-session reconciliation and native avatar announcement. C# inbox and informational helpers are linked into the offline harness and compiled Unity instance. [Offline validation](README.md#omitted-local-evidence) and [build validation](README.md#omitted-local-evidence) bind current results; live delivery remains untested.

## Informational Friend_Accepted5 confirmation

The native client also confirms informational Type5 using26. The pure `NebulaInformationalNotifications` helper records a notice only after a successful Type5 send, keyed by exact recipient GUID/sourceName/platform. Accept additionally requires type5, consumes the key once and makes no friendship or entitlement change. It does not require a live sender. The instance routes this branch before NamedPeer lookup while retaining bound/current-session/announced validation.

Retention is authored in-process policy: default TTL300 seconds/capacity256; both are injectable and bounded. Repeated successful sends refresh one key, consistent with native unread Type5 deduplication. Expire removes at the exact expiry boundary; Disconnect removes only the recipient session. It has no clock, filesystem or event-file access. `InformationalChecks.Run()` contains30 pure assertions for unsolicited/wrong-source/platform/session acceptance, every other shipped type, one-use acknowledgement, TTL, capacity, isolation and invalid inputs.

## Animation layer93

`UpdateAnimationLayerProcessor.Process0x5ec380` consumes `guid#layerName#Int32weight`. It first resolves a Unity player, then requires its avatar, a PlayerAnimationEvents child, that child's footStepAnimationEvent and avatar Animator. A missing player returns and the event is not queued; other missing dependencies throw through the native null path.

In order it writes **footStepAnimationEvent.activated=false**, obtains Animator.GetLayerIndex(layerName), and calls SetLayerWeight(index, float(parsedInt)). Native MOVD0x5ec49b/CVTDQ2PS0x5ec4a2 prove the integer-to-float conversion omitted by Ghidra's inferred signature. No index guard or weight clamp was recovered. Emitting fractional strings would fail Int32.Parse.

No C2S93 producer was recovered in the existing direct TCP send inventory. Many local operations call Animator.SetLayerWeight (coffee, locomotion, swimming, wardrobe/hand weights, avatar masking and Mirror.NetworkAnimator); those calls do not prove a TCP93 producer or original server policy. The report lists direct native candidates so this distinction is auditable. Incoming93 stays clientbound-only. Do not blanket-clear footsteps or invent remote layer messages merely to cover the enum; a justified authored effect must be delivered after the actual actor avatar is built.

Remaining non-game limitations in this scope are native validation of the gift/reward formatting candidate and delivery timing, unrecovered legacy join7/8/9/13 server policy, and absent original animation93 producer semantics. Integration is present in source and compiles; retired-server parity remains unproven.
