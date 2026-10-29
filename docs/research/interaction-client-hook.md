> Historical research: this file records an earlier investigation, not current feature acceptance. The root [PROGRESS report](../PROGRESS.md) is authoritative. Local evidence and extracted game code are intentionally omitted. See [research index](README.md).

# Native interaction registry hook: final exact-build candidate

The prepared Windows x64 candidate uses twelve exact PE sites and a sibling `NebulaRegistryBridge.dll`. It preserves the game's assigned IDs and dense receiver list, records complete initial/save/load epochs, and emits the chunked opcode 97 semantic descriptor. It is statically validated and incorporates a correction established by bounded prior private-client runtime evidence. This final bridge revision has not been executed; the Steam originals remain unchanged.

## Bound artifacts

| Artifact | SHA-256 | Size |
| --- | --- | ---: |
| Steam baseline `work/evidence/GameAssembly.dll` | `c4dd5db599e5e5ce4adf25f09ffe70ad10e0928adf6a2e862176d537026b44ac` | 42,310,144 |
| Composed input `work/patched-client-keyboard-focus/GameAssembly.dll` | `ec6f909d3af35c89cd287a2803b86839cd5d1b168bc1f76517eed2494c85e01b` | 47,281,152 |
| Candidate `work/interaction-registry-build/GameAssembly-final.dll` | `e61302de37b2914a0eb6c2e93e173d300e7638653d0bd1b2eb39eef7de26ad39` | 48,939,520 |
| `NebulaRegistryBridge.dll` | `07fa4033c844e6432b9e2809a1ed8eb64d30f80e985fa544d93baf2a1e456761` | 926,277 |
| Wrapper object | `5c3ae6c80323ff2d8a7708d5f6614868917bd5ceabf8ec7a8d1346dfc061e8b3` | 4,057 |

## Twelve exact sites

| Phase | Site RVA | Original bytes / target | Obligation |
| --- | --- | --- | --- |
| initial begin | `0x5eae90` | `e84ba32a00` → `0x8951e0` | Begin, then original FindObjects |
| save begin | `0x6be9ac` | `e82f681d00` → `0x8951e0` | Begin, then original FindObjects |
| load begin | `0x6bd280` | `48895c2408` | Begin, replay prologue, resume `0x6bd285` |
| initial occupable | `0x5eaec7` | `e8b4740200` → `0x612380` | Original Initialize, then Record |
| initial generic | `0x5eaf1d` | `e83e61e6ff` → `0x451060` | Original Initialize, then Record |
| save occupable | `0x6beab7` | `e8c438f5ff` → `0x612380` | Original first, then owner-bound Record |
| save generic | `0x6beb17` | `e84425d9ff` → `0x451060` | Original first, then owner-bound Record |
| load occupable | `0x6cbc4a` | `e83167f4ff` → `0x612380` | Original first, then owner-bound Record |
| load generic | `0x6cbc8e` | `e8cd53d8ff` → `0x451060` | Original first, then owner-bound Record |
| initial commit | `0x5eafe1` | `e8ca14e300` → `0x141c4b0` | Commit, then original SetResult |
| save commit | `0x6bec57` | `e8c47dceff` → `0x3a6a20` | Original Send_SavePreset, then Commit candidate |
| load commit | `0x6ca8dc` | `488b5028488b4840ff5018` | Replay completion delegate, then Commit |

Begin is required: it clears the pending source namespace even when the following scan is empty, so a complete empty epoch cannot retain stale entries. Record wrappers call the original initializer first and capture the installed `send_id`. At commit, occupables resolve a distinct dense-list `receive_id`; generics require equal IDs.

## Five-export ABI

The fixed ABI is declared in `client-fixes/interaction_registry_bridge_abi.h`:

[Code/listing block omitted from the public research archive.]

Sources are initial=1, housing-save=2, housing-load=3; kinds are generic=1 and occupable=2. `DllMain` retains only its module handle. Initialization and all IL2CPP work occur lazily on the original Unity thread.

## Canonical descriptors and framing

Static keys use the exact top-root name after stripping only a trailing `(Clone)`. The selected component's top root must be the unique active root with that normalized name. Static paths exclude the anchor root. Furniture uses an empty anchor and a path relative to the placed ground root. Missing/duplicate anchors, incomplete component descriptions, unresolved dense receiver IDs, or trusted-manifest mismatches fail the entire commit.

The document is split into contiguous raw UTF-8 slices of at most 4096 bytes. Each slice is independently base64url encoded without padding and sent as `97#guid#seq#zeroBasedPart#partCount#chunk`. Part count is capped at 256. This is below the shipped Telepathy limit: its constructor at `0x12ddb60` writes `0x4000` client/server limits, and `GetMaxPacketSize` at `0x73f8e0` returns the configured field.

Runtime observation exposed and closed one native overload mismatch. MethodInfo slot `0x252de38` resolves to a closed method at `0x877040` with a `List<Component>` return and incompatible `IEnumerable` RGCTX; it is not the required generic component-array enumerator. The final bridge has zero references to that slot. It calls non-generic `GameObject.GetComponentsInternal` at `0x1b87670` with the exact eight-argument ABI and obtains the `Component` `System.Type` from IL2CPP parent metadata. The baseline helper prefix is `48895c240848896c2410488974241857`.

A successful INITIAL commit always hands off a complete housing LOAD namespace. With an owner, the bridge publishes the complete typed ground signature even when there are no interactive entries, and the collected ground count must equal the validated owner-list size. Without an owner, only an empty LOAD entry set is valid; this publishes an explicit empty public-world namespace and ground signature. Ownerless records and malformed or partially collected nonzero ground lists fail closed. A later genuine owner LOAD follows the same complete validation path.

## Guard and evidence boundary

The bridge C++ source is SHA-256 `484b0a6e86feeaa63c091695622206aa3d0718321c38ef3a1db7ce506079c4f3`. The guard is `tools/interaction_registry_patch.py` SHA-256 `911e8f8484c53017631baf29ca22b6ea56a7768c44b35c162c1625bdb3228850`. Its final report is `work/interaction-registry-build/interaction-registry-patch-final.json`, SHA-256 `7760e123420a971049114a8e3b266e2b6cdb35078088f11af5c551af36b11b35`, size 9,010.

The report proves strict input/wrapper/DLL hashes, all five exports, native helper prefixes, the supported housing MethodInfo slot, absence of the rejected component-enumeration slot, disassembly of every wrapper, 13 registered unwind records, successful PE reparse, and exactly 84 changed bytes across the twelve approved original sites. The appended `.nbi` section contains 1,536 bytes of code and 112 bytes of unwind data; original runtime-function entries remain preserved.

The bounded prior private-client observation proves the rejected overload mismatch and informed the corrected helper; it does not prove this final bridge revision or every Unity interaction path. The Steam installation is unchanged, and save activation remains server-pending until its typed ground signature matches backend durability. Full runtime acceptance must use the isolated runner and retain `game_ready=false` until those observations pass.
