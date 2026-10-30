# Rust world engine scope and evidence

This is a native Rust port of the reconstructed preservation instance, using
`NebulaInstanceServer.cs`, `NebulaWorldState.cs`, `NebulaInteractionRegistry.cs`,
`NebulaSocialState.cs`, the animation/spawn/command helpers, and the vendored
Mirror 66 message layouts. It runs no Python proxy, Unity process, scene, or
client. It does not establish equivalence to the unavailable commercial server.

## Incoming opcode inventory

| Opcode | Result |
| --- | --- |
| 0 | Clientbound connected reply; reject incoming |
| 1 | Validate current session, allocation, owned netId, username/platform; announce and seed remotes |
| 2 | Validate finite owned pose and quaternion; retain and relay pose |
| 3 | Visible-remote animation query and post-avatar-load boat/wardrobe replay |
| 4 | Translate validated animation netId sentinel/enums/count into reply 5 |
| 5 | Clientbound animation reply; reject incoming |
| 6 | Visible-remote companion query, reply 17 |
| 7 | Unused legacy clientbound companion enum; reject incoming |
| 8, 9, 10 | Legacy occupancy query/acquire/release or trusted per-client semantic mapping; no raw fallback after opcode 97 |
| 11, 12 | Public/private typing with current moderation and consent checks |
| 13 | Public or authorized private chat; cross-instance durable short-lived relay |
| 14 | Clientbound entity retirement; reject incoming |
| 15, 17 | Companion/locomotion mutation through shared HTTP resource authority, entitlement/asset/lease/CAS/replay validation; broadcast only after commit |
| 16 | Visible-remote locomotion query, reply 15 |
| 18 | Post-HTTP preference publication for source-supported keys 0,1,2,3,4,15,21 |
| 19 | Correlated private-chat 0, friendship 1, and space invitation 6; S2C schema differs from C2S |
| 20 | Visible-remote pose query |
| 21 | Durable reciprocal friendship/favorite removal with friend event |
| 22, 23, 24, 25 | Post-HTTP silence/block publication; authoritative DB mutation must already match |
| 26 | Correlated private-chat/friend acceptance 0/1; gift 3/4 acknowledgement; informational 5 acknowledgement; game types rejected |
| 27, 28 | Clientbound notification/relationship values; reject incoming |
| 29 | Fresh HTTP wardrobe lease, retained editing ghost and deferred remote delivery |
| 30 | Bound day/night publication and late-join replay |
| 31 | Verified-scene boat tokens, duplicate suppression, post-avatar replay and delayed entity reseed after exit |
| 32–43 | Board minigames excluded; reject incoming |
| 44 | Verified LeafPark coffee receipt claim; immutable DB receipt, exactly-once handoff retirement and replies 44/45 |
| 45 | Clientbound coffee one-way reply; reject incoming |
| 46 | Oktoberfest receipt transition retained, but no shipped active inventory authorizes it |
| 47 | Clientbound Oktoberfest one-way reply; reject incoming |
| 48–50 | Pinball minigame excluded; reject incoming |
| 51–63 | Pool minigame excluded; reject incoming |
| 64–79 | Bowling minigame excluded; reject incoming |
| 80–91 | Darts minigame excluded; reject incoming |
| 92 | Animator parameters with float/int/bool/trigger type validation |
| 93 | Clientbound animation-layer receiver; reject incoming: no recovered C2S emitter |
| 94 | Verified scene generic bool/extension relay/history, or trusted semantic namespace remapping; deferred minigame/separate-protocol classifications denied |
| 95 | Recognize validated game-decline envelope, reject uncorrelated unsupported game invitation; no claimed implementation |
| 96 | Clientbound instance-closing receiver; reject incoming: no recovered C2S emitter |
| 97 | Preservation semantic registry extension: bounded ordered base64url chunks, trusted descriptors, namespace collision checks, owner-save rebind, visitor reload on epoch change |
| Any other integer | Audit unsupported opcode and reject; no passthrough |

`InviteToJoin` notification 6 is intentionally accepted through the recovered
HTTP username/platform lookup and `LoadSpace` flow, not an invented opcode 26
type-6 acknowledgment. The existing client evidence is recorded in
[`notification-contracts.md`](../../../../docs/research/notification-contracts.md).

## Mirror message/command inventory

Incoming messages: Ready, AddPlayer, NetworkPing, Command and global
`NebulaMessage`. Ready/AddPlayer admit a local object without conferring an
account identity. Every account-affecting operation rechecks the latest DB
session, exact allocation, revocation, ban and maintenance policy. Idle authority
is rechecked on ticks. Other message IDs and trailing bytes are rejected.

Outgoing messages: ObjectSpawnStarted, exact PlayerAssetId Spawn payload,
ObjectSpawnFinished, ObjectDestroy, EntityState, Rpc, NetworkPong and encrypted
`NebulaMessage`. Speed uses component 1, dirty mask 1 and a finite float. Component
0 supports the exact native signatures for nullable client-to-server transform,
teleport, teleport with rotation and the legacy teleport-and-rotate alias. Sync
uses unreliable RPCs; teleports use reliable RPCs. Commands require the owned
netId and reject malformed nullable flags, invalid quaternions and trailing
payloads. Unknown component/hash pairs are audited and rejected.

## Remaining evidence limits

- No native client/UI runs are claimed by the synthetic engine tests.
- The underlying preservation source itself calls its networking parity
  unproven. Typed command coverage is not commercial-server policy recovery.
- Opcode 93 receiver fields are known (`guid#layerName#Int32Weight`), but its
  server emission policy is unknown. Opcode 96 receiver fields are known
  (`unused#instanceId`), but its original owner-disconnect/closing trigger and
  timing are unknown. Neither is invented from the existence of a receiver.
- Rapid-boat exit has no recovered native report. Boat exit reseeding is the
  preservation source's explicit replacement policy. Current consumable use
  counts/removal are not reconstructed for late joiners; no prop snapshots are
  fabricated.
- Static legacy generic IDs in mixed or unknown scenes remain closed; opted-in
  clients need a trusted descriptor. Raw occupancy IDs remain the preservation
  source's legacy policy. No scene discovery or client-supplied trust exists.
- Minigame game types, game invitation metadata/declines and server-only
  minigame outputs are intentionally excluded.
- Asset entitlement/availability remains the shared service's authority.
  Resource selection rejects if its real listener owner/heartbeat lease is absent.

The engine returns bounded actions (8,192 entries and 8 MiB per operation), uses
a bounded metadata audit queue, and publishes presence/avatars/poses only through
the host's explicit listener state. Transport owns the actual bound listener and
status heartbeat; the engine does not claim a listening socket on its own.

## Cross-instance social mailbox correction

The post-snapshot regression pass corrected a Rust-port defect: chat admission
already accepted up to 4,096 UTF-16 code units, but mailbox delivery counted
UTF-8 bytes and reused an 8 KiB small-request reader. Valid Chinese, emoji and
JSON-escaped messages could therefore echo locally while silently disappearing
for a player in another instance. The relay now uses the preserved C# mailbox's
32 KiB envelope cap and the same UTF-16 text limit on admission and consumption.

Social files are staged, flushed and published through an atomic no-replace
hard link in the same directory. A receiver claims the completed message before
reading it, validates its event filename, identities, kind, timing and payload,
and consumes it at most once. The mailbox applies the same 512-message pending
backpressure as the existing C# implementation. This requires a filesystem that
supports same-volume hard links (the supported NTFS and Linux Docker state
volumes do); failure does not fall back to publishing partial JSON.

Four focused unit tests cover malformed/oversized envelopes, UTF-16 boundaries,
immutable publication with concurrent readers, single consumption and full
mailbox refusal. The world-engine cross-instance test additionally sends Chinese,
emoji and escaped-control messages at the native text limit through encrypted
Mirror messages and verifies exactly one remote delivery. These are synthetic
contract and concurrency checks, not native game acceptance or historical-server
policy recovery. The earlier validation records remain evidence for the exact
source and binaries pinned in those records.

Recorded 2026-10-30: the complete Rust test suite passed **103 tests on Windows
GNU and 103 on Linux**, with no failures or skips, using Rust 1.90.0. The Linux
run used a network-disabled, read-only-root Docker container with writable
dedicated build/fixture/temp mounts; no desktop or native game was exercised.
