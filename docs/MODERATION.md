# Moderation contracts and preservation policy

The shipped client supports a ban screen, report submission, server-maintenance checks, a staff display label, and personal silence/block relationships. These are separate from authenticated operator powers. The recovered client does not establish the original server's role model or moderation workflow.

[The machine-readable contract](../protocol/moderation-contracts.json) binds the findings to the original binary and metadata hashes, method addresses, and bounded native-byte digests. This is static evidence; it does not claim a successful native moderation test.

## Bans and admission

`CheckerServlet`, `N2UserExist`, and `UserExistsServlet` have existing ban flags and date/reason fields. `N2LoadSpace` also has a ban flag, but does not populate the date/reason display. `N2AddUserOnline` returns a general boolean admission result: its original login continuation quits when false.

The ban screen treats the literal expiry string `null` as permanent suspension. Other strings replace `(x)` in its existing date label; the client does not parse or enforce an expiry. The reason is displayed directly. The preservation backend must own sanction expiry, account binding, and current-session enforcement. A readable UTC timestamp is a preservation formatting choice, not a recovered historical convention.

The early checker sends a persona name and network/hardware claims before a session GUID exists. Those fields, the client-supplied developer flag, and the display badge must not grant operator authority. Authenticated account identity must govern account sanctions.

## Staff display and operator roles

`PlayerLabelInfoServlet` may return a sixth token after its JSON data. The original client copies that token verbatim into the character's staff label and uses the nickname color. No accepted role-value enum or moderation permission check was recovered in this path.

A staff badge is display data. It does not prove developer, moderator, administrator, or dashboard access. Dashboard roles and server action capabilities require separate backend authorization; do not derive them from the badge or `isDev`.

## Reports and silence

The original report categories are `0` threat/harassment, `1` hate speech, and `2` other. `ReportServlet` sends the current session/account, category, target username, and report text. Its response selects either the sent-report or previously-reported presentation. The client does not prove historical storage, deduplication scope, or review behavior; those are server responsibilities. The original request contains no target platform/account field, so ambiguous names require an explicit server policy.

The original silence controls are personal relationships. `N2AddSilenced`/`N2RemoveSilenced` and scene opcodes `23`/`22` refresh the relationship between a viewer and target. They are not a source-proven global moderator mute. Account-wide or global chat restrictions must be enforced by the server independently, while preserving personal silence settings.

## Maintenance and messages

The startup status route has existing normal, maintenance, and updating states. The in-session maintenance poll runs every 10 seconds. A new nonzero remaining-time integer is displayed in `txtMinutes` for 5 seconds; repeated values are suppressed until the display cache is reset. This numeric popup is not an arbitrary text announcement or a client-side shutdown mechanism.

The current scene chat types are only `Space = 0` and `SocialInternal = 1`. A Space message from an unmapped server GUID is rejected by the native player lookup. A `SYSTEM` formatting literal does not remove that guard. Notification opcode `19` has social, gift, game and invitation types; no dedicated moderator announcement type was recovered.

The legacy support-screen constant `141` belongs to an older message family. Although a support-screen text component exists, a current Mirror-route producer for it was not recovered. Current TypeTCP `32` is a board-game command. Do not repurpose these values, invent a chat enum, or claim native broadcast delivery without a separately reviewed and tested consumer. Instance-close opcode `96` redirects a matching current instance to the Nexus; it is not a proven targeted kick-reason channel.

## Implementation boundary

This document records the original client contract. Operator API routes, dashboard role permissions, sanction persistence, audit records, delivery acknowledgements, and configuration belong to the preservation implementation and need their own implementation evidence and tests. They must not be presented as recovered historical behavior.

Authored reasons, badges and report text must obey the existing delimiter framing and bounded validation. Never place credentials or personal network details in reports, issue attachments, or published evidence. Original game binaries, metadata, decompiled source and private analysis files are not included in this contract.
