# Source boundaries

| Path | Role |
|---|---|
| `backend/` | Integrated Python account, inventory, shop, social, apartment and persistence services |
| `mirror-server/` | Reconstructed C# scene server and pinned Mirror dependencies |
| `protocol/` | Recovered contracts, schemas, identifiers and asset references |
| `admin-panel/` | Separate Astro/React operator interface using the authenticated internal management API |
| `client-patches/network-only/` | Default networking compatibility profile, retaining shipped input, cursor and rendering |
| `patcher/` | Rust Steam discovery, exact-build patching, endpoint updates and receipt-backed restore |
| `deployment/` | Linux Docker hosting, ingress and Ubuntu automation |
| `tools/`, `scripts/`, `tests/` | Operational tools, source/release checks and offline tests |
| `experimental/` | Earlier overlays and optional research profiles retained for provenance |
| `experimental/rust-server/` | Independent Rust HTTP, Mirror world, SQLite and operator API candidate; isolated Docker profile and contract tests |
| `docs/research/`, `tools/research/` | Sanitized findings and scripts requiring separately supplied private inputs |

Managed hosting targets Linux/POSIX. Docker copies the integrated source directly rather than selecting a historical private backend variant.

`admin-panel/` is a separate Astro SSR application. It uses an internal, authenticated management API; its browser bundle contains no service token. Dashboard roles are local administration policy, separate from game privileges.

`deployment/docker/` contains the primary container setup. Its private runtime input and secrets are ignored. A source checkout must be paired with a matching complete Linux Unity build; build/test output does not belong in Git.

The integrated backend includes durable resource selections, current-session guards, explicit public-access authentication, management transactions and atomic two-part apartment saves. Housing interaction coverage classifies known scriptless placeholders from exact shipped records; genuinely unknown components remain denied. No blanket unknown-item trust was added.

`client-patches/network-only/` is the default client source profile. It retains networking compatibility changes and a minimal join-queue bridge while preserving original controls, input assets, cursor and rendering. Legacy optional input/test profiles remain research material. Six/seven-artifact patcher profiles are distinct from older eight/nine-artifact profiles; transitions requiring restore must not be bypassed.

`experimental/` retains earlier overlays and staged work. Do not reapply old resource/auth overlays to the integrated backend. The current networking-only adapter repairs the stripped-Unity compatibility issue through the owned authenticated TLS proxy and covers all 70 application request sites. It still requires native acceptance. The canonical legacy consumer remains only to preserve older locked test/input recipes; use the repaired consumer under `client-patches/network-only/public-access/` for the default profile.

Protocol manifests contain schemas, identifiers and asset references, not original textures, models, audio or game assemblies. Missing historical store/reward policy is explicit local preservation policy. Research notes describe evidence available at their time; they are not a current runtime guarantee. Referenced private captures and decompiler output are not bundled. Original contributions and upstream material have the [separate licensing boundaries](LICENSING.md).

The root `SOURCE-INVENTORY.json` records the current publication files and excludes itself explicitly. Older component inventories are labelled historical receipts; their original hashes are retained rather than rewritten as new test evidence.

Generated reports bind exact source/artifact hashes. Editing compiled C# inputs invalidates an old build's source match. Preserve frozen historical evidence and generate a successor rather than rewriting an old success claim.

`work/`, `releases/`, credentials, databases and generated build/test output are private or ignored inputs, not source deliverables.
