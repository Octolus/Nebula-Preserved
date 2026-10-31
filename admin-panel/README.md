# Nebula administration panel

Astro server rendering with React and the shadcn/ui `dashboard-01` sidebar, cards and table components. This is a separate operator interface; it does not replace the game UI.

## Linux Docker

Use the repository's `deployment/docker/compose.yaml`. The panel talks to the backend's internal management listener. Port 8090 must remain unpublished. The default panel address is `http://localhost:4321`; set `NEBULA_PANEL_ORIGIN` to the exact browser-facing origin. Remote administration requires an HTTPS reverse proxy and a matching HTTPS origin. Do not expose the HTTP login publicly.

Create secrets once, outside Git. The [Docker instructions](../deployment/docker/README.md#operator-credentials) provide a Docker-only bootstrap command; no host Node installation is required. For development with Node 24 installed, the equivalent command is:

```sh
cd admin-panel
read -rs -p 'New operator password (14+ characters): ' password; printf '\n'
printf '%s' "$password" | node scripts/bootstrap.mjs --dir ../deployment/docker/secrets --owner server-owner --password-stdin
unset password
```

The tool creates a random service token, random session signing key and scrypt password record. It prints no secret values and refuses to overwrite existing files. Ensure container UID 1000 can read the files; keep them inaccessible to other users. Never commit this directory.

The operator file seeds backend roles on its first management startup. Subsequent role changes use the owner-only panel API, which persists and audits them. The file remains the login password source; backend `/me` is authoritative for the current role and enabled state on every request.

To create another operator: first assign its ID and role from **Panel access**, then stop the panel and add its password using the same command with `--owner their-operator-id --add-login`. Credential additions use an exclusive lock and atomic file replacement. Recreate the panel (`docker compose up -d --force-recreate panel`) afterward: file-backed Compose secrets must be remounted after replacement. The role in the credential file is only an initial seed and does not override an existing backend role. Keep at least one enabled owner. To rotate a password, stop the panel, replace only that operator's `password_scrypt` with a newly generated scrypt record, rotate the panel session key to invalidate existing sessions, then recreate the panel. Preserve backend state and the service token. If a crashed credential CLI leaves `admin-bootstrap.lock`, verify no credential CLI is running before removing that stale lock; never run multiple uncoordinated writers.

## What the panel shows

- **Overview:** headline numbers (players, online, purchases, bans, mutes, open reports), who is online, the latest purchases and staff actions. Every tile links to its page.
- **Live monitor:** players online right now and which world they are in, running worlds and anything waiting to load, server errors from the last hour, a live activity stream and the full login history with IP location.
- **Players:** search by name or Steam ID, filter online or restricted players, and open a player for:
  - **Character:** what they are wearing now, saved outfits (wear, rename, delete), game settings, friends and blocks, apartments and furniture, last location (reset when stuck) and consumables.
  - **Inventory:** owned items with photos and one-click **Give** / **Remove**.
  - **Purchases, Credits, Sessions** (start, duration, IP, location, how it ended; other players on the same IP; failed logins), **Moderation** and **History**.
- **Real-time updates:** the panel polls the server every few seconds, shows a toast for new logins, purchases, reports and staff actions, and refreshes what is on screen.
- Names replace IDs throughout: players, items, stores and staff actions are shown by name and link to their page; IDs stay as small secondary text.
- Reasons are only required for moderation and panel-access changes. Giving items, changing credits, store edits and save-data edits are one click and still audited. Destructive edits ask for a second click.
- Dark monochrome theme by default; the sidebar toggles light mode.

## Features and limits

The panel uses compact shadcn cards, tabs, selects, checkboxes and forms. At phone
widths, records become labeled cards and navigation opens in a dismissible sheet.
Choose a navigation destination to close the sheet. Player tabs wrap into two
rows with touch-sized controls; long IDs and notes wrap without widening the page.

Click a player ID from Players, credit adjustments, audit history, operator links
or a report's reporter field to open that account. Player pages have shareable
hash links and preserve the selected tab after reload and browser back/forward:

- **Summary:** server presence, wallet balances, creation, latest recorded login
  and latest avatar save. Login time means the latest session issue recorded in
  this database, not proof of a currently connected game client.
- **Inventory:** paginated ownership plus catalog search. Choose an exact entry
  to fill its grant ID and variant; grants do not charge the wallet.
- **Purchases:** recorded store purchases and offer grants, with current catalog
  prices clearly distinguished from unavailable historical paid prices.
- **Credits:** add or deduct crystals/Nebula Points and inspect this account's
  paginated before/after credit ledger.
- **Moderation:** supported ban, unban, kick, mute, unmute and owner display-label
  actions, with reasons, confirmation and optional policy expiry.
- **Activity:** account-scoped management history with expandable before/after
  details. Operator, news and report targets are not treated as player identities.

Successful changes refresh server records and the wallet shown on the page.
Changing a confirmed form clears its confirmation. Read-only roles still see
history but do not get wallet or grant forms. Game menus may cache state until
reopened or the player rejoins; a panel save does not claim an in-game refresh.

- Search players and the catalog. Paginate players, catalog, credit adjustments, operators and audit history.
- Inspect wallets and paginate owned items and store purchases, 25 records per page.
- Add or deduct crystals/Nebula Points, and grant existing catalog items or configured offers. Every change requires a reason and server-side authorization, with before/after audit data and idempotent retries.
- Moderate a player by account ID, or from their account page. Ban, unban, kick, mute and unmute controls appear only when advertised by the backend. Every command requires a reason and target confirmation; bans and mutes can have an optional UTC expiry. A successful response records committed server policy; client delivery and client UI acknowledgment are separate.
- Review and paginate player reports and moderation history. Report targets are player-supplied usernames; reporter account IDs identify reporters, not offenders. Resolving or dismissing a report changes its workflow status without automatically banning an account.
- Admins and owners can set or clear maintenance notices and publish or archive login news. Clients poll for maintenance and fetch news through their original paths; publishing does not inject a live popup or broadcast. Optional news expiry uses UTC and the server supplies the date label.
- Owners can set an optional player staff display label. It is display text received on the next original label lookup, and grants no game commands or panel permissions. Unsupported game-role and live-announcement controls stay hidden.
- Owners can explicitly link an existing operator to an existing player from **Panel access**. This establishes the backend's moderation hierarchy checks; an empty player ID unlinks it. It does not create credentials or assign a role. Assign the operator's panel role separately and use the credential CLI for its password.
- Owner: all panel management; admin: account changes, credits, grants, player moderation, maintenance and news; moderator: reads, supported player moderation and report review. Wallets, grants, display labels and owner-only operator access retain separate server authorization. Panel permissions do not confer game GM/VIP/developer privileges.
- Credit adjustments have exact before/after balances. Historical store purchases may lack original paid prices; current catalog prices are identified separately.
- The game caches some account state; an affected player may need to reopen a store or rejoin. The panel does not inject client UI or pretend a refresh occurred.

## Development and verification

Node 24 is recommended. Install exactly the lockfile:

```sh
npm ci
npm test
npm run check
npm run format:check
npm run build
```

Runtime configuration is listed in `.env.example`. All secret variables are file paths; none are browser-public variables. Production starts with `HOST=0.0.0.0 PORT=4321 node dist/server/entry.mjs`. For development use `npm run astro -- dev --background`; manage it with `astro dev status`, `astro dev logs` and `astro dev stop`.

Browser acceptance uses `npm run test:e2e` with explicit `NEBULA_E2E_URL`, `NEBULA_E2E_FIXTURE_FILE`, `NEBULA_E2E_PASSWORD_FILE` and `NEBULA_E2E_MODERATOR_PASSWORD_FILE`. It refuses fixtures without the synthetic fixture marker/account ID; the report-review case also requires a synthetic `report_id` from an actual fixture report submitted before the phase. Prepare a new disposable backend/database and private synthetic credentials first; never point this test at a real community server. Install the Playwright Chromium runtime with `npx playwright install chromium` when needed. Test artifacts are ignored.

The five browser workflows exercise actual management requests, role denial,
revocation, moderation, reports, notices, credits, item grants, replay and CSRF.
The mobile workflow additionally checks the navigation sheet, catalog-to-grant
selection, confirmation invalidation, player deep-link reload, scoped history,
tab geometry and page overflow at 320, 375, 768, 1024 and 1440 pixels. These panel
checks do not establish original game-client delivery or presentation.

Browser workflows cover login, audited mutations, moderation, idempotent replay, CSRF defenses and access revocation against explicit disposable fixtures. Browser acceptance does not establish native game networking acceptance.

The browser receives only a signed HttpOnly session and a session-bound CSRF token. The SSR service reads the internal API token from its secret file, restricts proxied routes, validates origins and bodies, and checks the current backend operator role. Sessions expire after eight hours; rotating the signing key invalidates them. Login attempts are bounded in process memory; use reverse-proxy rate limits for public HTTPS administration. No analytics, remote fonts or external avatar images are loaded.

Component sources originate from [shadcn/ui dashboard-01](https://ui.shadcn.com/blocks/dashboard), distributed under MIT. The sample company, accounts, chart data and unrelated demo navigation have been removed.

Player inventory and grant results share catalog photos, readable categories,
character labels and current store prices. Exact asset IDs remain in the item
inspector. Missing historical names are explicitly identified; names are not
inferred from opaque IDs. Unknown legacy entitlements remain visible without
being matched to a different variant or given an unrelated photo.
