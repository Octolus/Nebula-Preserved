"""Pure staged checks for the closed two-account local test identity gate."""
import json
import contextlib
import io
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parents[1]
PROTOCOL = BACKEND.parent / "protocol"
sys.path.insert(0, str(BACKEND))

import server
from service import Service
from state import Catalog, Store
from test_identity import FIXED_TEST_IDENTITIES
from wire import ProtocolError


class EmptyResources:
    def list(self, _ps4_id):
        return []


class LocalTestIdentityGateTests(unittest.TestCase):
    def setUp(self):
        self.sockets = patch.object(socket, "socket", side_effect=AssertionError("sockets forbidden"))
        self.sockets.start()
        scratch = Path(tempfile.gettempdir()) / "nebula-preserved-tests"
        scratch.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()
        self.sockets.stop()

    def service(self, enabled):
        store = Store(self.root / "state.sqlite3", local_test_identities=enabled)
        return store, Service(store, Catalog(PROTOCOL))

    def test_cli_allows_boolean_only_on_concrete_private_endpoints(self):
        for bind, advertise in (("127.0.0.1", "127.0.0.1"),
                                ("10.1.2.3", "192.168.2.4"),
                                ("172.16.0.1", "172.31.255.254")):
            parsed = server.parse_args(["--local-test-identities", "--bind", bind,
                                        "--advertise-ip", advertise])
            self.assertTrue(parsed.local_test_identities)
        for bind, advertise in (("0.0.0.0", "127.0.0.1"),
                                ("127.0.0.1", "203.0.113.4"),
                                ("169.254.1.2", "127.0.0.1")):
            with self.subTest(bind=bind, advertise=advertise), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    server.parse_args(["--local-test-identities", "--bind", bind,
                                       "--advertise-ip", advertise])
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            server.parse_args(["--local-test-identities", "--local-test-identity-id", "anything"])

    def test_direct_backend_construction_cannot_bypass_endpoint_gate(self):
        with self.assertRaises(ValueError):
            server.Backend(self.root, bind="0.0.0.0", advertise_ip="127.0.0.1",
                           local_test_identities=True)
        with self.assertRaises(ValueError):
            server.Backend(self.root, bind="127.0.0.1", advertise_ip="198.51.100.7",
                           local_test_identities=True)

    def test_direct_constructors_reject_non_boolean_before_filesystem_writes(self):
        for value in ("false", "true", 0, 1, None):
            store_path = self.root / ("store-" + str(value)) / "state.sqlite3"
            with self.subTest(component="Store", value=value), self.assertRaises(TypeError):
                Store(store_path, local_test_identities=value)
            self.assertFalse(store_path.parent.exists())
            backend_path = self.root / ("backend-" + str(value))
            with self.subTest(component="Backend", value=value), self.assertRaises(TypeError):
                server.Backend(backend_path, local_test_identities=value)
            self.assertFalse(backend_path.exists())

    def test_normal_mode_rejects_every_reserved_creation_and_session_route(self):
        identity, name = next(iter(FIXED_TEST_IDENTITIES.items()))
        store, service = self.service(False)
        try:
            calls = (
                ("STMGetUserInfo", "#" + identity),
                ("N2UserExist", "#".join((name, "v72", "false", identity, "nonce"))),
                ("UserExistsServlet", "#".join((identity, "v72", "false", identity, "nonce"))),
                ("N2AddUser", "#".join((identity, name, "mail", "false", "region", "1"))),
                ("ChannelGUIDServlet", identity + "#" + "a" * 64),
            )
            for command, body in calls:
                with self.subTest(command=command), self.assertRaises(ProtocolError) as raised:
                    service.dispatch(command, body + "#StandaloneWindows")
                self.assertEqual(raised.exception.status, 403)
            self.assertIsNone(store.db.execute(
                "SELECT 1 FROM profiles WHERE ps4_id=?", (identity,)).fetchone())
        finally:
            store.close()

    def test_enabled_mode_accepts_only_two_exact_pairs_and_regular_accounts(self):
        store, service = self.service(True)
        try:
            for index, (identity, name) in enumerate(FIXED_TEST_IDENTITIES.items(), 1):
                self.assertTrue(service.dispatch(
                    "STMGetUserInfo", "#".join(("", identity, "StandaloneWindows"))).startswith("OK#"))
                self.assertTrue(service.dispatch("N2UserExist", "#".join(
                    (name, "v72", "false", identity, "nonce", "StandaloneWindows"))).startswith(identity + "#"))
                request_hash = str(index) * 64
                self.assertEqual(service.dispatch("ChannelGUIDServlet", "#".join(
                    (identity, request_hash, "StandaloneWindows"))), "true#")
                self.assertEqual(store.account(identity)["username"], name)
            self.assertEqual(store.account("ordinary-local-account", "Ordinary")["username"], "Ordinary")
            invalid = (
                ("local-preservation-test-3", "[TEST] Preservation Client 3"),
                ("LOCAL-preservation-test-1", "Ordinary-looking name"),
                ("local-preservation-test-1-extra", "[TEST] Preservation Client 1"),
                ("local-preservation-test-1", "[TEST] Preservation Client 2"),
                ("ordinary", "[TEST] Preservation Client 1"),
            )
            for identity, name in invalid:
                with self.subTest(identity=identity, name=name), self.assertRaises(ProtocolError):
                    store.account(identity, name)
        finally:
            store.close()

    def test_reopen_normal_blocks_old_session_lookup_and_filters_snapshots(self):
        identity, name = next(iter(FIXED_TEST_IDENTITIES.items()))
        enabled = Store(self.root / "state.sqlite3", local_test_identities=True)
        enabled.account(identity, name)
        enabled.account("ordinary", "Ordinary")
        enabled.bind_session(identity, "b" * 32)
        with enabled.db:
            enabled.db.execute("INSERT INTO relations VALUES(?,?,?,'friend')",
                               (identity, "Ordinary", "StandaloneWindows"))
            enabled.db.execute("INSERT INTO relations VALUES(?,?,?,'friend')",
                               ("ordinary", name, "StandaloneWindows"))
            # Simulate a pre-gate database row that has an ordinary account ID
            # but a reserved display-name prefix. Its outbound relation must
            # not survive normal-mode publication.
            enabled.db.execute("INSERT INTO profiles VALUES(?,?,?,?,?)",
                               ("ordinary-spoof", "[TeSt] Preservation Client Spoof",
                                "StandaloneWindows", "MALE", 0.0))
            enabled.db.execute("INSERT INTO profile_state(ps4_id) VALUES(?)", ("ordinary-spoof",))
            enabled.db.execute("INSERT INTO relations VALUES(?,?,?,'friend')",
                               ("ordinary-spoof", "Ordinary Target", "StandaloneWindows"))
        enabled.close()

        normal = Store(self.root / "state.sqlite3")
        normal.instance_resources = EmptyResources()
        try:
            with self.assertRaises(ProtocolError) as raised:
                normal.session("b" * 32)
            self.assertEqual(raised.exception.status, 403)
            with self.assertRaises(ProtocolError):
                normal.find_username(name, "StandaloneWindows")
            normal.export_instance_accounts(self.root)
            accounts = json.loads((self.root / "instance-accounts.json").read_text())["accounts"]
            relations = json.loads((self.root / "instance-relations.json").read_text())["relations"]
            self.assertEqual(accounts, [])
            self.assertEqual(relations, [])
        finally:
            normal.close()


if __name__ == "__main__":
    unittest.main()

