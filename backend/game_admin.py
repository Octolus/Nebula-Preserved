"""Operator actions that the shipped client can actually experience.

Only capabilities with a recovered client receiver are exposed. Each one is
delivered through a channel the unmodified client already consumes; see
docs/MODERATION-CAPABILITIES.md for the evidence table and for everything that
is deliberately *not* offered (teleport, forced day/night, freeze, free-text
popups, GM/VIP flags ...).

Management owns authentication, idempotency and the audit row; Moderation owns
the persisted policy and its append-only history. This module only validates
targets, chooses sessions and describes the actions for the dashboard.
No sockets, files or processes are opened here.
"""
from __future__ import annotations

import hashlib
import re

from allocation import NONMINI_PUBLIC_SCENES
from moderation import PROFILE_TEXT_DEFAULTS, REDIRECT_SECONDS, SERVER_STATUS, SERVER_STATUS_CODES

# Readable names for the public worlds a staff member may send a player to.
# Personal apartments are excluded: the reconnect request carries no owner
# GUID, so a visitor cannot be placed into someone else's apartment natively.
# Labels follow the shipped in-world trigger texts ("Enter Ghost Town", ...).
SCENE_LABELS = {"Nexus": "Nexus", "LeafPark": "Leaf Park", "Beach": "Beach", "Cinema": "Cinema",
                "Bowling": "Bowling", "Dome": "Dome", "StoneLakeCastle": "Stone Castle", "Cube": "Cube",
                "GhostTown": "Ghost Town", "TheNebulianOpenHouse": "The Nebulian Open House",
                "ZeroDistrict": "Zero District", "NebuHouseOpenHouse": "NebuHouse Open House",
                "WestValleyApartmentOpenHouse": "West Valley Apartment Open House",
                "MedievalVillage": "Medieval Village", "SKL": "Super Kickers Pitch"}
INSTANCE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
DELIVERY_NOTE = ("The scene drops the player within about a second of the snapshot publication; "
                 "the unmodified client shows its disconnect notice, waits two seconds, shows "
                 "'Searching Server' and reloads through N2LoadSpace/N2SpaceLoading.")


def _field(name, kind, label, *, required=False, **extra):
    return {"name": name, "type": kind, "label": label, "required": required, **extra}


SCENE_FIELD = _field("scene", "enum", "Destination world", required=True,
                     options_source="moderation/scenes", option_value="id", option_label="label")
EXPIRY_FIELD = _field("expires_at", "utc_timestamp", "Expires (UTC seconds, empty = permanent)",
                      nullable=True)

# Generic panel contract. `path` is relative to /management/v1 and uses
# {account_id} / {instance_id} placeholders. `fixed_body` is merged into the
# POST body by the panel. `reason` is required exactly when requires_reason.
ADMIN_ACTIONS = (
    {"id": "ban", "label": "Ban", "permission": "moderation.ban", "target": "player",
     "path": "users/{account_id}/ban", "fields": [EXPIRY_FIELD], "requires_reason": True,
     "destructive": True, "live_only": False,
     "client_effect": "Login shows the native UserBanned screen with date/reason; a connected client is "
                      "dropped and its automatic reload receives N2LoadSpace isBanned=true (UserBanned screen)."},
    {"id": "unban", "label": "Unban", "permission": "moderation.ban", "target": "player",
     "path": "users/{account_id}/unban", "fields": [], "requires_reason": True,
     "destructive": False, "live_only": False,
     "client_effect": "Next login is admitted; revoked sessions stay revoked."},
    {"id": "kick", "label": "Kick", "permission": "moderation.kick", "target": "player",
     "path": "users/{account_id}/kick", "fields": [], "requires_reason": True,
     "destructive": True, "live_only": False,
     "client_effect": "Session revoked and dropped. The client shows its disconnect notice, then "
                      "'Searching Server'; its reload is refused, so the player must restart the game."},
    {"id": "mute", "label": "Mute chat", "permission": "moderation.mute", "target": "player",
     "path": "users/{account_id}/mute", "fields": [EXPIRY_FIELD], "requires_reason": True,
     "destructive": False, "live_only": False,
     "client_effect": "Server drops public/private chat and typing; the client has no mute notice."},
    {"id": "unmute", "label": "Unmute chat", "permission": "moderation.mute", "target": "player",
     "path": "users/{account_id}/unmute", "fields": [], "requires_reason": True,
     "destructive": False, "live_only": False, "client_effect": "Chat is relayed again."},
    {"id": "move", "label": "Move to world", "permission": "moderation.move", "target": "player",
     "path": "users/{account_id}/move", "fields": [SCENE_FIELD], "requires_reason": True,
     "destructive": True, "live_only": True,
     "client_effect": "Brief disconnect notice, 'Searching Server', then 'Loading <world>'."},
    {"id": "return_to_nexus", "label": "Return to Nexus", "permission": "moderation.move", "target": "player",
     "path": "users/{account_id}/move", "fixed_body": {"scene": "Nexus"}, "fields": [],
     "requires_reason": True, "destructive": True, "live_only": True,
     "client_effect": "Brief disconnect notice, 'Searching Server', then 'Loading Nexus'."},
    {"id": "reload_world", "label": "Reconnect player", "permission": "moderation.move", "target": "player",
     "path": "users/{account_id}/move", "fixed_body": {"scene": None}, "fields": [],
     "requires_reason": True, "destructive": True, "live_only": True,
     "client_effect": "Native reconnect to the world the client requests (its current one). Other "
                      "players re-fetch its name label, status and staff badge."},
    {"id": "clear_profile_text", "label": "Clear status / mood", "permission": "moderation.profile",
     "target": "player", "path": "users/{account_id}/clear-profile",
     "fields": [_field("fields", "multi_enum", "Clear", options=[
                    {"value": "status", "label": "Status message"}, {"value": "mood", "label": "Mood"}],
                       default=["status", "mood"]),
                _field("reconnect", "boolean", "Reconnect online player so others see it now", default=False)],
     "requires_reason": True, "destructive": True, "live_only": False,
     "client_effect": "PlayerLabelInfoServlet returns the cleared values the next time a client loads "
                      "the label; the player's own client shows it after its next login."},
    {"id": "staff_label", "label": "Set staff badge", "permission": "players.staff", "target": "player",
     "path": "users/{account_id}/staff-label",
     "fields": [_field("label", "text", "Badge text (empty removes)", max_length=32, allow_empty=True,
                       required=True)],
     "requires_reason": True, "destructive": False, "live_only": False,
     "client_effect": "Native lblStaff text under the name, drawn in the name colour; display only."},
    {"id": "rename", "label": "Rename player", "permission": "users.rename", "target": "player",
     "path": "users/{account_id}/rename",
     "fields": [_field("username", "text", "New name", required=True, max_length=64)],
     "requires_reason": False, "destructive": False, "live_only": False,
     "client_effect": "New name is returned by label/social lookups; connected viewers update on reload."},
    {"id": "maintenance_countdown", "label": "Maintenance countdown", "permission": "moderation.maintenance",
     "target": "server", "path": "moderation/maintenance",
     "fields": [_field("minutes", "integer", "Minutes (0 clears)", required=True, min=0, max=1440)],
     "requires_reason": True, "destructive": False, "live_only": False,
     "client_effect": "In-world 'server down in N minutes' popup, polled every 10 s, shown 5 s per new value."},
    {"id": "server_status", "label": "Server availability", "permission": "moderation.server_status",
     "target": "server", "path": "moderation/server-status",
     "fields": [_field("status", "enum", "Status", required=True, options=[
         {"value": "normal", "label": "Open"},
         {"value": "maintenance", "label": "Under maintenance screen"},
         {"value": "updating", "label": "Updating screen"}])],
     "requires_reason": True, "destructive": True, "live_only": False,
     "client_effect": "Every login and every world load (travel or reconnect) shows the native "
                      "ServerUnderMaintenance / UpdatingPatch scene. Linked staff accounts bypass it."},
    {"id": "disconnect_all", "label": "Reconnect / relocate everyone", "permission": "moderation.disconnect",
     "target": "server", "path": "moderation/disconnect-all",
     "fields": [dict(SCENE_FIELD, required=False, nullable=True,
                     label="Destination world (empty = their current world)")],
     "requires_reason": True, "destructive": True, "live_only": True,
     "client_effect": "Every connected player reloads; with server status 'maintenance' they land on "
                      "the maintenance screen."},
    {"id": "evacuate_instance", "label": "Evacuate world instance", "permission": "moderation.disconnect",
     "target": "scene", "path": "moderation/instances/{instance_id}/evacuate",
     "fields": [dict(SCENE_FIELD, default="Nexus")], "requires_reason": True,
     "destructive": True, "live_only": True,
     "client_effect": "Everyone in that instance reloads into the chosen world."},
    {"id": "publish_news", "label": "Publish login news", "permission": "moderation.news", "target": "server",
     "path": "moderation/news",
     "fields": [_field("text", "textarea", "News text", required=True, max_length=1000), EXPIRY_FIELD],
     "requires_reason": True, "destructive": False, "live_only": False,
     "client_effect": "Shown by the native news fetch at login; not a live popup."},
)

# Candidate powers that the shipped client cannot receive (or that need a
# scene-server rebuild). Returned so the dashboard can explain their absence.
UNSUPPORTED_ACTIONS = (
    {"id": "teleport", "status": "needs_scene_server_rebuild",
     "reason": "Client applies TCP opcode 2 (TransformProcessor -> Memory.GetNebulaPlayer includes the local "
               "player) and Mirror RpcTeleport, but only the scene process can send them."},
    {"id": "force_day_night", "status": "needs_scene_server_rebuild",
     "reason": "Client applies TCP opcode 30 (DayNightCycle.StartCycle); scene must originate it."},
    {"id": "close_instance_popup", "status": "needs_scene_server_rebuild",
     "reason": "TCP opcode 96 shows the owner-disconnected panel and RedirectToNexus; scene must send it. "
               "Use evacuate_instance (native reload) instead."},
    {"id": "live_label_refresh", "status": "needs_scene_server_rebuild",
     "reason": "TCP opcode 18 PlayerPref updates mood/status/colour live; use reconnect instead."},
    {"id": "invisibility_spectate", "status": "needs_scene_server_rebuild",
     "reason": "Only achievable by the scene withholding spawn/PlayerJoined; no client flag exists."},
    {"id": "announcement_popup", "status": "not_supported_by_client",
     "reason": "No free-text broadcast receiver: chat type 0 needs a known player GUID, notification types are "
               "social/gift/reward only, support-screen 141 has no current producer."},
    {"id": "warn_message", "status": "not_supported_by_client",
     "reason": "No targeted text-message receiver; ban reason (login/UserBanned) is the only free text shown."},
    {"id": "freeze", "status": "not_supported_by_client",
     "reason": "No standalone input-lock receiver (opcode 96 locks input only while redirecting to Nexus)."},
    {"id": "gm_vip_developer_flags", "status": "not_supported_by_client",
     "reason": "No GM/VIP/admin role exists client-side. isDev is client->server only; isTesting is only "
               "echoed back in N2LoadSpace/GetShopData and changes nothing in the client."},
    {"id": "mute_notice", "status": "not_supported_by_client",
     "reason": "isChatRestricted is the platform (PSN) restriction set locally; the server cannot set it."},
)


def redirected_load(store, fields, profile):
    """Rewrite one N2LoadSpace request when staff released this exact session.

    Called by Service.route_N2LoadSpace after identity checks. The native reload
    after a scene disconnect asks for its *current* psidglobal; the scene the
    client then loads is the one named in the N2SpaceLoading reply.
    """
    moderation = getattr(store, "moderation", None)
    if moderation is None:
        return fields
    scene = moderation.consume_load_redirect(fields[0], profile["ps4_id"])
    if scene is None:
        return fields
    return (fields[0], fields[1], scene, fields[3], "", "")


class GameAdmin:
    READS = ("moderation/scenes", "moderation/instances", "moderation/server-status")

    def __init__(self, management):
        self.management = management
        self.service = management.service
        self.store = management.store
        self.db = management.db

    # ---- reads ------------------------------------------------------------
    def handles_read(self, parts):
        return "/".join(parts) in self.READS or (len(parts) == 3 and parts[0] == "users" and parts[2] == "live")

    def read(self, parts, query, actor):
        tail = "/".join(parts)
        if tail == "moderation/scenes":
            return {"items": self.scenes()}
        if tail == "moderation/instances":
            return {"items": self.instances()}
        if tail == "moderation/server-status":
            return {**self.service.moderation.server_status(),
                    "maintenance_minutes": self.service.moderation.maintenance_minutes(),
                    "options": sorted(SERVER_STATUS_CODES, key=SERVER_STATUS_CODES.get)}
        return self.live(parts[1])

    def scenes(self):
        managed = self.service.lifecycle is not None
        ready = self.service.instances.all_ready()
        rows = []
        for scene, label in SCENE_LABELS.items():
            instances = [row for row in ready if row["psidglobal"] == scene]
            rows.append({"id": scene, "label": label, "kind": "public",
                         "ready_instances": len(instances),
                         "players": sum(int(row.get("players", 0)) for row in instances),
                         # Managed mode launches a world on demand; manual mode needs one running.
                         "available": managed or bool(instances)})
        return rows

    def instances(self):
        housing = {row[0]: row[1] for row in self.db.execute(
            "SELECT instance_id,owner_ps4_id FROM housing_spaces")} if self._table("housing_spaces") else {}
        owners = self.management._usernames(housing.values())
        counts = {row[0]: row[1] for row in self.db.execute(
            "SELECT instance_id,COUNT(*) FROM allocations GROUP BY instance_id")}
        rows = []
        for row in self.service.instances.all_ready():
            owner = housing.get(row["instance_id"])
            rows.append({"instance_id": row["instance_id"], "psidglobal": row["psidglobal"],
                         "label": SCENE_LABELS.get(row["psidglobal"], spaced(row["psidglobal"])),
                         "kind": "personal" if owner else "public", "owner_account_id": owner,
                         "owner_name": owners.get(owner), "players": int(row.get("players", 0)),
                         "allocated_players": counts.get(row["instance_id"], 0),
                         "maxusers": int(row.get("maxusers", 32))})
        rows.sort(key=lambda r: (r["psidglobal"], r["instance_id"]))
        return rows

    def _table(self, name):
        return self.db.execute("SELECT 1 FROM sqlite_schema WHERE type='table' AND name=?", (name,)).fetchone() is not None

    def live(self, account_id):
        profile = self.management.profile(account_id)
        moderation = self.service.moderation
        sessions = moderation.world_sessions(account_id=account_id)
        current = sessions[0] if sessions else None
        result = {"account_id": account_id, "username": profile["username"], "in_world": current is not None,
                  "online_flag": bool(profile["online"]), "scene": None, "scene_label": None,
                  "instance_id": None, "allocated_at": None, "connected": False, "announced": False,
                  "in_wardrobe": False, "position": None, "position_source": None,
                  "pending_redirect": None, "server_status": moderation.server_status()["status"]}
        saved = self.store.position(account_id)
        if saved["updated_at"]:
            result.update(position={**saved["position"], "updated_at": saved["updated_at"]},
                          position_source="last_saved")
        if current is None:
            return result
        result.update(scene=current["psidglobal"], instance_id=current["instance_id"],
                      allocated_at=current["allocated_at"],
                      scene_label=SCENE_LABELS.get(current["psidglobal"], spaced(current["psidglobal"])),
                      pending_redirect=moderation.pending_redirect(current["guid"]))
        avatar = self._avatar(current["instance_id"], current["guid"])
        if avatar is not None:
            result.update(connected=bool(avatar.get("connected")), announced=bool(avatar.get("announced")),
                          in_wardrobe=bool(avatar.get("in_wardrobe")))
            position = avatar.get("position")
            if isinstance(position, dict) and avatar.get("position_updated_at"):
                result.update(position={**{k: position.get(k) for k in ("x", "y", "z")},
                                        "updated_at": avatar["position_updated_at"]},
                              position_source="scene_live")
        return result

    def _avatar(self, instance_id, guid):
        """Fresh scene-authored avatar record (instance-avatar-state.json), if any."""
        for path in self.store.instance_files("instance-avatar-state.json"):
            value = self.store.instance_document(path, "avatars")
            if value is None or value.get("instance_id") != instance_id:
                continue
            for avatar in value["avatars"]:
                if isinstance(avatar, dict) and avatar.get("guid") == guid:
                    return avatar
        return None

    # ---- commands -----------------------------------------------------------
    @staticmethod
    def route(parts):
        """(permission, target) for routes owned here, else None."""
        if len(parts) == 3 and parts[0] == "users" and parts[2] == "move":
            return "moderation.move", parts[1]
        if len(parts) == 3 and parts[0] == "users" and parts[2] == "clear-profile":
            return "moderation.profile", parts[1]
        if parts == ["moderation", "server-status"]:
            return "moderation.server_status", "server"
        if parts == ["moderation", "disconnect-all"]:
            return "moderation.disconnect", "server"
        if len(parts) == 4 and parts[:2] == ["moderation", "instances"] and parts[3] == "evacuate":
            return "moderation.disconnect", parts[2]
        return None

    def _scene(self, body, *, allow_current):
        scene = body.get("scene")
        if scene is None and allow_current:
            return None
        self.management_require(isinstance(scene, str) and scene in SCENE_LABELS,
                                "Destination must be one of: " + ", ".join(SCENE_LABELS))
        if self.service.lifecycle is None:
            self.management_require(self.service.instances.ready(psidglobal=scene) is not None,
                                    "No ready instance of that world is running", 409, "conflict")
        return scene

    def management_require(self, value, message, status=400, code="invalid_request"):
        from management import require
        require(value, message, status, code)

    def command(self, parts, body, actor, request_id, reason):
        from management import fields
        moderation = self.service.moderation
        arguments = {"reason": reason, "actor": actor, "request_id": request_id}
        if parts[0] == "users" and parts[2] == "move":
            fields(body, ("scene", "reason"))
            self.management_require("scene" in body, "An explicit scene or null (current world) is required")
            target = parts[1]
            self.management.profile(target)
            self.management.protect_target(target, actor)
            scene = self._scene(body, allow_current=True)
            sessions = moderation.world_sessions(account_id=target)
            self.management_require(sessions, "Player is not connected to a world", 409, "conflict")
            before, after, changed = moderation.release_sessions(
                sessions, scene, operation="move", target=target, **arguments)
            return before, {**after, "delivery_note": DELIVERY_NOTE}, changed
        if parts[0] == "users" and parts[2] == "clear-profile":
            fields(body, ("fields", "reconnect", "reason"))
            target = parts[1]
            self.management.profile(target)
            self.management.protect_target(target, actor)
            keys = body.get("fields", list(PROFILE_TEXT_DEFAULTS))
            reconnect = body.get("reconnect", False)
            self.management_require(type(reconnect) is bool, "reconnect must be a Boolean")
            before, after, changed = moderation.clear_profile_text(target, keys, **arguments)
            sessions = moderation.world_sessions(account_id=target) if reconnect else []
            if sessions:
                # Same request: history keeps one event per mutation via a derived ID.
                moderation.release_sessions(sessions, None, operation="move", target=target,
                                            reason=reason, actor=actor, request_id=derived(request_id))
            return before, {**after, "reconnected": bool(sessions)}, changed or bool(sessions)
        if parts == ["moderation", "server-status"]:
            fields(body, ("status", "reason"))
            return moderation.set_server_status(body.get("status"), **arguments)
        if parts == ["moderation", "disconnect-all"]:
            fields(body, ("scene", "reason"))
            scene = self._scene(body, allow_current=True)
            sessions = moderation.world_sessions()
            before, after, changed = moderation.release_sessions(
                sessions, scene, operation="disconnect.all", target="global", **arguments)
            return before, {**after, "delivery_note": DELIVERY_NOTE}, changed
        # moderation/instances/{id}/evacuate
        fields(body, ("scene", "reason"))
        instance_id = parts[2]
        self.management_require(INSTANCE_ID.fullmatch(instance_id), "Invalid instance ID")
        scene = self._scene({"scene": body.get("scene", "Nexus")}, allow_current=False)
        sessions = moderation.world_sessions(instance_id=instance_id)
        self.management_require(sessions, "No connected player holds that instance", 409, "conflict")
        before, after, changed = moderation.release_sessions(
            sessions, scene, operation="instance.evacuate", target=instance_id, **arguments)
        return before, {**after, "instance_id": instance_id, "delivery_note": DELIVERY_NOTE}, changed

    # ---- capability description ---------------------------------------------
    def capabilities(self, actor, permissions):
        allowed = permissions[actor["role"]]
        return {"admin_actions": [{**action, "allowed": action["permission"] in allowed}
                                  for action in ADMIN_ACTIONS],
                "admin_actions_unsupported": [dict(row) for row in UNSUPPORTED_ACTIONS],
                "server_status_options": [SERVER_STATUS[code] for code in sorted(SERVER_STATUS)],
                "redirect_seconds": REDIRECT_SECONDS,
                "move_scenes": [{"id": key, "label": value} for key, value in SCENE_LABELS.items()]}


def derived(request_id):
    """Stable secondary history ID for a second mutation inside one request."""
    return hashlib.sha256(("secondary:" + request_id).encode("ascii")).hexdigest()[:32]


def spaced(name):
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name) if isinstance(name, str) else name


if set(NONMINI_PUBLIC_SCENES) != set(SCENE_LABELS):
    raise RuntimeError("Scene labels must cover exactly the reviewed public worlds")
