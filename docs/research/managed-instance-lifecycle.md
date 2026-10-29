> Historical research: this file records an earlier investigation, not current feature acceptance. The root [PROGRESS report](../PROGRESS.md) is authoritative. Local evidence and extracted game code are intentionally omitted. See [research index](README.md).

# Managed instance lifecycle v1

Managed lifecycle is an explicit preservation deployment policy. It is disabled by default and does not change manually launched instance behavior.

Enable it only with both HTTP flags:

[Code/listing block omitted from the public research archive.]

The backend never starts a process, allocates a port, or trusts a supervisor journal as readiness evidence. It owns account/apartment bindings, pending demands, capacity reservations and `desired-instances.json`. A separate supervisor owns process and port leases. Clients become ready only through the existing fresh `instances/<instance_id>/instance-status.json`, housing-binding and semantic-interaction gates.

## Native flow

The recovered native pending flow is preserved exactly:

- `N2LoadSpace` accepts a durable demand with `{guid}#false#false`.
- `N2SpaceLoading` returns `{guid}#false` until the exact desired instance is ready.
- Ready returns `{guid}#true#{instance_id}#{psidglobal}#{ip}#{port}`.
- A false poll is repeated by the native client after scaled `WaitForSeconds(1)`, with no observed retry counter.

An accepted pending demand is retained while its session remains current. Each poll renews its short active lease. Stopped polling makes the demand inactive for supervisor drain without deleting its durable target; a later valid poll can renew it. Allocated demands stay active while exact fresh presence exists, with a bounded post-allocation grace before an empty world becomes stopped.

## Account and apartment policy

Accounts created after the first managed-mode activation receive one default `Home` binding. This is an authored local preservation policy, not recovered original entitlement behavior. Preexisting accounts are grandfathered. Other apartment types require an existing explicit admin/entitlement binding.

New personal instance IDs are `apt-` plus a random UUID4 hex value. New public pool IDs are `pub-` plus UUID4 hex. IDs never encode an account name or identifier. Existing valid admin bindings are adopted without renaming. The unique owner/logical-space database constraint and `BEGIN IMMEDIATE` make concurrent first requests converge on one binding.

A visitor invite is pinned during `N2LoadSpace` to the exact desired owner session and bound apartment. Before allocation, that owner session must still be current, freshly present and allocated to the same instance. A visitor is never redirected to another apartment or a newer owner session.

## Capacity

Public selection uses the greater of descriptor player count and exact fresh allocated presence, plus pending/not-yet-present reservations. The total must remain below the descriptor's native maximum of 32 before accepting another reservation. This closes concurrent HTTP over-allocation while descriptor files lag.

## Backend-owned desired snapshot

Path: `<state-dir>/desired-instances.json`

Top-level exact fields:

- `format_version`: integer `1`
- `generation`: finite Unix time
- `managed`: Boolean `true`
- `instances`: rows sorted by `instance_id`

Each row has:

- `instance_id`: safe opaque string
- `kind`: `public` or `personal`
- `psidglobal`: exact admitted scene
- `owner_ps4_id`: personal owner, or empty for public
- `logical_space_key`: personal navigator key, or empty for public
- `desired_state`: `running` or `stopped`
- `active_demands`: unexpired current-session pending and allocated demands
- `pending_reservations`: pending plus allocated clients not yet present
- `active_allocations`: fresh present clients whose database allocation exactly matches
- `adopted_existing`: Boolean indicating a preexisting safe identifier
- `readiness_profile`: exact `nonmini-semantic-v1`

`stopped` rows are retained so the supervisor can drain an owned child and preserve stable IDs. `instance-housing.json` remains the only personal ownership registry.

## Supervisor-owned runtime journal

The coordinated path is `<state-dir>/managed-instance-runtime.json`. It may record the desired generation, leased port/token, PID and process start token, argument/build hashes, health times, restart/backoff state and counters. The backend deliberately never reads this file when deciding readiness.

The supervisor may launch only the pinned Linux build with backend-authored identity and these arguments:

[Code/listing block omitted from the public research archive.]

`build-linux-validation.json` executable, managed assembly and source hashes are the launch pin. The supervisor must not kill or relabel a process it cannot prove it owns.

## Safety boundary

- Client scene, owner and instance fields never become command arguments directly.
- Supervisor output cannot grant ownership or readiness.
- Personal binding, descriptor owner, scene, semantic epoch and endpoint must all match current backend snapshots.
- Manual mode creates no managed schema intent, desired snapshot, default apartment or pending behavior.
- Full server/game readiness remains separately tracked; this lifecycle only orchestrates already reviewed instance profiles.
