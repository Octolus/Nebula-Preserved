"""Managed lifecycle is opt-in, durable and never starts a process in backend tests."""
import json
import contextlib
import io
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from housing import HousingStore
from interaction_registry import InteractionRegistryPublisher
from service import Service
from state import Catalog, Store
from wire import ProtocolError, session_guid
import server


class ManagedInstanceTests(unittest.TestCase):
    def setUp(self):
        self.socket_guard = patch.object(socket, "socket", side_effect=AssertionError("sockets forbidden"))
        self.socket_guard.start()
        scratch = (Path(tempfile.gettempdir()) / "nebula-preserved-tests") / "work/offline-managed-instances"
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "preservation.sqlite3")
        self.service = Service(self.store, Catalog(BACKEND.parent / "protocol"),
                               core_test_profile="nonmini-semantic-v1", managed_instances=True)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()
        self.socket_guard.stop()

    def account(self, account_id, username=None):
        username = username or account_id
        self.service.dispatch("N2UserExist", "#".join(
            (username, "v72", "false", account_id, "nonce", "StandaloneWindows")))
        request_hash = (account_id.encode().hex() + "0" * 64)[:64]
        guid = session_guid(account_id, request_hash)
        self.service.dispatch("ChannelGUIDServlet", "#".join(
            (account_id, request_hash, "StandaloneWindows")))
        return guid

    def descriptor(self, instance_id, scene, owner="", players=0, port=28001):
        personal = bool(owner)
        value = dict(format_version=1, protocol_complete=False, game_ready=False,
            networking_parity="unproven", listening=True, listener_bound=True,
            readiness_scope="nonmini-semantic-v1", core_test_eligible=True,
            board_tables=0, darts_tables=0, heartbeat=time.time(), ip="127.0.0.1",
            bind="127.0.0.1", port=port, instance_id=instance_id, psidglobal=scene,
            players=players, maxusers=32, scene_registry_verified=True,
            housing_bound=personal, housing_owner=owner,
            interaction_bridge_required=True, interaction_registry_trusted=True)
        path = self.root / "instances" / instance_id / "instance-status.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")
        self.service.housing.export_bindings(self.root)
        InteractionRegistryPublisher(self.store, BACKEND.parent / "protocol").export(self.root)
        return value

    def presence(self, instance_id, scene, players):
        path = self.root / "instances" / instance_id / "instance-presence.json"
        path.write_text(json.dumps({"format_version": 1, "generation": time.time(),
            "instance_id": instance_id, "psidglobal": scene,
            "players": [{"guid": guid, "status": 0} for guid in players]}), encoding="utf-8")

    def load(self, guid, account, scene="Home", desired="", exclude=""):
        return self.service.dispatch("N2LoadSpace", "#".join(
            (guid, account, scene, "false", exclude, desired, "StandaloneWindows")))

    def poll(self, guid, account):
        return self.service.dispatch("N2SpaceLoading", "#".join(
            (guid, account, "StandaloneWindows")))

    def test_managed_mode_requires_explicit_semantic_profile_and_manual_mode_is_unchanged(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            server.parse_args(["--managed-instances"])
        parsed = server.parse_args(["--managed-instances", "--core-test-profile", "nonmini-semantic-v1"])
        self.assertTrue(parsed.managed_instances)
        other_root = self.root / "manual"
        manual_store = Store(other_root / "preservation.sqlite3")
        try:
            manual_store.account("manual", "Manual")
            manual_store.bind_session("manual", "a" * 32)
            manual = Service(manual_store, Catalog(BACKEND.parent / "protocol"))
            with self.assertRaises(ProtocolError) as raised:
                manual.dispatch("N2LoadSpace", "#".join(
                    ("a" * 32, "manual", "Login", "false", "", "", "StandaloneWindows")))
            self.assertEqual(raised.exception.status, 503)
            self.assertFalse((other_root / "desired-instances.json").exists())
        finally:
            manual_store.close()

    def test_new_managed_accounts_receive_distinct_stable_opaque_default_homes(self):
        first = self.account("owner-one")
        second = self.account("owner-two")
        rows = self.store.db.execute(
            "SELECT owner_ps4_id,instance_id,logical_space_key FROM housing_spaces ORDER BY owner_ps4_id").fetchall()
        self.assertEqual([row["owner_ps4_id"] for row in rows], ["owner-one", "owner-two"])
        self.assertTrue(all(row["logical_space_key"] == "Home" for row in rows))
        self.assertTrue(all(row["instance_id"].startswith("apt-") and len(row["instance_id"]) == 36 for row in rows))
        self.assertEqual(len({row["instance_id"] for row in rows}), 2)
        self.service.lifecycle.provision_account("owner-one")
        self.assertEqual(self.store.db.execute(
            "SELECT COUNT(*) FROM housing_spaces WHERE owner_ps4_id='owner-one'").fetchone()[0], 1)
        self.assertNotEqual(first, second)

    def test_preexisting_account_binding_is_adopted_without_automatic_new_grant(self):
        other = self.root / "grandfathered"
        store = Store(other / "preservation.sqlite3")
        store.account("old", "Old Account")
        housing = HousingStore(store, BACKEND.parent / "protocol")
        # A legacy safe ID may begin with apt- without being the exact managed
        # apt- plus 32 lowercase hex format.
        housing.bind_space("apt-home", "Home", "old")
        service = Service(store, Catalog(BACKEND.parent / "protocol"),
                          core_test_profile="nonmini-semantic-v1", managed_instances=True)
        try:
            self.assertIsNone(service.lifecycle.provision_account("old"))
            store.bind_session("old", "b" * 32)
            self.assertEqual(service.lifecycle.request_load(
                ("b" * 32, "old", "Home", "false", "", ""), store.session("b" * 32)),
                "b" * 32 + "#false#false")
            row = store.db.execute("SELECT * FROM managed_instances WHERE instance_id='apt-home'").fetchone()
            self.assertEqual((row["kind"], row["adopted_existing"]), ("personal", 1))
        finally:
            store.close()

    def test_native_pending_false_then_exact_ready_and_desired_snapshot(self):
        guid = self.account("owner")
        self.assertEqual(self.load(guid, "owner"), guid + "#false#false")
        self.assertEqual(self.poll(guid, "owner"), guid + "#false")
        desired = json.loads(self.service.lifecycle.export_desired(self.root).read_text())
        row = desired["instances"][0]
        self.assertEqual((row["kind"], row["psidglobal"], row["desired_state"]),
                         ("personal", "Home", "running"))
        self.assertEqual((row["active_demands"], row["pending_reservations"]), (1, 1))
        first_target = row["instance_id"]
        self.assertEqual(self.load(guid, "owner"), guid + "#false#false")
        self.assertEqual(self.store.db.execute(
            "SELECT COUNT(*) FROM instance_demands WHERE requester_guid=?", (guid,)).fetchone()[0], 1)
        self.assertEqual(self.store.db.execute(
            "SELECT instance_id FROM instance_demands WHERE requester_guid=?", (guid,)).fetchone()[0], first_target)
        self.descriptor(row["instance_id"], "Home", "owner")
        status_path = self.root / "instances" / row["instance_id"] / "instance-status.json"
        status = json.loads(status_path.read_text())
        status_path.write_text(json.dumps({**status, "interaction_registry_trusted": False}))
        self.assertEqual(self.poll(guid, "owner"), guid + "#false")
        status_path.write_text(json.dumps(status))
        self.assertEqual(self.poll(guid, "owner").split("#"),
                         [guid, "true", row["instance_id"], "Home", "127.0.0.1", "28001"])
        allocation = self.store.db.execute("SELECT * FROM allocations WHERE guid=?", (guid,)).fetchone()
        self.assertEqual(allocation["instance_id"], row["instance_id"])

    def test_same_owner_binding_creation_is_serialized_across_connections(self):
        self.store.account("race", "Race Owner")
        barrier = threading.Barrier(2)
        results, failures = [], []
        def bind():
            local = None
            try:
                local = Store(self.root / "preservation.sqlite3")
                housing = HousingStore(local, BACKEND.parent / "protocol")
                barrier.wait(timeout=10)
                results.append(housing.ensure_binding("race", "Home")["instance_id"])
            except BaseException as exc:
                failures.append(exc)
                barrier.abort()
            finally:
                if local is not None:
                    local.close()
        workers = [threading.Thread(target=bind, daemon=True) for _ in range(2)]
        for worker in workers: worker.start()
        for worker in workers: worker.join(timeout=15)
        self.assertFalse(any(worker.is_alive() for worker in workers), "Binding race did not finish")
        self.assertEqual(failures, [])
        self.assertEqual(len(results), 2)
        self.assertEqual(len(set(results)), 1)
        self.assertEqual(self.store.db.execute(
            "SELECT COUNT(*) FROM housing_spaces WHERE owner_ps4_id='race' AND logical_space_key='Home'").fetchone()[0], 1)

    def test_public_pending_reservations_scale_before_descriptor_count_changes(self):
        targets = []
        for index in range(33):
            account = f"public-{index:02d}"
            guid = self.account(account)
            self.assertEqual(self.load(guid, account, "Login"), guid + "#false#false")
            targets.append(self.store.db.execute(
                "SELECT instance_id FROM instance_demands WHERE requester_guid=?", (guid,)).fetchone()[0])
        self.assertEqual(len(set(targets[:32])), 1)
        self.assertNotEqual(targets[31], targets[32])
        self.assertTrue(targets[0].startswith("pub-") and targets[32].startswith("pub-"))

    def test_public_fallback_combines_reported_players_and_reservations(self):
        self.descriptor("shared-nexus", "Nexus", players=31)
        first_guid = self.account("first-public")
        self.load(first_guid, "first-public", "Login")
        first_target = self.store.db.execute(
            "SELECT instance_id FROM instance_demands WHERE requester_guid=?", (first_guid,)).fetchone()[0]
        self.assertEqual(first_target, "shared-nexus")
        self.load(first_guid, "first-public", "Login")
        self.assertEqual(self.store.db.execute(
            "SELECT COUNT(*) FROM instance_demands WHERE requester_guid=?", (first_guid,)).fetchone()[0], 1)
        second_guid = self.account("second-public")
        self.load(second_guid, "second-public", "Login")
        second_target = self.store.db.execute(
            "SELECT instance_id FROM instance_demands WHERE requester_guid=?", (second_guid,)).fetchone()[0]
        self.assertNotEqual(second_target, "shared-nexus")
        self.assertTrue(second_target.startswith("pub-"))

    def test_expired_public_demand_does_not_reuse_a_now_full_target(self):
        self.descriptor("expiring-nexus", "Nexus", players=0)
        guid = self.account("expired-public")
        self.load(guid, "expired-public", "Login")
        self.assertEqual(self.store.db.execute(
            "SELECT instance_id FROM instance_demands WHERE requester_guid=?", (guid,)).fetchone()[0],
            "expiring-nexus")
        with self.store.db:
            self.store.db.execute("UPDATE instance_demands SET expires_at=? WHERE requester_guid=?",
                                  (time.time() - 1, guid))
        path = self.root / "instances/expiring-nexus/instance-status.json"
        status = json.loads(path.read_text())
        path.write_text(json.dumps({**status, "players": 32, "heartbeat": time.time()}))
        self.assertEqual(self.load(guid, "expired-public", "Login"), guid + "#false#false")
        replacement = self.store.db.execute(
            "SELECT instance_id FROM instance_demands WHERE requester_guid=?", (guid,)).fetchone()[0]
        self.assertNotEqual(replacement, "expiring-nexus")
        self.assertTrue(replacement.startswith("pub-"))

    def test_expired_personal_demand_rechecks_capacity_before_reaccepting(self):
        guid = self.account("expired-owner")
        self.load(guid, "expired-owner")
        instance_id = self.store.db.execute(
            "SELECT instance_id FROM instance_demands WHERE requester_guid=?", (guid,)).fetchone()[0]
        self.descriptor(instance_id, "Home", "expired-owner", players=32)
        with self.store.db:
            self.store.db.execute("UPDATE instance_demands SET expires_at=? WHERE requester_guid=?",
                                  (time.time() - 1, guid))
        self.assertEqual(self.load(guid, "expired-owner"), guid + "#false#true")
        demand = self.store.db.execute(
            "SELECT instance_id,expires_at FROM instance_demands WHERE requester_guid=?", (guid,)).fetchone()
        self.assertEqual(demand["instance_id"], instance_id)
        self.assertLess(float(demand["expires_at"]), time.time())

    def test_personal_capacity_rejects_extra_before_accept_and_existing_pollers_complete(self):
        owner_guid = self.account("capacity-owner")
        self.load(owner_guid, "capacity-owner")
        instance_id = self.store.db.execute(
            "SELECT instance_id FROM instance_demands WHERE requester_guid=?", (owner_guid,)).fetchone()[0]
        self.descriptor(instance_id, "Home", "capacity-owner", players=0)
        self.poll(owner_guid, "capacity-owner")
        self.presence(instance_id, "Home", [owner_guid])
        status_path = self.root / "instances" / instance_id / "instance-status.json"
        status = json.loads(status_path.read_text())
        status_path.write_text(json.dumps({**status, "players": 1, "heartbeat": time.time()}))
        accepted = []
        for index in range(31):
            account = f"capacity-visitor-{index:02d}"
            guid = f"{index + 1:032x}"
            self.store.account(account, account)
            self.store.bind_session(account, guid)
            self.assertEqual(self.load(guid, account, "Home", owner_guid), guid + "#false#false")
            accepted.append((guid, account))
        extra_account, extra_guid = "capacity-extra", "f" * 32
        self.store.account(extra_account, extra_account)
        self.store.bind_session(extra_account, extra_guid)
        self.assertEqual(self.load(extra_guid, extra_account, "Home", owner_guid), extra_guid + "#false#true")
        self.assertIsNone(self.store.db.execute(
            "SELECT 1 FROM instance_demands WHERE requester_guid=?", (extra_guid,)).fetchone())
        for guid, account in accepted:
            self.assertEqual(self.poll(guid, account).split("#")[2], instance_id)

    def test_expired_personal_poll_cannot_reactivate_over_capacity_then_resumes(self):
        owner_guid = self.account("poll-owner")
        self.load(owner_guid, "poll-owner")
        instance_id = self.store.db.execute(
            "SELECT instance_id FROM instance_demands WHERE requester_guid=?", (owner_guid,)).fetchone()[0]
        self.descriptor(instance_id, "Home", "poll-owner", players=0)
        self.assertEqual(self.poll(owner_guid, "poll-owner").split("#")[1], "true")
        self.presence(instance_id, "Home", [owner_guid])

        late_account, late_guid = "poll-late", "a" * 32
        self.store.account(late_account, late_account)
        self.store.bind_session(late_account, late_guid)
        self.assertEqual(self.load(late_guid, late_account, "Home", owner_guid), late_guid + "#false#false")
        with self.store.db:
            self.store.db.execute("UPDATE instance_demands SET expires_at=? WHERE requester_guid=?",
                                  (time.time() - 1, late_guid))

        fresh = []
        for index in range(31):
            account, guid = f"poll-fresh-{index:02d}", f"{index + 1:032x}"
            self.store.account(account, account)
            self.store.bind_session(account, guid)
            self.assertEqual(self.load(guid, account, "Home", owner_guid), guid + "#false#false")
            fresh.append((guid, account))
        self.assertEqual(self.poll(late_guid, late_account), late_guid + "#false")
        self.assertLess(self.store.db.execute(
            "SELECT expires_at FROM instance_demands WHERE requester_guid=?", (late_guid,)).fetchone()[0],
            time.time())
        for guid, account in fresh:
            self.assertEqual(self.poll(guid, account).split("#")[1], "true")

        # The owner is exactly present at a now-full target. Neither a normal
        # repeat poll nor an expired-demand reactivation may double count it.
        self.assertEqual(self.poll(owner_guid, "poll-owner").split("#")[1], "true")
        with self.store.db:
            self.store.db.execute("UPDATE instance_demands SET expires_at=? WHERE requester_guid=?",
                                  (time.time() - 1, owner_guid))
        self.assertEqual(self.poll(owner_guid, "poll-owner").split("#")[1], "true")

        released_guid = fresh[-1][0]
        with self.store.db:
            self.store.db.execute("UPDATE instance_demands SET expires_at=? WHERE requester_guid=?",
                                  (time.time() - 1, released_guid))
        self.assertEqual(self.poll(late_guid, late_account).split("#")[1], "true")

    def test_expired_public_poll_cannot_reactivate_over_capacity_then_resumes(self):
        self.descriptor("poll-public", "Nexus", players=0)
        late_guid = self.account("public-poll-late")
        self.assertEqual(self.load(late_guid, "public-poll-late", "Login"), late_guid + "#false#false")
        with self.store.db:
            self.store.db.execute("UPDATE instance_demands SET expires_at=? WHERE requester_guid=?",
                                  (time.time() - 1, late_guid))

        fresh = []
        for index in range(32):
            account = f"public-poll-fresh-{index:02d}"
            guid = self.account(account)
            self.assertEqual(self.load(guid, account, "Login"), guid + "#false#false")
            target = self.store.db.execute(
                "SELECT instance_id FROM instance_demands WHERE requester_guid=?", (guid,)).fetchone()[0]
            self.assertEqual(target, "poll-public")
            fresh.append((guid, account))
        self.assertEqual(self.poll(late_guid, "public-poll-late"), late_guid + "#false")
        for guid, account in fresh:
            self.assertEqual(self.poll(guid, account).split("#")[1], "true")

        with self.store.db:
            self.store.db.execute("UPDATE instance_demands SET expires_at=? WHERE requester_guid=?",
                                  (time.time() - 1, fresh[-1][0]))
        self.assertEqual(self.poll(late_guid, "public-poll-late").split("#")[1], "true")

    def test_old_instance_presence_does_not_count_after_allocation_moves(self):
        guid = self.account("moved-presence")
        self.descriptor("old-public", "Nexus", players=0, port=28001)
        self.load(guid, "moved-presence", "Login")
        self.assertEqual(self.poll(guid, "moved-presence").split("#")[2], "old-public")
        self.presence("old-public", "Nexus", [guid])
        with self.store.db:
            self.store.db.execute(
                "UPDATE allocations SET instance_id='new-public',psidglobal='LeafPark' WHERE guid=?", (guid,))
        self.assertNotIn(guid, self.store.presence())

    def test_invited_visitor_is_pinned_to_exact_owner_and_revalidated(self):
        owner_guid = self.account("owner")
        visitor_guid = self.account("visitor")
        self.load(owner_guid, "owner")
        instance_id = self.store.db.execute(
            "SELECT instance_id FROM instance_demands WHERE requester_guid=?", (owner_guid,)).fetchone()[0]
        self.descriptor(instance_id, "Home", "owner")
        self.poll(owner_guid, "owner")
        self.presence(instance_id, "Home", [owner_guid])
        self.assertEqual(self.load(visitor_guid, "visitor", "Home", owner_guid),
                         visitor_guid + "#false#false")
        target = self.store.db.execute(
            "SELECT instance_id,desired_owner_guid FROM instance_demands WHERE requester_guid=?",
            (visitor_guid,)).fetchone()
        self.assertEqual(tuple(target), (instance_id, owner_guid))
        self.assertEqual(self.poll(visitor_guid, "visitor").split("#")[2], instance_id)
        self.store.bind_session("owner", "c" * 32)
        with self.store.db:
            self.store.db.execute("DELETE FROM allocations WHERE guid=?", (visitor_guid,))
            self.store.db.execute("UPDATE instance_demands SET state='pending' WHERE requester_guid=?", (visitor_guid,))
        self.assertEqual(self.poll(visitor_guid, "visitor"), visitor_guid + "#false")
        self.assertIsNone(self.store.db.execute("SELECT 1 FROM allocations WHERE guid=?", (visitor_guid,)).fetchone())

    def test_presence_keeps_running_then_expired_empty_world_stops(self):
        guid = self.account("owner")
        self.load(guid, "owner")
        instance_id = self.store.db.execute(
            "SELECT instance_id FROM instance_demands WHERE requester_guid=?", (guid,)).fetchone()[0]
        self.descriptor(instance_id, "Home", "owner")
        self.poll(guid, "owner")
        self.presence(instance_id, "Home", [guid])
        running = json.loads(self.service.lifecycle.export_desired(self.root).read_text())["instances"][0]
        self.assertEqual((running["desired_state"], running["active_allocations"]), ("running", 1))
        self.presence(instance_id, "Home", [])
        with self.store.db:
            self.store.db.execute("UPDATE instance_demands SET expires_at=? WHERE requester_guid=?",
                                  (time.time() - 1, guid))
        stopped = json.loads(self.service.lifecycle.export_desired(self.root).read_text())["instances"][0]
        self.assertEqual((stopped["desired_state"], stopped["active_demands"], stopped["active_allocations"]),
                         ("stopped", 0, 0))


if __name__ == "__main__": unittest.main()

