> Historical research: this file records an earlier investigation, not current feature acceptance. The root [PROGRESS report](../PROGRESS.md) is authoritative. Local evidence and extracted game code are intentionally omitted. See [research index](README.md).

# Shared Linux host network configuration

The intended topology is one Linux host running the HTTP adapter and one or more Unity/Mirror instance processes. Every patched client uses that host's HTTP endpoint and receives that same host's concrete IPv4 address plus the selected instance's TCP port. All server processes use the same local state directory. A public advertised address does not relocate status files or cause the HTTP backend to connect to a remote registry.

The original addressing/profile assessment at **2026-10-28T19:50:05Z** used static review and offline checks, without starting listeners or a game during that work. Later controlled local Windows execution has occurred; its separate follow-up is below. `game_ready` and `protocol_complete` remain false in generated instance status; the HTTP health response also remains `game_ready=false`. Test eligibility is a separate field.

## Controlled runtime follow-up

<!-- runtime-followup:start -->
The [current runtime checkpoint](README.md#omitted-local-evidence), recorded at
**2026-10-28T22:05:28.367063+00:00** and bound here as SHA-256 `2616f7f0b09cf12d6b3d64959121a2c7fb3f9bd71318257c01e7ef316adaf5f5`, contains
56 evidence files. Actual local Windows HTTP/Mirror listeners and
connections are observed. The native client loads Nexus, renders the protocol
fixture's remote avatar and completes a public-chat round trip with that second
account. This is not a two-native-client result.

The canonical Linux dedicated-server build and an isolated WSL HTTP/Mirror
protocol fixture pass. Native Linux connection is
`true` and
native-to-fixture Linux public chat is
`true`.
The fresh native Linux-backed run separately checks saved outfit, Music and
wallet/ownership. Remote deployment, firewall/NAT behavior and public/private
external reachability remain unproven.

The current blocker is **core_flows_passed_remaining_nonmini_and_shared_host_validation**: The bounded Nexus core flows pass. Remote shared-host deployment, a second real native client and remaining non-mini features are still pending. Cause: A target Linux host/SSH alias has not been supplied. Other spaces, all social/housing UI branches, mixed-scene runtime IDs and exact visual morph reapplication require further validation; full allocation remains closed outside the explicit Nexus test profile. Observation: Named preset save/list/load request, walking, local purchase and equip/save passed. Fresh Linux login restored the red jacket, Music0.9,475 crystals/200NP and owned-offer status; public chat passed both directions with a distinct protocol account. The private Windows client is left open in Nexus.

Current network-relevant milestones include
`mirror_listener_bound=true`,
`native_world_loaded=true` and
`two_account_chat_proven=true`. Full
readiness and parity remain false.
<!-- runtime-followup:end -->

## Configuration contract

| Component | Argument | Default | Meaning |
| --- | --- | --- | --- |
| HTTP adapter | `--bind` | `127.0.0.1` | Local IPv4 to listen on; `0.0.0.0` selects all IPv4 interfaces. |
| HTTP adapter | `--advertise-ip` | `127.0.0.1` | Exact instance IPv4 admitted by the same-host allocator. It does not rewrite the patched client's HTTP URL. |
| HTTP adapter | `--port` | `8080` | HTTP listen port, integer 1–65535. |
| HTTP adapter | `--state-dir` | `work/server-state` | Common server state directory. |
| HTTP adapter | `--listen` | absent | Existing explicit listener opt-in. Address flags alone do not start a listener. |
| HTTP adapter | `--core-test-profile` | absent | Only `nexus-core-v1` is recognized. Accepts a matching Nexus test candidate, without declaring full readiness. |
| Unity instance | `--nebula-bind` | `127.0.0.1` | Local Mirror/Telepathy IPv4 to listen on; `0.0.0.0` selects all IPv4 interfaces. |
| Unity instance | `--nebula-advertise-ip` | `127.0.0.1` | Concrete client-facing IPv4 written to instance status. Must match the HTTP allocator configuration. |
| Unity instance | `--nebula-port` | `28000` | Mirror/Telepathy TCP listen port, integer 1–65535. |
| Unity instance | `--nebula-state-dir` | required | Same common directory as the HTTP adapter. |
| Unity instance | `--nebula-instance` | absent | Existing explicit instance opt-in. Address flags alone do not activate it. |
| Unity instance | `--nebula-core-test-profile` | absent | Only `nexus-core-v1` is recognized; requires exact `Nexus` and zero Board/Darts tables. |

`--nebula-instance-id` remains a path-safe unique identifier, and `--nebula-space` selects the scene. Instances on the same host need distinct IDs and listen ports. Existing probe/instance mutual exclusion is preserved. Parent-owned deployment templates and client endpoint patching supply the actual host address later.

Both implementations accept canonical four-part decimal IPv4 literals. They reject DNS names, URLs, embedded ports, IPv6, legacy short/integer/hex forms, leading-zero forms, whitespace, the 0/8 range and first octets 224–255. `0.0.0.0` is the sole exception and is valid only for listening. Private or public concrete IPv4 addresses are allowed; validation does not prove that an address belongs to the machine, that a port is available, or that clients can reach it. No address/port probing is performed. Descriptor ports must be exact JSON integers; booleans, fractions and strings are rejected.

For a host with a public NAT address, the listen address can be `0.0.0.0` while the advertised address is the concrete public address that clients use. The HTTP adapter's `--advertise-ip` and every instance's `--nebula-advertise-ip` must agree. Binding directly to a public address requires that address to exist locally; this source revision does not create network interfaces or port forwarding.

## Allocation and local files

The allocator reads `instances/<instance_id>/instance-status.json` under the common directory, with the legacy root `instance-status.json` fallback retained. It does not fetch status over HTTP/TCP. Shared account, relation, notification, receipt and event handoffs remain at the common root; per-instance status, ownership locks, presence, avatar state and pose cache remain under the instance directory.

Status retains format version 1 and adds `bind`; `ip` carries the advertised address and `port` carries the instance's TCP port. Older descriptors without `bind` remain structurally supported. The admitted destination must match the configured concrete advertised IPv4 exactly. A descriptor cannot select a different public host, a hostname, wildcard address or arbitrary URL. Duplicate instance IDs/endpoints remain ambiguous and are excluded.

Normal allocation preserves the existing readiness conditions: fresh heartbeat aged 0–15 seconds, exact `listening=true`, exact `protocol_complete=true`, valid instance/scene/count fields, and `game_ready=true` when that field exists. Legacy descriptors that omit `game_ready` retain the prior compatibility behavior. Current producers explicitly include `game_ready=false` and `protocol_complete=false`, so normal allocation remains closed. Least-player count then instance ID remains the authored selection policy.

The only additional admission path requires the named `nexus-core-v1` profile on **both** components. Its descriptor must have exact `readiness_scope="nexus-core-v1"`, `core_test_eligible=true`, `listener_bound=true`, `psidglobal="Nexus"`, integer zero `board_tables` and `darts_tables`, exact false `game_ready` and `protocol_complete`, and `networking_parity="unproven"`. All existing freshness, host, identifier, count, port and duplicate checks still apply. Missing/mismatched profiles, other scenes or any enabled Board/Darts tables are rejected. This is a finite reviewed test capability, with no general skip-checks option. The instance rejects invalid profile/scene/table combinations before requesting a listener.

The transport's inherited `Active` property still measures listener-thread liveness. A separate volatile `Listening` flag is set only after `TcpListener.Start` succeeds, and cleared on stop and in the listener's `finally` block. `TelepathyTransport.ServerListening` exposes this read-only signal. The instance publishes a listening descriptor only while its own active transport has that actual-bound signal; a later signal loss publishes stopped status and empty live state. This establishes local bind completion in the authored code, not public reachability or successful client interoperability. As with any heartbeat registry, a crash can leave the last descriptor apparently fresh until its 15-second expiry.

## Pinned Mirror source delta

Mirror remains v66.0.9, commit `4d0cd1054a9011ee4492f91ed4bd16c671fea470`. Two pinned source files differ. `Runtime/Transports/Telepathy/Telepathy/Server.cs` defaults `Server.BindAddress` to IPv4 loopback. `Start` snapshots that setting before its listener thread starts, validates IPv4/port, and passes the snapshot to `Listen`. `new TcpListener(bindAddress, port)` replaces upstream `TcpListener.Create(port)`. The volatile actual-bound flag described above is the only other behavior added. `Runtime/Transports/Telepathy/TelepathyTransport.cs` adds its read-only accessor. The instance component sets the bind value before `NetworkServer.Listen`; each deployed instance is a separate process. Telepathy framing, queues, send/receive loops and Mirror wire serializers are unchanged. The project Server.cs also lacks the upstream UTF-8 BOM, a pre-existing encoding difference from the prior loopback modification.

Upstream SHA256: `ec513d43b1a2274464e17eb282fc8b6983339d5d4465026903ec90f48061dcf7`.

Project Server.cs SHA256: `b8d9c4f95695c8c9905399749e8726a8a342ee7be7aa9d78d9f4c0053ab43695`.

Transport SHA256: upstream `d358b21c173162bbacbd9c3ef69185968f3072209de414e81101e03c148492a0`; project `5bb320e981e472f95d8bfed00ebf7d7102b9c31d1399db7aacf0ac1c42308baa`.

All 245 recorded upstream/project source pairs were rehashed; exactly these two pairs differ. `mirror-server/provenance.json` records their hashes. The coordinated Windows compile passed at `2026-10-28T19:48:17Z`, with all 14 recorded compiled-source hashes matching at that compile. Managed assembly SHA256: `37cc28cc8d56dd48ddfba1e778d5f908df97201329fbee30f1ff28366616c4ec`. `mirror-server/build-validation.json` is the canonical Windows report. Its no-listener/no-client flags describe only that compile run. The separate Linux build, WSL protocol fixture and fresh native Linux-backed Nexus flow pass; remote reachability remains unproven.

## Authentication and verification boundary

The existing local preservation account/session policy remains in place. Application GUID binding uses the current account snapshot and matching instance allocation; this revision adds no Steam ticket verification or original-service identity assurance. Existing business handlers, notification acknowledgement import/export and background state refresh remain integrated.

The parent-owned offline run at `2026-10-28T20:07:54Z` historically passed **120 backend unit tests**, including 10 allocation, 6 network-configuration and 6 scoped-profile tests. Those counts describe that prior socket-forbidden scope, not a fresh claim about the current working tree. The current parent-owned `offline-validation.json` is a pointer without a reciprocal hash, avoiding a report cycle. Later integration establishes local Windows networking, a WSL fixture and native Linux-backed outfit/settings/wallet readbacks plus two-account public chat. Two native clients and external reachability remain unproven. The per-flow audit is in [core-test-readiness.md](core-test-readiness.md); Linux evidence is in [the canonical build](README.md#omitted-local-evidence), [WSL fixture report](README.md#omitted-local-evidence) and [native Linux report](README.md#omitted-local-evidence).
