> Historical research: this file records an earlier investigation, not current feature acceptance. The root [PROGRESS report](../PROGRESS.md) is authoritative. Local evidence and extracted game code are intentionally omitted. See [research index](README.md).

# Initial Nexus integration-validation milestone

The original static assessment at **2026-10-28T19:51:04Z** found a contract-supported candidate for controlled Nexus integration. No game, listener, UI, connection or native execution was used during that audit. Those execution flags describe the audit at that timestamp. Later controlled local execution has occurred and is recorded separately below. Minigames are deferred by the user; original service parity remains unproven.

The audit found and corrected one definite native settings mismatch: enum key `NotificationLoginFriend` must save to JSON/storage key `notificationLoginFriend`. The regression exercises native save names, response hydration, database reopen and the legacy wrapper. No additional mandatory Nexus opcode/HTTP handler gap was identified in the listed core flows. Their live ordering and engine behavior still require integration observation.

## Controlled runtime follow-up

<!-- runtime-followup:start -->
The [current runtime checkpoint](README.md#omitted-local-evidence), recorded at
**2026-10-28T22:05:28.367063+00:00** and bound here as SHA-256 `2616f7f0b09cf12d6b3d64959121a2c7fb3f9bd71318257c01e7ef316adaf5f5`, contains
56 evidence files. The private native client now loads Nexus; a
remote protocol-fixture avatar is rendered; one native account and one protocol
fixture complete a public-chat round trip; the body slider responds; and the
named preset is saved, listed and requested for load.

This proves `native_world_loaded=true`,
`native_remote_avatar_rendered=true`,
`two_account_chat_proven=true` and
`native_preset_saved_and_listed=true`.
Additional current milestones are server-observed walking
`true`, male torso
equip/save/fresh-login `true`,
Music persistence `true`
and local purchase `true`.
The walking test uses separate W presses. Held-key control, two native clients
and exact visual morph reapplication after named load remain unproven.

The current blocker is **core_flows_passed_remaining_nonmini_and_shared_host_validation**: The bounded Nexus core flows pass. Remote shared-host deployment, a second real native client and remaining non-mini features are still pending. Cause: A target Linux host/SSH alias has not been supplied. Other spaces, all social/housing UI branches, mixed-scene runtime IDs and exact visual morph reapplication require further validation; full allocation remains closed outside the explicit Nexus test profile. Observation: Named preset save/list/load request, walking, local purchase and equip/save passed. Fresh Linux login restored the red jacket, Music0.9,475 crystals/200NP and owned-offer status; public chat passed both directions with a distinct protocol account. The private Windows client is left open in Nexus.

Native connection to the separate Linux backend is recorded as
`true`;
native-to-fixture Linux public chat is
`true`.
See the separate Linux-native report for outfit, settings, wallet/ownership and
clean shutdown evidence. Remote/public host reachability is unproven.
`game_ready`, `protocol_complete` and original networking parity remain false.
<!-- runtime-followup:end -->

## Admission contract

Normal allocation remains closed for the current producer: `game_ready=false`, `protocol_complete=false`, `networking_parity="unproven"`. A separate finite validation scope is available only when the HTTP adapter is explicitly configured with `--core-test-profile nexus-core-v1` **and** the instance is explicitly configured with `--nebula-core-test-profile nexus-core-v1`.

The instance accepts that profile only for exact scene `Nexus`, integer zero Board tables and integer zero Darts tables. A listening descriptor additionally carries `readiness_scope="nexus-core-v1"`, `core_test_eligible=true` and `listener_bound=true`. The last signal comes from Telepathy's volatile read-only `Listening` flag, which is set only after the OS listener starts and is cleared on stop/finally. It is distinct from the inherited worker-thread `Active` property. No listening descriptor is first published before that signal.

The allocator requires the matching configured profile, exact false full-readiness flags, unproven parity, exact Nexus/table restrictions and exact true eligibility/bound/listening signals. Existing heartbeat freshness, configured advertised-host allowlist, valid IDs/ports/counts and duplicate exclusions remain enforced. The selected account still needs an actual HTTP allocation before its GUID can bind to a Mirror peer. The profile adds no arbitrary skip-checks option, authentication bypass, synthetic allocation or response shortcut.

It is appropriate to call this **eligible for scoped integration validation**. It is not appropriate to call it game-ready or original-network-compatible before the flows are observed. No status flag changes in response to this report automatically start anything.

## Per-flow evidence and limits

| Flow | Implemented/static and offline evidence | Original runtime targets; current progress is above |
| --- | --- | --- |
| Login and allocation | Reviewed Steam-ID/local-session bootstrap handlers; current-session hash export; neutral starter presets. Native `Login` scene sentinel maps explicitly to Nexus. `N2LoadSpace` writes allocation; `N2SpaceLoading` returns fresh descriptor endpoint in native fields2–5. The private native client now completes Login, allocation and loading into Nexus. | Local account-ID trust remains replacement policy; no Steam ticket validation was added. Native-client operation against Linux is separate and unproven. |
| Nexus bundles and bootstrap | Booter level0 contains an enabled active-root ScreenLoader. Scene/logic/bundle closure exists locally. The private native client now resolves and renders Nexus. | Sustained traversal, broader scene coverage and the native-client Linux path. |
| Spawn and local avatar | Ready/add-player/raw spawn precedes application0. Spawn uses the recovered prefab GUID and 42-byte two-component state. The native client renders the protocol fixture as a remote avatar. | Two-native-client simultaneous joins and exact full appearance parity. Raw server identity bookkeeping remains authored compatibility code. |
| Arrival and movement | Six serialized Nexus arrival transforms are recovered. Native `0x5ea260` moves the local root after C2S1. Custom2/20 and root component codecs are implemented and checked offline. Nexus arrival/world rendering is observed. | Sustained CharacterController walking, remote interpolation/speed and disabled NetworkTransform timing. Native speed assignment/replication remains explicit replacement policy. |
| Public and private chat | Recovered Public and SocialInternal shapes are implemented. One native account and one protocol-fixture account now complete a public-chat round trip. | Two-native-client delivery, private tabs and typing. No separate cross-instance global channel was recovered. |
| Customization and item removal | Native appearance schemas and durable preset operations are implemented. The clothing editor opens, body slider responds, and `PreservationTest` is saved, listed and requested for named load. | Exact visual morph reapplication after load, confirmed saved/reloaded appearance, item wear/remove rendering and reconnect persistence. |
| Wardrobe return and remote appearance | HTTP lease/current-session rules and pose cache are implemented. Native wardrobe ghosts receive raw Spawn/Joined before post-build29. Return removes old identities/player-info state then reseeds, with visibility suppression during retirement. | Native end-of-frame destruction across clients and the authored two-server-frame reseed barrier. The barrier has no recovered client acknowledgement and remains a material timing risk. |
| Settings | Native PlayerPrefsJson persistence is implemented with recovered names/types and the notification-key mismatch fixed. The native options menu opens and arrow-focus navigation works. | Actual option effects, save and relogin persistence. `ShowPets`/`PlatformOnly` remain absent from native hydration. |
| Credits/admin and shops | Offline admin, seeded wallets/catalogs and transactional purchase logic remain checked. The native wallet displays 500 crystals and 200 NP. | Resolve the shop's connection problem after HTTP 200, then observe buy response, debit, grant and inventory refresh. No purchase is currently claimed; no real Steam commerce is enabled. |

## Original staging prerequisites and remaining flow sequence

The numbered sequence below is retained as the original static staging plan.
Its login/menu/world/chat portions have since progressed substantially; it is
dated history, not the current blocker list.

1. Rebuild after the final profile/transport source changes and verify the canonical source hashes. A Windows build is sufficient for a local Windows integration test. A successful Windows build does not establish the Linux dedicated-server build; that module/build remains a separate deployment prerequisite.
2. Select a separate complete exact-build client copy containing the reviewed native compatibility candidate and endpoint metadata. Its API origin and instance advertised IPv4 must match the chosen backend configuration. The earlier loopback endpoint specimen alone does not configure a shared Linux host.
3. Choose explicit, distinct listen ports and a common state directory. Enable the named profile on both components only for the intended controlled test. Actual bound status is a local prerequisite; external routability/firewall/NAT remain separate observations.
4. Apply the validated local shop seed to that same state directory and give the intended preservation account an explicit balance for a paid purchase. Starter clothes are automatically granted by login policy; purchase funds are not.
5. Evaluate the flows in order: login/loading → local avatar → walking → second-client visibility/public chat → wardrobe wear/remove/save/return → options save/relogin → server-priced purchase and inventory refresh. Record the first failed transition before widening scope. A single-client success cannot establish multi-client or shared-host reachability.

The definite closed-allocation blocker is addressed by the finite bilateral
profile, without changing parity. The settings-key and cinema bootstrap bugs
are corrected. The later keyboard/input compatibility work allowed the private
client to reach Nexus, so the 20:15 login-menu input blocker remains only in the
dated runtime history. The current blocker is native shop-response rejection
after HTTP 200. Exact visual morph reload, sustained walking, settings
persistence and purchases remain unproven.

## Evidence references

- [Shared host addressing and profile fields](shared-server-networking.md)
- [Modern loading pipeline](world-loading-pipeline.md), [ScreenLoader placement](loader-bootstrap.md), [Nexus arrival points](tcp-world-spawn.md)
- [Application packet ordering](tcp-reconstruction.md), [root Mirror commands](mirror-command-contracts.md), [player prefab](mirror-player-state.json)
- [Avatar parser/fixture checks](README.md#omitted-local-evidence), [default assets](../../protocol/avatar-default-catalog.json), [shop contracts](http-shop.md), [reachable shop seed](local-shop-seeding.md)
- [Canonical Unity compilation](README.md#omitted-local-evidence), [recorded offline validation](README.md#omitted-local-evidence)
- [Current controlled runtime checkpoint](README.md#omitted-local-evidence), [cinema bootstrap correction](cinema-bootstrap-compatibility.json)
- [Canonical Linux build](README.md#omitted-local-evidence), [isolated WSL protocol validation](README.md#omitted-local-evidence)

The parent-owned offline backend run at `2026-10-28T20:07:54Z` historically
passed **120 unit tests**, including the cinema termination regression and six
socket-forbidden scoped-profile tests. It also recorded 133 pure C# checks and
12 avatar fixture/parser checks. Those counts describe that prior scope, not a
fresh claim about the current working tree. The current parent-owned
`offline-validation.json` is linked without a reciprocal hash to avoid a cycle.
Current implementation hashes are bound in the companion JSON; the previous
`backend/state.py` hash remains there as a dated superseded record.
