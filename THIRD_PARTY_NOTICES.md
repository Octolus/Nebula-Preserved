# Third-party components and provenance

Original project contributions use the root [MIT license](LICENSE). This file records the separate terms and provenance of third-party components. It does not relicense them or the original game. See [licensing and distribution scope](docs/LICENSING.md).

## Mirror and bundled dependencies

The instance server vendors Mirror **v66.0.9**, commit `4d0cd1054a9011ee4492f91ed4bd16c671fea470`. Its MIT notice is retained at [Assets/Mirror/LICENSE](mirror-server/UnityProject/Assets/Mirror/LICENSE). The Telepathy bind/readiness adaptation is a local modification; serializers and wire framing use the pinned upstream code. Component notices remain alongside Telepathy, SimpleWebTransport, kcp2k and where-allocation in the vendored tree.

The historical Mirror Weaver includes Mono.CecilX plugin libraries from that upstream distribution. Their retained [License.txt](mirror-server/UnityProject/Assets/Mirror/Plugins/Mono.Cecil/License.txt) identifies Jb Evain, Novell and vis2k and contains the upstream permission notice. These are build dependencies, not game assemblies. See the pinned [Mirror provenance](mirror-server/provenance.json); keep the notice and binary/source provenance together.

The vendored component notices are retained at:

| Component | Notice |
| --- | --- |
| Mirror | [MIT license](mirror-server/UnityProject/Assets/Mirror/LICENSE) |
| Telepathy | [MIT license](mirror-server/UnityProject/Assets/Mirror/Runtime/Transports/Telepathy/Telepathy/LICENSE) |
| SimpleWebTransport | [MIT license](mirror-server/UnityProject/Assets/Mirror/Runtime/Transports/SimpleWebTransport/LICENSE) |
| kcp2k | [MIT license](mirror-server/UnityProject/Assets/Mirror/Runtime/Transports/KCP/kcp2k/LICENSE) |
| where-allocation | [MIT license](mirror-server/UnityProject/Assets/Mirror/Runtime/Transports/KCP/kcp2k/where-allocation/LICENSE) |
| Mono.CecilX | [Upstream permission notice](mirror-server/UnityProject/Assets/Mirror/Plugins/Mono.Cecil/License.txt) |

## External build and runtime dependencies

Unity editor, build modules and engine runtime are supplied separately under Unity's terms. Unity package declarations are retained; package caches and editor installations are excluded. Redistributing a compiled Unity server requires reviewing the applicable Unity terms.

Python dependencies are declared in `backend/requirements.txt`, `deployment/docker/requirements.lock.txt`, `client-patches/requirements-dev.txt` and `experimental/optional-input/requirements.txt`. Rust dependencies are declared and locked in `patcher/` and `experimental/remote-transport/client/`. JavaScript dependencies are declared in `admin-panel/package.json` and pinned by `admin-panel/package-lock.json`. These packages are fetched separately; their respective upstream licenses apply. A project code license does not replace dependency terms.

Keep resolved dependency SBOM/license reports with release evidence and ship the actual required notices for the artifact being distributed. Include operating-system/container packages and native runtime dependencies when auditing a compiled server or image. Do not infer one license for a complete dependency graph from its direct dependencies.

## Nebula Realms material

Nebula Realms names, game binaries and assets belong to their respective owners. This repository is an unofficial preservation effort. Full game binaries, textures, models, audio and original asset bundles are excluded. Protocol identifiers, data schemas, referenced asset names and reconstruction notes were derived from a locally supplied client. This does not grant rights to the original game's content.

Client patch output and delta packages depend on a specific locally supplied Steam build. Review their contents and distribution rights separately before publishing release artifacts. No claim of endorsement or ownership of the original game is made.

## Administration panel

The Astro/React panel adapts shadcn/ui dashboard-01 and component sources. The upstream MIT notice is retained at [admin-panel/LICENSE-shadcn-ui.txt](admin-panel/LICENSE-shadcn-ui.txt). Resolved JavaScript dependency versions are recorded in its package lockfile; dependency notices remain with those packages. Sample dashboard accounts, company branding and unrelated demo data were removed.

## Historical overlays

The retained [public-access overlay notice](experimental/public-access-v9/THIRD_PARTY_NOTICES.md) and [remote transport notice](experimental/remote-transport/THIRD_PARTY_NOTICES.md) describe their own source/dependency boundaries. Historical overlays and their tests remain provenance references; their presence does not authorize applying an old overlay to the integrated backend or redistributing original game material.
