# Recorded headless validation

## Current checkpoint — 2026-10-30

The current candidate passed **103 tests on Windows and 103 on Linux**, including
four new mailbox edge cases. These contract and socket tests remain headless;
original-client/UI and independent-player acceptance are pending.
The separate [world regression record](world-regression-validation.json) records
these counts and pins the two changed source files; it does not refresh the
earlier binary, comparison or gateway records.

The differential, gateway and container records below belong to the **earlier
99-test binaries**, pinned by source and binary hashes. Their 649 comparisons,
33 rejection controls, nine gateway checks and footprint measurements must not
be transferred to the current candidate without rerunning those layers.

## Recorded 99-test binaries

Recorded 2026-10-30 using Rust 1.90.0. The machine-readable
[validation record](headless-validation.json) pins the crate source digest and
each tested binary. This is evidence for the reconstructed preservation backend;
complete historical-server equivalence and original-game acceptance remain
unproven.

| Check | Executed result |
| --- | --- |
| Rust contracts and real sockets, Windows GNU | 99 passed, no failures or skips |
| Rust contracts and real sockets, Linux | 99 passed, no failures or skips |
| Authored Python reference versus Windows executable | 649 matched cases |
| Authored Python reference versus Linux release executable | 649 matched cases |
| Authored Python reference versus binary extracted from the recorded Docker image | 649 matched cases |
| Comparator rejection controls | 22 baseline/fixture and 11 management controls passed |
| Existing TLS gateway with Windows executable | Nine checks passed |
| Existing TLS gateway with recorded Docker executable | Nine checks passed |
| Restricted Linux image | Nonroot startup, health check and graceful exit passed |

The 649 cases comprise 436 baseline, 76 configured mutation, 134 management and
three mandatory Unicode-version cases. They include 481 exact game HTTP
comparisons, complete typed SQLite checkpoints, process reopen and unchanged-state
checks. Only explicitly documented clock fields and correlated management UUIDs
are normalized. The detailed [parity reports](parity/README.md) identify exercised
branches and remaining differential-test gaps. A framing test does not prove a
successful gameplay flow.

The Rust tests separately exercise bounded Telepathy sockets, Mirror framing and
spawn layouts, account isolation, durable character/settings state, resource
selection authority, social state, transactional purchases and housing, management
permissions, managed world startup and concurrent two-part apartment saves. One
saturation test starts 70 first-part requests and verifies that a counterpart can
still complete exactly one housing commit. Python-derived wire and registry
vectors retain their source hashes.

The TLS tests run the actual Rust CLI with the existing Python gateway. They
verify certificate identity and ALPN, exact NRT1 admission, Ready/AddPlayer/spawn,
authenticated presence, forged-GUID rejection, live credential revocation and
denial after revocation. The
[Windows report](interop/synthetic-interop-report.json) and
[Linux Docker report](interop/synthetic-linux-interop-report.json) retain sanitized
source and binary hashes. Both owned processes exited and generated private keys
were deleted. No desktop, game client or original game assets were used.

## Container footprint

The recorded Linux image is **33,264,619 bytes** including the binary, protocol
metadata, Debian runtime and license notices. One idle startup sample measured
**7,488 KiB process RSS**. This is not a load test or a multiplayer capacity claim,
and does not include the separate TLS gateway or dashboard.

The smoke test used UID/GID 10001, no network interface beyond loopback, a
read-only root filesystem, dropped capabilities, `no-new-privileges`, and writable
state/tmp tmpfs mounts. The HTTP health command passed and SIGINT shutdown exited
with status zero. The supplied Compose profile instead retains state in its own
named volume and restarts after host boot. Container recreation with a retained
volume remains a separate deployment acceptance check for this candidate.

## Reproduce and interpret

Follow the [build/run instructions](README.md),
[differential harness](parity/README.md) and
[gateway harness](interop/README.md). The candidate workflow runs these layers
on Windows and Linux, builds an explicit probe executable, and checks the
restricted container. Its Windows runner uses MSVC; the locally executed Windows
result above uses GNU. Hosted CI execution is not claimed by this local record.

The Rust core serves HTTP, SQLite state and Mirror worlds directly, without a
running Unity or Python backend. Public TLS currently uses the existing separate
Python gateway. This candidate remains isolated from the default deployment.

Still open:

- Original-client load, reconnect, customization, stores, social/invites,
  apartments and independent remote-peer acceptance with the final patch bundle.
- Unrecovered server emission rules for animation-layer opcode 93 and
  instance-closing opcode 96; receiver layouts alone do not establish these rules.
- Differential branches listed in the reports, abrupt-crash/load testing and
  candidate deployment acceptance. Implemented unit coverage and reference
  comparisons have different scopes.
- Minigames, deliberately excluded from this candidate.

The [world contract inventory](src/world/PARITY.md) records those boundaries.
Health responses continue to report `game_ready=false` and networking parity as
unproven. No synthetic result is promoted to an original-game pass.
