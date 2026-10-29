# Provisional preservation client sources

The networking-only development default uses all **70 application API request hooks** and the repaired stripped-Unity loopback consumer. Public native TLS acceptance is pending. Configured direct HTTPS is unsupported; direct six-artifact mode supports unconfigured local forwarding only. Public connections use the explicit seven-artifact remote profile, exact owned proxy, upstream CA/hostname verification and account authorization. Controls, cursor and rendering remain shipped behavior. Current source/build pins are in `network-only/network-profile-contract.json`.

The recommended preservation default is the separate **network-only** profile in
`network-only/`. It preserves shipped input assets, controls, cursor and rendering.
Its direct/TLS release plans contain six/seven artifacts and require the reviewed
explicit Rust `network-only` profile support. Runtime acceptance is pending.

The reconstruction below is retained as a **legacy optional keyboard/client-bug-fix
and testing pipeline**. Its historical profile named `default` means original
cursor only; it also contains keyboard aliases, client bug fixes and passive test
hooks. It is not the networking-only default. Never select it implicitly for
players who want shipped UI and controls. See `network-only/README.md` for the
minimal build, exact source contract and profile-switch restore requirements.

This source reconstructs both client profiles from locally owned, pristine Steam
app 919290 build 11018722 files. It includes the reviewed V9 non-minigame network
adapters and exact source-stage orchestration. Runtime acceptance remains
incomplete. No complete game file, local account, address or credential belongs
in this source tree.

The **default** profile preserves original cursor behavior. The optional
**free-mouse** profile suppresses the three reviewed cursor methods and must be
chosen explicitly. Both preserve controller mappings and use the same V9
networking source. The default remains outside the settings automation
cursor-safety allowlist.

## Maintainer reconstruction

Install `requirements-dev.txt` and use a Windows x64 MinGW toolchain. Supply a
separately reviewed PublicAccess DLL with SHA256
`8d6d812dbff42bd38cd5763dbbb969609125d5540af9a38745b76f2d3f0d79b5`.
This directory retains its locked legacy PublicAccess source; configured
public HTTPS is unsupported by that legacy consumer in the stripped game.
The repaired current default is the separate `network-only/public-access/`
project. Do not substitute its new DLL into legacy plans or the legacy DLL
into current networking-only plans. Both CMake projects require an exact
reviewed sidecar pin; do not invent one.
Different sources or toolchains need fresh output review and explicit pins.

```text
python build_client_targets.py --originals LOCAL_PRISTINE_STEAM_FOLDER --output LOCAL_NEW_PRIVATE_BUILD --cc PATH_TO_GCC --cxx PATH_TO_GXX --public-access REVIEWED_PUBLIC_ACCESS_DLL
python verify_targets.py --targets LOCAL_NEW_PRIVATE_BUILD --originals LOCAL_PRISTINE_STEAM_FOLDER --cxx PATH_TO_GXX --output LOCAL_NEW_CHECK_RECEIPT
```

The new external build contains both GameAssembly profiles, matching helpers,
the input manager and CharacterEditor targets, source-stage evidence and two
provisional bundle plans. It verifies every exact input and intermediate hash.
It never installs, launches a client or changes Steam. Complete target game
files, private build scratch, generated receipts and release-input plans contain
local paths and must remain outside the public repository.

Standalone project-owned helper builds use the same exact source lock and
profile pins. The automation build includes all ten source units, including the
join-queue gate. Its default explicitly rebinds only the GA profile header.
The registry retains its reviewed C++17 flags and preferred image base.

```text
python build_helpers.py --component automation --profile default --cxx PATH_TO_GXX --output LOCAL_NEW_DEFAULT_HELPER
python build_helpers.py --component automation --profile free-mouse --cxx PATH_TO_GXX --output LOCAL_NEW_OPTIONAL_HELPER
python build_helpers.py --component registry --cxx PATH_TO_GXX --output LOCAL_NEW_REGISTRY_HELPER
```

After independent source review, the Rust patcher source's bundle builder can
consume `release-input-default.json`, or the explicitly optional
`release-input-free-mouse.json`. It emits COPY/ADD/ZERO deltas against exact
pristine files and copies project-owned helpers. CharacterEditor canonicalization
also checks decoded node parity.

```text
python PATCHER_SOURCE/tools/build_bundle.py --plan LOCAL_NEW_PRIVATE_BUILD/release-input-default.json --patcher LOCAL_RUST_PATCHER_EXE --output LOCAL_NEW_PROVISIONAL_BUNDLE
```

These eight-artifact plans remain provisional. They use the direct server
profile and do not include a TLS transport sidecar. `--remote-transport` requires
a separately reviewed profile with its sidecar, authentication, CA and gateway
configuration. No remote service or VPS is provisioned by these build scripts.

## Player installation after bundle review

Players need the Rust executable, selected reviewed bundle and its independently
published manifest SHA256. Steam libraries are discovered automatically. Supply
the server origin and advertised IPv4 when patching; no personal server is
compiled into this source reconstruction. Keep the game closed.

```text
nebula-preservation-patcher.exe patch --bundle REVIEWED_BUNDLE --manifest-sha256 PUBLISHED_MANIFEST_SHA256 --server http://SERVER_IPV4:8080 --advertise-ip SERVER_IPV4 --allow-provisional --dry-run
```

Review the dry run before repeating without `--dry-run`. For an installation
managed by the patcher, repeat the same command with the new server or selected
reviewed bundle/profile. The patcher resolves exact pristine inputs from its
verified receipt history and backups automatically. Keep `.nebula-preservation`
and its backups intact; each `restore` returns one captured previous state.

For a reviewed manual overlay or a missing/unverifiable backup chain, retain an
exact pristine source folder and select it explicitly:

```text
nebula-preservation-patcher.exe patch --bundle REVIEWED_BUNDLE --manifest-sha256 PUBLISHED_MANIFEST_SHA256 --server http://SERVER_IPV4:8080 --advertise-ip SERVER_IPV4 --originals LOCAL_PRISTINE_SOURCE_FOLDER --allow-provisional --dry-run
```

Explicit `--originals` takes precedence over automatic backup discovery. Every
source must still match the supported original hash; receipt entries cannot
authorize a different build. Preserve the original executable, GameAssembly,
metadata, input manager and CharacterEditor at their original relative paths.
Unknown or unsupported installed hashes, stale receipts and edited or redirected
backups fail closed.

The patcher never starts or terminates the game or server. Source and offline
reconstruction evidence do not establish successful gameplay or persistence.
