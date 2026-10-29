> Historical research: this file records an earlier investigation, not current feature acceptance. The root [PROGRESS report](../PROGRESS.md) is authoritative. Local evidence and extracted game code are intentionally omitted. See [research index](README.md).

# Local core-runtime peer

`tools/core_runtime_peer.py` is a narrow integration peer for explicitly enabled local Nexus checks. It uses the authored replacement account ID `preservation-integration-peer`; it is not a Steam account, Steam-ticket substitute, or original-service identity.

The default mode is an offline dry-run. It derives and checks the pinned Mirror message IDs, exercises synthetic Telepathy/Mirror/Spawn/AES/announce/chat packets in memory, prints a JSON plan, and exits without creating a socket. Network mode requires the explicit `--run` flag, an explicit new log path, and remains hard-coded to IPv4 loopback `127.0.0.1`.

The original implementation was checked offline. A later parent-controlled integration run loaded the native world and completed native → peer → native public chat. The peer log `work/integration-state/peer-20261028-2020.jsonl` records `exchange_complete=true`; the native UI reply is retained in [public-chat-reply.png](README.md#omitted-local-evidence). This establishes that bounded native/fixture exchange, not two fully native clients or overall game readiness. The optional pose extension below was verified in memory without opening sockets during its implementation.

## Implemented finite flow

1. Send the recovered encrypted HTTP GET envelope for `N2UserExist` with the fixture account and `StandaloneWindows` trailer. Require its exact seven-field existing-account response.
2. Send `ChannelGUIDServlet` with a fixed lowercase SHA-256 request hash, require `true#`, and locally derive the same 32-character session GUID as `backend/wire.py`.
3. Send `N2LoadSpace` with the literal `Login` sentinel and exact six request fields. Require `{guid}#false#false`.
4. Poll `N2SpaceLoading` until it returns the recovered six-field ready envelope. Reject any scene other than exact `Nexus`, any address other than `127.0.0.1`, and any noncanonical port.
5. Connect to that allocated loopback TCP port. Send a Telepathy frame containing timestamp-batched `Mirror.ReadyMessage` and `Mirror.AddPlayerMessage`.
6. Parse the server's known pinned Mirror messages. The local `SpawnMessage` must be owner/local, scene ID zero, asset GUID `86041873-b099-ede4-687c-67606e379683`, and carry the exact 42-byte initial state before it is accepted.
7. Use the spawn's authoritative `netId` to send AES application C2S1 as `1#netId#guid#username#1#StandaloneWindows`.
8. Only when `--position X Y Z` is supplied, send one C2S2 owned pose immediately after C2S1. It uses the peer's own spawned `netId`, the requested coordinates and identity rotation. Without the option, the packet sequence is unchanged.
9. Observe S2C1 remote joins. Send one same-instance public C2S13 greeting using `[guid,Public,-1,message,0]` plus the global platform trailer. If another account sends public S2C13, send one authored acknowledgement. Own server echoes do not trigger a reply loop.
10. Send standard Mirror pings during a bounded 1–300 second run and close when the duration expires or any protocol boundary fails.

This covers fixture spawn/announce, optional one-time fixture placement and same-instance public chat. It does not simulate native walking, avatar assembly, wardrobe, items, shops, housing, private social policy, other scenes or minigames. A protocol pose update is not evidence of native CharacterController movement.

## Optional owned fixture placement

`--position X Y Z` accepts exactly three finite coordinates representable as Unity float32. NaN, infinities and values outside that range are rejected before network mode begins. The helper constructs:

[Code/listing block omitted from the public research archive.]

The option sends one normal encrypted `NebulaMessage` after the peer announces. No position is sent before an authoritative owner/local spawn, and repeated announce calls do not resend it. The existing server binds field zero to that connection's owned netId and reads the JSON from field one. This places only the fixture avatar; it never names or moves the native player's netId. Identity rotation and instant placement are authored fixture behavior.

The first fixture used the default origin while the native user was near `(67,19.31047,-24)`, placing the fixture outside the camera view. Those observed coordinates can be supplied explicitly for a later visibility check. They are not baked into the tool or applied by default.

## Exact wire implementation

- HTTP: `GET /{route}?data={urlencoded Base64}`. Plaintext is `#`-delimited and ends in `#StandaloneWindows`. AES is the shared backend wire implementation: SHA-1 of `[cipher-material-omitted]`, first 16 bytes, AES-128-ECB, PKCS7, UTF-8.
- Telepathy: four-byte big-endian positive payload length, bounded to the pinned 16 KiB maximum.
- Mirror batch: little-endian IEEE-754 double timestamp, followed by packed messages without per-message lengths.
- Mirror message: little-endian 16-bit `GetStableHashCode(full type name) & 0xffff`, followed by the exact generated field serializer.
- Mirror string: little-endian 16-bit UTF-8 byte count plus one; zero is null.
- Byte segment: little-endian 32-bit byte count plus one; zero is null.
- Spawn: `uint32 netId`, two one-byte Booleans, `uint64 sceneId`, .NET GUID bytes, Vector3, Quaternion, Vector3, then the sized payload.
- `NebulaMessage`: one Mirror string containing the Base64 AES ciphertext.

The parser has exact consumers for the 16 currently relevant pinned message types: Nebula, Ready, NotReady, AddPlayer, Scene, Command, RPC, Spawn, ChangeOwner, spawn-start, spawn-finish, destroy, hide, entity-state, ping, and pong. Since Mirror batches do not carry per-message boundaries, an unknown message cannot be skipped safely. The peer hashes/logs the remaining batch bytes, closes, and reports failure instead of guessing a length.

## Structured logging

`--run` mode writes newline-delimited JSON to a caller-selected path opened with exclusive creation. It records HTTP route/status/size; allocation endpoint; Mirror type/ID/decoded structural fields; spawn payload size/hash; announce state; join identity hashes; public-message size/hash; completion flags; and bounded failure reasons. With explicit placement, one `owned_position` event records the fixture netId and finite x/y/z values.

It does not record HTTP ciphertext, decrypted session-bearing requests, raw session GUIDs, raw remote account names, or public chat text. The fixture account ID and authored protocol messages are not treated as Steam identity.

## Authorized local usage

Dry-run, which opens no sockets:

[Code/listing block omitted from the public research archive.]

Only after the parent-controlled HTTP and instance processes have both been explicitly enabled with the bilateral `nexus-core-v1` profile, a local integration run can use:

[Code/listing block omitted from the public research archive.]

For a separate near-native fixture visibility check, use a fresh log path and explicitly requested coordinates:

[Code/listing block omitted from the public research archive.]

The peer itself starts no listener and cannot enable either server component. The HTTP adapter still needs `--core-test-profile nexus-core-v1`; the instance still needs `--nebula-core-test-profile nexus-core-v1`, exact Nexus, zero Board tables, zero Darts tables, and its explicit instance activation flag. Full readiness and parity flags remain false.

## Offline verification

The completed checks were execution-free with respect to networking:

- Python compilation passed.
- Default dry-run completed with `socket.socket` and `socket.create_connection` patched to raise.
- Stable IDs matched the retained candidates: Nebula 58609, Ready 40252, AddPlayer 13085, Spawn 16484, spawn-start 59786, and spawn-finish 34417.
- AES round-trip, Telepathy length, Mirror string, synthetic 42-byte local Spawn, authoritative-netId C2S1, remote S2C1, public S2C13 receive, and one-shot reply passed in memory.
- Optional pose tests decode the exact encrypted C2S2 netId/JSON/platform shape, identity quaternion, announce-before-pose ordering, no pre-spawn update and no duplicate update. Invalid nonfinite/out-of-float32 coordinates and malformed netIds are rejected.
- Both default and positioned dry-runs passed with `socket.socket` and `socket.create_connection` forbidden. The default still emits only the original announce packet in the synthetic local-spawn test.
- The pose extension itself has not been exercised over a live connection during this implementation. The prior bounded public-chat run is recorded separately above.

## Evidence identities

- `backend/wire.py`: `53aa05c27f6ae64adeb5ff2e9b9ad57c4d92c82a7701887c38129c8a7e62302f`
- `backend/server.py`: `174482cdd6c339798c2464abd8c50ea02caa6ca39dea729c45b1028ba30c932f`
- `backend/service.py`: `2a282906497f7c5b0916767500b0f47a348c18f3a75367395add25a7c884a96c`
- `protocol/bootstrap-response-contracts.md`: `6ac4f6f249741514b1d28f9c78e8983b81905ad63a5bf20560574de1412e1cf7`
- `protocol/tcp-contracts.json`: `36bcf6d0caf8407e4cf69ea9e5634de29f48aae7a5fb6e675597be56e38a7136`
- `protocol/mirror-message-id-candidates.json`: `35af8bd7b0a94d287dc9faf6fc04e26e84f5013832e6879692d195af74b73a27`
- `Mirror/Runtime/Messages.cs`: `45467e31f4d001552deddbc21c793eb48196e5dd6766db1982f081cec1c81852`
- `Mirror/Runtime/MessagePacking.cs`: `fbfa8278e1453e976f397f36b060d71e820ea6badecb624c64d7f9064a429bd1`
- `Mirror/Runtime/Batching/Batcher.cs`: `9b36403083abd6f3de749dad2b86e9281d8308dd9523a5debf1115a3ef081594`
- `Mirror/Runtime/NetworkWriterExtensions.cs`: `4dbf55c98e613afe50814bc2e15aa902959e75d37c51ed2550c55d22b28c4293`
- `Telepathy/ThreadFunctions.cs`: `4a53fb10d4860a4a1e7b44ae0e03eca5e0e9cfae7a1b9d1b7e5c4e3f86406525`
- `Preservation/NebulaInstanceServer.cs`: `8c70ed0b9fe8844258256115c867993ce7dd2fffba3cf246d57cd0daf53f14fe`
- `Preservation/NebulaApplicationCrypto.cs`: `b5926d0caac85ccd6e80db60183acaee6712e4babca0352ada56abbd253df882`

The retained exchange log SHA256 is `94b72d96c0ee195367d799ea92ce1cc0dc0cdcbacb49d98473680ab8d8012443`; the native public-chat screenshot SHA256 is `bafb1dd6c36229bfb8de70dd3e8d7d94a67f40bd700674a4ae9747d36ae2118d`.

These hashes bind this report to its reviewed sources and bounded runtime evidence. Source/build matches alone do not establish native interoperability.

## Remaining limits

- Local services, a native client and one native/fixture public-chat exchange have run. Two fully native clients, private chat, customization and purchases are separate milestones.
- The optional one-time position packet is a fixture placement tool, not a native movement or collision test.
- The Python peer does not instantiate Unity objects or render an avatar. It only exercises the server's raw Mirror/application contracts.
- The successful peer exchange validates this narrow replacement path, not original server behavior, shared-host deployment, Linux reachability, full networking parity or game readiness.
- The authored fixture login policy has no Steam-ticket verification. It must never be described as a real Steam identity.
- Unknown Mirror messages fail closed because their lengths are not recoverable from the batch envelope.
