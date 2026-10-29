> Historical research: this file records an earlier investigation, not current feature acceptance. The root [PROGRESS report](../PROGRESS.md) is authoritative. Local evidence and extracted game code are intentionally omitted. See [research index](README.md).

# Character customization persistence audit

Follow-up: native visual testing exposed an original female save-writer permutation that this earlier canonical-stream audit did not emulate. See [the source-bound correction and repair scope](avatar-female-save-compensation.md). The female HTTP test fixtures now reproduce that original writer.

The current backend retains the recovered male450/female462 preset fields across save, SQLite reopen and a new session GUID. Seven isolated service tests pass. This audit found no backend data-loss defect requiring a production change. It adds regression tests and static mesh evidence; it does not claim visual verification of every native editor control.

The audit used source files and original build11018722 artifacts only. No game, backend process, listener, connection, live profile or installed asset was started or changed. Exact source hashes and test scope are in `avatar-persistence-audit.json`.

## Data and native application

`N2SavePreset` decodes the declaration-ordered EntryData stream, rounds numeric inputs to client Single precision, validates each non-null wardrobe ID against the exact gender/category catalog and account entitlements, then stores every recovered field. `Store.save_preset` selects the saved name separately for each gender. `GetLastUsedPreset`, `GetLoadPresetByName` and `GetPresetGameServlet` return the complete stored JSON. The remote game-avatar response uses the target profile gender and target appearance, while response field1 remains the requester account identity required by the client. Position JSON identifies the target GUID/account.

Native named loading is not merely a successful HTTP response. `NETGcloudEditor.OnGetLoadPresetByName`3c4490 calls `CreatePlayer`3c3c10, which inlines the `ManagerPreset.LoadPreset`57d040 flow. After synchronous asset loading it invokes male591e30/female58f530 blend application, male592210/female58f910 bone application, male594430/female591bf0 skin application, cloth colors58eee0 and hat attachment58ea90. It then restores blend controls58b5c0 and the high-heel animator. The world avatar assembly has its own bone/blend/skin reapplication in `NebulaPlayerAvatar.PostInstantiateAssets`5fc840. These call paths exist; visible correctness remains a separate test.

The Maps-only tattoo/paint concern is resolved. Although57d040 constructs an `/FBX/` resource string for all categories, `AssetBundleManager.LoadAssetBundlePS4Editor`36ea50 selects `Load<Texture>` for tattoo/head-paint/tights categories. The shipped `ResourcesLoader.Load<T>`8a6c80 ignores the resource-path arguments and loads the typed item by its original item ID from the gender/item bundle. There is no evidence to justify a path patch in this route.

## Height and face must be checked separately

`CHARACTEREDITOR_SLIDERS.Height`3943e0 reads the current gender's height slider and sets every matching `MaleBase`/`FemaleBase` local scale to `(1 + sliderValue)` on all three axes. The native float at RVA1dd2c74 is exactly1.0 (`0000803f`). The bone readers store that scale as `MaleRoot_x/y/z` or `FemaleRoot_x/y/z`. On load, the bone writers set the height control from saved root_x minus1 and restore the complete saved scale. Therefore a height change should be assessed through all three Root fields and visible scale, not a head blend token.

The source-hashed default head channel inventory is `avatar-morph-channels.json`, produced by `../tools/inspect_avatar_morphs.py`. Examples for the shipped default head LOD0 meshes:

| Purpose | Male preset field / channel | Female preset field / channel |
|---|---|---|
| Neck thin | b73 / `Head_0_BS.Neck_Thin` | b74 / `CopyBlendshapes.Neck_Thin` |
| Neck fat | b72 / `Head_0_BS.Neck_Fat` | b73 / `CopyBlendshapes.Neck_Fat` |
| Nose outward length | b28 / `Head_0_BS.Nose_Lenght_out` | b29 / `CopyBlendshapes.Nose_Lenght_Out` |
| Nose width pair | b33/b34 | b34/b35 |

The earlier saved male b73=100 proves persistence of a neck channel. It cannot confirm height. Replacement full heads need their own evidence: the inspected native writer applies the complete face array to the genuine default head renderers, while other meshes with blend shapes receive only index0. Detailed default-head face controls cannot be assumed to work on arbitrary replacement heads.

The male reader586e30 captures91 values then appends zero b92. The female reader5820f0 captures87 then appends zero b88, even though the shipped female mesh has88 channels and index87 is named `Cupid_Bow`. This is a shipped reader limitation; the backend preserves the supplied stream. The default female head bundle contains matching lod0/lod1 renderers, while the native writer also recognizes a lod2 name. Raw channel prefixes differ among LOD meshes, so unequal raw name strings alone do not prove different semantic ordering.

## Tests added

`../backend/tests/test_avatar_persistence.py` uses temporary SQLite state and blocks socket creation. Its synthetic appearance inputs are explicitly not original service defaults.

- Male and female appearance save/reopen/new-GUID login retain every field, checking float32 bit equality. Inputs include blends, root scale, head bone scale, skin color, cloth color, hat offsets and the female stomach field spelling.
- Per-gender selection survives saving both genders; the game-avatar route selects the target's current female preset.
- Manifest-backed hat/left-hand items are added, compacted on removal and saved with the corresponding color slot. Removal from the outfit preserves account ownership.
- Gender-specific feet replace the correct ID/category; the supplied highHeel value is preserved rather than inferred from an uninspected asset.
- A Maps-only tattoo survives the same persistence route with its actual category.
- A different requester receives the target female appearance with the correct requester response identity and target position identity.
- Unowned/wrong-gender item saves fail without replacing the selected preset.

Run: `python -m unittest discover -s outputs/nebula-preservation/backend/tests -p test_avatar_persistence.py -v`.

## Remaining native verification sequence

This sequence is preparation for the parent-controlled native test; it was not executed by this audit.

1. Use the genuine default full head for the selected gender. Record the initial camera/framing and body/face values. Change Height and a distinct face control such as nose width. Verify the serialized Root scale triplet and the relevant gender-specific blend pair both change.
2. Save under a new nonempty preset name using the reviewed preset-input v2 flow: Save Preset, Return, type the name, Return. Require `N2SavePreset` success. Record the saved appearance fields without exposing session identifiers.
3. Change height/face visibly away from the saved state, then select the named preset. Require `GetLoadPresetByName`; compare the resulting body scale, face shape and editor controls with the saved state using the same framing. An HTTP200 alone is insufficient.
4. Save/exit through the native route, inspect the world avatar, then close and start a fresh client. Check the initially loaded avatar and reopen the editor to confirm the same saved state. This also tests the separate world assembly route and clears cached `Persistency.avatarInfo` as an explanation.
5. Repeat for female. Do not reuse male blend indices for different female semantics. Confirm each gender retains its own selected preset.
6. Equip a second nonmandatory category, save/reload, then unequip it through the native outfit action and save/reload again. Verify it is absent from the avatar and still available in account inventory. Storage/deleted wardrobe views are inventory-display operations, not proof of outfit removal. Mandatory torso/legs/head/hands/feet have default fallback rules and need separate assertions.
7. If color editing is tested, use a material that actually supports the control and an explicit reviewed local itemType. The server's default type1 is Normal; type2 means NormalEditable. Original item interaction metadata is not recovered globally from bundle names.

## Evidence boundaries

There is a narrow original-client attachment gap: save3c6680 reads hat and both hand offset arrays, but inspected editor load57d040/3c3c10 invokes `WriteAttachedItem` only with hat data/type0. Backend hand offset persistence is not evidence of their native reapplication. Reproducing a hand-offset control is necessary before preparing a compatibility patch; no speculative patch was made.

Original discontinued-service appearance defaults, commercial item interaction types and arbitrary replacement-head face compatibility remain unknown. The neutral fixtures remain explicit reconstructions from shipped assets. No missing body/face HTTP field or missing default head asset was found in this audit. Native visual verification is still required for exact morph reapplication, female appearance, another wardrobe category, heel behavior, colors and removal.
