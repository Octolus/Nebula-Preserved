"""Build the static spawn contract from already extracted native/asset evidence."""

from _research_paths import workspace, output_root, game_path
import hashlib
import json
from pathlib import Path

ROOT = workspace()
OUT = ROOT/'results/protocol'
assets = json.loads((OUT/'tcp-world-spawn-assets.json').read_text(encoding='utf-8'))
bundle = next(b for b in assets['bundles'] if b['bundle']=='s/nexuslogicprefab')
controller = bundle['controllers'][0]
assert controller['class']=='ManagerInstanceNexus' and len(controller['spawnPoints'])==6
points = []
for point in controller['resolved_spawn_points']:
    leaf = point['ancestry_leaf_to_root'][0]
    points.append({'index':point['index'],'name':leaf['name'],'transform_path_id':leaf['transform_path_id'],'game_object_path_id':leaf['game_object_path_id'],'position_xyz':point['computed_world_position'],'rotation_xyzw':point['computed_world_rotation'],'forward_xyz':point['computed_forward'],'transform_raw_sha256':leaf['raw_sha256']})

sources = [OUT/'tcp-world-spawn-assets.json',OUT/'tcp-world-spawn-native.json',OUT/'tcp-world-loader-native.json',OUT/'tcp-world-prefab-native.json',OUT/'tcp-world-spawn-xrefs.json',ROOT/'work/decompiled/dump.cs']
for rva in ['5ea260','5dfdc0','4382a0','438a00','438a10','43bd90','43be60','43c820','4377f0','5e8480','617b10','46fa80','5f6a80','6033e0','5f63e0','5fc840','5f6ef0','622740','605d40']:
    path=ROOT/f'work/evidence/ghidra/functions/{rva}.c'
    if path.exists():
        sources.append(path)
native_steps = [
 {'rva':'0x5ea2be','action':'Read ManagerInstance.spawnPoints at instance offset 0x160.'},
 {'rva':'0x5ea2d6','action':'UnityEngine.Random.Range(int 0, array.Length) chooses one element. No saved-position or server-coordinate field is read in this selection.'},
 {'rva':'0x5ea335','action':'Disable Memory.localPlayerInfo.nebulaPlayer.PlayerControl.controller.'},
 {'rva':'0x5ea382','action':'Read selected spawn Transform.position.'},
 {'rva':'0x5ea3ac','action':'Assign that position to the local NebulaPlayer Transform.'},
 {'rva':'0x5ea3f0','action':'Read selected spawn Transform.forward.'},
 {'rva':'0x5ea41a','action':'Assign that forward vector to local NebulaPlayer Transform.forward.'},
 {'rva':'0x5ea473','action':'Set local player Animator bool AnimInfinite to false.'},
 {'rva':'0x5ea5a7','action':'Align NebulaCamManager.cameraPivotY X/Z to spawn; its Y is PlayerLabel.targetCam Transform.position.y minus float 0.45. This is a separate transform from the avatar root.'},
 {'rva':'0x5ea5f5','action':'Re-enable local CharacterController collider.'},
 {'rva':'0x5ea60e','action':'Store coroutine state 1 and yield null for one frame.'},
 {'rva':'0x5ea650','action':'Resumed state hides ScreenLoader; then clears ManagerInstance.isChatMenuLocked at offset 0x272.'},
]
result = {
 'scope':'Static native and serialized-asset reconstruction only. No game, Unity editor play mode, client, server, listening socket or connection/protocol test was run for this audit.',
 'conclusion':'In the modern OnConnected avatar-loaded path, the client places its local NebulaPlayer at one of six Nexus ManagerInstance.spawnPoints and copies its forward vector before revealing the scene. Earlier transport/preset coordinates do not determine the final arrival position in this path.',
 'confidence':{'native_path':'direct bounded x64 instructions and Ghidra pseudocode','coordinates':'parsed serialized Unity Transform trees and identity prefab root; not observed runtime coordinates','global_behavior':'bounded initial-load path; not a proof about later gameplay teleports, scene edits, collision settling or all modes'},
 'binary':{'sha256':'c4dd5db599e5e5ce4adf25f09ffe70ad10e0928adf6a2e862176d537026b44ac','preferred_image_base':'0x180000000'},
 'loading':[
  {'method':'Scenes.<LoadLogicPrefab>d__19.MoveNext','rva':'0x5e8480','finding':'Builds s/ + Scenes.Active + logicprefab, then awaits NebulaAssetBundleManager.Load. For Active=nexus this is s/nexuslogicprefab; it does not use s/pre/nexuslogicprefab.'},
  {'method':'NebulaAssetBundleManager.<Load>d__15.MoveNext','rva':'0x617b10','finding':'Loads dependencies, resolves StreamingAssets/platform/relativePath, loads bundle and all assets asynchronously, returns request.asset. This stage does not instantiate or place the prefab.'},
  {'method':'SpacePREFAB.<Initialize>d__4.MoveNext','rva':'0x46fa80','call_rva':'0x46fcca','finding':'After await LoadLogicPrefab, calls the one-argument Object.Instantiate<GameObject>(asset) overload at 0x8953d0, without parent/position/rotation parameters; no transform setter occurs in this body. Loads optional event prefab, destroys loading camera/ScreenLoader, then calls ManagerInstance.Launch at 0x46feaf.'},
  {'method':'ManagerInstanceNexus.Init','rva':'0x4377f0','finding':'Calls TCPInit; initializes cinema and optional night cycle. Does not replace spawnPoints. Bounded scans of 54 ManagerInstance/ManagerInstanceNexus methods find no memory operand displacement 0x160; this is scoped negative evidence, not a global field-use proof.'},
 ],
 'serialized_controller':{'bundle':bundle['bundle'],'bundle_sha256':bundle['sha256'],'asset_file':controller['asset_file'],'class':controller['class'],'path_id':controller['path_id'],'game_object':controller['game_object'],'raw_sha256':controller['raw_sha256'],'field':'ManagerInstance.spawnPoints','instance_offset':'0x160','root':controller['resolved_spawn_points'][0]['ancestry_leaf_to_root'][-1]},
 'spawn_points':points,
 'native_placement':{'method':'OnConnectedProcessor.<MoveAvatarDelay>d__3.MoveNext','rva':'0x5ea260','steps':native_steps,'local_reference_chain':['ManagerInstance.Memory(+0x2c0)','Memory.localPlayerInfo(+0x10)','PlayerInfo.nebulaPlayer(+0x30)'],'controller_reference_chain':['NebulaPlayer.playerControl(+0x28)','NebulaPlayerControl.controller(+0x28)'],'selection':'Random.Range(0,6); client RNG state is not recovered, so no single spawn index can be predicted statically.'},
 'ordering':[
  'Scene logic prefab is loaded and instantiated before ManagerInstance.Launch initializes/connects networking.',
  'CreatePlayer(0x5f6a80) -> CREATEPLAYER.MoveNext(0x6033e0) instantiates the gender base, then CreateGhost(0x5f63e0) applies AvatarInfo.lastPos to the NebulaPlayer root for both local and remote avatars.',
  'Asset assembly completes through PostInstantiateAssets(0x5fc840) and End(0x5f6ef0); CREATEPLAYER.MoveNext then clears loading flags and invokes NebulaPlayerAvatar.OnAvatarLoaded(+0xf8) with NebulaPlayer.GUID(+0xa0).',
  'OnConnectedProcessor avatar-loading continuation calls OnAvatarLoaded at 0x5dfdc0.',
  'OnAvatarLoaded initializes local control/random idle, sends its stored application opcode 1 through TCPClient.Send, then constructs MoveAvatarDelay state 0 and starts it on the local NebulaPlayer.',
  'MoveAvatarDelay state 0 sets avatar position/forward to a chosen scene point, then yields null. State1 hides the loading screen and unlocks chat menu.',
 ],
 'saved_position':{'finding':'HTTPGetPresetGame.OnResponse(0x622740) parses LastPosJson xyz and passes that Vector3 into AvatarInfo.ctor(0x605d40). AvatarInfo.lastPos is actually applied early by NebulaPlayerAvatar.CreateGhost(0x5f63e0): param_2 is NebulaPlayer, param_3 is AvatarInfo; it copies AvatarInfo+0x60/+0x68 into a Vector3 and calls Transform.set_position. Both local and remote paths converge before this assignment; isLocal at+0x9c only gates the earlier PS4Info.gender update. The reviewed later MoveAvatarDelay never reads LastPos; it supersedes this initial position for the local player. Remote avatars retain the initial HTTP position until other movement updates.','application_chain':['HTTPGetPresetGame.OnResponse(0x622740)','AvatarInfo.ctor(0x605d40)','NebulaPlayerAvatar.CreatePlayer(0x5f6a80)','CREATEPLAYER.MoveNext(0x6033e0)','NebulaPlayerAvatar.CreateGhost(0x5f63e0)','PostInstantiateAssets(0x5fc840)','End(0x5f6ef0)','local OnAvatarLoaded(0x5dfdc0)','local MoveAvatarDelay(0x5ea260)'],'cross_audit':'Exact earlier application/order supplied by the avatar agent from its existing static audit; original source files are hashed below.','not_claimed':'This does not claim LastPos is unused by remote-avatar construction, wardrobes, persistence, personal spaces, alternate paths or later teleports.'},
 'server_implications':[
  'Do not claim Mirror initial position(0,0,0) is a verified safe/visible Nexus arrival point. The client later moves its own root to a scene spawn before ScreenLoader.Hide.',
  'The C2S opcode 1 send precedes this final local placement and carries no chosen spawn index or coordinates in the recovered application message.',
  'Preserving this client behavior requires the real scene logic prefab, valid local player/control/camera/label components and completion of avatar load. Sending only an HTTP LastPos or Mirror position cannot replace those initialization steps.',
  'Server ownership and later NetworkTransform replication are a separate Mirror contract. This static spawn audit does not establish a successful connection or a working world session.',
 ],
 'known_limits':['No RNG/runtime selection observed.','No assertion about collider settling after the one-frame yield.','No full global proof that another component cannot later move the prefab/player.','No original server code or original server spawn policy was recovered.','No target runtime testing under current user constraint.'],
 'sources':[{'path':str(path.relative_to(ROOT)),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()} for path in sources],
}
(OUT/'tcp-world-spawn.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
lines=[
 '# Initial local Nexus spawn: static contract','',
 result['conclusion'],'',
 'No game/client/server was launched and no connection was tested. Native addresses below are RVAs in the exact GameAssembly.dll SHA256 `'+result['binary']['sha256']+'`. Pseudocode is decompiler output, not original C# source.','',
 '## Six bundled arrival points','',
 'The modern `s/nexuslogicprefab` bundle contains `ManagerInstanceNexus` with six ordered `spawnPoints`. Its root is at identity position/rotation/scale. `SpacePREFAB.Initialize` uses the one-argument `Instantiate<GameObject>(asset)` overload, so this reviewed load path adds no placement offset. Positions below are parsed asset coordinates, not runtime observations.','',
 '| Index | Name | Position (x, y, z) | Forward (x, y, z) | Transform path ID |',
 '| --- | --- | --- | --- | --- |',
]
for p in points:
    fmt=lambda v:', '.join(f'{x:.6g}' for x in v)
    lines.append(f"| {p['index']} | {p['name']} | ({fmt(p['position_xyz'])}) | ({fmt(p['forward_xyz'])}) | `{p['transform_path_id']}` |")
lines += ['',
 f"Bundle SHA256: `{bundle['sha256']}`. Serialized file: `{controller['asset_file']}`; ManagerInstanceNexus object path ID `{controller['path_id']}`; raw-object SHA256 `{controller['raw_sha256']}`. Full float values, quaternion rotations, raw Transform hashes and complete ancestry are in `tcp-world-spawn-assets.json`.",'',
 '## Native selection and ordering','',
 '`OnConnectedProcessor.OnAvatarLoaded` (`0x5dfdc0`) sends its stored application opcode 1, constructs the `MoveAvatarDelay` coroutine and starts it on the local NebulaPlayer. The successful state 0 path at `0x5ea260` performs these operations:','',
 '1. Read `ManagerInstance.spawnPoints` (+0x160) at `0x5ea2be`; choose `Random.Range(0, array.Length)` at `0x5ea2d6`.',
 '2. Disable `NebulaPlayer.PlayerControl.controller` at `0x5ea335`.',
 '3. Set the local NebulaPlayer root position to the chosen Transform.position at `0x5ea3ac`; set its forward vector to the chosen Transform.forward at `0x5ea41a`.',
 '4. Clear `AnimInfinite`, align the camera pivot separately, re-enable the CharacterController collider at `0x5ea5f5`, and yield null.',
 '5. On state 1, hide the loading screen at `0x5ea650` and clear `isChatMenuLocked` (+0x272).','',
 'The local reference chain is `ManagerInstance.Memory(+0x2c0) -> Memory.localPlayerInfo(+0x10) -> PlayerInfo.nebulaPlayer(+0x30)`. The collider is the CharacterController reached through playerControl(+0x28), then controller(+0x28); it is not the NebulaInteractor field. The camera pivot X/Z match the spawn; Y comes from the PlayerLabel.targetCam transform minus 0.45 and does not alter the avatar root.','',
 'The chosen index depends on the client RNG state. Static evidence establishes six candidates, not one predetermined point. The application opcode 1 precedes the final move and has no chosen spawn field.','',
 '## Scene-loading evidence','',
 '| Method RVA | Evidence |', '| --- | --- |',
 '| `0x5e8480` | Scenes.LoadLogicPrefab builds `s/` + Active + `logicprefab`; no `pre/` segment. |',
 '| `0x617b10` | NebulaAssetBundleManager.Load resolves the platform path, loads dependencies/assets, and returns the asset. |',
 '| `0x46fcca` | SpacePREFAB.Initialize calls one-argument Object.Instantiate<GameObject>. No transform setter occurs in this body. |',
 '| `0x46feaf` | SpacePREFAB.Initialize calls ManagerInstance.Launch after logic/event prefab creation. |',
 '| `0x4377f0` | ManagerInstanceNexus.Init calls TCPInit and cinema/night logic; no spawnPoints replacement. |','',
 'A bounded native scan of 54 ManagerInstance/ManagerInstanceNexus methods found no memory operand using displacement 0x160. This supports retaining the serialized field within those methods; it is not a global proof against all other code or indirect writes.','',
 '## LastPos and Mirror implications','',
 result['saved_position']['finding'],'',
 'An early Mirror spawn position is also superseded by this local assignment in the reviewed path. `(0,0,0)` is therefore not a verified Nexus arrival coordinate. The scene prefab and completed local avatar initialization are required to reach this placement. NetworkTransform ownership/replication and original server policy remain separate questions.','',
 'This audit does not establish post-yield collision settling, later teleports, behavior in every scene/mode, a successful connection, or original server behavior. Machine-readable evidence/provenance is in `tcp-world-spawn.json`; native instructions are in `tcp-world-spawn-native.json`, `tcp-world-loader-native.json` and `tcp-world-prefab-native.json`.','',
]
(OUT/'tcp-world-spawn.md').write_text('\n'.join(lines),encoding='utf-8')
print(json.dumps({'json':str(OUT/'tcp-world-spawn.json'),'markdown':str(OUT/'tcp-world-spawn.md'),'points':len(points),'sources':len(sources)}))
