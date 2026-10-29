# Security

This is a development preservation server with separate private, public and
administrative trust boundaries. Follow the [deployment instructions](deployment/docker/README.md)
for the selected profile; successful local or synthetic checks do not establish
native public-client readiness.

## Network profiles

The default private profile binds to loopback. It accepts reconstructed account
identifiers and does **not** verify Valve Steam authentication tickets. An account
identifier is not proof of ownership. Use this profile only within an explicitly
trusted local network or VPN; do not publish its raw HTTP or scene ports to the
Internet. Historical application encryption and Mirror framing provide neither
modern account authentication nor a substitute for TLS.

Public hosting requires the explicit auth-schema migration, operator-provisioned
per-account credentials and matching TLS certificates. The public Compose
override replaces the private raw ports with authenticated ingress. Keep
certificate/hostname validation enabled, including when using a configured
private CA. Original-client acceptance through that path remains a separate gate.

## Operator access and secrets

There are no shipped passwords or service tokens. The documented bootstrap creates
random service/session keys and a password record without printing the secrets.
Store them as private files outside Git and image layers. The containers run as
UID/GID 1000; arrange readable secret ownership or a narrow ACL for that UID and
keep other users excluded. File-backed Compose secrets preserve host permissions.

Keep management port 8090 internal. The panel binds to loopback by default;
remote administration needs operator HTTPS and an exact configured browser origin.
Roles are resolved by the backend, and mutations require authorization, a reason
and idempotency. Never send the service token to browser code or treat a client
supplied role as authority.

Protect the state volume, backups, credential files and TLS private keys. Retain
separate off-volume backups and secrets for recovery. Back up before migrations
or upgrades; deleting a state volume deletes player data. Avoid exposing database
files, session exports, IPC directories or unredacted runtime logs.

## Reporting a vulnerability

A dedicated security contact and private reporting channel have not yet been
configured. Use a private contact explicitly published by the repository
maintainer when one is available. Do not put working credentials, private keys,
personal data or sensitive exploit details in public issues. Public reports can
describe the affected component and impact without including those materials.

No security-support window or coordinated-disclosure address is promised by this
snapshot. See [privacy](docs/PRIVACY.md) for safe evidence sharing and
[publishing](docs/PUBLISHING.md) for source-release hygiene.
