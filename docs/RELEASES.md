# Releases and distribution

This repository is a development snapshot. A successful build, image publication
or transactional patch test is not a completed multiplayer release. Keep the
[status matrix](PROGRESS.md) and each release's validation limits visible.

## Separate the deliverables

| Deliverable | Includes | Still supplied privately |
|---|---|---|
| Source snapshot | Reconstruction code, manifests, tests and upstream notices | Original game installation, generated runtime and secrets |
| Server/panel images | Reviewed source and the matching validated server runtime | Deployment configuration, credentials, TLS keys and persistent state |
| Client patch bundle | Reviewed patch artifacts, version/hash manifest and restore tooling | Player's matching Steam installation and server credentials |

Do not attach complete game files, state databases, operator secrets or private
native captures to source archives or release assets. Review redistribution
permissions for every bundled dependency and generated runtime. The root MIT
license covers original reconstruction code only; see [licensing](LICENSING.md)
for upstream terms and excluded game assets.

## Before calling a build a release

1. Complete [publication checks](PUBLISHING.md) and inspect the exact source and
   artifact manifests. Record the source revision, dependency locks and hashes.
2. Produce the complete matching Linux build and validation report. Keep the
   [source-build and deployment requirements](../deployment/docker/README.md#build-images-from-source)
   with the image's instructions.
3. Run the component and synthetic deployment checks described in
   [testing](TESTING.md). State which original-client/native gates remain open.
4. Validate a client bundle's install, endpoint update and restore against a
   disposable matching installation. Preserve pristine originals and receipts.
5. Publish only the reviewed deliverables to the intended repository/registry.
   Include checksums, deployment/upgrade notes and the known acceptance limits.

## Continuous integration

GitHub Actions runs only the [backend HTTP and restart check](../.github/workflows/backend-e2e.yml)
on backend and protocol changes. The Windows patcher, Linux images and the
experimental Rust server are built and tested locally before a release; see
[testing](TESTING.md) and the [patcher release instructions](PATCHER-RELEASE.md).
Passing checks do not establish native game acceptance.

## Linux images

Images are built locally and copied to the server by the
[installer](../deployment/bootstrap/README.md); none are published to a registry.
If you publish images yourself, operators do not need a local Unity build.
From `deployment/docker/`, use `configure-image.sh` with the selected registry
prefix and tag. It pulls the pair, checks their Linux platform and equal source
revision, validates the three server build-hash labels and creates a **new**
mode-0600 `runtime.env` with immutable image digest references. It never starts
the stack or replaces existing runtime metadata. For an upgrade, keep the old
file and choose a new output filename.

Pass the private `.env` and generated metadata as ordered Compose environment
files with `compose.yaml` plus `compose.ghcr.yaml`; public mode also requires the
public override last. Do not shell-source either environment file. Follow the
[Docker pull instructions](../deployment/docker/README.md#pull-published-images-from-ghcr)
for the actual commands, operator secrets and selected private/public boundary.
Image publication does not provision credentials, DNS, firewall, TLS or a
state-volume backup, and does not establish native multiplayer acceptance.

## Upgrades and rollback

Take a consistent state backup and retain separate secret files before changing
images or schemas. Use the same intended Compose project and named state volume.
Finish explicit in-game saves before shutdown. Follow the Docker lifecycle
instructions; do not use volume deletion as a restart or upgrade step.

Pin the image/source/runtime version used for a deployment. Review migrations
before rolling backward: an older image is not automatically compatible with a
newer database schema. Test recovery using a disposable copy of the backup.
See [setup](SETUP.md), [security](../SECURITY.md) and
[third-party notices](../THIRD_PARTY_NOTICES.md) before sharing a release.
