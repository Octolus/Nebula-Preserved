> Historical research: this file records an earlier investigation, not current feature acceptance. The root [PROGRESS report](../PROGRESS.md) is authoritative. Local evidence and extracted game code are intentionally omitted. See [research index](README.md).

# Root player Mirror command contracts

Static native evidence plus compiled codec implementation. No game, listener or connection was executed.

| Component | Command | Hash (signed Int32) | Channel | Payload |
|---:|---|---:|---:|---|
| 1 | speed | 421014902 | 0 | float32 little endian, exactly4 bytes |
| 0 | transform_sync | -1415757549 | 1 | byte presence flag + optional Vector3; byte flag + optional Quaternion; byte flag + optional Vector3 |
| 0 | teleport | -788685907 | 0 | Vector3 destination, exactly12 bytes |
| 0 | teleport_rotation | -840469116 | 0 | Vector3 destination then Quaternion rotation, exactly28 bytes |
| 0 | obsolete_teleport_rotation | -1564373760 | 0 | Vector3 destination then Quaternion rotation, exactly28 bytes; shares modern two-argument user body |

Channel0 is reliable, channel1 is the historical unreliable path (Telepathy itself uses TCP). Every registered command requires ownership. Function hashes use all32 bits; a modern ushort-hash implementation would mismatch this client.

The native transform command handlers forward the corresponding RPC to observers including the owner; the owner client has its own authority suppression in the transform component. The obsolete teleport-and-rotate command invokes the current two-argument RPC. Initial transform state is only emitted for initial spawn; ordinary transform updates travel through RPC/custom opcode2.

## Observations and replacement policy

- SetSpeed sends a float but its shipped UserCode method is an empty return at sharedRVA0x35a740. InvokeUserCode reads the float and checks type/server state without assigning it. Therefore assigning the accepted value to cached speed and replicating SyncVar is an explicit new local server policy, inferred from the client speed SyncVar consumer, not recovered server behavior.
- Transform command payload/RPC mapping and includeOwner/channel flags are native-derived. The raw replacement caches authoritative pose and forwards the matching RPC rather than running an original server-side interpolation component.
- All commands require a bound ready spawned connection and its own netId. Malformed, extra, nonfinite and degenerate-rotation values are rejected as local validation.
- Prefab component0 is disabled; registration does not prove ordinary gameplay sends its commands. The direct E8 references list has a bounded linear-instruction scope and omits indirect/virtual/inlined calls.
- No additional NetworkIdentity scene-object registry, original scheduling/authority, server physics, anticheat or original speed thresholds are established by these contracts.

The JSON includes exact signatures, string-literal RVAs, method bodies, hashes, verified bounded E8 references and all evidence-file digests. Native pseudocode is not the original C# or the retired server.
