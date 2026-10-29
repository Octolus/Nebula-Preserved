# Windows launcher

Double-click the release executable, or run `nebula-preservation-patcher.exe gui`. The launcher leaves the mouse and the game's UI/input settings alone.

1. Enter the server IPv4 address or complete HTTPS origin. A bare address uses HTTPS on port 8444. HTTP, credentials in URLs and ambiguous origins are refused.
2. The launcher checks Steam registry paths, Steam's library list and bounded common Steam folders on drives C–Z. Broken libraries do not hide valid installations elsewhere. If several supported copies exist, select one using **Browse executable**. If none is found, select the installed **Nebula Realms.exe**. Other executables, incomplete installations and unsupported Steam builds are refused.
3. On the first connection, select your own operator-issued account credential file, the operator's DER CA certificate, and its trusted SHA256 fingerprint. Check the fingerprint through a trusted channel. A prepared portable build can include the public CA and fingerprint. Click **Import connection**. Credentials are protected with Windows CurrentUser DPAPI and restricted file permissions; Steam ownership is still required. Each player needs their own credential. Never distribute an account credential inside the launcher.
4. Click **Start the game**. Verification runs in the background. It checks the manifest, exact executable, Steam build (where its manifest exists), network-only profile, transaction history, pristine backups, installed helper outputs and regenerated metadata. It verifies the TLS profile and server certificate/hostname against the pinned CA, probes the existing HTTP protocol, applies the verified transaction and launches the exact executable from its game folder.

The probe is read-only and deliberately does not send an account token. Success establishes certificate-verified backend reachability, not server-side account authentication, multiplayer or world loading. The game performs login. A successful process start is reported as a process start.

Existing saved profiles must match the selected server. **Reset connection** asks before removing only this Windows user's saved connection files. It preserves the server account and patch backups. Import the new server's credential and CA afterward. If import is interrupted, reset and retry with the trusted files. Store the source credential securely outside the game/repository as a recovery secret; never send it to another player.

Close the game before patching, restoring, changing accounts or changing servers. The launcher refuses concurrent operations, unknown modifications, mixed optional UI/input patches, damaged backups and unfinished transactions. Use CLI `recover`/`restore` when instructed. It never silently repairs an unknown installation or discards backups.

## Build a portable release

The normal GUI requires a **frozen seven-artifact remote network-only bundle** whose native acceptance is complete. A development executable without a compiled bundle pin can open the UI, discover games and provision a connection, but cannot start a game. Developers can explicitly run `gui --allow-provisional` for authorized native acceptance; the window identifies itself as **DEVELOPMENT provisional acceptance**. This flag changes only the provisional status gate, retains all byte/profile/TLS checks, is never enabled by defaults or embedded configuration, and must never be presented as release acceptance. The developer CLI retains its explicit provisional acceptance workflow.

Build on Windows with private inputs outside the repository:

```powershell
$env:NEBULA_DEFAULT_SERVER = 'https://play.example.org:8444'
$env:NEBULA_BUNDLE_SHA256 = 'REVIEWED_MANIFEST_SHA256'
$env:NEBULA_CA_SHA256 = 'TRUSTED_CA_DER_SHA256'
$env:NEBULA_EMBED_BUNDLE = 'PRIVATE_REVIEWED_BUNDLE_DIRECTORY'
$env:NEBULA_EMBED_CA = 'PRIVATE_PUBLIC_CA_DER_FILE'
cargo build --locked --release --manifest-path patcher/Cargo.toml
```

Embedding is optional. The build checks the manifest pin, frozen remote network-only profile, artifact allowlist and every embedded payload size/hash. It embeds manifest/payload release material and the public CA, never game originals or player credentials. Runtime extraction uses a restricted cache under `%LOCALAPPDATA%/NebulaPreservationLauncher`, keyed by pins. Existing cache files must match compiled bytes. The executable is portable; no Rust installation or extra launcher files are needed. The original Steam game is always required.

Without embedding, place the reviewed `bundle/` beside the executable and optionally `operator-ca.der`. The same compiled manifest pin and launch checks apply. Changing servers requires explicitly importing matching trusted connection material.

Default server and CA material are public distribution configuration. Keep operator passwords, SSH keys, admin session keys and account credentials outside source. Clear the build environment variables after producing the intended artifact. Generic CI builds have no deployment-specific server, CA or reviewed bundle pin unless a separate reviewed release process supplies them.

## Validation status

Windows unit tests cover parser limits, corrupt Steam libraries, address normalization, profile boundaries, output pins, rollback and backup/receipt tampering. They never run fake fixture executables. Compilation and protocol probes do not establish native multiplayer acceptance. Record original-client remote TLS/login/world/social/customization checks before freezing or distributing a launch-enabled bundle.
