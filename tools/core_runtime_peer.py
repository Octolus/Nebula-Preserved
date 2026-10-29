#!/usr/bin/env python3
"""Localhost-only Nebula core integration peer.

Default execution is an offline dry-run and creates no sockets.  Network access
requires the explicit --run flag.  This peer is intentionally limited to the
reconstructed Nexus spawn/announce/public-chat path; it is not a general game
client or a claim of original-server parity.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import io
import json
import math
import socket
import struct
import sys
import time
import urllib.parse
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from wire import decrypt, encrypt, session_guid  # noqa: E402


HOST = "127.0.0.1"
PLATFORM = "StandaloneWindows"
PLATFORM_NUMBER = 1
ACCOUNT_ID = "preservation-integration-peer"
USERNAME = "Preservation Integration Peer"
VERSION = "v72"
MAX_TELEPATHY_FRAME = 16 * 1024
MAX_CHAT_BYTES = 4096
FLOAT32_MAX = 3.4028234663852886e38
PLAYER_ASSET_ID = "86041873-b099-ede4-687c-67606e379683"


def stable_hash32(text: str) -> int:
    value = 23
    for character in text:
        value = ((value * 31 + ord(character)) & 0xFFFFFFFF)
    return value


def message_id(full_name: str) -> int:
    return stable_hash32(full_name) & 0xFFFF


MESSAGE_NAMES = (
    "NebulaMessage",
    "Mirror.ReadyMessage",
    "Mirror.NotReadyMessage",
    "Mirror.AddPlayerMessage",
    "Mirror.SceneMessage",
    "Mirror.CommandMessage",
    "Mirror.RpcMessage",
    "Mirror.SpawnMessage",
    "Mirror.ChangeOwnerMessage",
    "Mirror.ObjectSpawnStartedMessage",
    "Mirror.ObjectSpawnFinishedMessage",
    "Mirror.ObjectDestroyMessage",
    "Mirror.ObjectHideMessage",
    "Mirror.EntityStateMessage",
    "Mirror.NetworkPingMessage",
    "Mirror.NetworkPongMessage",
)
MESSAGE_IDS = {name: message_id(name) for name in MESSAGE_NAMES}
ID_NAMES = {value: name for name, value in MESSAGE_IDS.items()}


class ProtocolStop(RuntimeError):
    """Fail-closed protocol boundary; caller closes the connection."""


class Reader:
    def __init__(self, data: bytes):
        self.data = data
        self.offset = 0

    @property
    def remaining(self) -> int:
        return len(self.data) - self.offset

    def take(self, count: int) -> bytes:
        if count < 0 or count > self.remaining:
            raise ProtocolStop(f"truncated_message_needed_{count}_remaining_{self.remaining}")
        result = self.data[self.offset : self.offset + count]
        self.offset += count
        return result

    def unpack(self, fmt: str) -> tuple[Any, ...]:
        size = struct.calcsize(fmt)
        return struct.unpack(fmt, self.take(size))

    def u8(self) -> int:
        return self.unpack("<B")[0]

    def boolean(self) -> bool:
        value = self.u8()
        if value not in (0, 1):
            raise ProtocolStop("noncanonical_boolean")
        return bool(value)

    def u16(self) -> int:
        return self.unpack("<H")[0]

    def u32(self) -> int:
        return self.unpack("<I")[0]

    def i32(self) -> int:
        return self.unpack("<i")[0]

    def u64(self) -> int:
        return self.unpack("<Q")[0]

    def f64(self) -> float:
        return self.unpack("<d")[0]

    def vector3(self) -> tuple[float, float, float]:
        return self.unpack("<fff")

    def quaternion(self) -> tuple[float, float, float, float]:
        return self.unpack("<ffff")

    def mirror_string(self) -> str | None:
        encoded_size = self.u16()
        if encoded_size == 0:
            return None
        size = encoded_size - 1
        if size >= 32768:
            raise ProtocolStop("mirror_string_too_large")
        try:
            return self.take(size).decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise ProtocolStop("invalid_utf8_string") from exc

    def byte_segment(self) -> bytes | None:
        encoded_size = self.u32()
        if encoded_size == 0:
            return None
        return self.take(encoded_size - 1)


def mirror_string(value: str | None) -> bytes:
    if value is None:
        return struct.pack("<H", 0)
    encoded = value.encode("utf-8")
    if len(encoded) >= 32768:
        raise ValueError("Mirror string exceeds the pinned writer limit")
    return struct.pack("<H", len(encoded) + 1) + encoded


def packed_message(full_name: str, payload: bytes = b"") -> bytes:
    return struct.pack("<H", MESSAGE_IDS[full_name]) + payload


def telepathy_frame(messages: list[bytes], timestamp: float | None = None) -> bytes:
    batch = struct.pack("<d", time.monotonic() if timestamp is None else timestamp) + b"".join(messages)
    if not 0 < len(batch) <= MAX_TELEPATHY_FRAME:
        raise ValueError("Telepathy batch is outside the pinned 16 KiB bound")
    return struct.pack(">I", len(batch)) + batch


def receive_exact(sock: socket.socket, count: int) -> bytes:
    chunks: list[bytes] = []
    remaining = count
    while remaining:
        chunk = sock.recv(remaining)
        if not chunk:
            raise EOFError("connection_closed")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def receive_frame(sock: socket.socket) -> bytes:
    size = struct.unpack(">I", receive_exact(sock, 4))[0]
    if not 0 < size <= MAX_TELEPATHY_FRAME:
        raise ProtocolStop(f"invalid_telepathy_length_{size}")
    return receive_exact(sock, size)


class JsonLog:
    def __init__(self, stream: BinaryIO):
        self.stream = stream

    def write(self, event: str, **fields: Any) -> None:
        record = {"time": time.time(), "event": event, **fields}
        encoded = (json.dumps(record, ensure_ascii=True, separators=(",", ":")) + "\n").encode("utf-8")
        self.stream.write(encoded)
        self.stream.flush()


def digest_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class HttpWire:
    def __init__(self, port: int, log: JsonLog, timeout: float):
        self.port = port
        self.log = log
        self.timeout = timeout

    def call(self, route: str, fields: list[str]) -> str:
        plaintext = "#".join(fields) + "#" + PLATFORM
        query = urllib.parse.urlencode({"data": encrypt(plaintext)})
        connection = http.client.HTTPConnection(HOST, self.port, timeout=self.timeout)
        try:
            connection.request("GET", f"/{route}?{query}", headers={"Connection": "close"})
            response = connection.getresponse()
            body = response.read(1024 * 1024 + 1)
            if len(body) > 1024 * 1024:
                raise ProtocolStop("http_response_too_large")
            self.log.write("http_response", route=route, status=response.status, bytes=len(body))
            if response.status != 200:
                raise ProtocolStop(f"http_{route}_status_{response.status}")
            try:
                return decrypt(body.decode("ascii", errors="strict"))
            except (ValueError, UnicodeError) as exc:
                raise ProtocolStop(f"http_{route}_invalid_encrypted_response") from exc
        finally:
            connection.close()


@dataclass(frozen=True)
class Allocation:
    instance_id: str
    scene: str
    host: str
    port: int


def bootstrap(http: HttpWire, timeout: float) -> tuple[str, Allocation]:
    user = http.call("N2UserExist", [USERNAME, VERSION, "false", ACCOUNT_ID, "0"])
    user_fields = user.split("#")
    if len(user_fields) != 7 or user_fields[0] != ACCOUNT_ID or user_fields[4:] != ["false", "", ""]:
        raise ProtocolStop("N2UserExist_response_contract_mismatch")

    request_hash = hashlib.sha256(b"preservation-integration-peer:core-runtime-peer-v1").hexdigest()
    channel = http.call("ChannelGUIDServlet", [ACCOUNT_ID, request_hash])
    if channel != "true#":
        raise ProtocolStop("ChannelGUIDServlet_response_contract_mismatch")
    guid = session_guid(ACCOUNT_ID, request_hash)

    loaded = http.call("N2LoadSpace", [guid, ACCOUNT_ID, "Login", "false", "", ""])
    if loaded != f"{guid}#false#false":
        raise ProtocolStop("N2LoadSpace_response_contract_mismatch")

    deadline = time.monotonic() + timeout
    while True:
        response = http.call("N2SpaceLoading", [guid, ACCOUNT_ID])
        fields = response.split("#")
        if fields == [guid, "false"]:
            if time.monotonic() >= deadline:
                raise ProtocolStop("N2SpaceLoading_ready_timeout")
            time.sleep(0.5)
            continue
        if len(fields) != 6 or fields[0:2] != [guid, "true"]:
            raise ProtocolStop("N2SpaceLoading_response_contract_mismatch")
        if fields[3] != "Nexus" or fields[4] != HOST:
            raise ProtocolStop("allocation_outside_local_nexus_scope")
        try:
            port = int(fields[5], 10)
        except ValueError as exc:
            raise ProtocolStop("allocation_invalid_port") from exc
        if not 1 <= port <= 65535 or str(port) != fields[5]:
            raise ProtocolStop("allocation_noncanonical_port")
        return guid, Allocation(fields[2], fields[3], fields[4], port)


@dataclass
class PeerState:
    guid: str
    local_net_id: int | None = None
    announced: bool = False
    greeting_sent: bool = False
    reply_sent: bool = False
    remote_join_seen: bool = False
    received_public_chat: bool = False
    position_sent: bool = False


def checked_position(position: tuple[float, float, float] | list[float]) -> tuple[float, float, float]:
    if len(position) != 3 or any(type(value) not in (int, float) for value in position):
        raise ValueError("position requires three numeric coordinates")
    coordinates = tuple(float(value) for value in position)
    if any(not math.isfinite(value) or abs(value) > FLOAT32_MAX for value in coordinates):
        raise ValueError("position coordinates must be finite and representable as float32")
    return coordinates


def position_plaintext(net_id: int, position: tuple[float, float, float]) -> str:
    if type(net_id) is not int or not 0 < net_id <= 0xFFFFFFFF:
        raise ValueError("position update requires the owned uint32 netId")
    x, y, z = checked_position(position)
    pose = {"position": {"x": x, "y": y, "z": z}, "rotation": {"x": 0, "y": 0, "z": 0, "w": 1}}
    return "2#" + str(net_id) + "#" + json.dumps(pose, separators=(",", ":"), allow_nan=False)


def parse_spawn(reader: Reader) -> dict[str, Any]:
    net_id = reader.u32()
    is_local = reader.boolean()
    is_owner = reader.boolean()
    scene_id = reader.u64()
    asset_id = str(uuid.UUID(bytes_le=reader.take(16)))
    position = reader.vector3()
    rotation = reader.quaternion()
    scale = reader.vector3()
    payload = reader.byte_segment()
    return {
        "net_id": net_id,
        "is_local_player": is_local,
        "is_owner": is_owner,
        "scene_id": scene_id,
        "asset_id": asset_id,
        "position": position,
        "rotation": rotation,
        "scale": scale,
        "payload_bytes": None if payload is None else len(payload),
        "payload_sha256": None if payload is None else hashlib.sha256(payload).hexdigest(),
    }


def parse_known_message(name: str, reader: Reader) -> dict[str, Any]:
    if name in {
        "Mirror.ReadyMessage",
        "Mirror.NotReadyMessage",
        "Mirror.AddPlayerMessage",
        "Mirror.ObjectSpawnStartedMessage",
        "Mirror.ObjectSpawnFinishedMessage",
    }:
        return {}
    if name == "Mirror.SceneMessage":
        return {"scene_name": reader.mirror_string(), "operation": reader.u8(), "custom": reader.boolean()}
    if name in {"Mirror.CommandMessage", "Mirror.RpcMessage"}:
        net_id = reader.u32()
        component_index = reader.u8()
        function_hash = reader.i32()
        payload = reader.byte_segment()
        return {
            "net_id": net_id,
            "component_index": component_index,
            "function_hash": function_hash,
            "payload_bytes": None if payload is None else len(payload),
        }
    if name == "Mirror.SpawnMessage":
        return parse_spawn(reader)
    if name == "Mirror.ChangeOwnerMessage":
        return {"net_id": reader.u32(), "is_owner": reader.boolean(), "is_local": reader.boolean()}
    if name in {"Mirror.ObjectDestroyMessage", "Mirror.ObjectHideMessage"}:
        return {"net_id": reader.u32()}
    if name == "Mirror.EntityStateMessage":
        net_id = reader.u32()
        payload = reader.byte_segment()
        return {"net_id": net_id, "payload_bytes": None if payload is None else len(payload)}
    if name == "Mirror.NetworkPingMessage":
        return {"client_time": reader.f64()}
    if name == "Mirror.NetworkPongMessage":
        return {"client_time": reader.f64(), "server_time": reader.f64()}
    if name == "NebulaMessage":
        return {"ciphertext": reader.mirror_string()}
    raise ProtocolStop(f"known_id_without_parser_{name}")


class RuntimePeer:
    def __init__(self, sock: socket.socket, state: PeerState, log: JsonLog, chat_message: str, reply_message: str,
                 position: tuple[float, float, float] | None = None):
        self.sock = sock
        self.state = state
        self.log = log
        self.chat_message = chat_message
        self.reply_message = reply_message
        self.position = None if position is None else checked_position(position)

    def send(self, messages: list[bytes], kind: str) -> None:
        frame = telepathy_frame(messages)
        self.sock.sendall(frame)
        self.log.write("mirror_send", kind=kind, messages=len(messages), frame_bytes=len(frame))

    def send_nebula(self, plaintext_without_platform: str, kind: str) -> None:
        ciphertext = encrypt(plaintext_without_platform + "#" + PLATFORM)
        payload = mirror_string(ciphertext)
        self.send([packed_message("NebulaMessage", payload)], kind)

    def send_ready_add_player(self) -> None:
        self.send(
            [packed_message("Mirror.ReadyMessage"), packed_message("Mirror.AddPlayerMessage")],
            "ready_add_player",
        )

    def announce(self) -> None:
        if self.state.local_net_id is None or self.state.announced:
            return
        plaintext = "#".join(
            ("1", str(self.state.local_net_id), self.state.guid, USERNAME, str(PLATFORM_NUMBER))
        )
        self.send_nebula(plaintext, "application_announce_1")
        self.state.announced = True
        self.log.write("application_announce", net_id=self.state.local_net_id, guid_sha256=digest_text(self.state.guid))
        self.send_position_once()

    def send_position_once(self) -> None:
        if self.position is None or self.state.position_sent or not self.state.announced or self.state.local_net_id is None:
            return
        self.send_nebula(position_plaintext(self.state.local_net_id, self.position), "owned_position_2")
        self.state.position_sent = True
        self.log.write("owned_position", net_id=self.state.local_net_id,
                       x=self.position[0], y=self.position[1], z=self.position[2])

    def public_chat(self, message: str, kind: str) -> None:
        encoded = message.encode("utf-8")
        if not encoded or len(encoded) > MAX_CHAT_BYTES or any(c in message for c in "#<>"):
            raise ProtocolStop("authored_chat_message_outside_native_safe_subset")
        plaintext = "#".join(("13", self.state.guid, "Public", "-1", message, "0"))
        self.send_nebula(plaintext, kind)
        self.log.write(kind, message_bytes=len(encoded), message_sha256=hashlib.sha256(encoded).hexdigest())

    def handle_application(self, ciphertext: str | None) -> None:
        if not ciphertext:
            raise ProtocolStop("null_or_empty_nebula_ciphertext")
        try:
            plaintext = decrypt(ciphertext)
        except (ValueError, UnicodeError) as exc:
            raise ProtocolStop("invalid_nebula_ciphertext") from exc
        fields = plaintext.split("#")
        try:
            opcode = int(fields[0], 10)
        except (ValueError, IndexError) as exc:
            raise ProtocolStop("invalid_application_opcode") from exc
        self.log.write("application_receive", opcode=opcode, fields=max(0, len(fields) - 1), bytes=len(plaintext.encode("utf-8")))
        if opcode == 0:
            if fields != ["0"]:
                raise ProtocolStop("application_0_shape_mismatch")
            return
        if opcode == 1:
            if len(fields) != 5:
                raise ProtocolStop("application_1_shape_mismatch")
            try:
                remote_net_id = int(fields[1], 10)
                remote_platform = int(fields[4], 10)
            except ValueError as exc:
                raise ProtocolStop("application_1_numeric_mismatch") from exc
            if fields[2] != self.state.guid:
                self.state.remote_join_seen = True
                self.log.write(
                    "remote_join",
                    net_id=remote_net_id,
                    guid_sha256=digest_text(fields[2]),
                    username_sha256=digest_text(fields[3]),
                    platform=remote_platform,
                )
            return
        if opcode == 13:
            if len(fields) != 6:
                raise ProtocolStop("application_13_shape_mismatch")
            if fields[2] != "Public" or fields[3] != "-1" or fields[5] != "0":
                self.log.write("non_public_chat_ignored", group_sha256=digest_text(fields[2]))
                return
            message_bytes = fields[4].encode("utf-8")
            own_echo = fields[1] == self.state.guid
            self.log.write(
                "public_chat_receive",
                own_echo=own_echo,
                sender_guid_sha256=digest_text(fields[1]),
                message_bytes=len(message_bytes),
                message_sha256=hashlib.sha256(message_bytes).hexdigest(),
            )
            if not own_echo:
                self.state.received_public_chat = True
                if not self.state.reply_sent:
                    self.public_chat(self.reply_message, "public_chat_reply")
                    self.state.reply_sent = True
            return

    def handle_batch(self, batch: bytes) -> None:
        reader = Reader(batch)
        timestamp = reader.f64()
        self.log.write("mirror_batch", timestamp=timestamp, bytes=len(batch))
        while reader.remaining:
            msg_id = reader.u16()
            name = ID_NAMES.get(msg_id)
            if name is None:
                remainder = reader.take(reader.remaining)
                self.log.write(
                    "unknown_mirror_message",
                    message_id=msg_id,
                    remaining_bytes=len(remainder),
                    remaining_sha256=hashlib.sha256(remainder).hexdigest(),
                )
                raise ProtocolStop(f"unknown_mirror_message_{msg_id}")
            start = reader.offset
            parsed = parse_known_message(name, reader)
            consumed = reader.offset - start
            public = {key: value for key, value in parsed.items() if key != "ciphertext"}
            self.log.write("mirror_receive", message=name, message_id=msg_id, serialized_bytes=consumed, **public)
            if name == "Mirror.SpawnMessage" and parsed["is_local_player"]:
                if (
                    not parsed["is_owner"]
                    or parsed["scene_id"] != 0
                    or parsed["asset_id"] != PLAYER_ASSET_ID
                    or parsed["payload_bytes"] != 42
                ):
                    raise ProtocolStop("local_spawn_contract_mismatch")
                if self.state.local_net_id is not None and self.state.local_net_id != parsed["net_id"]:
                    raise ProtocolStop("multiple_local_spawn_net_ids")
                self.state.local_net_id = parsed["net_id"]
                self.announce()
            elif name == "NebulaMessage":
                self.handle_application(parsed["ciphertext"])


def offline_self_test() -> None:
    expected_ids = {
        "NebulaMessage": 58609,
        "Mirror.ReadyMessage": 40252,
        "Mirror.AddPlayerMessage": 13085,
        "Mirror.SpawnMessage": 16484,
        "Mirror.ObjectSpawnStartedMessage": 59786,
        "Mirror.ObjectSpawnFinishedMessage": 34417,
    }
    for name, expected in expected_ids.items():
        if MESSAGE_IDS[name] != expected:
            raise AssertionError((name, MESSAGE_IDS[name], expected))
    ciphertext = encrypt("0")
    if decrypt(ciphertext) != "0":
        raise AssertionError("backend wire AES roundtrip failed")
    spawn_payload = b"x" * 42
    asset = uuid.UUID(PLAYER_ASSET_ID)
    spawn = b"".join(
        (
            struct.pack("<IBBQ", 7, 1, 1, 0),
            asset.bytes_le,
            struct.pack("<fff", 1, 2, 3),
            struct.pack("<ffff", 0, 0, 0, 1),
            struct.pack("<fff", 1, 1, 1),
            struct.pack("<I", len(spawn_payload) + 1),
            spawn_payload,
        )
    )
    parsed = parse_spawn(Reader(spawn))
    if parsed["net_id"] != 7 or not parsed["is_local_player"] or parsed["payload_bytes"] != 42:
        raise AssertionError("SpawnMessage parser self-test failed")
    frame = telepathy_frame([packed_message("NebulaMessage", mirror_string(ciphertext))], timestamp=1.25)
    if struct.unpack(">I", frame[:4])[0] != len(frame) - 4:
        raise AssertionError("Telepathy length self-test failed")

    class CaptureSocket:
        def __init__(self):
            self.frames: list[bytes] = []

        def sendall(self, data: bytes) -> None:
            self.frames.append(data)

    captured = CaptureSocket()
    log = JsonLog(io.BytesIO())
    guid = "a" * 32
    state = PeerState(guid)
    peer = RuntimePeer(captured, state, log, "Peer online.", "Peer received chat.")
    incoming = struct.pack("<d", 2.0) + b"".join(
        (
            packed_message("Mirror.ObjectSpawnStartedMessage"),
            packed_message("Mirror.SpawnMessage", spawn),
            packed_message("Mirror.ObjectSpawnFinishedMessage"),
            packed_message("NebulaMessage", mirror_string(encrypt("0"))),
        )
    )
    peer.handle_batch(incoming)
    if state.local_net_id != 7 or not state.announced or len(captured.frames) != 1:
        raise AssertionError("local spawn/announce self-test failed")
    announce_reader = Reader(captured.frames[0][4:])
    announce_reader.f64()
    if announce_reader.u16() != MESSAGE_IDS["NebulaMessage"]:
        raise AssertionError("announce carrier ID self-test failed")
    announced = decrypt(announce_reader.mirror_string())
    if announced != f"1#7#{guid}#{USERNAME}#1#{PLATFORM}":
        raise AssertionError("application announce self-test failed")
    # Position is opt-in, owned-netId only, ordered after announce and sent once.
    positioned_socket = CaptureSocket()
    positioned_state = PeerState(guid)
    positioned_log = io.BytesIO()
    positioned = RuntimePeer(positioned_socket, positioned_state, JsonLog(positioned_log),
                             "Peer online.", "Peer received chat.", (67, 19.31047, -24))
    positioned.send_position_once()
    if positioned_socket.frames:
        raise AssertionError("position sent before owned spawn/announce")
    positioned.handle_batch(incoming)
    if len(positioned_socket.frames) != 2 or not positioned_state.position_sent:
        raise AssertionError("opt-in position must follow exactly one announce")
    pose_reader = Reader(positioned_socket.frames[1][4:])
    pose_reader.f64()
    if pose_reader.u16() != MESSAGE_IDS["NebulaMessage"]:
        raise AssertionError("position carrier ID mismatch")
    fields = decrypt(pose_reader.mirror_string()).split("#")
    if len(fields) != 4 or fields[:2] != ["2", "7"] or fields[3] != PLATFORM or pose_reader.remaining:
        raise AssertionError("owned C2S2 fields/trailer mismatch")
    if json.loads(fields[2]) != {"position":{"x":67.0,"y":19.31047,"z":-24.0},
                                "rotation":{"x":0,"y":0,"z":0,"w":1}}:
        raise AssertionError("position JSON/quaternion mismatch")
    positioned.announce()
    positioned.send_position_once()
    if len(positioned_socket.frames) != 2:
        raise AssertionError("position was sent more than once")
    events = [json.loads(line) for line in positioned_log.getvalue().splitlines()]
    if len([event for event in events if event["event"] == "owned_position"]) != 1:
        raise AssertionError("owned position logging mismatch")
    for invalid in ((float("nan"),0,0), (0,float("inf"),0), (0,0,-float("inf")),
                    (FLOAT32_MAX * 2,0,0), (True,0,0), (0,0)):
        try:
            checked_position(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid position accepted")
    for invalid_id in (None, True, 0, -1, 0x100000000):
        try:
            position_plaintext(invalid_id, (0,0,0))
        except ValueError:
            pass
        else:
            raise AssertionError("non-owned netId shape accepted")
    remote_guid = "b" * 32
    peer.handle_batch(
        struct.pack("<d", 3.0)
        + packed_message("NebulaMessage", mirror_string(encrypt(f"1#8#{remote_guid}#UI Fixture#1")))
        + packed_message("NebulaMessage", mirror_string(encrypt(f"13#{remote_guid}#Public#-1#hello#0")))
    )
    if not state.remote_join_seen or not state.received_public_chat or not state.reply_sent:
        raise AssertionError("public chat receive/reply self-test failed")


def plan(args: argparse.Namespace) -> dict[str, Any]:
    result = {
        "mode": "dry_run",
        "sockets_opened": False,
        "host": HOST,
        "http_port": args.http_port,
        "fixture_account": ACCOUNT_ID,
        "scene": "Nexus",
        "mirror_message_ids": MESSAGE_IDS,
        "future_steps": [
            "N2UserExist",
            "ChannelGUIDServlet",
            "N2LoadSpace(Login)",
            "poll N2SpaceLoading",
            "Telepathy connect",
            "Mirror ReadyMessage + AddPlayerMessage",
            "parse local SpawnMessage",
            "AES application announce opcode1",
            "public chat opcode13 exchange",
        ],
        "limits": [
            "localhost only",
            "Nexus only",
            "one fixture account",
            "unknown Mirror message stops the peer",
            "no minigame or unsupported-scene behavior",
        ],
    }
    if args.position is not None:
        result["fixture_position"] = dict(zip(("x", "y", "z"), args.position))
        result["future_steps"].insert(-1, "one owned-netId pose opcode2 after announce")
    return result


def validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if not 1 <= args.http_port <= 65535:
        parser.error("--http-port must be 1..65535")
    if not 1 <= args.duration <= 300:
        parser.error("--duration must be 1..300 seconds")
    if not 1 <= args.ready_timeout <= 120:
        parser.error("--ready-timeout must be 1..120 seconds")
    if args.position is not None:
        try:
            args.position = checked_position(args.position)
        except ValueError as exc:
            parser.error("--position: " + str(exc))
    for value, label in ((args.chat_message, "--chat-message"), (args.reply_message, "--reply-message")):
        encoded = value.encode("utf-8")
        if not encoded or len(encoded) > MAX_CHAT_BYTES or any(c in value for c in "#<>"):
            parser.error(f"{label} must be 1..4096 UTF-8 bytes and contain none of #<>")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="explicitly enable the future localhost integration run")
    parser.add_argument("--http-port", type=int, default=8080)
    parser.add_argument("--duration", type=float, default=30.0)
    parser.add_argument("--ready-timeout", type=float, default=30.0)
    parser.add_argument("--chat-message", default="Preservation integration peer online.")
    parser.add_argument("--reply-message", default="Preservation integration peer received public chat.")
    parser.add_argument("--position", nargs=3, type=float, metavar=("X", "Y", "Z"),
                        help="send one owned fixture pose after announce; finite float32 coordinates")
    parser.add_argument("--log", type=Path, help="JSONL path; required with --run")
    args = parser.parse_args(argv)
    validate_args(parser, args)
    if args.run and args.log is None:
        parser.error("--log is required with --run")
    return args


def run(args: argparse.Namespace) -> int:
    if args.log is None:
        raise AssertionError("run requires an explicit log path")
    args.log.parent.mkdir(parents=True, exist_ok=True)
    with args.log.open("xb") as stream:
        log = JsonLog(stream)
        log.write("peer_start", host=HOST, http_port=args.http_port, account=ACCOUNT_ID, parity="unproven")
        sock: socket.socket | None = None
        try:
            http = HttpWire(args.http_port, log, args.ready_timeout)
            guid, allocation = bootstrap(http, args.ready_timeout)
            log.write(
                "allocation",
                instance_id=allocation.instance_id,
                scene=allocation.scene,
                host=allocation.host,
                port=allocation.port,
                guid_sha256=digest_text(guid),
            )
            state = PeerState(guid)
            sock = socket.create_connection((HOST, allocation.port), timeout=5.0)
            sock.settimeout(0.25)
            peer = RuntimePeer(sock, state, log, args.chat_message, args.reply_message, args.position)
            peer.send_ready_add_player()
            started = time.monotonic()
            deadline = started + args.duration
            next_ping = started + 5.0
            greeting_deadline = started + 5.0
            while time.monotonic() < deadline:
                now = time.monotonic()
                if state.announced and not state.greeting_sent and (state.remote_join_seen or now >= greeting_deadline):
                    peer.public_chat(args.chat_message, "public_chat_greeting")
                    state.greeting_sent = True
                if now >= next_ping:
                    peer.send(
                        [packed_message("Mirror.NetworkPingMessage", struct.pack("<d", now))],
                        "network_ping",
                    )
                    next_ping = now + 5.0
                try:
                    peer.handle_batch(receive_frame(sock))
                except socket.timeout:
                    continue
            complete = (
                state.announced
                and state.remote_join_seen
                and state.greeting_sent
                and state.received_public_chat
                and state.reply_sent
            )
            log.write(
                "peer_complete",
                exchange_complete=complete,
                announced=state.announced,
                greeting_sent=state.greeting_sent,
                remote_join_seen=state.remote_join_seen,
                received_public_chat=state.received_public_chat,
                reply_sent=state.reply_sent,
            )
            return 0 if complete else 3
        except (EOFError, OSError, ProtocolStop) as exc:
            log.write("peer_stopped", reason=type(exc).__name__, detail=str(exc))
            return 4
        finally:
            if sock is not None:
                sock.close()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    offline_self_test()
    if not args.run:
        print(json.dumps(plan(args), indent=2, sort_keys=True))
        return 0
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())

