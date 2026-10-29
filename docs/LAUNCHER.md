# Windows launcher

Double-click the release executable, or run `nebula-preservation-patcher.exe gui`. The launcher leaves the mouse and the game's UI/input settings alone.

1. **Find your game.** Steam libraries are searched automatically. Use **Find game** to search again or **Browse…** to choose the installed **Nebula Realms.exe**. If several supported copies exist, choose the one you want. Other executables, incomplete installations and unsupported builds are refused.
2. **Connect to your server.** Enter the IPv4 address or complete HTTPS address supplied by the server owner. A bare IPv4 address uses HTTPS on port 8444. Choose your own account credential file. Open **Certificate settings** if the server certificate and fingerprint are not already supplied by the player release. Confirm the fingerprint with the server owner, then click **Save connection**. Each player needs their own account file; it is protected with Windows CurrentUser DPAPI and restricted permissions.
3. **Start the game.** The next-step message explains any missing requirement. Start becomes available after the game and connection checks pass and the launcher has a reviewed bundle pin. It checks the exact executable, Steam build, patch profile, receipt history, backups, helper outputs and metadata again before patching and opening the game. Named progress stages show the work in the background.

Returning players have their saved server restored and checked automatically.
Use **Check server** to retry after an outage. The check uses the saved profile;
it does not import a new account. The main screen keeps certificate settings and
technical details expandable. A development build without a reviewed patch bundle
explains why Start is unavailable.

The launcher uses themed native Windows controls, Segoe UI typography, resizable
sections and per-monitor display scaling. Smaller windows scroll; Tab follows the
visual order and brings focused controls into view. Errors open the technical
details and offer a recovery step. It does not capture the pointer or change the
game's controls. The DPI handling follows Microsoft's
[per-monitor guidance](https://learn.microsoft.com/en-us/windows/win32/hidpi/wm-dpichanged).

The probe is read-only and deliberately does not send an account token. Success establishes certificate-verified backend reachability, not server-side account authentication, multiplayer or world loading. The game performs login. A successful process start is reported as a process start.

Existing saved profiles must match the selected server. Editing the server address invalidates the previous connection check. Under **Certificate settings**, **Forget connection** asks before removing only this Windows user's saved connection files. It preserves the server account and patch backups. Import the new server's credential and CA afterward. Certificate preflight rejects a wrong fingerprint before account provisioning begins. If import is interrupted, forget the incomplete connection and retry with the trusted files. Store the source credential securely outside the game/repository as a recovery secret; never send it to another player.

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

The current patcher suite has 37 tests, including launch prerequisites, stale
connection invalidation, layout overlap/bounds, 100–300% scaling geometry, scroll
reachability, saved-origin parsing and read-only certificate preflight. Windows
release inspection checks the embedded native-control/DPI manifest, normal-user
execution and absence of input-capture imports. These headless checks do not
replace a visual and keyboard/screen-reader pass on an unlocked Windows desktop.
The [recorded checks](../patcher/launcher-ui-validation.json) pin the tested source
and local preview binary; that preview contains no reviewed game bundle.
