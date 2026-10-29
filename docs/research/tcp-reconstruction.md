> Historical research: this file records an earlier investigation, not current feature acceptance. The root [PROGRESS report](../PROGRESS.md) is authoritative. Local evidence and extracted game code are intentionally omitted. See [research index](README.md).

# Modern TCP reconstruction: static evidence and state ordering

The modern `TCPs.TCPClient` is a Mirror message bridge, not an independent raw-socket protocol. Its dispatch framing, AES encoding, initial avatar sequence, and core chat/player/world fields are recovered from native bodies. These findings do **not** establish a complete 1:1 replacement server. No game, listener, connection test, packet simulation, or protocol execution test was run for this reconstruction.

The typed contract is in [tcp-contracts.json](tcp-contracts.json), with a readable field table in [tcp-contracts.md](tcp-contracts.md). [tcp-dispatch-map.json](tcp-dispatch-map.json) records all 80 exact client receive registrations. This audit covers 46 receive contracts and 38 send contracts; the independent [minigame audit](minigame-contracts.md) covers the remaining 34 receive contracts plus 19 send contracts. Each contract identifies native RVAs; the JSON hashes the reviewed Ghidra files. Evidence binary `work/evidence/GameAssembly.dll` has SHA256 `c4dd5db599e5e5ce4adf25f09ffe70ad10e0928adf6a2e862176d537026b44ac`, preferred image base `0x180000000`. RVAs are relative to this image, not file offsets. IL2CPP dump declarations provide names/types; Ghidra output is native pseudocode, not the original C#.

## Wire layers

Observed send chain at `TCPClient.Send` RVA`0x5e7820`:

1. Caller constructs a plaintext command with decimal opcode and `#` separated fields.
2. `AES.Encrypt` appends `#` and the **enum name** of local platform: `StandaloneWindows` or `PS4` (`0x6a32c0`). This occurs even when the caller has already included a numeric platform field.
3. UTF8 encodes that complete string, AES128 ECB encrypts with PKCS7 padding, and standard Base64 encodes the ciphertext.
4. `Mirror.NetworkClient.Send<NebulaMessage>(new NebulaMessage { data = ciphertext }, channelId:0)` transports the result.

`AES` constructor `0x6a35a0` hashes UTF8 bytes of literal `[cipher-material-omitted]` with SHA1, copies the first16 bytes as the key, then sets Mode2=ECB and Padding2=PKCS7. The derived key is `f794fdd76962dfc07ba2efa75c7cf887`. This key is a hardcoded shipped-client protocol constant, not a recovered user credential. ECB has no per-message IV in this path. Native calls are identified by SymmetricAlgorithm virtual slots from dump.cs declarations, rather than interpreting the numeric2 without context.

Observed receive chain at `TCPClient.OnNebulaMessage` `0x5e7690`:

1. Checks `Mirror.NetworkClient.active`.
2. `AES.Decrypt(message.data)` (`0x6a2f80`) checks structural Base64 eligibility, decodes, AES decrypts, and UTF8 decodes. It returns null on invalid input/decryption exception. `IsBase64` `0x6a34d0` requires a nonempty length divisible by4 and rejects ASCII space/tab/CR/LF; actual alphabet validation occurs in `Convert.FromBase64String`.
3. Splits plaintext on character`0x23` (`#`) using StringSplitOptions.None, preserving empty tokens. The receive path does not strip a platform suffix.
4. Enqueues `string[]` in `ProcessorQueue.processQueue`.
5. Queue update drains the count present at update start (`0x5e5010`, `0x5e54c0`). For each entry, parses token0 with `Int32.Parse`, finds its registered handler, copies tokens1..end, and calls `TCPProcessor.Process` (`0x5e5240`, equivalent code in ProcessTasks).

No application length prefix or escaping appears inside the decrypted command. TCP segment boundaries and Mirror/Telepathy length/batch framing are a separate layer. Trailing empty fields matter: removing locomotion sends `15#guid#`; encryption produces `15#guid##StandaloneWindows`. A generic split that drops empty strings will change the command.

Malformed numeric, Boolean, count, and undersized field inputs generally reach parse/bounds exceptions. Unknown numeric opcodes are logged and ignored. These are observations about this client, not a recommendation to reproduce unsafe server input handling.

## Local and remote player sequence

This is the client-side dependency order observed in bodies, not a claim about the retired server's unshipped scheduling or recipient policy:

[Code/listing block omitted from the public research archive.]

`OnConnectedProcessor.Process` `0x5e0570` ignores incoming fields and enters its async body `0x5ea6e0`. That body constructs, but does not immediately send, `1#<NetworkClient.localPlayer.netId>#<PS4Info.SessionGUID>#<PS4Info.userName>#<numericPlatform>`. It waits for Memory's pending local player, clears that pending reference, removes wardrobe checker, initializes interaction UI, and requests label/avatar. It also initializes space occupables, generic interactables, and game managers. These may send their own requests before the stored opcode1 announcement; server readiness cannot depend exclusively on opcode1 arriving before every scene-state request.

`OnConnectedProcessor.OnAvatarLoaded` `0x5dfdc0` configures animator, enables control, restores companion and locomotion from persistency, requests wardrobe occupants, removes wardrobe ghost, initializes random idle, then sends stored opcode1. The callback starts a later avatar movement path as well; its full timing/body must be joined with the separate spawn/space investigation.

`PlayerJoinedProcessor.ProcessDelay` `0x5e43c0` expects `[uint netId,guid,username,int platform]`. It does not create a player object. It takes `Memory.remotesToBuild[netId]`, removes the pending entry, sets identity/guid, creates PlayerInfo, registers the remote, then loads label/avatar. `OnAvatarLoaded` `0x5e42d0` enables remote components and sends locomotion16, companion6, position20, and animation3 queries in that order. It also initializes random idle and removes a matching wardrobe ghost.

Consequences for server construction:

- A plain opcode0 response can satisfy that handler's payload read, but cannot replace Mirror ready/add-player/spawn and state synchronization.
- Remote Mirror Spawn must precede application PlayerJoined for the same netId. The pending dictionary lookup is not optional.
- Player announcements and state queries use different identifiers: Mirror netId for transform/spawn; session/player guid for avatar/animation/companion/chat.
- The client code establishes request/response *constraints*. It does not prove the retired server's caching, acknowledgement, timeout, recipient selection, reconnect, or authority policies.

## Movement, avatars, wardrobe, inventory

`NebulaPlayerTransform.SendData` `0x615000` sends `2#<local Mirror netId>#<JsonUtility.ToJson(TransformData)>`; constructor `0x6156b0` sets opcode2. TransformData declares `position:Vector3` and `rotation:Quaternion` (`dump.cs:72363`). SendData checks squared change from previous position before sending, so rotation-only updates need separate assessment of Mirror NetworkTransform and animation/SyncVar paths. Receiver `0x5e7ed0` parses netId as Int32, resolves player, and assigns the deserialized position and rotation directly. Thus the server also needs the Mirror entity stream; this application command alone is insufficient to account for all movement behavior.

Remote visual assembly remains HTTP driven: PlayerJoined calls `LoadAvatar(guid)`, whose data/resource contracts belong to the avatar/HTTP reconstruction. Companion17 and locomotion15 carry guid plus resource/name string; an empty string removes the selection. They are not complete inventory lists. Wardrobe29 carries guid only, with remote ghost/deactivation and local CharacterEditor transition; it does not read an in/out Boolean. Inventory purchases, equipped items and avatar meshes must be restored from the HTTP/persistency/resource path, not fabricated as extra TCP fields.

Animation change C2S opcode4 includes guid, the source-observed signed `-1` sentinel (metadata calls it `netId`, but every recovered caller passes `-1`), animation type, cycle type, animation name, count, and names. S2C opcode5 omits the sentinel. EnumTypeAnim0..7 and TypeCycle0..2 are exported in the JSON. Parameter92 carries guid, parameter name, AnimatorControllerParameterType and value. Layer93 receives an integer weight converted to float; native MOVD/CVTDQ2PS at `0x5ec49b`/`0x5ec4a2` confirms this despite a missing floating argument in Ghidra pseudocode.

Preference18 is sent after a successful HTTP save for only mood0/status1/color15/platformOnly21 in `HTTPSavePlayerPref.OnResponse` `0x6399f0`. The receive body also supports label-display keys2/3/4; Boolean values in that body are the literal string`1`. Color15 is Unity JSON of `{x:float,y:float,z:float}` (`PlayerPrefsManager.ColorData`, dump.cs23333). Unknown other preference keys are ignored by this receiver.

## Chat and social fields

Chat C2S and S2C opcode13 both have `[guid,groupName,platform,message,chatType]`, then client sends add the platform-name suffix. The platform payload is supplied from the active ChatTab, while suffix platform is the sender's local platform. Those must not be conflated. `ChatType.Space=0`, `SocialInternal=1`.

`Chat.SendMessage` `0x4640c0` strips literal `<`, `>`, and `#` to empty and removes repeated consecutive ASCII spaces, keeping the first. The resolved string globals are `0x24f1980='<',0x24fa948='>',0x252c658='#',0x251f580=''`. No CR/LF sanitizer appears in this method. It does not use CustomEncrypt. PC `OnMessageWritten` `0x463310` and PS4 dialog result `0x4625b0` send stop-typing12 with guid before chat. Start-typing11 carries guid and active group; Notifications tab excluded (`0x5f0320`).

Receiver13 `0x5d7790` applies presence/relationship/platform checks for type0. Nonzero type uses the delivery path without those normal space-chat checks. `SendMessage` `0x5d7a70` fills pooled ChatMessageData and calls Chat.OnMessageReceived for nonempty group. Downstream tab/profanity/name lookup behavior remains a separate client display path and must be reviewed before claiming identical social UX.

Notification19 is asymmetric. Reviewed C2S request constructors carry `[senderUsername,targetUsername,notificationType,targetPlatform]` (private-chat0/friend1/invite6), whereas S2C receiver expects `[playerName,platform,type,arguments,ticks]`, with ticks parsed as Int64. [Notification and consumable details](tcp-social-consumables.md) record acceptance26/decline95 variants, invite-to-join's HTTP/GCloud branch, full-game scene handoff and the platform-omitting RemoveFriend21 branch. RemoveFriend21/RemoveSilenced22/AddSilenced23 share the same receive body: username plus numeric platform, guid lookup, SetRemoteRelation(false). RelationshipUpdated28 takes guid plus relation enum. HTTP social persistence and original server notification policy remain separate gaps.

## World interaction asymmetries

- Occupable9 sends `[guid,occupableId]`, receives `[requesterGuid,occupableId,occupantGuid]`. Empty occupant is ignored. Matching requester/occupant invokes local SetOccupable; otherwise it updates a target interactable. Server must arbitrate seat state and choose recipients, rather than echo two fields.
- GetOccupable8 sends requester guid and id during each scene occupable initialization. Leave10 sends guid/id, but receiver ignores token0 and clears id's occupant.
- DayNight30 sends one Boolean string; receiver ignores token0 and parses Boolean token1, then calls StartCycle with its inverse. `Boolean.Parse` means `True`/`False`, not `0`/`1`.
- Boat31 receives guid, Boolean allowed, integer token; a successful result assigns a boat token and starts delayed instantiate/seat paths.
- GenericInteractable94 sends guid, id, inverse current Boolean state, then any extension strings. Receiver dispatches the full token array to a matching subtype on state change. Subtype extension schemas still need tracing.
- ToJoinNotification27 checks only payload length: fewer than3 means full/failure; at least3 starts a fresh HTTPSpaceLoading request. Values are unread. Its length gate is sensitive to an extra appended suffix.
- InstanceClosing96 ignores token0, compares token1 with current instance id and redirects to Nexus on match. This is not a generic disconnect notification.

## CustomEncrypt is a separate reversible permutation

`TCPProcessor` constructor allocates `CRYPTManager.EncryptDecryptNaeFiles`, but the modern TCP send/receive bodies call AES. No direct E8 caller of CustomEncrypt/CustomDecrypt was found in the executable-section candidate scan; that is not proof of global non-use or absence of inlining.

`CustomEncrypt` `0x5d7f90` copies UTF16 char bytes into an even-length byte array using BlockCopy, runs EncryptBytesAsset, then copies bytes back to UTF16 chars. `CustomDecrypt` `0x5d7e90` reverses it. This is not UTF8, Base64 or AES.

Let `P` swap every adjacent byte pair: `[a,b,c,d] -> [b,a,d,c]`. `InverseBytes` `0x5d9010` is this operation, not a full array reversal. Let `S(k)` swap byte ranges `[0,k)` and `[k,2k)` in place, preserving the tail. `ReplaceBlockBytes` `0x5d90d0` uses its `end` argument as k and does not use `init`.

For n bytes, encryption `0x5d8800` is initial P, then7 iterations of:

[Code/listing block omitted from the public research archive.]

Decryption `0x5d8090` does7 iterations of the reverse list, then final P:

[Code/listing block omitted from the public research archive.]

The permutation algorithm was read from bodies; no codec roundtrip or execution test was performed. UTF16 strings may contain surrogate code units, so a future implementation must preserve code units rather than normalize Unicode. Odd arbitrary byte arrays would violate P's pair access; the string wrappers produce even lengths.

## Bowling and consumables

[Bowling contracts](tcp-bowling.md) describe the nested EntryData panel, ready/start/leave sequence, shot acknowledgement variants, pin transforms and two shipped synchronization inconsistencies. Pin float strings use raw low/high16-bit UTF16 code units from a float32, not decimal or Base64. Its recovery path mixes modern cached action numbers with an older switch and reads the cached lane id from a different field; these remain explicit compatibility gaps.

Coffee44/45 and OktoberFest46/47 have distinct receive layouts. The transitive managers instantiate or refill an avatar consumable prop, with local drink/help UI. These packets are not complete account inventory updates. [The consumable report](tcp-social-consumables.md) traces their HTTP-before-TCP send sequence and existing-prop refill behavior.

## Remaining reconstruction boundary

The client contains 97 TypeTCP enum values and 80 registrations. The dispatch map is exact. Field-consumption contracts for all 80 are now covered across this audit and the independent minigame audit; that is not proof of restored server behavior. No retired server executable/source/state was supplied, so even complete client field recovery cannot prove identical server policy. Required remaining work includes authoritative minigame rules, notification persistence, object-specific extension commands, HTTP/session/space/avatar/inventory dependencies and the full Mirror spawn/authority/SyncVar/command stream. The current evidence supports implementation design but does not support announcing a 1:1 online restoration or starting a client test under the user's constraint.
