# Management differential supplement

The candidate matched **137/137 exercised cases** against the actual Python Management adapter. Overall parity remains **NOT_PROVEN**.

The recorded run uses the current harness source hashes.

All state is disposable. The reviewed fixture supplies two synthetic game accounts and four synthetic management operators; its fixed 32-byte token is public test data, not a secret. Both implementations receive identical init data. No listener, desktop, game, original native runtime or remote service runs.

The corpus reaches 35/36 management route patterns (21 GET, 15 POST inventory). A route observation proves its exercised branch only. Complete typed snapshots include every column and value in all 47 tables, including empty tables.

Cases cover authentication and role precedence; Origin and forged-role guards; body type, size and content-type rejection; literal search and pagination; wallet debit limits, typed deltas, actor-specific idempotency, replay and conflict; successful companion and bundle-offer grants; rename/social-state persistence; staff labels; report creation/review; mute/unmute; maintenance; news creation/replay; kick/ban/unban with revoked sessions; linked-owner sanction denial; disabled operator persistence and graceful process reopen.

The mandatory isolated Unicode regression submits U+1C89 as a staff label. Python Unicode15 categorizes it as unassigned and rejects it without writing state. An initial Rust Unicode16 implementation accepted it and committed data; the final corpus retains this regression and checks the complete raw state after rejection.

Normalization is limited to explicitly listed source-proven clock paths and correlated management request/news UUIDs. It checks canonical durable audit/receipt JSON before transforming it; IDs retain cross-table and replay identity. News dates must derive from the exact creation clock, and maintenance duration remains exact. Raw no-change boundaries preserve timestamps and UUIDs. Eleven deliberate comparator mutations pass their rejection controls.

## Remaining gaps

* News archive route: **NOT_PROVEN**.
* Successful direct wardrobe, locomotion and housing admin grants: **NOT_PROVEN**.
* Duplicate raw JSON keys, invalid UTF-8/raw JSON and actual HTTP body framing: **NOT_PROVEN**.
* Secret/operator file loading, listeners/TLS and header duplication: **NOT_PROVEN**.
* Concurrent idempotent commands and database busy/constraint fault injection: **NOT_PROVEN**.
* Runtime sync publication failure/retry and client acknowledgement: **NOT_PROVEN**.
* Timed ban/mute/news expiry boundaries and maintenance expiry: **NOT_PROVEN**.
* Exhaustive Unicode scalar classification and operator-protected policy combinations: **NOT_PROVEN**.
* Abrupt process crash durability and original-client acceptance: **NOT_PROVEN**.

## Reproduction

```sh
python -B admin/test_controls.py
python -B admin/run_admin.py --reference ../../.. --name admin-control --self-control
python -B admin/run_admin.py --reference ../../.. --name admin-final --candidate ../target/debug/nebula-preserved-server
python -B admin/run_admin.py --reference ../../.. --name admin-edge-final --candidate ../target/debug/nebula-preserved-server --unicode-version-edge
```

Run from experimental/rust-server/parity; append .exe to the candidate filename on Windows. Python must provide the reference Unicode15 data (Python3.12).
The candidate uses its `probe` subcommand. Each run copies its executable into private disposable scratch before launch, fixing its hash even if another build occurs. Both ordinary and Unicode reports must use the same binary and reference digest.

* Candidate SHA256: `8df20c772bdb8a99afdf261ccf2669f4c1221f18bef09107dcaa871c2e827578`.
* Python Unicode data: `15.0.0`; final Rust pin: `15.0.0`.
* Machine evidence: admin-verification.json and admin/coverage-manifest.json. No run database, stderr, original asset, real account, real credential or personal path is part of this report.
