"""Headless in-memory gateway close diagnostics; no sockets or real identities."""
import asyncio
from contextlib import redirect_stdout
import io
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import diagnostic_logging
import remote_gateway as gateway
from wire import encrypt

GUID = "disposable-test-guid"
SECRET = "x" * 85


def frame(batch):
    return struct.pack(">I", len(batch)) + batch


def identity(guid=GUID):
    ciphertext = encrypt(f"1#sample-account#{guid}#sample-name#0#StandaloneWindows").encode("ascii")
    return struct.pack("<dHH", 1.0, gateway.NEBULA, len(ciphertext) + 1) + ciphertext


class Writer:
    def __init__(self, tls=False):
        self.tls = tls
        self.data = bytearray()
        self.closed = False
        self.waited = False
        self.written = asyncio.Event()

    def get_extra_info(self, key):
        if key == "ssl_object":
            return self if self.tls else None
        if key == "peername":
            return ("192.0.2.99", 12345)

    def selected_alpn_protocol(self):
        return "nebula-game/1"

    def write(self, data):
        self.data.extend(data)
        self.written.set()

    async def drain(self):
        pass

    def close(self):
        self.closed = True

    async def wait_closed(self):
        self.waited = True


class Authority:
    def __init__(self, revalidation_error=None, initial_error=None):
        self.revalidation_error = revalidation_error
        self.initial_error = initial_error

    def resolve(self, port, authorization, actor=None):
        if actor is not None and self.revalidation_error:
            raise self.revalidation_error
        if actor is None and self.initial_error:
            raise self.initial_error
        return {"guid": GUID, "account": "sample-account", "credential": SECRET}


class Diagnostics(unittest.IsolatedAsyncioTestCase):
    async def exercise(self, data, *, eof=True, stop=None, authority=None):
        reader, local = asyncio.StreamReader(), asyncio.StreamReader()
        reader.feed_data(struct.pack(">4sHH", b"NRT1", 28000, 85) + SECRET.encode() + data)
        if eof:
            reader.feed_eof()
        writer, upstream = Writer(tls=True), Writer()
        service = gateway.Gateway(authority or Authority())
        output = io.StringIO()
        loop = asyncio.get_running_loop()
        warnings = []
        previous = loop.get_exception_handler()
        loop.set_exception_handler(lambda _loop, event: warnings.append(event))
        scheduled = None
        original_sleep = asyncio.sleep

        async def fast_revalidation(_delay):
            await upstream.written.wait()
            await original_sleep(0)

        if stop == "server_eof":
            async def finish():
                await upstream.written.wait()
                local.feed_eof()
            scheduled = asyncio.create_task(finish())
        try:
            with redirect_stdout(output), patch.object(gateway.asyncio, "open_connection", AsyncMock(return_value=(local, upstream))):
                if stop == "revalidation":
                    with patch.object(gateway.asyncio, "sleep", fast_revalidation):
                        await asyncio.wait_for(service.serve(reader, writer), 2)
                else:
                    await asyncio.wait_for(service.serve(reader, writer), 2)
            if scheduled:
                await scheduled
            await original_sleep(0)
        finally:
            if scheduled and not scheduled.done():
                scheduled.cancel()
                await asyncio.gather(scheduled, return_exceptions=True)
            loop.set_exception_handler(previous)
        self.assertFalse(warnings)
        self.assertFalse(service.active)
        self.assertEqual(service.slots._value, gateway.MAX_CONNECTIONS)
        self.assertTrue(writer.closed and writer.waited)
        if writer.data:
            self.assertTrue(upstream.closed and upstream.waited)
        events = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertTrue(events)
        for event in events:
            self.assertIn(event["event"], ("gateway_close", "identity_bound"))
            self.assertLessEqual(set(event), {"event", "task", "stage", "reason", "frame_length", "first_mirror_id",
                "timestamp", "connection_id", "elapsed_ms", "actor_ref", "session_ref", "frames_received",
                "frames_forwarded", "client_bytes_received", "client_bytes_forwarded", "server_bytes_received",
                "server_bytes_forwarded", "last_mirror_id", "last_opcode", "denial_detail"})
        for sensitive in (GUID, SECRET, "sample-account", "sample-name", "192.0.2.99"):
            self.assertNotIn(sensitive, output.getvalue())
        self.last_events = events
        return [event for event in events if event["event"] == "gateway_close"], bytes(upstream.data)

    async def test_identity_denial_has_numeric_context_only(self):
        batch = identity("wrong-guid")
        events, sent = await self.exercise(frame(batch))
        self.assertEqual(sent, b"")
        expected = {"event": "gateway_close", "task": "client_to_server",
            "stage": "identity_filter", "reason": "application_identity",
            "frame_length": len(batch), "first_mirror_id": gateway.NEBULA,
            "denial_detail": "guid_mismatch"}
        self.assertEqual({key: events[0][key] for key in expected}, expected)

    async def test_malformed_announced_length(self):
        events, sent = await self.exercise(struct.pack(">I", gateway.MAX_FRAME + 1))
        self.assertEqual(events[0]["reason"], "frame")
        self.assertEqual(events[0]["frame_length"], gateway.MAX_FRAME + 1)
        self.assertNotIn("first_mirror_id", events[0])
        self.assertFalse(sent)

    async def test_unknown_mirror_message(self):
        batch = struct.pack("<dH", 1.0, 65535)
        events, sent = await self.exercise(frame(batch))
        self.assertEqual(events[0]["reason"], "message")
        self.assertEqual(events[0]["first_mirror_id"], 65535)
        self.assertFalse(sent)

    async def test_partial_payload_stream_eof(self):
        events, _ = await self.exercise(struct.pack(">I", 100) + b"short")
        self.assertEqual(events[0]["reason"], "stream_eof")
        self.assertEqual(events[0]["frame_length"], 100)
        self.assertNotIn("first_mirror_id", events[0])

    async def test_accepted_identity_then_client_eof(self):
        batch = identity()
        events, sent = await self.exercise(frame(batch))
        self.assertEqual(sent, frame(batch))
        self.assertEqual(events[0]["stage"], "bound_read")
        self.assertEqual(events[0]["reason"], "stream_eof")
        self.assertNotIn("frame_length", events[0])

    async def test_accepted_identity_then_server_eof(self):
        batch = identity()
        events, sent = await self.exercise(frame(batch), eof=False, stop="server_eof")
        self.assertEqual(sent, frame(batch))
        self.assertEqual(events[0]["task"], "server_to_client")
        self.assertEqual(events[0]["reason"], "stream_eof")

    async def test_revalidation_denial_is_retrieved(self):
        batch = identity()
        events, sent = await self.exercise(frame(batch), eof=False, stop="revalidation",
            authority=Authority(revalidation_error=gateway.Denied("revoked_session")))
        self.assertEqual(sent, frame(batch))
        self.assertEqual(events[0]["task"], "revalidation")
        self.assertEqual(events[0]["reason"], "revoked_session")

    async def test_arbitrary_exception_text_is_never_logged(self):
        events, sent = await self.exercise(b"", authority=Authority(initial_error=RuntimeError(SECRET)))
        self.assertEqual(events[0]["task"], "admission")
        self.assertEqual(events[0]["stage"], "authorization")
        self.assertEqual(events[0]["reason"], "internal_error")
        self.assertFalse(sent)

    async def test_unrecognized_denial_text_is_redacted(self):
        events, _ = await self.exercise(b"", authority=Authority(initial_error=gateway.Denied(SECRET)))
        self.assertEqual(events[0]["reason"], "denied")

    async def test_completed_task_unexpected_exception_is_retrieved_and_redacted(self):
        with patch.object(gateway, "first_identity_frame", side_effect=RuntimeError(SECRET)):
            events, sent = await self.exercise(frame(identity()))
        self.assertEqual(events[0]["task"], "client_to_server")
        self.assertEqual(events[0]["stage"], "identity_filter")
        self.assertEqual(events[0]["reason"], "internal_error")
        self.assertFalse(sent)

    async def test_correlation_timing_counters_and_identity_milestone(self):
        batch = identity()
        events, _ = await self.exercise(frame(batch))
        close = events[0]
        milestones = [event for event in self.last_events if event["event"] == "identity_bound"]
        self.assertEqual(len(milestones), 1)
        milestone = milestones[0]
        self.assertRegex(close["connection_id"], "^[0-9a-f]{16}$")
        self.assertEqual(close["connection_id"], milestone["connection_id"])
        self.assertGreaterEqual(close["elapsed_ms"], milestone["elapsed_ms"])
        self.assertGreaterEqual(milestone["elapsed_ms"], 0)
        self.assertEqual(close["actor_ref"], hashlib.sha256(b"sample-account").hexdigest()[:16])
        self.assertEqual(close["session_ref"], hashlib.sha256(GUID.encode()).hexdigest()[:16])
        self.assertEqual(close["frames_received"], 1)
        self.assertEqual(close["frames_forwarded"], 1)
        self.assertEqual(close["client_bytes_received"], len(batch) + 4)
        self.assertEqual(close["client_bytes_forwarded"], len(batch) + 4)
        self.assertEqual(close["server_bytes_received"], 0)
        self.assertEqual(close["server_bytes_forwarded"], 0)
        self.assertEqual(close["last_mirror_id"], gateway.NEBULA)
        self.assertEqual(close["last_opcode"], 1)
        self.assertEqual(milestone["frames_forwarded"], 0)

    async def test_connections_have_distinct_correlation_ids(self):
        first, _ = await self.exercise(frame(identity()))
        second, _ = await self.exercise(frame(identity()))
        self.assertNotEqual(first[0]["connection_id"], second[0]["connection_id"])
        self.assertEqual(first[0]["actor_ref"], second[0]["actor_ref"])

    async def test_authentication_failure_has_no_identity_references(self):
        events, _ = await self.exercise(b"", authority=Authority(initial_error=gateway.Denied("credential")))
        self.assertNotIn("actor_ref", events[0])
        self.assertNotIn("session_ref", events[0])

    async def test_partial_frame_bytes_are_counted(self):
        events, _ = await self.exercise(struct.pack(">I", 100) + b"short")
        self.assertEqual(events[0]["client_bytes_received"], 9)
        self.assertEqual(events[0]["frames_received"], 0)

    async def test_schema_denial_distinguished_without_payload(self):
        ciphertext = encrypt("1#sample-account#disposable-test-guid#StandaloneWindows").encode()
        batch = struct.pack("<dHH", 1.0, gateway.NEBULA, len(ciphertext) + 1) + ciphertext
        events, _ = await self.exercise(frame(batch))
        self.assertEqual(events[0]["denial_detail"], "invalid_identity_schema")

    async def test_events_are_mirrored_to_rotating_state_file(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.addCleanup(diagnostic_logging.configure_file_sink, None)
        path = Path(temp.name) / "logs" / "gateway.jsonl"
        diagnostic_logging.configure_file_sink(path)
        await self.exercise(frame(identity()))
        mirrored = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(mirrored, self.last_events)
        self.assertIsNone(diagnostic_logging._file_sink.handler.stream)
        for sensitive in (GUID, SECRET, "sample-account", "192.0.2.99"):
            self.assertNotIn(sensitive, path.read_text(encoding="utf-8"))

    async def test_server_relay_counts_both_directions_without_payload_log(self):
        source = asyncio.StreamReader()
        source.feed_data(b"private-server-payload")
        source.feed_eof()
        destination = Writer()
        context = {"stage": "upstream_read", "_connection": {
            "server_bytes_received": 0, "server_bytes_forwarded": 0}}
        await gateway.Gateway(Authority()).relay(source, destination, context)
        self.assertEqual(context["_connection"]["server_bytes_received"], 22)
        self.assertEqual(context["_connection"]["server_bytes_forwarded"], 22)


if __name__ == "__main__":
    unittest.main()
