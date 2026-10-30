# Testing the Linux stack and original clients

## Fast unit and edge-case checks

From the repository root, install the pinned Python test dependencies once:

```sh
python -m pip install -r deployment/docker/requirements.lock.txt -r scripts/requirements-ci.txt
python scripts/run_unit_tests.py --report test-results/unit.json
```

The default command runs five independent Python suites with at most three
worker processes. It uses disposable fixtures and does not start Docker, Unity,
Steam or a game. No community server, credentials or player database is required.
It works from another working directory when given the script's absolute path.

| Suite | Coverage |
|---|---|
| `backend` | Accounts/sessions, avatar saves, settings, ownership, purchases, social state, housing, allocation, notifications, gateway admission and moderation |
| `tooling` | Source/privacy inventory, release packaging, runtime collection, disposable smoke ownership and this runner's failure behavior |
| `builder` | Linux build admission, source/build pins, target and platform validation |
| `bundles` | Exact client patch profiles, required/optional artifacts and mixed-profile rejection |
| `harness` | Offline native-acceptance file protocol, identity, deadlines and mutation declarations; does not run a native client |

For a focused edit, run only the relevant suite or filename group:

```sh
python scripts/run_unit_tests.py --suite backend --pattern "test_moderation*.py"
python scripts/run_unit_tests.py --suite backend --pattern "test_management*.py"
python scripts/run_unit_tests.py --jobs 1 --durations 5
```

Each Python result includes test counts, skip reasons and the slowest tests,
including setup/cleanup time. Suite deadlines default to 180 seconds and can be
changed with `--timeout`. Zero discovered tests, unexpected skips, expected
failures, worker errors and timeouts all fail the command. The three exact
allowlisted skips require private native evidence that is intentionally absent
from the public repository; functional wardrobe checks still run.

Add the dashboard and Rust patcher with:

```sh
python scripts/run_unit_tests.py --suite panel
python scripts/run_unit_tests.py --all --report test-results/all-unit.json
```

The panel unit suite needs Node.js (24 recommended), using its built-in test
runner. The patcher needs Rust and a working platform linker. Prepare its locked
dependency cache once with `cargo fetch --locked --manifest-path patcher/Cargo.toml`.
Testing itself uses `cargo test --locked --offline` and never installs tools or
downloads missing crates. Keep Cargo's ignored target cache for fast repeat runs.

Policy tests exercise a fixed-seed 160-step transition model, all 45
operator-role/linked-player/action combinations, expiry and Unicode boundaries,
13 compound-operation rollback points, concurrent idempotent requests and
authorization revoked between the initial check and the write lock. Protocol
tests include AES block boundaries, malformed ciphertext, delimiter escaping and
exact platform trailers. Primary resource-selection tests cover stale sessions,
leases, revisions, ownership revocation, conflicting retries, rollback and
recovery after an acknowledgment write fails.

Pure policy cases use real in-memory SQLite; persistence and concurrency cases
use separate temporary file-backed databases. Linux automatically puts these
disposable fixtures in `/dev/shm` when at least 128 MiB is free, avoiding disk
flush overhead; other systems use their OS temporary directory. Use `--disk-temp`
to exercise disk-backed temporary storage explicitly. Each suite has its own
private temporary directory and cleanup. Fixed clocks replace expiry sleeps.
No test disables durability on the actual server. Performance timings are
reported rather than asserted against a flaky machine-dependent threshold.

CI runs these Python suites, dashboard checks and Windows Rust tests. JSON Python
results are retained for seven days, including on test failure. `test-results/`
is ignored by Git. Unit reports can contain local paths; keep them out of source
exports and check before sharing them.

The current suite discovers 452 Python tests: 354 backend, 60 tooling, 23 Linux
builder, six bundle and nine offline harness checks. Three backend tests require
private evidence and are skipped explicitly. The panel adds 44 unit tests and
the Rust patcher adds 66 on Windows. The separate, explicitly gated live
registration fixture also passed against the deployed server. An earlier local Linux run of
all five Python suites completed in approximately 25 seconds using shared memory;
timings depend on the machine and temporary storage. These counts describe unit
coverage, not complete native
multiplayer acceptance.

## Current additional checks — 2026-10-30

These results are separate from the 452-test Python unit baseline and its three
allowlisted skips; the latest Windows baseline run passed in approximately 74
seconds. Counts describe different test boundaries and must not be
combined into a native-game pass.

| Layer | Observed result | Boundary and reproduction |
|---|---|---|
| Backend process E2E | 24 checks passed on Windows and restricted Linux | Real encrypted game HTTP, management actions and controlled process restart; explicit trusted scene/presence and friendship fixtures. [Run the harness](../scripts/NONMINI-E2E.md) with a new private artifact directory. No Mirror/native client is exercised. |
| C# social publication | 17 contracts passed | Compiles the actual authored social state and relationship planner with a test-only Unity JSON substitute. [Run the .NET harness](../mirror-server/tests/social-contracts/README.md); no Unity runtime or listener. |
| Deployment automation | 44 tests passed on Linux | [Offline deployment tests](../deployment/ansible/README.md#fast-offline-tests) cover setup and certificate policy without installing services or reaching a server. |
| Client TLS transport | 13 Windows / 11 Linux tests passed | [Headless transport and trust checks](../experimental/remote-transport/client/tls-validation.json); final original-client/UI acceptance remains pending. |
| C++ public-access profile and consumer | 23 profile / ten consumer checks passed | [Compile the real parser/consumer](../client-patches/network-only/public-access/README.md) with disposable fixtures; these checks do not launch the game. |

Actual Steam discovery also found one supported installation with no warnings
after the slash-alias duplicate fix. Discovery and unit tests do not complete
visual/keyboard, original-client or independent-player acceptance.
The current patcher's actual `check-server` subprocess passed against the API
on port 8444 using default system trust; this is not an account-login result.

## Catalog coverage

The expanded [catalog](CATALOG.md) has 12 focused backend checks, included in
the 354 backend count above. They also passed inside a nonroot, network-disabled,
read-only Linux container. They cover all 7,688 shop item responses, encrypted
wire budgets, generated-offer purchases, duplicate suppression, reopen
persistence, rollback, import locking, inactive operator choices and metadata.
The largest encrypted category response measured 375,232 bytes, below the
8 MiB transport limit. Real disposable backend plus SSR browser checks passed
at 390px and 1280px, including proxy filters and source metadata. The deployed
dashboard also passed both widths using normal trusted HTTPS. Two login
browser regressions cover pre-hydration submission and the hydrated JSON flow.
These checks do not load or equip every item in the original client.

## Automatic registration and photo delivery

Seven additional claimed-ID tests pass on Windows and restricted Linux. They
cover multiple devices, retained primary credentials and avatar state, shared
policy restart/disable, account bans, cross-account binding and actual native
gateway admission/revalidation.

The opt-in registration suite has ten passing tests on Windows and restricted
Linux. An actual isolated Nginx/TLS fixture checks first registration, protected
retry, conflicts, rate limits and unchanged authentication on other routes.
The final Windows tester's actual Rust TLS/DPAPI live acceptance passed a new
registration and matching-key retry; reopening the saved profile required no
further registration. Wrong keys and existing-account claims returned 409.
The owned synthetic account was removed, retaining all 48 prior table hashes.

All 50 deployment tests passed on Linux. The 8,892-file private photo pack was
validated, installed atomically, repeated without changes and repaired after a
corruption control. Actual recovered photo browser checks passed at 390px and
1280px, including all item kinds, artwork, prices, details and authenticated
WebP delivery. Twenty-five concurrent images returned 200, followed immediately
by valid catalog JSON. These checks do not launch the original game.

## Experimental Rust server

The separate [Rust candidate](../experimental/rust-server/README.md) has its own
locked Windows/Linux contract and real-socket suite, currently 103 passing tests
on each platform, including four new mailbox edge cases. Its
[recorded validation](../experimental/rust-server/VALIDATION.md) separates those
results from the earlier 99-test binaries' 649 authored-reference comparisons,
33 rejection controls and nine synthetic TLS gateway checks. Those recorded
results do not validate a newer binary automatically. The candidate workflow
runs all three layers on Windows and Linux, then
builds and checks the restricted Linux container. None starts the original game
or uses the desktop. Keep native acceptance as a separate gate.

## Runtime and browser acceptance

The [panel instructions](../admin-panel/README.md) cover type checking, security tests and browser tests. Browser tests require an explicitly supplied, newly created synthetic backend fixture and private credential files. They mutate its credits, ownership and operator access. Never point them at player data. A passing browser workflow proves the panel-to-backend path, not native client compatibility.

For Docker, check container health, demand-start a reviewed world through the original protocol, and verify persistence after recreating containers while retaining the state volume and secrets. Keep the management port internal. Do not use a volume deletion as a restart test. Public ingress requires separate authentication/TLS boundary tests and native client acceptance; no HTTP test or successful image build can substitute for those.

The current [prepared-release installer](../deployment/bootstrap/README.md)
completed with 41 successful tasks, 11 changed and no failures. Fourteen external
checks passed with default system certificate trust: API/dashboard access with
retained credentials, SAN/chain checks on ports 443/8444/8443, ALPN and 35 closed
internal ports. The renewal service completed successfully with no runtime-file
change or TLS sidecar refresh, leaving active connections undisturbed.
A repeat installation passed with 40 successful tasks, one changed and no
failures. An actual reboot restored boot services, retained authority/TLS files
and preserved all 48 durable table fingerprints. The sanitized
[deployment record](../deployment/bootstrap/validation.json) pins its source.
The default public installer configures Let's Encrypt public-IP HTTP-01 and
hourly renewal; players need no manual CA import. A prepared lawful runtime
release, owned public address and reachable ports remain prerequisites.

The default client payload is networking-only and contains no test IPC bridge. The optional native acceptance source below is a separate private test profile. It must not be bundled into the default player patch.

## Native acceptance testing

This repository keeps source and acceptance evidence separate. The files under
`tests/native/` are a portable, file-based client for the reviewed `NAC1`
automation protocol. They are not a game launcher, injector, server supervisor,
or substitute for human-visible acceptance.

The harness never opens a network socket, sends desktop input, changes focus,
or starts/stops a process. It can only publish a bounded command into a session
directory that an independently owned native test process already created.

## Safety boundary

Before running a plan, the operator must independently establish all of the
following:

1. The game and preservation helper are the intended, reviewed builds.
2. The session directory and nonce came from that exact owned process.
3. The process remains alive and belongs to the operator for the whole run.
4. The preservation backend and instance are disposable or backed up when a
   mutating plan is used.
5. No second client writes shared player preferences during a settings test.

The portable harness intentionally does not automate those ownership checks.
The historical acceptance launchers depended on private build receipts, fixed
test identities, and machine-specific process metadata and are therefore not
published here as turnkey tools.

A bounded 2026-10-30 observer found that original Unity cursor confinement can
affect the active desktop even when the client runs on a never-switched desktop
that receives no input. Its watchdog stopped the owned process before login;
cursor confinement returned to normal and no game or helper survived. That run
does not establish public login or world acceptance. Do not run the original-input
client as a background test while someone uses the computer. Server, protocol and
offline checks can continue without launching it. Keep any separately reviewed
test-only cursor changes outside the player networking bundle.

`run_plan.py` refuses a plan containing a known mutating action unless the plan
declares `"mutating": true` and the operator supplies `--allow-mutation`.
Command and result files are never overwritten. A result is accepted only when
its nonce, sequence, action, status, size, and stable file identity match.

## Protocol

Commands use newline-delimited ASCII:

```text
NAC1
<64-lowercase-hex nonce>
<sequence 1..256>
<monotonic deadline in milliseconds>
<allowlisted action>
[bounded argument]
```

The helper responds with `result-<sequence>.json`. Outer statuses are `ok`,
`started`, `rejected`, or `error`. **`started` proves only that the original
callback was dispatched.** It does not prove asynchronous completion,
persistence, peer visibility, wallet mutation, or a successful server write.
Every mutating feature therefore needs the independent evidence listed below.

## Running the offline checks

From the repository root:

```powershell
python -m unittest discover -s tests/native -p "test_*.py"
python -m py_compile tests/native/nac1.py tests/native/run_plan.py
```

These checks use temporary directories only. They do not require the game.

## Running a plan

With an already-running reviewed test session:

```powershell
python tests/native/run_plan.py `
  --session C:\path\to\owned-session `
  --nonce <session-nonce> `
  --plan tests/native/plans/social-navigation.json `
  --output tests/native/reports/social-run.json
```

For an explicitly reviewed disposable fixture, add `--allow-mutation` to run a
mutating plan. Runtime reports and session directories are ignored by Git, but
operators should still treat them as sensitive because they can contain account
hashes, instance identifiers, and local state.

The example plans are parameter-free contract examples, not universal scripts.
Read each plan's `fixture_notes` and adapt the fixture—not the safety checks—to
the reviewed catalog and scene under test.

## Evidence required by feature

| Area | What the file driver can prove | Additional acceptance evidence required |
| --- | --- | --- |
| Movement | Original movement lease dispatch, fixed-step progress, return to original idle | Before/after position and a second client observing the same peer movement |
| Social and chat | Original panel/tab/selection/callback dispatch and generation snapshots | Recipient-side message/invite/relation evidence, plus removal/reseed behavior for relation removals |
| Housing | Original editor callbacks and a fresh native save receipt | Durable backend layout readback, fresh-process reload, visitor read-only enforcement, and peer interaction translation |
| Economy | Original shop open/selection/buy callbacks and wallet/ownership snapshots | Exact selected offer/price/currency, wallet delta, durable ownership, and fresh-process readback; use preservation-catalog currency only |
| Settings | Original settings open/toggle callbacks and immediate manager/UI readback | Baseline capture, distinct-process hydration, and restoration of the baseline; run one client at a time |
| Companion/locomotion resources | Original navigation, select, and remove callbacks | Durable equipped-state readback and fresh-process/peer visibility; server ownership alone is insufficient |

## Current staged status and omissions

- No `GameAssembly.dll`, helper DLL, game executable, or generated asset bundle
  is committed in this testing area.
- No credentials, access tokens, Steam IDs, test identities, private launch
  receipts, fixture databases, or machine-specific paths are included.
- No launcher or process-control code is included. Exact process ownership and
  cleanup remain the responsibility of a separately reviewed launcher.
- Public authentication and remote transport require their own runtime
  acceptance; these file-based plans do not establish either.
- Resource select/remove callbacks exist, but durable equipped-resource
  persistence is still an acceptance boundary rather than a completed claim.
- The optional mouse-look tool under `experimental/optional-input/` is a
  deterministic source transformer. Its generated asset and runtime behavior
  have not been accepted and must not replace the standard input asset by
  default.
- Mini-games remain outside this non-mini-game acceptance scope.

The native plans deliberately preserve these distinctions. A green plan report
is one component of acceptance, not a declaration that the whole game is ready.
