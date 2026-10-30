# Preservation status

Snapshot assembled 2026-10-30. This file distinguishes observed native behavior from implemented source and deferred acceptance. All readiness claims remain provisional.

An independent [Rust server candidate](../experimental/rust-server/README.md)
now implements the recovered HTTP, Mirror world, persistence and operator API
contracts without a running Unity or Python backend. It has isolated headless
protocol, socket, persistence and cross-language tests. It remains experimental:
original-client acceptance and complete historical-server parity are unproven.
The existing deployment remains the default while that acceptance is pending.

## Current checkpoint — 2026-10-30

The V4 Windows tester restores verified originals after its owned game exits,
even when the launcher window closes. Next-start preparation recovers an
interrupted patch/restore and unwinds earlier versions before applying the
current bundle. Unknown Steam changes or damaged backups stop automatic writes.
All 66 Windows tests passed, including normal/forced fixture process exits and
interrupted restoration; no original game was launched. See the
[recovery validation record](../patcher/recovery-validation.json).

The deployed server now intentionally trusts a supplied Steam ID. Another
device can register into the same existing character/inventory without the
old login secret. Additional device credentials do not replace primary
credentials or reset player data. HTTP and the native TLS gateway read the
same persisted policy; account bans still apply. This permits impersonation
by ID as an explicit operator choice. Generic deployments keep the strict
policy unless `--trust-steam-id` is enabled with public registration.
See the [sanitized policy validation record](../deployment/bootstrap/trusted-id-validation.json).

The current [Windows tester launcher](LAUNCHER.md) uses a fixed server and a
find-game → Start flow. Steam identity detection, first-time preservation
registration and per-user protected credential storage are automatic. Its
actual Rust HTTPS/DPAPI acceptance passed new registration, lost-response retry
and saved-profile reuse. Existing credentials cannot be replaced by claiming
an ID. This opt-in registration is a preservation identity policy and does not
verify Valve ownership; see [enrollment](ENROLLMENT.md).

The [visual catalog](CATALOG_PREVIEWS.md) now has 7,686 recovered item photos,
two explicitly labeled generic fallbacks and 1,205 artwork references. The
separate private pack contains 8,892 WebPs; source and ordinary container
images contain no game pixels. Cards show readable labels, current prices and
store availability, with a compact list option. Mobile and desktop checks
exercise actual decoded photos and authenticated delivery.

The latest Linux release installed with 47 successful tasks, ten changed and
no failures. All 48 pre-existing durable table fingerprints and authority/TLS
files were retained, including after removal of the owned registration test
account. Two additive tables support enrollment audit and limits. The private
live test used the actual Rust TLS/DPAPI code; original-game launch and
independent-player acceptance remain separate.
The sanitized [preview and enrollment record](../deployment/bootstrap/previews-enrollment-validation.json)
pins the final source, images and tester executable.

The [expanded catalog](CATALOG.md) is deployed: all 7,688 ordinary validated
items have active offers. Existing 15 offers and four stores remain unchanged;
the deployed total is 7,689 offers across eight stores, including the earlier
bundle. The source identity digest matches deployed coverage exactly. Only
`shop_catalogs` and `shop_offers` changed among 48 durable table fingerprints;
the other 46 tables and authority/TLS files were retained. New deployment
completed with 40 successful tasks, six changed and no failures; the final
login-hardening release passed 40 tasks with five changed and no failures.

The dashboard defaults to all items and exposes complete available source
metadata, store offers, filters, provenance and 1,205 read-only shop artwork
references. Original commercial names, prices and historical brand membership
remain unrecovered; the new stores/prices are explicit preservation policy.
Eleven focused catalog tests passed on Windows and restricted Linux, and
disposable and deployed backend/SSR browser checks passed at 390px and 1280px.
The deployed checks used normal trusted HTTPS and read-only catalog operations.
The login form now blocks submission before hydration and uses POST fallback;
two focused browser regressions passed. The owner password/session key were
rotated as part of the login hardening; player authorization was retained.
This does not establish native loading/equipping of every asset.

The [one-command Ubuntu installer](../deployment/bootstrap/README.md) installs
Docker/Compose and Ansible as needed from a reviewed release, configures boot
persistence and daily verified backups, and obtains Let's Encrypt public-IP
certificates through HTTP-01 with hourly renewal. The default public launcher
uses system trust without manual CA import. A prepared lawful runtime release,
an owned public IPv4 address and reachable ports are required; this source
checkout contains no Unity runtime, game assets or container images.

The earlier TLS deployment completed with 41 successful tasks, 11 changed and no
failures. Fourteen external default-system-trust checks passed: API/dashboard
access retained owner/player credentials; ports 443, 8444 and 8443 passed
certificate SAN/chain checks; ALPN passed; and 35 internal ports remained closed.
The renewal service completed successfully with `runtime_files_changed=false`
and `tls_sidecars_refreshed=false`, leaving active connections undisturbed.
A repeat installation passed with 40 successful tasks, one changed and no
failures. Actual reboot recovery retained authority/TLS files and all 48 durable
table fingerprints; all boot services returned automatically. The sanitized
[deployment record](../deployment/bootstrap/validation.json) pins its source.
Private addresses, credentials and raw evidence are excluded from this repository.

The patcher passed 46 Windows and 42 Linux tests. Actual Steam discovery found
one supported installation with no warnings after fixing a slash-alias duplicate.
Its current `check-server` subprocess also verified the actual API on port 8444
using default system trust; this check does not establish account login.
Final original-client UI, networking-profile and independent-player acceptance
remain pending; background checks do not complete those gates.
The latest private background observer stopped before login when original Unity
cursor confinement affected the active desktop despite isolated-desktop checks.
Its owned processes were terminated and cursor confinement returned to normal.
Original-input client tests must wait until the computer is available for them.

Additional current checks passed separately: 24 backend HTTP/admin/restart checks
on Windows and restricted Linux using explicit trusted scene/friend fixtures;
17 contracts compiling the actual authored C# social state; 38 Linux deployment
tests; and client TLS suites with 13 Windows/11 Linux tests plus 23 C++ profile
and ten consumer checks. The backend fixture does not exercise Mirror or a native
client. The Rust candidate passed 103 tests on both Windows and Linux, including
four new mailbox edge cases. Its older 649 reference comparisons, 33 rejection
controls and nine gateway checks remain bound to the earlier 99-test binaries;
see [candidate validation](../experimental/rust-server/VALIDATION.md).

## Native and earlier runtime evidence

The observations below describe their tested builds and configurations. Repeat
the remaining flows through the final distribution before release acceptance.

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
| Portable patcher | Guided game/connection/start flow, scalable native controls, saved connections and recovery guidance; 46 Windows/42 Linux tests; Steam discovery found one supported installation with no warnings | Final visual/keyboard and original-client acceptance, runtime-accepted bundle and independent tester install |
| Linux / remote | Linux Docker backend/panel and Unity demand-start passed; fresh Linux/Weaver build and isolated state restart passed; public TLS client source repairs passed independent review; native acceptance remains incomplete | Original Windows client/sidecar/DPAPI acceptance and independent remote peer connectivity |
| Moderation | Account bans, current-session kicks, global chat restrictions, report review, staff labels, operator/player links, maintenance notices and login news implemented; disposable Linux protocol, restart and four dashboard browser cases pass | Original Windows-client moderation presentation remains unverified; no proven arbitrary live broadcast |
| Minigames | Existing protocol, rules and asset research preserved | Deferred until the non-minigame networking and persistence requirements are verified |

Earlier Linux Docker validation exercised the separate Astro/shadcn panel with synthetic real-backend browser checks for login, credits, catalog grants, audit, idempotent retries, CSRF, read-only moderation and revocation. These are management-interface checks, not a claim of original-client public connectivity. Atomic apartment-save and management-state restart tests passed against isolated databases. That composed backend passed 233 tests with three expected private-evidence skips; an isolated process-restart fixture retained all 39 non-internal table snapshots, including its runtime tables. Docker restart preserved 36 durable projected table fingerprints, excluding runtime allocations, sessions and transient presence. Linux Docker started the backend, panel and a real Unity world on demand. The panel image passed two synthetic browser workflows covering moderator access/revocation, credits, catalog grants, audit, replay protection and CSRF. A real backend SIGKILL recovered in about 2.4 seconds within the same container, retaining all 36 durable fingerprints. An unexpected supervisor SIGKILL parked the service unhealthy without a second authority; full-stack stop removed its remaining owned Unity process. The public Docker profile passed credential-denial, cross-account, certificate/hostname and owned-scene TLS forwarding checks. Those wire probes do not prove native opcode1 application acceptance or native multiplayer. Native apartment/resource and shared-host acceptance remain separate gates.

The networking-only client profile replaces the earlier keyboard-enabled default. It leaves original input, cursor and rendering untouched and uses exact six/seven-artifact patch contracts. Original optional input experiments are outside network completion. The public adapter source repairs the stripped Unity API dependency by using its owned authenticated local TLS proxy, and all 70 application HTTP request sites are covered. Source replay, ABI checks and the matching six/seven-artifact plans passed independent review. Original-client TLS acceptance remains pending; source and protocol tests do not establish that result. The package remains `production_ready=false`.

Original game rendering or cosmetic defects remain outside the networking restoration scope unless they prevent a required flow. Original service rules that are absent from the shipped client require explicit local policy, not claims of exact historical parity.

The moderation update adds authenticated moderator actions; the earlier read-only
moderator browser result above describes an older permission set. The current
backend regression suite discovers 336 tests with three expected private-evidence
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

The offline unit runner discovers 434 Python tests with three allowlisted skips;
the current Windows run passed in approximately 61 seconds. It also covers
33 dashboard tests and 46 Windows/42 Linux Rust patcher tests. Coverage
includes permission matrices, transaction rollback,
malformed wire inputs, resource-selection recovery and concurrent retries.
See [testing](TESTING.md) for the single-command runner and measured timings.
These checks do not replace the native acceptance gates above.

No game launches, server listeners, account changes or purchases are needed to assemble or inspect this repository.
