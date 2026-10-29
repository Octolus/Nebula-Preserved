"""Durable local gift/reward notices, separate from entitlement ownership.

Wire evidence: protocol/notification-contracts.json. Delivery/retention are
authored preservation policy. Importing this module performs no IO.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import re
import time
import uuid

from wire import PLATFORMS, ProtocolError

TICKS_EPOCH = 621355968000000000
MAX_TICKS = 3155378975999999999
ACK_KEYS = {"format_version", "event_id", "target_ps4_id", "guid", "source_username",
            "source_platform", "notification_type", "accepted_at"}


def _token(value, label, maximum=512, empty=False):
    if (not isinstance(value, str) or (not value and not empty) or len(value) > maximum
            or any(ord(c) < 32 for c in value) or "#" in value):
        raise ProtocolError("Invalid notification " + label)
    return value


def _event_id(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{32}", value) is not None


class NotificationOutbox:
    def __init__(self, store):
        self.store = store
        if store.db.atomic_depth or store.db.in_transaction:
            raise RuntimeError("Initialize notification schema before a grant transaction")
        store.db.executescript("""
            CREATE TABLE IF NOT EXISTS notification_outbox (
              event_id TEXT PRIMARY KEY, target_ps4_id TEXT NOT NULL REFERENCES profiles(ps4_id),
              source_username TEXT NOT NULL, source_platform INTEGER NOT NULL CHECK(source_platform IN (0,1)),
              notification_type INTEGER NOT NULL CHECK(notification_type IN (3,4)),
              arguments TEXT NOT NULL, ticks INTEGER NOT NULL, dedupe_key TEXT NOT NULL,
              created_at REAL NOT NULL, accepted_at REAL,
              UNIQUE(target_ps4_id,dedupe_key));
        """)

    def _account(self, ps4_id):
        _token(ps4_id, "account")
        row = self.store.db.execute("SELECT * FROM profiles WHERE ps4_id=?", (ps4_id,)).fetchone()
        if row is None:
            raise ProtocolError("Unknown notification account", 404)
        return row

    def _enqueue(self, target_ps4_id, source, notification_type, arguments, dedupe_key):
        # A notice must never outlive a rolled-back grant or commit it early.
        if not self.store.db.atomic_depth:
            raise RuntimeError("Enqueue notifications inside the entitlement Store.atomic() group")
        self._account(target_ps4_id)
        name = _token(source["username"], "source name")
        platform = PLATFORMS.get(str(source["platform"]))
        if platform is None:
            raise ProtocolError("Unsupported notification platform")
        arguments = _token(arguments, "arguments", empty=True)
        dedupe_key = _token(dedupe_key, "dedupe key", maximum=2048)
        existing = self.store.db.execute(
            "SELECT * FROM notification_outbox WHERE target_ps4_id=? AND dedupe_key=?",
            (target_ps4_id, dedupe_key)).fetchone()
        if existing:
            if (existing["source_username"], existing["source_platform"], existing["notification_type"],
                    existing["arguments"]) != (name, platform, notification_type, arguments):
                raise ProtocolError("Notification dedupe key has a different payload", 409)
            return existing["event_id"]
        created = time.time()
        event_id = uuid.uuid4().hex
        ticks = TICKS_EPOCH + int(created * 10_000_000)
        if not 0 <= ticks <= MAX_TICKS:
            raise ProtocolError("Notification timestamp is outside native DateTime range")
        self.store.db.execute("INSERT INTO notification_outbox VALUES(?,?,?,?,?,?,?,?,?,NULL)",
            (event_id, target_ps4_id, name, platform, notification_type, arguments, ticks, dedupe_key, created))
        return event_id

    def enqueue_gift(self, target_ps4_id, source_ps4_id, item_display_name, dedupe_key):
        return self._enqueue(target_ps4_id, self._account(source_ps4_id), 3,
                             _token(item_display_name, "gift display name"), dedupe_key)

    def enqueue_reward(self, target_ps4_id, dedupe_key):
        # Use the actual recipient identity, an explicit local policy. Native
        # GetguidByUsername scans remotes only; full Reward4 text also requires
        # the separately reviewed client fallback-formatting correction.
        return self._enqueue(target_ps4_id, self._account(target_ps4_id), 4, "", dedupe_key)

    def pending(self, target_ps4_id=None):
        sql = "SELECT event_id,target_ps4_id,source_username,source_platform,notification_type,arguments,ticks FROM notification_outbox WHERE accepted_at IS NULL"
        args = ()
        if target_ps4_id is not None:
            sql += " AND target_ps4_id=?"
            args = (target_ps4_id,)
        return [dict(row) for row in self.store.db.execute(sql + " ORDER BY created_at,event_id", args)]

    def acknowledge(self, event):
        if (not isinstance(event, dict) or set(event) != ACK_KEYS
                or type(event["format_version"]) is not int or event["format_version"] != 1
                or not _event_id(event["event_id"]) or type(event["source_platform"]) is not int
                or type(event["notification_type"]) is not int
                or type(event["accepted_at"]) not in (int, float)
                or not math.isfinite(event["accepted_at"])
                or event["accepted_at"] < 0 or event["accepted_at"] > time.time() + 30):
            raise ProtocolError("Malformed notification acknowledgement")
        for key in ("target_ps4_id", "guid", "source_username"):
            _token(event[key], key)
        with self.store.atomic():
            # Old sessions cannot retire a new session's durable inbox.
            latest = self.store.db.execute(
                "SELECT guid FROM sessions WHERE ps4_id=? ORDER BY created_at DESC,guid DESC LIMIT 1",
                (event["target_ps4_id"],)).fetchone()
            if latest is None or latest[0] != event["guid"]:
                raise ProtocolError("Notification acknowledgement session is not current", 403)
            row = self.store.db.execute("SELECT * FROM notification_outbox WHERE event_id=?",
                                        (event["event_id"],)).fetchone()
            if row is None or any(row[key] != event[key] for key in
                    ("target_ps4_id", "source_username", "source_platform", "notification_type")):
                raise ProtocolError("Uncorrelated notification acknowledgement", 403)
            self.store.db.execute("UPDATE notification_outbox SET accepted_at=COALESCE(accepted_at,?) WHERE event_id=?",
                                  (event["accepted_at"], event["event_id"]))
        return True

    def import_acknowledgements(self, state_dir):
        directory = Path(state_dir) / "notification-acks"
        accepted = 0
        if not directory.is_dir():
            return accepted
        for path in sorted(directory.glob("*.json")):
            match = re.fullmatch(r"([0-9a-f]{32})(?:-([0-9a-f]{32}))?", path.stem)
            if not match:
                continue
            try:
                if path.stat().st_size > 16384:
                    continue
                event = json.loads(path.read_text(encoding="utf-8-sig"))
                if event.get("event_id") != match[1] or (match[2] and event.get("guid") != match[2]):
                    continue
                self.acknowledge(event)
            except (ValueError, TypeError, AttributeError, OSError, ProtocolError):
                continue
            # Accepted files are retained: they are immutable, idempotent
            # receipts, and retaining them avoids deleting an instance writer.
            accepted += 1
        return accepted

    def export(self, state_dir):
        state_dir = Path(state_dir)
        entries = self.pending()
        if len(entries) > 10000:
            raise ProtocolError("Notification snapshot exceeds local capacity", 503)
        snapshot = {"format_version": 1, "generation": time.time(), "entries": entries}
        path = state_dir / "instance-notifications.json"
        temporary = state_dir / (".instance-notifications-" + uuid.uuid4().hex + ".tmp")
        state_dir.mkdir(parents=True, exist_ok=True)
        try:
            with temporary.open("x", encoding="utf-8") as stream:
                json.dump(snapshot, stream, ensure_ascii=False, separators=(",", ":"))
            temporary.replace(path)
        finally:
            if temporary.exists():
                temporary.unlink()
        return path
