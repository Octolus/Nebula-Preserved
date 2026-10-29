> Historical research: this file records an earlier investigation, not current feature acceptance. The root [PROGRESS report](../PROGRESS.md) is authoritative. Local evidence and extracted game code are intentionally omitted. See [research index](README.md).

# Animation and profile entitlement boundary

Status: static reconstruction only. No game, server, listener, connection, or runtime target was started.

## Outcome

The shipped client proves that `GetPurchases` has real paired ID/name fields for `animations`, `dances`, `emotes`, `gestures`, `poses`, `profilePictures`, `bundles`, and `bundlesHousing`. It does **not** provide the original server's entitlement catalog for any of those groups.

The shipped dance, gesture, pose, and seating wheel entries are authored directly in `resources.assets`. They are available to the menu independently of `GetPurchases`; they are not evidence of ownership and must not be copied into account purchases. Consequently, no animation grant backend was added. An arbitrary string grant would satisfy the JSON shape while offering no evidence that the client can use it.

Machine-readable evidence and all exact authored pairs are in [animation-entitlements.json](animation-entitlements.json). The extractor is [inspect_animation_entitlements.py](README.md#omitted-local-evidence).

## Exact `GetPurchases` contract

`PurchasesData` stores parallel `List<string>` fields. `Persistency.AddPurchasedAssets` maps the fields to `TypePurchase` values, and `Persistency.GetDatas` indexes both lists at the same position to construct `AssetData { asset = ids[i], name = names[i] }`. A names list shorter than its ID list causes an indexed read failure.

| Type | Enum value | ID field / offset | Parallel name field / offset |
|---|---:|---|---|
| animations | 2 | `animations` / `0x28` | `animationsName` / `0x90` |
| dances | 4 | `dances` / `0x38` | `dancesName` / `0xA0` |
| emotes | 5 | `emotes` / `0x40` | `emotesName` / `0xA8` |
| gestures | 6 | `gestures` / `0x48` | `gesturesName` / `0xB0` |
| pose | 7 | JSON `poses` / `0x50` | `posesName` / `0xB8` |
| profilepicture | 8 | JSON `profilePictures` / `0x60` | `profilePicturesName` / `0xC8` |
| bundles | 11 | `bundles` / `0x70` | `bundlesName` / `0xD8` |
| bundlesHousing | 12 | `bundlesHousing` / `0x78` | `bundlesHousingName` / `0xE0` |

The case and singular/plural differences above are significant: the JSON field is `poses`, while the enum member is `pose`; the JSON field is `profilePictures`, while the enum member is `profilepicture`.

## Menu consumer contract

Observed native behavior:

- `MenuWheelDances.Show` selects the male or female `MenuWheelInflate`, filters the authored dance pairs by serialized male/female `AnimationClip` names, then inflates the parallel `entryNames` and `entryAnims` arrays.
- `MenuWheelGestures.Show` and `MenuWheelPoses.Show` inflate their authored parallel arrays directly.
- None of those three `Show` methods calls `Persistency.GetDatas`, `GetIdAssets`, or another purchase lookup.
- `MenuWheelInflate.AddEntry(displayName, animationTrigger)` writes the first argument to the visible label and stores the second as the animation name.

Authored shipped menu counts:

| Menu | Entries |
|---|---:|
| Dance, pre-gender-filter union | 22 |
| Gesture male | 20 |
| Gesture female | 19 |
| Pose male | 14 |
| Pose female | 16 |
| Seat male | 3 |
| Seat female | 2 |

These exact strings are useful for preserving authored menu behavior, but not as entitlement IDs. For example, the dance display `YMCA DANCE` maps to animator trigger `YMCADANCE`; that pairing says nothing about a purchase record.

## Catalog search boundary

The read-only inventory searched all 15,761 saved bundle manifests for a complete path segment named animation(s), dance(s), emote(s), gesture(s), pose(s), or profile picture(s). It found zero matching asset paths. Earlier substring hits such as `NC_DanceFloor01_Prefab` are housing decorations and are deliberately excluded.

`resources.assets` does contain seven `MenuWheelInflate` components, which the extractor parses using the shipped `MenuWheelInflate` field order. Their raw SHA-256 values and exact display/trigger pairs are retained in the JSON report.

## Safe reconstruction decision

- Keep all paired `GetPurchases` lists initialized, even when empty.
- Do not grant authored wheel entries: the menu already owns them locally.
- Do not derive ownership from bundle filenames, animation clip names, menu labels, or housing decoration names.
- Only populate these purchase groups after recovering an original response/capture or another shipped catalog that binds an exact entitlement ID to its exact parallel display name.
- `bundles` and `bundlesHousing` remain opaque server SKU/content mappings. The existence of local Unity asset bundles does not identify commercial bundle IDs or contents.

## Evidence

- `work/evidence/ghidra/functions/634fb0.c`: `GetPurchases.OnResponse` parses `PurchasesData` and calls `AddPurchasedAssets`.
- `work/evidence/ghidra/functions/615f30.c`: all 13 ID/name pairs mapped to enum values.
- `work/evidence/ghidra/functions/6162f0.c`: positional ID/name construction.
- `work/evidence/ghidra/functions/4ba520.c`, `4ba930.c`, `4be9d0.c`: dance, gesture, and pose menu inflation.
- `work/evidence/ghidra/functions/4bb5b0.c`: authored dance gender filtering.
- `work/evidence/ghidra/functions/4bb090.c`: display-name/animation-trigger consumer semantics.
- `work/evidence/assets/bundle-manifests.json`: bounded local bundle inventory.
- Installed `Nebula Realms_Data/resources.assets`: serialized authored menu components.

All source hashes are recorded in the JSON report. Native pseudocode is analysis output, not original source code.

## Unresolved

- Original account ownership, commercial labels, SKU IDs, prices, bundle contents, and entitlement policy.
- Any legacy non-menu consumer of `animations`, `emotes`, or `profilePictures` in this build.
- Runtime interoperability, intentionally untested under the static-only freeze.
