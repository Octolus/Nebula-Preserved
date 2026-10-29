> Historical research: this file records an earlier investigation, not current feature acceptance. The root [PROGRESS report](../PROGRESS.md) is authoritative. Local evidence and extracted game code are intentionally omitted. See [research index](README.md).

# Original female preset save correction

The original build11018722 client swaps the right pectoral translation and left pectoral scale when it writes a female preset. The replacement service now corrects those six named fields only at `N2SavePreset` ingress. Canonical defaults, admin inputs, SQLite storage, EntryData decoding and response JSON retain their existing meaning. Male saves are unchanged.

This is backend compatibility policy for the original native writer. A future client patch that corrects that writer must use separately versioned ingress; applying both corrections would swap the fields again. No client patch is needed for this correction.

## Native evidence

Exact build, DLL, metadata and decompiled-body hashes are in `avatar-female-save-compensation.json`. Its twelve-row fixture is extracted from the saved native reader and save-writer assignments, using the current `JsonClasses.PresetFemaleJson` metadata offsets.

| Native reader582470 raw float indices | Actual transform values | Save writer3c6680 named destination |
|---|---|---|
| 36–38 | Left pectoral translation | `f_ch_l_pectoral_jnt_t_x/y/z` |
| 39–41 | Left pectoral scale | `f_ch_r_pectoral_jnt_t_x/y/z` — incorrect |
| 42–44 | Right pectoral translation | `f_ch_l_pectoral_jnt_s_x/y/z` — incorrect |
| 45–47 | Right pectoral scale | `f_ch_r_pectoral_jnt_s_x/y/z` |

Both `ManagerPreset.WriteFemaleBones`58f910 and `NebulaPlayerAvatar.WriteFemaleBonesGame`600200 expect the canonical named order: translation vectors12/13, scale vectors14/15. Their left pectoral branch reads translation at managed vector-array offset0xb0 and scale0xc8; the right branch reads translation0xbc and scale0xd4. The save writer places raw floats39–41 in JSON object offsets0x35c–0x364 and raw42–44 in0x368–0x370. This establishes the exact permutation; no value-based guess or anatomical default is used.

The local native `FemaleOutfitA` currently contains right pectoral translation `(1,1,1)` and left pectoral scale approximately `(.11377,.03010,.13131)`. Swapping the six values restores the authored translation and unit scale. This invalid saved transform is sufficient to deform weighted clothing; visual removal of the observed jersey spike must still be confirmed after repair and native reload. Whether the retired original server compensated this shipped mismatch is unknown.

## Exact existing-preset repair

A read-only audit found these female presets in the current integration database:

| Profile | Preset | Finding |
|---|---|---|
| Unique native numeric Windows account | Default | Canonical; excluded |
| Same native account | FemaleMorphA | Original writer permutation; repair pinned |
| Same native account | FemaleOutfitA | Original writer permutation; repair pinned |
| Other, non-native test account | Default | Canonical; excluded |

There were no other female presets in that snapshot. This is an audit of existing rows, not a general detector for arbitrary future data. The two repairs preserve the exact authored float values, including their small differences; they do not replace them with neutral values.

`../tools/repair_native_female_presets.py` defaults to read-only preparation. The prepared plan is `work/integration-state/avatar-female-repair-plan.json`; its canonical SHA256 is `5ca63eefba616eaf4d1fab9af1286df7575d905c64990bf4c10c8cbda1a8a8cd`. It contains a hashed account selector and six-field before/after values, without account/session identifiers.

The optional apply mode requires that reviewed plan, its exact hash, and a new backup filename. It checks the pinned account and original complete preset JSON hashes under a SQLite write reservation, snapshots the committed database including WAL, then updates only the two `preset_json` cells using compare-and-swap. Selection, profile gender, timestamps, entitlements, position, assets and all other rows remain unchanged. A changed or already repaired row is rejected. This worker tested apply mode only against temporary synthetic databases.

The parent subsequently reviewed and applied the real plan with all services/client closed. Its receipt is `work/integration-state/avatar-female-repair-applied.json`; backup is `work/integration-state-backup-before-semantic/before-female-preset-repair.sqlite3`. The parent verified both named rows normalized while selection and15 inventory items were preserved. Native visual confirmation remains pending.

After the HTTP process is reloaded, native testing must explicitly load repaired `FemaleOutfitA` before any resave, enter the world, inspect the jersey from the back, then save/reload once more and compare the six canonical fields. An already loaded deformed avatar carries its current transforms until a preset is reapplied. The ingress correction cannot reconstruct lost author intent from arbitrary earlier corrupted/resaved data.

## Offline validation

All160 backend tests pass (16.436 seconds), including16 focused avatar tests. The combined avatar/wardrobe/HTTP contract subset separately passed55 tests. Service/repair tests block sockets. They cover actual native export hashes and writer assignments, current metadata field names/offsets, a fixture with four distinct pectoral vectors, male preservation, female save/load/resave across SQLite reopen and fresh sessions, direct canonical storage, untouched defaults, and repair backup/refusal/single-application behavior. Earlier lifecycle test fixtures now emulate the original female writer instead of assuming it emitted canonical fields. `backend/tests/test_avatar_native_save.py` is automatically discovered by the existing backend suite; no additional tool-test module wiring is needed.

This worker performed no game, UI, listener, connection, backend restart, installed file modification or live database write. The parent-applied repair is separately recorded above.
