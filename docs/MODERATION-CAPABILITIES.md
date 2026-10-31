# Staff capabilities the original client can receive

This is the complete map of moderation, staff and administrator powers that the
shipped Nebula Realms client (Steam build, `GameAssembly.dll` SHA-256
`c4dd5db5…44ac`) can actually experience, and how the preservation server
delivers each one. A power is listed as supported only when a client receiver
was found in the binary. Everything else is listed with the reason it is not
offered. Nothing here needs a client patch.

Evidence is static: IL2CPP metadata, native disassembly at the RVAs given
(image base `0x180000000`) and the existing contracts in
[moderation-contracts.json](../protocol/moderation-contracts.json),
[tcp-contracts](research/tcp-contracts.md) and
[notification contracts](research/notification-contracts.md). No game was
launched for this review. Backend behavior is covered by unit tests, not by a
native-client acceptance run.

[MODERATION.md](MODERATION.md) records the original client contracts.
[MODERATION-OPERATIONS.md](MODERATION-OPERATIONS.md) is the operator guide.

## The reload path that makes live actions possible

Most live actions use one sequence that the unmodified client already runs:

1. The backend removes the player's world allocation. It does not revoke the
   session.
2. Within about a second of the snapshot publication, the scene server drops
   the peer: the authority pump runs every 250 ms and rejects
   `allocated_instance_id != instance`. The public gateway does the same on its
   two-second revalidation.
3. `ManagerInstance.OnClientDisconnect` (`0x4390f0`) shows the client's
   disconnect notice. It skips this only while the player is already travelling
   (`isMovingFromSpace`).
4. `OnClientDisconnectedDelay` (`0x447300`) waits 2.0 s (`0x1dd2ca0`), calls
   `NetworkClient.Shutdown` and shows **Searching Server**. It then calls
   `NETGcloudLogin.LoadSpace(spaceParams.psidglobal, "", true, "", null)`
   (`0x4474c2`).
5. `LoadSpace` first asks `CheckServerStatusServlet`. If the status is 0 it
   loads the maintenance scene, and if 2 the updating scene. Otherwise it sends
   `N2LoadSpace`, whose `isBanned=true` reply loads the `UserBanned` scene.
6. `N2SpaceLoading` returns `instance#psidglobal#ip#port`.
   `HTTPSpaceLoading.JoinSpace` (`0x63beb0`) then shows
   "Loading <scene name>" and calls `Scenes.Load` with the **scene from the
   reply** (`0x63c14b`). The server therefore picks the destination.

The backend stores a one-shot redirect for that exact session GUID. It lasts
120 s and only the next `N2LoadSpace` consumes it. A later journey the player
chooses is never redirected.

## Capability table

Status values:

- **done**: existed before this change.
- **implemented**: added in this change.
- **scene rebuild**: the client supports it, but the scene server must
  originate a message. That needs a rebuilt Linux Unity runtime (see the last
  section).
- **not possible**: there is no client receiver, so it would need a client
  patch.

| Capability | Client support (evidence) | How the server triggers it | What the player sees | Status |
|---|---|---|---|---|
| Ban (timed or permanent) | Yes. `N2UserExist` (`0x636a10`), `UserExistsServlet` (`0x63ce30`) and `CheckerServlet` (`0x6074a0`) read fields `isBanned`, `banDate` and `banDescription`. `BannedUntil.ReadData` is at `0x6cc410`. | HTTP response fields at login. A connected client is dropped (all GUIDs revoked) and its reload gets `N2LoadSpace` `isBanned=true` (`0x635990`). | At login: the native ban screen with reason and expiry date (`null` = permanent). In session: drop, then the UserBanned scene. Only login fills the date and reason. | done; live reload path verified by test |
| Unban | Same fields | Ban flag false at login | Normal login. Revoked sessions stay revoked. | done |
| Kick | Mirror disconnect → `OnClientDisconnect` | Revoke the current GUID and drop the peer | Disconnect notice, then **Searching Server**. The reload with the revoked GUID gets HTTP 403, and `HTTPLoadSpace.OnError` is empty. The player stays on the spinner until they restart the game. No kick text exists. | done |
| Mute / unmute | No client receiver. `isChatRestricted` (`PS4Info+0x97`) is the platform restriction, set locally. | Server drops chat (13) and typing (11/12) relay | Messages silently go nowhere. There is no notice. | done (server-enforced) |
| Move player to another world | Yes, through the reload path. `JoinSpace` loads the scene named in the reply. | Release the allocation and set a one-shot redirect | Disconnect notice, Searching Server, then "Loading Beach" | **implemented** |
| Return to Nexus | Same | Same, with destination `Nexus` | Same, then "Loading Nexus" | **implemented** |
| Reconnect player (reload current world) | Same | Release the allocation, no redirect | Short reload. Viewers re-fetch the player's label, staff badge and status. | **implemented** |
| Evacuate one world instance | Same | Release every allocation in the instance and redirect them | Everyone in it reloads into the chosen world | **implemented** |
| Relocate or reconnect everyone | Same | Release all allocations, with an optional redirect | Everyone reloads | **implemented** |
| Server availability: maintenance / updating screen | Yes. `CheckServerStatusServlet` (`0x63abc0`) and its continuation (`0x6ecc00`): 0 → ServerUnderMaintenance, 1 → continue, 2 → UpdatingPatch. `LoadSpace` checks it before every world load. | HTTP status integer. Accounts an owner has explicitly linked to an enabled operator get 1. | New logins, travel and reloads show the native maintenance or updating screen. Combined with "relocate everyone", it moves the whole server to the maintenance screen. | **implemented** |
| Maintenance countdown | Yes. `checkerToServerDownMaintenanceServlet` (`0x4233b0`) → `ServerDownMaintenance.Show` (`0x4ddac0`) | Polled every 10 s | Shows "N minutes" for 5 s for each new value | done |
| Login news | Yes, through `GetNewsServlet` | HTTP | News text at login | done |
| Staff badge | Yes. `PlayerLabelInfoServlet` field 5 → `NebulaPlayer.staff` (`+0xD0`), shown by `NebulaPlayerLabel.SetValues` (`0x613c00`) in the name colour | HTTP label lookup | Badge text under the name. It is display only. | done (owner only) |
| Clear offensive status / mood | Yes. The label JSON `status`/`mood` goes to `SetValues(userName, status, mood, color, staff)`. | Overwrite the stored preferences. The optional reconnect makes viewers re-fetch now. | Others see the cleared label the next time they load it. The player's own client shows it after its next login. | **implemented** |
| Rename | Yes, through the label `userName` and social lookups | Stored username | New name on the next label or social fetch | done (admin) |
| Report review | `ReportServlet` (`0x3e93a0`) shows sent / previously-reported only | n/a | Nothing is sent back to the reporter | done (staff-side only) |
| Teleport within a world | **Yes.** Two receivers: TCP opcode 2 `TransformProcessor` (`0x5e7ed0`) uses `Memory.GetNebulaPlayer(int)` (`0x610ad0`), which checks the **local** player first and then calls `Transform.set_position`/`set_rotation`; and Mirror `NetworkTransformBase.UserCode_RpcTeleport` (`0x1270cf0`) → `OnTeleport` (`0x126d790`) sets the position with no authority check. A CharacterController settle is unverified at runtime. | The scene must send `2#<netId>#{TransformData}` or the RpcTeleport RPC | Instant move | **scene rebuild** |
| Force day / night | Yes. TCP 30 `ChangeDayNightAtServerProcessor` (`0x5d7650`) → `DayNightCycle.StartCycle` | The scene must broadcast `30##True/False` | Sky changes | **scene rebuild** |
| Close an instance with the owner-left panel | Yes. TCP 96 `GetInstanceClosingProcessor` (`0x5dbd80`): matching instance id → `spaceOwnerDisconnected` panel, input lock (`PadPS4+0x10/0x11`), `RedirectToNexus` (`0x4225d0`) | The scene must send `96##<instance_id>`. The scene source now sends it to every spawned player on a deliberate instance shutdown (supervisor stop, idle or eviction stop, housing retire). That change is source-fixed and awaits the Linux rebuild. An operator-triggered close still needs the command channel below. | "Owner disconnected" panel, then Nexus | **scene rebuild** (evacuate covers the outcome) |
| Live label refresh | Yes. TCP 18 `PlayerPrefsProcessor` (`0x5e4670`), keys mood 0, status 1 and colour 15 | Scene broadcast | Label updates without a reload | **scene rebuild** (reconnect covers it) |
| Scene-initiated move (alternative) | Yes. TCP 27 `ToJoinNotificationProcessor` (`0x5e7db0`): 3 or more fields → `HTTPSpaceLoading` | The scene sends `27#x#y#z` and the backend reserves the target | Loading screen, no disconnect notice | **scene rebuild** (the reload path covers it) |
| Invisibility / spectate | No client flag. The scene could only withhold spawn and `PlayerJoined` from others. | Scene policy | n/a | **scene rebuild** (server-only design) |
| Force wardrobe / character editor | Receiver exists. TCP 29 with the player's own GUID → CharacterEditor (`0x5e6530`). | This is the echo of a player-initiated HTTP wardrobe lease. Forcing it would desync that lease. | n/a | not offered |
| Free-text announcement or popup | **No.** Chat type 0 needs a known player GUID (`0x5d7790`/`0x6109e0`). Notification 19 types are social, gift or reward only. Gift shows "X has sent you <args> as a gift", which would be misleading. Support-screen 141 has no current producer. | n/a | n/a | not possible |
| Warn / private staff message | **No** targeted text receiver. Ban reason is the only free text the client shows. | n/a | n/a | not possible |
| Freeze | **No** standalone input-lock receiver. Only opcode 96 locks input, and it then redirects. | n/a | n/a | not possible |
| GM / admin / moderator / VIP roles | **No** such enum, field or type in the metadata. The only staff concept is the display string `NebulaPlayer.staff`. | n/a | n/a | not possible |
| Developer / tester flag | `isDev` (`PS4Info+0xB0`) is only *sent* (`0x63d5e1`, `0x6371c1`). `isTesting` (`+0xCC`) is set from `N2UserExist` field 3 and only *echoed* back in `N2LoadSpace` (`0x635e5f`) and `GetShopData` (`0x411c1d`) (bounded scan of every app method). | Echo only | Nothing changes in the client | not possible (no client effect) |
| Chat-restricted notice | `isChatRestricted` is set locally from the platform | n/a | n/a | not possible |
| Refuse admission at login | `N2AddUserOnline` false → `Application.Quit` (`0x6ec320`) | HTTP | The game closes | covered by ban |

The client has no receiver for anything that is not listed as supported.
Dashboard roles never become client privileges.

## Roles and permissions

| Permission | moderator | admin | owner |
|---|:-:|:-:|:-:|
| `read`, `moderation.ban`, `moderation.kick`, `moderation.mute`, `moderation.reports` | ✓ | ✓ | ✓ |
| `moderation.move` (move, return to Nexus, reconnect) | ✓ | ✓ | ✓ |
| `moderation.profile` (clear status/mood) | ✓ | ✓ | ✓ |
| `moderation.maintenance`, `moderation.news` |  | ✓ | ✓ |
| `moderation.server_status` (maintenance/updating screens) |  | ✓ | ✓ |
| `moderation.disconnect` (relocate everyone, evacuate instance) |  | ✓ | ✓ |
| economy/catalog/data/rename (existing) |  | ✓ | ✓ |
| `operators.manage`, `players.staff` (staff badge) |  |  | ✓ |

Player-targeted actions keep the existing hierarchy rule. A moderator or admin
cannot act on an account that an owner explicitly linked to an enabled operator
of equal or higher rank. Owners can.

Every POST goes through `Management._command`. That means a bearer token plus
`X-Management-Actor`, a permission check that is repeated under the write lock,
and a required `Idempotency-Key`: the same key and body replays the stored
receipt, and the same key with a different body returns 409. Each POST writes
one append-only `management_audit` row with the before and after state.
Moderation-type actions also append a `moderation_events` row. A reason is
required exactly when the permission starts with `moderation.`, and for the
staff badge and operator changes.

## Management API contract (prefix `/management/v1`)

### New commands (POST, JSON body)

| Path | Permission | Body | Notes |
|---|---|---|---|
| `users/{account_id}/move` | `moderation.move` | `{"scene": <one of the 15 public worlds in backend/game_admin.py SCENE_LABELS>\|null, "reason": str}` | `scene` is required. `null` means reconnect to the current world. Returns 409 if the player holds no world allocation. In manual (non-managed) mode, 409 if no instance of the destination is running. |
| `users/{account_id}/clear-profile` | `moderation.profile` | `{"fields"?: ["status","mood"], "reconnect"?: bool, "reason": str}` | Default is both fields. Works offline. `reconnect` releases a connected player so viewers re-fetch the label. |
| `moderation/server-status` | `moderation.server_status` | `{"status": "normal"\|"maintenance"\|"updating", "reason": str}` | Native codes 1, 0 and 2. |
| `moderation/disconnect-all` | `moderation.disconnect` | `{"scene"?: scene\|null, "reason": str}` | Releases every connected player, with an optional destination. |
| `moderation/instances/{instance_id}/evacuate` | `moderation.disconnect` | `{"scene"?: scene (default "Nexus"), "reason": str}` | Returns 409 if no connected player holds the instance. |

Existing commands are unchanged:

- `users/{id}/ban` and `users/{id}/mute`, body `{expires_at?, reason}`
- `users/{id}/unban`, `users/{id}/unmute` and `users/{id}/kick`
- `users/{id}/staff-label`, body `{label, reason}`
- `users/{id}/rename`
- `moderation/maintenance`, body `{minutes, reason}`
- `moderation/news`
- `moderation/reports/{id}`

The response envelope is `{"data": {request_id, audit_id, operation,
account_id, operator_id, store_id, offer_id, before, after, changed, replayed,
runtime_sync}}`. For relocation actions, `after` contains `released`,
`redirect_scene`, `redirect_expires_at`, `delivery` and `delivery_note`.
`runtime_sync: "snapshot_published"` means the scene-authority files were
written, which is what triggers the drop. A value of `pending` means retry with
the same key. Errors use `{"error": {code, message}}` with status 400, 401,
403, 404, 409 or 503.

### New reads (GET, permission `read`)

| Path | Response |
|---|---|
| `users/{account_id}/live` | `{account_id, username, in_world, online_flag, scene, scene_label, instance_id, allocated_at, connected, announced, in_wardrobe, position:{x,y,z,updated_at}\|null, position_source:"scene_live"\|"last_saved"\|null, pending_redirect:{scene,expires_at}\|null, server_status}` |
| `moderation/scenes` | `{items:[{id, label, kind:"public", ready_instances, players, available}]}`. This is the move picker. |
| `moderation/instances` | `{items:[{instance_id, psidglobal, label, kind:"public"\|"personal", owner_account_id, owner_name, players, allocated_players, maxusers}]}` |
| `moderation/server-status` | `{code, status, reason, actor_id, updated_at, maintenance_minutes, options}` |

`moderation/status` now also returns `server_status`.

### `GET capabilities` additions

- `admin_actions`: a list of actions the panel can render generically. Each
  entry has this shape:

  ```json
  {"id": "move", "label": "Move to world", "permission": "moderation.move",
   "target": "player", "path": "users/{account_id}/move",
   "fixed_body": {"scene": "Nexus"},
   "fields": [{"name": "scene", "type": "enum", "label": "Destination world", "required": true,
               "options_source": "moderation/scenes", "option_value": "id", "option_label": "label"}],
   "requires_reason": true, "destructive": true, "live_only": true,
   "client_effect": "…", "allowed": true}
  ```

  - `fixed_body` is optional and is merged into the POST body.
  - `target` is one of `player`, `scene` or `server`.
  - Field `type` is one of `enum`, `multi_enum`, `text`, `textarea`,
    `integer`, `boolean` or `utc_timestamp`.
  - Fields may also carry `options`, `options_source`, `default`, `min`,
    `max`, `max_length`, `nullable` and `allow_empty`.
  - Path placeholders are `{account_id}` and `{instance_id}`.
  - `allowed` is evaluated for the calling operator.

  The ids are `ban`, `unban`, `kick`, `mute`, `unmute`, `move`,
  `return_to_nexus`, `reload_world`, `clear_profile_text`, `staff_label`,
  `rename`, `maintenance_countdown`, `server_status`, `disconnect_all`,
  `evacuate_instance` and `publish_news`.
- `admin_actions_unsupported`: `[{id, status, reason}]`, where `status` is
  `needs_scene_server_rebuild` or `not_supported_by_client`. The ids are
  `teleport`, `force_day_night`, `close_instance_popup`, `live_label_refresh`,
  `invisibility_spectate`, `announcement_popup`, `warn_message`, `freeze`,
  `gm_vip_developer_flags` and `mute_notice`.
- `server_status_options`, `redirect_seconds`, `move_scenes`,
  `server_status_supported: true` and `player_relocation_supported: true`.
- `moderation_actions` adds `move` and `clear-profile`.
- `game_privilege_mutation_supported` and
  `game_developer_flag_grant_supported` remain false.

## Limits

- Relocation targets are the four reviewed public worlds. Personal apartments
  are excluded because the reload request carries no owner GUID. A visitor
  reloading from someone else's apartment follows the native behavior.
- The redirect is consumed by the first `N2LoadSpace` of that GUID. If the
  destination then reports `noFreeSlot`, the native null callback leaves the
  player on the loading screen. This is the same as any full world.
- A player who is already mid-travel (`isMovingFromSpace`) does not run the
  reload. Their own travel completes instead.
- The maintenance or updating status is a client gate, enforced by the
  unmodified client's own status check. It is not an HTTP admission block.
- These are static and unit-tested findings. Runtime acceptance with the native
  client is still outstanding. Track it in [PROGRESS.md](PROGRESS.md).

## Scene-server work needed for the "scene rebuild" rows

The moderation change itself left the scene (`mirror-server/`) source
unchanged. (A later protocol pass added the automatic shutdown 96 and the
Waterfall-only 30 rule; see `PROTOCOL-COVERAGE.md`.) The local Unity 6000.6.3f1
install has only the WebGL and Windows standalone modules. It lacks **Linux
Dedicated Server** support, so the Linux runtime cannot be rebuilt or
validated here. To add the remaining live powers:

1. **Command channel.** The backend publishes `instance-admin-commands.json`
   at the state root. It uses the same atomic `_publish_snapshot`, format
   version 1, a generation timestamp, the 15 s freshness rule and fail-closed
   parsing as `instance-accounts.json`. Each entry is
   `{command_id (uuid-hex), instance_id, target_guid|"*", kind, args,
   expires_at}`. Management enqueues inside the same atomic group as the
   audit row.
2. **Scene consumer.** In `NebulaInstanceServer.PumpAuthorizations`, which
   runs every 250 ms, the scene executes each unseen `command_id` once, and
   only for bound, announced peers on its own `instanceId`. It writes an
   immutable acknowledgement `admin-acks/<command_id>-<instance_id>.json` the
   same way as `notification-acks`.
3. **Senders, using existing helpers:**
   - `teleport`: set `peer.position` and `peer.rotation`. Then send
     `Send(peer, "2#" + peer.netId + "#" + JsonUtility.ToJson(TransformData))`
     to the owner, broadcast the same packet to observers, and call
     `ObservePose(peer)`. Mirror's `RpcTeleport(Vector3,Quaternion)` (hash
     already in `NebulaMirrorCommands.TeleportRotationRpcHash`) is the second
     native receiver.
   - `day_night`: set `isDay`, then `Broadcast("30##True|False", null)`. Line
     853 already does this for the player-triggered case.
   - `close_instance`: call the existing `AnnounceClosing()` (sends
     `96##<instanceId>` to every spawned peer), then let the deliberate-quit
     path in `WantsToQuit` flush it before the instance stops.
   - `label_refresh`: `Broadcast(Join(18, guid, key, value))` for mood (0),
     status (1) and colour (15, Unity JSON `{x,y,z}`).
4. **Build and pin.** Install the Linux Dedicated Server module. Run
   `python3 mirror-server/build_linux.py --unity <editor> --build`, which
   regenerates `build-linux-validation.json`. Update the
   `NEBULA_SERVER_SHA256`, `NEBULA_MANAGED_SHA256` and build-report pins, then
   run the Linux runtime peer tests before deploying the backend and scene
   together.
