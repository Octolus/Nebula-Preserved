# Linux setup and administration

The server deployment target is Linux x86_64 using [Docker Compose](../deployment/docker/README.md). Windows is the Steam client target. Historical Windows local launch scripts are retained as research/developer material; they are not the hosting quickstart. Start with the [status matrix](PROGRESS.md) for current native-client limits and [releases](RELEASES.md) for distribution requirements.

## Deployment

Docker automatically fills the [complete validated item catalog](CATALOG.md)
using preservation stores and prices while retaining existing offers and player
state. The dashboard separates game assets, store offers and recovered shop
artwork; original commercial metadata remains explicitly unknown.

Follow the [Docker quickstart](../deployment/docker/README.md#pull-published-images-from-ghcr) for published images, Docker-only operator-secret bootstrap, private/public profiles and persistent state volume. Image availability depends on a reviewed publisher build. `configure-image.sh` pulls an explicit image pair and creates new digest-pinned `runtime.env` metadata from its verified matching revision and build labels. The containers include their Python/Node/runtime dependencies; do not install Unity on the hosting machine merely to run already-built images.

For local image builds, supply the complete validated Linux runtime described below. The same report, ELF and managed-assembly hashes remain mandatory in either path. Treat `runtime.env` as Compose data, not a shell script; use the documented ordered `--env-file` arguments.

No default password or token is supplied. Create your own private secret files and ensure container UID 1000 can read them without granting other users access. Keep the management listener unpublished. The [security notes](../SECURITY.md) explain those boundaries.

The default private profile listens on host loopback. For a trusted LAN or VPN, configure the published bind and the concrete address other clients can reach. Each player's `localhost` means that player's own machine. The panel's browser-facing origin must match its configuration exactly. Keep the management listener internal; it is not a public API.

Public mode requires an explicit auth-schema migration, per-account credentials and operator-managed TLS. See the Docker-only named-volume provisioning recipe. Public-server boundary tests and the native client adapter are separate acceptance gates. The networking-only source repairs the stripped-Unity compatibility issue through its owned TLS proxy and includes the previously missing central HTTP request path. Original-client acceptance is still required before calling public-client connectivity ready.

## Prepare the Linux Unity runtime

Build maintainers need the project's pinned Unity6000.6.3f1 editor and Linux Dedicated Server support. The runtime containers do not need an editor or editor license. Use the [Linux build instructions](../mirror-server/README.md); the portable Python build command is:

```sh
python3 mirror-server/build_linux.py --unity /path/to/Unity --build
```

Keep the entire generated `build-linux/` directory and `build-linux-validation.json`. Copy them to `deployment/docker/private-linux/build/` and `deployment/docker/private-linux/build-linux-validation.json`. Set the report, executable and managed-assembly hashes in the private environment file. Startup validates the complete artifact inventory and the supervisor's admission rules; copying an executable alone is insufficient.

Builds must match the selected source. Do not use an unrelated old report to validate new C# changes. The source tree contains the pinned Mirror version; upgrading Mirror is not a shortcut to restoring the original protocol.

## Player administration

Use the [Astro panel](../admin-panel/README.md) to find an account, inspect its wallet and purchases, adjust crystals/Nebula Points, grant catalog items and manage panel access. Every change is authorized and audited. Moderator is read-only; it does not grant an unproven game staff flag. A cached game screen may require reopening or rejoining to display a changed balance or item.

Private login creates replacement accounts from the supplied identifier. Historical accounts and personal runtime data are not shipped. The private profile does not verify Valve tickets; restrict it to its trusted network boundary. Public credentials are provisioned explicitly through the documented auth utilities.

Take a consistent backup before migrations or bulk administration. Keep the state volume and secrets across upgrades. Do not use `docker compose down --volumes` as a restart command.

## Client patching

Supply your own matching Steam app919290/build11018722 installation. Build the Rust patcher and the [networking-only payload](../client-patches/network-only/README.md) using their instructions. The six-artifact direct profile and seven-artifact remote profile use explicit version/hash checks and receipt-backed restore. Remote payload assembly does not establish that its native TLS path is functional.

The default patch does not install keyboard aliases, alter the mouse or repair cosmetic game bugs. Optional experiments are documented separately in [controls](CONTROLS.md). Checking out this source does not modify Steam files. Keep original backups, and validate restore on a disposable copy before sharing a bundle. Full game files are never part of a patch release. Follow [publication checks](PUBLISHING.md) before sharing source or artifacts.

## Development checks

For backend work outside containers:

```sh
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r backend/requirements.txt
python3 -m unittest discover -s backend/tests -p 'test_*.py'
```

For the panel use its lockfile, type checks, security tests and explicit synthetic browser fixture. See [native testing](TESTING.md) for original-client callbacks and multiplayer acceptance. Docker and HTTP tests do not replace those checks.
