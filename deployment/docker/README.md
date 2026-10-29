# Linux Docker hosting

Host the preserved networking services on Linux x86_64 using Docker Compose.
It leaves the original game's UI unchanged. The separate Astro SSR panel is
included as the `panel` service; its management contract is documented below. There is no
Unity Editor, Unity licence, WSL or host Python prerequisite for the containers.
Docker Engine and the Compose plug-in are host prerequisites. Compose >=2.24.4
is required for the public port-list replacement.
The server and panel Dockerfiles pin their tested Python 3.12 and Node 24 base
image digests. `requirements.lock.txt` pins all resolved server Python packages;
the panel uses its committed npm lockfile. Rebuild and retest when updating them.

## Pull published images from GHCR

This path uses published server and panel images without a local Unity or image
build. Registry publication and the publisher's Unity licensing setup are release
prerequisites; these instructions do not claim that an image has already been
published for your repository.

From `deployment/docker/`, copy `.env.example` to a private `.env` and set
`NEBULA_IMAGE_PREFIX=ghcr.io/owner/repo` to your lowercase repository prefix.
The images are named `ghcr.io/owner/repo-server` and
`ghcr.io/owner/repo-panel`. `NEBULA_IMAGE_TAG` defaults to `latest` from the
default branch; prefer a matching `sha-<40-character-commit>` or release version
for a repeatable deployment.

Resolve the published images and their build metadata without downloading a
GitHub Actions artifact:

```bash
bash ./configure-image.sh ghcr.io/owner/repo latest
```

Replace the prefix with your publisher's repository. The helper pulls images but
starts no application. It requires Linux/amd64 images, three valid server build
hash labels and the same source revision on both images. A partially published
pair fails closed; wait for publication to finish and retry. It creates a new
mode-600 `runtime.env` containing the report, ELF and managed-assembly hashes,
source revision and immutable server/panel digest references. Existing metadata
is never overwritten. These image references take precedence over the tag, so a
later change to `latest` cannot silently change the selected deployment. Docker
must trust the chosen publisher; image labels do not independently establish
source authenticity.

The three build pins remain mandatory: startup verifies the complete Linux build
against its report. A stale or mismatched file fails startup. Alternatively, use
the `runtime.env` from the matching CI `linux-runtime` Actions artifact, with
its three computed pins, and explicitly select the matching image prefix/tag in
`.env`. No GitHub release asset is required by the primary helper path.

Create the operator secret files as described under **Operator credentials**
below. Compose reads `.env` followed by `runtime.env` as data; do not execute or
shell-source either file. Then validate, pull and start:

```bash
docker compose --env-file .env --env-file runtime.env \
  -f compose.yaml -f compose.ghcr.yaml config --quiet
docker compose --env-file .env --env-file runtime.env \
  -f compose.yaml -f compose.ghcr.yaml pull
docker compose --env-file .env --env-file runtime.env \
  -f compose.yaml -f compose.ghcr.yaml up --no-build -d
docker compose --env-file .env --env-file runtime.env \
  -f compose.yaml -f compose.ghcr.yaml ps
```

`compose.ghcr.yaml` removes both build sections and selects the same server image
for `public-game`. It changes no state volume, credentials, UID, security setting,
health check or published port. For private GHCR packages, authenticate Docker
using an account with package-read access before pulling.

For public TLS mode, retain the existing certificate, account and gateway setup
below, set `NEBULA_MODE=public` and `COMPOSE_PROFILES=public`, and include the
public port override last in every command:

```bash
docker compose --env-file .env --env-file runtime.env \
  -f compose.yaml -f compose.ghcr.yaml -f compose.public.yaml pull
docker compose --env-file .env --env-file runtime.env \
  -f compose.yaml -f compose.ghcr.yaml -f compose.public.yaml up --no-build -d
```

The public override replaces the private host mappings; management 8090 remains
internal and raw scene ports remain behind the TLS gateway. Use the same Compose
project name and existing state volume when upgrading. Take a consistent backup,
resolve the selected pair into a new file, then use that file as the second
`--env-file` for every update command:

```bash
bash ./configure-image.sh ghcr.io/owner/repo sha-REPLACE_WITH_40_HEX_COMMIT upgrade.env
docker compose --env-file .env --env-file upgrade.env \
  -f compose.yaml -f compose.ghcr.yaml pull
docker compose --env-file .env --env-file upgrade.env \
  -f compose.yaml -f compose.ghcr.yaml up --no-build -d
```

Take the backup before `up --no-build -d`. Keep the previous metadata for
rollback. `latest` tracks main; `sha-<40-character-commit>` selects a commit, and
a repository tag `vX.Y.Z` publishes image tag `X.Y.Z` without moving `latest`.
Do not remove volumes to update an image. Switching back uses
the matching earlier image references and runtime metadata, subject to the
existing schema compatibility and backup requirements.

Compose's [reset/override rules](https://docs.docker.com/reference/compose-file/merge/)
and [ordered environment files](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/)
describe these two deployment mechanisms.

## Build images from source

Build only from the **complete repository**, including current
backend network/persistence fixes, management API and Linux supervisor. The
Dockerfile copies the repository source and supplied runtime directly.

The operator supplies the **complete matching reviewed Linux Unity build** in
the Git-ignored `deployment/docker/private-linux/` directory:

```
private-linux/
  build-linux-validation.json
  build/
    NebulaServer.x86_64
    NebulaServer_Data/Managed/Assembly-CSharp.dll
    ... every other generated runtime file and native plug-in ...
```

Retain the original relative paths. The existing build report and three explicit
SHA-256 pins are mandatory. Startup reuses the final supervisor's ELF admission
and verifies every report artifact. The runtime must match the server source being deployed. Verify its build
report and compiled-source hashes before distribution. No build output is included in Git.

The adjacent `Dockerfile.dockerignore` automatically applies to this build
without replacing the repository's existing root ignore file. It deliberately
includes only backend, protocol, tools and this private runtime payload; state,
credentials, keys, original game installations and work archives are excluded.
The image builds directly from the repository backend, protocol and tools.

## Operator credentials

From `deployment/docker/`, copy `.env.example` to `.env` if it does not already
exist. For source builds, set the report, ELF and assembly hashes to the matching
build report values; the GHCR path reads them from `runtime.env`. Create the panel credentials
using only Docker and Bash; Node is not required on the host:

The following first-start recipe requires a **new** `secrets/` directory. It
refuses an existing directory or symlink; never use it to change permissions on
an existing credential set. Its short root container checks that the mounted
directory is still empty and changes only that directory's ownership/mode. The
bootstrap then creates credentials as the services' UID/GID 1000. This works
when the host operator is root as well as a regular user, on a standard rootful
Docker Engine without user-namespace remapping. For rootless/remapped Docker,
arrange the equivalent host UID mapping first. The Node image digest matches
the panel's pinned base image.

```bash
(
set -euo pipefail
umask 077
[[ ! -e secrets && ! -L secrets ]] || {
  printf '%s\n' 'secrets already exists; preserve it and review its ownership instead.' >&2
  exit 1
}
mkdir -- secrets
node_image='node:24-bookworm-slim@sha256:c86ecead9e55a5210ac1727de38a4ca840bf03dcaf34dc9749addbf383b1920c'
docker run --rm --network none --read-only --user 0:0 \
  --cap-drop ALL --cap-add CHOWN --cap-add FOWNER --cap-add DAC_OVERRIDE \
  --security-opt no-new-privileges:true \
  -v "$PWD/secrets:/secrets" \
  "$node_image" /bin/sh -ec '
    test -d /secrets && test ! -L /secrets
    entries=$(find /secrets -mindepth 1 -maxdepth 1 -print -quit)
    test -z "$entries" || { echo "secrets must be empty" >&2; exit 1; }
    chmod 0700 /secrets
    chown 1000:1000 /secrets
  '
trap 'unset panel_password' EXIT
IFS= read -r -s -p 'Panel password: ' panel_password
printf '\n'
printf '%s' "$panel_password" | docker run --rm -i \
  --network none --read-only --user 1000:1000 --cap-drop ALL \
  --security-opt no-new-privileges:true \
  -v "$PWD/../../admin-panel/scripts:/bootstrap:ro" \
  -v "$PWD/secrets:/secrets" \
  "$node_image" node /bootstrap/bootstrap.mjs \
  --dir /secrets --owner server-owner --password-stdin
unset panel_password
)
```

This creates `admin-token.txt`, `admin-operators.json` and
`panel-session-key.txt` with mode 0600, without printing their secrets. It refuses
to overwrite an existing credential set. Choose a unique password of at least
14 characters; no default password is provided. The containers run as UID 1000:
files and their directory must remain readable/traversable by that UID. Keep
keys inaccessible to other users.
File-backed Compose secrets preserve host permissions rather than remapping them.

Keep optional TLS leaf certificates and private keys in `secrets/` too. Keep CA
private keys outside containers. Passwords and tokens belong in these ignored
files, never in `.env`, shell arguments or image layers.

For a source build, validate and start with:

```bash
docker compose config --quiet
docker compose up --build -d
docker compose ps
docker compose logs --tail=100 server
```

For published images, use the pull-only commands above instead.

For the maintenance commands below, define this Bash array in each new terminal
so backups, one-shot tools and restarts keep the same image and runtime metadata:

```bash
compose=(docker compose --env-file .env --env-file runtime.env \
  -f compose.yaml -f compose.ghcr.yaml)
# Source-built deployment instead: compose=(docker compose --env-file .env -f compose.yaml)
# Already in public TLS mode? Also append: compose+=(-f compose.public.yaml)
```

Use your selected metadata filename in place of `runtime.env` after an upgrade.
Keep the same project name; an explicit `-p` must be present in this array too
if you used it at first start.

The default private profile publishes HTTP `127.0.0.1:8080` and raw scene TCP
ports `127.0.0.1:28000-28031`. Local clients use advertised `127.0.0.1`. For a
trusted LAN/VPN, explicitly set both `NEBULA_HOST_BIND` and the reachable concrete
`NEBULA_ADVERTISE_IP`; this private profile has no per-account credential gate.
Keep it restricted to that trusted group. Fixed test-account shortcuts are not
enabled. The management port 8090 is never published.

`docker compose stop` preserves the named `state` volume, including SQLite,
avatars, inventory, settings, apartment layouts, account credentials and runtime
files. `docker compose down` also preserves that named volume. `down --volumes`
deliberately deletes it; do not use that command to upgrade or restart.
Create a consistent online SQLite backup using Docker only:

```bash
"${compose[@]}" exec -T server python tools/backup_state.py \
  --state-dir /var/lib/nebula \
  --destination /var/lib/nebula/backups/manual --keep 14
```

This backup remains inside the same volume. Securely copy backups off that volume
for disaster recovery and retain the separate credential and TLS secret files.
Alternatively, stop the complete stack and back up its state volume. Retain a
backup before schema migration or version upgrades. No image build seeds or
resets accounts.

## Optional starter shop catalog

A fresh database does not contain a complete store catalog. After building the
server image and preparing `.env` and secrets, you can explicitly create the
small local preservation catalog below. Run these commands from
`deployment/docker/`, using the **same Compose project name and `.env`** as your
server so they select its intended `state` volume. Keep all stack applications
stopped while changing the catalog. The subshell aborts on any failed config,
stop, preview, backup or seed command; it will not continue to a later write or
restart after that failure.

```bash
(
set -eu
"${compose[@]}" config --quiet
"${compose[@]}" stop

# Preview only: this uses temporary state, not a diff of your existing database.
"${compose[@]}" run --rm --no-deps --entrypoint python server \
  tools/seed_local_shops.py

# Back up an existing database first; a new empty volume has nothing to back up.
# The shell stops on a backup error before the explicit seed runs.
"${compose[@]}" run --rm --no-deps --entrypoint /bin/sh server -ec '
  if [ -f /var/lib/nebula/preservation.sqlite3 ]; then
    python tools/backup_state.py --state-dir /var/lib/nebula \
      --destination /var/lib/nebula/backups/pre-shop-seed --keep 14
  fi
  python tools/seed_local_shops.py --state-dir /var/lib/nebula --apply
'

"${compose[@]}" up --no-build -d
)
```

The one-shot containers replace the server entrypoint and start no backend,
Unity scene or listener. They can initialize the shop tables in a new empty
volume. The backup remains inside the same volume; securely copy it off-volume
if you need disaster recovery. No command deletes or resets the state volume.

With the current manifests, the applied JSON result lists **four shops and 15
offers**: eight clothing, two companions, two furniture, two locomotions and one
companion-plus-locomotion bundle with two child offers. The item IDs and
thumbnails come from the shipped manifests. Labels and prices are authored local
preservation policy, not recovered publisher prices:

| Offer kind | Crystals | NP |
|---|---:|---:|
| Clothing | 25 | 10 |
| Companion | 40 | 20 |
| Furniture | 30 | 15 |
| Locomotion | 35 | 15 |
| Companion + locomotion bundle | 60 | 25 |

The commands deliberately omit `--account-id` and starter balance flags. They
create no account, wallet balance, item ownership or apartment ownership.
Configure an existing account's credits separately through the owner/admin panel
when desired; a catalog entry alone does not make an item owned. The seed tool's
optional account/balance flags **set an absolute balance**, so do not add them
when preserving an existing wallet.

Re-seeding reuses stable offer IDs and does not duplicate purchases or grants.
It does update those named local shops/offers to this tool's labels, prices and
visibility, and adds or updates its two expected bundle links. It does not prune
additional operator rows or links. Back up first and avoid re-seeding over
deliberate edits to those entries. Unrelated operator shops and offers are
retained. Inspect the returned plan before applying a different tool version.

The server reads configured shop rows from SQLite for requests. Start the full
stack after seeding, then reopen an already displayed in-game shop so the client
requests fresh rows. This setup supplies a small representative catalog; it is
not a claim that every historical store or native store screen has been tested.

## Optional public TLS ingress

First provision the existing explicit public-access schema migration and account
credentials through the reviewed offline/admin utilities, preserving existing
state and taking a backup. Startup never silently performs that auth migration.
Provide a valid operator-managed leaf certificate matching the hostname used by
the patched client, and its private key. The current client may use an explicit
private CA provisioned by the reviewed patcher. Public trust is not bypassed.

The following commands run offline tools in the already built backend image.
First stop the complete stack and keep its named state volume. A newly empty
volume must have been initialized by a private start before this migration.
These one-shot commands replace the image entrypoint, so they do not start the
backend, supervisor or listeners. Use the same Compose project name and `.env`
for all commands to select the same volume.

```bash
(
set -eu
"${compose[@]}" config --quiet
"${compose[@]}" stop
"${compose[@]}" run --rm --no-deps --entrypoint python server \
  tools/migrate_public_access.py --state-dir /var/lib/nebula \
  --backup-dir /var/lib/nebula/backups/pre-public
)
```

Create a separate operator authority key once. It is distinct from panel
credentials and is not needed by the running services:

```bash
"${compose[@]}" run --rm --no-deps --user 1000:1000 \
  -v "$PWD/secrets:/operator-secrets" \
  --entrypoint python server -c \
  'import os,secrets; p="/operator-secrets/operator-key.bin"; f=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600); os.write(f,secrets.token_bytes(48)); os.close(f)'
"${compose[@]}" run --rm --no-deps --entrypoint python \
  -v "$PWD/secrets/operator-key.bin:/operator-key:ro" server \
  backend/public_access_admin.py --state-dir /var/lib/nebula \
  --operator-key-file /operator-key init-operator
```

Provision each real account using its operator-verified identity, then issue its
credential. Replace both placeholders before running. The issue output contains
a plaintext authorization credential exactly once; save it privately for the
client patcher and do not commit or paste it into logs:

```bash
steam_id='REPLACE_WITH_STEAM_ID64'
account_name='REPLACE_WITH_ACCOUNT_NAME'
"${compose[@]}" run --rm --no-deps --entrypoint python \
  -v "$PWD/secrets/operator-key.bin:/operator-key:ro" server \
  backend/public_access_admin.py --state-dir /var/lib/nebula \
  --operator-key-file /operator-key provision-account "$steam_id" "$account_name"
"${compose[@]}" run --rm --no-deps --user 1000:1000 --entrypoint /bin/sh \
  -v "$PWD/secrets:/operator-secrets" server -ec '
    umask 077
    set -C
    python backend/public_access_admin.py --state-dir /var/lib/nebula \
      --operator-key-file /operator-secrets/operator-key.bin issue "$1" \
      > /operator-secrets/account-credential.json
  ' issue-account "$steam_id"
```

The final command creates an exclusive mode-600 credential file as UID 1000
inside the ignored secret directory. It refuses to overwrite that filename;
choose a separate private file for another account. To revoke a credential, run
the same Python utility with `revoke "$steam_id"` in place of `provision-account`
and its account name. Revocation changes authority state; it does not
reset character, wallet, inventory or apartment records. Keep a verified state
backup before upgrades. The migration tool takes a consistent pre-migration
backup in the requested directory and refuses a missing source database.

The public server and TLS gateway have passed isolated protocol tests. The
current networking-only client source repairs the two stripped Unity API
dependencies and reproduces the reviewed direct six-artifact and remote
seven-artifact bundles. Native remote client acceptance remains **pending**;
these server and source-build results do not establish that the patched game can
complete its application login and join flow.

Set `.env`:

```
COMPOSE_PROFILES=public
COMPOSE_FILE=compose.yaml:compose.public.yaml
NEBULA_MODE=public
NEBULA_HOST_BIND=0.0.0.0
NEBULA_ADVERTISE_IP=127.0.0.1
```

Append `compose+=(-f compose.public.yaml)` to the selected array if it is not
already present. Then validate and recreate the stack without building:

```bash
"${compose[@]}" config --quiet
"${compose[@]}" up --no-build -d
```

The public override publishes **only** HTTPS 8444 and authenticated game TLS 8443.
It replaces private HTTP/raw scene mappings. The backend and raw scene listeners
use internal loopback, as required by the existing credential gateway. HTTPS
and game TLS share that namespace through `network_mode: service:server`;
neither sidecar gets Docker socket access or privileges. The public HTTPS
proxy forwards the Authorization header and the backend authenticates it.
The game gateway independently validates account/allocation before proxying.
Each HTTP proxy also checks the actual backend's `public_access` health flag
before starting, so selecting the wrong ingress profile fails closed.

Configure DNS/firewall/reverse-proxy endpoint forwarding deliberately. The
patcher must target the configured HTTPS URL/8444 and game gateway 8443; this configuration does not change the patcher's current endpoint assumptions. Ports
443/8443 may be used by an operator's external proxy with the appropriate TLS
setup. The admin panel remains a separate operator-facing service, preferably
bound to localhost/VPN or placed behind a trusted HTTPS frontend.

## Lifecycle and health

The runtime runs as UID/GID 1000, read-only root, dropped capabilities and
`no-new-privileges`, with a bounded tmpfs. Only `/var/lib/nebula` is writable
persistent state. The supervisor launches existing source-backed Unity scene
processes and owns their process groups; persisted PIDs are never adopted.

The entrypoint waits for backend startup, then starts the owned supervisor.
Health probes verify HTTP identity and a fresh supervisor journal, including
zero-demand states. Health does not claim rendering or networking parity.

If a previously healthy backend exits, the entrypoint first asks the still-owned
supervisor to stop. The supervisor waits for and reaps all its owned Unity
children, including a bounded wait after forced termination. Only a confirmed
zero exit without forced supervisor termination permits a replacement backend.
The entrypoint stays alive, preserving the container and ingress network
namespace. Recovery is bounded to three retries with 1/2/4-second backoff; 60
healthy seconds resets the budget. In the synthetic container test, terminating
the backend recovered existing HTTP ingress in 2.438 seconds with the same
container and network namespace, no Docker restart, and identical durable state.
Explicit character, settings and apartment saves remain the application's
persistence boundary.

Unexpected supervisor exit, uncertain cleanup, startup failure or an exhausted
retry budget parks the container unhealthy without starting a replacement
service. Unity listeners may survive an unexpected supervisor SIGKILL. Recovery
does not adopt or signal processes from persisted PID journals. Stop and recreate
the **complete** stack so Docker removes any remaining container processes:

```bash
"${compose[@]}" down
"${compose[@]}" up --no-build -d --force-recreate
```

Do not pass `--volumes`. Verify `docker compose ps`, health and ingress afterward.
A true container recreation requires its namespace-sharing ingress services to
be recreated too. `depends_on: service_healthy` orders startup and is not a
promise of transparent sidecar recovery after container replacement.

Compose stops dependent ingress/panel services before the runtime. SIGTERM stops
owned scene groups before the backend/SQLite. The container grace is 45 seconds.
This shutdown is not an application-wide save barrier: finish explicit saves
before stopping. The synthetic container test verified all 36 durable table
fingerprints survived graceful stop/restart and full-stack recreation, including
wallet, inventory, character, settings, apartment and operator records.

## Astro SSR / management integration contract

The `admin-panel/` image is a **separate service** with `PORT=4321`,
`HOST=0.0.0.0`, `NODE_ENV=production`. Bind its published port to loopback by
default; put it behind operator HTTPS for remote use. It depends on a healthy
`server` so Compose stops it before the runtime. The supplied service builds from
the final `admin-panel/` directory, publishes `127.0.0.1:4321` by default and
mounts its credentials as files at runtime.

Pass only to the SSR server, never browser JavaScript:

```
NEBULA_MANAGEMENT_URL=http://server:8090
NEBULA_ADMIN_TOKEN_FILE=/run/secrets/admin_token
NEBULA_ADMIN_OPERATORS_FILE=/run/secrets/admin_operators.json
NEBULA_PANEL_SESSION_KEY_FILE=/run/secrets/panel_session_key
NEBULA_PANEL_ORIGIN=http://localhost:4321
```

Mount the same admin token/operator registry and a separate random panel session
key as read-only secrets. The backend's in-process API uses its existing Store
and Service, listens on internal `0.0.0.0:8090`, and serves `/management/v1`.
SSR supplies Bearer authentication plus its authenticated `X-Management-Actor`;
the backend resolves roles from the operator registry. JSON writes also carry
an `Idempotency-Key` and reason. No second database authority, Docker socket,
privileged container or client-supplied role is used. The panel and backend images are built from this same source tree.

## Validation status

The composed server and panel images build successfully on Linux/amd64. The
panel passes Astro type checking, its production build and development-dependency
pruning. Image IDs, exact source/runtime inventories and resolved dependency
versions are recorded in the release build evidence. No build
output, original Unity runtime, state database or generated credential is
included in the public source tree.

The lifecycle regression tests cover bounded retry, unsafe parking, interruptible
shutdown and owned process cleanup, including real benign Linux process groups.
Config tests cover private/public port selection, internal management isolation
and wrong-mode ingress refusal. Fresh synthetic container tests verified real
demand-driven Nexus and Home Unity processes, encrypted character/settings/
two-part apartment saves, and 36-table durable persistence across stop/restart,
backend recovery and full-stack recreation. Killing the supervisor parked the
service without replacement; an actual surviving Unity process was removed by
full-stack shutdown. The production panel browser tests verified permissions,
a single credit ledger adjustment despite replay, item grant and operator
revocation.

A separate fresh public-mode test verified authenticated HTTPS account traffic,
current-session binding and a real owned Nexus allocation. Missing/wrong
credentials and cross-account requests were rejected without changing the
46-table database contents. Both TLS ports rejected the wrong CA and hostname;
only HTTPS/game TLS were published, with management and raw scene ports hidden.
The authenticated game gateway forwarded actual Mirror Spawn and pong messages,
while wrong-token, unallocated and cross-account sessions were refused. All test
applications stopped and their published ports closed after the checks. These
results cover server protocol boundaries; native multiplayer and native
public-client application acceptance remain separate results.

Docker contracts: [startup ordering](https://docs.docker.com/compose/how-tos/startup-order/),
[service settings](https://docs.docker.com/reference/compose-file/services/),
[secrets](https://docs.docker.com/compose/how-tos/use-secrets/).
