> Historical research: this file records an earlier investigation, not current feature acceptance. The root [PROGRESS report](../PROGRESS.md) is authoritative. Local evidence and extracted game code are intentionally omitted. See [research index](README.md).

# Initial local Nexus spawn: static contract

In the modern OnConnected avatar-loaded path, the client places its local NebulaPlayer at one of six Nexus ManagerInstance.spawnPoints and copies its forward vector before revealing the scene. Earlier transport/preset coordinates do not determine the final arrival position in this path.

No game/client/server was launched and no connection was tested. Native addresses below are RVAs in the exact GameAssembly.dll SHA256 `c4dd5db599e5e5ce4adf25f09ffe70ad10e0928adf6a2e862176d537026b44ac`. Pseudocode is decompiler output, not original C# source.

## Six bundled arrival points

The modern `s/nexuslogicprefab` bundle contains `ManagerInstanceNexus` with six ordered `spawnPoints`. Its root is at identity position/rotation/scale. `SpacePREFAB.Initialize` uses the one-argument `Instantiate<GameObject>(asset)` overload, so this reviewed load path adds no placement offset. Positions below are parsed asset coordinates, not runtime observations.

| Index | Name | Position (x, y, z) | Forward (x, y, z) | Transform path ID |
| --- | --- | --- | --- | --- |
| 0 | Spawn Point Origin | (-22.11, 19.323, 27.31) | (0.918735, 0, -0.394874) | `-6156842241099354577` |
| 1 | Spawn Point Park | (34.51, 19.32, 65.97) | (-0.564168, 0, -0.82566) | `2965147469171295281` |
| 2 | Spawn Point Bowling | (-7.23, 19.34, 41.71) | (0.468515, 0, -0.883455) | `-8439589371330713728` |
| 3 | Spawn Point Beach | (67, 19.311, -24) | (0, 0, 1) | `7877514380706886611` |
| 4 | Spawn Point Dome | (46.83, 20.08, 20.19) | (-0.997948, 0, -0.0640298) | `7459093048511770470` |
| 5 | Spawn Point Cinema | (10.19, 19.48, -60.73) | (0.5, 0, 0.866025) | `6354698535567923801` |

Bundle SHA256: `7a555fddd0bf0743444f60a3eacf0533cc6ce3a546995b6bd6ffc2ed10bd5f66`. Serialized file: `CAB-c5363acfac84eb34fd358ba601dc24dd`; ManagerInstanceNexus object path ID `-7098812427836398199`; raw-object SHA256 `7dbe6365f08a8d303e329f5c3cc8636d8080a71478acdc7c3b515f1b112fc9e8`. Full float values, quaternion rotations, raw Transform hashes and complete ancestry are in `tcp-world-spawn-assets.json`.

## Native selection and ordering

`OnConnectedProcessor.OnAvatarLoaded` (`0x5dfdc0`) sends its stored application opcode 1, constructs the `MoveAvatarDelay` coroutine and starts it on the local NebulaPlayer. The successful state 0 path at `0x5ea260` performs these operations:

1. Read `ManagerInstance.spawnPoints` (+0x160) at `0x5ea2be`; choose `Random.Range(0, array.Length)` at `0x5ea2d6`.
2. Disable `NebulaPlayer.PlayerControl.controller` at `0x5ea335`.
3. Set the local NebulaPlayer root position to the chosen Transform.position at `0x5ea3ac`; set its forward vector to the chosen Transform.forward at `0x5ea41a`.
4. Clear `AnimInfinite`, align the camera pivot separately, re-enable the CharacterController collider at `0x5ea5f5`, and yield null.
5. On state 1, hide the loading screen at `0x5ea650` and clear `isChatMenuLocked` (+0x272).

The local reference chain is `ManagerInstance.Memory(+0x2c0) -> Memory.localPlayerInfo(+0x10) -> PlayerInfo.nebulaPlayer(+0x30)`. The collider is the CharacterController reached through playerControl(+0x28), then controller(+0x28); it is not the NebulaInteractor field. The camera pivot X/Z match the spawn; Y comes from the PlayerLabel.targetCam transform minus 0.45 and does not alter the avatar root.

The chosen index depends on the client RNG state. Static evidence establishes six candidates, not one predetermined point. The application opcode 1 precedes the final move and has no chosen spawn field.

## Scene-loading evidence

| Method RVA | Evidence |
| --- | --- |
| `0x5e8480` | Scenes.LoadLogicPrefab builds `s/` + Active + `logicprefab`; no `pre/` segment. |
| `0x617b10` | NebulaAssetBundleManager.Load resolves the platform path, loads dependencies/assets, and returns the asset. |
| `0x46fcca` | SpacePREFAB.Initialize calls one-argument Object.Instantiate<GameObject>. No transform setter occurs in this body. |
| `0x46feaf` | SpacePREFAB.Initialize calls ManagerInstance.Launch after logic/event prefab creation. |
| `0x4377f0` | ManagerInstanceNexus.Init calls TCPInit and cinema/night logic; no spawnPoints replacement. |

A bounded native scan of 54 ManagerInstance/ManagerInstanceNexus methods found no memory operand using displacement 0x160. This supports retaining the serialized field within those methods; it is not a global proof against all other code or indirect writes.

## LastPos and Mirror implications

HTTPGetPresetGame.OnResponse(0x622740) parses LastPosJson xyz and passes that Vector3 into AvatarInfo.ctor(0x605d40). AvatarInfo.lastPos is actually applied early by NebulaPlayerAvatar.CreateGhost(0x5f63e0): param_2 is NebulaPlayer, param_3 is AvatarInfo; it copies AvatarInfo+0x60/+0x68 into a Vector3 and calls Transform.set_position. Both local and remote paths converge before this assignment; isLocal at+0x9c only gates the earlier PS4Info.gender update. The reviewed later MoveAvatarDelay never reads LastPos; it supersedes this initial position for the local player. Remote avatars retain the initial HTTP position until other movement updates.

An early Mirror spawn position is also superseded by this local assignment in the reviewed path. `(0,0,0)` is therefore not a verified Nexus arrival coordinate. The scene prefab and completed local avatar initialization are required to reach this placement. NetworkTransform ownership/replication and original server policy remain separate questions.

This audit does not establish post-yield collision settling, later teleports, behavior in every scene/mode, a successful connection, or original server behavior. Machine-readable evidence/provenance is in `tcp-world-spawn.json`; native instructions are in `tcp-world-spawn-native.json`, `tcp-world-loader-native.json` and `tcp-world-prefab-native.json`.
