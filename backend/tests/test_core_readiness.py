"""Bilateral Nexus test eligibility; no listener or network may run."""
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
from allocation import InstanceDirectory, validation_profile
from service import Service
from state import Catalog, Store
from wire import ProtocolError
import server


class CoreReadiness(unittest.TestCase):
    def setUp(self):
        self.guard = patch.object(socket, "socket", side_effect=AssertionError("No sockets in eligibility checks"))
        self.guard.start()
        scratch = (Path(tempfile.gettempdir()) / "nebula-preserved-tests") / "work/offline-core-readiness-tests"
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.root = Path(self.temp.name)
        self.directory = InstanceDirectory(self.root, core_test_profile="nexus-core-v1")

    def tearDown(self):
        self.temp.cleanup()
        self.guard.stop()

    def descriptor(self, name="nexus-test", port=28000, **overrides):
        value = dict(format_version=1, protocol_complete=False, game_ready=False, networking_parity="unproven",
                     listening=True, listener_bound=True, readiness_scope="nexus-core-v1", core_test_eligible=True,
                     board_tables=0, darts_tables=0, heartbeat=time.time(), ip="127.0.0.1", bind="0.0.0.0",
                     port=port, instance_id=name, psidglobal="Nexus", players=0, maxusers=32)
        value.update(overrides)
        path = self.root / "instances" / name / "instance-status.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")
        return value

    def test_both_component_opt_ins_are_required_and_parity_remains_false(self):
        value = self.descriptor()
        self.assertIsNone(InstanceDirectory(self.root).ready())
        actual = self.directory.require("Nexus")
        self.assertFalse(actual["protocol_complete"])
        self.assertFalse(actual["game_ready"])
        self.assertEqual(actual["readiness_scope"], "nexus-core-v1")
        for overrides in ({"readiness_scope": "closed"}, {"readiness_scope": "other"}, {"core_test_eligible": False}):
            self.descriptor(**overrides)
            self.assertIsNone(self.directory.ready())
        self.assertFalse(value["protocol_complete"])

    def test_listener_and_strict_metadata_are_required(self):
        for key, invalid in (("listener_bound", [False, 1, "true", None]),
                             ("listening", [False, 1, "true", None]),
                             ("core_test_eligible", [False, 1, "true", None]),
                             ("game_ready", [True, 0, None]),
                             ("protocol_complete", [None, 0]),
                             ("networking_parity", ["proven", None])):
            for value in invalid:
                with self.subTest(key=key, value=value):
                    self.descriptor(**{key: value})
                    self.assertIsNone(self.directory.ready())

    def test_scope_does_not_admit_other_scenes_or_minigame_tables(self):
        for overrides in ({"psidglobal": "LeafPark"}, {"psidglobal": "nexus"}, {"psidglobal": "Bowling"},
                          {"board_tables": 1}, {"darts_tables": 3}, {"board_tables": False},
                          {"darts_tables": None}, {"board_tables": "0"}):
            with self.subTest(overrides=overrides):
                self.descriptor(**overrides)
                self.assertEqual(self.directory.all_ready(), [])

    def test_scope_preserves_fresh_host_count_port_and_duplicate_validation(self):
        for overrides in ({"heartbeat": time.time()-16}, {"heartbeat": time.time()+60},
                          {"ip": "192.0.2.10"}, {"port": True}, {"players": 33},
                          {"maxusers": 64}, {"format_version": True}):
            with self.subTest(overrides=overrides):
                self.descriptor(**overrides)
                self.assertIsNone(self.directory.ready())
        self.descriptor()
        self.descriptor("second", port=28000)
        self.assertEqual(self.directory.all_ready(), [])
        self.descriptor("second", port=28001)
        self.assertEqual([x["instance_id"] for x in self.directory.all_ready()], ["nexus-test", "second"])

    def test_cli_and_backend_accept_only_the_named_scope_without_starting_maintenance(self):
        args = server.parse_args(["--core-test-profile", "nexus-core-v1"])
        self.assertFalse(args.listen)
        self.assertEqual(args.core_test_profile, "nexus-core-v1")
        self.assertIsNone(server.parse_args([]).core_test_profile)
        for value in (True, False, "", "all", "Nexus", "nexus-core-v2"):
            with self.assertRaises(ValueError): validation_profile(value)
        backend = server.Backend(self.root, core_test_profile="nexus-core-v1")
        try:
            self.assertEqual(backend.service.instances.core_test_profile, "nexus-core-v1")
            self.assertIsNone(backend.maintenance_task)
        finally:
            backend.log.close()
            backend.store.close()

    def test_actual_http_allocation_uses_scoped_candidate_and_native_envelopes(self):
        self.descriptor()
        store = Store(self.root / "preservation.sqlite3")
        try:
            guid = "e" * 32
            store.account("offline-core", "Core Fixture")
            store.bind_session("offline-core", guid)
            service = Service(store, Catalog(BACKEND.parent / "protocol"))
            request = guid + "#offline-core#Login#false###StandaloneWindows"
            with self.assertRaises(ProtocolError): service.dispatch("N2LoadSpace", request)
            service.instances.core_test_profile = "nexus-core-v1"
            self.assertEqual(service.dispatch("N2LoadSpace", request), guid + "#false#false")
            fields = service.dispatch("N2SpaceLoading", guid + "#offline-core#StandaloneWindows").split("#")
            self.assertEqual(fields, [guid, "true", "nexus-test", "Nexus", "127.0.0.1", "28000"])
            exported = store.export_instance_accounts(self.root)
            snapshot = json.loads((self.root / "instance-accounts.json").read_text())
            self.assertEqual(snapshot["accounts"][0]["allocated_instance_id"], "nexus-test")
            self.descriptor(listener_bound=False)
            self.assertEqual(service.dispatch("N2SpaceLoading", guid + "#offline-core#StandaloneWindows"), guid + "#false")
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()

