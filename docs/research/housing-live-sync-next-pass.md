> Historical research: this file records an earlier investigation, not current feature acceptance. The root [PROGRESS report](../PROGRESS.md) is authoritative. Local evidence and extracted game code are intentionally omitted. See [research index](README.md).

# Housing live synchronization next pass

The recovered client does not provide live furniture-layout synchronization. HTTP is the durable layout authority, and the “one user” check is a point-in-time gate when someone tries to open the furnishing editor—not a continuous occupancy lock.

`PlayerJoinedProcessor.Process` (`0x5e4660`) creates the remote `PlayerInfo`, adds it to `Memory`, marks the avatar remote, and begins label/avatar loading. `OnAvatarLoaded` (`0x5e42d0`) enables that avatar and requests its locomotion, companion, position, and animation state. Neither calls the housing manager, `DeactivateUIMode`, `Deactivate`, save/reload, or the one-user popup. The deactivation bodies only close UI/input/camera when explicitly called. Therefore a visitor arrival does not interrupt an owner who was already editing.

When furnishing mode is requested, `HousingManager.Initialize` (`0x6c4080`) checks the authored house collider and current remote-player dictionary count. Zero remotes initializes the editor; one or more remotes starts `ShowOnlyOneUserPopUpDelay`. The popup coroutine (`0x6cb280`) only displays the popup briefly and hides it; it does not deactivate an editor, save, reload, kick, or send TCP. This blocks a visitor from beginning edits while the owner is present, but it does not terminate an already active owner editor after a later join.

Every client constructs furnishings from its own `N2HousingReadPreset` HTTP response. `SaveAssetsAtServer` (`0x6c4dc0`) serializes the owner’s local objects and sends the two HTTP parts. It also causes placed generic children to be registered locally, which can change generic interaction IDs. The complete recovered `TypeTCP` enum contains no furniture add/remove/transform/layout message; type 94 synchronizes a generic interaction’s state, not furniture placement. No recovered producer asks an already connected visitor to reload after the HTTP save.

Consequently, a visitor arriving during editing may see the last durable layout rather than the owner’s unsaved state, and an already connected visitor is not proven to refresh after the owner saves. The source-bound preservation rule is to furnish while alone and require visitors to reload or re-enter before claiming the updated layout is visible. Dynamic generic IDs on placed furniture must remain unauthorized across peers unless a shared mapping epoch is explicitly established.

On owner disconnect, `OnRemoteDisconnected` compares the peer GUID to `guidOwner` from the read-preset response and begins the existing kick/wardrobe decision. An ordinary visitor disconnect is removed from `Memory`; no housing refresh or edit-mode transition is recovered. The one-user popup is an edit-attempt response, not a join notification.

No live layout push, editor-occupancy TCP signal, or automatic visitor refresh should be invented.
