# Automatic preservation account setup

The server can optionally accept first-time registration from the tester
launcher. This creates a **preservation account for an asserted SteamID64**;
it neither creates a Steam identity nor verifies a Steam ownership ticket.
The launcher reads the active Steam identity locally. A first claimant could
assert someone else's unused ID, so this policy is intended for an operator's
explicitly enabled preservation test. Verified Valve authentication is a
separate integration.

Registration is off by default. Enable `NEBULA_PUBLIC_ENROLLMENT=1` only with
the public TLS profile. Direct backend usage requires both `--public-access`
and `--public-enrollment`, a loopback listener and initialized account operator
authority. Private mode refuses this option.

The launcher creates a cryptographically random 32-byte account secret and
protects the pending registration with Windows CurrentUser DPAPI before
contacting the server. The pending record is bound to the exact server origin
and Steam identity. A lost HTTP response can therefore be retried safely.
There is no shared player credential embedded in the launcher.

## Registration contract

`POST /preservation/enroll` accepts at most 1,024 bytes of JSON:

```json
{
  "steam_id": "<17-digit SteamID64>",
  "enrollment_key": "<43-character unpadded base64url random secret>"
}
```

Successful responses contain `steam_id`, `authorization`, `created` and
`steam_identity_verified: false`. The existing 85-byte account credential
format is `Nebula-Account-v1 ` followed by the unpadded base64url encoding of
the 17 ASCII identity bytes, a dot, and the enrollment key.

| Status | Meaning |
|---|---|
| 201 | A new profile and credential were created atomically. |
| 200 | This exact enrollment account and secret already exist; safe retry. |
| 400 | Invalid bounded request. |
| 404 | Automatic registration is disabled. |
| 405 | POST is required. |
| 409 | Account unavailable; use the existing saved credential or contact the operator. |
| 429 | Registration rate or capacity limit reached. |

Existing profiles cannot be claimed, reset or overwritten. A retry only
succeeds when the account has an enrollment audit record, an active matching
credential and no active ban. Operator-created profiles require their existing
credentials. Revoked credentials stay revoked. Changing the supplied key
never rotates a credential.

The TLS proxy admits anonymous requests only at the exact registration route
and retains authentication for every other game route. It limits registration
to one request per minute with a small burst. Persistent backend limits allow
eight attempts per source address per hour, 100 global attempts per hour and
1,000 newly enrolled accounts. Invalid and conflicting requests count too.
Rate records contain keyed address digests instead of raw client addresses.
Responses disable caching; request and response secrets are not logged.

Registration only creates the normal profile and unique account access. It
does not grant operator access, credits, special inventory or Steam rights.
Normal account authorization, cross-account checks and moderation still apply.

## Focused checks

```sh
python -B -m unittest discover -s backend/tests -p test_enrollment.py -v
```

The checks exercise actual loopback HTTP, first registration, retry, existing
account refusal, actor binding, ban/revocation, limits, rollback and concurrent
claims. They do not launch the game or establish native-client acceptance.
