> Historical research: this file records an earlier investigation, not current feature acceptance. The root [PROGRESS report](../PROGRESS.md) is authoritative. Local evidence and extracted game code are intentionally omitted. See [research index](README.md).

# Static world-loading pipeline

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

The 30-second realtime watchdog (`0x444150`, bounded assembly in [native evidence](README.md#omitted-local-evidence)) checks transport connectivity only. Failure closes the client and repeats allocation with the current scene/instance and `isSpaceToLoad=false`. An already connected transport with a stalled avatar does not trigger this recovery.

## Load-balancer code is legacy evidence

`loadbalancerConn` supplies three constants: development104.196.161.5 (`0x12499a0`), production104.196.60.146 (`0x12499d0`), port28000 (`0x1249a00`). The executable-section E8/E9 candidate scan finds the production getter at `0x42ab8c` in PS4Info.Init; this assigns ipLoadBalancer. It finds no direct calls to the other two getters. The legacy MANAGER_MSGS.LOADBALANCER DTO types have zero ScriptMetadata TypeInfo references.

The traced HTTP JoinSpace does not invoke those getters, a SpaceLoaderBalancer or the older NETGcloudLogin.JoinSpace/SpaceLoaderManager.JoinSpace path. The Nexus scene has an active SpacePREFAB and no SpaceLoaderManager/SpaceLoaderBalancer component among its nine resolved MonoBehaviour headers. The selected SpacePREFAB full typetree parses without errors; this is not a full-field audit of the other eight components. Thus a separate load-balancer service is not a demonstrated dependency here. The [xref artifact](README.md#omitted-local-evidence) explicitly does not cover virtual/indirect/inlined/reflection calls.

## Local scene and asset loading

Booter.Start (`0x68b170`) initializes the modern NebulaAssetBundleManager, starts the independent music initializer and initializes Scenes. Music initializer (`0x641ef0`) awaits local gamemusic, instantiates it, marks it persistent and calls GameMusic.InitGameMusic. Booter.Init (`0x69f440`) awaits nav, then s/nebulaplayer, then loads preinitiload in Single mode. It does not invoke its LoadScreenLoader/LoadPooler helpers. Built-in level0 already contains active ScreenLoader (path46), SpinCircle47, Booter45 and both managers43/44. ScreenLoader.get_Instance (`0x429fd0`) resolves the existing object with FindObjectOfType; it does not load a resource. All14 boot component headers resolve; full typetree parsing failed for12 and those exact errors remain in the asset artifact. Bounded PreInitLOAD.Start assembly (`0x3afd00`) selects PC platform1, updates version from VersionGame, and loads InitLOAD in Single mode.

Scenes.Load (`0x5e9800`) uses `Application.streamingAssetsPath/StandaloneWindows/s/{lowercase scene}` with AssetBundle.LoadFromFileAsync, takes GetAllScenePaths()[0], switches to the main thread and awaits SceneManager.LoadSceneAsync. Single mode first awaits UnloadAll; Additive bypasses it. No URL or remote manifest is used here. Progress display is a local bundle/scene calculation, not server progress.

SpacePREFAB starts the scene initialization chain (`0x46c4d0` -> `0x46f870` -> `0x46c570` -> `0x46fa80`). It awaits `s/{Active}logicprefab` (`0x5e8480`), instantiates it, then awaits `s/{Active}spaceevent` (`0x5e9470`). Logic is required; event is tested for null and optional. It destroys its temporary camera/screen-loader reference and launches ManagerInstance. Nexus's event bundle is absent, which this branch accepts; its scene and logic bundles are present.

NebulaAssetBundleManager.Load (`0x617b10`) uses a local cache and local file existence check. A missing file returns null; it has no HTTP fallback. LoadExtract (`0x617250`) follows the same local mechanism with a named asset. ResourcesLoader.LoadDependenciesBundles (`0x4dc2f0`) loads local skinmaterials, not a generic remote/text-manifest dependency system. ResourcesLoader.Load<object> (`0x8a6c80`) and its async state (`0x9e0060`) use local normalized item folders gated by PS4Info asset flags; the bounded fallback rewrites enye-containing local filenames.

The [asset audit](world-loading-assets.json) hashes all11 selected roots and their text-manifest dependency closure: nav, skinmaterials, gamemusic, screenloader, pooler, s/preinitiload, s/initload, s/login, s/nebulaplayer, s/nexus, s/nexuslogicprefab. None are missing. Nexus declares skinmaterials; its logic declares nav and skinmaterials; the player and pooler declare skinmaterials. These shipped text manifests are inventory evidence, not manifests fetched or parsed by the traced runtime loader.

The embedded `assetbundleserverurl` value `htt[local-path]` belongs to legacy AssetBundles.AssetBundleManager code. The direct-call scan finds no external callers of its Initialize/source-URL setup methods, and modern loader methods do not call it. Its active use is unproven; there is no basis here to create a remote bundle server or patch this loader.

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
