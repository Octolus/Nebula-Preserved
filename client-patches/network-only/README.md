# Networking-only preservation client

Development source for Steam app 919290, build 11018722. Public native acceptance is pending. This profile preserves the shipped controls, cursor, menus, rendering, InputManager and CharacterEditor assets. It installs and launches nothing. Optional keyboard, free-mouse, cosmetic fixes and test profiles remain separate.

Five patch stages repair network state: consume the final wardrobe response element; send the rapid-boat exit state after the original exit; collect the semantic interaction registry and exact housing-save snapshot; save and hydrate existing settings; wrap all 70 application API request sites and gate remote-player queue processing until original registration exists. The engine WWW request remains unchanged and receives no preservation credential. The central account coroutine at `0x6183f0`, used by Steam user-info producers, is included.

`NebulaNetworkBridge.dll` links only the reviewed join-queue gate. Its existing single export is named `NebulaAutomation_JoinQueueReady` for ABI compatibility. It contains no automation IPC, movement override, keyboard helper, economy telemetry, test identity or automation pump. A direct import supplies the gate; only an exact success result permits the unchanged original queue drain.

Original client bugs outside networking remain, including Neck Thin editor loading, eye lifetime and empty notification text. Keep the existing backend female pectoral save compensation for the original writer. Do not add a server Neck Thin inversion.

## Reconstruct the patch targets

Use locally owned pristine game files, Python with `pefile` and `capstone`, and the reviewed Windows x64 MinGW toolchain. Build the PublicAccess source in this directory with CMake Release. Supply its required `NEBULA_REMOTE_TRANSPORT_SHA256` from `network-profile-contract.json`; rebuilding the sidecar requires a matching wrapper and release manifest. `public-access/README.md` describes the stripped Unity consumer and its offline regression.

```text
python build_network_client.py --originals ORIGINAL_GAME_FOLDER --output NEW_OUTPUT --cc PATH_TO_GCC --cxx PATH_TO_GXX --registry-bridge REVIEWED_REGISTRY_DLL --public-access REVIEWED_PUBLIC_ACCESS_DLL
python verify_network_client.py --originals ORIGINAL_GAME_FOLDER --build NEW_OUTPUT --output NEW_CHECKS_JSON
```

Direct mode emits six artifact inputs: GameAssembly, endpoint metadata, NetworkBridge, RegistryBridge, PublicAccess and `steam_appid.txt`. It supports unconfigured local API forwarding only. Configured direct HTTPS is unsupported in this stripped Unity build and fails closed. It is not a public server connection mode.

For a Linux Docker host, use `--transport remote --remote-transport REVIEWED_TLS_SIDECAR`. The seven-artifact plan adds the exact matching sidecar. The Rust patcher configures the HTTPS origin, account authorization and transport profile; public certificates use Windows system trust automatically, while the advanced private-CA option keeps an explicit DER digest. The game endpoint is the fixed `http://127.0.0.1:38080` sidecar origin. The wrapper admits requests only after validating the profile and the hash-pinned, owned sidecar's readiness. The sidecar validates the upstream certificate chain and hostname, supplies Authorization, follows no redirects and rejects every upstream redirect response. No account token is placed in a URL or passed to Unity. See the separate server/authentication instructions for account setup.

The endpoint metadata recipe runs in the Rust patcher using the supplied server configuration. InputManager and CharacterEditor are absent from both plans. The generated `release-input-network-only.PROVISIONAL.json` is an input to the reviewed Rust bundle builder, not a distributable release or runtime acceptance proof. Its `transport` field selects the plan; runtime manifests use `profile: network-only` and derive transport from the six/seven artifact set.

Switching from an older keyboard/test profile requires restoring its verified originals first so omitted input changes cannot persist. Subsequent endpoint changes use verified backups automatically, with an explicit pristine originals directory as a fallback. Retain pristine inputs and backups.

Publish authored sources, manifests, project-owned helpers and delta bundles only. Keep complete game files, local plans/build receipts, scratch outputs, account databases, credentials, raw decompilation and test evidence outside the repository. This source candidate has not been installed, run in a game or published.
