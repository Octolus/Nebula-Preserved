# Authenticated TLS source profile

This source profile connects Windows clients to one operator-controlled Linux
host. The host may be local, on a LAN or later hosted elsewhere. It requires no
particular hosting provider. Preparing or building this source does not start a
server, modify Steam, create an account, install a certificate or enable a unit.

The backend's default remains `public_access=False`. This profile explicitly
adds `--public-access` and keeps HTTP and raw scene listeners on loopback. HTTPS
carries account API requests; a separate authenticated TLS gateway carries the
historical Mirror/Telepathy scene stream. Only HTTPS 443 and gateway 8443 need
to be reachable by players. The Windows proxy uses local ports 38080 and
28000â€“28031, so its machine cannot also host listeners on those same ports.

## What has been checked

The current backend with the account integration and narrow validated gift
recipient capability passed independent auth, migration, current-session,
resource-selection and gift checks. The full current backend suite passed 186
tests with three expected skips for private extracted/native evidence. The
gift policy rejects either-direction blocks without deleting friend rows; that
is an authored preservation rule rather than a recovered retired-server rule.

An isolated synthetic TLS fixture exercised the actual Rust `api()`/`game()`
functions, backend handler, gateway and account authority: authenticated
encrypted bootstrap/allocation, invalid CA/hostname/token, account/GUID
binding, reconnect and revocation. Its upstream was a frame recorder/echo
fixture. It did not exercise the game's original startup, CurrentUser DPAPI,
game-owned socket checks or native multiplayer through TLS. Those remaining
checks, a final nine-artifact client bundle and Linux package acceptance are
required before activation. See `STATUS.json` and `RUNTIME-BUNDLE.md`.

## Linux preparation

The commands below are operator instructions, not actions performed by the
repository. Start from a reviewed checkout installed at `/opt/nebula-preservation`.
Use a dedicated `nebula` service account and keep operator secrets, certificates,
state and backups outside the checkout. For a new machine, install Python 3,
venv support, OpenSSL 3 and nginx using its distribution packages.

```sh
cd /opt/nebula-preservation
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
```

Create `/var/lib/nebula-preservation`, `/var/backups/nebula-preservation` and
`/etc/nebula-preservation/tls` with restrictive service/operator permissions.
The `nebula` account needs write access to state, read access to the gateway leaf
key/certificate, and access to the exact Linux Unity build. Keep the CA private
key and account operator key accessible only to the operator. Do not put any
of these generated files into Git or a release archive.

For a new empty state directory only, initialize the core SQLite schema:

```sh
NEBULA_STATE_DIR=/var/lib/nebula-preservation
.venv/bin/python - "$NEBULA_STATE_DIR" <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, 'backend')
from state import Store
path = Path(sys.argv[1]) / 'preservation.sqlite3'
if path.exists():
    raise SystemExit('Existing database: skip this new-state bootstrap')
store = Store(path)
store.close()
PY
```

For existing state, stop its writers before an upgrade and retain its database
and snapshots. Run the additive credential migration through its backup wrapper:

```sh
.venv/bin/python tools/migrate_public_access.py \
  --state-dir "$NEBULA_STATE_DIR" \
  --backup-dir /var/backups/nebula-preservation
```

This migration adds credential/operator/migration tables. It does not seed,
reset or clear profiles, wallets, items, presets, settings, relationships,
housing, resource selections or future application tables. Keep the verified
backup and test a restore before replacing a running deployment.

## Certificate setup

Choose a stable DNS hostname that resolves to the chosen host for every player.
For private/local testing it may resolve through an operator-managed local DNS
or hosts entry. The hostname must match the certificate SAN. Use a normal
certificate chain or a private operator CA; never disable verification.

This example creates a private CA and one leaf. Run it in a private operator
directory outside the checkout. Replace the example hostname before running.

```sh
umask 077
NEBULA_TLS_HOST=preservation.example.org
openssl req -x509 -newkey rsa:3072 -noenc -sha256 -days 3650 \
  -subj '/CN=Nebula Preservation Operator CA' \
  -addext 'basicConstraints=critical,CA:TRUE,pathlen:0' \
  -addext 'keyUsage=critical,keyCertSign,cRLSign' \
  -keyout operator-ca-key.pem -out operator-ca.pem
openssl req -new -newkey rsa:3072 -noenc -sha256 \
  -subj "/CN=$NEBULA_TLS_HOST" -keyout server-key.pem -out server.csr
cat > server-extensions.conf <<EOF
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=DNS:$NEBULA_TLS_HOST
EOF
openssl x509 -req -in server.csr -CA operator-ca.pem -CAkey operator-ca-key.pem \
  -CAcreateserial -days 365 -sha256 -extfile server-extensions.conf -out server.pem
cat server.pem operator-ca.pem > fullchain.pem
openssl x509 -in operator-ca.pem -outform DER -out operator-ca.der
openssl verify -CAfile operator-ca.pem -verify_hostname "$NEBULA_TLS_HOST" server.pem
sha256sum operator-ca.der
```

Install only `fullchain.pem` and `server-key.pem` where the nginx/gateway
templates expect them. Give players the public `operator-ca.der` and its exact
lowercase SHA-256 through a trusted channel. Keep `operator-ca-key.pem` private
and off the player/server package. Renew leaf certificates under the same CA
before expiry. Changing the root requires reconfiguring each player's CA pin.
No global Windows trust-root installation is used.

## Account provisioning and revocation

The server authenticates a per-account preservation credential. This does not
validate a Valve ownership ticket. The client keeps the game's original Steam
initialization and ownership path. Each player supplies the account identifier
used by that original client; do not share one credential between accounts.

Create a random operator key once in a private operator directory. It must be a
regular non-symlink file with mode 0600, owned by the invoking account or root.
The initialized operator key is required for provisioning, issuing and revoking.

```sh
umask 077
openssl rand -out /etc/nebula-preservation/operator-key.bin 32
chmod 0600 /etc/nebula-preservation/operator-key.bin
.venv/bin/python backend/public_access_admin.py \
  --state-dir "$NEBULA_STATE_DIR" \
  --operator-key-file /etc/nebula-preservation/operator-key.bin init-operator
```

Set the following values to one player's identifier/name. The identifier must
match the supported 17-digit SteamID64 format. Initialization is a one-time
operation; an existing operator record is not overwritten.

```sh
STEAM_ID64=REPLACE_WITH_PLAYER_STEAM_ID64
DISPLAY_NAME=REPLACE_WITH_PLAYER_DISPLAY_NAME
.venv/bin/python backend/public_access_admin.py \
  --state-dir "$NEBULA_STATE_DIR" \
  --operator-key-file /etc/nebula-preservation/operator-key.bin \
  provision-account "$STEAM_ID64" "$DISPLAY_NAME"
.venv/bin/python backend/public_access_admin.py \
  --state-dir "$NEBULA_STATE_DIR" \
  --operator-key-file /etc/nebula-preservation/operator-key.bin \
  issue "$STEAM_ID64" > issued-account.json
.venv/bin/python - <<'PY'
import json
from pathlib import Path
value = json.loads(Path('issued-account.json').read_text())['authorization'].encode('ascii')
if len(value) != 85:
    raise SystemExit('Unexpected account credential length')
with Path('account-authorization.txt').open('xb') as stream:
    stream.write(value)  # Exactly 85 bytes, with no newline or JSON wrapper.
PY
```

Transfer only that player's `account-authorization.txt` privately. The patcher
requires the exact raw 85-byte ASCII value. The JSON and raw file contain a
secret: do not paste them into commands, logs, issues or the repository. A new
`issue` rotates the previous token. Revoke a player with:

```sh
.venv/bin/python backend/public_access_admin.py \
  --state-dir "$NEBULA_STATE_DIR" \
  --operator-key-file /etc/nebula-preservation/operator-key.bin revoke "$STEAM_ID64"
```

The HTTP authority rejects a revoked token on its next request. The game
gateway revalidates current credentials/allocation every two seconds and
closes an invalidated existing tunnel. Session/allocation changes similarly
invalidate an old tunnel; a new connection must claim the current GUID.

## Linux runtime configuration

Build the Linux Unity server from the current primary scene/backend source and
record the executable, managed assembly and build-report hashes. Existing
binary receipts from a private test machine are not release inputs. Set all
three exact hashes in a private copy of `nebula.env.example`.

Use these templates together:

| Source template | Operator destination |
| --- | --- |
| `nebula.env.example` | `/etc/nebula-preservation/nebula.env` |
| `nebula-managed-http.service.in` | `/etc/systemd/system/nebula-managed-http.service` |
| `../instance-supervisor/nebula-instance-supervisor.service` | `/etc/systemd/system/nebula-instance-supervisor.service` |
| `remote-gateway.env.example` | `/etc/nebula-preservation/remote-gateway.env` |
| `nebula-remote-gateway.service.in` | `/etc/systemd/system/nebula-remote-gateway.service` |
| `nginx.conf.example` | A reviewed nginx site configuration |

Replace every placeholder, verify paths/permissions, run `nginx -t` and review
`systemd-analyze verify` output before deliberately starting services. The
supervisor's exact game bind/advertisement must both be `127.0.0.1` for this
gateway profile. Gateway 8443 admits only the authenticated account's latest
session and current fresh ready allocated instance. Raw game ports must stay
private. The gateway's state directory is read-only; the backend/supervisor
write the authoritative database and descriptors.

The templates do not start or enable themselves. Complete native client/TLS
acceptance with the final source-built client bundle before opening access to
other players. For an operator-run acceptance after that review, start the
authenticated HTTP service, supervisor, HTTPS frontend and gateway explicitly.
Stopping the gateway/backend does not erase durable account state.

## Windows player setup

Close the game before configuring or patching. Build the patcher from current
primary source, retaining its reviewed backup/update behavior. Supply the
reviewed remote bundle described in `RUNTIME-BUNDLE.md`; an eight-artifact
direct/local bundle is insufficient for `--remote-transport`.

The player receives a trusted release manifest hash, the operator HTTPS origin,
their own authorization file and the operator public CA DER/hash. Example
PowerShell commands, using values delivered by the operator:

```powershell
$server = 'https://preservation.example.org'
$caHash = 'REPLACE_WITH_EXACT_LOWERCASE_CA_DER_SHA256'
$manifestHash = 'REPLACE_WITH_REVIEWED_REMOTE_MANIFEST_SHA256'
.\nebula-patcher.exe configure-public --server $server --authorization-file .\account-authorization.txt
.\nebula-patcher.exe configure-remote --server $server --ca-file .\operator-ca.der --ca-sha256 $caHash
.\nebula-patcher.exe discover
.\nebula-patcher.exe patch --bundle .\remote-bundle --manifest-sha256 $manifestHash --server $server --advertise-ip 127.0.0.1 --remote-transport --dry-run
```

The dry run validates inputs without writing game files. The operator must
provide a reviewed frozen bundle before the player runs the same patch command
without `--dry-run`. For an initial installation on an already modified client,
follow the current patcher README's original-input requirements. Existing
verified installations use their trusted backup/update path; these instructions
do not replace that behavior. The patcher discovers Steam libraries and never
launches the game. Launch through Steam only after successful installation.

The patcher stores the credential with Windows CurrentUser DPAPI and restrictive
per-user ACLs. It writes fixed public/remote profiles and the public CA beneath
`%LOCALAPPDATA%\NebulaPreservation`. Delete or securely retain the transferred
plaintext authorization file according to the operator's local policy; the
patcher does not silently remove it.

The importing game starts the hash-pinned sibling `NebulaRemoteTransport.exe`
on its first reviewed backend request after original Steam startup. The helper
assigns a kill-on-close job, waits for a PID/creation-time readiness event and
then calls the original request. The sidecar checks its exact original game
parent and accepts local sockets only from that game. Starting it manually is
unsupported. It uses the exact configured CA root, normal hostname/chain
validation, no redirects and no ambient proxy. Closing the game ends its
owned sidecar.

For a deliberately rotated token/root, close the game and use the patcher's
`reset-remote-config` / `reset-public-config` commands before reprovisioning in
the same order. Resetting these profiles does not restore game files; use the
current patcher `restore`/`recover` commands when appropriate. Keep the original
game and preservation backup data until recovery has been verified.
