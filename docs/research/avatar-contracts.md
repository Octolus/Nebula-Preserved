> Historical research: this file records an earlier investigation, not current feature acceptance. The root [PROGRESS report](../PROGRESS.md) is authoritative. Local evidence and extracted game code are intentionally omitted. See [research index](README.md).

# Avatar, wardrobe and save contracts

This is a static reconstruction for Steam919290 build11018722, Unity2021.3.9f1 IL2CPP. No game, client, server, UI test or live connection was started. Native method addresses below use GameAssembly.dll image base0x180000000. IL2CPP declarations supply field layouts; focused Ghidra pseudocode and bounded native disassembly supply behavior. These are not recovered C# source.

## Deliverables

`avatar-save-contract.json` contains the request/response grammar, exact450/462 ordered preset fields, native method/source hashes and constraints. `../tools/avatar_entry_codec.py` is an importable offline codec. `avatar-static-validation.json` records12 passing offline fixture/parser checks.

`avatar-asset-catalog.json` maps6374 wardrobe FBX/Maps asset rows from6274 item bundles to6255 distinct source IDs, gender/category hints, bundle names, actual asset paths and requested resource paths. `avatar-default-catalog.json` joins all11 native default-editor item literals to real bundle assets. Nine rows have unresolved gender/category;24 rows have conflicting category hints. Both remain explicit and are rejected by the item-to-category helper.

`avatar-neutral-male.json` and `avatar-neutral-female.json` contain complete450/462-field authored-neutral reconstruction fixtures. `avatar-neutral-seed-evidence.json` explains each field; `avatar-prefab-baselines.json` preserves the underlying serialized transforms/material properties. Original service-selected appearance defaults have not been recovered.

## Save request and result

ManagerPreset.Save0x18058b560 calls NETGcloudEditor.Send_SavePreset. NETGcloudEditor.getPresetDataToSave0x1803c6680 constructs PresetMaleJson for numeric gender0 or PresetFemaleJson otherwise, fills the current editor values and calls EntryData.Serialize0x1806a65b0. Despite the class names, this save payload is a custom reflection stream, not JSON.

Both coroutine bodies0x1803e3480 (save) and0x1803e4220 (save and exit) build this logical AES input:

[Code/listing block omitted from the public research archive.]

SessionGUID comes from PS4Info+0xe8 and PS4ID from+0xd8. Gender is integer decimal0 male/1 female. AES.Encrypt0x6a32c0 appends `#` plus the platform enum name internally before encrypting, including for these direct coroutines; the decrypted wire request therefore ends in `#StandaloneWindows` or `#PS4`. The client URI-escapes the ciphertext and requests GET`/N2SavePreset?data={0}`. The save coroutine selects its configured appspot base or local8080 from the existing PS4Info flag. The shared AES transport is documented by the HTTP protocol investigation.

The decrypted response is split on`#`. Success requires field0 exact lowercase`true` and Boolean.Parse(field1)==true;`true#true` satisfies these checks. There is no returned GUID check here. Successful ordinary save invokes PresetSaved; save-and-exit then closes the wardrobe.

A local implementation should split only the first four request separators, preserving any`#` in serialized string values. Header fields are not escaped by the client; preset names containing`#` cannot be represented unambiguously and should be rejected by the local backend. Session binding and item ownership must be enforced from local account state.

## EntryData stream

Serialize0x1806a65b0 calls GetType().GetFields() then SerializeFields0x1806a5d10. For public primitive/string fields, each lexical value is encoded as one UTF16 code unit whose unsigned value is`0x24 + value.Length`, followed by the value itself. Length is UTF16 code units; an astral character occupies two. The encoded fields concatenate directly. There is no JSON escaping, delimiter, terminator or outer field count.

Examples: empty string is just`$` (U+0024). String`abc` is`'abc` (prefix U+0027). Null is lexical`nulls`, producing`)nulls`. Unused clothing slots contain ordinary literal`null`, producing`(null`; these two sentinels have different meanings.

Float formatting is Single.ToString(InvariantCulture). DeserializeFields0x1806a5020 parses the float token as invariant Double with NumberStyles0xa7 then casts to Single. Other scalars use ToString; bool outputs True/False, and enum outputs symbolic names where defined. Enum decoding calls Enum.Parse and also accepts underlying numeric strings. Null tokens skip assignment, leaving the destination constructor/current value; therefore a literal string`nulls` cannot round-trip as an ordinary string.

The450/462 preset fields are taken in metadata declaration order, matching the observed GetFields flow; the client has not been run to independently confirm reflection order. Do not alphabetize the fields or use JSON property order from arbitrary input. The classes inherit only a private EntryData cursor. Preserve exact field spelling and casing, including male`skin_bodybumpmap` versus female`skin_Bodybumpmap` and the female stomach typos.

Arrays begin with a normal prefixed decimal element-count token, then their elements. String/primitive elements are individually prefixed. Nonnull EntryData object elements concatenate their own fields directly, without an element wrapper or length. Nonarray nested EntryData fields follow the same direct recursion. Null arrays are the nulls token and skip assignment. The native class-element reader does not support the writer's null class-element marker coherently; the helper rejects null nested objects/elements. GetArrayObject0x1806a5a50 may reuse existing larger destination arrays, and GetArrayValue0x1806a5bb0 creates missing class elements; the generic helper models stream values rather than CLR object reuse.

The module exports decode_flat_preset(text,gender,schemas), encode_value_texts(lexical_tokens), build_id_assets_tablenames(preset,gender,catalog), and schema-driven decode_entry_fields/encode_entry_fields. Generic field descriptors are ordered{name,type}, with type string/bool/int/long/float/double, {enum:[names]}, {array:element_type}, or {object:ordered_fields}. Floating values must be supplied as explicit invariant lexical strings for encoding; this avoids an unverified assumption about byte-identical Python/client numeric formatting. The decoder bounds lengths, array counts and finite preset numbers. Existing token spellings can be re-emitted losslessly.

## Preset to avatar and bundles

LoadPreset0x1805f8770 uses cached Persistency.avatarInfo for the local session when available; otherwise GetPresetGame0x1805f7800 delegates to HTTPGetPresetGame. The modern response handlers map the flat preset JSON plus IdAssetsTablenamesJson and LastPosJson into AvatarInfo. Their response-array contract is owned by the HTTP investigation.

CreatePlayer0x1805f6a80 checks IsPresetCorrect0x1805f8440 and the first item ID length (at least32). An invalid local preset triggers HTTPResetDefaultPreset and then refetch. Invalid source IDs or missing category data can therefore create a reset/refetch cycle before assembly.

IdAssetsTablenamesJson is{"data":"..."}. The data splits on`!`: all item IDs occupy the first half, with the corresponding category/table names occupying the second half. For example`idA!idB!CLOTH_BODY_TORSO!CLOTH_BODY_LEGS`, with no trailing separator. They are not alternating pairs. GetAssetNames0x1805f7410 and IsPresetCorrect use this arrangement. The category list must have more than three entries and include feet, head and hands. CLOTH_BODY_TORSO_LEGS_FEET counts as feet; CLOTH_BODY_FULLBODY sets all three flags. AddDefaultFeetIfNeeded0x1805f5c30 inserts a genuine gender default foot when necessary. Default fixtures already contain feet, hands and head plus torso and legs.

CREATEPLAYER coroutine0x1806033e0 loads the gender base and assembles the supplied slots. InstantiateIndividualAsset0x1805f7e00 requests ordinary prefabs using:

[Code/listing block omitted from the public research archive.]

BODY_TATTOO/BODY_PAINT/BODY_LEG_TIGHTS/HEAD_PAINT use Maps in place of FBX. The asset-bundle mode calls ResourcesLoader.LoadAsync with gender, original-case item ID and formatted resource path. Lowercase bundle filenames are a separate identifier. Some asset paths were moved under ART/ResourcesART or00_CLOTHS; the catalog preserves both the actual manifest path and the requested resource path.

PostInstantiateAssets0x1805fc840, UpdateBlends0x1805ff480, ModifySkin0x1805f8960 and WriteMaleBones0x180601920/WriteFemaleBones0x180600200 apply the reconstructed arrays/material state. RootCreationAvatar and serialized MaleBase/FemaleBase resources are present locally. Dependency names in manifests retain original developer build-drive prefixes; actual dependency resolution remains a runtime unknown.

## Default fixtures and constraints

The native default-editor loaders0x18057c4d0/0x18057b9a0 establish genuine torso, legs, feet, hands and full-head IDs, plus female hairstyle. They are in avatar-default-catalog.json with all actual bundle/asset references. The fixture uses this native call order for slots and matching category halves. Native ReadClothNETGCloud deduplicates active child names and pads to40 with literal null.

Male has92 blend values (91 head values plus final zero) and female88 (87 plus zero). The neutral head weights are zero. Bone fields come from serialized MaleBase/FemaleBase transforms matched against native readers. Root_x/y/z represent localScale, so the neutral value is1,1,1. Attachment defaults are six zeros then three ones for position/rotation/scale. All40 item-color RGB triplets are white as supported by default materials and native padding. Skin texture IDs and colors come from bundled materials; no textures were exported.

Female default feet serialize HighHeel._type1, yielding HighHeel1; male0 yields HighHeel0. Six female stomach JSON fields retain the shipped f_ch_c_stomaf_ch_jnt_ typo while mapping to F_ch_c_stomach_jnt. idpreset/iduser are empty local placeholders for the backend to replace. Presetname Default is an explicit local name. These fixtures reconstruct a neutral client appearance; they are not evidence of the discontinued service's original numerical defaults or preset ordering.

## Item ownership

Persistency.AddPurchasedAssets0x180615f30 passes PurchasesData.cloths and clothsName to GetDatas0x1806162f0. GetDatas indexes each ID and the name at the same index into AssetData{asset=ID,name=name}. Thus clothsName is a parallel name/display label, not a category list. The category lookup comes from the item catalog. All13 ID lists and13 matching Name lists should be initialized; each names list must be at least as long as its IDs list.

Commercial names, prices, SKU mappings and original ownership policy are not present in these manifests. A local admin add-item command can validate known exact item ID/gender/category and append it to cloths plus an explicit local label (or ID fallback), but should mark that label as reconstructed. Nine unresolved-category rows and all conflicting-category rows must not be silently guessed.

The offline checks cover both full fixture roundtrips with float32 bit equality, lexical token preservation, genuine default item/category matching, UTF16 surrogate lengths, delimiter-bearing strings, null/empty distinctions, malformed-length rejection and synthetic nested arrays/enums/int64. They do not establish game load, avatar assembly or network interoperability. Full runtime verification remains intentionally deferred.
