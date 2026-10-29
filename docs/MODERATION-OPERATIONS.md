# Operating moderation

Use **Moderation** for server notices, reports and history. Open a player by their
account ID for bans, kicks and chat restrictions. Each mutation requires a reason,
target confirmation and an authenticated operator. The backend commits the policy,
audit record and retry receipt together; refreshing or retrying a completed request
does not apply the action twice.

The [original client contracts](MODERATION.md) describe recovered behavior.
The role model, global mute policy, report workflow and audit storage below are
preservation server policy, rather than a claim about the former service.

## Assigning moderators

1. An owner opens **Panel access** and assigns an operator ID the moderator role.
2. Add that operator's password using the documented
   [credential bootstrap procedure](../admin-panel/README.md#linux-docker), then
   recreate the panel to remount the replaced credentials file.
3. Optionally link the operator to their existing player account from **Panel
   access**. This explicit link enables sanction hierarchy checks. Matching names
   or IDs alone establish no relationship.

The backend checks the current enabled role on every request. Only owners manage
operators or set player staff labels. Admins can also adjust wallets, grant items,
rename players, publish login news and set maintenance countdowns. Moderators can
read records, ban/unban, kick, mute/unmute and review reports. A moderator or admin
cannot sanction an explicitly linked enabled operator of equal or higher rank;
owners can. Keep at least one enabled owner.

A player staff label is optional display text delivered through the original
player-label lookup. It grants no game commands, developer flag, dashboard login
or permissions. Assigning a dashboard role does not invent an in-game GM menu.

## Player actions

| Action | Effect |
|---|---|
| Ban | Refuses account admission and revokes all existing session GUIDs. An optional UTC expiry controls future admission. |
| Unban | Clears the active ban. Previously revoked GUIDs stay revoked; the player must authenticate into a new session. |
| Kick | Revokes the player's current session and disconnects it. Fresh authentication is permitted unless another restriction applies. |
| Mute | Rejects public chat, private chat and typing from the account, including cross-scene relay. Personal silence settings remain separate. |
| Unmute | Clears the server chat restriction. Optional mute expiry also clears enforcement when it elapses. |

Sanctions persist in the state database across restarts. Kicks and bans retain
session tombstones so an old session cannot be revived by unbanning or replaying
an earlier action. Bans use the original client ban fields: permanent expiry is
the literal `null`; timed bans display a server-authored UTC date string.

After a management commit, the backend immediately attempts to publish the
runtime authority snapshot. `runtime_sync=snapshot_published` confirms the file
publication, not a game UI acknowledgment. `pending` means the policy committed
but that publication attempt failed; retrying the same request retries publication
without duplicating the action. Periodic publication remains enabled.

Scene servers check current authority on a 250 ms pump; the public gateway also
revalidates established admission every two seconds. These are polling intervals,
not a guaranteed end-to-end deadline. Missing, malformed or stale authority fails
closed. A kick or ban disconnect does not promise a native explanatory popup on
an already connected client.

## Reports and messages

Reports retain the original categories and raw target username. The reporter's
account ID identifies the reporter, not the offender. Resolve or dismiss a report
with a review note; this never automatically bans a username. Confirm the target
account independently before applying a sanction.

Maintenance is a numeric countdown notice. The original client polls every ten
seconds and suppresses repeated values. Setting a countdown does not shut down
the server or block admission. Clearing it sets zero.

Login news is text returned by the original news fetch. Admins and owners can
publish it with an optional UTC expiry or archive it. Players receive it when
that existing fetch runs; it is not a live popup. No compatible arbitrary live
broadcast channel was proven, so the dashboard does not expose one.

## Verification and limits

Backend tests cover account binding, expiry, immutable revocations, rollback,
idempotency, hierarchy, report identity and gateway admission. Runtime and browser
acceptance must use fresh disposable accounts and state; see the panel's
[verification instructions](../admin-panel/README.md#development-and-verification).
The matching Linux runtime passed a disposable two-peer protocol run covering
public/private and cross-scene mute enforcement, kick/ban disconnects, revoked
session denial and fresh login after unban. Report, maintenance, label and news
HTTP checks and moderation-state restart comparison passed. Four dashboard
browser workflows passed against that stack. No existing player database was used.

Protocol clients and dashboard results do not establish original Windows-client
UI acceptance or complete multiplayer restoration. Track those remaining gates
in [project status](PROGRESS.md).

Back up the persistent state volume and separate operator secrets before upgrades.
Upgrade the backend and Unity scene runtime together using the matching reviewed
image. The scene reader requires moderation authority schema version 1; an older
backend snapshot is refused. Recreate the full stack rather than leaving old
scene processes running alongside a new backend. Preserve the state volume;
schema creation and report indexing run at backend startup.

Do not expose the internal management listener. Use HTTPS for remote dashboard
access and never publish credentials, player databases or private test receipts.
