# Contributing

Help reconstruct the original client's networking and durable state. Keep changes
focused and cite the shipped producer, consumer or protocol contract that supports
them. Where historical server policy cannot be recovered, label replacement policy
explicitly. Minigames are deferred until the other networking and persistence
requirements are complete; unrelated UI, rendering and gameplay fixes are outside
the current scope.

## Before changing code

Read [setup](docs/SETUP.md), [testing](docs/TESTING.md) and the
[status matrix](docs/PROGRESS.md). Preserve pinned protocol dependencies and
upstream notices. Treat the original Steam installation as an input: exercise
patch/update/restore on a disposable copy first.

Explain the concrete behavior before and after your change. Include meaningful
tests for the affected contract and record the build/profile used. Distinguish
source tests, protocol probes, synthetic container tests and actual native-client
observations. Passing one does not establish the others.

For quick feedback, run `python scripts/run_unit_tests.py`. It runs independent
Python suites in parallel and reports slow tests; `--all` adds dashboard and Rust
unit tests. See [testing](docs/TESTING.md#fast-unit-and-edge-case-checks) for initial
dependencies and targeted commands. Keep unit tests deterministic and offline;
use real SQLite transactions for state invariants, fixed clocks for expiry and
temporary file-backed databases for restart/concurrency. Add a regression for
the contract or failure being fixed, rather than matching private implementation
details. Keep native and Docker acceptance separate from the fast loop.

## Evidence that helps review

| Change | Useful verification |
|---|---|
| Purchase or grant | Exact wallet/ownership deltas, one receipt, unrelated state preserved |
| Social delivery | Sender and intended recipient evidence, current session identity |
| Character or apartment save | Complete durable state, then a distinct-process reload |
| Shared world state | Two actual clients in the same allocation and receiving-peer evidence |
| Deployment or restart | Same image/state-volume lineage, clean ownership and durable-state comparison |

Use synthetic accounts and disposable fixtures. Keep runtime evidence privately
outside the source tree. Never grant, reset or overwrite community data to make a
test pass. Update the status matrix when new evidence changes a claim.

## Keep contributions safe to share

Do not commit game binaries/assets, generated runtimes, account databases,
credentials, private keys, personal machine configuration or private captures.
Follow the [privacy](docs/PRIVACY.md) and [publication](docs/PUBLISHING.md) checks.
Report sensitive defects using [SECURITY.md](SECURITY.md).

Submit original contributions under the project's [MIT license](LICENSE).
Identify any upstream material and retain its license and provenance. Third-party
components remain under their included terms; contributing does not change those
licenses or authorize distribution of game assets. See [licensing scope](docs/LICENSING.md).
