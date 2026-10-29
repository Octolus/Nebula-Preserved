# Preservation status

Snapshot assembled 2026-10-30. This file distinguishes observed native behavior from implemented source and deferred acceptance. All readiness claims remain provisional.

An independent [Rust server candidate](../experimental/rust-server/README.md)
now implements the recovered HTTP, Mirror world, persistence and operator API
contracts without a running Unity or Python backend. It has isolated headless
protocol, socket, persistence and cross-language tests. It remains experimental:
original-client acceptance and complete historical-server parity are unproven.
The existing deployment remains the default while that acceptance is pending.

The Ubuntu 26 Ansible deployment now configures Docker, authenticated TLS
ingress, a persistent state volume, boot services and verified daily backups.
An operator-owned deployment passed actual reboot recovery, retained its account,
wallet and credential, and passed certificate-verified API/dashboard checks.
Its private address, credentials and evidence are excluded from this repository.
The Windows launcher now has server selection, Steam discovery, an executable
picker and a verified Start action. Thirty Rust unit tests and 44 disposable CLI
acceptance commands passed. The final original-client GUI test remains blocked
by Windows desktop access; the release bundle remains provisional.

| Area | Observed or implemented | Still required |
|---|---|---|
| Bootstrap and world | Native login and Nexus load; two isolated native clients authenticated and announced in the same instance | Repeat through the final shared distribution and deployment configuration |
| Avatar editor | Original hat removal and named preset save/load; saved outfit and all 88 body values persisted; fresh authenticated clients restored the hatless outfit and a receiving client resolved its asset list | Final networking-profile reload and peer state across additional customization categories; original UI quirks remain outside scope |
| Credits and items | Server-side inventory and wallet administration; existing-account credit changes verified; original store showed the exact test balance/debit | More item categories and equipped-resource acceptance |
| Stores | One original companion Buy callback completed; exact debit, durable buy ownership/resource grant and distinct-client ownership checked; a fresh client restored the purchase after backend restart; unrelated durable state preserved | Broader item/currency combinations and final distribution |
| Movement | Two native clients: forward and reverse movement completed and returned to ordinary idle; receiving-client and server positions matched within 0.1 mm | Repeat through the final distribution and remote host |
| Friends, chat, invites | Native friend request/notification/acceptance and reciprocal durable rows; fresh clients hydrated friendship; public chat and fixed-marker private chat delivered both ways | Invite accept, join and server-restart acceptance |
| Apartments | Ownership, layouts, placement limits, persistence and allocation source | Original owner placement/save, fresh load, visitor join and edit denial |
| Resources | Durable selections/current-session guards integrated; 13 authority tests passed; complete Linux/Weaver build from a fresh copy of the public server source passed | Native selection/rejection reconciliation, fresh-session restoration and peer proof |
| Settings | Original friend-login notification toggle persisted; a second fresh process loaded the changed value and restored baseline; a third loaded baseline; unrelated durable state preserved | Other settings and final-distribution acceptance; original platform-only UI defect excluded |
| Input | Default networking profile retains shipped input; optional keyboard/mouse research remains separate | Optional input experiments are outside the required networking completion scope |
| Portable patcher | Steam discovery and exact version checks; 22 Rust tests, six builder tests and 44 CLI fixture commands verified receipt-backed endpoint/profile updates, idempotence, tamper refusal and restore; inherited recovery checks retained | Final runtime-accepted bundle and independent tester install |
| Linux / remote | Linux Docker backend/panel and Unity demand-start passed; fresh Linux/Weaver build and isolated state restart passed; public TLS client source repairs passed independent review; native acceptance remains incomplete | Original Windows client/sidecar/DPAPI acceptance and independent remote peer connectivity |
| Moderation | Account bans, current-session kicks, global chat restrictions, report review, staff labels, operator/player links, maintenance notices and login news implemented; disposable Linux protocol, restart and four dashboard browser cases pass | Original Windows-client moderation presentation remains unverified; no proven arbitrary live broadcast |
| Minigames | Existing protocol, rules and asset research preserved | Deferred until the non-minigame networking and persistence requirements are verified |

The current server target is Linux Docker. The separate Astro/shadcn panel has passed synthetic real-backend browser checks for login, credits, catalog grants, audit, idempotent retries, CSRF, read-only moderation and revocation. These are management-interface checks, not a claim of original-client public connectivity. Atomic apartment-save and management-state restart tests pass against isolated databases. The final composed backend passed 233 tests with three expected private-evidence skips; an isolated process-restart fixture retained all 39 non-internal table snapshots, including its runtime tables. Docker restart preserved 36 durable projected table fingerprints, excluding runtime allocations, sessions and transient presence. Linux Docker started the backend, panel and a real Unity world on demand. The production panel image passed two synthetic browser workflows covering moderator access/revocation, credits, catalog grants, audit, replay protection and CSRF. A real backend SIGKILL recovered in about 2.4 seconds within the same container, retaining all 36 durable fingerprints. An unexpected supervisor SIGKILL parked the service unhealthy without a second authority; full-stack stop removed its remaining owned Unity process. The public Docker profile passed credential-denial, cross-account, certificate/hostname and owned-scene TLS forwarding checks. Those wire probes do not prove native opcode1 application acceptance or native multiplayer. Native apartment/resource and shared-host acceptance remain separate gates.

The networking-only client profile replaces the earlier keyboard-enabled default. It leaves original input, cursor and rendering untouched and uses exact six/seven-artifact patch contracts. Original optional input experiments are outside network completion. The public adapter source repairs the stripped Unity API dependency by using its owned authenticated local TLS proxy, and all 70 application HTTP request sites are covered. Source replay, ABI checks and the matching six/seven-artifact plans passed independent review. Original-client TLS acceptance remains pending; source and protocol tests do not establish that result. The package remains `production_ready=false`.

Original game rendering or cosmetic defects remain outside the networking restoration scope unless they prevent a required flow. Original service rules that are absent from the shipped client require explicit local policy, not claims of exact historical parity.

The moderation update adds authenticated moderator actions; the earlier read-only
moderator browser result above describes an older permission set. The current
backend regression suite discovers 325 tests with three expected private-evidence
skips. Moderation rules and operator setup are documented in
[moderation operations](MODERATION-OPERATIONS.md). Connected protocol and browser
acceptance are tracked separately from these offline checks. A fresh disposable
Linux stack passed public/private and cross-scene chat, mute/unmute rejection,
live kick/ban disconnects, revoked-session denial and fresh login after unban.
Original report, maintenance, staff-label and news HTTP contracts passed, and
moderation state survived a complete server restart. Four actual dashboard
browser workflows passed against that same disposable stack. These are protocol
and browser results, not shipped Windows-client presentation or full multiplayer
acceptance.

The offline unit runner now covers 423 Python tests, 33 dashboard tests and
30 Rust patcher tests, including permission matrices, transaction rollback,
malformed wire inputs, resource-selection recovery and concurrent retries.
See [testing](TESTING.md) for the single-command runner and measured timings.
These checks do not replace the native acceptance gates above.

No game launches, server listeners, account changes or purchases are needed to assemble or inspect this repository.
