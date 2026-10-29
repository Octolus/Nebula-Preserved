"""Optional TLS gateway for the preserved, source-pinned Mirror/Telepathy flow.

Install beside public_access.py/allocation.py/wire.py in the packaged backend.
Importing this module starts nothing. --listen and an operator TLS keypair are
required. No credential, session, packet payload or peer address is logged.
"""
from __future__ import annotations
import argparse
import asyncio
from contextlib import closing
import hashlib
import json
import math
from pathlib import Path
import signal
import sqlite3
import ssl
import struct
import threading
import time

from public_access import AccessAuthority, AccessDenied
from allocation import InstanceDirectory
from wire import decrypt

MAX_FRAME = 16 * 1024
MAX_CONNECTIONS = 64
MAX_LIFETIME = 24 * 3600


def message_id(name):
    result = 23
    for char in name:
        result = (result * 31 + ord(char)) & 0xffffffff
    return result & 0xffff


READY = message_id("Mirror.ReadyMessage")
NOT_READY = message_id("Mirror.NotReadyMessage")
ADD_PLAYER = message_id("Mirror.AddPlayerMessage")
PING = message_id("Mirror.NetworkPingMessage")
COMMAND = message_id("Mirror.CommandMessage")
ENTITY = message_id("Mirror.EntityStateMessage")
NEBULA = message_id("NebulaMessage")


class Denied(Exception):
    pass


def first_identity_frame(batch: bytes, guid: str, bound=False):
    """Admit only controls until exact source opcode1 binds the TLS actor.

    Reuses the pinned historical layout, not modern Mirror varuint batching:
    timestamp f64; ushort message ID; NebulaMessage ushort string size+1.
    Early owned Command/EntityState packets are discarded: the instance cannot
    accept ownership before the application's identity claim either. A different
    application opcode before the claim fails closed, pending native acceptance.
    """
    if not 8 <= len(batch) <= MAX_FRAME or not math.isfinite(struct.unpack_from("<d", batch)[0]):
        raise Denied("frame")
    offset = 8
    controls, accepted = [], []
    while offset < len(batch):
        start = offset
        if offset + 2 > len(batch):
            raise Denied("frame")
        kind, = struct.unpack_from("<H", batch, offset)
        offset += 2
        if kind in (READY, NOT_READY, ADD_PLAYER):
            pass
        elif kind == PING:
            if offset + 8 > len(batch) or not math.isfinite(struct.unpack_from("<d", batch, offset)[0]):
                raise Denied("frame")
            offset += 8
        elif kind in (COMMAND, ENTITY):
            prefix = 9 if kind == COMMAND else 4
            if offset + prefix + 4 > len(batch):
                raise Denied("frame")
            length, = struct.unpack_from("<I", batch, offset + prefix)
            offset += prefix + 4 + max(0, length - 1)
            if offset > len(batch):
                raise Denied("frame")
        elif kind == NEBULA:
            if offset + 2 > len(batch):
                raise Denied("frame")
            length, = struct.unpack_from("<H", batch, offset)
            offset += 2
            if not 1 < length < 32768 or offset + length - 1 > len(batch):
                raise Denied("frame")
            ciphertext = batch[offset:offset + length - 1].decode("ascii")
            offset += length - 1
            fields = decrypt(ciphertext).split("#")
            if len(fields) < 3 or fields[-1] != "StandaloneWindows" or not fields[0].isdigit():
                raise Denied("application_identity")
            opcode = int(fields[0])
            # Keep checking every GUID-bearing packet, even after opcode1. A
            # correct GUID claim may still be rejected by the instance (e.g.
            # stale snapshot or incorrect netId); it must never unlock a later
            # claim for another actor. Dispatch/Own: opcode1 GUID is token2;
            # every other Own consumer uses token1. 2/19/30 call Bound instead.
            if opcode == 1:
                if len(fields) != 6 or fields[2] != guid:
                    raise Denied("application_identity")
            elif opcode not in (2, 19, 30) and fields[1] != guid:
                raise Denied("application_identity")
            if not bound:
                if (len(fields) != 6 or fields[0] != "1" or fields[2] != guid
                        or fields[5] != "StandaloneWindows"):
                    raise Denied("application_identity")
                bound = True
        else:
            raise Denied("message")
        raw = batch[start:offset]
        if kind in (READY, NOT_READY, ADD_PLAYER, PING) and not bound:
            controls.append(raw)
        elif bound:
            accepted.append(raw)
    prefix = batch[:8]
    return ([prefix + b"".join(controls)] if controls else []) + ([prefix + b"".join(accepted)] if accepted else []), bound


class Authority:
    def __init__(self, state_dir: Path, first: int, last: int):
        self.state = state_dir
        self.first, self.last = first, last
        self.instances = InstanceDirectory(state_dir, advertised_ip="127.0.0.1",
                                            core_test_profile="nonmini-semantic-v1")
        # This sync limit remains held by the actual worker even if its asyncio
        # caller is cancelled. At most two memory-hard derivations can run.
        self.password_work = threading.BoundedSemaphore(2)
        self.descriptor_lock = threading.Lock()
        self.descriptors = {}
        self.descriptors_at = 0.0

    def resolve(self, port: int, authorization=None, expected=None):
        if not self.first <= port <= self.last:
            raise Denied("port")
        uri = (self.state / "preservation.sqlite3").resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=2)) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA query_only=ON")
            db.execute("BEGIN")
            if expected is None:
                with self.password_work:
                    account = AccessAuthority(db).authenticate(authorization)
            else:
                account = expected["account"]
            credential = db.execute("SELECT salt,verifier FROM public_access_credentials WHERE ps4_id=? AND revoked_at IS NULL", (account,)).fetchone()
            if credential is None:
                raise Denied("credential")
            fingerprint = hashlib.sha256(bytes(credential["salt"]) + bytes(credential["verifier"])).hexdigest()
            row = db.execute("""SELECT s.guid,a.instance_id,a.psidglobal,a.ip
                FROM sessions s JOIN allocations a USING(guid)
                WHERE s.ps4_id=? AND s.guid=(SELECT guid FROM sessions WHERE ps4_id=?
                    ORDER BY created_at DESC,guid DESC LIMIT 1)""", (account, account)).fetchone()
            if row is None or row["ip"] != "127.0.0.1":
                raise Denied("allocation")
            # Read the backend's committed sanction authority in the same
            # SQLite snapshot as credentials and allocation. No gateway writer
            # or dependency on a later scene snapshot publication is involved.
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_schema WHERE type='table' AND name IN ('moderation_accounts','moderation_revoked_sessions')")}
            if tables != {"moderation_accounts", "moderation_revoked_sessions"}:
                raise Denied("moderation_unavailable")
            sanction = db.execute("SELECT ban_enabled,ban_expires_at FROM moderation_accounts WHERE ps4_id=?", (account,)).fetchone()
            if sanction is not None and sanction["ban_enabled"] == 1 and (
                    sanction["ban_expires_at"] is None or time.time() < sanction["ban_expires_at"]):
                raise Denied("banned")
            if db.execute("SELECT 1 FROM moderation_revoked_sessions WHERE guid=?", (row["guid"],)).fetchone():
                raise Denied("revoked_session")
            value = {"account": account, "guid": row["guid"], "instance": row["instance_id"],
                     "scene": row["psidglobal"], "credential": fingerprint}
            if expected is not None and expected != value:
                raise Denied("changed")
        # Share the complete canonical readiness scan across connections rather
        # than reparse all semantic registries once per player every two seconds.
        with self.descriptor_lock:
            now = time.monotonic()
            if now - self.descriptors_at >= 1:
                self.descriptors = {row["instance_id"]: row for row in self.instances.all_ready()}
                self.descriptors_at = now
            descriptor = self.descriptors.get(value["instance"])
        if descriptor is None or descriptor["ip"] != "127.0.0.1" or descriptor.get("bind") != "127.0.0.1" or descriptor["port"] != port:
            raise Denied("instance")
        if descriptor["psidglobal"] != value["scene"] or not 0 <= time.time() - descriptor["heartbeat"] <= 15:
            raise Denied("instance")
        return value


async def read_frame(reader, timeout=45):
    header = await asyncio.wait_for(reader.readexactly(4), timeout)
    length, = struct.unpack(">I", header)
    if not 8 <= length <= MAX_FRAME:
        raise Denied("frame")
    return await asyncio.wait_for(reader.readexactly(length), timeout)


async def write_frame(writer, frame):
    writer.write(struct.pack(">I", len(frame)) + frame)
    await asyncio.wait_for(writer.drain(), 10)


class Gateway:
    def __init__(self, authority):
        self.authority = authority
        self.slots = asyncio.Semaphore(MAX_CONNECTIONS)
        self.password_work = asyncio.Semaphore(2)
        self.active = set()
        self.attempts = {}

    async def relay(self, source, destination):
        while True:
            chunk = await asyncio.wait_for(source.read(65536), 120)
            if not chunk:
                return
            destination.write(chunk)
            await asyncio.wait_for(destination.drain(), 10)

    async def serve(self, reader, writer):
        if self.slots.locked():
            writer.close()
            return
        await self.slots.acquire()
        task = asyncio.current_task()
        self.active.add(task)
        upstream = None
        jobs = []
        try:
            tls = writer.get_extra_info("ssl_object")
            if tls is None or tls.selected_alpn_protocol() != "nebula-game/1":
                raise Denied("tls")
            peer = writer.get_extra_info("peername")
            source = peer[0] if isinstance(peer, tuple) else ""
            now = time.monotonic()
            self.attempts = {ip: values for ip, values in self.attempts.items() if values[0] + 10 > now}
            began, count = self.attempts.get(source, (now, 0))
            if count >= 8 or len(self.attempts) >= 4096:
                raise Denied("rate")
            self.attempts[source] = (began, count + 1)
            header = await asyncio.wait_for(reader.readexactly(8), 5)
            magic, port, length = struct.unpack(">4sHH", header)
            if magic != b"NRT1" or length != 85:
                raise Denied("preamble")
            raw = await asyncio.wait_for(reader.readexactly(length), 5)
            authorization = raw.decode("ascii")
            async with self.password_work:
                actor = await asyncio.wait_for(asyncio.to_thread(self.authority.resolve, port, authorization), 5)
            del raw, authorization
            local, upstream = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", port), 5)
            writer.write(b"OK01")
            await asyncio.wait_for(writer.drain(), 5)

            async def client_to_server():
                bound = False
                expires = time.monotonic() + 30
                frames = 0
                while not bound:
                    remaining = expires - time.monotonic()
                    if remaining <= 0 or frames >= 256:
                        raise Denied("identity_timeout")
                    batch = await read_frame(reader, min(remaining, 30))
                    outputs, bound = first_identity_frame(batch, actor["guid"])
                    for output in outputs:
                        await write_frame(upstream, output)
                    frames += 1
                while True:
                    batch = await read_frame(reader, 120)
                    outputs, still_bound = first_identity_frame(batch, actor["guid"], True)
                    if not still_bound:
                        raise Denied("application_identity")
                    for output in outputs:
                        await write_frame(upstream, output)

            async def revalidate():
                until = time.monotonic() + MAX_LIFETIME
                while time.monotonic() < until:
                    await asyncio.sleep(2)
                    await asyncio.to_thread(self.authority.resolve, port, None, actor)
                raise Denied("lifetime")

            jobs = [asyncio.create_task(client_to_server()),
                    asyncio.create_task(self.relay(local, writer)),
                    asyncio.create_task(revalidate())]
            await asyncio.wait(jobs, return_when=asyncio.FIRST_COMPLETED)
        except (AccessDenied, Denied, OSError, ValueError, UnicodeError, sqlite3.Error,
                asyncio.TimeoutError, asyncio.IncompleteReadError):
            pass
        finally:
            for job in jobs:
                job.cancel()
            if jobs:
                await asyncio.gather(*jobs, return_exceptions=True)
            if upstream:
                upstream.close()
                try:
                    await asyncio.wait_for(upstream.wait_closed(), 2)
                except (OSError, asyncio.TimeoutError):
                    pass
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), 2)
            except (OSError, asyncio.TimeoutError):
                pass
            self.active.discard(task)
            self.slots.release()


async def run(args):
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.minimum_version = ssl.TLSVersion.TLSv1_2
    tls.load_cert_chain(args.certificate, args.private_key)
    tls.set_alpn_protocols(["nebula-game/1"])
    service = Gateway(Authority(args.state_dir, args.first_scene_port, args.last_scene_port))
    server = await asyncio.start_server(service.serve, args.bind, args.port, ssl=tls,
                                        ssl_handshake_timeout=5, backlog=64, limit=65536)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for name in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(name, stop.set)
    try:
        async with server:
            await stop.wait()
    finally:
        server.close()
        await server.wait_closed()
        for task in tuple(service.active):
            task.cancel()
        await asyncio.gather(*tuple(service.active), return_exceptions=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--listen", action="store_true")
    parser.add_argument("--bind", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8443)
    parser.add_argument("--first-scene-port", type=int, default=28000)
    parser.add_argument("--last-scene-port", type=int, default=28031)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--certificate", type=Path, required=True)
    parser.add_argument("--private-key", type=Path, required=True)
    args = parser.parse_args()
    if not args.listen:
        parser.error("No listener started: --listen required")
    if not (1 <= args.port <= 65535 and 1024 <= args.first_scene_port <= args.last_scene_port <= 65535
            and args.last_scene_port - args.first_scene_port < 32):
        parser.error("Invalid bounded ports")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
