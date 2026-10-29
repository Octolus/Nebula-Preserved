# Deployment templates

For the maintained Docker deployment and Ubuntu 26 Ansible automation, see
[Docker hosting](docker/README.md) and [Ansible deployment](ansible/README.md).
The historical private service templates below retain their original scope.
Public TLS server health is separate from native Windows-client acceptance.

This directory contains source templates for the preservation server's local or
private-network deployment. Nothing here is installed, enabled, or started by
the repository checkout.

## Supported boundary

The baseline deployment is for loopback, a trusted LAN, or an operator-managed
VPN. The Mirror/Telepathy game connection is not an Internet security boundary
and must not be exposed directly to the public Internet. The reviewed but
undeployed account/HTTPS overlay is kept separately in
`../experimental/public-access-v9/`; the experimental TLS game-transport relay
is in `../experimental/remote-transport/`.

`instance-supervisor/nebula-managed-http.service.in` is the private baseline
template. It expects the repository's top-level `backend/`, `mirror-server/`,
and `tools/instance_supervisor.py`, which are maintained by their owning
components. Replace every placeholder and verify all binary/build-report hashes
before installing any unit.

## Operator preparation (does not start services)

From the repository root:

```text
python -m py_compile deployment/tools/backup_state.py
python -m py_compile deployment/tools/migrate_public_access.py
python -m py_compile deployment/tools/package_public_deployment.py
```

The templates use conventional Linux paths under `/opt`, `/etc`, and `/var`.
Copying them into those locations, creating the service account, and enabling
units are deliberate operator actions and are not performed by this repository.

Before any first start:

1. create a dedicated unprivileged service account;
2. create state and backup directories with restrictive permissions;
3. pin the exact managed assembly, Linux server, and build-report hashes;
4. keep the HTTP listener on loopback or a trusted private interface;
5. configure a private/VPN game address and bounded port range;
6. create and verify an offline backup; and
7. inspect the unit sandbox and every placeholder.

`deployment/tools/backup_state.py` creates a consistent SQLite backup plus
manifest. `migrate_public_access.py` and `package_public_deployment.py` belong to
the deferred public-access workflow; they are retained for reproducibility, not
as an activation recommendation.

## Current status

- No listener or service was started while curating these files.
- No credentials, account state, SQLite databases, logs, or private paths are
  included.
- Public activation is not approved by this package.
- Runtime acceptance of the remote transport remains deferred.

See `STATUS.json` and the component READMEs for the exact limitations.
