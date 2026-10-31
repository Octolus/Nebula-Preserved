"""Staff actions delivered through receivers the shipped client already has.

Covers permissions, reasons, audit/history, idempotency, offline/online targets
and the native reload path (scene drop -> N2LoadSpace -> N2SpaceLoading).
No sockets, processes or game clients are used.
"""
import json
from pathlib import Path
import socket
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from game_admin import ADMIN_ACTIONS, SCENE_LABELS, UNSUPPORTED_ACTIONS
from interaction_registry import InteractionRegistryPublisher
from management import PERMISSIONS, Management, ManagementError
from moderation import REDIRECT_SECONDS
from public_access import actor_scope
from service import Service
from state import Catalog, Store
from wire import ProtocolError, session_guid

TOKEN = b"temporary-game-admin-test-service-token-1234567"
ROLES = ("owner", "admin", "moderator")


class GameAdminBase(unittest.TestCase):
    managed = True

    def setUp(self):
        self.socket_guard = patch.object(socket, "socket", side_effect=AssertionError("sockets forbidden"))
        self.socket_guard.start()
        self.addCleanup(self.socket_guard.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "preservation.sqlite3")
        self.addCleanup(self.store.close)
        if self.managed:
            self.service = Service(self.store, Catalog(BACKEND.parent / "protocol"),
                                   core_test_profile="nonmini-semantic-v1", managed_instances=True)
        else:
            self.service = Service(self.store, Catalog(BACKEND.parent / "protocol"))
        self.manager = Management(self.store, self.service, TOKEN,
                                  [{"id": role, "role": role, "enabled": True} for role in ROLES])
        self.sequence = 0
        self.port = 28100

    # ---- helpers ---------------------------------------------------------
    def account(self, account_id, username=None):
        username = username or account_id
        self.service.dispatch("N2UserExist", "#".join(
            (username, "v72", "false", account_id, "nonce", "StandaloneWindows")))
        request_hash = (account_id.encode().hex() + "0" * 64)[:64]
        self.service.dispatch("ChannelGUIDServlet", "#".join((account_id, request_hash, "StandaloneWindows")))
        return session_guid(account_id, request_hash)

    def descriptor(self, instance_id, scene, players=0):
        self.port += 1
        if self.managed:
            value = dict(format_version=1, protocol_complete=False, game_ready=False,
                         networking_parity="unproven", listening=True, listener_bound=True,
                         readiness_scope="nonmini-semantic-v1", core_test_eligible=True,
                         board_tables=0, darts_tables=0, heartbeat=time.time(), ip="127.0.0.1",
                         bind="127.0.0.1", port=self.port, instance_id=instance_id, psidglobal=scene,
                         players=players, maxusers=32, scene_registry_verified=True,
                         housing_bound=False, housing_owner="",
                         interaction_bridge_required=True, interaction_registry_trusted=True)
        else:
            value = dict(format_version=1, protocol_complete=True, listening=True, heartbeat=time.time(),
                         ip="127.0.0.1", port=self.port, instance_id=instance_id, psidglobal=scene,
                         players=players, maxusers=32)
        path = self.root / "instances" / instance_id / "instance-status.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")
        if self.managed:
            self.service.housing.export_bindings(self.root)
            InteractionRegistryPublisher(self.store, BACKEND.parent / "protocol").export(self.root)

    def load(self, guid, account, scene="Nexus"):
        return self.service.dispatch("N2LoadSpace", "#".join(
            (guid, account, scene, "false", "", "", "StandaloneWindows")))

    def poll(self, guid, account):
        return self.service.dispatch("N2SpaceLoading", "#".join((guid, account, "StandaloneWindows")))

    def enter(self, guid, account, scene="Nexus"):
        self.assertEqual(self.load(guid, account, scene), guid + "#false#false")
        reply = self.poll(guid, account).split("#")
        self.assertEqual(reply[1], "true", reply)
        return reply

    def headers(self, actor="owner", key=None):
        self.sequence += 1
        return {"Authorization": "Bearer " + TOKEN.decode(), "X-Management-Actor": actor,
                "Idempotency-Key": key or "game-admin-test-" + str(self.sequence)}

    def command(self, tail, body, actor="owner", key=None):
        return self.manager.command(tail, body, self.headers(actor, key))

    def read(self, tail, actor="owner", query=None):
        return self.manager.read(tail, query or {}, self.manager.actor(self.headers(actor)))

    def allocation(self, guid):
        row = self.store.db.execute("SELECT instance_id,psidglobal FROM allocations WHERE guid=?", (guid,)).fetchone()
        return tuple(row) if row else None

    def assertDenied(self, status, call):
        # Management validation raises ManagementError; Moderation policy raises
        # ProtocolError. Management.handle maps both to the same HTTP status.
        with self.assertRaises((ManagementError, ProtocolError)) as caught:
            call()
        self.assertEqual(caught.exception.status, status, str(caught.exception))
        return caught.exception


class CapabilityContract(GameAdminBase):
    managed = False

    def test_role_table_is_hierarchical(self):
        self.assertLess(PERMISSIONS["moderator"], PERMISSIONS["admin"])
        self.assertLess(PERMISSIONS["admin"], PERMISSIONS["owner"])
        self.assertTrue({"moderation.move", "moderation.profile"} <= PERMISSIONS["moderator"])
        self.assertFalse({"moderation.server_status", "moderation.disconnect"} & PERMISSIONS["moderator"])
        self.assertTrue({"moderation.server_status", "moderation.disconnect"} <= PERMISSIONS["admin"])
        self.assertNotIn("players.staff", PERMISSIONS["admin"])

    def test_admin_actions_shape_reasons_and_per_role_allowed(self):
        ids = [action["id"] for action in ADMIN_ACTIONS]
        self.assertEqual(len(ids), len(set(ids)))
        all_permissions = set().union(*PERMISSIONS.values())
        for action in ADMIN_ACTIONS:
            self.assertTrue({"id", "label", "permission", "target", "path", "fields", "requires_reason",
                             "destructive", "live_only"} <= action.keys(), action["id"])
            self.assertIn(action["target"], ("player", "scene", "server"))
            self.assertIn(action["permission"], all_permissions)
            # Reasons are required exactly for moderation-type actions.
            self.assertEqual(action["requires_reason"],
                             action["permission"].startswith("moderation.") or action["permission"] == "players.staff")
            for field in action["fields"]:
                self.assertTrue({"name", "type", "label", "required"} <= field.keys())
        for role in ROLES:
            caps = self.read("capabilities", role)
            allowed = {row["id"]: row["allowed"] for row in caps["admin_actions"]}
            for action in ADMIN_ACTIONS:
                self.assertEqual(allowed[action["id"]], action["permission"] in PERMISSIONS[role])
        caps = self.read("capabilities", "moderator")
        self.assertFalse(caps["game_privilege_mutation_supported"])
        unsupported = {row["id"] for row in caps["admin_actions_unsupported"]}
        self.assertTrue({"teleport", "announcement_popup", "gm_vip_developer_flags", "freeze"} <= unsupported)
        self.assertEqual({row["id"] for row in UNSUPPORTED_ACTIONS} & set(ids), set())
        self.assertEqual([row["id"] for row in caps["move_scenes"]], list(SCENE_LABELS))

    def test_unknown_route_and_missing_reason(self):
        self.account("player-one")
        self.assertDenied(404, lambda: self.command("users/player-one/teleport", {"reason": "x"}))
        self.assertDenied(400, lambda: self.command("users/player-one/move", {"scene": "Nexus"}))
        self.assertDenied(400, lambda: self.command("moderation/server-status", {"status": "maintenance"}, "admin"))


class ServerStatus(GameAdminBase):
    managed = False

    def status(self, actor_account=None):
        call = lambda: self.service.dispatch("CheckServerStatusServlet", "Persona#nonce#StandaloneWindows")
        if actor_account is None:
            return call().split("#")[3]
        with actor_scope(actor_account):
            return call().split("#")[3]

    def test_native_status_codes_audit_history_and_idempotency(self):
        self.assertEqual(self.status(), "1")
        body = {"status": "maintenance", "reason": "Database migration"}
        result = self.command("moderation/server-status", body, "admin", key="status-key-0001")
        self.assertTrue(result["changed"])
        self.assertEqual((result["before"]["code"], result["after"]["code"]), (1, 0))
        self.assertEqual(self.status(), "0")
        replay = self.command("moderation/server-status", body, "admin", key="status-key-0001")
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["audit_id"], result["audit_id"])
        self.assertDenied(409, lambda: self.command("moderation/server-status",
                                                    {"status": "updating", "reason": "x"}, "admin",
                                                    key="status-key-0001"))
        self.command("moderation/server-status", {"status": "updating", "reason": "Patch"}, "owner")
        self.assertEqual(self.status(), "2")
        same = self.command("moderation/server-status", {"status": "updating", "reason": "Still"}, "owner")
        self.assertFalse(same["changed"])
        self.command("moderation/server-status", {"status": "normal", "reason": "Done"}, "admin")
        self.assertEqual(self.status(), "1")
        audit = [row[0] for row in self.store.db.execute(
            "SELECT operation FROM management_audit WHERE operation='moderation.server_status'")]
        events = [row[0] for row in self.store.db.execute(
            "SELECT operation FROM moderation_events WHERE operation='server.status'")]
        self.assertEqual(len(audit), 4)
        self.assertEqual(len(events), 4)
        self.assertEqual(self.read("moderation/server-status")["status"], "normal")

    def test_permissions_validation_and_linked_staff_bypass(self):
        self.assertDenied(403, lambda: self.command("moderation/server-status",
                                                    {"status": "maintenance", "reason": "x"}, "moderator"))
        self.assertDenied(400, lambda: self.command("moderation/server-status",
                                                    {"status": "closed", "reason": "x"}, "admin"))
        self.assertDenied(400, lambda: self.command("moderation/server-status",
                                                    {"status": "maintenance", "reason": "x", "extra": 1}, "admin"))
        self.account("staff-player")
        self.account("plain-player")
        self.command("operators/admin/player-link", {"account_id": "staff-player", "reason": "Link"})
        self.command("moderation/server-status", {"status": "maintenance", "reason": "Lockdown"}, "admin")
        self.assertEqual(self.status("plain-player"), "0")
        self.assertEqual(self.status("staff-player"), "1")
        # A disabled operator's linked account no longer bypasses.
        self.command("operators/admin", {"role": "admin", "enabled": False, "reason": "Off"})
        self.assertEqual(self.status("staff-player"), "0")


class ManagedRelocation(GameAdminBase):
    managed = True

    def setUp(self):
        super().setUp()
        self.descriptor("pub-nexus", "Nexus")
        self.descriptor("pub-beach", "Beach")
        self.guid = self.account("player-one", "PlayerOne")
        self.other = self.account("player-two", "PlayerTwo")

    def test_move_reloads_into_destination_without_revoking_session(self):
        self.enter(self.guid, "player-one")
        self.assertEqual(self.allocation(self.guid), ("pub-nexus", "Nexus"))
        result = self.command("users/player-one/move", {"scene": "Beach", "reason": "Stuck in wall"}, "moderator")
        self.assertTrue(result["changed"])
        self.assertEqual(result["operation"], "moderation.move")
        self.assertEqual(result["after"]["redirect_scene"], "Beach")
        self.assertEqual(result["before"]["sessions"],
                         [{"account_id": "player-one", "from_scene": "Nexus", "from_instance_id": "pub-nexus"}])
        # The scene authority snapshot now names no instance: the scene drops the peer.
        self.assertIsNone(self.allocation(self.guid))
        self.store.export_instance_accounts(self.root)
        accounts = json.loads((self.root / "instance-accounts.json").read_text(encoding="utf-8"))["accounts"]
        row = next(a for a in accounts if a["ps4_id"] == "player-one")
        self.assertEqual(row["allocated_instance_id"], "")
        # Not a kick: the GUID remains current and admitted.
        self.assertEqual(self.store.current_guid("player-one"), self.guid)
        live = self.read("users/player-one/live")
        self.assertFalse(live["in_world"])
        # Native reload asks for its current world; the reply names the destination.
        self.assertEqual(self.load(self.guid, "player-one", "Nexus"), self.guid + "#false#false")
        ready = self.poll(self.guid, "player-one").split("#")
        self.assertEqual(ready[1:4], ["true", "pub-beach", "Beach"])
        # One-shot: a later voluntary journey is not hijacked.
        self.assertEqual(self.load(self.guid, "player-one", "Nexus"), self.guid + "#false#false")
        self.assertEqual(self.poll(self.guid, "player-one").split("#")[2:4], ["pub-nexus", "Nexus"])

    def test_return_to_nexus_audit_history_and_replay(self):
        self.enter(self.guid, "player-one", "Beach")
        body = {"scene": "Nexus", "reason": "Harassing players"}
        first = self.command("users/player-one/move", body, "moderator", key="move-key-00001")
        replay = self.command("users/player-one/move", body, "moderator", key="move-key-00001")
        self.assertTrue(replay["replayed"])
        self.assertEqual(first["request_id"], replay["request_id"])
        audit = self.store.db.execute("SELECT * FROM management_audit WHERE request_id=?",
                                      (first["request_id"],)).fetchone()
        self.assertEqual((audit["operation"], audit["target_id"], audit["actor_role"]),
                         ("moderation.move", "player-one", "moderator"))
        event = self.store.db.execute("SELECT * FROM moderation_events WHERE request_id=?",
                                      (first["request_id"],)).fetchone()
        self.assertEqual((event["operation"], event["reason"]), ("move", "Harassing players"))
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM moderation_events WHERE operation='move'")
                         .fetchone()[0], 1)
        history = self.read("users/player-one/audit")["items"]
        self.assertEqual(history[0]["operation"], "moderation.move")
        self.assertEqual(self.load(self.guid, "player-one", "Beach"), self.guid + "#false#false")
        self.assertEqual(self.poll(self.guid, "player-one").split("#")[3], "Nexus")

    def test_offline_unknown_and_invalid_targets(self):
        self.assertDenied(409, lambda: self.command("users/player-one/move",
                                                    {"scene": "Nexus", "reason": "x"}))
        self.assertDenied(404, lambda: self.command("users/nobody/move", {"scene": "Nexus", "reason": "x"}))
        self.enter(self.guid, "player-one")
        for scene in ("Home", "Atlantis", "", 5):
            self.assertDenied(400, lambda: self.command("users/player-one/move", {"scene": scene, "reason": "x"}))
        self.assertDenied(400, lambda: self.command("users/player-one/move", {"reason": "x"}))
        self.assertEqual(self.allocation(self.guid), ("pub-nexus", "Nexus"))
        # A kicked (revoked) session no longer counts as connected.
        self.command("users/player-one/kick", {"reason": "Kick"})
        self.assertDenied(409, lambda: self.command("users/player-one/move", {"scene": "Nexus", "reason": "x"}))

    def test_reload_without_redirect_and_redirect_expiry(self):
        self.enter(self.guid, "player-one", "Beach")
        result = self.command("users/player-one/move", {"scene": None, "reason": "Refresh label"})
        self.assertIsNone(result["after"]["redirect_scene"])
        self.assertEqual(self.load(self.guid, "player-one", "Beach"), self.guid + "#false#false")
        self.assertEqual(self.poll(self.guid, "player-one").split("#")[3], "Beach")
        self.command("users/player-one/move", {"scene": "Nexus", "reason": "Relocate"})
        live = self.read("users/player-one/live")
        self.assertFalse(live["in_world"])
        clock = self.store.moderation.clock
        self.store.moderation.clock = lambda: clock() + REDIRECT_SECONDS + 1
        self.assertEqual(self.load(self.guid, "player-one", "Beach"), self.guid + "#false#false")
        self.assertEqual(self.poll(self.guid, "player-one").split("#")[3], "Beach")

    def test_live_read_scenes_and_pending_redirect(self):
        self.enter(self.guid, "player-one")
        avatar = self.root / "instances" / "pub-nexus" / "instance-avatar-state.json"
        avatar.write_text(json.dumps({"format_version": 1, "generation": time.time(), "instance_id": "pub-nexus",
                                      "psidglobal": "Nexus", "listening": True, "avatars": [
                                          {"guid": self.guid, "ps4_id": "player-one", "net_id": 3, "connected": True,
                                           "announced": True, "in_wardrobe": False,
                                           "position": {"x": 1.5, "y": 2.0, "z": -3.0},
                                           "position_updated_at": time.time()}]}), encoding="utf-8")
        live = self.read("users/player-one/live", "moderator")
        self.assertTrue(live["in_world"])
        self.assertEqual((live["scene"], live["scene_label"], live["instance_id"]), ("Nexus", "Nexus", "pub-nexus"))
        self.assertEqual(live["position_source"], "scene_live")
        self.assertEqual((live["position"]["x"], live["position"]["z"]), (1.5, -3.0))
        self.assertTrue(live["connected"] and live["announced"])
        self.assertIsNone(live["pending_redirect"])
        scenes = {row["id"]: row for row in self.read("moderation/scenes")["items"]}
        self.assertEqual(set(scenes), set(SCENE_LABELS))
        self.assertTrue(all(row["available"] for row in scenes.values()))  # launched on demand
        self.assertEqual(scenes["LeafPark"]["label"], "Leaf Park")
        instances = {row["instance_id"]: row for row in self.read("moderation/instances")["items"]}
        self.assertEqual(instances["pub-nexus"]["allocated_players"], 1)
        offline = self.read("users/player-two/live")
        self.assertFalse(offline["in_world"])
        self.assertIsNone(offline["scene"])

    def test_hierarchy_protects_linked_operator_accounts(self):
        self.enter(self.guid, "player-one")
        self.command("operators/admin/player-link", {"account_id": "player-one", "reason": "Staff account"})
        self.assertDenied(403, lambda: self.command("users/player-one/move", {"scene": "Beach", "reason": "x"},
                                                    "moderator"))
        self.assertDenied(403, lambda: self.command("users/player-one/clear-profile", {"reason": "x"}, "admin"))
        self.assertEqual(self.allocation(self.guid), ("pub-nexus", "Nexus"))
        self.command("users/player-one/move", {"scene": "Beach", "reason": "Owner may"}, "owner")
        self.assertIsNone(self.allocation(self.guid))

    def test_disconnect_all_and_evacuate_instance(self):
        self.enter(self.guid, "player-one")
        self.enter(self.other, "player-two", "Beach")
        self.assertDenied(403, lambda: self.command("moderation/disconnect-all", {"scene": None, "reason": "x"},
                                                    "moderator"))
        self.assertDenied(409, lambda: self.command("moderation/instances/pub-missing/evacuate",
                                                    {"reason": "x"}, "admin"))
        self.assertDenied(400, lambda: self.command("moderation/instances/bad%20id/evacuate",
                                                    {"reason": "x"}, "admin"))
        result = self.command("moderation/instances/pub-beach/evacuate", {"reason": "World broken"}, "admin")
        self.assertEqual(result["after"]["redirect_scene"], "Nexus")
        self.assertEqual(result["after"]["released"], 1)
        self.assertEqual(self.allocation(self.guid), ("pub-nexus", "Nexus"))
        self.assertIsNone(self.allocation(self.other))
        self.assertEqual(self.load(self.other, "player-two", "Beach"), self.other + "#false#false")
        self.assertEqual(self.poll(self.other, "player-two").split("#")[3], "Nexus")
        everyone = self.command("moderation/disconnect-all", {"scene": None, "reason": "Restart worlds"}, "admin")
        self.assertEqual(everyone["after"]["released"], 2)
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM allocations").fetchone()[0], 0)
        empty = self.command("moderation/disconnect-all", {"scene": "Nexus", "reason": "Nobody left"}, "owner")
        self.assertFalse(empty["changed"])

    def test_maintenance_lockdown_reaches_reloading_players(self):
        self.enter(self.guid, "player-one")
        self.command("moderation/server-status", {"status": "maintenance", "reason": "Lockdown"}, "admin")
        self.command("moderation/disconnect-all", {"scene": None, "reason": "Lockdown"}, "admin")
        # NETGcloudLogin.LoadSpace checks status before N2LoadSpace: 0 -> maintenance scene.
        reply = self.service.dispatch("CheckServerStatusServlet", "PlayerOne#n#StandaloneWindows")
        self.assertEqual(reply.split("#")[3], "0")


class ProfileText(GameAdminBase):
    managed = False

    def label(self, viewer_guid, viewer, target_guid):
        reply = self.service.dispatch("PlayerLabelInfoServlet", "#".join(
            (viewer_guid, viewer, target_guid, "StandaloneWindows"))).split("#")
        return json.loads(reply[4])

    def test_clear_status_and_mood_offline_with_history(self):
        guid = self.account("player-one")
        viewer = self.account("player-two")
        self.store.save_preference("player-one", "status", "offensive words")
        self.store.save_preference("player-one", "mood", "7")
        before = self.label(viewer, "player-two", guid)
        self.assertEqual((before["status"], before["mood"]), ("offensive words", "7"))
        result = self.command("users/player-one/clear-profile", {"reason": "Offensive status"}, "moderator")
        self.assertEqual(result["before"], {"mood": "7", "status": "offensive words"})
        self.assertEqual(result["after"], {"mood": "0", "status": "", "reconnected": False})
        after = self.label(viewer, "player-two", guid)
        self.assertEqual((after["status"], after["mood"]), ("", "0"))
        again = self.command("users/player-one/clear-profile", {"fields": ["status"], "reason": "Again"})
        self.assertFalse(again["changed"])
        event = self.store.db.execute("SELECT operation FROM moderation_events WHERE request_id=?",
                                      (result["request_id"],)).fetchone()
        self.assertEqual(event[0], "profile.clear")

    def test_validation_and_permissions(self):
        self.account("player-one")
        for bad in (["name"], [], ["status", "status"], "status"):
            self.assertDenied(400, lambda: self.command("users/player-one/clear-profile",
                                                        {"fields": bad, "reason": "x"}))
        self.assertDenied(400, lambda: self.command("users/player-one/clear-profile",
                                                    {"reconnect": "yes", "reason": "x"}))
        self.assertDenied(400, lambda: self.command("users/player-one/clear-profile", {}))
        self.assertDenied(404, lambda: self.command("users/nobody/clear-profile", {"reason": "x"}))

    def test_reconnect_option_releases_online_player(self):
        self.descriptor("nexus-a", "Nexus")
        guid = self.account("player-one")
        self.enter(guid, "player-one")
        result = self.command("users/player-one/clear-profile", {"reconnect": True, "reason": "Refresh"})
        self.assertTrue(result["after"]["reconnected"])
        self.assertIsNone(self.allocation(guid))
        events = [row[0] for row in self.store.db.execute(
            "SELECT operation FROM moderation_events ORDER BY event_id")]
        self.assertEqual(events[-2:], ["profile.clear", "move"])


class ManualRelocation(GameAdminBase):
    managed = False

    def test_manual_mode_requires_running_destination(self):
        self.descriptor("nexus-a", "Nexus")
        guid = self.account("player-one")
        self.enter(guid, "player-one")
        scenes = {row["id"]: row["available"] for row in self.read("moderation/scenes")["items"]}
        self.assertEqual(scenes, {scene: scene == "Nexus" for scene in SCENE_LABELS})
        self.assertDenied(409, lambda: self.command("users/player-one/move", {"scene": "Beach", "reason": "x"}))
        self.descriptor("beach-a", "Beach")
        self.command("users/player-one/move", {"scene": "Beach", "reason": "Relocate"})
        self.assertEqual(self.load(guid, "player-one", "Nexus"), guid + "#false#false")
        self.assertEqual(self.allocation(guid), ("beach-a", "Beach"))
        self.assertEqual(self.poll(guid, "player-one").split("#")[2:4], ["beach-a", "Beach"])

    def test_banned_session_reload_gets_native_ban_branch(self):
        self.descriptor("nexus-a", "Nexus")
        guid = self.account("player-one")
        self.enter(guid, "player-one")
        self.command("users/player-one/ban", {"reason": "Cheating"}, "moderator")
        # The client's automatic reload after the drop receives isBanned=true (UserBanned scene).
        self.assertEqual(self.load(guid, "player-one", "Nexus"), guid + "#true#false")


if __name__ == "__main__":
    unittest.main()
