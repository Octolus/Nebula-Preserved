# Experimental Rust server

An isolated Rust candidate for the reconstructed HTTP, Mirror and SQLite
services. Source implementations cover the 92 recovered HTTP routes and world
flows outside minigames. Original Windows-client acceptance and full networking
parity remain unproven. Minigames are outside this candidate's current scope.

The existing [Linux deployment](../../deployment/docker/README.md) remains the
default. This candidate has passed bounded headless checks with its existing
Python TLS gateway; original-client and patcher acceptance remain pending. It is
not a drop-in replacement for that stack. It contains no Unity runtime or
original game assets. Players supply their own matching installation.

## Test and run locally

Run from the repository root with Rust **1.90.0** and the platform's native C
build tools. SQLite is compiled from the locked `rusqlite` dependency.

```sh
rustup toolchain install 1.90.0 --profile minimal
cargo +1.90.0 test --locked --manifest-path experimental/rust-server/Cargo.toml
cargo +1.90.0 run --locked --manifest-path experimental/rust-server/Cargo.toml -- serve --bind 127.0.0.1:8088 --state-dir work/rust-server-state --protocol-dir protocol
```

This starts an isolated loopback HTTP listener. Its health response at
`http://127.0.0.1:8088/preservation/health` reports the candidate's limits;
successful HTTP checks do not establish original-client connectivity.

Demand-started world listeners require explicit `--managed-instances`. For a
local test, append `--managed-instances --world-bind 127.0.0.1 --advertised-ip
127.0.0.1 --max-worlds 8 --first-scene-port 28000 --last-scene-port 28031` to the
serve command. `--max-worlds` defaults to eight, is capped at 32, and must fit
the configured scene-port range. The default range matches the existing Python
TLS gateway. Keep one server process per state directory. The `probe` subcommand
exercises isolated JSONL contracts without network listeners.

Public mode requires `--public-access`, provisioned account credentials and an
operator-managed TLS reverse proxy plus the matching world gateway. A routable
advertised address does not establish compatibility with the existing patched
TLS client. Synthetic gateway checks verified certificate-checked TLS, NRT1
forwarding, Mirror bootstrap/session admission and live revocation/cleanup.
Original-client acceptance remains unproven. Keep raw HTTP and Mirror listeners
private behind the configured gateway.

## Optional administration

The management API is disabled unless both `--admin-token-file PATH` and
`--admin-operators-file PATH` are supplied to `serve`. Its separate listener
defaults to `--admin-bind 127.0.0.1:8090` and accepts loopback addresses only.
The API prefix is `/management/v1`; keep this port private.

Supply a regular token file containing 32–512 printable, non-space characters
and an explicit operator configuration. No token or operator is baked into the
image. A role seed file has this shape, with at least one enabled owner:

```json
{"operators":[{"id":"server-owner","role":"owner","enabled":true}]}
```

Append the two file options to the local serve command, for example
`--admin-token-file work/rust-server-secrets/admin-token.txt
--admin-operators-file work/rust-server-secrets/admin-operators.json`.
For a container, mount the files read-only and pass their container paths;
the default Compose command leaves management disabled.

The [operator dashboard](../../admin-panel/README.md) can reach this API from
the same host network or through a secure SSH forward. Configure its
`NEBULA_MANAGEMENT_URL` for that private address and use the same service token.
Dashboard login still needs its normal password records and session key;
the role seed above alone is not a dashboard login file. Existing panel
bootstrap files with `password_scrypt` records can supply the operator list.
Operator deployment, patcher and original-client acceptance remain separate
pending checks.

## Optional Linux container

Build from the repository root. The Dockerfile-specific ignore file allowlists
only this crate's manifests/source/tests, authored protocol files and license
documents. Runtime state, build caches, private evidence and game files are
excluded from the build context.

```sh
docker build -f experimental/rust-server/Dockerfile -t nebula-preserved-rust:candidate .
docker compose -f experimental/rust-server/compose.yaml up -d
docker compose -f experimental/rust-server/compose.yaml logs --tail 80
docker compose -f experimental/rust-server/compose.yaml down
```

This Compose file uses **Linux host networking** so the container's loopback
listener is also host-local. It binds HTTP to `127.0.0.1:8088`, publishes no
ports and leaves managed worlds disabled. It is intended for a Linux Docker
host; Docker Desktop's default networking does not provide this arrangement.
Enable managed worlds only by explicitly appending their options to `command`.
The file does not configure a public gateway or the operator panel.
The image's default command is a private development profile; production
readiness remains unproven.

The container runs as UID/GID **10001**, with a read-only root filesystem,
dropped capabilities and a writable `/tmp` tmpfs. Its separate named volume
holds SQLite and instance state; retain and back up that volume across upgrades.
`down` retains it. Docker sends SIGINT for the candidate's shutdown hook. The
profile restarts after host boot and has a bounded loopback HTTP health check.
Health means the service is alive; it does not assert original-game acceptance.

The build stage uses pinned official Rust 1.90.0 Bookworm; the runtime uses
pinned Debian Bookworm slim with the server binary, protocol files and license
documents. No image is pushed by these instructions or the CI job.

## Evidence and licensing

The [candidate workflow](../../.github/workflows/rust-server.yml) tests the locked
crate, [reference comparisons](parity/README.md) and
[TLS gateway interoperability](interop/README.md) on Windows and Linux using
Rust 1.90.0 and Python 3.12, then checks the restricted container profile.
[Recorded validation](VALIDATION.md) includes exact tested binary hashes and
measured idle footprint. These synthetic checks do not establish native game
acceptance, production readiness or historical server-policy parity.

Original contributions use the root [MIT license](../../LICENSE). The
[dependency inventory](DEPENDENCIES.json) and [retained notices](licenses/README.md)
record the separate upstream terms, including bundled SQLite, cryptographic
libraries and the pinned Rust standard library. The image includes these texts;
refresh them with dependency/toolchain changes. See the repository's
[licensing scope](../../docs/LICENSING.md) for game and distribution boundaries.
