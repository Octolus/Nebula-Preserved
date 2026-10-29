> Historical research: this file records an earlier investigation, not current feature acceptance. The root [PROGRESS report](../PROGRESS.md) is authoritative. Local evidence and extracted game code are intentionally omitted. See [research index](README.md).

# ScreenLoader bootstrap audit

## Conclusion

The sole compiled startup scene (Booter.unity / level0) directly serializes one enabled ScreenLoader component on an active root GameObject. Unity loads that scene object graph before MonoBehaviour Start callbacks; ScreenLoader.get_Instance can therefore find the placed component. No runtime prefab instantiation is required to explain first existence.

**Confidence:** high. This is static placement evidence, not a runtime observation.

## Serialized placement

- BuildSettings scene 0: `Assets/Scenes/Boot/Booter.unity`; compiled scene file: `level0`.
- MonoBehaviour path ID `46` resolves through script path ID `1805` to `ScreenLoader` in `Assembly-CSharp.dll`.
- It is enabled: `True`; its GameObject path ID `14` is named `ScreenLoader` and active: `True`.
- RectTransform path ID `38` has parent path ID `0`. It is therefore an active scene root, not merely a detached prefab record.

## Why the preload/resource copies are not the bootstrap proof

The `PreloadData` table has 16 entries, all represented with external file ID 1; it does not reference the local `level0` ScreenLoader component. `resources.assets` separately contains 1 ScreenLoader component record, and a `screenloader` AssetBundle is packaged. Those facts establish available assets, not that either copy is instantiated at startup. The direct `level0` component does.

## Native ordering corroboration

- `ScreenLoader.get_Instance` (`0x429fd0`) reads the static cache and calls `FindObjectOfType<ScreenLoader>`: `True`. An Instantiate call is present: `False`.
- `Booter.Start` (`0x68b170`) initializes the asset-bundle manager and Scenes, then starts Init.
- `Booter.<Init>d__5.MoveNext` (`0x69f440`) loads nav, NebulaPlayer, and `preinitiload`.
- Either reviewed Booter function mentions ScreenLoader: `False`.
- A separate `Booter.<LoadScreenLoader>d__6.MoveNext` (`0x69fde0`) does call the Scenes loader, instantiate the returned GameObject, and mark it `DontDestroyOnLoad`: `True`.
- Its Scenes state machine (`0x5e9110`) requests the `screenloader` bundle: `True`. No call/start of this separate loader appears in the reviewed `Booter.Start` or `Booter.Init` bodies.

The lifecycle step that the artifacts do not encode as an ordinary call is Unity's scene deserialization before `Start`. That engine lifecycle rule plus the active root component is the bounded inference connecting the serialized observation to availability during `Booter.Start`.

## Evidence boundaries

Observed:

- BuildSettings contains exactly one scene: Assets/Scenes/Boot/Booter.unity.
- level0 contains exactly one ScreenLoader MonoBehaviour candidate.
- That component is enabled and attached to an active GameObject named ScreenLoader.
- Its RectTransform has a null parent reference, making the GameObject a scene root.
- The component's MonoScript resolves to ScreenLoader in Assembly-CSharp.dll.
- ScreenLoader.get_Instance checks its static cache, then calls FindObjectOfType<ScreenLoader>; no Instantiate call appears.
- Booter.Start initializes local managers and starts Init; Init loads nav, NebulaPlayer, then preinitiload. Neither reviewed function mentions ScreenLoader.
- Separate compiled LoadScreenLoader state machines request the screenloader bundle, instantiate the returned GameObject, and mark it DontDestroyOnLoad.
- The reviewed Booter.Start/Init path does not call or start that separate LoadScreenLoader state machine.

Inferred:

- Unity deserializes the initial scene object graph before invoking Start callbacks, so the placed active component exists when Booter.Start runs.
- The resources.assets and bundle copies are not needed to explain the first instance and must not be treated as proof of dynamic instantiation.
- The separate bundle loader may be a later, alternate, or obsolete path; its mere presence does not establish that it runs during initial startup.

Still unknown:

- No runtime observation confirms whether later scene transitions destroy, retain, or replace this initial ScreenLoader.
- This audit does not establish when or whether the separate screenloader bundle loader is invoked outside the reviewed Booter.Start/Init path.
- Static placement proves the intended initial host, not successful rendering or execution on this machine.

## Source identities

- `[local-path] Realms\Nebula Realms_Data\globalgamemanagers`: `ecdebe7c899776956a4d5fb801f37f04128ec9bef72e744cd1e7fd5349ce8466` (1131320 bytes)
- `[local-path] Realms\Nebula Realms_Data\globalgamemanagers.assets`: `4600d3bef0d3e503bbf028c6b203bb7ca80e5f48711bfef4c523ff905ab4e299` (344828 bytes)
- `[local-path] Realms\Nebula Realms_Data\level0`: `95e80ae6c2658c6da0c9269e9e6a54ecf8d6b43c4cd28e091957521235fe1e0c` (9824 bytes)
- `[local-path] Realms\Nebula Realms_Data\resources.assets`: `adf9fcbca4f1b6910ab2a4d6260196cdb378f19c20dc616d1fd97c3b9b06eb1b` (135412392 bytes)
- `[local-path] Realms\GameAssembly.dll`: `c4dd5db599e5e5ce4adf25f09ffe70ad10e0928adf6a2e862176d537026b44ac` (42310144 bytes)
- `[local-path]` (ScreenLoader.get_Instance 0x429fd0): `cfebed2575816b2e44418dc0898b8ff97e005a49f3994e35c6d66f86b054b821` (1306 bytes)
- `[local-path]` (Booter.Start 0x68b170): `7085af18b639a00a9565be4fe371b553bb74ea26d1fe385625b443bbb3427301` (3415 bytes)
- `[local-path]` (Booter.<Init>d__5.MoveNext 0x69f440): `22e8677e6310a884e202aa5b455816149f2fa4858214d076850a00a3588e43e3` (8772 bytes)
- `[local-path]` (Booter.<LoadScreenLoader>d__6.MoveNext 0x69fde0): `7bcdfa8e2dd0d78c9f3634055f80cceb44a2a9b786225da7db982eecfc2f97ed` (4862 bytes)
- `[local-path]` (Scenes.<LoadScreenLoader>d__16.MoveNext 0x5e9110): `21262f4186298d2405c8cd9a021e88d840ed3b9c02b9db110eb9a8bff64f00da` (5945 bytes)

The audit was execution-free: no game process, UI automation, listener, server, or network connection was used.
