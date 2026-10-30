# Windows preservation patcher

The Windows GUI and portable release build are documented in [LAUNCHER.md](../docs/LAUNCHER.md). Normal release launching requires a frozen native-accepted remote bundle. The explicit private fixed-server TEST BUILD supports provisional community acceptance with automatic player enrollment, retaining every patch/profile/TLS check; see the tester section in LAUNCHER.md. Explicit `gui --allow-provisional` is available only for developer native acceptance and visibly marks its window as development. CLI patch/restore commands never launch the game.

The GUI guides players through finding the game, saving their server connection
and starting. Saved connections are checked automatically; certificate settings
and technical details expand when needed. Missing requirements and failures
explain the next action. It uses scalable, themed native Windows controls and
background progress without capturing the pointer.

Publicly trusted HTTPS certificates use Windows certificate trust automatically;
players do not choose a certificate file. Pinned private CAs remain an explicit
advanced option. `check-server --server https://play.example.org:8444` is a
read-only TLS/backend check. `migrate-system-trust --server ...` explicitly
upgrades a matching saved account's TLS profile while retaining its DPAPI token.
Certificate identity, dates and chain signatures are always verified.

Rust source for Steam app **919290**, build **11018722**. Windows x64 is the supported patching platform. Steam discovery uses registry and VDF library/app manifests; `--game` selects an explicit installation. Original executable, licensing and ownership initialization are preserved.

Discovery deduplicates by existing directory identity, including Windows volume
and 128-bit file ID. Mixed slash/case/dot spellings cannot create false multiple
copies, while different real directories remain distinct. Canonicalization does
not bypass symlink/reparse checks, and stale manifests without a game directory
are reported as warnings rather than usable installations.

```powershell
cargo build --locked --release
cargo test --locked
```

The CLI stages hash-verified changes, backs up exact previous files, commits helper dependencies before GameAssembly, and retains receipts for restore/recovery. Only explicitly accepted fingerprints are patched. Keep the game closed throughout patching; a process census cannot prevent a user launching it afterward. CLI file commands never start or terminate the game/server; the GUI's explicit Start action launches the verified game after its checks.

Unit tests cover delta parsing, endpoint validation, exact profile admission, rollback/recovery and backup-based updates. Updates can reuse original files from an existing patcher transaction: every required source must be bound by the active receipt and match a compiled supported-original hash. The resolver verifies current installed files, the complete receipt chain and every referenced backup before staging. Missing, edited or redirected files, broken history and repeated transaction IDs are rejected. History traversal stops at 64 transactions; normal receipt size and parser limits also apply.

Players need the executable plus a reviewed bundle and its separately published manifest SHA256. Build outputs and release archives are excluded from this repository. `release-input.template.json` is a developer template, not an installable bundle: replace local input/output paths, verify exact hashes and obtain review before constructing an artifact.

```text
nebula-preservation-patcher.exe patch --bundle bundle --manifest-sha256 PUBLISHED_MANIFEST_SHA256 --server http://SERVER_IPV4:8080 --advertise-ip SERVER_IPV4 --allow-provisional --dry-run
nebula-preservation-patcher.exe restore --game "LOCAL_GAME_FOLDER"
nebula-preservation-patcher.exe recover --game "LOCAL_GAME_FOLDER"
```

Review the dry run and repeat without `--dry-run` only for the intended local installation. For a receipt-managed installation, use the same command to change the server or install a different reviewed bundle/profile; verified transaction backups supply the originals automatically. Keep `.nebula-preservation` and its backups intact. Each `restore` returns one captured previous state, including its prior receipt.

The explicit `network-only` manifest profile installs exactly six artifacts: GameAssembly, metadata, `NebulaNetworkBridge.dll`, `NebulaRegistryBridge.dll`, `NebulaPublicAccess.dll` and `steam_appid.txt`. Its remote form adds `NebulaRemoteTransport.exe` and requires `--remote-transport` together with the configured HTTPS account/trust profile. System trust uses the exact seven-field `nebula-remote-transport-v2` profile with `trust=system`; pinned private CAs retain the exact eight-field v1 profile. Mixed fields, unknown trust values and implicit trust downgrades are refused. The remote mode is derived from the seventh artifact; no separate runtime transport field is accepted. Existing manifests without a profile retain their eight/nine-artifact behavior.

Networking-only installation requires the original `globalgamemanagers` input data and `charactereditor` asset, with no `NebulaAutomation.dll` present. Before crossing between the old optional profile and networking-only, run `restore` repeatedly until there is no active receipt, then inspect the installation. Restore a remote networking-only profile before switching to its six-artifact direct form. An edited or incomplete installation may require Steam's file verification after preserving transaction backups; the patcher refuses to delete unknown files or silently retain optional patches. Direct networking-only may add the remote transport, and normal endpoint updates within a profile still reuse verified backups.

For a reviewed manual overlay or an installation without a complete verified backup chain, provide `--originals "LOCAL_PRISTINE_STEAM_FOLDER"`. That explicit directory takes precedence over automatic backup discovery, and each source still has to match its compiled original hash. It does not authorize an unknown current installation. A new transaction captures the exact accepted manual before-state; an older receipt predating manual changes still refuses an unsafe restore.

`tools/build_bundle.py` produces source-referenced COPY/ADD/ZERO deltas and copies only project-owned helpers. It consumes a locally reviewed input plan and verifies every input pin. `tools/build_editor_candidate.py` canonicalizes the reviewed editor reconstruction with independent UnityPy node parity; complete decoded scratch files are removed. Never upload proprietary inputs, reconstructed complete game files, credentials or generated private receipts.

For a networking-only release input plan, set `"profile": "network-only"` and list exactly those six or seven paths. `release-input.network-only.template.json` is a noninstallable template. Frozen plans require native composition, HTTP hook and matching bridge-composition evidence. Optional editor plans additionally require UnityFS runtime acceptance. Source/profile checks alone never establish native networking acceptance.

Disposable acceptance scripts exercise pristine install, idempotence, restore, recovery and manual overlays. `tools/accept_backup_update.py` reads explicitly selected locally owned originals and writes a new private fixture outside the source, originals and Steam directories. It tests real CLI install, server repoint, target/profile change, three restores without `--originals`, backup/current-file/receipt tampering, redirected backups and explicit-original precedence. It creates deliberately nonexecutable fake helper payloads and invalid game targets; never run or distribute fixture game files. These checks establish file-transaction behavior; game and server acceptance remain separate.

`tools/accept_network_profile.py` tests the six/seven-artifact production builder and CLI against a new private fixture, including endpoint updates, restore boundaries, mixed/missing helpers, stale receipts and tampered backups. Its child process uses an isolated `LOCALAPPDATA` with synthetic protected-token/CA containers. It does not validate DPAPI, TLS certificates, sidecar startup or gameplay, and never runs the fake game files.

**Status:** provisional. The file-transaction checks do not validate a release bundle or shared-host deployment. Final bundle acceptance and public remote/TLS activation remain incomplete. Source dependencies are pinned in Cargo.lock; bundle construction additionally uses Python, UnityPy1.25.4, pefile and capstone as described in `../client-patches/README.md`.

Original public game service host/IP literals in `src/endpoint.rs` are exact-match reconstruction constants from the shipped client, not developer/user network addresses. No personal machine or account configuration is included. Original contributions use the root MIT license; upstream and game-derived materials retain their separate terms. See [licensing scope](../docs/LICENSING.md) and [provenance](../client-patches/PROVENANCE.md).
