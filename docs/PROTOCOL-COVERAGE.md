# Protocol coverage

Snapshot 2026-10-30. This matrix compares every networking contract the shipped
Windows client (Steam app 919290, build 11018722, GameAssembly SHA-256
`c4dd5db5…44ac`) uses with what this repository serves. It covers the HTTP
servlets and the scene-server connection (TypeTCP application opcodes carried in
the Mirror `NebulaMessage`, plus Mirror-level messages, Commands, RPCs and
SyncVars). [PROGRESS](PROGRESS.md) remains authoritative for runtime acceptance.

**Method.** Client ground truth is the il2cpp dump, the recovered command
literals and the Ghidra pseudocode of each parser/sender, plus targeted
disassembly where no pseudocode existed. The recovered contracts in
`protocol/bootstrap-response-contracts.json` and `docs/research/*` were
re-checked against the current handlers field by field: field order and count,
delimiters, the exact success literal, empty-list and trailer rules, and what the
client actually reads. Live evidence came from read-only inspection of the
deployed server's `requests.jsonl`, the persistent diagnostic files and the
per-instance logs (two real players, 2026-10-29 21:22 to 2026-10-30 20:59 UTC).
Nothing was deployed, and no game was launched.

**Status values**

| Status | Meaning |
|---|---|
| implemented-correct | Wire shape matches what the client parses and the behavior the client depends on. Where the original server rule is unknowable, the documented local preservation policy applies; it is noted, not claimed as parity. |
| implemented-divergent | Implemented, but some client-observable behavior differs from what the client expects. |
| stub | Returns a valid "nothing available" reply only. |
| missing | Client uses it; the server does not provide it. |
| minigame-deferred | Belongs to a minigame or full-game flow and is deliberately out of current scope. |
| unused-enum | Scene-server enum value that the client neither sends nor handles. |

## Summary

| Surface | Total | Correct | Divergent | Stub | Missing | Minigame-deferred | Unused |
|---|---:|---:|---:|---:|---:|---:|---:|
| HTTP servlets | 122 | 112 | 0 | 8 | 2 | 0 | — |
| TypeTCP opcodes (0–96) | 97 | 81 | 4 | 0 | 2 | 1 | 9 |
| Mirror-level elements | 17 | 17 | 0 | 0 | 0 | 0 | — |

The HTTP count is the 121 concrete route literals recovered earlier
(`docs/research/nonmini-surface-status.md`) plus `AddXPServlet`. A fresh scan of
the client's string literals found that one extra: `XPNET.Send_AddXP`
(0x44a1f0) sends it with a minigame type; it is now implemented with the HTTP
minigame routes (see the minigame plan). All other
`*Servlet`, `N2*`, `STM*`, `Get_*`, `Send_*` and `NPShop*` literals are already
in the union or are error-callback names.

The two HTTP "missing" rows are retired Steam commerce (`STMBuyCrystals`,
`STMCompleteOrder`), deliberately disabled. `N2LoadSpace`, the earlier
divergent row, is source-fixed for all 11 remaining public worlds (gap 7). It
requires the rebuilt scene runtime. Every other non-minigame servlet matched
its recovered client parser in this pass. The 13 HTTP-only minigame
routes (Archery, Boat, FootRace, XP, Archery Cupid, SKL goal and
`checkRewardGameServlet`) were implemented in a later pass (2026-10-31) from
freshly recovered sender and parser contracts; see
[minigame-contracts.md](research/minigame-contracts.md#http-minigame-servlets-2026-10-31).

## Fixed in this pass

| Gap | Fix | Test |
|---|---|---|
| Large native requests never reached the handlers. Every client request is a `UnityWebRequest.Get` with the AES payload in `?data=`. aiohttp's default request-line limit (8190 bytes) rejected them with a 400 before dispatch, so they never appeared in `requests.jsonl`. A fully equipped `N2SavePreset` produces a 9.1–9.6 KB request line. Each `HousingSavePresetServletParts` part exceeds 8190 bytes at about 75 placed items, and the recovered placement budget is 200 (about 21 KB). nginx in front already allows 64 KB. | `backend/server.py`: `MAX_REQUEST_LINE = 64 * 1024`, applied through `application()` (`handler_args={"max_line_size": ...}`). It matches `large_client_header_buffers 4 64k` in both nginx profiles. | `backend/tests/test_request_line_limits.py`: real codec-built maximal preset and housing payloads are rejected by the default parser and accepted by the configured one. The test round-trips decrypt/parse and checks the limit against both nginx files. |
| Shop 3D try-on preview could not find models. `EntryItem.Set` (0x4aa380) stores `ItemData.id` as `itemSelected`. `EntryItem.OnClick` (0x4a9790) passes that value to the preview loader `SetShopBase.Init(itemSelected, tablename)`. `WardrobeWindow.buyItem`/`OnClickBuyNP`/`OnClickGift` (0x4b8500/0x4b75e0/0x4b7700) send the same value to the buy/gift servlets. Generated offers put the offer ID there. `EntryBase.setThumbnail` uses only `imagePath`, so thumbnails were unaffected. | `backend/shop.py`: list replies (`GetFeatures`, `GetShopTypeData` direct-item genders, `GetItemAssetsData`, `NPShopBundleItems`) now send the shipped asset ID as `ItemData.id`. Exceptions keep the offer ID: bundles, and asset IDs that name more than one active local item or collide with another offer ID. In the full catalog that is 8 MALE IDs shipped under two categories, which a buy request (no category field) cannot disambiguate. `NPShopBuyItem`, `NPShopGiftItem`, `NPShopIsItemPurchased` and `NPShopBundleItems` resolve an exact offer ID first, then an unambiguous asset ID among active offers, using the displayed price to pick between stores. `shop_owned` stays keyed by offer ID; nothing is migrated. `GetPurchases` already lists asset IDs and is unchanged. | `backend/tests/test_shop_item_ids.py` (7 cases: list IDs, asset- and legacy-ID buy/check, pre-existing offer-keyed ownership, cross-store price selection, gift, ambiguous fallback, offer-ID collision). Four existing tests that looked rows up by offer ID now expect the asset ID. |
| Joining a friend in a shared world failed. Native InviteToJoin loads the friend's `psidglobal` with the friend's session GUID as `desiredGuid` (`N2GetPsidglobalAndGuidByUsernamePlatform` returns both; callback 0x488fe0). `HousingStore.resolve_load` treated every `desiredGuid` as an apartment owner and answered 403 when the friend was in Nexus, LeafPark, Beach or Cinema, in both managed and manual mode. | `backend/housing.py:209` returns no binding for a friend allocated to a public world (personal names keep apartment authority). `ManagedInstanceLifecycle._public_invite_target` (`backend/instance_lifecycle.py:228`) pins the friend's exact public instance: the friend's session must be current, present and in the requested scene, and that instance must not be excluded. A full or unlaunchable target answers `noFreeSlot=true`. A friend-pinned public demand stays valid after the friend leaves. | `backend/tests/test_scene_admission.py`: managed and manual joins land on the friend's instance, not the least populated one. Full target gives noFreeSlot. Absent, wrong-scene, excluded and apartment requests are refused. Blocked destinations reserve nothing. Allow-lists in the backend, the image entrypoint, the systemd unit and `NebulaCoreReadiness.cs` must agree. |

Already fixed in source before this pass but not yet deployed: the write-free
`STMCompleteSucceededOrders` acknowledgement (the live server still logged five
501s), and the gateway no longer requires opcode 1 first (see live evidence).

## Scene-server gaps: source-fixed, awaiting Linux rebuild

The six gaps found in the previous pass, plus the opcode 15 wheel-selection
defect found while fixing them, were fixed in the Unity C# sources on
2026-10-31. None of them is live. The deployed scene server still runs the old
build, and these rows only change behavior after a reviewed Linux rebuild with
`mirror-server/build_linux.py`.

A compile check of all `Assets/Preservation` sources against the Unity
6000.6.3f1 and Mirror reference assemblies (Roslyn from the Unity SDK, outside
the repository) succeeded with no errors or warnings. A real Linux Dedicated
Server build was then attempted in a scratch copy. Unity exited with code 198
before compiling anything because the editor licence was not available
(`com.unity.editor.headless` entitlement not found). The rebuild therefore still
has to happen on a licensed build host. The Python gateway change (item 5) is
not part of the Unity build and works as soon as the backend is deployed.

1. **Opcode 15: wheel selection and jetpack (17 shares the durable flow).**
   *Client evidence:*
   - Every sender renders its own request locally right after sending.
     `LocomotionPrefab.OnClick` (0x4b9be0) sends `15#guid#<idAsset>`, or
     `15#guid#` for the `isEmpty` "none" entry (field +0x28). It then calls
     `UpdateLocomotion` (0x5f5270). `PetPrefab.OnClick` (0x4c0b00) does the
     same with `UpdateCompanion`, and the jetpack calls (0x41f200, 0x420090,
     0x41fa00) do the same too. A self-echo is therefore never needed.
   - `UpdateLocomotion` always calls `RemoveLocomotion` (0x5f3c60). When the
     player whose animator it is already has a locomotion object, that call
     sends `15#<local SessionGUID>#` and clears the local Persistency. This
     produces automatic empties in four situations:
     - Right after the sender's own 15. A wheel switch from A to B sends B,
       then an empty, and "none" sends two empties.
     - When the client receives S2C15 for itself.
     - When a viewer receives S2C15 for a remote player who has a locomotion
       (`UpdateLocomotionProcessor` 0x5ec4d0). The viewer then sends an empty
       15 under its own GUID.
     - When the jetpack landing restores the remembered locomotion.
   - `RemoveLocomotion` is also a deliberate removal on its own. It is called
     by `SetCurrentAnim` (0x5f4500), Cupid StartInLove, Zombie StartZombie,
     FoodTruck, OktoberFest, SkatingArea, SpaceGame and the CampSilverLake
     launcher, and by jetpack `DisableLocomotionAndCompanion` (0x41f6c0).
   - The remote animation receiver S2C5 → `SetAnim` (0x5f4440) does not remove
     the locomotion. `UpdateCompanion` and `RemoveCompanion` send nothing.
   - The explicit removal is therefore an empty 15, and so is a side effect.

   *Fix* (`NebulaInstanceServer.Selection`/`Locomotion`/`PumpSelection`, and
   `NebulaLocomotionEchoes` in `NebulaWorldState.cs`):
   - **Latest wins.** Ownership is checked at once, and the new value is
     relayed to the other players at once. The durable backend commit follows,
     with one in flight per kind. Newer requests are coalesced and committed
     after it, so nothing is rejected while a commit is pending.
   - **No self-echo for client-initiated changes.** The sender receives S2C15
     or S2C17 only for a server-originated correction: an item it does not
     own, a failed or expired commit, or an HTTP/operator/revocation revision
     change. In those cases durable state is authoritative for everyone.
   - **Empty-frame accounting by ordering.** The server expects one automatic
     empty from a client in these cases:
     - After that client's own 15, if its model says an object was present.
       The window is 0.5 s; the side effect is sent in the same client frame.
     - After each S2C15 the server sends to that client while the client's
       copy of that avatar has an object. This covers the announce self-15,
       relays and 16 replies, and the window is 3 s. A freshly spawned remote
       avatar has no object. An unknown state, such as the local Persistency
       restored by `OnAvatarLoaded` (0x5dfdc0), counts as "may have one".
   - Each incoming empty consumes the oldest unexpired expectation. Any other
     empty is a deliberate removal: it is relayed to the others and persisted.
   - **Jetpack** (FlyingDevice/SteamPunk only). The scene-provided ID is a
     transient overlay with no ownership check or durable selection. The
     flight's own removal (`DisableLocomotionAndCompanion`) is a real removal
     and is persisted as empty, matching the client's cleared Persistency. The
     landing 15 restores the remembered locomotion and its side-effect empty
     is dropped. A failed commit or an external revision mid-flight never
     sends S2C15 to the flyer.
   - FlyingDevice is one of the 31 personal spaces in the shipped personal
     navigator. It loads for its bound owner and the owner's invited
     visitors (it is not a public world), and passed the all-scenes protocol
     smoke. SteamPunk ships no scene bundle and stays closed (gap 7).
     Granting the jetpack item from Python is still rejected, because it
     would persist it as the saved locomotion.
   - *Residual assumption.* A deliberate removal can be dropped if it arrives
     inside an unused expectation window. Examples are an emote within 0.5 s
     after a wheel selection, or a viewer's own emote within 3 s after a relay
     whose remote object had not finished loading (the side-effect empty is
     sent only when the object exists). The durable value then keeps the old
     locomotion until the player's next request.
   - Contract cases are in `mirror-server/tests/world-contracts` (48 checks).
2. **C2S 93 UpdateAnimationLayer.** `NebulaWorldState.AnimationLayer` accepts
   exactly three fields, layer `InLove` or `Zombie` and weight `0` or `1`. The
   senders are 0x556f20, 0x5572d0, 0x5952a0 and 0x595650. The server relays
   `93#guid#layer#weight` as `Delivery.Others`, so `DeliverWorld` sends it only
   to announced viewers that have loaded the actor. That gate is required:
   receiver 0x5ec380 resolves the player with `Memory.GetNebulaPlayer` and
   dereferences the built avatar. The last weight-1 layers per actor are kept
   and replayed from `SnapshotActor` on every fresh avatar build (C2S3). They
   are cleared by weight 0 or on disconnect. Opcode 92 state is still not
   tracked, so it is not replayed (see item 6).
   The two scenes that send it, MedievalVillage and GhostTown, are admitted by
   `N2LoadSpace` once the rebuilt scene runtime is deployed (gap 7).
3. **S2C 96 GetInstanceClosing.** On a deliberate quit (supervisor SIGTERM, idle
   or eviction stop, housing instance retire or supervisor shutdown), every
   spawned peer receives `96##<instanceId>`. Receiver 0x5dbd80 reads token1
   (the token after the empty token0, as for 30) and compares it with
   `ManagerInstance.id_instance` (+0x248). That value is `N2SpaceLoading`
   field 2, which `service.py`/`instance_lifecycle.py` fill from this
   instance's `instance_id`. The client then shows `spaceOwnerDisconnected`,
   locks input and runs `RedirectToNexus`.
   - `Application.wantsToQuit` postpones the quit by at least two frames and
     0.5 s, so Mirror's LateUpdate batch flush delivers the frame. The
     supervisor's stop grace is 10 s.
   - If a quit bypasses `wantsToQuit`, `Stop()` sends 96, runs Mirror's
     internal `NetworkLateUpdate` by reflection (the build is Mono), and
     sleeps 250 ms before `NetworkServer.Shutdown`.
   - A per-player allocation change (travel, moderation move or kick) sends
     **no** 96. During travel `N2LoadSpace` reallocates before the client
     replaces `id_instance`, so a 96 would match and hijack the journey to
     Nexus. The housing layout-epoch reload of visitors also keeps the generic
     reconnect, because it reloads the same apartment rather than closing it.
4. **Legacy 94 relay.** `DeliverWorld` no longer gates `94#` frames on
   `loadedRemotes`. Receiver 0x5d91b0 only looks up scene `APITPInteractables`.
5. **Pre-binding speed, transform and opcode 2.** Before the first
   GUID-bearing request, the scene keeps the latest Mirror `SetSpeed` and the
   latest `CmdClientToServerSync`/teleport position, rotation and scale. It
   also keeps the latest opcode 2 transform. The netId must match. Ownership
   still binds only through a GUID-bearing request, and the stored values are
   applied in `Own` on that first binding (`ApplyPreBinding`, before
   `SeedRemotes`). `backend/remote_gateway.py first_identity_frame` now
   forwards each fully validated batch whole and in order, instead of dropping
   unbound updates. The GUID check still covers every GUID-bearing frame, and
   the 30 s / 256-frame identity budget is unchanged. Opcodes 19 and 30 are
   forwarded but still rejected by the scene until binding. 19 is UI-driven
   after announcement, and 30 is a user interaction at the Waterfall trigger,
   so neither can occur that early.
6. **Minor items, decided on client evidence:**
   - Opcode 30 is now accepted only in Waterfall. Its only sender is
     `DayNightTrigger.Interact` (0x44f580), and of the 48 shipped logic prefabs
     only `waterfalllogicprefab` contains a `DayNightTrigger`. The unmodified
     client is unaffected.
   - Empty 17 from boat paths: unchanged. `HarbourEnter.Interact` (0x451e00)
     sends `17#guid#` and calls `NebulaPlayer.UpdateCompanion("")` locally
     without keeping anything to restore, so "no pet" is what the client
     itself shows afterwards.
   - 18 sender exclusion: unchanged. The sender already applied its own label
     after the HTTP save, and no visible difference is proven.
   - 92 late-joiner replay: unchanged. `SendParameter` (0x5f3ee0) has no
     direct caller, and nothing shows that the retired server stored animator
     parameters.
   - 27: still no producer known.

7. **11 original public worlds (N2LoadSpace).** The shipped navigator
   (`PreInitLOAD.NavigatorPublicSpaces` in `s/preinitiload`; its
   `PublicSpacesDisabled` list is empty) and the Nexus `CustomSpaceTrigger`s
   (`spaceName`, read from `s/nexuslogicprefab`) send Bowling, Dome,
   StoneLakeCastle, Cube, GhostTown, TheNebulianOpenHouse, ZeroDistrict,
   NebuHouseOpenHouse, WestValleyApartmentOpenHouse, MedievalVillage and SKL
   (the SKL and Cinema triggers ship inactive). All ship scene and logic
   bundles. The old scene server throws `invalid_core_test_profile_or_scene`
   at start for any `nonmini-semantic-v1` space outside
   `NebulaCoreReadiness.publicScenes`, so the backend answered 404.
   *Fix:* `NebulaCoreReadiness.cs` `publicScenes` now lists all 15 public
   worlds. Nothing else in the scene server is scene-specific:
   `NebulaWorldState.SceneInventory.ForSpace` already classifies all 11. The
   same set is in `NONMINI_PUBLIC_SCENES` (`backend/allocation.py:24`, also
   used by the interaction registry), `SCENE_LABELS`
   (`backend/game_admin.py:26`), `SCENES` in `deployment/docker/entrypoint.py`,
   the `--allowed-scene` lists in `deployment/instance-supervisor/`, the
   admin panel's `publicScenes`, and the experimental Rust port.
   `protocol/static-interaction-manifest.json` was regenerated with
   `tools/research/build_static_interaction_manifest.py` (46 scenes, 43 core).
   The 35 existing rows are unchanged, and every new row is complete with
   ordinary entries only: Bowling 30, Dome 41, StoneLakeCastle 6, Cube 72,
   TheNebulianOpenHouse 12 and ZeroDistrict 66 `NebulaSeat` entries;
   NebuHouseOpenHouse 1 and WestValleyApartmentOpenHouse 2
   `JG_DoorInteractable` entries; GhostTown, MedievalVillage and SKL verified
   empty. `backend/tests/test_scene_admission.py` checks that every list
   agrees and that every public world allocates and becomes ready with its
   registry.
   *Minigame tables:* Bowling (3 darts tables, 12 lanes, pool, pinball) and
   StoneLakeCastle (8 board-game tables, archery) still start with zero
   board, darts, pool and bowling tables. With `nonmini-semantic-v1`, any
   nonzero count is rejected at instance start and by
   `NebulaCoreReadiness.Eligible`. The worlds load with those tables closed.
   *Not admitted:* SteamPunk is in the navigator, but the client ships only
   `s/steampunklogicprefab`, with no `s/steampunk` scene bundle, and its
   Nexus trigger is inactive. `Scenes.Load` cannot load it.
   TokyoApartmentOpenHouse has bundles but no navigator entry or trigger.
   **Deploy coupling:** the backend now admits these worlds, so it requires
   the rebuilt scene runtime. If this backend runs with the old Linux
   runtime, the supervisor launches a scene server that exits at start. The
   client then polls `N2SpaceLoading` forever behind "Synchronizing to
   Server". Deploy the backend and the rebuilt runtime together.

## Remaining non-minigame gaps

Gap numbers 1-7 refer to the source-fixed list above.

- 27 ToJoinNotification: no original producer recovered.
- 92 AnimParameter: not replayed to late joiners (see above).

**Client-patch requirements:** none new. The only client-side dependency found
is the existing `GetAllInWardrobe` loop fix at 0x608323, which the network-only
patch bundle already applies (`client-patches/network-only/verify_network_client.py`).

**Policy limits that are not wire defects.** These are kept and documented:
- `N2LoadSpace` admits every destination the shipped client can load: 15
  public worlds plus 31 personal spaces (46 of 47; SteamPunk has no scene
  bundle). This requires the rebuilt scene runtime (gap 7). Personal spaces
  need an owner binding, or an invite from the present owner. A
  visitor cannot pass an apartment invite on. With 1.9 GB RAM and 1 CPU the
  host runs at most 3 worlds, and idle worlds are evicted for new demand.
  When every slot is busy the reply is the native `noFreeSlot=true`, never a
  refusal of the world.
- Apartment ownership. The native navigator always offers `Home`
  (`NavigatorSelector.SetPersonalSpaces` 0x47d5b0, `GetPersonalSpaces`
  0x3e86a0) and enables other apartments only from GetPurchases
  `personalspacesName`. In managed mode every account (existing accounts
  backfilled once at startup) owns `Home` plus `NEBULA_STARTER_APARTMENTS`
  (default `CliffApartment`, `LakeApartment`, a preservation choice).
  The other apartments are sold again in the shop's Spaces tab
  (`GetItemAssetsData` gender 4, type `PERSON`; EntryGender.OnClick
  0x4a86e0) under their shipped `PersonalSpaces/<id>` shop IDs. The
  ID-to-apartment mapping is inferred from shipped images and scene bundles
  (`protocol/personal-space-shop.json`); the 150 crystal / 75 NP price is
  preservation policy. A purchase, gift or grant creates the binding and
  GetPurchases returns the shop ID with the navigator name. Staff also give
  or remove apartments in the panel (`Home` cannot be removed).
- The local reward, gathering and shop policies stay in place.
- `GetCinemaFilms` returns no films.
- `GetSpaceEventServlet` reports no events.
- Persona names containing `#` cannot be represented. The client does not
  escape `#` in request fields, so such a name shifts every following field.
  Live data has none.

## Live-server evidence (read-only)

Second snapshot, 2026-10-30 23:02 to 2026-10-31 09:22 UTC (3,139 game requests
after the coverage deploy), and what was changed because of it:
- Every game request took about 100 ms server-side (median 106 ms, p10 97 ms),
  including requests that failed before dispatch. The cause was a fresh scrypt
  credential derivation (n=2^15, 32 MiB) on the event loop for each request,
  which caps a 1-CPU host at about 10 game requests/s for all players.
  `AccessAuthority` now remembers successful derivations under a process-secret
  HMAC bound to the stored salt and verifier. The row is still read on every
  request, so revocation and rotation apply immediately.
- `invalid_route` 400 ×64 came in groups of three about 4 s before each login.
  They are the launcher's TLS probe (`GET /launcher-probe`, patcher
  `launcher::probe`), which requires that exact 400 body. It is now recorded as
  `launcher_probe`, not as a failure. Other malformed requests now log the
  method and a sanitized path, never the query.
- `Get_GatherStatus` 404 ×2 with no configured event now returns the native
  "no event" answer (field 3 `false`; callback 0x3f0470 returns before any UI).
- `SKLPromoTriggerServlet` 404 ×2 with no configured promo now returns
  "already consumed" (field 3 `true` hides the trigger, callback 0x3e96a0),
  the same suppression as `CheckOwnGenericReward`.
- `N2LoadSpace` 404 ×8 were the closed public worlds (gap 7, source-fixed).
- `STMBuyCrystals` 501 ×1 is retired Steam commerce; the client's response
  handler is a no-op.

First snapshot (before the coverage deploy):

- `requests.jsonl`: 1,436 game requests. All returned 200 except these:
  - `CheckServerStatusServlet` 403 ×8. Each came 0.2 s after an identical 200.
    This is the launcher's reachability probe without credentials, not the
    client.
  - `STMGetUserInfo` 403 ×1.
  - `STMCompleteSucceededOrders` 501 ×5, already fixed in source.
- Instance logs, 20:25–20:40: 58 scene connections each disconnected about
  0.3 s after spawn, with no application identity. The client re-ran
  `CheckServerStatus` → `N2LoadSpace` → `N2SpaceLoading` every ~11 s. This is
  the known opcode1-first gateway defect. From 20:40:25 every connection
  registered (opcode 97), announced (opcode 1) and stayed connected for minutes.
- 20:50:05: `mirror_command_while_in_wardrobe` rejection right after
  `SetUserInWardrobe`, then a disconnect and a reconnect at 20:50:53 after
  `RemoveInWardrobe`. This matches the client leaving the world for the avatar
  editor. The rejection is only journaled.
- No `unknown_route`, `missing_data` or `request_failed` lines exist since the
  persistent diagnostic sink was created. Docker logs were reset at 21:38 by a
  container recreate. Requests rejected by the old request-line limit could not
  appear in any of these logs. The one live `N2SavePreset` (20:50:42) was small
  enough to pass.

## HTTP servlet matrix

`Client evidence` names the native task class, or the sender method and RVA.
Handler line numbers are for the current tree.

| Route | Family | Client evidence | Our handler | Status | Notes |
|---|---|---|---|---|---|
| GetCompanionsServlet | avatar editor and entitlements | legacy coroutine | `backend/service.py:777` | implemented-correct | `true#guid#ids...`; empty fields skipped by client |
| GetInfoServlet | avatar editor and entitlements | legacy coroutine | `backend/service.py:647` | implemented-correct | mode-multiplexed (0 wardrobe `!`-framed, 1/2/3 presets); live mode 0 returned 200 |
| GetLastUsedPreset | avatar editor and entitlements | Assets.Scripts.HTTPs.Tasks.HTTPGetLastUsedPreset | `backend/service.py:411` | implemented-correct | 6 fields; data1 = requester PS4ID, gender as NAME |
| GetLoadPresetByName | avatar editor and entitlements | Assets.Scripts.HTTPs.Tasks.HTTPGetLoadPresetByName | `backend/service.py:414` | implemented-correct | 6 fields |
| GetLocomotionsServlet | avatar editor and entitlements | legacy coroutine | `backend/service.py:780` | implemented-correct | as companions |
| GetPlayerPrefsServlet | avatar editor and entitlements | Assets.Scripts.HTTPs.Tasks.HTTPGetPlayerPrefs | `backend/service.py:290` | implemented-correct | `true#guid#json` + `prefs-v1#PlatformOnly` trailer read only by the shipped patched consumer |
| GetPresetGameServlet | avatar editor and entitlements | Assets.Scripts.HTTPs.Tasks.HTTPGetPresetGame | `backend/service.py:417` | implemented-correct | 6 fields |
| GetPurchases | avatar editor and entitlements | Assets.Scripts.HTTPs.Tasks.HTTPGetPurchases | `backend/service.py:331` | implemented-correct | `true#guid#PurchasesData` JSON (`#` escaped as `\u0023`) |
| N2SavePreset | avatar editor and entitlements | legacy coroutine | `backend/service.py:590` | implemented-correct | `true#true`. **Fixed here:** fully equipped saves (~9.1-9.6 KB request line) were rejected by aiohttp before dispatch |
| PlayerPrefsServlet | avatar editor and entitlements | Assets.Scripts.HTTPs.Tasks.HTTPCheckPlayerPrefs | `backend/service.py:305` | implemented-correct | response ignored |
| RemovePresetServlet | avatar editor and entitlements | legacy coroutine | `backend/service.py:621` | implemented-correct | body never read |
| RenamePresetServlet | avatar editor and entitlements | legacy coroutine | `backend/service.py:635` | implemented-correct | body never read |
| ResetDefaultPresetServlet | avatar editor and entitlements | Assets.Scripts.HTTPs.Tasks.HTTPResetDefaultPreset | `backend/service.py:713` | implemented-correct | response array unused |
| SavePlayerPref | avatar editor and entitlements | Assets.Scripts.HTTPs.Tasks.HTTPSavePlayerPref | `backend/service.py:338` | implemented-correct | `true#guid`; client then sends TCP 18 for keys 0/1/15/21 |
| SetPlayerPrefsServlet | avatar editor and entitlements | legacy coroutine | `backend/service.py:709` | implemented-correct | legacy 4-field editor variant; body ignored |
| ShowPresetsServlet | avatar editor and entitlements | legacy coroutine | `backend/service.py:615` | implemented-correct | `true#guid#names...`; empty list is exactly `true#guid` |
| WardrobeOptionItemServlet | avatar editor and entitlements | legacy coroutine | `backend/service.py:694` | implemented-correct | 4 or 5 fields; `true#guid` |
| CinemaInteractionNPServlet | cinema social interaction | NETGCloudSpace$$Send_CinemaInteractionNP @0x3ea1a0 | `backend/rewards.py:267` | implemented-correct | operator-configured local reward policy; wire per docs/research/http-rewards.md (second-pass reviewed) |
| GetConsumablePriceServlet | consumables | legacy coroutine | `backend/service.py:898` | implemented-correct | local policy; generic-sender true/guid/ps4 checks |
| GetConsumableServlet | consumables | legacy coroutine | `backend/service.py:901` | implemented-correct | local policy; HTTP field6 relayed by the client in TCP 44/46 |
| Get_GatherConsume | gathering and event progress | NETGcloudNPGather$$Send_GatherConsume @0x3f2e90 | `backend/gathering.py:321` | implemented-correct | operator-configured gathering events; wire per docs/research/http-gathering.md |
| Get_GatherConsumeReward | gathering and event progress | NETGcloudNPGather$$Send_GatherConsumeReward @0x3f2590 | `backend/gathering.py:357` | implemented-correct | operator-configured gathering events; wire per docs/research/http-gathering.md |
| Get_GatherMedievalVillage | gathering and event progress | GatherMedievalVillage$$CheckIsAvailable @0x690700 | `backend/gathering.py:399` | implemented-correct | operator-configured gathering events; wire per docs/research/http-gathering.md |
| Get_GatherPhaseGame | gathering and event progress | NETGcloudNPGather$$Get_GatherPhaseGame @0x3f0130 | `backend/gathering.py:311` | implemented-correct | operator-configured gathering events; wire per docs/research/http-gathering.md |
| Get_GatherStatus | gathering and event progress | NETGcloudNPGather$$Send_GatherStatus @0x3f4b30 | `backend/gathering.py:295` | implemented-correct | operator-configured gathering events; wire per docs/research/http-gathering.md |
| Get_npGather | gathering and event progress | NETGcloudNPGather$$Send_Init @0x3f4e70 | `backend/gathering.py:270` | implemented-correct | operator-configured gathering events; wire per docs/research/http-gathering.md |
| Get_npGatherChristmas | gathering and event progress | NETGcloudNPGather$$Send_GatherChristmas @0x3f2190 | `backend/gathering.py:375` | implemented-correct | operator-configured gathering events; wire per docs/research/http-gathering.md |
| Get_npGatherProcessItem | gathering and event progress | NETGcloudNPGather$$ProcessItem @0x3f18d0 | `backend/gathering.py:283` | implemented-correct | operator-configured gathering events; wire per docs/research/http-gathering.md |
| Send_GatherInitInSpace | gathering and event progress | NETGcloudNPGather$$Send_GatherInitInSpace @0x3f4730 | `backend/gathering.py:300` | implemented-correct | operator-configured gathering events; wire per docs/research/http-gathering.md |
| Send_GatherMedievalVillageConsume | gathering and event progress | GatherMedievalVillage$$SendConsumeMedievalVillageItem @0x691120 | `backend/gathering.py:411` | implemented-correct | operator-configured gathering events; wire per docs/research/http-gathering.md |
| CheckOwnGenericReward | generic rewards and promotions | NETGCloudSpace.<Send_CheckOwnGenericRewardCoroutine>d__16$$MoveNext @0x3f7540 | `backend/rewards.py:271` | implemented-correct | operator-configured local reward policy; wire per docs/research/http-rewards.md (second-pass reviewed) |
| checkRewardAvailableServlet | generic rewards and promotions | NETGCloudSpace.<checkRewardAvailableCoroutine>d__35$$MoveNext @0x4161b0 | `backend/rewards.py:285` | implemented-correct | operator-configured local reward policy; wire per docs/research/http-rewards.md (second-pass reviewed) |
| GenericReward | generic rewards and promotions | NETGCloudSpace.<Send_GenericRewardCoroutine>d__18$$MoveNext @0x3f9530 | `backend/rewards.py:253 (dispatch, claim route)` | implemented-correct | operator-configured local reward policy; wire per docs/research/http-rewards.md (second-pass reviewed) |
| RewardClothServlet | generic rewards and promotions | NETGCloudSpace.<Send_rewardBeachTShirtCoroutine>d__14$$MoveNext @0x3ffd70 | `backend/rewards.py:293` | implemented-correct | operator-configured local reward policy; wire per docs/research/http-rewards.md (second-pass reviewed) |
| RewardConsumeServlet | generic rewards and promotions | NETGCloudSpace$$Send_RewardConsume @0x3ed990 | `backend/rewards.py:253 (dispatch, claim route)` | implemented-correct | operator-configured local reward policy; wire per docs/research/http-rewards.md (second-pass reviewed) |
| SKLPromoServlet | generic rewards and promotions | NETGCloudSpace$$Send_SKLPromoConsume @0x3ee1d0 | `backend/rewards.py:296` | implemented-correct | operator-configured local reward policy; wire per docs/research/http-rewards.md (second-pass reviewed) |
| SKLPromoTriggerServlet | generic rewards and promotions | NETGCloudSpace$$Send_SKLPromoCheckToSetAvailable @0x3ede80 | `backend/rewards.py:281` | implemented-correct | operator-configured local reward policy; wire per docs/research/http-rewards.md (second-pass reviewed) |
| GetHousingTypeServlet | housing | legacy coroutine | `backend/service.py:810` | implemented-correct | `true#guid#ps4#type` + ID/table/name triples; exactly 4 fields when empty |
| HousingReadPresetServlet | housing | legacy coroutine | `backend/service.py:821` | implemented-correct | 5 fields; guidOwner is the owner's present session |
| HousingSavePresetServletParts | housing | legacy coroutine | `backend/service.py:849` | implemented-correct | `true#guid#ps4#true`. **Fixed here:** parts beyond ~75 placed items (budget 200, up to ~21 KB) were rejected by aiohttp before dispatch |
| N2HousingReadPreset | housing | Assets.Scripts.HTTPs.Tasks.N2.HTTPN2HousingReadPreset | `backend/service.py (alias of route_HousingReadPresetServlet)` | implemented-correct | alias of HousingReadPresetServlet |
| ChannelGUIDServlet | login and account | Assets.Scripts.HTTPs.Tasks.HTTPGenerateGUID | `backend/service.py:278` | implemented-correct | `true#`; server derives the same SHA-256 session GUID as PS4Info (ASCII, `?` replacement) |
| CheckerServlet | login and account | Assets.Scripts.HTTPs.Tasks.HTTPChecker | `backend/service.py:195` | implemented-correct | 5 fields, nonce echoed in data1; ban fields from moderation |
| checkerToServerDownMaintenanceServlet | login and account | legacy coroutine | `backend/service.py:222` | implemented-correct | `true#guid#ps4#minutes`; 0 = no notice |
| CheckServerStatusServlet | login and account | Assets.Scripts.HTTPs.Tasks.HTTPServerStatus | `backend/service.py:217` | implemented-correct | `true#user#nonce#1`; data3=1 continues login |
| GetCinemaFilmsServlet | login and account | Assets.Scripts.HTTPs.Tasks.HTTPGetCinemaFilms | `backend/service.py:309` | stub | termination-safe no-films sentinel `LOCAL_NO_FILMS#84600` (an empty list hangs CinemaFilms.Set) |
| GetIinitInfosNeededServlet | login and account | Assets.Scripts.HTTPs.Tasks.HTTPGetIinitInfosNeeded | `backend/service.py:285` | implemented-correct | `guid#true#true#true` (no `true` prefix, as parsed); flags are local policy; field3 isMemorionActive is now `true` (MemorionServlet implemented) |
| GetNewsServlet | login and account | Assets.Scripts.HTTPs.Tasks.HTTPGetNews | `backend/service.py:319` | implemented-correct | count/date/text pairs; never `0#` (crashes both client loops) |
| InfoServlet | login and account | Assets.Scripts.HTTPs.Tasks.HTTPSendNetInfo | `backend/service.py:380` | implemented-correct | 11-field telemetry not stored; client ignores body |
| N2AddUser | login and account | legacy coroutine | `backend/service.py:267` | implemented-correct | body never read by client; `true#` satisfies the shared sender |
| N2UserExist | login and account | Assets.Scripts.HTTPs.Tasks.N2.HTTPN2UserExist | `backend/service.py:227` | implemented-correct | 7 fields; data0 must equal PS4ID or the client quits |
| STMGetUserInfo | login and account | Assets.Scripts.HTTPs.Tasks.HTTPSTMGetUserInfo | `backend/service.py:187` | implemented-correct | `OK#<json>\n` (client strips final char); country/currency are local fixture values |
| UserExistsServlet | login and account | Assets.Scripts.HTTPs.Tasks.HTTPUserExist | `backend/service.py:239` | implemented-correct | 7 fields; PS4ID binding checked |
| AddScoreArcheryServlet | minigame or full game | CastleNETGCloud$$Send_AddScoreArchery @0x432f70 | `backend/minigames.py:194` | implemented-correct | `GUID#PS4ID#score` → `true#GUID#PS4ID` (callback 0x35a740 is a no-op). Best = max; score 1..100000 is a local bound. See minigame-contracts.md |
| AddScoreBoatMiniGameServlet | minigame or full game | BlueWaveHideoutNETGCloud$$Send_AddScoreBoatMiniGame @0x431ab0 | `backend/minigames.py:210` | implemented-correct | `GUID#PS4ID#ticks` → `true#GUID#PS4ID#rank` (@0x431850 shows field 3 in RankingPosition). Lower time wins; 1 s..24 h tick bound is local |
| AddStatisticsServlet | minigame or full game | FullGameNETGCloud$$Send_AddStatistics @0x4e89e0; MiniGolf parser @0x513de0 | `backend/fullgame.py:191` | implemented-correct | MiniGolf `true#guid#ps4#0#newBest#hits#secs#rank` (>=8 fields). Kart never sends (its InfoAddStatistic is never instantiated), so type 8 is rejected. Personal best = fewest hits, then seconds |
| AddToPoolFullGameServlet | minigame or full game | FullGameNETGCloud.<AddToPoolFullGame>d__32$$MoveNext @0x4ec1c0 | `backend/fullgame.py:318` | stub | `true#guid#ps4#false` (client: "Game is full"); no full-game host exists, so no game is joinable |
| AddXPServlet | minigame or full game | XPNET$$Send_AddXP @0x44a1f0 | `backend/minigames.py:277` | implemented-correct | `GUID#PS4ID#TypeXPGame` → `true#GUID#np` (@0x449fe0 shows `+ N NP`). NP per type is operator policy, default 0; credits go to `shop_wallets` + `management_wallet_ledger` |
| CheckIsAvailableToJoinFullGameServlet | minigame or full game | FullGameNETGCloud.<CheckIsFirstToJoinFullGame>d__31$$MoveNext @0x4ecd80; UI lambda @0x4eeec0 | `backend/fullgame.py:325` | stub | `true#guid#ps4#2` (0 wait, 1 join, 2 refresh open games) |
| checkRewardGameServlet | minigame or full game | NETGCloudSpace.<checkRewardGameCoroutine>d__39$$MoveNext @0x416a20 | `backend/rewards.py:309` | implemented-correct | `GUID#PS4ID#typeGame#stage` → `true#GUID#alreadyOwned`; optional local grant keyed `typeGame:stage`, unconfigured = `true` (suppressed) |
| CreateGameServlet | minigame or full game | FullGameNETGCloud$$Send_CreateGame @0x4e8e00; parser @0x4e7320 | `backend/fullgame.py:293` | stub | `true#guid#ps4#totalPlayers#OpenGameEntry` echoing the client entry with port -1: the client's own not-created branch. Port != -1 would start `LaunchMultiScene` against a full-game host that does not exist |
| Get_BRAINMEMORION | minigame or full game | NETGcloudNPGather$$Send_TriggerBRAINMEMORION @0x3f5260; parser @0x3f08c0 | `backend/fullgame.py:392` | implemented-correct | `true#guid#ps4#state`: -1 when Christmas 2018 (type 4) is inactive or the session is not in one of its five scenes, 1 when that scene is completed, else 0 |
| Get_GatherArcheryCupid | minigame or full game | ArcheryCupidManager$$CheckIsAvailable @0x529340 | `backend/minigames.py:312` | implemented-correct | `GUID#PS4ID#ticks` → `true#GUID#PS4ID#active#cooldownSec#fires#hearts` (@0x529990). Event inactive by default (trigger hidden); shipped 6 spawn points / 4 hearts |
| Get_GatherChristmasGetSpacesCompleted | minigame or full game | NETGcloudNPGather$$Send_GatherChristmasGetSpacesCompleted @0x3f1d60; parser @0x3ef0c0 | `backend/fullgame.py:406` | implemented-correct | `true#guid#ps4#level#spacesCompleted`; level must equal the last MemorionServlet level; client compares with shipped `aRewardsID` [5,7,9,11,15,25] |
| GetActiveStagesServlet | minigame or full game | FullGameNETGCloud$$Send_GetActiveStages @0x4e9300; parsers @0x4e77e0/@0x500080 | `backend/fullgame.py:181` | implemented-correct | `true#guid#ps4#type#3`: every shipped stage unlocked (preservation choice; Kart can never report a finish) |
| GetBestScoreArcheryServlet | minigame or full game | CastleNETGCloud$$Get_BestScoreArchery @0x432770 | `backend/minigames.py:201` | implemented-correct | `true#GUID#PS4ID#best` (Int32 field 3 @0x432c30; 0 = none, -1 is the client error) |
| GetBestScoreBoatMiniGameServlet | minigame or full game | BlueWaveHideoutNETGCloud$$Get_BestScoreBoatMiniGame @0x430f80 | `backend/minigames.py:221` | implemented-correct | `true#GUID#PS4ID#ticks` (Int64 @0x4313e0; 0 = no time) |
| GetCooldownServlet | minigame or full game | FootRaceManager$$Send_InitializeGame @0x56fc30 | `backend/minigames.py:231` | implemented-correct | `GUID#PS4ID#FootRace` → `true#GUID#PS4ID#ticks` (@0x56e8a0: <0 opens race, ≥0 cooldown ticks). Cooldown length is operator policy, default 0 |
| GetFullGameLeaderboardServlet | minigame or full game | FullGameNETGCloud$$Send_GetLeaderboard @0x4e9d00; parsers @0x514710/@0x500690 | `backend/fullgame.py:219` | implemented-correct | `true#guid#ps4#type#stage#panel#count#entries`, top 10; Kart always 0 rows |
| GetInviteFriendList | minigame or full game | FullGameNETGCloud$$Send_GetInviteFriendList @0x4e9650; parser @0x4e7b30 | `backend/fullgame.py:263` | implemented-correct | `true#guid#ps4#FriendListEntries{names,stages,guids}`; online friends only (the GUID is the invite address) |
| GetLastScoreServlet | minigame or full game | FullGameNETGCloud$$Send_GetLastScore @0x4e99b0; parsers @0x514140/@0x500210 | `backend/fullgame.py:241` | implemented-correct | `true#guid#ps4#type#InfoLastScore`; no result is a 404 (client retries 5 times, then reopens the menu) |
| GetLeaderboardArcheryServlet | minigame or full game | CastleNETGCloud$$Get_ArcheryLeaderboard @0x4325d0 | `backend/minigames.py:206` | implemented-correct | `true#GUID#name!score…` (@0x52be80); top 10 is local policy, `!`/`#` names skipped |
| GetLeaderboardBoatMiniGameServlet | minigame or full game | BlueWaveHideoutNETGCloud$$Get_BoatMiniGameLeaderboard @0x431120 | `backend/minigames.py:226` | implemented-correct | `true#GUID#name!ticks…` (@0x545170, FormatTime 0x544110); top 10 local |
| GetLeaderboardServlet | minigame or full game | NETGCloudSpace.<send_getLeaderboardCoroutine>d__30$$MoveNext @0x401860; consumer @0x3eb040 | `backend/fullgame.py:332` | implemented-correct | header-less `name!value` rows (MiniGolf `name!hits!HH:mm:ss`), top 10. The consumer has no empty representation, so an empty board is a 404 (client spinner stays) |
| GetOpenGamesServlet | minigame or full game | FullGameNETGCloud$$Send_GetOpenGames @0x4ea240; parser @0x4e83c0 | `backend/fullgame.py:286` | stub | `true#guid#ps4#0` ("No open games found"); no full-game host exists |
| MemorionServlet | minigame or full game | UIMemorionGame$$SendScore @0x5ac040 / GatherUIMemorionGame$$SendScore @0x691e30; parsers @0x5aba40/@0x691c30 | `backend/fullgame.py:371` | implemented-correct | `true#guid#ps4#level#bestLevel`; arcade enabled via GetIinitInfosNeeded field3 |
| Send_ArcheryCupidConsume | minigame or full game | ArcheryCupidManager$$SendConsumeArcheryCupidItem @0x529dc0 | `backend/minigames.py:332` | implemented-correct | `GUID#PS4ID#ticks` → `true#GUID#PS4ID#fires#hearts#cooldownSec` (@0x529780); round end needs cooldown > 0; 4-heart grant optional |
| SetCooldownServlet | minigame or full game | FootRaceManager$$Send_FinishGame @0x56f610 | `backend/minigames.py:244` | implemented-correct | finish `…#FootRace#route#true` (0x56f610) or time-out `…#FootRace#false` (0x570460) → `true#GUID#PS4ID#completed#reward` (@0x56dee0). Route reward is an optional local grant |
| SetLeaderboardServlet | minigame or full game | NETGCloudSpace.<send_addStatisticsLeaderBoardCoroutine>d__33$$MoveNext @0x401100 | `backend/fullgame.py:356` | implemented-correct | ChronoRace ms per stage (best = lowest); Kart results send empty plaintext, acknowledged write-free `true#` |
| XSpacesGamesType0Servlet | minigame or full game | NETGCloudSpace$$Send_SKLMiniGameSuccess @0x3edcd0 | `backend/minigames.py:356` | implemented-correct | `GUID#PS4ID#0` → `true#GUID#PS4ID#0#step#inserted#cooldownTicks` (@0x3e9550 → UISKLResult 0x5c26b0); 6 steps, cooldown policy default 0, completion grant optional |
| STMBuyCrystals | retired steam commerce | Assets.Scripts.HTTPs.Tasks.HTTPSTMBuyCrystals | — | missing | retired Steam commerce, intentionally 501; client OnResponse is a ret stub |
| STMCompleteOrder | retired steam commerce | Assets.Scripts.HTTPs.Tasks.HTTPSTMCompleteOrder | — | missing | retired Steam commerce, intentionally 501 |
| STMCompleteSucceededOrders | retired steam commerce | Assets.Scripts.HTTPs.Tasks.HTTPSTMCompleteSucceededOrders | `backend/service.py:93 (RETIRED_ACKNOWLEDGED)` | implemented-correct | write-free `OK#` ack (client OnResponse is a ret stub). Already fixed in source; the deployed image still returned 501 five times on 2026-10-30 |
| CheckIfSpaceStillExistServlet | separate space liveness | legacy coroutine @0x46e360 | `backend/rewards.py:256` | implemented-correct | `true#bool`; compiled under MITM_Space, not shown on the modern load path |
| GetFeaturesServlet | shop catalog and local transactions | ShopNETGcloud$$Send_GetFeatures @0x410f60 | `backend/shop.py:241` | implemented-correct | local wallet/catalog policy; EntryData lists per docs/research/http-shop.md; one native Buy observed. ItemData.id is the asset ID (preview); asset or offer ID accepted back |
| GetGenderDataShopServlet | shop catalog and local transactions | ShopNETGcloud$$Send_GetGenderData @0x411100 | `backend/shop.py:242` | implemented-correct | local wallet/catalog policy; EntryData lists per docs/research/http-shop.md; one native Buy observed. ItemData.id is the asset ID (preview); asset or offer ID accepted back |
| GetItemAssetsDataServlet | shop catalog and local transactions | ShopNETGcloud$$Send_GetItemAssetsData @0x411490 | `backend/shop.py:243` | implemented-correct | local wallet/catalog policy; EntryData lists per docs/research/http-shop.md; one native Buy observed. ItemData.id is the asset ID (preview); asset or offer ID accepted back. Gender 4 + type `PERSON` lists apartments (shop ID, `PersonalSpaces/<id>` thumbnail, tablename `PERSON`) |
| GetShopDataShopServlet | shop catalog and local transactions | ShopNETGcloud$$Send_GetShopData @0x411950 | `backend/shop.py:244` | implemented-correct | local wallet/catalog policy; EntryData lists per docs/research/http-shop.md; one native Buy observed. ItemData.id is the asset ID (preview); asset or offer ID accepted back |
| GetShopInfoPlayerShop | shop catalog and local transactions | ShopNETGcloud$$Send_ShopInfoPlayer @0x413cb0 | `backend/shop.py:245` | implemented-correct | local wallet/catalog policy; EntryData lists per docs/research/http-shop.md; one native Buy observed. ItemData.id is the asset ID (preview); asset or offer ID accepted back |
| GetShopTypeDataShopServlet | shop catalog and local transactions | ShopNETGcloud$$Send_GetShopTypeData @0x411e50 | `backend/shop.py:246` | implemented-correct | local wallet/catalog policy; EntryData lists per docs/research/http-shop.md; one native Buy observed. ItemData.id is the asset ID (preview); asset or offer ID accepted back |
| NPShopBundleItemsServlet | shop catalog and local transactions | ShopNETGcloud$$Send_NPShopBundleItems @0x412710 | `backend/shop.py:247` | implemented-correct | local wallet/catalog policy; EntryData lists per docs/research/http-shop.md; one native Buy observed. ItemData.id is the asset ID (preview); asset or offer ID accepted back |
| NPShopBuyItemServlet | shop catalog and local transactions | ShopNETGcloud$$Send_NPShopBuyItem @0x412a60 | `backend/shop.py:248` | implemented-correct | local wallet/catalog policy; EntryData lists per docs/research/http-shop.md; one native Buy observed. ItemData.id is the asset ID (preview); asset or offer ID accepted back |
| NPShopGiftItemServlet | shop catalog and local transactions | ShopNETGcloud$$Send_NPShopGiftItem @0x412fe0 | `backend/shop.py:249` | implemented-correct | local wallet/catalog policy; EntryData lists per docs/research/http-shop.md; one native Buy observed. ItemData.id is the asset ID (preview); asset or offer ID accepted back |
| NPShopIsItemPurchasedServlet | shop catalog and local transactions | ShopNETGcloud$$Send_NPShopIsItemPurchased @0x4134a0 | `backend/shop.py:250` | implemented-correct | local wallet/catalog policy; EntryData lists per docs/research/http-shop.md; one native Buy observed. ItemData.id is the asset ID (preview); asset or offer ID accepted back |
| NPShopSyncCrystalsServlet | shop catalog and local transactions | ShopNETGcloud$$Send_NPShopSyncCrystals @0x413830 | `backend/shop.py:251` | implemented-correct | local wallet/catalog policy; EntryData lists per docs/research/http-shop.md; one native Buy observed. ItemData.id is the asset ID (preview); asset or offer ID accepted back |
| checkStateNPFriendsServlet | social and reporting | legacy coroutine | `backend/service.py:882` | stub | PSN only; `true#guid` takes the empty-list branch on Steam |
| GetrefusernameServlet | social and reporting | legacy coroutine | `backend/service.py:805` | implemented-correct | `true#guid#refGuid` |
| GetSocialList | social and reporting | Assets.Scripts.HTTPs.Tasks.HTTPGetSocialList | `backend/service.py:514` | stub | request/JSON shape exact; no client caller recovered, list selection is local interpretation |
| N2AddBlock | social and reporting | Assets.Scripts.HTTPs.Tasks.HTTPAddBlock | `backend/service.py:459` | implemented-correct | `OK#true` |
| N2AddSilenced | social and reporting | Assets.Scripts.HTTPs.Tasks.HTTPAddSilenced | `backend/service.py:462` | implemented-correct | `OK#true` |
| N2GetPsidglobalAndGuidByUsernamePlatform | social and reporting | Assets.Scripts.HTTPs.Tasks.N2.HTTPGetPsidglobalAndGuidByUsernamePlatform | `backend/service.py:533` | implemented-correct | `OK#psid#guid` or `OK##` (invite safe-empty branch) |
| N2GetRelationship | social and reporting | Assets.Scripts.HTTPs.Tasks.HTTPGetRelationship | `backend/service.py:521` | implemented-correct | exactly 5 fields `OK####code` (other lengths ignored); precedence of overlapping relations is local policy |
| N2GetSocialList | social and reporting | legacy coroutine | `backend/service.py:498` | implemented-correct | special-bypass parser: `true#guid#sel#count#entries`; lists 0/1/2 (SpaceUsers is client-local, PSN n/a) |
| N2RemoveBlock | social and reporting | Assets.Scripts.HTTPs.Tasks.HTTPRemoveBlock | `backend/service.py:465` | implemented-correct | `OK#true` |
| N2RemoveFriend | social and reporting | Assets.Scripts.HTTPs.Tasks.HTTPRemoveFriend | `backend/service.py:471` | implemented-correct | `OK#true` |
| N2RemoveSilenced | social and reporting | Assets.Scripts.HTTPs.Tasks.HTTPRemoveSilenced | `backend/service.py:468` | implemented-correct | `OK#true` |
| N2ToggleFavorite | social and reporting | Assets.Scripts.HTTPs.Tasks.HTTPToggleFavorite | `backend/service.py:474` | implemented-correct | `OK#true` |
| ReportServlet | social and reporting | legacy coroutine | `backend/service.py:869` | implemented-correct | `true#guid#ps4#bool` |
| GetAllInWardrobe | world allocation and wardrobe | Assets.Scripts.HTTPs.Tasks.HTTPGetAllInWardrobe | `backend/service.py:574` | implemented-correct | `OK#` suppresses the callback; non-empty replies rely on the shipped network-only patch at 0x608323 (present) |
| GetPersonalSpacesServlet | world allocation and wardrobe | legacy coroutine | `backend/service.py:805` | implemented-correct | `true#guid#ps4#a!b`; minimum 4 fields. No direct caller of `Send_GetPersonalSpaces` (0x3ecc10) in this build; the navigator reads GetPurchases `personalspacesName` |
| GetSpaceEventServlet | world allocation and wardrobe | legacy coroutine | `backend/service.py:801` | stub | always `true#guid#false` (no local space events) |
| InWardrobeCheckerServlet | world allocation and wardrobe | legacy coroutine | `backend/service.py:787` | implemented-correct | body never read; refreshes the wardrobe lease |
| N2AddUserOnline | world allocation and wardrobe | Assets.Scripts.HTTPs.Tasks.N2.HTTPAddUserOnline | `backend/service.py:388` | implemented-correct | `OK#true` |
| N2GetUserTypeSpace | world allocation and wardrobe | legacy coroutine | `backend/service.py:854` | implemented-correct | `OK##bool` (only data2 read) |
| N2LoadSpace | world allocation and wardrobe | Assets.Scripts.HTTPs.Tasks.N2.HTTPLoadSpace | `backend/service.py:737` | implemented-correct | source-fixed, awaiting Linux rebuild (gap 7); requires the rebuilt scene runtime. Wire `guid#banned#noFreeSlot`. Full or unlaunchable targets answer native `noFreeSlot=true`. Admits all 15 public worlds the client can load (`allocation.py:24`), all 31 personal spaces with an owner binding, and friend invites into either kind (`instance_lifecycle.py:228`). SteamPunk gets 404 on the client error path (`instance_lifecycle.py:256`) because the client ships no `s/steampunk` scene bundle |
| N2SpaceLoading | world allocation and wardrobe | Assets.Scripts.HTTPs.Tasks.HTTPSpaceLoading | `backend/service.py:751` | implemented-correct | `guid#false` while pending; 6 fields when ready |
| N2UpdateUserOnline | world allocation and wardrobe | Assets.Scripts.HTTPs.Tasks.N2.HTTPUpdateUserOnline | `backend/service.py:394` | implemented-correct | client OnResponse is a ret stub |
| PlayerLabelInfoServlet | world allocation and wardrobe | Assets.Scripts.HTTPs.Tasks.HTTPGetPlayerLabelInfo | `backend/service.py:420` | implemented-correct | 6 fields; data5 staff label |
| RemoveInWardrobeServlet | world allocation and wardrobe | legacy coroutine | `backend/service.py:794` | implemented-correct | body never read |
| Send_CheckIsInWardrobeServlet | world allocation and wardrobe | Assets.Scripts.HTTPs.Tasks.HTTPCheckIsInWardrobe | `backend/service.py:547` | implemented-correct | 5 fields incl. required unused trailer |
| SetUserInWardrobe | world allocation and wardrobe | Assets.Scripts.HTTPs.Tasks.HTTPSetIsInWardrobe | `backend/service.py:553` | implemented-correct | 13-field request (invariant floats); `OK#true` |
| spaceExistServlet | world allocation and wardrobe | Assets.Scripts.HTTPs.Tasks.HTTPCheckSpaceExist | `backend/service.py:766` | implemented-correct | `true#guid#bool` |

## Minigame plan

Update 2026-10-31: the 13 HTTP-only minigame routes (Archery, Boat, FootRace,
XP, Archery Cupid, SKL goal and `checkRewardGameServlet`) are implemented in
`backend/minigames.py` and `backend/rewards.py`. Every request and response
field was re-derived from the sender and its callback/parser; the contracts,
RVAs, shipped scene bounds and the local preservation choices (leaderboard size,
score bounds, cooldown lengths, NP awards, optional grants) are in
[minigame-contracts.md](research/minigame-contracts.md#http-minigame-servlets-2026-10-31).
The full-game lobby, leaderboard and Memorion routes are implemented in
`backend/fullgame.py` (2026-10-31). Contracts, RVAs, shipped stage catalogs
and preservation choices are in
[minigame-contracts.md](research/minigame-contracts.md#full-game-lobby-leaderboards-and-memorion-2026-10-31).
Multiplayer full games need a full-game host that does not exist: `CreateGame`
answers with the client's own `port == -1` not-created branch, so no game is
ever open, joinable or invitable. The invite path additionally needs the C#
change specified there (TCP 19/26 type 2, 95 type 10).

Originally none of the 27 deferred HTTP routes was implemented. Only four had
recovered response parsers: `GetLeaderboardServlet`, `SetLeaderboardServlet`,
`XSpacesGamesType0Servlet` and `checkRewardGameServlet`, all in
`docs/research/http-legacy-contracts.json`.

| Group | HTTP routes (client sender @RVA) | Scene-server pieces | Effort |
|---|---|---|---|
| Archery (Castle) | AddScoreArcheryServlet (CastleNETGCloud.Send_AddScoreArchery @0x432f70), GetBestScoreArcheryServlet (@0x432770), GetLeaderboardArcheryServlet (@0x4325d0) | none (HTTP/local only) | **Done** (2026-10-31) |
| Boat minigame (BlueWaveHideout) | AddScoreBoatMiniGameServlet (@0x431ab0), GetBestScoreBoatMiniGameServlet (@0x430f80), GetLeaderboardBoatMiniGameServlet (@0x431120) | opcodes 31 and empty 17 already implemented | **Done** (2026-10-31) |
| Full-game lobby (ChronoRace, MiniGolf, Pinball, Kart, Memorion) | AddToPoolFullGameServlet (@0x4ec1c0), CheckIsAvailableToJoinFullGameServlet (@0x4ecd80), CreateGameServlet (@0x4e8e00), GetOpenGamesServlet (@0x4ea240), GetInviteFriendList (@0x4e9650), GetActiveStagesServlet (@0x4e9300), GetLastScoreServlet (@0x4e99b0), GetFullGameLeaderboardServlet (@0x4e9d00), AddStatisticsServlet (@0x4e89e0), GetLeaderboardServlet (@0x401860), SetLeaderboardServlet (@0x401100) | invites over TCP 19/26 type 2 and 95 decline type 10 need a C# change and a full-game host (see minigame-contracts.md) | **Done** (2026-10-31): solo stages, scores and leaderboards; lobby routes answer the client's no-host branches |
| FootRace | GetCooldownServlet (FootRaceManager.Send_InitializeGame @0x56fc30), SetCooldownServlet (Send_FinishGame @0x56f610) | none | **Done** (2026-10-31) |
| Memorion | MemorionServlet (UIMemorionGame.SendScore @0x5ac040, Gather variant @0x691e30), Get_BRAINMEMORION (@0x3f5260), Get_GatherChristmasGetSpacesCompleted (@0x3f1d60) | none | **Done** (2026-10-31): `backend/fullgame.py`; the old stub left `gathering.py` |
| ArcheryCupid | Get_GatherArcheryCupid (@0x529340), Send_ArcheryCupidConsume (@0x529dc0) | none | **Done** (2026-10-31) |
| SKL goal / rewards | XSpacesGamesType0Servlet (@0x3edcd0), checkRewardGameServlet (@0x416a20) | none | **Done** (2026-10-31) |
| XP | AddXPServlet (XPNET.Send_AddXP @0x44a1f0; TypeXPGame 0–12) | none | **Done** (2026-10-31) |
| Board / Darts / Pool / Bowling | none | TCP 32-37, 51-57, 64-66, 68-71, 80-82, 84-86 in `NebulaMinigameState.cs` (see the TypeTCP matrix) | **Done** (2026-10-31, source-fixed, awaiting Linux rebuild; per-scene counts wired) |

Recommended order once minigames are in scope:
1. The HTTP-only score games (Archery, Boat, FootRace, XP). Done 2026-10-31.
2. Board relay for Chess and Draughts. Done 2026-10-31 (source-fixed, awaiting Linux rebuild).
3. Darts, Pool and Bowling. Done 2026-10-31 (source-fixed, awaiting Linux rebuild).

## Scene-server dispatch (applies to every TCP row)

Abbreviations: NIS = `mirror-server/UnityProject/Assets/Preservation/NebulaInstanceServer.cs`, NWS = `NebulaWorldState.cs`, NMS = `NebulaMinigameState.cs`, NIR = `NebulaInteractionRegistry.cs`; numbers are line numbers. C2S = client sends (sender RVA), S2C = client registered receive handler (process RVA in `ManagerInstance.SetTCPClient` 0x439f60). Evidence tags: [V] verified from client native code and our C# in this pass, [R] from earlier research, [I] inferred.

- Transport and framing: the `NebulaMessage{string data}` handler (NIS 268) decrypts AES-ECB/Base64 (`NebulaApplicationCrypto.cs`). It requires `peer.spawned` (NIS 740), a trailer of `PS4` or `StandaloneWindows` matching the bound account (NIS 745-747), and strips the opcode and trailer (NIS 748). Replies carry no trailer (NIS 1806-1809).
- Routing order in `Dispatch` (NIS 788-859):
  1. Opcode 97 goes to the interaction registry.
  2. Opcodes 8, 9, 10 and 94 go to the registry when the client is opted in (NIS 791-802).
  3. NWS handles 31, 44-47, 93 and 94 (NWS 151).
  4. NMS handles 32-37, 51-57, 64-66, 68-71, 80-82 and 84-86 (NMS 172-174).
  5. The core `switch` handles the rest (NIS 822-858). Anything else is journaled as `unsupported_opcode`, gets no reply and causes no disconnect (NIS 856-857).
- Identity: `Own()` (NIS 915-947) binds the connection to an account on the **first GUID-bearing request of any opcode**. Nothing has to come before it except the Mirror spawn. `Bound()` (NIS 1054-1062) requires an account that is already bound. `RequireAnnounced()` (NIS 1831-1834) requires that C2S1 has been processed.

---

## Scene-server TypeTCP matrix (all 97 enum values)

| # | Name | Client direction (evidence) | Minigame | Our handling (file:line) | Status | Notes / divergence |
|---:|---|---|:-:|---|---|---|
| 0 | OnConnected | S2C 0x5e0570 (fields ignored) | | NIS 717: `Send(peer,"0")` after `ObjectSpawnStarted`/`SpawnMessage(local)`/`ObjectSpawnFinished` (NIS 711-713) | implemented-correct | Ordering matches the client: the Mirror local spawn comes before 0 [R][V]. |
| 1 | PlayerJoined | C2S 0x5dfdc0 (send at 0x5e024f, after RandomIdle at 0x5e0223); S2C 0x5e4660 | | C2S: `Announce` NIS 861-893 (netId==peer.netId, Own, username/platform match). S2C: `SeedRemote` NIS 498-509, `ProcessReseeds` NIS 580-581, always right after the Mirror `SpawnMessage` | implemented-correct | S2C1 goes only for announced actors (`Entities()` NIS 416). A duplicate C2S1 is ignored (NIS 868). Announce also sends the self 17/15, the scene 94 snapshot (if not opted in), the 30 state and the 28 relation pairs (NIS 876-881). |
| 2 | Transform | C2S 0x615000; S2C 0x5e7ed0 | | `Transform` (NIS): netId owned + finite JSON. Before the first GUID-bearing request the latest sample is kept and applied on binding (`ApplyPreBinding`); afterwards `Bound` + `Broadcast` to viewers that have the actor spawned, sender excluded | implemented-correct | **Pre-binding samples: source-fixed, awaiting Linux rebuild.** Previously a sample before binding was rejected, and the gateway dropped it too; the client distance gate (0x615000) never resends it. `backend/remote_gateway.py` now forwards pre-binding frames (GUID checks unchanged). |
| 3 | GetCurrentAnim | C2S 0x5f2070 (called from remote OnAvatarLoaded 0x5e42d0, last after 16/6/20) | | `Query(...,5)` NIS 1080-1101: requester only. Also sets `loadedRemotes`, the boat `SnapshotActor` (NWS 241) and `ShowWardrobe` 29 | implemented-correct | The requester does **not** need to be announced. The target must be announced and already spawned for the requester (NIS 1083-1085). No reply when the target has no recorded animation (authored). |
| 4 | SetCurrentAnim | C2S 0x5f4500 / 0x44aed0 / 0x6157c0; RandomIdle 0x43e740, local branch only [R] | | `Animation` NIS 1103-1110 + `NebulaAnimationWire.BuildReply` (field1 must be -1 or `(int)netId`, line 24). Broadcast S2C5 to others; stored for 3 | implemented-correct | Accepted before announcement, as the client requires. Count and empty-trailing-name handling match the contract. |
| 5 | Anim | S2C 0x5d6fb0 | | Produced by 4 (broadcast) and 3 (query) | implemented-correct | Field1 (netId) is dropped as the receiver expects. |
| 6 | GetCurrentCompanion | C2S 0x5e3b10 | | `Query(...,17)` NIS 1088 | implemented-correct | Reply is S2C17. |
| 7 | Companion | none (not registered; the client uses 17) | | none | unused-enum | |
| 8 | GetOccupable | C2S 0x612380 (sent from `OnConnected` async 0x5ea6e0, **before** the avatar loads and before C2S1) | | Legacy `Occupancy(acquire=false)` NIS 1134-1147: requester gets 9 (occupied) or `10##id`. Registry `HandleReady` NIR 295-301; queued before the registry is ready (NIR 263-268) | implemented-correct | No announce requirement, as the client requires [V]. |
| 9 | Occupable | C2S 0x6159f0, 0x44b2f0; S2C 0x5dfa40 | | Legacy: claim broadcasts `9#g#id#g` to all spawned non-opted-in peers (NIS 1140-1144); a conflict replies `9#req#id#occupant` to the requester only (NIS 1145). Registry: a conflict throws (NIR 302-308), and `Message.finally` disconnects opted-in clients (NIS 782-784, NIR 102) | implemented-correct | Receiver at 0x5dfa40 [V]: field0==field2 calls local `NebulaInteractor.SetOccupable` (0x5df560 only writes `occupable[id].occupant`); otherwise it calls an interactable virtual. Arbitration is authored policy. In registry mode, a seat click before registration (`registry_not_ready`) also causes a **disconnect** (see the timing table below). |
| 10 | LeaveOccupable | C2S 0x612700; S2C 0x5dc440 | | `LeaveOccupancy` NIS 1302-1310 (broadcast); disconnect cleanup NIS 1781-1785; registry NIR 311-317 | implemented-correct | Rejected when the sender does not own the seat (no reply). |
| 11 | StartTyping | C2S 0x5f0320, plus **RemotePlayerMenu.OnOptionSelected 0x483650** and **SocialOptionsMenu.OnTalk 0x4c7700**. All three send `11#SessionGUID#activeTab.name` [V disasm] | | `StartTyping` NIS 1351-1373: `Public` goes to announced others filtered by relation; a private target gets `11#guid#username`, or a cross-instance relay | implemented-correct | Requires announced and not muted. A private tab requires a chat grant; otherwise it is rejected silently. |
| 12 | StopTyping | C2S 0x463310 / 0x4625b0; S2C 0x5e7580 | | NIS 833, `StopTyping` NIS 1375-1393 | implemented-correct | |
| 13 | ChatMessage | C2S 0x4640c0 (callers 0x463310 / 0x4625b0); S2C 0x5d7790 | | `Chat` NIS 1312-1336. Type 0: group must be `Public`, delivered to **all announced including the sender** (NIS 1323-1324). Type 1: both private parties (NIS 1326-1334) | implemented-correct | The client does **not** add its own message locally (0x463310 only calls `SendMessage` and has no `OnMessageReceived`) [V], so including the sender is required and correct. Other type-0 group names are rejected (`unsupported_space_chat_group`) [I: only `Public` observed]. |
| 14 | OnRemoteDisconnected | S2C 0x5e0c60 | | `RetireEntityFor` NIS 518-527: `14#guid` then `ObjectDestroyMessage` | implemented-correct | Also used for the wardrobe and boat reseed. |
| 15 | UpdateLocomotion | C2S 0x4b9be0 (wheel; `isEmpty` entry sends `15#guid#`), 0x5f3c60 (RemoveLocomotion: empty, also inside UpdateLocomotion 0x5f5270 for local **and remote** avatars), JetpackFlying 0x41f200 / 0x420090 / 0x41f6c0 / 0x41fa00 (`GqOXf5oeSNwLL2W718G45L4s222EyKk5`) [V]; S2C 0x5ec4d0 | | NIS `Locomotion` → `NebulaLocomotionEchoes.ClientRequest` (drops automatic empties) → `Selection`: ownership, immediate relay to others only, coalesced durable commit (`PumpSelection`, `NebulaResourceSelections.cs`); corrections to self only when server-originated. Jetpack: transient overlay in FlyingDevice/SteamPunk | implemented-correct (source-fixed, awaiting Linux rebuild) | Previously: reject-while-pending plus restore, and a self-echo after each commit. Together with the client's automatic empty 15s, that removed the locomotion after a wheel switch, made viewers lose their own locomotion, and reverted the jetpack. See source-fixed gap 1 for the evidence and the residual timing assumption. |
| 16 | GetCurrentLocomotion | C2S 0x5e3d80 | | `Query(...,15)` NIS 1087 | implemented-correct | |
| 17 | UpdateCompanion | C2S 0x4c0b00 (PetPrefab); empty string from HarbourEnter.Interact 0x451e00, BoatMiniGame.RemoveCompanion 0x544b40, BoatTripManager.RemoveCompanion 0x546370; JetpackFlying 0x41fa00 [V disasm]; S2C 0x5d7c20 | | NIS `Selection("companions")`: same latest-wins flow as 15, relayed to others at once, no self-echo (PetPrefab 0x4c0b00 renders locally; `UpdateCompanion` 0x6e88d0 sends nothing, so no echo accounting) — source-fixed, awaiting Linux rebuild | implemented-correct | Empty selections from boat paths are persisted as the durable "no pet" selection. This matches the client: `HarbourEnter.Interact` 0x451e00 sends `17#guid#` and calls `NebulaPlayer.UpdateCompanion("")` locally with nothing kept to restore [V], so the pet is gone on the client too. The retired persistence policy is unknown. The jetpack landing 17 (0x41fa00) restores the remembered companion through the normal path. |
| 18 | PlayerPref | C2S 0x6399f0 (keys 0, 1, 15, 21); S2C 0x5e4670 / 0x5e4780 | | `Preference` NIS 1112-1121: keys {0,1,2,3,4,15,21}, broadcast to others, **sender excluded** | implemented-correct | [I] The receiver also accepts the local SessionGUID, so the retired server may have echoed to the sender too. No visible effect is proven. |
| 19 | Notification | C2S 0x6e8f80, 0x4c6a60 (types 0/1/6); S2C 0x5df8a0 | | `Notification` NIS 1507-1523: the 4-field request becomes a 5-field S2C19 to the target only (NIS 1528-1531); cross-instance via mailbox. Types other than 0/1/6 are rejected (`NebulaSocialState.cs` 223). Durable gift/reward 19s come from `PumpNotifications` NIS 314-343 | implemented-correct | Ticks are .NET `DateTime.UtcNow.Ticks`, as the receiver needs. |
| 20 | GetCurrentPosition | C2S 0x5e3ff0 | | `Query(...,2)` NIS 1086 | implemented-correct | |
| 21 | RemoveFriend | C2S 0x4c5db0 / 0x6ed5a0 / 0x4c9530 (2-field variant); S2C 0x5d6db0 | | `SocialRefresh` NIS 1595-1617: S2C21 `username#platform` to both sides, then 28 snapshots | implemented-correct | The 2-field variant is accepted (NIS 1597). |
| 22 | RemoveSilenced | C2S 0x4c6140 / 0x6ed8e0; S2C 0x5d6db0 | | same | implemented-correct | |
| 23 | AddSilenced | C2S 0x6edc20; S2C 0x5d6db0 | | same | implemented-correct | |
| 24 | AddBlock | C2S 0x4cbf60 / 0x6ed260; S2C 0x5d6bc0 | | same + reseed through `SendRelationSnapshot` NIS 1633-1649 | implemented-correct | |
| 25 | RemoveBlock | C2S 0x4c64d0; S2C 0x5e55e0 | | same | implemented-correct | |
| 26 | NotificationAccepted | C2S 0x47e050 / 0x488fe0 / 0x439ad0 / 0x4499b0 / 0x449250; no S2C | | `AcceptNotification` NIS 1536-1585: types 3/4 durable ack, 5 informational, 0/1 social. 3-field type 11 is rejected (NIS 1542-1546); type 2 is rejected (`NebulaSocialState.cs` 239) | implemented-correct | No S2C26 is sent, which is correct. FullGame2 needs a full-game host plus the C# change in minigame-contracts.md (HTTP side done; no invite is issued without a host); SpaceGame11 is minigame-deferred. Invite6 is handled over HTTP by the client and sends no 26 [R]. |
| 27 | ToJoinNotification | S2C 0x5e7db0 (only checks a field count ≥3) | | never sent | missing | No original producer has been recovered [R]. Modern Invite6 uses HTTP. Low impact. |
| 28 | RelationshipUpdated | S2C 0x5e54d0 | | NIS 1648, 1656, 583 | implemented-correct | |
| 29 | SetIsInWardrobe | C2S 0x4393e0; S2C 0x5e6530 | | `EnterWardrobe` NIS 597-612 (announced + fresh HTTP lease), self 29; `ShowWardrobe` NIS 590-595 to viewers once they have loaded the actor; retained ghost across disconnect (NIS 1787-1793) | implemented-correct | |
| 30 | DayNightCycle | C2S 0x44f580 `30#<!trigger.state>`; S2C 0x5d7650 reads only token1 and calls `StartCycle(!b)` [V] | | NIS case 30: `Bound`, **Waterfall only**; broadcasts `30##<b>` to **all spawned including the sender**; replayed on announce | implemented-correct | The layout is correct (token0 is empty). [I] Passing the bool through unchanged matches "relay"; that the original semantics were not inverted is unverified. **Scene allow-list: source-fixed, awaiting Linux rebuild**: only Waterfall's logic prefab has a `DayNightTrigger` (48 prefabs surveyed), so 30 from any other scene is rejected. |
| 31 | BoatTokenToInstantiate | C2S HarbourEnter.Callback 0x451640 (`True#idx`), BoatTripManager 0x545c50 (`True#0`), Boat.FixedUpdate 0x44ce10 (`False#idx`) [V disasm]; S2C 0x5d72a0 | | `NWS.Boat` 169-194 (scene token registry), `Delivery.Others` gated by `loadedRemotes`; exit reseed `RefreshVehicleExit` NIS 529-538; late viewers through `SnapshotActor` NWS 241 | implemented-correct | Known, documented gap: rapid-boat exit (BoatRapid, 0x44bab0) sends nothing [R]. |
| 32 | Board_msg_InitGame | C2S 0x53f370; S2C 0x5d95b0 | ✔ | NMS `BoardJoin` 266-285 (+ PS4ID check in NIS dispatch) | implemented-correct | source-fixed, awaiting Linux rebuild. Seat0 gets Free(0), seat1 Awaiting(2), busy tables Full(1)/Playing(4) with `BoardGamesTable.Data`; 39 to others. |
| 33 | Board_msg_SelectGame | C2S 0x53fd20; S2C 0x5d97f0 | ✔ | NMS `BoardSelect` 287-301 | implemented-correct | source-fixed, awaiting Linux rebuild. TicTacToe/Chess/Draughts (rules 1-3); owner only (the rules menu is the Free branch); 40 to rival. |
| 34 | Board_msg_StartGame | C2S 0x5400c0; S2C 0x5d9830 | ✔ | NMS `BoardStart` 305-318 | implemented-correct | source-fixed, awaiting Linux rebuild. Either seat may start: `OnClickStartGame`/`OnClickJoinMatch` share 0x575790, which calls `Send_StartGame`. 41 to the other seat. |
| 35 | Board_msg_MakeMove | C2S 0x53f9e0; S2C 0x5d96d0 | ✔ | NMS `BoardMove` 320-341; TicTacToe 343, Chess 407-579, Draughts 581-645 | implemented-correct | source-fixed, awaiting Linux rebuild. The client never decides a result (`CheckNewMatchState` 0x53cbe0 only consumes the server GameState; Chess pieces are filtered by `IsMoveSaveForKing` 0x530050 and nothing detects mate), so the server tracks the board: checkmate gives P?Wins, stalemate Draw [I], a Draughts opponent without moves loses, Draughts capture chains keep the turn (0x5395c0). Moves are applied leniently (own piece, bounds), not re-validated. |
| 36 | Board_msg_LeaveGame | C2S 0x53f730; S2C 0x5d9690 | ✔ | NMS 192-197, `RemoveBoard` 366-376 | implemented-correct | source-fixed, awaiting Linux rebuild. |
| 37 | Board_msg_SyncGame | C2S 0x540370; S2C 0x5d9870 | ✔ | NMS 198-201, `BoardSnapshot` 378-394 | implemented-correct | source-fixed, awaiting Linux rebuild. Rules digit plus concrete Chess/Draughts/TicTacToe text (0x541310); the skipped slot N is preserved. |
| 38 | Board_msg_SyncTable | none | ✔ | none | unused-enum | |
| 39 | Board_msg_InitGameOneWay | S2C 0x5d9570 | ✔ | NMS 284, 375 | implemented-correct | source-fixed, awaiting Linux rebuild. |
| 40 | Board_msg_SelectGameOneWay | S2C 0x5d97b0 | ✔ | NMS 300 | implemented-correct | source-fixed, awaiting Linux rebuild. |
| 41 | Board_msg_StartGameOneWay | S2C 0x5d9830 | ✔ | NMS 317 | implemented-correct | source-fixed, awaiting Linux rebuild. |
| 42 | Board_msg_LeaveGameOneWay | S2C 0x5d9690 | ✔ | NMS 374 | implemented-correct | source-fixed, awaiting Linux rebuild. |
| 43 | Board_msg_MakeMoveOneWay | S2C 0x5d9770 | ✔ | NMS 340 (rival seat only) | implemented-correct | source-fixed, awaiting Linux rebuild. Spectators are not sent 43: their input replay state is uninitialised [I]. |
| 44 | FoodTruck_msg_GotConsumable | C2S 0x4190b0 (field 2 = opaque HTTP field 6); S2C 0x5dbcc0 | | `NWS.Consumable` 220-237: claims the HTTP receipt (NIS `ClaimConsumable` 2002+), replies 4-field 44 to the sender and 45 to others | implemented-correct | Admitted only in LeafPark. No late-joiner prop snapshot [R]. |
| 45 | FoodTruck_msg_GotConsumableOneWay | S2C 0x5dbc00 | | Produced (NWS 235), gated by `loadedRemotes` | implemented-correct | A client-sent 45 is rejected (NWS 162). |
| 46 | OktoberFest_msg_GotConsumable | C2S 0x419ba0; S2C 0x5dbfb0 | | same as 44, tag `oktoberfest` | implemented-correct | Dormant: the OktoberFest groups are inactive in shipped prefabs, so no scene admits the tag [R]. |
| 47 | OktoberFest_msg_GotConsumableOneWay | S2C 0x5dbef0 (3 fields) | | Produced as 3 fields (NWS 235) | implemented-correct | |
| 48 | Pinball_msg_addScore | none (no sender in `tcp-callers`, no registration) | ✔ | none | unused-enum | |
| 49 | Pinball_msg_getBestScore | none | ✔ | none | unused-enum | |
| 50 | Pinball_msg_getLeaderboard | none | ✔ | none | unused-enum | |
| 51 | Pool_msg_InitGame | C2S 0x5a98c0; S2C 0x5dc070 | ✔ | NMS `PoolJoin` 774-797 | implemented-correct | source-fixed, awaiting Linux rebuild. Free seats the owner; Awaiting (rivalName, rulesID) only after a 2-player selection; otherwise the Full/Playing busy menu (0x5995f0). |
| 52 | Pool_msg_LeaveGame | C2S 0x5a9af0; S2C 0x5dc200 | ✔ | NMS 203-208, `RemovePool` 884-895 | implemented-correct | source-fixed, awaiting Linux rebuild. Reply payload is ignored (0x5457f0); the rival gets 59. |
| 53 | Pool_msg_SelectGame | C2S 0x5a9e70; S2C 0x5dc3c0 | ✔ | NMS `PoolSelect` 801-815 | implemented-correct | source-fixed, awaiting Linux rebuild. Owner only; rules 0 = 1 player, rules 1-2 = 2 players; reply field2 is the player count. |
| 54 | Pool_msg_StartGame | C2S 0x5aa3c0; S2C 0x5dc400 | ✔ | NMS `PoolStart` 819-835 | implemented-correct | source-fixed, awaiting Linux rebuild. Role `playerOne` for seat0, `playerTwo` (any other text) for seat1, rival name in field2; 60 to the other seat. |
| 55 | Pool_msg_MakeMove | C2S 0x59a850; S2C 0x5dc340 | ✔ | NMS `PoolShot` 850-856 | implemented-correct | source-fixed, awaiting Linux rebuild. Actor gets the exact `OK` (unblocks BallMoveWaitServer); rival gets 61 with the five floats. |
| 56 | Pool_msg_EndsMove | C2S 0x59a810; S2C 0x5dc300 | ✔ | NMS `PoolBalls` 859-871 | implemented-correct | source-fixed, awaiting Linux rebuild. Actor `OK`; rival 62 without GUID and block-word count M. |
| 57 | Pool_msg_MoveFoul | C2S 0x59a8a0; S2C 0x5dc380 | ✔ | NMS `PoolFoul` 874-880 | implemented-correct | source-fixed, awaiting Linux rebuild. Actor `OK`; rival 63. |
| 58 | Pool_msg_SyncGame | none | ✔ | none | unused-enum | |
| 59 | Pool_msg_LeaveGameOneWay | S2C 0x5dc110 | ✔ | NMS 894 | implemented-correct | source-fixed, awaiting Linux rebuild. |
| 60 | Pool_msg_StartGameOneWay | S2C 0x5dc400 | ✔ | NMS 834 | implemented-correct | source-fixed, awaiting Linux rebuild. |
| 61 | Pool_msg_MakeMoveOneWay | S2C 0x5dc340 | ✔ | NMS 855 | implemented-correct | source-fixed, awaiting Linux rebuild. |
| 62 | Pool_msg_EndsMoveOneWay | S2C 0x5dc300 | ✔ | NMS 870 | implemented-correct | source-fixed, awaiting Linux rebuild. |
| 63 | Pool_msg_MoveFoulOneWay | S2C 0x5dc380 | ✔ | NMS 879 | implemented-correct | source-fixed, awaiting Linux rebuild. |
| 64 | Bowling_msg_InitGame | C2S 0x552ea0; S2C 0x5d9d30 | ✔ | NMS `BowlingJoin` 902-923 | implemented-divergent | source-fixed, awaiting Linux rebuild. Awaiting panel with a 4-seat array that keeps empty slots; full or started lanes get a Playing panel (busy menu). Divergence: `currentTime` (an absolute CurrentTime.Millis ready deadline, 0x562760/0x563920) is 0, so the auto-ready countdown does not run; the original deadline length is unrecovered. |
| 65 | Bowling_msg_LeaveGame | C2S 0x54c3d0; S2C 0x5da230 | ✔ | NMS 215-220, `RemoveBowling` 1004-1023 | implemented-correct | source-fixed, awaiting Linux rebuild. The departed slot is emptied (no compaction); the turn moves to the next occupied seat; an empty lane becomes Free. |
| 66 | Bowling_msg_ReadyGame | C2S 0x5634e0; S2C 0x5da760 | ✔ | NMS `BowlingReady` 926-946 | implemented-divergent | source-fixed, awaiting Linux rebuild. When every seated player is ready the panel is Ready(3) (clients run `Get_StartGame` 0x548740), then Playing. Same countdown divergence as 64. |
| 67 | Bowling_msg_StartGame | none (no C2S67 seen, no registration) | ✔ | none | unused-enum | |
| 68 | Bowling_msg_ShotGame | C2S 0x54b8b0; S2C 0x5d9c30 | ✔ | NMS `BowlingShot` 958-965 | implemented-correct | source-fixed, awaiting Linux rebuild. Actor `OK` (BallMoveSendData waits on it); 76 replay to all other peers. |
| 69 | Bowling_msg_PinsGame | C2S 0x54c750; S2C 0x5daf60 | ✔ | NMS `BowlingPinsMessage` 970-989 | implemented-correct | source-fixed, awaiting Linux rebuild. Actor `OK`; 77 to all others without GUID/declared length; BinaryConverter two-unit tokens relayed verbatim. |
| 70 | Bowling_msg_TurnGame | C2S 0x54bff0; S2C 0x5db7e0 | ✔ | NMS `BowlingTurn` 993-1001 | implemented-correct | source-fixed, awaiting Linux rebuild. Actor gets 70 (EndShot waits for it before ChangeTurn15), others 78; the candidate index is kept for later 71 panels. |
| 71 | Bowling_msg_SyncGame | C2S (from the OneWay handlers); S2C 0x5dafa0 | ✔ | NMS 226-230 | implemented-correct | source-fixed, awaiting Linux rebuild. Reply `requesterGuid#lane#panel`. The client replay of its cached message is itself broken (field3 lane, actions 3211-3215; tcp-bowling.md). |
| 72 | Bowling_msg_InitGameOneWay | S2C 0x5d9c70 | ✔ | NMS 922 | implemented-divergent | source-fixed, awaiting Linux rebuild. Sent to every other announced peer (inactive spectator lanes activate). Countdown divergence as 64. |
| 73 | Bowling_msg_LeaveGameOneWay | S2C 0x5d9de0 | ✔ | NMS 1022 | implemented-correct | source-fixed, awaiting Linux rebuild. |
| 74 | Bowling_msg_ReadyGameOneWay | S2C 0x5da2e0 | ✔ | NMS 944 | implemented-divergent | source-fixed, awaiting Linux rebuild. Countdown divergence as 64. |
| 75 | Bowling_msg_StartGameOneWay | none | ✔ | none | unused-enum | |
| 76 | Bowling_msg_ShotGameOneWay | S2C 0x5d98b0 | ✔ | NMS 964 | implemented-correct | source-fixed, awaiting Linux rebuild. |
| 77 | Bowling_msg_PinsGameOneWay | S2C 0x5dabe0 | ✔ | NMS 988 | implemented-correct | source-fixed, awaiting Linux rebuild. |
| 78 | Bowling_msg_TurnGameOneWay | S2C 0x5db460 | ✔ | NMS 1000 | implemented-correct | source-fixed, awaiting Linux rebuild. |
| 79 | Bowling_msg_SyncPositionOneWay | S2C 0x5db1f0 | ✔ | never sent | missing | No client sender or server trigger was recovered; Init64/72 already seat players through `SeatPlayer`. Left unsent rather than inventing a trigger. |
| 80 | Darts_msg_InitGame | C2S 0x55c5e0; S2C 0x5db860 | ✔ | NMS `DartsJoin` 647-663 | implemented-correct | source-fixed, awaiting Linux rebuild. Busy (two seated, playing, or solo mode chosen) gives Full. |
| 81 | Darts_msg_LeaveGame | C2S 0x55cb90; S2C 0x5db9c0 | ✔ | NMS 232-236, `RemoveDarts` 717-730 | implemented-correct | source-fixed, awaiting Linux rebuild. Leaving ends an active match. |
| 82 | Darts_msg_SelectGame | C2S 0x55d240; S2C 0x5dbb40 | ✔ | NMS `DartsSelect` 665-683 | implemented-correct | source-fixed, awaiting Linux rebuild. |
| 83 | Darts_msg_SelectMode | none | ✔ | none | unused-enum | |
| 84 | Darts_msg_StartGame | C2S 0x55d730; S2C 0x5dbb80 | ✔ | NMS `DartsStart` 686-698 | implemented-correct | source-fixed, awaiting Linux rebuild. Either seat, once the seated count equals the selected mode; reply TableBlock with isActive=True; 90 to the rival, 87 to others. Scores and turns stay in the client `DartsRules*`. |
| 85 | Darts_msg_MakeMove | C2S 0x55ce40; S2C 0x5dbac0 | ✔ | NMS `DartsMove` 705-714 | implemented-correct | source-fixed, awaiting Linux rebuild. The shooter stays in Pointing(4) after sending (0x569e10) until this echo reaches `MakePassiveMove` 0x56c670, so the shot (with client-random deflection) is echoed as 85 and relayed as 91 to the rival seat. |
| 86 | Darts_msg_SyncGame | C2S 0x55d9f0; S2C 0x5dbbc0 | ✔ | NMS 241-244, `DartsSnapshot` 732-737 | implemented-correct | source-fixed, awaiting Linux rebuild. Active tables now report isActive=True. |
| 87 | Darts_msg_InitGameOneWay | S2C 0x5db820 | ✔ | Produced in NMS 662, 681, 697, 728 | implemented-correct | source-fixed, awaiting Linux rebuild. |
| 88 | Darts_msg_LeaveGameOneWay | S2C 0x5db8c0 | ✔ | Produced in NMS 727 | implemented-correct | source-fixed, awaiting Linux rebuild. |
| 89 | Darts_msg_SelectGameOneWay | S2C 0x5dbb00 | ✔ | Produced in NMS 682 | implemented-correct | source-fixed, awaiting Linux rebuild. |
| 90 | Darts_msg_StartGameOneWay | S2C 0x5dbb80 | ✔ | NMS 696 | implemented-correct | source-fixed, awaiting Linux rebuild. |
| 91 | Darts_msg_MakeMoveOneWay | S2C 0x5dbac0 | ✔ | NMS 713 (rival seat only) | implemented-correct | source-fixed, awaiting Linux rebuild. |
| 92 | AnimParameter | C2S 0x5f3ee0; S2C 0x5d6e90 | | `AnimationParameter` NIS 1123-1132: type ∈ {1,3,4,9}, broadcast to others | implemented-correct | Not replayed to late joiners [I, minor]: `SendParameter` 0x5f3ee0 has no direct caller and no evidence shows the retired server stored animator parameters, so no state is tracked. |
| 93 | UpdateAnimationLayer | **C2S** [V disasm]: Cupid2018WalkingInLove.StartInLove 0x556f20 `93#SessionGUID#InLove#1`, StopInlove 0x5572d0 `…#0`; Halloween2018ZombiesTrigger.StartZombie 0x5952a0 `93#SessionGUID#Zombie#1`, StopZombie 0x595650 `…#0`. S2C 0x5ec380 (`guid#layer#Int32`, resolves the player via `Memory.GetNebulaPlayer`) | | `NWS.AnimationLayer`: exactly 3 fields, layer ∈ {InLove, Zombie}, weight ∈ {0,1}; `Delivery.Others` → `DeliverWorld` to announced viewers that loaded the actor; last weight-1 layers replayed by `SnapshotActor` on each fresh avatar build (C2S3); cleared by 0 or disconnect | implemented-correct (source-fixed, awaiting Linux rebuild) | Was rejected as `world_clientbound_only_opcode`. Scenes: MedievalVillage (Cupid) and GhostTown (Halloween), both not yet admitted (gap 7). Contract test: `mirror-server/tests/world-contracts`. |
| 94 | Genericinteractable | C2S 0x451100; S2C 0x5d91b0 | | Legacy `NWS.Generic` → `Delivery.All`, then `DeliverWorld` to every announced non-opted-in viewer (**no `loadedRemotes` gate for `94#`**). Snapshot once per GUID. Registry path NIR 318-327 | implemented-correct (source-fixed, awaiting Linux rebuild) | The receiver 0x5d91b0 does not resolve the actor; it only calls `FindObjectsOfType<APITPInteractables>`, `Int32.Parse` and `Boolean.Parse` [V], so the former loaded-avatar gate made a still-loading viewer miss object changes. Only clients without the interaction-registry hook use this path. |
| 95 | NotificationGameDeclined | C2S 0x47fa70 / 0x47f160 (types 2/11 only); no S2C | ✔ | `DeclineNotification` NIS 1587-1593: social bookkeeping only; requires the requester announced in this instance (`NamedPeer`) | minigame-deferred | Stub: no FullGame/SpaceGame state exists. Payload `95#guid#requesterName#requesterPlatform#declineType` (10 FullGame_Declined, 12 SpaceGame_Declined). The required C# change (relay S2C19 type 10 to the inviter) is specified in minigame-contracts.md; it matters only once a full-game host exists. |
| 96 | GetInstanceClosing | S2C 0x5dbd80 (token1 compared with `ManagerInstance.id_instance` +0x248 → `spaceOwnerDisconnected` UI, input lock, `RedirectToNexus` 0x4225d0) | | `WantsToQuit`/`AnnounceClosing`/`Stop` (NIS): `96##<instanceId>` to every spawned peer on a deliberate quit; quit postponed ≥2 frames and 0.5 s so Mirror flushes, reflection flush fallback in `Stop()` | implemented-correct (source-fixed, awaiting Linux rebuild) | `instanceId` equals `N2SpaceLoading` field 2. Per-player allocation changes (travel, moderation move/kick) and housing layout reloads deliberately send no 96: during travel the client still holds the old `id_instance`, so a 96 would redirect the journey to Nexus. |
| (97) | *(not a TypeTCP value)* InteractionRegistry | Preservation client hook only | | NIS 1149-1181, NIR | n/a (extension) | Requires the patched client (`interaction-client-hook`); only on the `nonmini-semantic-v1` profile. |

### Counts (97 enum values)

| Status | Count | Opcodes |
|---|---:|---|
| implemented-correct | 81 | 0-6, 8-14, 15†, 16-26, 28-31, 44-47, 92, 93†, 94†, 96†; minigames 32-37, 39-43, 51-57, 59-63, 65, 68-71, 73, 76-78, 80-82, 84-91 |
| implemented-divergent | 4 | 64/66/72/74 (bowling ready countdown) |
| missing (non-minigame) | 1 | 27 |
| missing (minigame) | 1 | 79 |
| stub (non-minigame) | 0 | none |
| unused-enum | 9 | 7, 38, 48, 49, 50, 58, 67, 75, 83 |
| minigame-deferred | 1 | 95 |

† Non-minigame scene-server fixes of 2026-10-31: source-fixed, awaiting Linux rebuild (see "Scene-server gaps: source-fixed"). Opcodes 2 (pre-binding samples) and 30 (Waterfall allow-list) were already counted correct and carry the same marker in their rows.

Minigame TCP (2026-10-31 NMS rewrite, source-fixed, awaiting Linux rebuild):
Board, Darts, Pool and Bowling are implemented as seat authority plus relay.
Only 95 (FullGame decline, a full-game flow) remains minigame-deferred.
Contracts and evidence: [minigame-contracts.md](research/minigame-contracts.md#scene-server-relay-policy-2026-10-31).
Offline payload checks: `mirror-server/tests/minigame-contracts` (66 checks).
Per-scene table counts (read-only from the shipped logic prefabs; each count is
the manager's `gameTables` length and every table/lane `tableID` equals its
index, so client ids are 0..count-1):

| Scene | Board | Darts | Pool | Bowling | Notes |
|---|---:|---:|---:|---:|---|
| StoneLakeCastle | 8 | 0 | 0 | 0 | `BoardGamesManager` (active), Table00-07, two seat triggers each |
| Bowling | 0 | 3 | 9 | 12 | Pool GAME_00-08 (triggers for 6-8 sit under inactive `Table_06/07/08`); lanes LANE_00-11 with active triggers; Darts TABLE_00-02 under the inactive `DARTS` object (unreachable as shipped, count kept to the manager's index range); Pinball is inactive and has no TCP opcodes |
| all others | 0 | 0 | 0 | 0 | |

`NebulaCoreReadiness.SceneTables` is the single runtime contract: under a
readiness profile the instance refuses any other count at start, `Eligible`
requires the exact counts, and the status now also reports `pool_tables` and
`bowling_lanes`. `tools/instance_supervisor.py` passes the four counts per
scene; backend `allocation.MINIGAME_SCENE_TABLES` (and the experimental Rust
allocator) only admits a descriptor whose counts match its scene, so a runtime
without the pool/bowling relay is not admitted for Bowling. The supervisor and
the rebuilt server must therefore ship together.

---

## Mirror-level matrix

The client ships a 2022-era Mirror. Our project pins Mirror v66.0.9 (commit `4d0cd105`), whose `CommandMessage`/`RpcMessage` `functionHash` is `int` and whose `SpawnMessage.assetId` is `Guid` (`Assets/Mirror/Runtime/Messages.cs` 27-66), matching the client [V]. The only game NetworkBehaviour is `NebulaPlayerSyncVars` (dump.cs 72311). Every other `NetworkBehaviour` subclass in the dump is a Mirror sample or component (Tank, NetworkAnimator, NetworkRigidbody…) and is not on the player prefab.

| Element | Client evidence | Our handling (file:line) | Status | Notes |
|---|---|---|---|---|
| `NebulaMessage {string data}` (global namespace; id candidate 58609) | dump.cs 14228; `TCPClient.Send` 0x5e7820 / `OnNebulaMessage` 0x5e7690 | Struct `NebulaMirrorProbe.cs` 8; serializer NIS 253-254; handler NIS 268 (`requireAuthentication=false`); AES `NebulaApplicationCrypto.cs` (key SHA1("a56B…")[0:16], ECB, PKCS7, Base64) | implemented-correct | Replies have no platform trailer. Inbound trailer is validated at NIS 745-747. |
| Connect / authentication | `ManagerInstance` overrides only `OnClientConnect`/`OnClientDisconnect` (dump 26569+) | NIS 687-695 sets `isAuthenticated=true` | implemented-correct | [I] No authenticator is configured on the client NetworkManager. If one were, its `AuthRequestMessage` would be an unknown id and get disconnected (Mirror `NetworkServer.cs` 481-484, 533-544). |
| `ReadyMessage` | client Mirror | Mirror default (`NetworkServer.cs` 115) | implemented-correct | |
| `AddPlayerMessage` | client Mirror | `AddPlayer` NIS 697-719: allocates a netId, then SpawnStarted → Spawn(local) → SpawnFinished → `"0"` | implemented-correct | One player per connection. |
| `NotReadyMessage` | S2C-only in practice | no server handler; never sent | implemented-correct (n/a) | A client-sent NotReady would disconnect (unknown id). None is expected. |
| `SceneMessage` | — | never sent; the client loads the scene through HTTP `LoadSpace` | implemented-correct (by design) | |
| `SpawnMessage` (player prefab) | prefab `assetId 86041873b099ede4687c67606e379683`, sceneId 0 (`mirror-player-state.json`) | `Spawn` NIS 721-731; `NebulaSpawnState.cs` 11 (asset Guid), 13-28 (payload: comp0 NetworkTransform 28 bytes pos+rot, comp1 speed float) | implemented-correct | `isLocalPlayer`/`isOwner` only for the local spawn. Remote spawns go out without SpawnStarted/Finished, which is fine. |
| Scene NetworkIdentities (sceneId≠0) | none identified [R] | none | implemented-correct (n/a) | Not verified for every scene bundle. |
| `ObjectSpawnStarted/Finished` | client Mirror | NIS 711, 713 | implemented-correct | |
| `ObjectDestroyMessage` | client Mirror | NIS 525 (after `14#guid`) | implemented-correct | |
| `ObjectHideMessage` / `ChangeOwnerMessage` | — | not used | implemented-correct (n/a) | |
| `EntityStateMessage` | `NebulaPlayerSyncVars.DeserializeSyncVars` 0x614040 | NIS 1730-1733 + `NebulaSpawnState.SpeedDelta` 30-38 (comp1, dirty bit0, float) | implemented-correct | Sent to viewers other than the owner. |
| `[Command] SetSpeed(float)` comp1, hash 421014902 | 0x614560; registered 0x614850; UserCode is a `ret` stub 0x35a740 | NIS 1724-1734; `NebulaMirrorCommands.cs` 11-12, 35-48 | implemented-correct | Storing and replicating the value is authored policy (native UserCode is empty) [R]. Requires a bound account; see the timing table below. |
| `[SyncVar] speed` | dump 72315 | spawn initial plus delta, as above | implemented-correct | |
| `CmdClientToServerSync` comp0, hash -1415757549, ch1 | NetworkTransformBase | NIS 1736-1748 → `RpcServerToClientSync` to observers **including the owner** | implemented-correct | Matches native includeOwner [R]. Prefab NetworkTransform is disabled but enabled in local OnAvatarLoaded [R]. |
| `CmdTeleport(Vector3)` -788685907, `CmdTeleport(V3,Quat)` -840469116, obsolete `CmdTeleportAndRotate` -1564373760 | NetworkTransformBase | `NebulaMirrorCommands.cs` 50-98 → matching `RpcTeleport` | implemented-correct | |
| `ClientRpc`/`TargetRpc` in game code | none in `NebulaPlayerSyncVars`; only NetworkTransformBase RPCs | as above | implemented-correct | |
| Other Commands (any other hash) | — | journaled `unsupported_mirror_command` (NIS 1750-1751) | implemented-correct | None expected from game code. |
| `NetworkPingMessage` / `NetworkPongMessage` | client `NetworkTime` | Mirror default `NetworkTime.OnServerPing` (`NetworkServer.cs` 117) | implemented-correct | |

Mirror summary: 17 rows. 12 are implemented-correct and 5 are implemented-correct n/a by design. There are no divergences at the Mirror wire level. The only caveat is timing (timing table below).

---

## Timing and ordering assumptions in the scene server

| Assumption | Where | Matches client? |
|---|---|---|
| No app message before the Mirror local spawn | NIS 740 (`application_before_spawn`) | Yes. The client sends nothing before S2C0, and we send S2C0 after the spawn (NIS 717). |
| **No opcode-1-first requirement**; identity binds on the first GUID-bearing request | `Own` NIS 915-947, called by 1, 3, 4, 6, 8-12, 15-18, 20-26, 29, 31, 44, 46, 92, 94 and minigames | Yes [V]. 8 is sent from OnConnected async 0x5ea6e0 before the avatar loads, and 4 from RandomIdle before C2S1. The TLS gateway likewise binds on any GUID-bearing frame (`remote_gateway.py` 104-186). |
| 3/6/16/20 do not require the requester to be announced | `Query` NIS 1080-1101 | Yes. The target must be announced and spawned for the requester, and S2C1 is only ever sent for announced actors. |
| 8/9/10 do not require announcement | NIS 1134-1147, 1302-1310 | Yes. |
| 2, 19, 30 and Mirror Commands require a bound account | `Transform`, `Notification`, case 30, `Command` (NIS) | Yes after the source fix (awaiting Linux rebuild): the latest pre-binding speed and transform (opcode 2, `SetSpeed`, `CmdClientToServerSync`/teleport) are kept per spawned connection and applied on binding; the gateway forwards them. 19 and 30 stay rejected until binding; both are user-driven well after it. |
| 11, 13, 19, 21-26, 29, 95 require announcement | `RequireAnnounced` NIS 1316, 1355, 1510, 1540, 1590, 1599, 599 | Yes [R]. Chat unlocks in `MoveAvatarDelay` after C2S1 (`world-loading-pipeline.md` 51). |
| `loadedRemotes` (set by C2S3 only) gates 31/44/46/93 "others" and the wardrobe 29 ghost | `Query`, `DeliverWorld`, `ShowWardrobe` (NIS) | Yes; those receivers resolve the player. Legacy 94 is no longer gated (source-fixed gap 4, awaiting Linux rebuild). |
| Resource selection: one durable commit per kind in flight, newer requests coalesced; failure or a 15 s deadline reverts everyone to the durable value | `PumpSelection` (NIS) | Authored. Others see an accepted change at once; backend latency only delays persistence. |
| Registry mode: 9/10 before registry ready are rejected, and a rejected 9 **disconnects** | NIR 263-268, NIS 782-784 | Authored. Clicking a seat before the C2S97 registration completes forces a reload. 8 and 94 are queued instead. |
| Remote reseed waits for 2 Unity frames | NIS 523, 540-588 | Authored timing (documented in research). |
| Notifications (S2C19 durable) only to announced peers | NIS 329 | Yes. |
