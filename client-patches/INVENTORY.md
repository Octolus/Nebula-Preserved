# Preservation source pipeline and provenance

The networking-only development default uses all **70 application API request hooks** and the repaired stripped-Unity loopback consumer. Public native TLS acceptance is pending. Configured direct HTTPS is unsupported; direct six-artifact mode supports unconfigured local forwarding only. Public connections use the explicit seven-artifact remote profile, exact owned proxy, upstream CA/hostname verification and account authorization. Controls, cursor and rendering remain shipped behavior. Current source/build pins are in `network-only/network-profile-contract.json`.

The recommended preservation default is the separate **network-only** profile in
`network-only/`. It preserves shipped input assets, controls, cursor and rendering.
Its direct/TLS release plans contain six/seven artifacts and require the reviewed
explicit Rust `network-only` profile support. Runtime acceptance is pending.

The reconstruction below is retained as a **legacy optional keyboard/client-bug-fix
and testing pipeline**. Its historical profile named `default` means original
cursor only; it also contains keyboard aliases, client bug fixes and passive test
hooks. It is not the networking-only default. Never select it implicitly for
players who want shipped UI and controls. See `network-only/README.md` for the
minimal build, exact source contract and profile-switch restore requirements.

This tree supplies authored patch recipes and adapters for Steam app 919290,
build 11018722. It reconstructs exact client targets from locally owned pristine
files. It contains no complete game file or decompiler listing. Generated private
build receipts, plans, targets and scratch must remain outside the public tree.
All release plans are provisional and native runtime acceptance remains pending.

The original GameAssembly SHA256 is
`c4dd5db599e5e5ce4adf25f09ffe70ad10e0928adf6a2e862176d537026b44ac`.
The original executable, license and ownership initialization are preserved.

| Stage | Exact output SHA256 | Authored recipe |
| --- | --- | --- |
| Wardrobe final element | `29abe9dbf4f310ba72b4de19273da85c797e529fac6511ba40bb9f88314dc420` | `recipes/make_client_copy.py` |
| Rapid exit message | `ce1a74588e74499e282699e160b966439ffb4c278e8bcef791951e28a57b0dd0` | `recipes/rapid_boat_patch.py` |
| Notification text | `13158d2f08c9511c9cc283a6dda680081c5e1f6142bb86ddde1bfbd039de7fcb` | `recipes/notification_text_patch.py` |
| Keyboard button fallbacks | `3ddc1eb903eda90be06cc7079e2afa584d250b4430455b86564150fa05949703` | `recipes/keyboard_buttons_patch.py` |
| F8 focus fallback | `ec6f909d3af35c89cd287a2803b86839cd5d1b168bc1f76517eed2494c85e01b` | `recipes/keyboard_focus_patch.py` |
| Registry and save snapshot | `3001b2e4cf014a7ec961c370b50a947c9b6d6f4be86446f3e5d4bffe203353e3` | `recipes/interaction_registry_patch.py` |
| Neck saved value | `af25cec2ba6a9496f7c34b5ea8224f4ef5ab9f596bda6ae35bcb44197f30b195` | `recipes/neck_thin_load_patch.py` |
| Settings persistence | `c11dc93f3f67bb09781d9c097ce85cc2e497af9bf83efabaf279ec2b03b0f3d5` | `recipes/settings_preservation_patch.py` |
| Eye lifetime guard | `cd82cde50b71ea203fc09dc87153579f6cb504f1e9dfb74417408d602c704a74` | `recipes/eyes_lifetime_patch.py` |
| Steam Update helper pump | `8460554e5287fe8e3c5fe475f65379da971bcccf2f21f716f2ca82d6e029b9fd` | `recipes/steam_update_pump_patch.py` |
| Atomic 75 hooks and corrected IAT | `0ec5e89f91010e205b19ee4de29a4167c1deb7312a45733a866dbebec64a13ab` | `pe-composition/compose_iat_corrected.py` |
| Default original cursor plus join gate | `d59155564b142aa24dcfab03a47290d43261dccbfd55ea3a06543fffe65fda04` | `pe-composition/join_queue_patch.py` |
| Optional free mouse before join gate | `6fc2fcdf0e4178b96069f25e4f2e8fcacf8af3c33fb68c4f144ae6a5fd4dd4df` | Explicit optional three-method cursor transform |
| Optional free mouse plus join gate | `39ad8c096357f4a1e56b90524175f67b8e6cc88dcedf2c3bc0fbf87178271e3b` | `pe-composition/join_queue_patch.py` |

The matching V9 default helper is
`c880fb8df3265da1432ff3e6683156e2941abf972ad23df8e15699f38fea6e19`.
The matching V9 optional free-mouse helper is
`68415abf23ee90cbc3e9c6294097c0387eea8b29ddae42eb1fbc290739573083`.
`build_client_targets.py` and the standalone `build_helpers.py` enforce both
exact tuples. The default changes only the GA macro in `movement_profile.h`;
all other V9 networking and helper sources match the optional baseline.
The settings automation safe-list remains unchanged and excludes the default.
The original controller mappings remain present alongside keyboard aliases.

## Source inventory

`source-lock.json` pins 96 foundation files. Sixty-three files form the complete
V9 normal helper source tree. Ten translation units build the automation helper,
including `join_queue_gate.cpp`. The new helper baseline changes exactly six
native files from the previously reviewed foundation: `economy_store_module.cpp`,
`economy_store_policy.h`, `economy_v16_adapter.cpp`, `economy_v16_adapter.h`,
`v16_shared_core.inc` and `v16_social_core.inc`. The GameAssembly, input, editor,
registry, PublicAccess and PE emission sources retain their reviewed bytes.

The complete curated source selection adds `build_client_targets.py`,
`verify_targets.py`, `build_helpers.py`, this inventory, the README and the source
lock to those 96 files. Public promotion maps those 102 authored files directly
to `client-patches/`. Private evidence and complete reconstruction outputs are
excluded. PublicAccess CMake and registry C++17 build behavior are preserved.

The historical source chain and both GameAssembly profiles were independently
reconstructed and reviewed. The V9 networking composition has separate source
review. Those facts establish offline source and byte provenance; they do not
establish complete game functionality, persistence or a production release.

## Bundle boundary

Each generated input plan has eight exact artifacts. The Rust patcher handles
metadata endpoints at installation using the supplied server origin and
advertised address. The bundle builder emits source-referenced COPY/ADD/ZERO
deltas for game files and distributes project-owned helper files. No complete
game target or decoded editor file belongs in a published bundle.

The default bundle plan preserves cursor behavior. The optional plan must be
explicitly labeled free mouse. Both remain provisional until final source and
native acceptance are complete. The direct bundle lacks the separate optional
TLS sidecar profile. Receipt-managed clients can update, repoint or change
profile using hash-verified transaction backups automatically. Explicit
`--originals` remains available for reviewed manual overlays or an unavailable
verified backup chain, as described in the README.
