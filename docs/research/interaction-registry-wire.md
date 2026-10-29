> Historical research: this file records an earlier investigation, not current feature acceptance. The root [PROGRESS report](../PROGRESS.md) is authoritative. Local evidence and extracted game code are intentionally omitted. See [research index](README.md).

# Semantic interaction registry wire v1

The production bridge is fail-closed. Legacy profiles keep their prior behavior, while the explicit `nonmini-semantic-v1` process profile marks every authenticated peer bridge-required before its first opcode 97. A bridge-required peer never falls back to raw numeric IDs, including when the native hook fails to load.

## C2S 97

`97#guid#seq#partIndex#partCount#base64urlChunk#platform`

`partIndex` is zero-based and `partCount` is 1 through 256. The canonical UTF-8 document is split into contiguous byte slices of at most 4096 decoded bytes; each slice is independently base64url encoded with RFC 4648 URL-safe alphabet and no padding. Parts must arrive contiguously, without duplicates or gaps, within ten seconds. Reassembly is capped at 1 MiB, and the embedded JSON sequence must equal the outer sequence. This remains safely below the shipped Telepathy 16,384-byte packet ceiling. Canonical JSON property order is:

`v, source, scene, seq, entries, ground_sig`

`source` is `initial`, `load`, or `save`. `initial` contains the complete static registry and an empty ground signature. `load` contains the complete durable furniture registry for owners and visitors. `save` is a candidate post-save map and waits for the backend's authoritative durable layout.

Each entry is ordered:

`kind, send_id, receive_id, anchor, path, class, slot, ground_index, item_id`

The two IDs are intentionally distinct. Outgoing C2S 8/9/10 uses the component-assigned counter ID. Incoming S2C 9/10 indexes the current dense occupables list. Native `RemoveOccupable` removes list elements without renumbering component IDs, so delete/save/readd can make `send_id != receive_id`. Generic entries require equality because opcode 94 resolves assigned IDs rather than the dense occupables list.

For static entries, `anchor` is the exact top-root name after stripping only a trailing Unity `(Clone)`. It must match exactly one active scene root; missing or duplicate roots fail the whole commit. `path` is relative to and excludes that anchor. For furniture, `anchor` is empty and `path` is relative to and excludes the placed ground root (an interaction on that root is `[]`). `slot` is the zero-based full `m_Component` index. Static entries use `ground_index=-1` and an empty item ID. Furniture uses the compact persisted ground-array index and exact housing item ID.

Ground signature entries are ordered `item_id,index,tx,ty,tz,r`. Transform values are typed IEEE 754 float32 round-trip numbers with negative zero normalized to positive zero. The server compares typed values and order; it does not trust a client JSON digest.

## Authority and epochs

The backend atomically publishes `instance-interactions.json` from reviewed static and furniture manifests plus the current durable database layout. An unresolved furniture prefab denies the whole instance registry. Complete maps are compared all-or-nothing, including deferred minigame members, namespace collisions, kinds, paths, classes, slots, and furniture identities.

A save candidate freezes furniture interaction immediately and waits up to ten seconds for the published signature to match. A layout epoch change clears retained semantic state. The committing owner's pending map can then be accepted. If backend publication wins the race, the authenticated owner receives the same bounded rebind grace; stale visitors are disconnected so normal HTTP layout loading and a fresh registry occur. No guessed migration is attempted.

Up to 64 early opcode 8/94 packets are queued. Opcode 9/10 fails closed until both static and furniture namespaces are ready. Stale queued numeric IDs are discarded when a complete trusted map commits, so they cannot poison registration. Queue release and snapshots occur only after readiness.

## Translation

Incoming packets resolve `send_id` to a trusted semantic key. Outgoing packets resolve that key to each recipient's `receive_id`. Accepted 9, 10, and 94 delivery includes the sender. Deferred keys and wrong extension arity are denied. Legacy 9/10/94 broadcasts are filtered away from opted-in peers.

Native `NebulaSeat.Interact` disables the local collider and starts its seat animation immediately after sending opcode 9, before any possible server rejection. The native consumers expose no proven local rollback. Any failed semantic opcode 9 from an authenticated opted-in peer therefore disconnects that claimant so reconnect reloads authoritative state; occupied conflicts retain the typed `registry_occupable_claim_conflict` journal reason. This also covers not-ready, pending-save, stale, unbound, malformed, and authorization failures after identity binding. Opcode 8 remains a normal non-mutating held/free query. This is an explicit preservation safety policy and a less seamless UX than a future source-proven client rollback.

The optional S2C acknowledgment is `97#guid#seq#1#accepted` or `97#guid#seq#0#reason`. Native v1 does not depend on parsing it; the server owns queue and snapshot release.

The `nonmini-semantic-v1` validation scope admits only a fresh, complete backend-authored descriptor. The three mixed scenes include their deferred minigame keys for all-or-nothing mapping but deny those keys at relay. This implementation does not claim full readiness or set `game_ready`, `protocol_complete`, or networking parity true.
