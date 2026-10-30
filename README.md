# Nebula Preserved

### Reconstructing the services behind Nebula Realms.

A community preservation project for the Windows Steam client: accounts,
characters, items, social features and persistent worlds, hosted on Linux.
The separate operator dashboard uses Astro, React and shadcn/ui.

**[Quickstart →](deployment/bootstrap/README.md)** ·
[Administration](admin-panel/README.md) ·
[Ubuntu automation](deployment/ansible/README.md) ·
[Windows launcher](docs/LAUNCHER.md) ·
[Moderation](docs/MODERATION-OPERATIONS.md) ·
[Item catalog](docs/CATALOG.md) ·
[Client patching](client-patches/network-only/README.md) ·
[Project status](docs/PROGRESS.md) ·
[Rust server candidate](experimental/rust-server/README.md) ·
[Contributing](CONTRIBUTING.md)

> **Development snapshot.** This is not a completed multiplayer release.
> Native public-client login, final shared-server acceptance, apartment flows
> and equipped-resource reconciliation still need verification. The
> [status matrix](docs/PROGRESS.md) records the evidence and remaining work.

<details>
<summary>Operator dashboard preview</summary>

![Nebula operator dashboard overview using synthetic accounts](docs/images/admin-panel.png)

*Dashboard shown with disposable test data.*

</details>

## What is being preserved

| Service | Reconstruction |
|---|---|
| Accounts and characters | Replacement accounts, avatar presets, customization and saved preferences |
| Items and stores | Inventory, local wallets, catalog offers, purchases and audited operator grants |
| Social and worlds | Friends, chat, invitations, scene allocation and apartment ownership/layouts |
| Administration | Player lookup, credits, grants, purchase history, moderation, reports, roles and audit records |

Historical native tests demonstrated two clients in Nexus, public/private chat,
friendship, character/settings persistence and one store purchase. Linux Docker
and the panel have passed isolated synthetic runtime, persistence and TLS
boundary checks. Those results do not establish complete original-client
connectivity through the final distribution. The target is the original
networking and persistent state; minigame integration remains deferred in the
current snapshot. See the status matrix for incomplete flows.

The default client patch changes networking compatibility and server routing.
It retains the shipped interface, input and rendering. Original cosmetic/gameplay
bugs remain outside this project's networking scope. Optional input experiments
are documented separately in [controls](docs/CONTROLS.md).

## Start a server

Use a dedicated **Ubuntu 26.04+ x86_64** host and a prepared, reviewed runtime
release. Copy that release to the server through your verified SSH connection,
then run the [one-command installer](deployment/bootstrap/README.md) as root:

```sh
python3 /path/to/reviewed-release/deployment/bootstrap/deploy.py install \
  --release /path/to/reviewed-release --public-ip YOUR_SERVER_IPV4
```

The installer installs Docker/Compose and Ansible as needed, checks and loads
the release, creates private operator credentials, and configures persistent
boot services and daily verified backups. It obtains a publicly trusted Let's
Encrypt certificate for the server's IPv4 address through HTTP-01 and enables
hourly renewal. The default launcher uses system trust; no manual CA import or
certificate-hash editing is required on this public path.

The public address must belong to the server. Allow inbound TCP 80 for certificate
validation, 443 for the dashboard, and 8443/8444 for players, including in the
provider firewall. The source checkout alone cannot supply a runtime release:
operators need matching, lawfully prepared Unity runtime and image artifacts.

The current installer completed with 41 successful tasks, 11 changed and no
failures. Fourteen external checks passed using default system certificate
trust, including API/dashboard access with retained credentials, certificate
SAN/chain checks on all three TLS ports, ALPN and 35 closed internal ports.
The renewal service also completed with no runtime-file changes or TLS sidecar
refresh, leaving active connections undisturbed. A repeat installation passed
with 40 successful tasks, one changed and no failures. An actual reboot restored
all boot services, retained authority/TLS
files and preserved all 48 durable table fingerprints. Final native client/UI
acceptance remains pending. These deployment checks do not establish gameplay.

For manual Compose operation or an explicit private profile, see the
[Docker instructions](deployment/docker/README.md#pull-published-images-from-ghcr)
and [Ansible operations](deployment/ansible/README.md).

Building images yourself instead requires the complete matching Linux Unity
server build and validation report. The [setup guide](docs/SETUP.md) covers
preparing those inputs from source.

Runtime hosting does not require host Unity, Python, Node or Rust installations
when using the complete images. This source checkout contains no generated
Unity runtime, game assets, player database or credentials.

| Deployment | Boundary |
|---|---|
| Docker private profile | Loopback only; explicitly configure a trusted LAN/VPN for other players |
| Installer public profile | Per-account credentials, explicit auth migration and automatic publicly trusted TLS |
| Operator panel | Manual Docker binds loopback by default; installer exposes the dashboard through TLS; internal management API remains unpublished |

There are no default passwords. The installer creates private secrets; manual
Compose setup requires bootstrapping them with the documented UID 1000
permissions. Keep the named state volume and separate secrets across upgrades;
see [backup and lifecycle guidance](deployment/docker/README.md#lifecycle-and-health).

The installer needs a prepared release and reachable public ports. Manual
Compose operation additionally needs matching image/runtime metadata,
configuration and secrets. Keep the named state volume across either path.

## How it fits together

| Component | Stack | Source |
|---|---|---|
| Account, inventory, shop, social and persistence services | Python · aiohttp · SQLite | [backend](backend/) |
| Reconstructed scene servers | C# · Unity · Mirror v66.0.9 / Telepathy | [mirror-server](mirror-server/) |
| Operator dashboard | Astro SSR · React · shadcn/ui | [admin-panel](admin-panel/) |
| Hosting and ingress | Linux · Docker Compose | [deployment/docker](deployment/docker/) |
| Steam discovery, patching and restore | Rust | [patcher](patcher/) |
| Networking compatibility | Native/managed patch recipes | [client-patches](client-patches/) |
| Recovered contracts | Manifests and protocol research | [protocol](protocol/) |

The matching client is Steam app **919290**, build **11018722**. Players supply
their own installation. The networking-only patcher uses exact version/hash
checks, backups and receipt-backed restore; no complete game is distributed.

Mirror provides historical framing and serializers. Game-specific services are
reconstructed from shipped behavior. Publisher server code, historical accounts,
retired service data and original store policy were not recovered. Replacement
credits and offers use explicit local policy; real Steam commerce is disconnected.

## Work on the project

Start with [setup](docs/SETUP.md), [testing](docs/TESTING.md) and
[contribution guidelines](CONTRIBUTING.md). Review [security](SECURITY.md) and
[privacy](docs/PRIVACY.md) before sharing logs or operating a server.
[Releases](docs/RELEASES.md) and [publication checks](docs/PUBLISHING.md) describe
the separate source, image and client-bundle gates.

Original project contributions are licensed under [MIT](LICENSE). Vendored
components retain their [upstream terms](THIRD_PARTY_NOTICES.md); this license
does not cover the original game or grant rights to its assets. See
[licensing scope](docs/LICENSING.md) for the source and release boundaries.
Publication workflows are provided; assembling this checkout has not executed
them remotely or published a repository, image or patch bundle.
