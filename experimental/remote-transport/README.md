# Experimental remote transport v9

This is the source-only, undeployed remote-transport experiment. It tunnels the
game's TCP scene connections through a TLS sidecar and an operator gateway. It
does not replace the original Steam initialization and does not implement Valve
Steam-ticket validation.

## Status and security boundary

- Activation is **not ready**.
- The Rust sidecar and Python gateway were built by their owning stage, but the
  shipped game target was not executed and no listener was started for this
  curated copy.
- The sidecar requires normal TLS chain, hostname and time validation and a
  per-account preservation credential. The v2 profile uses the Windows trusted
  ROOT store without a certificate picker. The original v1 profile retains its
  explicitly pinned private CA for private deployments.
- Those controls authenticate the preservation service; they are not proof of
  ownership of a Steam account.
- Multi-client reconnect, credential/account binding, certificate operations,
  and end-to-end runtime acceptance remain deferred.
- The gateway imports compatible `public_access`, `allocation`, and `wire`
  modules from the preservation backend. It is not a standalone server.

The example configurations contain placeholders only. Never put credentials in
process arguments, committed config, or logs. If selecting a private CA, store
its certificate outside the repository and verify the operator's digest.

## Automatic public certificate trust

Use the [v2 system profile](config/remote-game-system.conf.example) for a server
with a certificate trusted by Windows. It contains exactly seven fields and no
CA path or fingerprint. The launcher writes this profile automatically. A public
IP requires a certificate with that exact IP in its subject alternative names;
a DNS certificate requires its matching DNS name.

System mode reads the Windows ROOT store without modifying it or honoring
`SSL_CERT_FILE`/`SSL_CERT_DIR`. It filters unusable roots, and both the API and
game-gateway clients share the resulting rustls verifier. The game gateway must
negotiate `nebula-game/1` before an account credential is sent. Redirects remain
disabled. Expired, untrusted and wrong-host certificates fail; there is no
automatic fallback to a private certificate or invalid-certificate bypass.

The [v1 private-CA profile](config/remote-game.conf.example) is still supported
with its exact eight fields. Versions and trust fields cannot be mixed. Earlier
sidecars reject v2 profiles, so distribute the rebuilt sidecar with its matching
hash-pinned native wrapper and candidate bundle, never as an isolated replacement.

## Source inspection and build

These commands inspect or build source; they do not launch a gateway or game:

```text
cd experimental/remote-transport/client
cargo build --release --locked
cargo test --locked --lib
python -m py_compile ../server/remote_gateway.py
```

Build the player executable on Windows. The library tests also run on Linux,
covering the same parser and certificate negative controls; loading the Windows
ROOT store and running the game-owned sidecar remain Windows operations. The
recorded candidate passed 13 Windows tests and 11 Linux library tests.

Building may download the crates pinned by `Cargo.lock`. Review
`THIRD_PARTY_NOTICES.md` and the upstream license files before distributing a
binary. Do not install the service unit or start the gateway until the operator
has completed the deferred acceptance and certificate/DNS setup.

The historical evidence receipt is preserved under `evidence/`. It records
static/build evidence only and explicitly sets `activation_ready` to false.
The current [TLS validation record](client/tls-validation.json) separately pins
the new candidate sources/binaries and headless checks. Neither record claims
native multiplayer acceptance.
