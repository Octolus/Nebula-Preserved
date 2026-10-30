# Windows launcher

Double-click the release executable, or run `nebula-preservation-patcher.exe gui`. The launcher leaves the mouse and the game's UI/input settings alone.

1. **Find your game.** Steam libraries are searched automatically. Use **Find game** to search again or **Browse…** to choose the installed **Nebula Realms.exe**. If several supported copies exist, choose the one you want. Other executables, incomplete installations and unsupported builds are refused.
2. **Connect to your server.** Enter the IPv4 address or complete HTTPS address supplied by the server owner. A bare IPv4 address uses HTTPS on port 8444. Choose your own account credential file and click **Save connection**. Publicly trusted HTTPS certificates are checked automatically against Windows trusted roots: no certificate file or fingerprint is needed. Each player needs their own account file; it is protected with Windows CurrentUser DPAPI and restricted permissions.
3. **Start the game.** The next-step message explains any missing requirement. Start becomes available after the game and connection checks pass and the launcher has a reviewed bundle pin. It checks the exact executable, Steam build, patch profile, receipt history, backups, helper outputs and metadata again before patching and opening the game. Named progress stages show the work in the background.

Returning players have their saved server restored and checked automatically.

The Windows launcher uses temporary game sessions. Before a session it recovers
an interrupted patch/restore and restores the previous patch history, then applies
the currently pinned bundle. A separate hidden helper owns the game process and
restores the backed-up originals after the game exits. Closing the launcher window
does not stop that helper or the game. Files are never restored underneath a
running game. If Windows shuts down or both processes are forcibly killed, the
next launcher start recovers the installation before another patch is applied.

Backups are kept under `.nebula-preservation/backups` inside the game directory.
The original `Nebula Realms.exe` is checked, not patched. Existing files that are
changed are copied and hash-verified before replacement; new helper files are
removed during restoration. Backups remain after restoration. Do not delete this
folder. Recovery refuses unexpected modifications, broken backup chains and
unsupported Steam updates instead of overwriting newer or unrecognized files.
An interrupted restoration can be resumed. Manual recovery remains available:
close the game and run `nebula-preservation-patcher.exe recover` when an unfinished
transaction is reported, or `nebula-preservation-patcher.exe restore` to undo an
installed patch. `restore` undoes one recorded generation; the launcher's automatic
preparation walks the complete verified history.

Discovery identifies the actual game directory: slash, case and dot aliases from
Steam's registry/library entries count as one installation. Separate real copies
still require a choice. Missing directories and linked/reparse paths are rejected.
Use **Check server** to retry after an outage. The check uses the saved profile;
it does not import a new account. The main screen keeps certificate settings and
technical details expandable. A development build without a reviewed patch bundle
explains why Start is unavailable.

**Private-CA servers:** open **Certificate settings**, turn off **Use Windows
certificate trust**, and supply the operator's DER certificate and its trusted
SHA256 fingerprint. A prepared release can include that public CA and fingerprint.
Confirm a private CA fingerprint with the server owner. An invalid, expired or
mismatched certificate is refused; there is no accept-any-certificate setting.

**Existing accounts after a TLS upgrade:** if the same server now uses a publicly
trusted certificate, open **Certificate settings**, turn on **Use Windows
certificate trust**, then click **Save connection** (or **Use automatic TLS**).
Confirm the explicit trust change. The launcher verifies the server first, then
replaces only the TLS profile. Your saved account and DPAPI token remain intact;
you do not need to import the account file again. Failed verification retains the
old profile. This migration is never an automatic fallback after a TLS failure.

The launcher uses themed native Windows controls, Segoe UI typography, resizable
sections and per-monitor display scaling. Smaller windows scroll; Tab follows the
visual order and brings focused controls into view. Errors open the technical
details and offer a recovery step. It does not capture the pointer or change the
game's controls. The DPI handling follows Microsoft's
[per-monitor guidance](https://learn.microsoft.com/en-us/windows/win32/hidpi/wm-dpichanged).

The probe is read-only and deliberately does not send an account token. Success establishes certificate-verified backend reachability, not server-side account authentication, multiplayer or world loading. The game performs login. A successful process start is reported as a process start.

Existing saved profiles must match the selected server. Editing the server address invalidates the previous connection check. Under **Certificate settings**, **Forget connection** asks before removing only this Windows user's saved connection files. It preserves the server account and patch backups. Import the new server's credential afterward, plus its CA only for private-CA servers. TLS/backend preflight runs before account provisioning begins. If import is interrupted, forget the incomplete connection and retry with the trusted files. Store the source credential securely outside the game/repository as a recovery secret; never send it to another player.

These read-only and trust-migration CLI commands also work without opening a GUI:

```powershell
nebula-preservation-patcher.exe check-server --server https://play.example.org:8444
nebula-preservation-patcher.exe migrate-system-trust --server https://play.example.org:8444
```

`check-server` needs no account or game installation and writes no profile. For a
private CA, supply both `--ca-file operator-ca.der` and `--ca-sha256 TRUSTED_SHA256`.
`configure-remote --server ...` also defaults to Windows certificate trust when
neither CA argument is supplied. Never use the dashboard owner password as a
player credential.

Close the game before patching, restoring, changing accounts or changing servers. The launcher refuses concurrent operations, unknown modifications, mixed optional UI/input patches, damaged backups and unfinished transactions. Use CLI `recover`/`restore` when instructed. It never silently repairs an unknown installation or discards backups.

## Build a portable release

The normal GUI requires a **frozen seven-artifact remote network-only bundle** whose native acceptance is complete. A development executable without a compiled bundle pin can open the UI, discover games and provision a connection, but cannot start a game. Developers can explicitly run `gui --allow-provisional` for authorized native acceptance; the window identifies itself as **DEVELOPMENT provisional acceptance**. This flag changes only the provisional status gate, retains all byte/profile/TLS checks, and must never be presented as release acceptance. Generic and ordinary release builds never enable it by default. The explicit private tester build below is a separate provisional distribution mode. The developer CLI retains its explicit provisional acceptance workflow.

Build on Windows with private inputs outside the repository:

```powershell
$env:NEBULA_DEFAULT_SERVER = 'https://play.example.org:8444'
$env:NEBULA_BUNDLE_SHA256 = 'REVIEWED_MANIFEST_SHA256'
$env:NEBULA_EMBED_BUNDLE = 'PRIVATE_REVIEWED_BUNDLE_DIRECTORY'
cargo build --locked --release --manifest-path patcher/Cargo.toml
```

Public-CA deployments need no CA build variables. For an intentionally pinned
private-CA release, also set `NEBULA_CA_SHA256` and `NEBULA_EMBED_CA` to the
verified public CA fingerprint and DER file. Never embed the CA's private key.

Embedding is optional. The build checks the manifest pin, frozen remote network-only profile, artifact allowlist and every embedded payload size/hash. It embeds manifest/payload release material and the public CA, never game originals or player credentials. Runtime extraction uses a restricted cache under `%LOCALAPPDATA%/NebulaPreservationLauncher`, keyed by pins. Existing cache files must match compiled bytes. The executable is portable; no Rust installation or extra launcher files are needed. The original Steam game is always required.

Without embedding, place the reviewed `bundle/` beside the executable and optionally `operator-ca.der`. The same compiled manifest pin and launch checks apply. Changing servers requires explicitly importing matching trusted connection material.

Default server and CA material are public distribution configuration. Keep operator passwords, SSH keys, admin session keys and account credentials outside source. Clear the build environment variables after producing the intended artifact. Generic CI builds have no deployment-specific server, CA or reviewed bundle pin unless a separate reviewed release process supplies them.

## Validation status

Windows unit tests cover parser limits, corrupt Steam libraries, address normalization, profile boundaries, output pins, rollback and backup/receipt tampering. They never run fake fixture executables. Compilation and protocol probes do not establish native multiplayer acceptance. Record original-client remote TLS/login/world/social/customization checks before freezing or distributing a launch-enabled bundle.

The current patcher suite has 46 Windows tests (42 on Linux), including launch prerequisites, stale
connection invalidation, layout overlap/bounds, 100–300% scaling geometry, scroll
reachability, saved-origin parsing and read-only certificate preflight. Windows
tests also cover native root loading, exact trust profiles, wrong names/IP SANs,
unrelated roots, invalid validity dates, damaged signatures and atomic migration
failure without changing a saved account. They use synthetic public certificates
and a fixed verification time; no private keys or deployment trust are embedded.
Windows release inspection checks the embedded native-control/DPI manifest, normal-user
execution and absence of input-capture imports. These headless checks do not
replace a visual and keyboard/screen-reader pass on an unlocked Windows desktop.
The [recorded checks](../patcher/launcher-ui-validation.json) pin the tested source
and local preview binary; that preview contains no reviewed game bundle.

## Fixed-server community tester build

Operators can explicitly build a compact **TEST BUILD** with a compiled HTTPS
server and the reviewed provisional network-only bundle. It is not a frozen
release or evidence of native gameplay acceptance. Generic CI builds retain
normal release gates and contain no deployment address or player credential.

The tester flow is **find the installed game, then Start**. Steam must be running
and signed in. Start reads Steam's active local Windows account and
automatically creates a new preservation account when
the operator enabled `/preservation/enroll`, protects the unique credential with
Windows CurrentUser DPAPI, applies verified networking patches, and starts the
game. Stored `MostRecent` accounts are never substituted for the active Steam
login. No server address, certificate, account file or Steam ID entry is needed.
Local Steam identity discovery is not Valve ticket or ownership verification;
Steam's original ownership/game initialization remains in place.

A retry key is encrypted and durably saved before enrollment. A lost response
can retry the same account without rotating its credential. In the default
strict enrollment policy, an existing account with a different key requires
operator recovery. An operator may explicitly enable the `trust_claimed_id`
policy to admit another device to the same claimed Steam ID; the server issues
that device its own credential and retains older credentials and player data.
A local Steam ID is a claim that can be spoofed, not ownership verification.
The launcher never replaces an existing profile, accepts an invalid TLS
certificate, or embeds a shared player secret. Switching Steam accounts on the
same Windows user is refused when a saved credential belongs to the earlier account.

Explicit private build inputs (outside the repository):

```powershell
$env:NEBULA_TESTER_BUILD = '1'
$env:NEBULA_TESTER_SERVER = 'https://play.example.org:8444'
$env:NEBULA_BUNDLE_SHA256 = 'REVIEWED_PROVISIONAL_MANIFEST_SHA256'
$env:NEBULA_EMBED_BUNDLE = 'PRIVATE_REVIEWED_BUNDLE_DIRECTORY'
cargo build --locked --release --manifest-path patcher/Cargo.toml
```

The build requires its pinned embedded bundle and system certificate trust;
private-CA embedding is refused in this mode. Remove these build variables when
building ordinary release artifacts. `setup-player` is a hidden headless tester
command for checking automatic setup without starting the game.

The default Windows unit suite has 56 passing tests and two explicitly ignored
live enrollment fixtures. The original opt-in fixture requires an authorized unused
synthetic account, a new isolated `LOCALAPPDATA` directory on the operator's
chosen drive, and private report/server/account environment values. It performs
two enrollment requests to test a lost-response retry, DPAPI persistence and
profile reopen, without opening the game or modifying Steam registry state.

The claimed-ID live fixture uses two isolated Windows profile directories for
the same authorized synthetic identity, performs one new-account request and
one second-device request with another protected key, and checks both local
profiles remain unchanged on reopen. Operator-side authenticated protocol
checks separately establish that both credentials remain accepted. Neither
fixture opens the game or uses a real player's account.
