# Automatic preservation account setup

The server can register preservation accounts for Steam IDs supplied by the
launcher. It neither creates Steam identities nor verifies Steam ownership
tickets. The launcher reads the active Steam identity locally. These are
explicit preservation identity policies, not Valve authentication.

Registration is off by default. Enable `NEBULA_PUBLIC_ENROLLMENT=1` only with
the public TLS profile. Direct backend usage requires both `--public-access`
and `--public-enrollment`, a loopback listener and initialized account operator
authority. Private mode refuses registration.

## Identity policies

**Strict first registration** is the generic default. Only a new profile can
register; existing accounts require their saved credential. Exact matching-key
retries safely recover lost responses. Existing profiles, primary credentials
and revoked credentials cannot be overwritten by registration.

**Trust supplied Steam ID** is an explicit operator choice:
`NEBULA_TRUST_STEAM_ID=1`, or `--trust-steam-id` together with the registration
flags above. A new device can claim any existing Steam ID and access its same
character and inventory without the old credential. Someone supplying another
person's ID can access that preservation account. This implements the chosen
trust policy; it does not verify who owns the Steam ID.

Trusted claims add a separate device credential. They do not rotate or delete
existing primary credentials, change the profile, reset inventory or invalidate
other devices. Previously revoked primary credentials remain revoked, but a
trusted claim can create a fresh device credential. Active account bans still
block claims and device authentication. Claimed-ID access never grants dashboard
operator permissions.

Device aliases are bound to their exact account and secret. The backend records
the active trust policy in SQLite so independent HTTP and native TLS gateway
readers agree. The gateway binds and revalidates the exact device credential,
account, session, allocation and moderation state. Disabling the policy disables
alias access without deleting aliases or changing primary credentials.

The launcher creates a cryptographically random 32-byte account secret and
protects the pending registration with Windows CurrentUser DPAPI before
contacting the server. The pending record is bound to the exact server origin
and Steam identity. There is no shared player credential in the launcher.

## Registration contract

`POST /preservation/enroll` accepts at most 1,024 bytes of JSON:

```json
{
  "steam_id": "<17-digit SteamID64>",
  "enrollment_key": "<43-character unpadded base64url random secret>"
}
```

Successful responses contain `steam_id`, `authorization`, `created` and
`steam_identity_verified: false`. The 85-byte account credential format is
`Nebula-Account-v1 ` followed by the unpadded base64url encoding of the 17 ASCII
identity bytes, a dot, and the enrollment key.

| Status | Meaning |
|---|---|
| 201 | A new profile and access credential were created atomically. |
| 200 | Exact strict retry, or a trusted device joined an existing profile. |
| 400 | Invalid bounded request. |
| 404 | Automatic registration is disabled. |
| 405 | POST is required. |
| 409 | Strict account unavailable, or trusted account banned. |
| 429 | Registration rate or capacity limit reached. |

Trusted bans return `account_banned`; strict conflicts return
`account_unavailable`. Existing account credentials and secrets are never
returned to a claimant. Every successful device receives only its own supplied
random secret in the existing credential format.

The TLS proxy admits anonymous requests only at the exact registration route
and retains authentication elsewhere. It limits registration to two requests
per second with a ten-request burst. Persistent strict limits allow eight
attempts per source address per hour and 100 globally. Trusted mode allows
120 per source address per hour and 1,200 globally. Both policies allow up to
1,000 newly registered accounts; trusted profiles allow 64 distinct device
aliases each. At capacity, existing device retries still work. Invalid and
conflicting requests count toward rate limits.

Rate records contain keyed address digests instead of raw client addresses.
Responses disable caching; request and response secrets are not logged.
Registration does not grant credits, special inventory or Steam rights.
Normal actor binding and moderation continue to apply.

## Focused checks

```sh
python -B -m unittest discover -s backend/tests -p test_enrollment.py -v
python -B -m unittest discover -s backend/tests -p test_trusted_enrollment.py -v
```

Checks cover actual loopback HTTP, strict registration, trusted existing-account
claims, two-device persistence, retained primary credentials, native gateway
binding and revalidation, bans, policy disablement, limits and rollback. They
do not launch the game or establish native-client acceptance.
