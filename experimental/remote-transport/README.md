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
- The design requires normal TLS hostname validation, an operator CA digest,
  and a per-account preservation credential.
- Those controls authenticate the preservation service; they are not proof of
  ownership of a Steam account.
- Multi-client reconnect, credential/account binding, certificate operations,
  and end-to-end runtime acceptance remain deferred.
- The gateway imports compatible `public_access`, `allocation`, and `wire`
  modules from the preservation backend. It is not a standalone server.

The example configuration contains placeholders only. Never put credentials in
process arguments, committed config, or logs. Store an operator CA file outside
the repository and restrict its permissions.

## Source inspection and build

These commands inspect or build source; they do not launch a gateway or game:

```text
cd experimental/remote-transport/client
cargo build --release --locked
python -m py_compile ../server/remote_gateway.py
```

Building may download the crates pinned by `Cargo.lock`. Review
`THIRD_PARTY_NOTICES.md` and the upstream license files before distributing a
binary. Do not install the service unit or start the gateway until the operator
has completed the deferred acceptance and certificate/DNS setup.

The historical evidence receipt is preserved under `evidence/`. It records
static/build evidence only and explicitly sets `activation_ready` to false.
