"""Offline HTTP diagnostics, privacy and bounded log rotation."""
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import socket
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import diagnostic_logging
from diagnostic_logging import (LOG_BACKUPS, MAX_LOG_BYTES, MAX_RECORD_BYTES, RotatingJSONLog, Throttle,
                                begin_request, end_request, missing_data, safe_id, safe_stack)
from enrollment import EnrollmentError
from server import Backend
from public_access import migrate
from state import Store
from wire import ProtocolError, decrypt, encrypt


def drive(coroutine):
    try:
        coroutine.send(None)
    except StopIteration as stopped:
        return stopped.value
    raise AssertionError("Offline adapter unexpectedly yielded")


def request(path="UnknownHandler", *, method="GET", query=None, headers=None):
    return SimpleNamespace(path="/" + path, method=method,
        query={"data": encrypt("synthetic-private-body#StandaloneWindows")} if query is None else query,
        headers=headers or {}, content_type="application/json")


class Logging(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.enterContext(patch.object(socket, "socket", side_effect=AssertionError("No sockets")))
        self.enterContext(patch.object(socket, "create_connection", side_effect=AssertionError("No network")))
        self.stdout, self.stderr = io.StringIO(), io.StringIO()
        self.enterContext(redirect_stdout(self.stdout))
        self.enterContext(redirect_stderr(self.stderr))
        self.enterContext(patch.object(diagnostic_logging, "THROTTLE", Throttle()))
        self.addCleanup(diagnostic_logging.configure_file_sink, None)

    def emitted(self, name=None):
        events = [json.loads(line) for line in self.stdout.getvalue().splitlines()]
        return [event for event in events if name is None or event["event"] == name]

    def backend(self, public=False):
        state_dir = Path(self.temp.name) / ("public" if public else "private")
        if public:
            state_dir.mkdir()
            store = Store(state_dir / "preservation.sqlite3")
            try:
                migrate(store.db)
            finally:
                store.close()
        backend = Backend(state_dir, public_access=public)
        backend.log.close()
        backend.log = io.StringIO()
        backend.publish_state = lambda: None
        self.addCleanup(backend.store.close)
        self.addCleanup(backend.log.close)
        return backend

    def event(self, backend):
        events = [json.loads(line) for line in backend.log.getvalue().splitlines()]
        event = events[-1]
        self.assertRegex(event["request_id"], "^[0-9a-f]{16}$")
        self.assertGreaterEqual(event["elapsed_ms"], 0)
        self.assertIn("status", event)
        return event

    def test_rotation_remains_bounded_and_reopens_without_losing_active_log(self):
        path = Path(self.temp.name) / "requests.jsonl"
        log = RotatingJSONLog(path, max_bytes=MAX_RECORD_BYTES, backup_count=2)
        for number in range(180):
            log.write(json.dumps({"number": number, "padding": "x" * 1500}) + "\n")
        log.flush()
        log.close()
        log.close()
        files = list(path.parent.glob("requests.jsonl*"))
        self.assertEqual(len(files), 3)
        for file in files:
            self.assertLessEqual(file.stat().st_size, MAX_RECORD_BYTES)
            for line in file.read_text().splitlines():
                json.loads(line)
        reopened = RotatingJSONLog(path, max_bytes=MAX_RECORD_BYTES, backup_count=2)
        reopened.write('{"event":"reopened"}\n')
        reopened.close()
        self.assertIn('"number": 179', path.read_text())
        self.assertEqual(json.loads(path.read_text().splitlines()[-1]), {"event": "reopened"})
        with self.assertRaises(ValueError):
            reopened.write("closed")

    def test_default_limits_and_oversize_multiline_rejection(self):
        path = Path(self.temp.name) / "requests.jsonl"
        log = RotatingJSONLog(path)
        self.assertEqual((log.handler.maxBytes, log.handler.backupCount), (MAX_LOG_BYTES, LOG_BACKUPS))
        log.write("sensitive" * MAX_RECORD_BYTES)
        log.write("sensitive\nforged\n")
        log.close()
        self.assertNotIn("sensitive", path.read_text())
        self.assertEqual(len(path.read_text().splitlines()), 2)
        for kwargs in ({"max_bytes": 1}, {"backup_count": 0}, {"backup_count": 6}, {"max_bytes": True}):
            with self.assertRaises(ValueError):
                RotatingJSONLog(path, **kwargs)

    def test_bad_method_and_encryption_have_status_correlation_and_no_input(self):
        backend = self.backend()
        response = drive(backend.handle(request(method="POST")))
        self.assertEqual(response.status, 400)
        first = self.event(backend)
        self.assertEqual(first["error_type"], "request_shape")
        response = drive(backend.handle(request(query={"data": "credential-secret-invalid"})))
        self.assertEqual(response.status, 400)
        second = self.event(backend)
        self.assertEqual(second["error_type"], "encryption")
        self.assertNotEqual(first["request_id"], second["request_id"])
        self.assertNotIn("credential-secret-invalid", backend.log.getvalue())

    def test_unknown_handler_retains_encrypted_protocol_status_and_audit_detail(self):
        backend = self.backend()
        response = drive(backend.handle(request()))
        self.assertEqual(response.status, 501)
        self.assertEqual(decrypt(response.text), "ERROR")
        event = self.event(backend)
        self.assertEqual(event["error_type"], "ProtocolError")
        self.assertEqual(event["error"], "Route behavior has not been reconstructed")
        self.assertEqual(len(event["request_sha256"]), 64)
        self.assertNotIn("synthetic-private-body", backend.log.getvalue())

    def test_internal_exception_is_encrypted_500_with_safe_locations_only(self):
        backend = self.backend()
        async def fail(*args):
            local_secret = "private-exception-secret"
            raise RuntimeError(local_secret)
        with patch("server.dispatch_housing_atomic", fail):
            response = drive(backend.handle(request()))
        self.assertEqual(response.status, 500)
        self.assertEqual(decrypt(response.text), "ERROR")
        event = self.event(backend)
        self.assertEqual((event["error"], event["error_type"]), ("internal_error", "internal_error"))
        self.assertTrue(event["stack"])
        for frame in event["stack"]:
            self.assertEqual(set(frame), {"file", "function", "line"})
            self.assertNotIn("/", frame["file"])
            self.assertNotIn("\\", frame["file"])
        self.assertNotIn("private-exception-secret", backend.log.getvalue())
        self.assertNotIn("local_secret", backend.log.getvalue())

    def test_authenticated_real_account_hash_only_after_authentication(self):
        backend = self.backend(public=True)
        account = "76561198000000001"
        backend.store.account(account, "Private Player")
        authorization = backend.access.issue(account)
        response = drive(backend.handle(request(headers={"Authorization": authorization})))
        self.assertEqual(response.status, 501)
        event = self.event(backend)
        self.assertEqual(event["actor_ref"], hashlib.sha256(account.encode()).hexdigest()[:16])
        self.assertNotIn(account, backend.log.getvalue())
        self.assertNotIn(authorization, backend.log.getvalue())
        response = drive(backend.handle(request(headers={"Authorization": "invalid-secret"})))
        self.assertEqual(response.status, 403)
        self.assertNotIn("actor_ref", self.event(backend))
        self.assertNotIn("invalid-secret", backend.log.getvalue())

    def test_unsafe_path_is_replaced_with_fixed_label(self):
        backend = self.backend()
        path = "secret-name/" + "private" * 100
        response = drive(backend.handle(request(path=path, method="POST")))
        self.assertEqual(response.status, 400)
        self.assertEqual(self.event(backend)["command"], "invalid_route")
        self.assertNotIn("secret-name", backend.log.getvalue())

    def test_enrollment_disabled_method_rejection_and_internal_error_are_logged(self):
        backend = self.backend()
        response = drive(backend.handle(request("preservation/enroll", method="POST")))
        self.assertEqual(response.status, 404)
        self.assertEqual(self.event(backend)["error"], "registration_disabled")
        backend.enrollment = SimpleNamespace(register=lambda *_: None)
        response = drive(backend.handle(request("preservation/enroll")))
        self.assertEqual(response.status, 405)
        self.assertEqual(self.event(backend)["error"], "method_not_allowed")
        def reject(*_):
            raise EnrollmentError(429, "registration_rate_limited")
        backend.enrollment.register = reject
        response = drive(backend.handle(request("preservation/enroll", method="POST")))
        self.assertEqual(response.status, 429)
        self.assertEqual(self.event(backend)["error"], "registration_rate_limited")
        def fail(*_):
            raise RuntimeError("private-enrollment-error")
        backend.enrollment.register = fail
        response = drive(backend.handle(request("preservation/enroll", method="POST")))
        self.assertEqual(response.status, 500)
        self.assertEqual(self.event(backend)["error"], "internal_error")
        self.assertNotIn("private-enrollment-error", backend.log.getvalue())

    def test_unknown_route_is_distinct_stdout_event_with_hashed_actor_only(self):
        backend = self.backend(public=True)
        account = "76561198000000002"
        backend.store.account(account, "Private Player")
        authorization = backend.access.issue(account)
        response = drive(backend.handle(request("MissingFeatureServlet", headers={"Authorization": authorization})))
        self.assertEqual((response.status, decrypt(response.text)), (501, "ERROR"))
        [event] = self.emitted()
        expected = {"event": "unknown_route", "route": "MissingFeatureServlet", "status": 501,
                    "reason": "unknown_route", "message": "Route behavior has not been reconstructed",
                    "field_count": 1, "actor_ref": hashlib.sha256(account.encode()).hexdigest()[:16],
                    "request_id": self.event(backend)["request_id"]}
        self.assertEqual({key: event[key] for key in expected}, expected)
        self.assertGreaterEqual(event["elapsed_ms"], 0)
        for secret in (account, authorization, "synthetic-private-body", "Private Player"):
            self.assertNotIn(secret, self.stdout.getvalue())

    def test_protocol_error_reason_prefers_missing_data_code(self):
        backend = self.backend()
        def lookup(*_):
            missing_data("wardrobe_entitlement_unknown", item_id="ItemA_01")
            raise ProtocolError("Unknown local wardrobe entitlement", 404)
        with patch("server.dispatch_housing_atomic", lookup):
            response = drive(backend.handle(request("WardrobeOptionItemServlet")))
        self.assertEqual(response.status, 404)
        warning, failure = self.emitted()
        self.assertEqual((warning["event"], warning["reason"], warning["item_id"], warning["level"]),
                         ("missing_data", "wardrobe_entitlement_unknown", "ItemA_01", "warning"))
        self.assertEqual((failure["event"], failure["reason"], failure["status"]),
                         ("request_failed", "wardrobe_entitlement_unknown", 404))
        self.assertEqual(warning["request_id"], failure["request_id"])
        self.assertEqual(warning["route"], "WardrobeOptionItemServlet")
        with patch("server.dispatch_housing_atomic", lambda *_: (_ for _ in ()).throw(
                ProtocolError("Invalid wardrobe view"))):
            drive(backend.handle(request("WardrobeOptionItemServlet")))
        self.assertEqual(self.emitted("request_failed")[-1]["reason"], "invalid_request")

    def test_unhandled_exception_traceback_on_stderr_shares_request_id(self):
        backend = self.backend()
        async def fail(*args):
            raise RuntimeError("diagnostic detail")
        with patch("server.dispatch_housing_atomic", fail):
            response = drive(backend.handle(request()))
        self.assertEqual((response.status, decrypt(response.text)), (500, "ERROR"))
        [event] = self.emitted()
        self.assertEqual((event["event"], event["reason"], event["level"]), ("request_failed", "internal_error", "error"))
        self.assertNotIn("message", event)
        lines = self.stderr.getvalue().splitlines()
        self.assertTrue(lines)
        for line in lines:
            self.assertTrue(line.startswith(f"[request_id={event['request_id']}] "))
        self.assertIn("RuntimeError: diagnostic detail", self.stderr.getvalue())
        self.assertIn("Traceback", self.stderr.getvalue())
        with patch("server.dispatch_housing_atomic", fail):
            drive(backend.handle(request()))
        self.assertEqual(len(self.emitted("request_failed")), 2)

    def test_repeated_failures_are_throttled_per_actor_and_reason(self):
        backend = self.backend()
        now = [0.0]
        diagnostic_logging.THROTTLE.clock = lambda: now[0]
        for _ in range(5):
            drive(backend.handle(request(method="POST")))
        drive(backend.handle(request(query={"data": "invalid"})))
        self.assertEqual([event["reason"] for event in self.emitted()],
                         ["invalid_request_shape", "invalid_encrypted_request"])
        now[0] = 61
        drive(backend.handle(request(method="POST")))
        self.assertEqual(self.emitted()[-1]["suppressed"], 4)
        self.assertEqual(len(backend.log.getvalue().splitlines()), 7)

    def test_launcher_probe_keeps_exact_reply_and_is_not_a_failure(self):
        backend = self.backend()
        response = drive(backend.handle(request("launcher-probe", query={})))
        # patcher launcher::probe requires exactly this status and body.
        self.assertEqual((response.status, response.text), (400, "Expected encrypted GET request"))
        self.assertEqual(self.emitted(), [])
        [row] = [json.loads(line) for line in backend.log.getvalue().splitlines()]
        self.assertEqual((row["command"], row["status"], row["error_type"]), ("launcher_probe", 400, "launcher_probe"))

    def test_malformed_request_failure_names_the_path_but_never_the_query(self):
        backend = self.backend()
        drive(backend.handle(request("odd path/x.png", query={"q": "secret-value"})))
        [event] = self.emitted()
        self.assertEqual((event["reason"], event["message"]), ("invalid_request_shape", "GET /odd?path/x.png"))
        self.assertNotIn("secret-value", self.stdout.getvalue() + backend.log.getvalue())

    def test_missing_data_hooks_emit_only_inside_requests(self):
        backend = self.backend()
        with self.assertRaises(ProtocolError):
            backend.store.preset("76561198000000003", "MALE")
        self.assertEqual(self.stdout.getvalue(), "")
        token = begin_request("0123456789abcdef", "GetPresetServlet")
        try:
            for call in (lambda: backend.store.preset("76561198000000003", "MALE"),
                         lambda: backend.service.shop._offer("offer_missing"),
                         lambda: backend.service.catalog.resolve("NoSuchItem", "MALE", "HAT")):
                with self.assertRaises(ProtocolError):
                    call()
        finally:
            end_request(token)
        events = self.emitted("missing_data")
        self.assertEqual([event["reason"] for event in events],
                         ["preset_unavailable", "shop_offer_unknown", "catalog_item_unknown"])
        self.assertEqual(events[1]["offer_id"], "offer_missing")
        self.assertEqual((events[2]["item_id"], events[2]["category"]), ("NoSuchItem", "HAT"))
        self.assertTrue(all(event["request_id"] == "0123456789abcdef" for event in events))
        self.assertNotIn("actor_ref", events[0])

    def test_failures_are_mirrored_to_rotating_state_file(self):
        backend = self.backend()
        async def fail(*args):
            raise RuntimeError("diagnostic detail")
        with patch("server.dispatch_housing_atomic", fail):
            drive(backend.handle(request()))
        drive(backend.handle(request(method="POST")))
        sink = diagnostic_logging._file_sink
        self.assertEqual((sink.handler.maxBytes, sink.handler.backupCount), (MAX_LOG_BYTES, LOG_BACKUPS))
        self.assertIsNone(sink.handler.stream)
        path = Path(self.temp.name) / "private" / "logs" / "backend-failures.jsonl"
        events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([event["event"] for event in events], ["unhandled_exception", "request_failed", "request_failed"])
        self.assertIn("RuntimeError: diagnostic detail", events[0]["traceback"])
        self.assertEqual(events[0]["request_id"], events[1]["request_id"])
        self.assertEqual(events[1:], self.emitted())
        self.assertNotIn("synthetic-private-body", path.read_text(encoding="utf-8"))

    def test_throttle_bounds_keys_and_ids(self):
        now = [0.0]
        throttle = Throttle(window=60, max_keys=2, clock=lambda: now[0])
        self.assertEqual([throttle.check(key) for key in ("a", "a", "b", "c")], [0, None, 0, None])
        now[0] = 60
        self.assertEqual((throttle.check("a"), throttle.check("c"), throttle.check("b")), (1, 0, None))
        self.assertLessEqual(len(throttle.entries), 2)
        self.assertEqual(safe_id("Item_01.v2"), "Item_01.v2")
        for unsafe in ("secret value", "x" * 97, "", "a#b", "line\nbreak"):
            self.assertEqual(safe_id(unsafe), "invalid_id")

    def test_stack_limit(self):
        def recurse(depth):
            if depth:
                return recurse(depth - 1)
            raise ValueError("private")
        try:
            recurse(20)
        except ValueError as error:
            self.assertEqual(len(safe_stack(error)), 8)


if __name__ == "__main__":
    unittest.main()
