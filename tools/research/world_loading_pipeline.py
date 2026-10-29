"""Build evidence-indexed static world-loading report; never executes the target."""

from _research_paths import workspace, output_root, game_path
import hashlib
import json
from pathlib import Path

ROOT = workspace()
OUT = ROOT / 'results/protocol'
GHIDRA = ROOT / 'work/evidence/ghidra/functions'

def digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

rvas = [0x68b170,0x69f440,0x69f890,0x69f9e0,0x69fde0,0x69fb30,
        0x634130,0x641ef0,0x429fd0,0x611310,0x5e59f0,0x5e9800,
        0x5e8480,0x5e9470,0x5e8810,0x5e8ae0,0x5e9110,0x5e8db0,
        0x617b10,0x617250,0x4dc2f0,0x4dbf10,0x8a6c80,0x9e0060,
        0x6ec320,0x3d5a40,0x400ae0,0x635bf0,0x635990,0x63c370,
        0x63c190,0x6427c0,0x63beb0,0x46c4d0,0x46f870,0x46c570,
        0x46fa80,0x438a10,0x43c820,0x4386b0,0x438520,0x438f80,
        0x6e82a0,0x5e0570,0x5ea6e0,0x5eb3a0,0x6e7af0,0x622740,
        0x5f63e0,0x6033e0,0x5dfdc0,0x5ea260,0x608270,
        0x12499a0,0x12499d0,0x1249a00,0x42aa90,
        0x3d54b0,0x46b4b0,0x648800,0x6477f0,0x6474e0,0x648b80,0x648a20]
meta = json.loads((ROOT/'work/decompiled/script.json').read_text(encoding='utf-8'))
names = {}
for m in meta['ScriptMethod']:
    names.setdefault(m['Address'], []).append(m['Name'])
evidence=[]
for rva in rvas:
    path=GHIDRA/f'{rva:x}.c'
    evidence.append(dict(rva=hex(rva),names=names.get(rva,[]),
                         path=str(path.relative_to(ROOT)),exists=path.exists(),
                         sha256=digest(path) if path.exists() else None))

stages = [
 dict(stage='boot',evidence=['0x68b170','0x69f440','0x3afd00'],
      order=['Initialize modern local bundle manager', 'Start independent game-music initializer',
             'Initialize Scenes', 'Await nav load', 'Await s/nebulaplayer load',
             'Load preinitiload in Single mode', 'PreInitLOAD.Start loads InitLOAD in Single mode'],
      caveat='PreInitLOAD is bounded assembly evidence in world-loading-preinit-native.json; built-in ScreenLoader exists before PreInitLOAD.Start.'),
 dict(stage='allocate',evidence=['0x6ec320','0x3d5a40','0x400ae0','0x635bf0','0x635990','0x63c370','0x63c190','0x6427c0'],
      initial_request_scene='Login',initial_request_is_space_to_load=True,
      server_status_success=1,
      load_space_request_fields=['SessionGUID','PS4ID','psidglobal','isTesting Boolean','noIdSpace','desiredGuid'],
      load_space_response_fields=['SessionGUID','isBanned Boolean','noFreeSlot Boolean'],
      space_loading_request_fields=['SessionGUID','PS4ID'],
      space_loading_ready_response_fields=['SessionGUID','ready Boolean','id_instance','psidglobal','ip','port decimal'],
      ready_false_retry=dict(seconds=1.0,time='scaled WaitForSeconds',limit_observed=None),
      requirement='Map initial Login allocation sentinel to a concrete available scene; ready response psidglobal is a literal local scene key, not the unique instance ID.'),
 dict(stage='join_and_load',evidence=['0x63beb0','0x5e9800','0x46fa80','0x5e8480','0x5e9470'],
      maxusers_hardcoded=32,
      response_field_mapping={'id_instance':'SpaceParams+0x10','psidglobal':'SpaceParams+0x18','ip':'SpaceParams+0x28','port':'SpaceParams+0x30'},
      scene_path='Application.streamingAssetsPath/StandaloneWindows/s/{response.psidglobal.ToLower()}',
      mode='Additive (1)',logic_bundle='s/{Scenes.Active}logicprefab',event_bundle='s/{Scenes.Active}spaceevent',
      logic_required=True,event_optional=True,
      not_loading_new_scene_branch='isSpaceToLoad=false invokes InitPlayerTCP directly'),
 dict(stage='mirror_connect',evidence=['0x438a10','0x43c820','0x4386b0','0x438520','0x438f80'],
      network_address='HTTP SpaceParams.ip -> ManagerInstance+0x260 -> inherited NetworkManager.networkAddress+0x38',
      port='HTTP SpaceParams.port -> ManagerInstance+0x268 -> TelepathyTransport.port+0x68 (ushort)',
      connect='TCPClient.Connect -> Mirror.NetworkManager.StartClient',
      on_client_connect='base NetworkManager.OnClientConnect then NetworkClient.AddPlayer',
      watchdog=dict(seconds=30.0,time='WaitForSecondsRealtime',
                    failure='Close client and reallocate current scene/instance with isSpaceToLoad=false',
                    does_not_cover='Transport-connected avatar/HTTP/asset stalls')),
 dict(stage='spawn_then_app_zero',evidence=['0x6e82a0','0x5ea6e0','0x5eb3a0'],
      must_precede_app_zero=['Mirror local player identity spawn', 'Connection.identity/netId assigned'],
      client_start='NebulaPlayer.Start -> SetPlayer; local branch sets Memory.LocalNebulaPlayerToConnected, player GUID, input and local PlayerInfo',
      pending_announcement='1#netId#SessionGUID#username#numericPlatform',
      app_zero_wait='UniTask.WaitUntil(Memory.LocalNebulaPlayerToConnected is Unity-valid)',
      callback='PlayerLabelInfo request and local NebulaPlayer.LoadAvatar(SessionGUID, OnAvatarLoaded)',
      parallel_initialization=['All active NebulaOccupable.Initialize', 'All active GenericInteractable.Initialize', 'Registered SpaceGameManager values'],
      response_count_gate_observed=False,
      risk='OnConnected constructs netId-bearing announcement before WaitUntil, so sending app0 before Mirror spawn can dereference null identity.'),
 dict(stage='avatar_and_close',evidence=['0x6e7af0','0x622740','0x5f63e0','0x6033e0','0x5dfdc0','0x5ea260'],
      dependency='GetPresetGame response must satisfy exact avatar contract, item table catalog and locally resolvable assets',
      early_position='CreateGhost copies HTTP AvatarInfo.lastPos to the instantiated player root for local and remote players',
      avatar_complete='PostInstantiateAssets -> End -> clear creation queue/loading flags -> OnAvatarLoaded callback(GUID)',
      connected_callback=['Animation controller', 'Enable NetworkTransform', 'Companion and locomotion',
                          'Fire GetAllInWardrobe asynchronously', 'Destroy prior local player if present',
                          'Initialize player control and RandomIdle', 'Send stored C2S1 announcement',
                          'Start MoveAvatarDelay'],
      local_override='MoveAvatarDelay chooses a serialized Nexus spawn point, applies position/forward/camera, then yields null once',
      close=['SpinCircle.Hide', 'ScreenLoader.Hide', 'ManagerInstance.isChatMenuLocked+0x272=false'],
      server_roster_or_state_ack_required_to_close=False,
      caveat='Uncaught exceptions or missing local resources can prevent callback completion; absence of an explicit reply-count gate is not proof all optional requests are safe to omit.')]

findings = dict(
 modern_allocation=dict(result='HTTP direct allocation followed by Mirror is the active traced modern path',
                        separate_loadbalancer_server_required_by_trace=False,
                        scene_response_must_be_literal=True,
                        distinguish_request_Login_sentinel=True),
 legacy_loadbalancer=dict(getters={'0x12499a0':'104.196.161.5','0x12499d0':'104.196.60.146','0x1249a00':28000},
                         direct_getter_call='get_Ip called at 0x42ab8c from PS4Info.Init; assigns ipLoadBalancer',
                         modern_socket_use_observed=False,
                         legacy_dto_typeinfo_references=0,
                         limitation='E8/E9 byte-position candidates do not cover virtual, indirect, reflection or inlined calls.'),
 local_assets=dict(remote_manifest_needed_in_traced_modern_path=False,
                   scene_loader='Local AssetBundle.LoadFromFileAsync; first scene path; SceneManager.LoadSceneAsync',
                   modern_asset_loader='Local file/cache; missing bundle returns null; no HTTP fallback',
                   shared_dependency_loader='Loads local skinmaterials only; not a generic manifest dependency resolver',
                   resources_fallback='Only bounded local filename rewrite for enye-containing item IDs; no HTTP fallback observed',
                   optional_missing='s/nexusspaceevent returns null and is skipped',
                   legacy_url='Redacted legacy assetbundleserverurl http://LEGACY_ASSET_HOST:7888/ belongs to legacy AssetBundles manager; active use not established',
                   new_loader_patch_justified_by_trace=False),
 readiness=dict(ready=False,target_execution=False,connections=False,
                claim='Static path reconstruction; no end-to-end or 1:1 runtime equivalence claim'),
 remaining_core_dependencies=[
   'Bootstrap identity/session and prerequisite HTTP tasks must produce the exact recovered callbacks; see bootstrap-response-contracts.',
   'Initial Login allocation sentinel must resolve to an available instance and literal scene key.',
   'Mirror identity spawn/component order/payload must match the shipped prefab and precede application opcode0.',
   'GetPresetGame/PlayerLabelInfo, avatar EntryData catalog/assets and avatar completion callback must be valid.',
   'GetAllInWardrobe nonempty responses require the documented copied-client loop fix and PlayerLabelJson elements; empty OK# suppresses callback in the original path.',
   'Local scene, logic, nav, player, UI and skinmaterials objects must deserialize and instantiate in the shipped player; file presence does not establish runtime compatibility.',
   'World occupancy/interactables/state replies and remote presence remain required for restored behavior even though no aggregate reply count gates ScreenLoader.Hide.'
 ],
 limits=[
   'Only bounded bootstrap/Nexus roots and their shipped text-manifest dependencies were hashed, not every avatar/housing asset.',
   'All14 built-in boot MonoBehaviour headers resolve; full typetree parsing fails for12 and those errors are preserved. All9 Nexus MonoBehaviour headers resolve; selected loader full-typetree parsing has0 errors.',
   'Ghidra output is native pseudocode, includes merged tails/generic names/indirect-call warnings, and is not recovered original C#.',
   'Legacy absence findings are scoped to the traced modern path and direct-call candidate scan.',
   'No server, listener, game, client or connection was started by this audit.'
 ])
artifacts=['world-loading-assets.json','world-loading-methods.json','world-loading-xrefs.json',
           'world-loading-native.json','world-loading-preinit-native.json',
           'tcp-world-spawn.json','tcp-wardrobe-patch.json','bootstrap-response-contracts.json']
out=dict(scope='Static installed-build world-loading path and local dependencies',
         binary_sha256=digest(ROOT/'work/evidence/GameAssembly.dll'),
         metadata_sha256=digest(ROOT/'work/decompiled/script.json'),stages=stages,findings=findings,
         native_pseudocode=evidence,
         supporting_artifacts=[dict(path=x,sha256=digest(OUT/x)) for x in artifacts])
(OUT/'world-loading-pipeline.json').write_text(json.dumps(out,indent=2)+'\n',encoding='utf-8')

md='''# Static world-loading pipeline

The modern path allocates an instance over HTTP, loads the installed scene and logic bundles, and connects directly with Mirror/Telepathy. This path does not require a separate load-balancer socket server or a remote bundle manifest. This conclusion is scoped to the traced methods; it does not claim every legacy path is unreachable.

No game, client, server, listener or connection was started. Readiness remains **false**. The [machine-readable report](world-loading-pipeline.json) records method names, RVAs, pseudocode hashes, stage contracts and supporting artifact hashes.

## Allocation and address handoff

1. After user-online success, `MANAGERLogin.<LoginProcess>b__46_1` (`0x6ec320`) calls `NETGcloudLogin.LoadSpace("Login", "", true, "", null)`. **Login is the initial allocation request sentinel.** The server must map it to an available public scene rather than demand an instance whose scene is literally Login.
2. `LoadSpace` (`0x3d5a40`) checks server status. Callback `0x400ae0` accepts status1; status0/2 select maintenance/update scenes. It then processes N2LoadSpace (`0x635bf0`): `SessionGUID#PS4ID#psidglobal#isTesting#noIdSpace#desiredGuid`.
3. N2LoadSpace.OnResponse (`0x635990`) consumes `[SessionGUID,isBanned,noFreeSlot]`. The GUID must match. Banned selects UserBanned; full invokes the supplied callback. Normal success starts N2SpaceLoading.
4. N2SpaceLoading sends `SessionGUID#PS4ID` (`0x63c370`). Response (`0x63c190`) is `[SessionGUID,ready,id_instance,psidglobal,ip,port]` when ready. `ready=false` schedules another Process after **1.0 scaled second** (`0x6427c0`); no polling limit is observed.
5. JoinSpace (`0x63beb0`) stores instance ID, scene key, IP and parsed port in SpaceParams and fixes maxusers to **32**. `isSpaceToLoad=true` invokes `Scenes.Load(psidglobal, Additive=1, false)`; false invokes InitPlayerTCP directly.

The response scene field must be a literal local key such as **Nexus** or LeafPark. It is lowercased into a bundle path. It does not pass through SeparateSpaceName. Keep the unique `id_instance` separate from this scene field; arbitrary owner prefixes or unique IDs in psidglobal would select a nonexistent local bundle.

`TCPInitialize`/`InitPlayerTCP` (`0x43c820`, `0x4386b0`) transfer SpaceParams to ManagerInstance fields `+0x248/+0x250/+0x258/+0x260/+0x268`. Connect (`0x438520`) copies the HTTP IP into inherited NetworkManager.networkAddress and the HTTP port into TelepathyTransport.port, then TCPClient.Connect starts Mirror.StartClient. Several methods share compiler tails; the evidence index preserves their individual pseudocode files.

The 30-second realtime watchdog (`0x444150`, bounded assembly in [native evidence](world-loading-native.json)) checks transport connectivity only. Failure closes the client and repeats allocation with the current scene/instance and `isSpaceToLoad=false`. An already connected transport with a stalled avatar does not trigger this recovery.

## Load-balancer code is legacy evidence

`loadbalancerConn` supplies three constants: development104.196.161.5 (`0x12499a0`), production104.196.60.146 (`0x12499d0`), port28000 (`0x1249a00`). The executable-section E8/E9 candidate scan finds the production getter at `0x42ab8c` in PS4Info.Init; this assigns ipLoadBalancer. It finds no direct calls to the other two getters. The legacy MANAGER_MSGS.LOADBALANCER DTO types have zero ScriptMetadata TypeInfo references.

The traced HTTP JoinSpace does not invoke those getters, a SpaceLoaderBalancer or the older NETGcloudLogin.JoinSpace/SpaceLoaderManager.JoinSpace path. The Nexus scene has an active SpacePREFAB and no SpaceLoaderManager/SpaceLoaderBalancer component among its nine resolved MonoBehaviour headers. The selected SpacePREFAB full typetree parses without errors; this is not a full-field audit of the other eight components. Thus a separate load-balancer service is not a demonstrated dependency here. The [xref artifact](world-loading-xrefs.json) explicitly does not cover virtual/indirect/inlined/reflection calls.

## Local scene and asset loading

Booter.Start (`0x68b170`) initializes the modern NebulaAssetBundleManager, starts the independent music initializer and initializes Scenes. Music initializer (`0x641ef0`) awaits local gamemusic, instantiates it, marks it persistent and calls GameMusic.InitGameMusic. Booter.Init (`0x69f440`) awaits nav, then s/nebulaplayer, then loads preinitiload in Single mode. It does not invoke its LoadScreenLoader/LoadPooler helpers. Built-in level0 already contains active ScreenLoader (path46), SpinCircle47, Booter45 and both managers43/44. ScreenLoader.get_Instance (`0x429fd0`) resolves the existing object with FindObjectOfType; it does not load a resource. All14 boot component headers resolve; full typetree parsing failed for12 and those exact errors remain in the asset artifact. Bounded PreInitLOAD.Start assembly (`0x3afd00`) selects PC platform1, updates version from VersionGame, and loads InitLOAD in Single mode.

Scenes.Load (`0x5e9800`) uses `Application.streamingAssetsPath/StandaloneWindows/s/{lowercase scene}` with AssetBundle.LoadFromFileAsync, takes GetAllScenePaths()[0], switches to the main thread and awaits SceneManager.LoadSceneAsync. Single mode first awaits UnloadAll; Additive bypasses it. No URL or remote manifest is used here. Progress display is a local bundle/scene calculation, not server progress.

SpacePREFAB starts the scene initialization chain (`0x46c4d0` -> `0x46f870` -> `0x46c570` -> `0x46fa80`). It awaits `s/{Active}logicprefab` (`0x5e8480`), instantiates it, then awaits `s/{Active}spaceevent` (`0x5e9470`). Logic is required; event is tested for null and optional. It destroys its temporary camera/screen-loader reference and launches ManagerInstance. Nexus's event bundle is absent, which this branch accepts; its scene and logic bundles are present.

NebulaAssetBundleManager.Load (`0x617b10`) uses a local cache and local file existence check. A missing file returns null; it has no HTTP fallback. LoadExtract (`0x617250`) follows the same local mechanism with a named asset. ResourcesLoader.LoadDependenciesBundles (`0x4dc2f0`) loads local skinmaterials, not a generic remote/text-manifest dependency system. ResourcesLoader.Load<object> (`0x8a6c80`) and its async state (`0x9e0060`) use local normalized item folders gated by PS4Info asset flags; the bounded fallback rewrites enye-containing local filenames.

The [asset audit](world-loading-assets.json) hashes all11 selected roots and their text-manifest dependency closure: nav, skinmaterials, gamemusic, screenloader, pooler, s/preinitiload, s/initload, s/login, s/nebulaplayer, s/nexus, s/nexuslogicprefab. None are missing. Nexus declares skinmaterials; its logic declares nav and skinmaterials; the player and pooler declare skinmaterials. These shipped text manifests are inventory evidence, not manifests fetched or parsed by the traced runtime loader.

The embedded `assetbundleserverurl` value `http://LEGACY_ASSET_HOST:7888/` belongs to legacy AssetBundles.AssetBundleManager code. The direct-call scan finds no external callers of its Initialize/source-URL setup methods, and modern loader methods do not call it. Its active use is unproven; there is no basis here to create a remote bundle server or patch this loader.

## Mirror spawn, avatar and loading-screen closure

ManagerInstance.OnClientConnect (`0x438f80`) calls base Mirror handling and NetworkClient.AddPlayer. The server must send the local Mirror spawn with correct shipped prefab/component data before application opcode0. OnConnected's async body (`0x5ea6e0`) constructs `1#netId#SessionGUID#username#numericPlatform` before its WaitUntil; it dereferences connection.identity to get netId at that point.

NebulaPlayer.Awake/Start (`0x6e7a10`, `0x6e88c0`) set NetworkIdentity and call SetPlayer (`0x6e82a0`). The local branch records Memory.LocalNebulaPlayerToConnected, assigns SessionGUID, initializes input and creates local PlayerInfo. The remote branch queues the NebulaPlayer by netId. OnConnected awaits the local-memory pointer (`0x5eb3a0`), clears it, initializes the interaction menu, fires PlayerLabelInfo and calls local LoadAvatar (`0x6e7af0`) with OnAvatarLoaded. It also initializes scene occupables, generic interactables and game-manager values; these sends are not awaited as a response-count barrier.

GetPresetGame (`0x622740`) must return a valid preset, table catalog and LastPos. CreateGhost (`0x5f63e0`) applies LastPos for both local and remote avatars. The assembly coroutine (`0x6033e0`) finishes assets, calls PostInstantiateAssets and End, removes the queue/loading flags and invokes OnAvatarLoaded(GUID). Exact avatar field/asset contracts are in the companion avatar reports; file presence alone does not prove the instantiated avatar will complete.

OnConnected.OnAvatarLoaded (`0x5dfdc0`) sets animation, enables NetworkTransform, applies companion/locomotion, fires GetAllInWardrobe asynchronously, removes any prior local player, initializes control/RandomIdle and sends the saved C2S1 announcement. It then starts MoveAvatarDelay (`0x5ea260`), which applies a serialized local spawn point and yields one frame. On resume it hides SpinCircle, hides ScreenLoader and clears isChatMenuLocked. See [spawn evidence](tcp-world-spawn.json) for the six nonzero Nexus spawn transforms and ordering.

There is **no aggregate roster/occupancy/state reply-count gate** on this closure path. Such handlers are still needed for correct world behavior; uncaught errors from them can still disrupt loading. GetAllInWardrobe is not awaited, but nonempty results expose the documented final-null bug: it needs the [copied-client patch](tcp-wardrobe-patch.json) plus PlayerLabelJson records. The original empty `OK#` path suppresses this callback.

## Concrete dependencies before testing

- Preserve exact bootstrap identity/session/task callbacks, including user-online success and the initial Login allocation sentinel.
- Return a reachable instance IP/port and a real local scene key; do not confuse scene and instance IDs.
- Match Mirror prefab component order/spawn payload and send application0 after local spawn.
- Satisfy exact PlayerLabelInfo/GetPresetGame/avatar item contracts and local avatar completion; implement wardrobe records with the documented copied-client fix.
- Keep local required bundles and embedded UI/resources available. All11 bounded roots exist; complete avatar/housing coverage and engine deserialization remain outside this file-presence check.
- Restore nonminigame world/remote presence handlers for their recovered semantics even though they do not collectively gate ScreenLoader.Hide.

This audit finds no additional required load-balancer socket service, remote manifest endpoint or loader patch for the modern Nexus chain. It does not establish end-to-end success or original-server equivalence, and it authorizes no runtime test.
'''
(OUT/'world-loading-pipeline.md').write_text(md,encoding='utf-8')
print(json.dumps(dict(report=str(OUT/'world-loading-pipeline.md'), indexed_methods=len(evidence),
                      missing_pseudocode=[x['rva'] for x in evidence if not x['exists']])))

