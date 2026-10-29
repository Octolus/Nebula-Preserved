Synthetic Rust / gateway integration test
========================================

This optional developer test runs the Rust preservation server and the unchanged
Python TLS gateway against a new private state directory. It exercises synthetic
protocol acceptance. Native-client compatibility and production readiness remain
unproven. No game client, game assets, browser, desktop API, interactive input, or
unlocked desktop is required. Desktop lock state is neither inspected nor changed.

Install optional test dependencies in your developer environment:

```text
python -m pip install -r requirements-interop.txt
```

These pinned dependencies are for this integration test. They are not runtime
Docker image dependencies. Python 3.12 was used for the recorded run.

Build the Rust candidate separately. This harness never invokes Cargo. Its
`--candidate` must name the compiled `nebula-preserved-server` executable (or the
Windows `.exe`), not a native game client. From a reference repository checkout:

```text
python path/to/run_interop.py --candidate path/to/nebula-preserved-server --work-dir ../private-interop-work
```

The reference repository root is detected by searching the script's parents and
the current working directory's parents. To select it explicitly:

```text
python path/to/run_interop.py --reference path/to/reference-checkout --candidate path/to/nebula-preserved-server --work-dir path/to/private-work
```

`--reference-root` is an alias for `--reference`. The reference must contain
`backend/wire.py`, `backend/public_access.py`, `backend/allocation.py`,
`experimental/remote-transport/server/remote_gateway.py`, and the public
`protocol/` metadata. The harness reads these inputs without modifying them and
records source/protocol/binary hashes. No proprietary asset tree is accessed.

Each run creates a generated subdirectory beneath `--work-dir`. It starts the
candidate with loopback HTTP, managed instances, a single bounded scene port, and
public HTTP access disabled. A known synthetic 17-digit SteamID-shaped fixture is
used only to exercise grammar. It is not proof of Steam ownership.

The test bootstraps that identity over encrypted HTTP, creates a current session,
requests Login/Nexus, and polls the managed allocation. A controlled operator
fixture invokes the preserved public-access migration and issuer against only the
new synthetic database. The account credential remains in memory. A fresh test
CA signs a loopback IP SAN certificate. TLS verifies the CA, hostname/IP identity,
and ALPN before the exact NRT1 port/85-byte authorization exchange.

Nine checks cover HTTP/bootstrap/allocation, salted credential compatibility,
TLS/NRT1 admission, wrong-hostname rejection, Ready/AddPlayer and spawn bytes,
current-GUID opcode 1 and presence, foreign-GUID forgery denial, live credential
revocation teardown, and revoked credential admission denial. A nonzero exit
means a check failed. `report.json` in the run directory contains sanitized
results, relative source hashes, the candidate hash, and cleanup status. Failure
details that could contain paths or host identifiers are omitted from the report.

The Windows gateway bootstrap adapts only `asyncio` signal registration, which
Windows does not implement. It then executes the unchanged gateway CLI using
`runpy.run_path`. Protocol, authentication, identity filters, readiness scans, and
revocation code are unmodified. Windows child processes use `CREATE_NO_WINDOW`.
On other platforms the gateway executes without the signal adaptation.

Owned child processes are terminated on success and failure; generated server
private keys are deleted. Keep the work directory private: its synthetic SQLite
database, certificates, and diagnostic logs are not public test artifacts. Only
the sanitized report is intended to be shareable.

The included `synthetic-interop-report.json` records execution of this portable
harness against the final Windows candidate. All nine checks passed. The tested
binary SHA256 is
`8df20c772bdb8a99afdf261ccf2669f4c1221f18bef09107dcaa871c2e827578`.
The original gateway/backend sources and public protocol tree remained unchanged;
both owned processes exited and the generated private key was deleted. The report
does not claim that a different binary hash has passed. An actual locked-desktop
run was not separately observed; the harness has no desktop dependency.
