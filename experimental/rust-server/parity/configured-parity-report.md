# Configured mutation differential supplement

The configured candidate comparison matched **76/76 cases**. This supplements the separate default 436-case corpus; overall one-to-one parity remains **NOT_PROVEN**.

The recorded run uses the current harness source hashes.

The immutable fixture seeds exactly two synthetic accounts and 30 rows in eleven whitelisted tables into fresh disposable state. Both implementations receive the same JSON object through init. Names and columns come from the audited fixture schema; no caller SQL, code, credential, secret table, file publication or listener is accepted.

## Exercised successful state changes

* A server-priced companion purchase, duplicate purchase and ownership query.
* A two-child bundle purchase, duplicate bundle and a deliberately invalid second-child failure after debit and the first grant. Whole typed state must match its pre-request state after rollback.
* A gift to an actual local friend, duplicate gift, wrong-price rejection and block-based denial. Wallet and recipient grants are compared.
* Generic companion reward, duplicate claim, locomotion reward and a coffee reward. Coffee units and prop-use policy are durable; another account's coffee balance stays empty.
* Cinema capability grant and duplicate claim.
* A 101-item housing layout committed by the real HTTP part1 path after a duplicate original part0. A visitor write is denied. Partial staging and complete layouts survive fresh probe processes.
* Resource and purchase DTOs expose the resulting account-specific grants.

The corpus contains 51 exact HTTP comparisons, 23 complete 42-table typed checkpoints, two full process reopens and 14 explicit no-change boundaries. Every no-change boundary compares each probe's raw durable state, including timestamps, so clock normalization cannot conceal an idempotence or rollback write.

## Deliberate fixture boundaries

One original housing counterpart is pre-staged with a fixed batch ID. This tests the real duplicate-part0 and part1 promotion paths, authority and durability; it does not prove fresh stage creation, concurrent part1 waiting, timeout/conflict handling or abrupt-crash recovery.

Exact notification dedupe rows are pre-staged. Grant/gift success exercises existing-notice validation and idempotence; new notification UUID creation remains unproven. Successful consumable receipt issuance and resource-selection CAS/IPC remain NOT_PROVEN. Configured gathering and the remaining Mirror/application/world contracts remain NOT_PROVEN.

The default seven-field clock whitelist is unchanged. Configured mode adds seven source-proven clock columns in its separate whitelist. It normalizes no HTTP value or UUID and keeps every table, identifier, entitlement, balance and numeric type observable.

## Reproduction and evidence

Use the configured command in README.md and inspect fixtures/schema.json, fixtures/registry.json, fixtures/configured-mutations-v1.json and fixtures/configured-corpus.json. The deliberate invalid rollback child is synthetic fault data, not a supported catalog item.

* Fixture SHA256: `2e5750a99f4f3b9148c77cf50db897937a512a407662e60763ce5885f4d0e1e8`.
* Candidate executable SHA256: `8df20c772bdb8a99afdf261ccf2669f4c1221f18bef09107dcaa871c2e827578`.
* Detailed summary SHA256: `f7cd6809fbbfaa0d51ec95bb541b86c92c7b4d274786104f8a20b9249a138de2`.
* Machine evidence: configured-verification.json; detailed observations and statuses are in runs/public-configured-final/.

Reference-versus-reference configured control: 76/76 matches. Comparator and fixture validation controls are in test_harness.py. No game, native scene server, desktop application, listener or remote endpoint was run. This supplement contains no real account, credential, original asset or personal filesystem path.
