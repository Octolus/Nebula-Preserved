> Historical research: this file records an earlier investigation, not current feature acceptance. The root [PROGRESS report](../PROGRESS.md) is authoritative. Local evidence and extracted game code are intentionally omitted. See [research index](README.md).

# Social and personal-space restoration pass

This pass adds cross-instance social routing and an explicit `nonmini-core-v1` validation scope. A later isolated Linux run passed 43 assertions using two protocol fixtures across Nexus and Home. That isolated run did not launch a native client or change the Windows services. A separate later unhooked native follow-up did validate one cross-instance private-chat presentation path; full readiness and original networking parity remain false. See [runtime report](README.md#omitted-local-evidence).

The managed suite passes **184 checks**, including 51 readiness/social cases. The new `tools/social_runtime_peer.py` passes8 checks while `socket.socket` is forbidden. Its default invocation is dry-run. The managed JSON shim checks policy/file behavior; it is separate from the compiled Unity player and actual two-instance runtime checks.

## Admission and state

Both HTTP and instance must explicitly select `nonmini-core-v1`. It admits public `Nexus`, `LeafPark`, `Beach`, `Cinema`, plus 28 of the31 shipped personal navigator names. CampSilverLake, CutteridgeEstate and SorcerersEyrie remain closed because ordinary/deferred generic IDs are interleaved. Names are case-exact. `Cube` is not a personal navigator entitlement. The existing Nexus-only profile keeps its original behavior.

An actual-bound listener, fresh descriptor, zero Board/Darts counts and verified static scene inventory are required. A personal scene additionally requires fresh root `instance-housing.json`, version1, generation Unix seconds aged0..15s, and `bindings:[{instance_id,psidglobal,owner_ps4_id,logical_space_key}]`. Its unique instance binding must match the current instance/scene, a native personal logical name and an existing current account. The descriptor exposes `scene_registry_verified`, `housing_bound`, `housing_owner`; these do not assert parity or complete housing synchronization.

## Cross-instance contracts

`NebulaSocialMailbox` routes only typed same-host envelopes to a configured safe instance directory. The receiver resolves both current accounts and rechecks allocation and fresh connected+announced presence. It constructs native packets itself. It does not forward arbitrary plaintext or take a client-supplied network endpoint.

The source stores a shared correlated request for19 types0/private,1/friend,6/invite. A different instance can consume26 approval for0/1 exactly once. Friend approval uses the existing immutable friend-event handoff; HTTP owns durable relationship rows. Private consent is shared by session GUID. Friend accepted5, relation refresh21..25/28, private chat13 and typing11/12 can reach another local instance process. Relation-denial checks apply to content, while block/removal refreshes remain deliverable so visibility can update.

A world switch can disconnect Mirror without ending the HTTP session. Its requests/consent therefore survive that transport transition; a superseded session revokes them. Requests expire after300s and consent after86400s, with live/current presence required for use. This and notification correlation/TTL are authored local policies, not recovered retired-server behavior.

The mailbox lease is15s, with a30s maximum accepted lease,512 queued events per target and128 events per0.25s drain. Message bodies are not journaled. Live envelopes contain private text in short-lived files and are deleted on delivery/rejection. A process crash during claim can lose a live notice and leave a processing file; this is not an offline inbox or exactly-once delivery guarantee.

Native `ChatMessageProcessor5d7790` sends nonzero SocialInternal directly to5d7a70, bypassing space-avatar presence checks. `Chat.OnMessageReceived4629c0` creates/finds the partner tab, pushes the message, then returns before avatar/bubble code for nonzero type. Downstream4784c0 calls4673c0. That export has truncated pseudocode because it misclassifies the GC write barrier at467464, so the hash-bound original-byte listing controls (`work/evidence/chat-format-4673c0-static.asm`). The exact lookup-null block at4674cc passes `data.group` as the nickname and `#FFFFFF` as its color while retaining the message text; it does not load `UNKNOWN_PLAYER`. That literal belongs to the separate returned-author/nickname-null path at4675d1. A later unhooked native test placed PID25748 in Home while the peer fixture remained in Nexus; the incoming private message displayed exact author `Preservation Integration Peer`. Screenshot `runtime-screenshots/home-cross-instance-private-chat.png` has SHA-256 `55e67fb5bb376fa16af93dc85c528a17e84ce18510966832a28e541387376ba7`. No label patch is needed. Notification6's488fe0 callback uses HTTP lookup and LoadSpace; no26 is invented for it.

## Controlled test configuration

The main agent must coordinate builds, state preparation and any restart. A suitable first personal scene is **Home** or **CliffApartment**, both with reviewed empty generic baselines. Use a separate state root containing a consistent account backup and explicit housing grants/binding. Keep its HTTP and every instance on the same host/shared root.

The isolated fixture run used HTTP18082, Nexus28003 and Home28004, after verifying they are unused. HTTP receives `--core-test-profile nonmini-core-v1`. Nexus receives `--nebula-instance --nebula-state-dir <isolated-state> --nebula-instance-id scoped-nexus --nebula-space Nexus --nebula-port 28003 --nebula-core-test-profile nonmini-core-v1`; Home uses id`owner-home`, space`Home`, port28004. Bind/advertise addresses remain explicitly configured; omit Board/Darts flags or set0. Spaces in these prose examples must be separated into normal command arguments.

The backend admin binds `owner-home`/`Home` to the actual native account and grants only chosen source-backed furniture. HTTP must publish current accounts and housing bindings before the instances become eligible. Only the private client metadata is pointed at the isolated HTTP origin by the main agent.

## Remaining native validation sequence

1. Fresh native login to Nexus; choose the owned Home entry in the Personal navigator. Verify allocation names Home and the correct owner instance, then verify owner editor access. HousingReadPreset returns the actual current owner GUID.
2. Place a granted item, rotate it, save/exit the editor, leave to Nexus and enter Home again. Verify persisted pose. Delete it, save, leave/reenter and verify absence. These are local/editor plus HTTP operations; this fixture does not place furniture or mutate the native wallet/layout.
3. Start a distinct fixture with `python tools/social_runtime_peer.py --run --http-port 18082 --account-id preservation-social-visitor --username "Preservation Social Visitor" --allow-source "<actual native username>" --follow-invites --duration 300 --log <new-jsonl>`. Use normal spaces after flag names. It initially joins Nexus. Its default invocation without `--run` opens no socket.
4. Send the fixture a friend request from native UI. It accepts only the configured exact source/platform and sends correlated26. Verify native friend-accepted5 and durable HTTP list refresh. Try private consent/chat while accounts occupy different instances: exact native text `Private native check.` expects `Private peer reply.`. Record native UI and independent fixture hashes separately.
5. With owner in Home and fixture in Nexus, send InviteToJoin6. The fixture performs native-shaped username/platform HTTP lookup, closes its old Mirror connection, requests the exact returned personal scene/owner GUID, and reconnects/spawns/announces in Home. Verify the native visitor/avatar and public/private chat there. Its protocol announcement does not prove a second native UI.
6. Verify visitor cannot save the owner's layout. Separately test current-session rollover and blocked/silenced routing. Do not infer UI success from an HTTP200 or an accepted queue event.

## Remaining source-bound gaps

`HousingFurnishing.SaveAtServer6bdb40` enumerates placed children and calls both NebulaOccupable.Initialize612380 and GenericInteractable.Initialize451060. Counters advance; no deterministic mapping from serialized path IDs to wire IDs is established. Generic94 therefore retains its reviewed static bounds and denies placed-object IDs. Existing8/9/10 arbitration does not prove that different clients assign the same dynamic furniture ID. A future source-bound registration bridge must cover both categories.

No recovered furniture-layout TCP producer establishes live refresh for visitors already present when an owner saves. Owner save/reload and a visitor's fresh load must be validated separately until a concrete refresh flow is recovered. Eleven ordinary interactions across the three mixed scenes remain requirements. Unrecovered notification7/8/9/13 behavior is not synthesized from enum names; deferred minigame paths are separate.

Source/native hashes, exact scene sets and validation scope are in [social-housing-restoration.json](social-housing-restoration.json). No external-host, two-native-client or full-parity claim is made.

## Presence and Home spawn findings

The actual first run exposed missing `instance_id`/`psidglobal` in presence publication. The new production DTO supplies both, with regression checks for live and stopped publications. After rebuilding Linux, invitation lookup and Home join passed. The failed attempts and corrected run remain separate evidence.

Native OnConnected.OnAvatarLoaded5dfdc0 unconditionally starts MoveAvatarDelay5ea260, which uses the loaded ManagerInstance spawn transform. The shipped Home manager references one active spawn with identity ancestors at approximately(-0.132,13.319,-1.470). This is source evidence, not a runtime collision/placement result; no arbitrary server pose override was added. See the hash-bound Home evidence linked by the JSON report.
