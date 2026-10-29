# Ansible deployment

This playbook installs Docker Engine and Compose on a dedicated Ubuntu 26.04+
x86_64 host, loads a reviewed local image archive, and enables the public TLS
stack and daily SQLite backups. Run Ansible from Linux or WSL. It does not build
Unity on the server or publish images. Keep operator inventories, SSH keys,
credentials, certificates and account state outside this repository.

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

Set `nebula_public_ip` to the host's public IPv4 address. The first installation
issues a leaf certificate with that IP in its SAN. Changing the address later
fails certificate verification until you deliberately reissue the leaf under the
same operator CA. Do not disable verification to work around an address mismatch.

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
| TCP 443 | Dashboard HTTPS |
| TCP 8444 | Authenticated game API HTTPS |
| TCP 8443 | Authenticated TLS game gateway |

SSH remains on the host's configured port. The dashboard's HTTP port 4321 is
bound only to loopback. Management 8090, backend HTTP and raw scene ports are not
published publicly. Apply any provider firewall rules explicitly for the ports
above; Docker's published-port rules must be considered when configuring a host
firewall.

For a small host, the initial limit is two simultaneous world processes, not two
players. Players in the same world share its process. The server container has a
1280 MiB memory limit, the panel 256 MiB, and TLS sidecars have smaller limits.
These are starting bounds, not a capacity guarantee. Measure actual memory,
CPU, process restarts and active worlds before increasing
`nebula_max_processes`. Idle worlds expire after 60 seconds.

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

The operator CA is stable across reruns. Export the **public**
`operator/operator-ca.der` for the launcher and verify its SHA-256 through your
trusted distribution channel. A browser also needs to trust the matching public
CA certificate to use the dashboard without certificate errors. Trust only the
specific CA you verified. Never distribute `ca-key.pem`, `server-key.pem`,
dashboard tokens or panel session keys. The leaf certificate lasts one year;
bootstrap refuses a certificate with less than 30 days remaining. Renew it under
the existing CA before that point, retaining the required IP SAN and
`serverAuth` purpose. Replacing the CA requires an explicit launcher trust update.

Game accounts require distinct operator-issued credentials bound to each
player's Steam identity. The dashboard owner password is not a player credential.
Use the existing [public-access administration workflow](../../backend/public_access_admin.py)
to initialize an operator key, provision an account and issue its credential.
Keep the operator key mode 0600, outside containers unless mounted for that
specific administrative command. Follow the state tool's consistency rules;
do not edit the live SQLite database manually. Give each player only their own
credential and the public CA, and revoke/reissue individual credentials when
needed. The Windows patcher encrypts imported account credentials with that
Windows user's DPAPI; do not copy another user's DPAPI token file.

## Backups, updates and recovery

`nebula-preserved-backup.timer` runs daily with missed runs handled after boot.
The backup utility uses SQLite's online backup API, verifies `quick_check`,
writes a SHA-256 receipt and retains 14 backups in
`/var/backups/nebula-preserved`. Trigger an extra backup before updates:

```bash
systemctl start nebula-preserved-backup.service
systemctl status nebula-preserved-backup.service --no-pager
ls -l /var/backups/nebula-preserved
```

Copy verified backups off the host through a secure channel. The database backup
does not include the deployment's CA, TLS key, dashboard credentials or runtime
metadata. Back those up separately with restrictive permissions and protect the
CA key especially carefully. Keep the exact earlier image archive and pins for
rollback. No off-host backup destination is configured automatically.

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
