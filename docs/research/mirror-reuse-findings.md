> Historical research: this file records an earlier investigation, not current feature acceptance. The root [PROGRESS report](../PROGRESS.md) is authoritative. Local evidence and extracted game code are intentionally omitted. See [research index](README.md).

# Reusing the shipped Mirror implementation

**The client retains real Mirror host/server entry points. It does not retain an identified application server handler for `NebulaMessage`.** Activating generic Mirror hosting is therefore a useful experiment, but it cannot be equated with bringing the whole game online.

Evidence is static metadata and bounded disassembly from build 11018722, GameAssembly SHA-256 `c4dd5db599e5e5ce4adf25f09ffe70ad10e0928adf6a2e862176d537026b44ac`. No host/server activation was executed by this sub-investigation.

## Surviving APIs

| Method | Native VA |
|---|---|
| `Mirror.NetworkManager.get_singleton` | `0x18129B660` |
| `NetworkManager.StartHost` | `0x18129A6F0` |
| `NetworkManager.StartServer` | `0x18129A840` |
| `NetworkManager.SetupServer` | `0x181299C20` |
| `NetworkManager.FinishStartHost` | `0x181296EC0` |
| `NetworkManager.StartHostClient` | `0x18129A440` |
| `NetworkManager.RegisterServerMessages` | `0x181298F10` |
| `NetworkManager.OnServerAddPlayerInternal` | `0x181298030` |
| `NetworkManager.OnServerAddPlayer` | `0x1812981F0` |
| `Mirror.NetworkServer.Listen` | `0x1812A22B0` |
| `NetworkServer.AddPlayerForConnection` overload | `0x1812A05B0` |
| `NetworkServer.SetClientReady` | `0x1812A5710` |
| `Mirror.NetworkConnection.Send<NebulaMessage>` | `0x180885CD0` |
| `Mirror.NetworkClient.Send<NebulaMessage>` | `0x1808843F0` |
| `Mirror.NetworkClient.RegisterHandler<NebulaMessage>` | `0x180882A50` |
| `Mirror.NetworkMessageDelegate..ctor` | `0x1812D6210` |

`StartHost` and `StartServer` have nontrivial native instruction bodies in retained slices `NEB-STATIC-129A6F0` and `NEB-STATIC-129A840`. Presence establishes that entry-point code survived IL2CPP stripping; it does not establish that invoking it in the boot scene will work.

`NetworkManager` retains `transport`, `playerPrefab`, `spawnPrefabs`, `authenticator`, `onlineScene`, `offlineScene`, `autoCreatePlayer`, `networkAddress` and related configuration. The selected scene's configured transport, prefab and initialization state still have to be inspected at runtime or in serialized assets before activation.

`NetworkServer.handlers` is declared as `Dictionary<ushort, NetworkMessageDelegate>` with managed static-field offset `0x18`. The dictionary may offer a direct registration path from instrumentation. That offset is relative to IL2CPP class static-field storage, not the module base. The delegate's invocation signature is `(NetworkConnection conn, NetworkReader reader, int channelId)`; its native instance method additionally receives the delegate object and MethodInfo arguments. A plugin must respect IL2CPP lifetime/ABI rules.

The complete `ScriptMethod` inventory includes server `RegisterHandler<T>` instantiations for `ReadyMessage`, `AddPlayerMessage`, `CommandMessage`, ping, matchmaking and demo authenticators. It has **no `NetworkServer.RegisterHandler<NebulaMessage>` instantiation**. Shared generic code or direct dictionary registration may still be usable; absence of a named native instantiation is not proof of runtime impossibility.

## Game-specific gaps

The complete `ManagerInstance : NetworkManager` declaration overrides `Awake`, `OnClientConnect` and `OnClientDisconnect`, and declares app TCP setup functions. It declares no `OnServerConnect`, `OnServerAddPlayer`, `OnStartServer` or `OnStartHost` override. Those hooks fall back to the inherited Mirror behavior unless other code installs handlers. No game server implementation was identified from these declarations.

`NebulaPlayerSyncVars` retains a generated `SetSpeed` command, its registration and SyncVar serialization. Its `.cctor` at `0x180614850` calls `RemoteProcedureCalls.RegisterCommand` with the full signature literal and an authority-required value of true. Evidence: `NEB-STATIC-614850`. Its `UserCode_SetSpeed__Single` method points at the shared native `ret 0` stub at `0x18035A740`, so this generated command's shipped user body does no work. That does not establish how custom `TypeTCP.Transform` messages are handled.

Application work still needed around a Mirror host includes the custom message handler, initial player/session data, room membership, chat, avatar/profile state, transforms, bootstrap HTTP responses and space selection. Reusing the existing Mirror runtime can avoid reimplementing batching, transport, spawning and serializers if the required scene configuration survives.

## Compatibility fingerprint

The exact Mirror version is **unresolved**. No version constant was found in the inspected declarations. Several features identify an older API family:

- `Mirror.MessagePacking.HeaderSize=2`, `GetId<T>`, and `Pack<T>`.
- `SpawnMessage.assetId` is `System.Guid`.
- `NetworkManager` has `serverTickRate`, `autoStartServerBuild`, old compatibility overloads, and an additional `OnClientDisconnect2` method.
- `Batcher.HeaderSize=8`; `Unbatcher` stores a remote timestamp.
- The KCP transport includes the older `NonAlloc` toggle and transport configuration fields.

A primary upstream snapshot dated 2022-06-16, commit `880a4eebd633c6e3a5d999aa3c315320a6f708cd`, matches the inspected MessagePacking and basic message field shapes. This is a **comparison candidate**, not an identified exact release. The additional local `OnClientDisconnect2` is absent in that upstream NetworkManager source, so local modifications are plausible.

Current upstream `SpawnMessage.assetId` is a `uint`, which differs from the shipped client's `Guid`. A current Mirror server cannot be assumed wire-compatible merely because it uses Mirror. Reusing the shipped native runtime gives the strongest starting compatibility; an external Unity/C# server should first pin and compare the historical API/serializer version. A Rust server would need to reproduce these wire details explicitly.

Primary references:

- [Historical MessagePacking](README.md#omitted-local-evidence)
- [Historical message structures](README.md#omitted-local-evidence)
- [Historical NetworkManager](README.md#omitted-local-evidence)
- [Current message structures, mutable branch reference](README.md#omitted-local-evidence)
- [Official Mirror NetworkManager callback template](README.md#omitted-local-evidence)
- [Official custom message registration example](README.md#omitted-local-evidence)
