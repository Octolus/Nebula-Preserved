# Network diagnostics

The TLS game gateway writes structured JSON to stdout. Docker retains a bounded
history: the supplied Compose configuration uses `json-file`, `max-size: 10m`,
`max-file: 3`, and compression. Budget approximately 30 MB per container. Rotation
is size based, so retention time depends on traffic. Logs are operational data;
restrict access and export only redacted excerpts when reporting incidents.

## Find a connection

Use `docker compose logs --since 15m --no-log-prefix` with the Compose files used
for your installation. Each accepted application identity emits `identity_bound`;
each closing gateway task emits `gateway_close`. Concurrent completions may emit
multiple close records for one connection. Filter the JSON by `connection_id` to
follow one connection, or `actor_ref` to find reconnects for the same account.

`connection_id` is a fresh random 16-character hexadecimal identifier for each
connection. `actor_ref` is the first 16 hexadecimal characters of SHA-256 over the
exact UTF-8 account ID; `session_ref` uses the session GUID in the same way. Both
references appear only after successful authorization. These are pseudonymous
correlation values, not anonymous data: someone who knows an account ID can
calculate its reference. Account IDs, GUIDs, credentials, addresses, player names,
chat text, decrypted packets, and arbitrary exception messages are never logged.

Calculate a target reference locally without placing it in a shell command or
shell history:

```console
python -c "import getpass,hashlib; print(hashlib.sha256(getpass.getpass('Account ID: ').encode('utf-8')).hexdigest()[:16])"
```

## Read the fields

| Field | Meaning |
| --- | --- |
| `timestamp`, `elapsed_ms` | UTC event time and monotonic milliseconds since connection acceptance. |
| `task`, `stage` | Admission, client relay, server relay, or periodic revalidation; the operation that was running. |
| `reason`, `denial_detail` | Fixed close code and optional identity schema/GUID mismatch classification. |
| `frame_length`, `first_mirror_id` | Announced current client frame payload size and first numeric Mirror ID, when available. |
| `last_mirror_id`, `last_opcode` | Last parsed client message ID and application opcode (opcodes outside 0–65535 are omitted). |
| `frames_received`, `client_bytes_received` | Complete client game frames and bytes read, including four-byte frame headers and partial EOF reads. Authorization/preamble bytes are excluded. |
| `frames_forwarded`, `client_bytes_forwarded` | Output game frames and bytes successfully drained upstream, including frame headers. The identity filter may split/drop frames, so totals may differ from received totals. |
| `server_bytes_received`, `server_bytes_forwarded` | Upstream game bytes received and successfully drained to the client. Server messages are not decrypted or parsed for logging. |

`identity_bound` means that a GUID-bearing request matched the authorized session.
It is emitted before forwarding that batch and does not prove the game instance
accepted a character or finished loading the scene. Drained bytes mean accepted
by the local transport buffer, not acknowledged or applied by the remote game.

## Troubleshoot close codes

| Code | Check |
| --- | --- |
| `tls`, `preamble` | Launcher/gateway protocol and ALPN settings. TLS handshake failures before the connection handler are outside these application records. |
| `rate`, stage `capacity` | Connection attempt throttling or simultaneous connection limit. |
| `port`, `credential`, `access_denied`, `allocation`, `instance` | Account authorization and current scene allocation; inspect server logs using the same actor reference if available. |
| `banned`, `revoked_session`, `changed` | Moderation, logout/session replacement, or changed allocation/credentials. Revalidation closes existing connections too. |
| `moderation_unavailable`, `database_error` | Availability and consistency of the authoritative state databases. |
| `application_identity` | `denial_detail=guid_mismatch` means a packet claimed another session; `invalid_identity_schema` means its platform/identity field layout was invalid. |
| `frame`, `message`, `invalid_data` | Announced size, historical Mirror framing/ID, numeric opcode and stage. Never infer the payload from counters. |
| `identity_timeout` | No permitted GUID-bearing request arrived within the bounded initialization period/frame count. |
| `stream_eof` | The named stream closed or ended partway through a frame; this alone does not identify why the peer closed. |
| `timeout`, `transport_error` | Stage identifies a stalled/failed read, connection, or write; check reachability and instance health. |
| `lifetime`, `cancelled` | Maximum connection lifetime or server/task shutdown. |
| `internal_error`, `denied` | Unexpected exception or an unrecognized denial; report the safe record, version and stage. Raw exception text is intentionally excluded. |

No packet-by-packet payload logging or unbounded local log files are enabled.
The gateway retrieves completed task exceptions and awaits canceled sibling tasks
before releasing connection capacity.

## Persistent diagnostic files

Docker logs are lost when a container is recreated, so the same JSON lines are also
appended to size-rotated files on the persistent `state` volume (5 MB × 5 files
each, at most ~30 MB per file family):

| File (inside the volume, `/var/lib/nebula/…`) | Writer | Content |
| --- | --- | --- |
| `logs/gateway.jsonl` | `public-game` | `gateway_close`, `identity_bound` |
| `logs/backend-failures.jsonl` | `server` | `request_failed`, `unknown_route`, `missing_data`, `background_failed`, `unhandled_exception` (with traceback) |
| `requests.jsonl` | `server` | Older per-request audit record (all statuses, `request_sha256`, safe stack locations). |

The gateway mounts `state` read-only plus only the `logs` subpath read-write
(Docker Engine ≥ 26 / Compose ≥ 2.30). The server creates `logs/` as uid 1000
before it reports healthy, which the gateway's `depends_on` already waits for. If
the directory cannot be written, `{"event":"diagnostic_file_unavailable"}` is
printed once and stdout logging continues. Files hold no descriptor between
writes; backups are `*.jsonl.1` … `*.jsonl.5`.

```console
# Last gateway closes for one player, including closes from before a recreate
docker exec nebula-preserved-server-1 sh -c 'cat /var/lib/nebula/logs/gateway.jsonl.* /var/lib/nebula/logs/gateway.jsonl 2>/dev/null' \
  | grep '"actor_ref":"<ref>"' | tail -50
# All backend failures/warnings for one player
docker exec nebula-preserved-server-1 sh -c 'cat /var/lib/nebula/logs/backend-failures.jsonl.* /var/lib/nebula/logs/backend-failures.jsonl 2>/dev/null' \
  | grep '"actor_ref":"<ref>"'
# Full traceback for a request_id seen in a request_failed line
docker exec nebula-preserved-server-1 grep -h '"request_id":"<id>"' /var/lib/nebula/logs/backend-failures.jsonl
```

Backups are concatenated oldest-numbered last, so sort by `timestamp` when order
matters (for example `| python -c "import sys,json;[print(l,end='') for l in sorted(sys.stdin,key=lambda l:json.loads(l)['timestamp'])]"`).

## Backend request failures and missing data

The HTTP backend (container `nebula-preserved-server-1`, project name
`nebula-preserved`) prints one compact JSON line on stdout per failed game request
and per "missing data" lookup. Successful requests are not printed. Unhandled
exceptions also print a full Python traceback on stderr; every traceback line is
prefixed with `[request_id=<id>]`, the same id as the `request_failed` line. The
client still receives only the generic encrypted `ERROR` response.

| Event | Level | Meaning |
| --- | --- | --- |
| `request_failed` | `warning` (4xx) / `error` (5xx) | A game request (or `preservation/enroll`) returned a non-200 status. |
| `unknown_route` | `warning` | The client called a route with no reconstructed handler (501). Use `route` to see which feature is missing. |
| `missing_data` | `warning` | A lookup the client depends on was empty, unknown, or rejected; emitted only during a game request. The request may still return 200 (for example `NOCRYSTALS`). |
| `background_failed` | `error` | The 2-second state export/import loop raised (`error_type` only). |

Request fields: `timestamp`, `request_id` (16 hex, also in `requests.jsonl`),
`route` (servlet name, or `invalid_route` if unsafe), `status`, `reason`, `message`
(server-authored `ProtocolError` text, ≤200 characters), `elapsed_ms`,
`field_count` (number of `#`-separated request fields; values are never logged),
`actor_ref` (only after authentication), `suppressed` (see below).

`reason` is the `missing_data` reason when one was raised during the request;
otherwise one of `invalid_request_shape`, `invalid_encrypted_request`,
`access_denied`, `internal_error`, `unknown_route`, an enrollment code, or a status
class: `invalid_request` (400), `forbidden` (403), `not_found` (404), `conflict`
(409), `server_error` (500), `not_implemented` (501), `unavailable` (503).

`missing_data` reasons and their ID fields (IDs that are not
`[A-Za-z0-9_.:@+-]{1,96}` are replaced by `invalid_id`):

| Reason | Fields | Source |
| --- | --- | --- |
| `wardrobe_entitlement_unknown` | `item_id` | Wardrobe option change for an item the account does not own (404). |
| `preset_unavailable` | `gender`, `named` | No stored avatar preset for the account/gender (501). |
| `catalog_item_unknown`, `catalog_item_ambiguous` | `item_id`, `gender`, `category` | Wardrobe catalog resolve failed. |
| `resource_item_unknown` | `kind`, `item_id` | Companion/locomotion catalog resolve failed. |
| `housing_item_unknown` | `item_id` | Housing asset not in the shipped catalog (shop). |
| `shop_offer_unknown`, `shop_offer_inactive` | `offer_id` | Shop offer missing or disabled. |
| `purchase_insufficient_funds`, `gift_insufficient_funds` | `offer_id`, `currency` | Buy/gift refused (`NOCRYSTALS`/`NOXP`). |
| `purchase_already_owned`, `gift_already_owned` | `offer_id` | Buy/gift refused (`ISPURCHASED`). |

Noise is bounded: identical `request_failed`/`unknown_route` (same actor, route,
status, reason) and `missing_data` (same actor, reason, IDs) lines are printed at
most once per 60 seconds. The next printed line carries `suppressed: N`; counts
pending when traffic stops are not printed. Unauthenticated failures share one
bucket per route/reason. `internal_error` lines are never suppressed. The
supervisor prints its `{"actions": …}` line only when it actually acts.

Example lines:

```json
{"event":"unknown_route","timestamp":"2026-10-30T20:57:38Z","level":"warning","request_id":"8bb8bafe0e05bddc","route":"GetFriendRequestsServlet","status":501,"reason":"unknown_route","message":"Route behavior has not been reconstructed","elapsed_ms":0,"field_count":3,"actor_ref":"5d41402abc4b2a76"}
{"event":"missing_data","timestamp":"2026-10-30T20:58:02Z","level":"warning","reason":"wardrobe_entitlement_unknown","route":"WardrobeOptionItemServlet","request_id":"1f0c9e4d2b7a6c55","actor_ref":"5d41402abc4b2a76","item_id":"Hat_042"}
{"event":"request_failed","timestamp":"2026-10-30T20:58:02Z","level":"warning","request_id":"1f0c9e4d2b7a6c55","route":"WardrobeOptionItemServlet","status":404,"reason":"wardrobe_entitlement_unknown","message":"Unknown local wardrobe entitlement","elapsed_ms":3,"field_count":4,"actor_ref":"5d41402abc4b2a76","suppressed":2}
{"event":"request_failed","timestamp":"2026-10-30T20:59:10Z","level":"error","request_id":"bae4443ae3fe0a40","route":"N2LoadSpace","status":500,"reason":"internal_error","elapsed_ms":12,"field_count":6,"actor_ref":"5d41402abc4b2a76"}
```

### Find failures for a player

1. Compute the player's `actor_ref` from the account ID (Steam ID) with the
   command in "Find a connection" above. Backend and gateway use the same value.
2. Filter:

```console
docker logs nebula-preserved-server-1 --since 1h 2>/dev/null | grep '"event":"request_failed"'
docker logs nebula-preserved-server-1 --since 1h 2>/dev/null | grep '"actor_ref":"<ref>"'
docker logs nebula-preserved-server-1 --since 24h 2>/dev/null | grep '"event":"unknown_route"' | grep -o '"route":"[^"]*"' | sort | uniq -c | sort -rn
docker logs nebula-preserved-server-1 --since 24h 2>/dev/null | grep '"event":"missing_data"' | grep -o '"reason":"[^"]*"' | sort | uniq -c
docker logs nebula-preserved-server-1 --since 1h 2>&1 | grep '\[request_id=<id>\]'   # traceback (stderr)
docker logs nebula-preserved-public-game-1 --since 1h | grep '"actor_ref":"<ref>"'  # gateway side
```

Without public access (private mode) there is no authenticated account, so
backend lines carry no `actor_ref`; correlate by time and `route`. Tracebacks on
stderr and in `backend-failures.jsonl` may contain exception text; treat them as
operator-only data and redact before sharing.
