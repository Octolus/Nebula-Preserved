# Nebula Preserved

### Community servers for Nebula Realms.

Nebula Realms is a social virtual world on Steam: you make a character, dress
it up, decorate apartments, meet friends in shared worlds and play minigames.
The game cannot do any of that without its online services. Nebula Preserved
rebuilds those services as open-source software, so the game can be played
again on servers run by the community.

You play with your own Steam copy of the game. A small launcher points it at a
community server; the game itself, its look and its controls stay exactly as
they were.

**[Play](#play) · [Host a server](#host-a-server) · [How it works](#how-it-works) ·
[Project status](docs/PROGRESS.md) · [Contributing](CONTRIBUTING.md)**

> **Early test phase.** People are playing on a community server, but not every
> feature has been confirmed against the original game. Expect bugs, and keep
> backups if you run a server. The [status page](docs/PROGRESS.md) tracks what
> has been checked and what hasn't.

## What works

| Area | Status |
|---|---|
| Login and characters | Automatic sign-up with your Steam account, character creation, wardrobe and saved outfits |
| Worlds | Nexus and 14 other public worlds, started on demand, with other players visible and chat |
| Friends and social | Friend lists, online status, private and public chat, invitations |
| Shop and items | Full item catalog, wallets, purchases and inventory |
| Apartments | Every new player gets three starter apartments (Home, Cliff and Lake) with saved furniture layouts |
| Minigames | Partly working; still being tested |
| Server admin | A web dashboard for players, items, credits, moderation, reports and an audit log |

Only the networking is changed. Bugs and visual quirks from the original game,
such as square tree leaves in older worlds, are left as they were on purpose.

## Play

You need:

- **Windows** with **Steam** installed, running and signed in.
- **Nebula Realms** installed from Steam (app 919290). The launcher works with
  the final Steam build, 11018722.
- **The launcher** (`nebula-preservation-patcher.exe`) for the server you want
  to join. Ask the person who runs that server; community test builds come with
  the server address built in.

Then:

1. Close the game if it is running.
2. Double-click `nebula-preservation-patcher.exe`. It finds your game
   automatically; if it can't, click **Browse…** and pick `Nebula Realms.exe`.
3. Click **Start the game**.

The first start creates your account on that server from your Steam login.
Nothing else needs to be typed in: no password, server address or certificate.

**What the launcher changes:** before the game starts it swaps in a few
networking files and keeps checked backups of the originals. When you quit the
game, the originals are put back automatically. `Nebula Realms.exe` itself is
never modified. If your PC crashes mid-game, just open the launcher again and
it repairs the install first.

If something goes wrong, the launcher explains the next step. With the game
closed you can also undo everything manually:

```powershell
nebula-preservation-patcher.exe restore
```

More detail, including joining a server that gives you an account file
instead: [Windows launcher guide](docs/LAUNCHER.md).

## Host a server

A server runs on one Linux machine with Docker. A small VPS is enough for a few
friends.

You need:

- A dedicated **Ubuntu 26.04 or newer (x86_64)** server with a public IPv4
  address. 2 GB of RAM handles about three worlds at once.
- Inbound TCP ports **80** (certificate checks), **443** (dashboard) and
  **8443/8444** (players) open, including in your provider's firewall.
- A **prepared release**: the server images plus the Linux world server built
  with Unity. The world server is built from the game's own data, so it can't
  be shipped in this repository; the [setup guide](docs/SETUP.md) explains how
  to build one from your own copy.

Copy the release to the server, then run this one command as root:

```sh
python3 /path/to/release/deployment/bootstrap/deploy.py install \
  --release /path/to/release --public-ip YOUR_SERVER_IPV4 --public-enrollment
```

`--public-enrollment` lets new players sign up by themselves from the launcher.
Add `--trust-steam-id` if players should also be able to use the same account
from a second PC. Note that this trusts the Steam ID the launcher reports, so
anyone who knows a player's Steam ID could use their account.

The installer sets up Docker, the game server and the dashboard. It also gets a
free HTTPS certificate for your IP address and renews it automatically, and it
sets up daily backups. Running it again later upgrades the server and keeps all
player data.

Afterwards:

- Open `https://YOUR_SERVER_IPV4/login` for the admin dashboard. The owner
  login is generated on the server in
  `/opt/nebula-preserved/operator/panel-login.txt`; read it over SSH. There are
  no default passwords.
- Build a launcher with your server address built in and give it to your
  players (see [building the launcher](docs/LAUNCHER.md#fixed-server-community-tester-build)).

Further reading: [installer details](deployment/bootstrap/README.md) ·
[player sign-up rules](docs/ENROLLMENT.md) · [dashboard](admin-panel/README.md) ·
[moderation](docs/MODERATION-OPERATIONS.md) · [Docker without the installer](deployment/docker/README.md) ·
[Ansible](deployment/ansible/README.md) · [releases and upgrades](docs/RELEASES.md)

<details>
<summary>Dashboard preview</summary>

![Nebula operator dashboard overview using synthetic accounts](docs/images/admin-panel.png)

*Shown with made-up test accounts.*

</details>

## How it works

| Part | What it does | Built with | Source |
|---|---|---|---|
| Backend | Accounts, characters, items, shop, friends, chat and saved state | Python · aiohttp · SQLite | [backend](backend/) |
| World servers | The shared 3D worlds players walk around in | C# · Unity · Mirror | [mirror-server](mirror-server/) |
| Dashboard | Web admin panel for server owners and moderators | Astro · React · shadcn/ui | [admin-panel](admin-panel/) |
| Hosting | Installer, Docker images, HTTPS, backups | Docker Compose · Ansible | [deployment](deployment/) |
| Launcher | Finds the game, patches networking, restores originals | Rust | [patcher](patcher/) |
| Client patches | The networking changes applied to the game | Patch recipes | [client-patches](client-patches/) |
| Protocol notes | Recovered messages, item catalog and research | JSON · Markdown | [protocol](protocol/), [docs](docs/) |

The original server code was never released. Everything here was rebuilt by
studying how the shipped game talks to its servers. Original accounts, store
prices and purchase history could not be recovered, so every server starts
fresh and sets its own prices. Real-money Steam purchases are disabled.

An independent [Rust server](experimental/rust-server/README.md) that does the
same job without Unity or Python is being developed alongside; it is
experimental.

## Contributing

Start with the [setup guide](docs/SETUP.md), [testing](docs/TESTING.md) and the
[contribution guidelines](CONTRIBUTING.md). Please read [security](SECURITY.md)
and [privacy](docs/PRIVACY.md) before sharing logs: server and game logs can
contain player identifiers.

Before publishing anything, run the checks in [publishing](docs/PUBLISHING.md),
including `python scripts/audit_public_tree.py`.

## Legal

This is an unofficial fan preservation project. It is not affiliated with or
endorsed by the game's developers or publisher. It contains no game files: you
need your own copy from Steam, and the launcher only changes networking files
in your own install.

Project code is released under the [MIT licence](LICENSE). Bundled third-party
components keep their own licences ([notices](THIRD_PARTY_NOTICES.md)). The
licence doesn't cover the game or give any rights to its assets; see
[licensing scope](docs/LICENSING.md).
