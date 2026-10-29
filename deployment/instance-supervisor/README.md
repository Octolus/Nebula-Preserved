# Managed instance supervisor

`instance_supervisor.py` reconciles a fresh, backend-authored
`desired-instances.json` snapshot with a bounded set of Linux Unity server
children. It is dry-run by default. Process creation requires `--run`; the
example systemd unit is intentionally not enabled or started by this package.

## Authority boundary

The backend remains the only authority for instance identity, housing
ownership, demand, allocation, and client readiness. The supervisor:

- accepts only the exact version-1 desired schema and operator-allowed scenes
  and readiness profiles;
- checks personal rows against the existing authoritative
  `instance-housing.json` snapshot;
- accepts new opaque `apt-`/`pub-` UUID IDs, or a bounded safe legacy ID only
  when the backend explicitly marks it `adopted_existing`;
- pins the build report, ELF, and managed `Assembly-CSharp.dll` by SHA-256;
- constructs a fixed argument vector without a shell or record-supplied extra
  arguments;
- owns a process group only when it launched that process in its current
  lifetime;
- never adopts or signals a PID read from disk after restart;
- never writes `instance-status.json`, `game_ready`, or networking parity.

The existing descriptor at
`instances/<instance_id>/instance-status.json` remains the actual health and
readiness evidence. A supervisor runtime row is observability, not permission
for the backend to allocate a client.

## Desired snapshot

Top-level fields are exactly `format_version`, `generation`, `managed`, and
`instances`. Rows are sorted by `instance_id` and contain exactly:

`instance_id`, `kind`, `psidglobal`, `owner_ps4_id`, `logical_space_key`,
`desired_state`, `active_demands`, `pending_reservations`,
`active_allocations`, `adopted_existing`, and `readiness_profile`.

`desired_state` is `running` or `stopped`. A stopped row must carry no active
demand counters. Unknown fields, stale/rollback generations, identity or
binding disagreement, an unapproved scene/profile, and malformed counters all
fail closed before reconciliation.

The process limit counts live and draining children; stopped history has a
separate bounded record limit. New starts queue until a process slot and a
collision-free leased port are available.

## Durable lease journal

The supervisor atomically writes `managed-instance-runtime.json` with
`format_version`, `generation`, and sorted instance rows. Each row records:

- instance policy: `instance_id`, `kind`, `psidglobal`, `owner_ps4_id`,
  `logical_space_key`, `readiness_profile`, `adopted_existing`;
- lease/process identity: `port`, `lease_token`, `pid`, `start_token`, and
  `build_sha256`;
- lifecycle evidence: `desired_generation`, `state`, `started_at`,
  `last_health_at`, `restart_count`, `next_restart_at`, `updated_at`, and
  `reason`.

Lease ports and tokens are unique and durable. On supervisor restart, the port
lease is retained, but the recorded PID is deliberately not adopted. If that
endpoint remains occupied, launch is refused rather than killing or replacing
the unknown process. Crashes use bounded exponential restart backoff. Backend
stop/removal and optional idle TTL use TERM followed by a bounded KILL only for
children owned by the current supervisor.
SIGTERM and SIGINT enter this same graceful owned-child shutdown path; the
systemd `TimeoutStopSec` is longer than the configured child grace interval.

The journal also retains the last accepted desired generation when there are
no lease rows, including a failed startup followed by shutdown. Each launch
persists its intent before creating the child, resets its health epoch and
writes distinct `supervisor-logs/<instance>/<start_token>.unity.log` and
`.process.log` files. A replacement cannot overwrite the previous attempt's
diagnostics.

## Operator flow

First inspect without writes or child processes:

```text
python3 tools/instance_supervisor.py --once \
  --state-dir /var/lib/nebula-preservation \
  --binary /opt/nebula-preservation/mirror-server/build-linux/NebulaServer.x86_64 \
  --build-report /opt/nebula-preservation/mirror-server/build-linux-validation.json \
  --build-report-sha256 <sha256> --binary-sha256 <sha256> \
  --managed-assembly-sha256 <sha256> \
  --bind 127.0.0.1 --advertise-ip 127.0.0.1 \
  --port-range 28000-28031 --max-processes 16 \
  --allowed-scene Nexus --allowed-scene LeafPark --allowed-scene Beach --allowed-scene Cinema \
  --allowed-scene Home --allowed-scene Greenhouse --allowed-scene Waterfall --allowed-scene StarCrawlers --allowed-scene BlueWaveHideout --allowed-scene DressingRoom --allowed-scene CutteridgeEstate --allowed-scene TheMoonlightRoom --allowed-scene LeChalet --allowed-scene LakeApartment --allowed-scene SereneGarden --allowed-scene WoodlandClearing --allowed-scene TheNebulian --allowed-scene SorcerersEyrie1 --allowed-scene ZeroDistrictDen --allowed-scene CampSilverLake --allowed-scene FlyingDevice --allowed-scene Deadquarters --allowed-scene HollyridgeEstate --allowed-scene WinterSnowGlobe --allowed-scene TokyoApartment --allowed-scene NebuHouse --allowed-scene WestValleyApartment --allowed-scene WhisperingHillsMansion --allowed-scene CliffApartment --allowed-scene TheCrypt --allowed-scene ForgottenStation --allowed-scene GreekSummerHouse --allowed-scene MountainHideout --allowed-scene GingerbreadHouse --allowed-scene WindMillFarmHouse \
  --allowed-profile nonmini-semantic-v1
```

After reviewing the plan, omit `--once` and add `--run`, or install the unit
and environment file. The supervisor refuses `--run --once` so a one-shot
command cannot launch children and immediately abandon them.

## Package installation

Use the package/prerequisite layout in [shared Linux preparation](../README.md).
The managed HTTP service and supervisor replace the fixed HTTP/Nexus pair for
this mode. Run one backend authority per state directory. Keep the intended
test group on the private VPN described there; current preservation login does
not verify Steam authentication tickets.

Copy `instance-supervisor.env.example` to
`/etc/nebula-preservation/instance-supervisor.env`, replace the advertised
documentation address with the host's reachable IPv4, and set all three hashes
from the packaged build report and actual artifacts. The build report sits at
`mirror-server/build-linux-validation.json`, one level above the ELF folder.
The supervisor verifies those exact pins before starting anything.

Install `nebula-managed-http.service.in` as
`/etc/systemd/system/nebula-managed-http.service` and
`nebula-instance-supervisor.service` in the same systemd directory. Stop the
older fixed services if they use these ports/state. Start managed HTTP first,
check `/preservation/health` and `desired-instances.json`, then run the
supervisor's dry-run command with the selected paths/hashes. Start the
supervisor service after the plan matches the configured state. No supplied
script installs, enables or starts these units automatically.

The supplied unit explicitly allows all 35 source-backed server scene names:
the four reviewed public scenes and the 31 case-exact personal-space scene
values. This is a server-process admission allowlist, not a claim that an
unpatched or arbitrary native client can render every scene or that original
online-service parity has been recovered.

Managed-mode account creation grants only the documented default `Home` under
the authored preservation policy. Every other apartment still requires an
explicit administrator entitlement/binding to its owner before the backend can
publish a personal instance. Existing accounts retain their explicit bindings.
Each owner's apartment gets a distinct stable instance and leased port when
requested; an idle instance can stop and restart with the same durable layout
and identity.
