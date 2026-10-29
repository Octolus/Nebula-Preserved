> Historical research: this file records an earlier investigation, not current feature acceptance. The root [PROGRESS report](../PROGRESS.md) is authoritative. Local evidence and extracted game code are intentionally omitted. See [research index](README.md).

# Notification and consumable protocol notes

These are static client contracts. No game, listener, connection, packet simulation or protocol execution was run. The typed fields and Ghidra hashes are in `tcp-contracts.json`; additional bounded assembly is in `tcp-notification-consumable-native.json`.

## Notification packet directions differ

Reviewed C2S19 constructors use `senderUsername # targetUsername # notificationType # targetPlatform`. These cover private chat0, friend1 and invite6 (`0x6e8f80`, `0x4c6a60`). S2C19 instead requires `playerName # platform # type # arguments # ticks` (`0x5df8a0`). The receiver constructs NotificationData and pushes it; ticks is Int64, and restricted chat suppresses type0. It cannot receive a raw request echo.

Notification types are Chat0, Friend1, FullGame2, Gift3, Reward4, Friend_Accepted5, InviteToJoin6, AskToJoin7, AceptedToJoin8, NewInstanceIsCreated9, FullGame_Declined10, SpaceGame11, SpaceGame_Declined12 and SocialToJoin13. The unusual spelling `AceptedToJoin` is the shipped enum name.

AcceptNotification (`0x47e050`) has distinct paths:

- SpaceGame11 sends C2S26 `guid # notification.playerName # 11`, omitting notification.platform.
- The ordinary TCP26 branch includes `guid # notification.playerName # notification.type # notification.platform`.
- InviteToJoin6 resolves PSID/global guid through HTTPGetPsidglobalAndGuidByUsernamePlatform. Callback `0x488fe0` rejects empty resolved psidglobal with CannotConnectIsNotInSpace and clears pad input lock. Otherwise it shows Searching Server and calls `NETGcloudLogin.LoadSpace(psidglobal, "", true, guid, null)` (`0x3d5a40`). It does not send26.
- FullGame2 calls ManagerInstance.Send_AcceptFullGameNotification (`0x439ad0`). It finds the first `!` in notification.arguments, passes the prefix through that delimiter to EntryData.Deserialize and uses the suffix to instantiate an OpenGameEntry subtype. A disconnect callback (`0x4499b0`) selects the full-game scene by enum name and loads it if absent. Coroutine `0x449250` then waits for its predicate, resets the full-game UI and calls FullGameManager.LaunchMultiScene(openGame). No modern TCP26 send occurs in these reviewed continuations. FullGame/GCloud networking after LaunchMultiScene remains a separate dependency.

DismissNotification (`0x47fa70`) and DeclineAll (`0x47f160`) send C2S95 only for incoming FullGame2 or SpaceGame11: `guid # notification.playerName # notification.platform # declineType`, where declineType is FullGame_Declined10 or SpaceGame_Declined12. The type/platform order is different from ordinary acceptance26. Neither26 nor95 has a client receive registration.

## Social relation operations

Standard C2S21/22/23/24/25 callbacks use `guid # targetUsername # targetPlatform`. One removal branch in SocialOptionsSpaceUsers.OnAddFriend (`0x4c9530`) sends21 with only `guid # targetUsername`; platform is omitted even though the global AES platform-name suffix remains. Preserve this source variant.

S2C21/22/23 instead read `username # platform`, resolve guid and call SetRemoteRelation(false); their native handler is shared (`0x5d6db0`). S2C24/25 use the same two fields and refresh relation/avatar visibility. S2C28 takes `guid # relationType`. The account friendship/block lists and persistence require the HTTP/social audit in addition to these online refresh messages.

## Coffee and OktoberFest

The UI first completes its HTTP callback and checks returned guid, item tag and success (`0x4190b0`, `0x419ba0`). On success it sends C2S44 `guid # coffee # HTTP-field6` or C2S46 `guid # oktoberfest # HTTP-field6`. HTTP-field7 separately updates an integer UI count; no claim is made that the copied field6 equals an account inventory balance.

Receive layouts after opcode removal are:

| Opcode | Fields | Consumer |
|---|---|---|
| 44 and45 | guid, unread token1, literal coffee, Int32 count | FoodTruckManager.Set |
| 46 | guid, unread token1, literal oktoberfest, Int32 count | OktoberFestManager.Set |
| 47 | guid, literal oktoberfest, Int32 count | OktoberFestManager.Set |

The normal46 and OneWay47 layouts differ by one token. Receiver field indices are proven in bodies (`0x5dbcc0`, `0x5dbc00`, `0x5dbfb0`, `0x5dbef0`).

FoodTruckManager.Set (`0x404da0`) and OktoberFestManager.Set (`0x4087f0`) resolve the player by guid. A missing player returns. They find the existing `PlayerCoffee(Clone)` or `PlayerOktoberFest(Clone)` child. If absent, they instantiate the configured prefab under the player and initialize it with the received integer and player object. If present, they set the consumable's current-times field0x18 to its maximum-times field0x1c; that refill branch ignores the newly received count. Local players also receive the drink/help UI. These packets create/refill visible consumable props; account inventory/ownership cannot be inferred from them alone.

Original server authorization, recipient selection, timestamps, acceptance matching, notification persistence and rate limits remain unshipped server policy. The recovered client schemas constrain a compatible implementation but do not establish identical policy.
