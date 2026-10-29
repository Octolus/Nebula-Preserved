# Headless authored-reference parity harness

This harness compares a candidate Rust server with the authored Python preservation backend. Every result states `one_to_one_parity: NOT_PROVEN`. Original-client schemas are static evidence, and original server rules are unavailable.

All writable state, reports, child temporary directories and caches remain below the resolved harness directory on the current filesystem. Traversal and symlinks that escape that directory are rejected. The reference adapter calls the actual `Backend.handle` directly and blocks sockets, name resolution and connection creation. It starts no listener, game, Unity/Terra process, desktop app or remote connection. Each run gets a fresh synthetic database. It never opens the reference deployment's state.

## Run

Use Python 3.12 with the reference backend dependencies available (`aiohttp` and `pycryptodome`). Python 3.12 supplies the Unicode 15.0 properties used by the management reference. From the repository root, enter `experimental/rust-server/parity`; the commands below use that directory as their working directory. Build the candidate using the parent Rust project instructions first.

On Linux:

```sh
export PYTHONDONTWRITEBYTECODE=1
mkdir -p temp
export TEMP="$PWD/temp" TMP="$PWD/temp" TMPDIR="$PWD/temp"
python -B -m unittest test_harness -v
python -B run_parity.py --reference ../../.. --candidate ../target/debug/nebula-preserved-server --candidate-arg probe --name default-run
```

On Windows, use the `.exe` candidate:

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:TEMP = "$PWD/temp"
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Force -Path $env:TEMP | Out-Null

python -B -m unittest test_harness -v
python -B run_parity.py --reference ../../.. --candidate ../target/debug/nebula-preserved-server.exe --candidate-arg probe --name default-run
```

The interpreter may be named `python3.12` on Linux. The optional `--name NAME` must identify a new directory under `runs/`. Existing state directories are refused. For a reference-only run, omit `--candidate` and `--candidate-arg`; observations are `REFERENCE_ONLY`. Missing candidate operations are `NOT_PROVEN`. Failures and reference errors return exit code 1. `--only SUBSTRING` narrows the reported cases but still executes the full setup sequence. Each request has a configurable timeout of at most 60 seconds.

Use the committed `coverage-manifest.json` to reproduce the reported comparison: the runner verifies every reference source hash before opening a probe. `build_manifest.py --reference ../../..` is an optional static inventory generator that opens no database; review source changes before regenerating evidence. Its optional `--research-protocol` argument accepts a separately reviewed metadata directory containing source names, evidence hashes, opcode names and native method metadata. Without that directory, regenerated enum names are explicitly unresolved; it does not reproduce the committed static extraction evidence. No original game assets are required.

## Artifacts

* `coverage-manifest.json`: every Service route, matching reference handler location and hash, static client evidence, existing reference test citations, all original application enum values, the authored extension, five inbound registrations and five command hashes. All unexercised contracts remain `NOT_PROVEN`.
* `case-corpus.json`: complete synthetic ordered requests, expected reference status assertions and state checkpoints.
* `normalization.json`: exact table/column whitelist for seven proven wall-clock fields. Zero, null and numeric type remain observable. No HTTP fields, UUIDs, item/session IDs, reply JSON order or schemas are normalized.
* `probe_contract.md`: candidate JSONL interface and full typed snapshot shape.
* `runs/NAME/summary.json`: reference/candidate/harness/corpus/normalization digests, per-case status, per-route case evidence and unexercised contracts.
* `reference-policy-inventory.json`: concrete reviewed authority, world, housing and resource policy, each tied to reference source hashes and explicitly distinguished from original server semantics.
* `runs/NAME/observations.json`: exact HTTP status, ciphertext, decrypted text and content type for the generated accounts. It contains no real accounts or credentials.

`summary.json` and the static manifest are suitable for review after normal source review. Run directories also contain synthetic SQLite databases and stderr logs. Those operational files are private scratch and should not be exported wholesale.

## Limits

The corpus includes malformed platform/arity input for all 92 routes, adapter errors, account isolation, preference edge cases, avatars, social relations, empty resource DTOs, unconfigured shop/reward/gathering behavior, unallocated housing/world readiness, current versus historical sessions, seven typed durable checkpoints, store close/reopen and a new probe process reading the same disposable state. A framing pass proves that branch only.

The separate configured and management supplements below add successful purchases/gifts/rewards, a complete housing commit and admin commands. Remaining gaps include configured gathering, housing saves with fresh/reversed/concurrent parts and waiting/rollback, resource selection IPC/revocation, scene discovery/allocation using fresh descriptors, Mirror transport and command authority, application state transitions, public credentials/TLS, process-crash durability and original-client acceptance. Graceful store/process reopen does not prove crash recovery.

Extending the corpus with stateful configured success cases should first add a narrow fixture operation to both probes. Directly seeding one implementation's private tables would bypass the application authority being tested.

## Configured mutation corpus

The reviewed fixture extension is now implemented. `fixtures/configured-mutations-v1.json` contains synthetic accounts and configuration only; its digest is pinned in `fixtures/registry.json`. Both probes seed the same explicitly whitelisted rows, documented in `fixtures/schema.json`. The default corpus is unchanged.

```sh
python -B run_parity.py --reference ../../.. --fixture configured-mutations-v1 --candidate ../target/debug/nebula-preserved-server --candidate-arg probe --name configured-run
```

This separate 76-case corpus covers successful buys/bundles/gifts, rejected prices, duplicate claims, mid-bundle grant rollback, companion/locomotion reward grants, coffee balance rewards, cinema capability, a full 101-item two-part housing commit and two process reopens. Every declared no-change boundary additionally compares raw durable snapshots inside each implementation, preserving even timestamps.

The fixture pre-stages an original housing counterpart and exact notification dedupe rows. It proves neither concurrent housing wait behavior nor creation of new notification IDs. Successful consumable receipt issuance and resource-selection CAS/IPC remain `NOT_PROVEN`; those require additional probe contracts. Configured mode has its own fourteen-field wall-clock whitelist with source hashes. It normalizes no UUID or HTTP value and does not change the default seven-field whitelist.

## Management corpus

`admin/run_admin.py` compares actual Python `Management.handle` with the Rust admin probe, using the same reviewed game fixture and the immutable synthetic admin configuration in `admin/fixture.json`. Its 32-byte token is public test data. The separate suite contains 134 ordered cases plus a mandatory isolated three-case Unicode regression; full snapshots compare all 47 typed tables. Every executable is copied into owned disposable scratch before launch.

```sh
python -B admin/test_controls.py
python -B admin/run_admin.py --reference ../../.. --name admin-control --self-control
python -B admin/run_admin.py --reference ../../.. --name admin-final --candidate ../target/debug/nebula-preserved-server
python -B admin/run_admin.py --reference ../../.. --name admin-unicode-final --candidate ../target/debug/nebula-preserved-server --unicode-version-edge
python -B admin/write_report.py --run admin-final --edge-run admin-unicode-final
```

Management requests use JSONL `admin_init` with `token` and `operators`, then `admin` with `method`, `tail`, `headers`, structured `body`, and an optional URL-encoded query string. Replies expose exact status and structured JSON. It exercises 35 of the 36 route patterns; archive and unexercised branches stay `NOT_PROVEN`. `admin/coverage-manifest.json` lists the exact clock paths and UUID correlations separately from the unchanged baseline comparator. Management read JSON ignores object key order while preserving array order and scalar types. Durable receipt/audit text must already be canonical.

Append `.exe` to the candidate path in the configured and management commands on Windows. All probe processes inherit temporary/cache directories under this harness. The portability changes use native `pathlib` resolution; Windows is exercised locally, while Linux execution requires its own run. Historical reports identify the harness hashes actually executed; a changed exported source file does not inherit their result automatically. Review `export-manifest.json` for the current derivative source hashes and exclude all operational run state from publication.
