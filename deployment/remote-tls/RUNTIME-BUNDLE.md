# Windows remote bundle contract

Development release inputs for the networking-only client. Native public TLS acceptance remains pending. This document is not a distributable bundle or installation receipt. Preserve the original Steam ownership/startup path and game UI, controls, cursor and rendering.

## Seven remote client artifacts

| Installed path | Bundle operation | Source/input authority |
| --- | --- | --- |
| `GameAssembly.dll` | `delta` | `client-patches/network-only` five-stage composer; all70application API Get sites plus the join gate |
| `Nebula Realms_Data/il2cpp_data/Metadata/global-metadata.dat` | `metadata` | Exact patcher endpoint recipe; remote API becomes fixed local proxy origin |
| `NebulaRegistryBridge.dll` | `owned_file` | Reviewed semantic registry/save snapshot source and exact build |
| `NebulaNetworkBridge.dll` | `owned_file` | Standalone join-queue source, bound to this exact GameAssembly |
| `NebulaPublicAccess.dll` | `owned_file` | Reviewed loopback consumer source with exact sidecar hash compiled in |
| `steam_appid.txt` | `owned_file` | Supported original Steam app-ID input |
| `NebulaRemoteTransport.exe` | `owned_file` | Windows build of `experimental/remote-transport/client` with locked dependencies |

No Automation DLL, InputManager or CharacterEditor target belongs in this profile. Legacy optional keyboard/client-bug/test profiles remain separate. A six-artifact direct plan omits the sidecar and supports unconfigured local forwarding only; configured direct HTTPS is unsupported and fails closed in the stripped Unity client. Public Linux Docker connections require the seven-artifact remote profile.

The game sends API requests to `http://127.0.0.1:38080`. The wrapper requires the configured profile and hash-pinned, owned sidecar readiness. Only the sidecar sends upstream HTTPS with account Authorization, CA and hostname verification, no redirect following, and rejection of every upstream redirect response. It does not send credentials to Unity or put tokens in a URL. The engine WWW request is outside preservation API credential scope and remains original.

Retain original game fingerprints, output/payload/source hashes, sizes, accepted-existing versions, profile checks and the independently published manifest hash. Runtime manifests use `nebula-patch-v1` and `profile: network-only` for the supported original Steam build. Transport is derived from the exact six/seven artifact set; `transport` is release-input plan metadata only. Keep the release provisional until native acceptance. Do not distribute complete game binaries, keys, account credentials, DPAPI files or databases.

## Build order and pin closure

1. Build the Windows sidecar with its checked-in Cargo lock. Record its actual executable SHA-256 and inspect imports. Do not run it standalone: production bootstrap requires the original game parent, owned process/job, readiness event and socket checks.
2. Configure `client-patches/network-only/public-access` with `-DNEBULA_REMOTE_TRANSPORT_SHA256=<exact lowercase executable SHA-256>` and build Release with the reviewed Windows toolchain. This repaired consumer no longer requires the absent managed header/redirect setters. The old `client-patches/public-access` six-file source is preserved only for historical optional/test source locks; its configured public mode is unsupported and it is not this build input. Inspect the same two exports and system dependencies. The reproduced pair is PublicAccess `d0a37cfd1e47e9ec706d92c8b29dd9b29a4cfc9ca5c9891b0f427ba2510a93aa` with sidecar `cfda7d033e93fe78a8150c6a11a6f3b1d66bc5e417f49ee869a0630f855c8420`.
3. Reconstruct the remaining targets with `build_network_client.py`, selecting explicit remote mode and that exact matching sidecar. Source/profile pins are in `network-profile-contract.json`. The old69-site profile and old92c/8d6 PublicAccess binaries are not substitutes. A changed source/toolchain/output requires new review and pins.
4. Use the reviewed Rust bundle builder with the generated seven-artifact input plan. Preserve Steam discovery, transactional backups, update/repoint, restore and recovery. Remote install orders the sidecar before PublicAccess and GameAssembly; restore reverses dependency order. Switching from an older input/test profile requires restoring verified originals first. Later endpoint updates can use verified backup history automatically; explicit originals remain a fallback.
5. Test the complete client with two independently authenticated players: original Steam startup, game-owned proxy readiness, API bootstrap, scene join, chat/social, store/customization, housing and durable restart. Verify invalid certificate/token/current-session rejection and full disconnect cleanup. Offline source/ABI proofs and synthetic transport fixtures do not establish this acceptance.

Use `--locked --offline` only with the reviewed dependency cache populated. Source equality does not guarantee equal binaries across toolchains. A changed sidecar requires rebuilding its pin consumer and final bundle together. No build/import step starts a service or launches a game.

## Linux server release inputs

The Docker package must use the current integrated backend, sanitized protocol data, tools, authentication/gateway modules and verified Unity Linux scene-server executable, managed assembly and build report. Preserve the supervisor's exact binary/report pins. Do not substitute an experimental backend snapshot or unrelated scene binary.

State, operator credentials, account credentials, TLS keys and host configuration live outside release binaries. See the Docker and remote TLS operator instructions for explicit setup. The source repairs are complete for these two identified client gaps; an end-to-end native TLS session is still pending.
