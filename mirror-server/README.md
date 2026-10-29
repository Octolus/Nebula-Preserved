# Unity scene server sources

This source tree implements the reconstructed game-instance transport using Mirror v66.0.9 (upstream commit `4d0cd1054a9011ee4492f91ed4bd16c671fea470`) and an authored preservation application layer. The historical Mirror version matches the recovered batching/message fingerprint; complete original server parity remains unproven.

The `UnityProject` includes authored preservation C# sources, its empty probe scene, the pinned Mirror runtime/Weaver and third-party dependencies, Packages and ProjectSettings. Unity Library/Temp, builds, logs, game assets and original game binaries are excluded. The four DLLs under Mirror/Plugins are third-party Cecil tooling used by the Weaver, not the game executable. Their licenses and the Mirror/transport licenses remain beside their sources.

## Linux build and deployment

On a Linux build host, install Unity **6000.6.3f1** with Linux Dedicated Server support, complete Unity licensing, and use Python 3.10 or newer:

```sh
python3 mirror-server/build_linux.py --unity /opt/Unity/Editor/Unity --build
```

Pass the editor executable itself, with no symlinks in the project, editor or output paths. The command uses the existing `PreservationBuild.BuildLinuxServer` method and Mono backend. It hashes the same 21 reviewed C# sources before and after compilation, checks the success marker and ELF64 x86-64 executable, and writes `mirror-server/build-linux-validation.json` with every file in the complete `build-linux` player directory. Report paths are relative and contain no editor installation path. The report works with the existing instance supervisor and packager.

Existing artifacts are never deleted by this command; Unity may update its own build outputs. A failed build preserves the previous report, whose hashes must still match before it can authorize a launch. Private, uniquely named `build-linux-*.log` files remain beside the report for troubleshooting and may contain local paths; do not publish them. An interrupted build may leave `.build-linux.lock`; remove it only after confirming that build has ended. Use a fresh source checkout/output directory when a clean artifact set is required. Build success proves compilation and artifact integrity; it does not prove Linux runtime or native multiplayer behavior. Start the backend and supervisor separately using the deployment instructions.


Run the resulting complete build through [Linux Docker Compose](../deployment/docker/README.md). The containers do not require an editor on the runtime host.

Run the portable build checks without invoking Unity:

```sh
python3 -B mirror-server/tests/test_build_linux.py
```

These checks use temporary source/output fixtures and include unreadable-directory failures. They do not establish game runtime acceptance.

## Historical Windows developer commands

Build with Unity6000.6.3f1 and the appropriate platform module. Linux requires Linux Dedicated Server support and the Windows-to-Linux toolchain when building from Windows; the build uses Mono2x. Unity licensing and dependency downloads are operator prerequisites.

```powershell
# Supply the location of your installed Unity editor, or set UNITY_EDITOR.
.\mirror-server\BuildLinux.ps1 -Unity $env:UNITY_EDITOR
.\mirror-server\Build.ps1 -Unity $env:UNITY_EDITOR
```

The Linux build script emits `build-linux/NebulaServer.x86_64`, its complete player directory and a NEW source/artifact hash report. The Windows script emits its own complete player directory and report. Copy complete builds, never a replacement DLL under an old report. No build is included in this repository and none was launched while exporting it.

For the smaller Windows-only Nexus baseline, after `Build.ps1` completes and the Python environment is ready:

```powershell
.\mirror-server\Start-CoreTest.ps1 -Start -Python .\.venv\Scripts\python.exe -StateDirectory .\private-state
```

This explicitly starts a loopback HTTP backend on8080 and one Nexus scene on28000. Without `-Start` it exits without starting processes. The portable adapter runs backend tests, verifies the new Windows build source/executable/assembly hashes and refuses occupied ports. It emits the two process IDs and private runtime logs; it does not launch or patch a game client. This exported adapter has been parsed and reviewed as source only; it has not been runtime-tested in the new repository layout. Other scenes/apartment travel require the managed supervisor configuration below.

For private managed worlds, first start the matching HTTP backend using `backend/README.md`. Then use `python tools/instance_supervisor.py --help`. The supervisor requires explicit state directory, binary/build-report paths, SHA256 values for the build report/executable/managed assembly, a concrete bind and advertised address, allowed scenes, allowed readiness profile and port range. It is a dry-run unless `--run` is supplied. A typical local port range is28000–28031. The allowed profile must match backend `nonmini-semantic-v1`; allowed scenes must come from reviewed catalog entries. This prevents inventing arbitrary scene readiness or reusing stale build pins.

The Unity process requires explicit instance/probe mode arguments. The supervisor supplies instance allocation, shared state and ownership arguments. A matching patched original client and private installed content are also required; the server source alone cannot make an unmodified retired-service client join it.

The primary source includes ownership/spawn state, movement, chat/social policies, housing, resource entitlements and durable companion/locomotion selections. The scene validates current-session authority, requests backend persistence through same-host IPC and broadcasts only after the matching durable acknowledgement and snapshot. A fresh private copy of all 601 public server files completed a full Linux Dedicated Server/Mono2x build, including Weaver processing and a new source/artifact report. Native sender/recipient reconciliation, fresh-session restoration and the broader acceptance matrix remain incomplete. The historical resource overlay must not be reapplied. Public remote transport remains experimental. Consult [current progress](../docs/PROGRESS.md) for observed behavior and blockers.
