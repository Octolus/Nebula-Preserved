"""JSONL adapter around the actual reference Backend.handle, without listeners."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import sys
from types import SimpleNamespace
from urllib.parse import parse_qsl

sys.dont_write_bytecode = True
from common import HERE, environment, scratch, snapshot
from fixture_support import apply_fixture


def drive(coroutine):
    """Backend paths used by this suite complete synchronously without an event loop."""
    try:
        yielded = coroutine.send(None)
    except StopIteration as stopped:
        return stopped.value
    coroutine.close()
    raise RuntimeError("REFERENCE_ASYNC_PATH_NOT_SUPPORTED")


def deny_network(*_args, **_kwargs):
    raise RuntimeError("NETWORK_FORBIDDEN_BY_HEADLESS_PROBE")


class Probe:
    def __init__(self, reference: Path):
        sys.path[:0] = [str(reference / "backend"), str(reference / "tools")]
        import server
        import wire
        self.Backend, self.wire = server.Backend, wire
        self.backend = None
        self.state_dir = None
        self.profile = None
        self.admin = None

    def process(self, request):
        op = request["op"]
        if op == "init":
            if self.backend is not None:
                raise ValueError("ALREADY_INITIALIZED")
            self.state_dir = scratch(Path(request["state_dir"]))
            self.profile = request.get("core_test_profile")
            self.backend = self.Backend(self.state_dir, core_test_profile=self.profile)
            if "fixture" in request:
                apply_fixture(self.backend, request["fixture"])
            return {}
        if self.backend is None:
            raise ValueError("NOT_INITIALIZED")
        if op == "http":
            query = {}
            if "plaintext" in request:
                query["data"] = self.wire.encrypt(request["plaintext"])
            elif "data" in request:
                query["data"] = request["data"]
            incoming = SimpleNamespace(path="/" + request["route"], method=request.get("method", "GET"),
                                       query=query, headers=request.get("headers", {}))
            response = drive(self.backend.handle(incoming))
            body = response.text
            try:
                plaintext = self.wire.decrypt(body)
            except (ValueError, UnicodeError):
                plaintext = None
            return {"status": response.status, "body": body, "plaintext": plaintext,
                    "content_type": response.content_type}
        if op == "snapshot":
            return {"state": snapshot(self.backend.store.db)}
        if op == "admin_init":
            from management import Management
            self.admin = Management(self.backend.store, self.backend.service, request["token"].encode("utf-8"), request["operators"])
            return {}
        if op == "admin":
            if self.admin is None:
                raise ValueError("ADMIN_NOT_INITIALIZED")
            raw = json.dumps(request.get("body"), ensure_ascii=True, separators=(",", ":")).encode("utf-8")
            async def read():
                return raw
            query = request.get("query", {})
            if isinstance(query, str):
                query = dict(parse_qsl(query, keep_blank_values=True))
            from multidict import CIMultiDict
            headers = CIMultiDict(request.get("headers", {}))
            incoming = SimpleNamespace(method=request.get("method", "GET"), match_info={"tail": request["tail"]},
                headers=headers, query=query,
                content_type=request.get("content_type", headers.get("Content-Type", "application/octet-stream").split(";")[0]), content_length=len(raw), read=read)
            response = drive(self.admin.handle(incoming))
            return {"status": response.status, "body": json.loads(response.text)}
        if op == "restart":
            drive(self.backend.close(None))
            self.backend = self.Backend(self.state_dir, core_test_profile=self.profile)
            return {}
        if op == "close":
            drive(self.backend.close(None))
            self.backend = None
            return {}
        return {"ok": False, "error": "NOT_IMPLEMENTED"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    args = parser.parse_args()
    os.environ.update(environment(HERE / "runs" / "probe-temp"))
    probe = Probe(args.reference.resolve())
    # Imports precede the guard because asyncio imports inspect the socket type.
    # The guard covers construction, every adapter operation and restart.
    socket.socket = deny_network
    socket.create_connection = deny_network
    socket.getaddrinfo = deny_network
    for line in sys.stdin:
        request = {}
        try:
            request = json.loads(line)
            result = {"id": request.get("id"), "ok": True, **probe.process(request)}
        except Exception as exc:
            result = {"id": request.get("id"), "ok": False, "error": type(exc).__name__,
                      "detail": "REFERENCE_OPERATION_FAILED"}
        print(json.dumps(result, ensure_ascii=True, allow_nan=False, separators=(",", ":")), flush=True)
        if request.get("op") == "close":
            break


if __name__ == "__main__":
    main()
