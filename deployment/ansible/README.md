# Ansible deployment

This playbook installs Docker Engine and Compose on a dedicated Ubuntu 26.04+
x86_64 host, loads a reviewed local image archive, and enables the public TLS
stack and daily SQLite backups. Run Ansible from Linux or WSL. It does not build
Unity on the server or publish images. Keep operator inventories, SSH keys,
credentials, certificates and account state outside this repository.

For the normal single-command root-local installation, use the
[prepared-release installer](../bootstrap/README.md). It derives the artifact
pins, generates private deployment settings and installs Ansible automatically.
The workflow below remains available for operators deploying over SSH.

The default `nebula_tls_mode: public_acme` issues a publicly trusted short-lived
IPv4 certificate, with staging validation, a restricted HTTP responder on TCP80
and hourly renewal. Players need no operator CA on that path. Select
`private_ca` explicitly for private/test deployments that distribute their own CA.

Deployment health checks prove service startup, certificate verification and
anonymous API rejection. They do **not** prove native game login, multiplayer,
customization or apartment behavior. Native Windows-client acceptance remains a
separate release gate; see the repository status and patcher instructions.

## Prepare access and reviewed artifacts

Use a dedicated SSH key. Verify the server's SSH host-key fingerprint through a
trusted channel before adding it to your private `known_hosts`. Keep strict host
key checking enabled. The playbook neither changes SSH authentication nor embeds
a root password. A root login or a dedicated account with working privilege
escalation is required for package installation and systemd setup.

Copy `inventory.example.yaml` and `vars.example.yaml` to an operator-owned
directory outside the checkout, restrict their permissions, and replace every
placeholder. Do not commit the filled-in files. Set
`ansible_ssh_common_args: '-o UserKnownHostsFile=/private/known_hosts -o StrictHostKeyChecking=yes'`
for the host if you use a dedicated host-key file.

Prepare the complete matching reviewed Linux Unity runtime as described in
[the Docker instructions](../docker/README.md#build-images-from-source). Verify
its source hashes and artifact inventory before building. A report hash is an
integrity pin, not a substitute for reviewing the supplied build.

**The backend and the scene runtime must be deployed together.** The current
backend admits all 15 original public worlds:

- Nexus, LeafPark, Beach and Cinema
- Bowling, Dome, StoneLakeCastle, Cube, GhostTown, TheNebulianOpenHouse,
  ZeroDistrict, NebuHouseOpenHouse, WestValleyApartmentOpenHouse,
  MedievalVillage and SKL

It requires the rebuilt scene runtime, whose `NebulaCoreReadiness.publicScenes`
lists the same 15. An older runtime exits at start for the 11 added worlds.
Players who pick one of those worlds then stay on the loading screen. Never
deploy this server image with the old Linux runtime. See gap 7 in
[PROTOCOL-COVERAGE](../../docs/PROTOCOL-COVERAGE.md).

From the repository root, build the current server and panel:

```bash
docker build -t nebula-preserved-server:host-reviewed \
  -f deployment/docker/Dockerfile .
docker build -t nebula-preserved-panel:host-reviewed admin-panel
docker pull nginx:1.28-alpine@sha256:a8b39bd9cf0f83869a2162827a0caf6137ddf759d50a171451b335cecc87d236
docker save -o /private/images.tar \
  nebula-preserved-server:host-reviewed nebula-preserved-panel:host-reviewed \
  nginx:1.28-alpine@sha256:a8b39bd9cf0f83869a2162827a0caf6137ddf759d50a171451b335cecc87d236
sha256sum /private/images.tar
```

Set the archive path/hash and selected image names in your private variables.
Use unique image tags for future deployments so the selected archive and image
names identify one reviewed version. The three runtime pins are:

| Variable | Value |
| --- | --- |
| `nebula_build_report_sha256` | SHA-256 of `build-linux-validation.json` itself |
| `nebula_server_sha256` | Report field `executable_sha256` |
| `nebula_managed_sha256` | Report field `managed_assembly_sha256` |

Set `nebula_public_ip` to the host's public IPv4 address. The public path requires
TCP80 reachable from the internet and automatically issues a certificate for
that IP. The installer accepts Let's Encrypt terms and registers without a
contact email. Private-CA mode instead issues a leaf under a stable operator CA;
changing its IP requires deliberate reissuance. Never disable verification to
work around an address mismatch.

## Deploy and verify

```bash
cd deployment/ansible
ansible-playbook -i /private/inventory.yaml site.yaml \
  -e @/private/vars.yaml --syntax-check
ansible-playbook -i /private/inventory.yaml site.yaml \
  -e @/private/vars.yaml
```

The archive hash is checked on the control machine before upload. The server
startup also checks the reviewed runtime report, executable, managed assembly and
complete artifact list. No original Steam game files are uploaded by this
playbook. An interrupted or inconsistent secret setup fails closed rather than
silently generating a replacement password or CA.

Before a first listener, a network-disabled container creates a fresh database,
installs the public-access schema and initializes the private account operator
key. An existing unmigrated database is refused: stop the stack, take a verified
backup and use the explicit migration tools before retrying. Bootstrap never
silently migrates or replaces an existing operator authority.

The deployment uses `/opt/nebula-preserved`, Compose project
`nebula-preserved`, and persistent volume `nebula-preserved_state`. Application
containers run as UID/GID 1000 with read-only root filesystems, dropped Linux
capabilities and bounded log rotation. The installation currently expects a
standard rootful Docker Engine with its default data root `/var/lib/docker`;
rootless engines, user-namespace remapping and custom data roots need an adapted
backup path and ownership policy before use.

The only public application mappings are:

| Port | Purpose |
| --- | --- |
| TCP 80 | Restricted ACME HTTP challenge responder (public ACME mode) |
| TCP 443 | Dashboard HTTPS |
| TCP 8444 | Authenticated game API HTTPS |
| TCP 8443 | Authenticated TLS game gateway |

SSH remains on the host's configured port. The dashboard's HTTP port 4321 is
bound only to loopback. Management 8090, backend HTTP and raw scene ports are not
published publicly. Apply any provider firewall rules explicitly for the ports
above; Docker's published-port rules must be considered when configuring a host
firewall (see *Host hardening* below).

### World capacity

`nebula_max_processes` (default 4) bounds simultaneous world processes, not
players; players in the same world share its process. One world uses roughly
225 MiB, so the server container memory limit scales as 768 MiB + 256 MiB per
slot (1280 MiB for 2, 1792 MiB for 4) and the PID limit as 256 + 128 per slot.
Set `nebula_server_mem_limit_mb` explicitly if the host has less free memory;
check `free -m` before raising the slot count. The panel keeps 256 MiB and TLS
sidecars smaller limits. These are starting bounds, not a capacity guarantee.

Empty worlds stay warm for an idle grace: `nebula_public_world_idle_seconds`
(default 900) for shared worlds such as Nexus, avoiding a ~20 s cold start on
each visit, and `nebula_personal_world_idle_seconds` (default 60) for
apartments. When every slot is busy and a player needs a new world, the
supervisor first stops the least recently active *empty* apartment, then an
empty shared world; a world with players or pending loads is never evicted.
If every slot holds players, the backend answers the client's native
`N2LoadSpace` "no free slot" response instead of accepting a load that would
spin forever (the `N2SpaceLoading` poll has no failure response in the client).

Useful host checks:

```bash
systemctl status nebula-preserved --no-pager
systemctl is-enabled nebula-preserved
systemctl list-timers nebula-preserved-backup.timer
journalctl -u nebula-preserved -n 100 --no-pager
cd /opt/nebula-preserved
docker compose --env-file runtime.env -f compose.yaml -f compose.public.yaml \
  -f compose.host.yaml ps
docker stats --no-stream
```

Set `nebula_verify_reboot: true` for an intentional reboot test. The playbook
reconnects, waits for the boot service, then checks the trusted public API and
dashboard. Leave it false for ordinary updates to avoid rebooting each run.
State is kept in the named volume across restarts and reboots. Do not run
`docker compose down --volumes` when upgrading.

## Owner login and player access

The first setup creates a random dashboard password and stores it only in
`/opt/nebula-preserved/operator/panel-login.txt`, readable by root. Retrieve it
over the verified SSH connection. Never put it in an image, GitHub secret-free
example file, chat transcript or shared launcher. The dashboard URL is
`https://<server-ip>/login`. The owner role is local administration policy; it
does not automatically grant a game account moderator privileges.

In explicit private-CA mode, the operator CA is stable across reruns. Export the **public**
`operator/operator-ca.der` for the launcher and verify its SHA-256 through your
trusted distribution channel. A browser also needs to trust the matching public
CA certificate to use the dashboard without certificate errors. Trust only the
specific CA you verified. Never distribute `ca-key.pem`, `server-key.pem`,
dashboard tokens or panel session keys. The leaf certificate lasts one year;
bootstrap refuses a certificate with less than 30 days remaining. Renew it under
the existing CA before that point, retaining the required IP SAN and
`serverAuth` purpose. Replacing the CA requires an explicit launcher trust update.

Public-ACME mode uses normal system trust and hourly renewal of six-day IP
certificates. Its account/certificate tree is root-only below `acme/config`.
Successful renewal validates chain, IP, key and expiry, then recreates only the
three TLS sidecars so their read-only bind mounts receive the new files. This
can briefly reconnect active TLS players; backend/world processes stay running.
The older private CA/account credentials remain intact when migrating to this
mode. The private-CA 30-day expiry threshold above does not apply to the public
short-lived certificate; public installation requires at least one day left.

Game accounts require distinct operator-issued credentials bound to each
player's Steam identity. The dashboard owner password is not a player credential.
Use the existing [public-access administration workflow](../../backend/public_access_admin.py)
to initialize an operator key, provision an account and issue its credential.
Keep the operator key mode 0600, outside containers unless mounted for that
specific administrative command. Follow the state tool's consistency rules;
do not edit the live SQLite database manually. Give each player only their own
credential (plus the public CA only in private-CA mode), and revoke/reissue individual credentials when
needed. The Windows patcher encrypts imported account credentials with that
Windows user's DPAPI; do not copy another user's DPAPI token file.

## Backups, updates and recovery

`nebula-preserved-backup.timer` runs daily with missed runs handled after boot,
and every playbook run takes a `-deploy` backup before restarting the stack.
Each set in `/var/backups/nebula-preserved` is `preservation-<UTC stamp>[-deploy]`:
the SQLite online backup (`.sqlite3`, `quick_check` verified), a
`.state.tar.gz` with the per-instance JSON state (`instance-*.json` at the state
root such as `instance-accounts.json`/`instance-housing.json`, and
`instances/*/instance-*.json`) re-read and hash-verified, and a `.json` receipt
written last with SHA-256 for every file. Retention keeps the newest set of each
UTC day for 14 days plus the newest 5 deploy sets, so repeated deploys cannot
flush daily history. Trigger an extra backup manually:

```bash
systemctl start nebula-preserved-backup.service
systemctl status nebula-preserved-backup.service --no-pager
ls -l /var/backups/nebula-preserved
```

Copy verified backups off the host through a secure channel. The database backup
does not include the deployment's CA, TLS key, dashboard credentials or runtime
metadata. Back those up separately with restrictive permissions and protect the
CA key especially carefully. Keep the exact earlier image archive and pins for
rollback.

Off-host copies are opt-in: set `nebula_backup_offsite_command` to a shell
snippet. The playbook writes it to `/opt/nebula-preserved/backup-offsite.sh`
(mode 0700) and runs it after every verified set with
`NEBULA_BACKUP_DIR`, `NEBULA_BACKUP_DATABASE`, `NEBULA_BACKUP_STATE_ARCHIVE` and
`NEBULA_BACKUP_RECEIPT` set; an empty value removes the hook. A failing hook
marks the backup unit failed but keeps the verified local set. The scheduled
unit is sandboxed (`ProtectHome`, read-only system), so reference keys and known
hosts explicitly, for example:

```yaml
nebula_backup_offsite_command: >-
  rsync -a -e "ssh -i /opt/nebula-preserved/operator/backup_ed25519
  -o UserKnownHostsFile=/opt/nebula-preserved/operator/backup_known_hosts"
  "$NEBULA_BACKUP_DATABASE" "$NEBULA_BACKUP_STATE_ARCHIVE" "$NEBULA_BACKUP_RECEIPT"
  backup@203.0.113.20:nebula/
```

To restore instance JSON state, extract the matching `.state.tar.gz` into the
stopped volume after checking each file against the receipt.

To restore, stop `nebula-preserved.service` first and confirm its containers and
world processes have stopped. Preserve the existing volume as a separate
recovery copy. Verify the chosen backup against its JSON receipt and run SQLite
`PRAGMA quick_check` before replacing state. Restore only into the same verified
volume mount point, using UID/GID 1000 ownership, and ensure no stale live WAL or
SHM files accompany the restored database. Restart the service, check health and
verify the restored accounts through the dashboard and game. Do not replace a
live database or remove the volume as a troubleshooting shortcut.

Run the playbook again with a newly reviewed image archive and matching three
pins for updates. It preserves existing state and credentials. It does not
perform a blanket OS upgrade or remove unrelated Docker resources.

## Host hardening

These tasks are prepared in `site.yaml`; review them before the next run.

- `nebula_ssh_hardening` (default `true`) installs
  `/etc/ssh/sshd_config.d/00-nebula-hardening.conf` with
  `PasswordAuthentication no`, `KbdInteractiveAuthentication no` and
  `PermitRootLogin prohibit-password`. The `00-` prefix wins over cloud-image
  `50-*` files because sshd uses the first value it reads. Before writing it the
  play requires at least one public key in `nebula_ssh_authorized_keys_files`
  (default `/root/.ssh/authorized_keys`) and stops otherwise, then validates the
  whole configuration with `sshd -t` before the handler reloads `ssh`; a failed
  validation removes the drop-in. Keep an existing session open while the first
  run applies it, and set the variable to `false` if you log in with passwords.
- `nebula_fail2ban` (default `true`) installs fail2ban with an `sshd` jail
  (journal backend, `nebula_fail2ban_maxretry` 5, `nebula_fail2ban_bantime` 1h).
- `nebula_ufw` (default `false`) enables ufw allowing only
  `nebula_ufw_allowed_tcp` (22, 80, 443, 8443, 8444), adding the SSH rule before
  enabling. It is opt-in because Docker publishes container ports through its own
  NAT/`DOCKER-USER` chains, which bypass ufw's INPUT rules: ufw protects host
  services such as sshd but does not restrict Docker-published ports, so the
  compose port bindings and the provider firewall remain the authority for
  those. Change SSH's allowed port first if sshd does not use 22.

## Player policy

- `nebula_starter_crystals` / `nebula_starter_np` (default 0) credit a new
  account exactly once, in the same transaction that creates the profile, and
  record `starter_wallet_grants` plus `management_wallet_ledger` rows
  (`system:starter-policy`). Changing them never affects existing accounts.
- `nebula_starter_apartments` (default `[Home, CliffApartment, LakeApartment]`)
  lists the apartments every account owns. `Home` is the client's native
  default apartment and is always included; the others are a preservation
  choice. At startup existing accounts are backfilled once per apartment
  (`starter_apartment_grants`); shrinking the list or a staff removal is never
  undone or re-granted. Staff can give or remove apartments in the panel's
  Character → Apartments tab (Home cannot be removed).
- `nebula_enrollment_max_accounts` (1000), `nebula_enrollment_per_ip_hourly`
  and `nebula_enrollment_global_hourly` (empty: 8/100 strict, 120/1200 trusted)
  bound registration.
- With `nebula_trust_steam_id`, `nebula_protect_staff_accounts` (default
  `true`) refuses claimed-device enrollment into staff-labelled or
  dashboard-operator-linked accounts and those in `nebula_protected_accounts`
  (SteamID64 list); they need their primary credential.

The bootstrap installer exposes the same knobs (`deploy.py install
--max-processes`, `--public-world-idle-seconds`, `--starter-crystals`,
`--starter-np`, `--enrollment-max-accounts`, `--protected-account`,
`--no-protect-staff-accounts`, `--no-ssh-hardening`, `--no-fail2ban`, `--ufw`).

## Fast offline tests

```bash
python3 -B -m unittest discover -s deployment/ansible/tests -v
```

Run this command from the repository root. Linux/OpenSSL tests create temporary
CA/server certificates and verify idempotence, SAN mismatch rejection, secret
permissions, password derivation, partial setup and expiry failure. They mock
ownership changes, never install services and never connect to a server. On
Windows these Linux-specific checks are skipped; execute them in WSL or Linux
CI to obtain actual coverage.
