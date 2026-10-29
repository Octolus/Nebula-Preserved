# Static reconstruction tools — operator fixtures required

This directory preserves67 research/extraction/patch-validation Python scripts from the reconstruction. The operational tools in the parent directory remain separate and unchanged. `INVENTORY.json` lists every retained script, its exported hash, and every omission. No original game binary, asset, Ghidra project/export, decompiler dump, private account, runtime receipt or extracted fixture accompanies these sources.

These are **staged research tools**, not a new one-click preservation installer. Paths were ported and syntax checked; their historical fixture-dependent pipelines were not rerun while packaging. Use the current patcher/client source overlays for installation. Historical patch scripts retain exact source hashes, instruction checks and new-output safeguards; a script refusing a newer binary is expected and must not be bypassed casually.

## Explicit inputs and outputs

```sh
python tools/research/run_research.py --list
python tools/research/run_research.py --script inspect_native.py --workspace ./work/research-fixtures -- --help
```

The second command prints a plan only. Create the fixture directory yourself. Add `--execute` before `--` to run the selected tool. Supply `--game-dir` when a script reads installed Unity assets. That path must be your own installation; there is no personal Steam-folder default. The runner refuses to use the primary repository root or the game installation as its output workspace. An explicitly chosen ignored `work/research-fixtures` subdirectory is suitable.

For direct script invocation instead, set `NEBULA_RESEARCH_WORKSPACE` to an existing fixture directory and, when needed, `NEBULA_GAME_DIR` to your own installed game directory. `workspace()` fails clearly when unset. Report outputs go under the chosen workspace's `results/`; CLI output overrides remain available where the original tool supports them. The runner deliberately executes no script without `--execute`.

Historical fixture layout remains recognizable:

* `work/decompiled/dump.cs` and `work/decompiled/script.json`: locally generated IL2CPP declarations/metadata.
* `work/evidence/GameAssembly.dll`: your own exact-version executable input, read statically.
* `work/evidence/ghidra/functions/<rva>.c`: your own source exports for report builders.
* `work/evidence/assets/*.json`: locally extracted manifests/type-tree inventories.
* `results/protocol/`: working schema/catalog/report copies; seed these from exported `protocol/` or `docs/research/` as the selected tool requires.
* `results/client-fixes/`, additional named `work/` candidate folders and compiler outputs: operator-supplied inputs to historical guarded patch/model tests. These are not supplied here. Current client-fix source lives elsewhere in this repository and may require an explicit path/layout adaptation before use.

Several scripts publish fixed historical report filenames and overwrite working reports. Use a dedicated disposable fixture workspace and inspect each script's source/arguments before executing it. They must not point at the primary source tree or an active server database. Some read their fixture at module load, so even direct `--help` may require configured input files/dependencies. The plan-first runner itself does not import the target tool.

## What is preserved

Avatar/default-item catalog extraction, IL2CPP schema parsing, annotated native disassembly, Mirror command/RPC identification, TCP caller/handler/field contracts, world loading/spawn analysis, minigame schema research, gathering/reward/shop branch reports, semantic interaction/furniture manifest builders and guarded PE/Unity-asset patch/model validation remain available as source. Legacy whole-workspace status publishers, process/listener orchestrators, desktop capture and client preparation launchers are omitted. Eight already-curated parent operator scripts are not duplicated.

Standard-library scripts need Python3.10+. Individual static readers additionally import `UnityPy`, `capstone`, `pefile` or `PyYAML`; install only the dependencies required by the selected script in a separate environment. Native/assembly patch validation can also require an operator-installed compiler and locally rebuilt helper object, with its exact recorded hash. Dependency installation and script execution were not performed as part of this export. Imported module names are listed in `INVENTORY.json`; they include local peer/helper modules as well as third-party packages.

The algorithms and observations reflect historical stages. Static branch coverage, a report flag or a synthetic model test is not native gameplay acceptance. Missing raw evidence remains a missing input, not a reason to invent source data or claim a result. Current root progress documentation takes precedence over historical generated status text.
