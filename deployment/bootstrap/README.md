# One-command Ubuntu installation

A prepared release installs Docker Engine/Compose, starts the complete server
and dashboard, creates private operator credentials, initializes durable state,
issues publicly trusted TLS certificates for the server's IPv4 address, and
enables boot recovery, daily verified backups and hourly certificate renewal.
It preserves existing accounts, credentials, state volumes and private CA files
when updating an earlier deployment. No certificate files or hash editing are
required on the normal public path.

Use a dedicated **Ubuntu 26.04+ x86_64** server. The public address must belong to
the server. TCP **80** must be reachable for ACME validation; players use 8443
and 8444, and the dashboard uses 443. The installer cannot change an external
provider firewall without that provider's API access. If validation fails, it
stops before starting the new game stack rather than disabling verification.

## Install a prepared release

Copy the reviewed release directory onto the server through your verified SSH
connection, then run this one command as root:

```bash
python3 /private/nebula-release/deployment/bootstrap/deploy.py install \
  --release /private/nebula-release --public-ip YOUR_SERVER_IPV4
```

For automatic first-time player registration, add `--public-enrollment`. This
is an explicit first-claim preservation policy, not verification of Steam
ownership. Existing accounts cannot be replaced by registration. The launcher
keeps each player's login private; see [the enrollment contract](../../docs/ENROLLMENT.md).

No host Ansible installation is required; the installer installs it if absent.
All release files, image configuration identities and runtime pins are checked
before package or service changes. Installation uses the fixed application root
`/opt/nebula-preserved`, Compose project `nebula-preserved` and existing durable
volume `nebula-preserved_state`. Installer bookkeeping remains root-only under
`/var/lib/nebula-preserved-installer`. Repeating the same command is supported;
it retains existing operator/account authority and never removes volumes.

The installer automatically accepts Let's Encrypt's subscriber terms for the
requested certificate and registers its ACME account without a contact email.
It first tests the HTTP challenge against staging, then requests the real
short-lived IP certificate using a digest-pinned Certbot 5.4.0 container.
An hourly systemd timer renews it. Successful renewal refreshes only the TLS
sidecars; existing TLS game connections may briefly reconnect, while the backend
and world processes keep running. Certificate/key identity, normal system trust,
IP SAN and expiry checks must pass before publishing the replacement.

Open `https://YOUR_SERVER_IPV4/login`. Retrieve the generated owner login only
over your private SSH connection from
`/opt/nebula-preserved/operator/panel-login.txt`. There is no shared default
password. Player account credentials are separate from dashboard credentials.

The public path uses normal certificate validation: players need no exported
operator CA. Explicit private/test deployments can select
`--tls-mode private_ca`; those intentionally retain operator-CA provisioning.

For updates, copy a new reviewed release and run the same install command.
Do not run Compose with `--volumes` when stopping or updating the service.
An existing deployment should be backed up before changing releases. Existing
unmigrated databases are refused rather than silently migrated.

Service checks prove deployment health, persistence setup, trusted TLS and
anonymous API rejection. They do not establish original-client gameplay or
multiplayer acceptance. A local install cannot reboot itself and keep its
foreground installer process alive; use the remote Ansible workflow for an
intentional reboot test and verify recovery afterward.

## Prepare a release as the maintainer

Build the matching server/panel images and complete reviewed Linux runtime using
the [Docker build instructions](../docker/README.md#build-images-from-source).
Keep these generated artifacts outside the public source tree. Save the chosen
images with repository tags, including `nginx:1.28-alpine`, then run:

```bash
docker save -o /private/images.tar \
  nebula-preserved-server:reviewed nebula-preserved-panel:reviewed nginx:1.28-alpine

python3 deployment/bootstrap/deploy.py prepare \
  --output /private/nebula-release --archive /private/images.tar \
  --runtime-report /private/build-linux-validation.json \
  --server-image nebula-preserved-server:reviewed \
  --panel-image nebula-preserved-panel:reviewed
```

The output contains only the selected image archive, runtime report, allowlisted
deployment source and a `release.json` integrity inventory. It contains no
installation state, SSH key, account credential or TLS private key. `prepare`
requires a new output directory and never overwrites an older release. The
reported SHA-256 of `release.json` can accompany the release through the trusted
distribution channel. Integrity hashes do not independently authenticate the
publisher; use your verified release source.

Check a release without installing it:

```bash
python3 deployment/bootstrap/deploy.py verify --release /private/nebula-release
```

## Operations

The sanitized [deployment checkpoint](validation.json) records the tested
installer, public TLS boundaries, repeat installation and actual reboot/state
retention. Original-client and multiplayer acceptance remain separate gates.

```bash
systemctl status nebula-preserved nebula-preserved-acme-http --no-pager
systemctl list-timers nebula-preserved-public-tls.timer nebula-preserved-backup.timer
systemctl start nebula-preserved-public-tls.service
journalctl -u nebula-preserved-public-tls -n 50 --no-pager
```

The challenge service exposes only bounded HTTP challenge paths on port 80;
backend HTTP, management and raw world ports remain private. ACME account keys
are stored below `/opt/nebula-preserved/acme/config` and never distributed.
Back up this tree together with the existing operator secrets, state and release
metadata. Do not replace a working certificate with an untrusted certificate or
turn off hostname verification as a troubleshooting shortcut.

The automation is covered by the [Ansible offline test suite](../ansible/README.md#fast-offline-tests).

## Optional item photos

When preparing a release, add `--catalog-preview-pack /private/catalog-previews.tar`
to include an operator-extracted pack. The installer validates its complete
index and image hashes, activates it atomically, and mounts it read-only in the
panel. Omission preserves an existing pack. No artwork is added to public source
or the ordinary container image. See [extraction instructions](../../docs/CATALOG_PREVIEWS.md).
