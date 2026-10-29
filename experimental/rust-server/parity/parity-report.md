# Headless authored-reference comparison

The Rust candidate matched **436 of 436 exercised cases**. Overall one-to-one parity and original-server behavior remain **NOT_PROVEN**.

The recorded run uses the current harness source hashes.

The run calls the actual preservation Backend HTTP adapter with sockets blocked and uses fresh generated accounts and disposable state beneath the harness root. It launches no game, Unity/Terra process, listener, desktop application or remote endpoint.

## Inventory and evidence

| Contract inventory | Count |
|---|---:|
| Service.ROUTES | 92 |
| Bootstrap route contracts with static original-client consumer evidence | 40 |
| Registered inbound Mirror messages | 5 |
| Recognized native command hashes | 5 |
| Original application enum values | 97 |
| Authored extension opcodes | 1 |
| Non-minigame application entries including extension | 42 |
| Broader behavior requirements | 36 |
| Concrete reviewed policy rows | 30 |
| Hashed reference source/schema/test files | 109 |

The registered inbound messages are ReadyMessage (40252), CommandMessage (46228), NetworkPingMessage (33151), AddPlayerMessage (13085) and global NebulaMessage (58609). EntityStateMessage serialization does not establish an inbound handler in the current reference.

| Native command | Component | Signed Int32 hash |
|---|---:|---:|
| Speed | 1 | 421014902 |
| Sync | 0 | -1415757549 |
| Teleport | 0 | -788685907 |
| TeleportRotation | 0 | -840469116 |
| LegacyTeleport | 0 | -1564373760 |

Recovered native client field names, parsers, enum members and hashes are separate from authored authorization, state transitions, grants, default balances, timing and concurrency policy. Neither category supplies the retired server implementation.

## Exercised comparison

* 427 HTTP cases compare exact status, raw body/ciphertext, decrypted reply and content type.
* All 92 routes have malformed framing/arity cases; 91 also have a request reaching beyond generic framing. 63 have an expected HTTP 200 case. These counts do not certify all branches of any route.
* Seven checkpoints compare every column and typed value in all 42 default durable tables, including empty tables. Extra tables and numeric storage-type changes fail.
* Preference/current-session/account isolation, avatar reads, social changes, empty resource DTOs, unconfigured commerce/rewards/gathering and missing world/housing readiness are exercised.
* Store close/reopen and a newly spawned probe process reopening the same state preserve the compared state and replies.
* Reference-versus-reference control:436/436 matches. Comparator negative controls:13/13 pass, including deliberately altered status/body/plaintext/types and extra empty tables.

The only normalization is the explicit seven table/column wall-clock whitelist. Numeric type, zero and null are preserved. No HTTP field, ID, UUID, list order, JSON order, entitlement, balance or schema is normalized.

## Resolved differences

The initial candidate had 25 differences in a 430-case corpus: allocation/liveness errors, neutral-avatar binary64 parsing, gift authority validation order and four extra default lifecycle tables. After implementation fixes, the expanded 436-case corpus has no remaining mismatch. This statement is limited to the candidate executable hash below.

## Gaps in this default corpus

The separate configured-parity-report.md supplements successful commerce, rewards and full-layout housing coverage. The items below describe the limits of this default corpus; use both reports when assessing total evidence.

* Successful configured purchases, gifts, rewards and gathering: balances, grants, duplicate claims, concurrent debit and rollback.
* Complete housing layouts: granted items, placement limits, reversed or concurrent sparse parts, pending HTTP acknowledgement, expiry/conflict/rollback and partial-save crash recovery.
* Resource grants and selection IPC: current session/instance ownership, commit acknowledgements, revocation, stale snapshots, restoration and peer appearance.
* Ready scene discovery and allocation using fresh descriptors, capacity, profiles, personal-space ownership and owner presence.
* All Mirror transport/inbound/command authority and all application state transitions, including semantic registries, occupancy, boats, consumables, chat and disconnect cleanup.
* Public credential/TLS gateway/management behavior, abrupt process-crash recovery and original-client acceptance. Cinema's successful clock-bearing reply is not exercised; malformed branches are exercised.

Every unexercised manifest contract remains NOT_PROVEN. Matching the codec or a route's malformed branch never promotes another contract. A reviewed fixture protocol is needed before configured mutation comparisons; direct one-sided SQL seeding would bypass the authority under test.

## Reproduction and hashes

Run the commands in README.md. The candidate uses its `probe` subcommand and the interface in probe_contract.md. Review coverage-manifest.json, reference-policy-inventory.json, normalization.json and case-corpus.json before regenerating evidence.

* Reference source digest: `ee84a152511488426825d36492ab27128c4cdf78cee0f6da88fc3521560e10b3`.
* Candidate executable SHA256: `8df20c772bdb8a99afdf261ccf2669f4c1221f18bef09107dcaa871c2e827578`.
* Detailed summary SHA256: `1293c213043dc62d6cbc022d2b47c823a97b4eb6bd3bf0d1fb6348b349f73f07`.
* Machine verification: verification.json. Detailed observations and per-case statuses: runs/public-baseline-final/.

This report contains generated test outcomes, protocol metadata and hashes. It includes no original game asset, real account, credential, private player state or personal filesystem path.
