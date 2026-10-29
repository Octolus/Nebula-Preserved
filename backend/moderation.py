"""Backend-owned moderation policy; no sockets, files or client packets.

Management authenticates/rechecks its operator and owns idempotency plus audit.
These mutation helpers enlist in that caller's existing Store.atomic() group.
Session tombstones are permanent: expiry/unban never resurrect an old GUID.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
import unicodedata
import uuid
from datetime import datetime, timezone

from public_access import current_actor, require_actor
from wire import ProtocolError

MAX_UTC = 253402300799
REQUEST_ID = re.compile(r"[0-9a-f]{32}\Z")
GUID = re.compile(r"[0-9a-f]{32}\Z")
REPORT_ID = re.compile(r"[0-9a-f]{64}\Z")
OPERATOR_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)


def require(condition, message, status=400):
    if not condition:
        raise ProtocolError(message, status)


def wire_text(value, label, maximum=512, *, empty=False):
    require(isinstance(value, str) and len(value) <= maximum
            and (empty or bool(value.strip())) and "#" not in value
            and not any(unicodedata.category(c).startswith("C") for c in value),
            "Invalid " + label)
    return value


def report_id(guid, target, option):
    """Stable identifier; old report content and ambiguous targets stay intact."""
    return hashlib.sha256(canonical([guid, target, option]).encode("ascii")).hexdigest()


def session_token(value, *, status=400):
    """Store historically accepts opaque tokens; native channel IDs stay stricter."""
    try:
        return wire_text(value, "session identifier", 128)
    except ProtocolError:
        raise ProtocolError("Invalid session identifier", status) from None


class Moderation:
    def __init__(self, store, *, clock=None):
        self.store, self.db = store, store.db
        self.clock = time.time if clock is None else clock
        require(callable(self.clock), "A moderation clock is required")
        require(not self.db.in_transaction and not self.db.atomic_depth,
                "Moderation schema requires an idle Store")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS moderation_accounts (
                ps4_id TEXT PRIMARY KEY REFERENCES profiles,
                ban_enabled INTEGER NOT NULL DEFAULT 0 CHECK(ban_enabled IN (0,1)),
                ban_expires_at INTEGER, ban_reason TEXT NOT NULL DEFAULT '',
                mute_enabled INTEGER NOT NULL DEFAULT 0 CHECK(mute_enabled IN (0,1)),
                mute_expires_at INTEGER, mute_reason TEXT NOT NULL DEFAULT '');
            CREATE TABLE IF NOT EXISTS moderation_revoked_sessions (
                guid TEXT PRIMARY KEY, ps4_id TEXT NOT NULL REFERENCES profiles,
                request_id TEXT NOT NULL, revoked_at INTEGER NOT NULL, reason TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS moderation_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT NOT NULL UNIQUE,
                actor_id TEXT NOT NULL, actor_role TEXT NOT NULL, operation TEXT NOT NULL,
                target_id TEXT NOT NULL, reason TEXT NOT NULL, before_json TEXT NOT NULL,
                after_json TEXT NOT NULL, created_at INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS moderation_maintenance (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                started_at INTEGER NOT NULL, end_at INTEGER NOT NULL, reason TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS local_reports (
                guid TEXT NOT NULL,target TEXT NOT NULL,option INTEGER NOT NULL,
                text TEXT NOT NULL,created_at REAL NOT NULL,PRIMARY KEY(guid,target,option));
            CREATE TABLE IF NOT EXISTS moderation_report_index (
                report_id TEXT PRIMARY KEY, guid TEXT NOT NULL, target TEXT NOT NULL,
                option INTEGER NOT NULL, UNIQUE(guid,target,option),
                FOREIGN KEY(guid,target,option) REFERENCES local_reports(guid,target,option));
            CREATE TABLE IF NOT EXISTS moderation_report_reviews (
                report_id TEXT PRIMARY KEY REFERENCES moderation_report_index,
                status TEXT NOT NULL CHECK(status IN ('open','resolved','dismissed')),
                note TEXT NOT NULL, actor_id TEXT NOT NULL, updated_at INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS moderation_news (
                news_id TEXT PRIMARY KEY, text TEXT NOT NULL, date_label TEXT NOT NULL,
                created_at INTEGER NOT NULL, expires_at INTEGER,
                active INTEGER NOT NULL CHECK(active IN (0,1)));
            CREATE TRIGGER IF NOT EXISTS moderation_events_no_update BEFORE UPDATE ON moderation_events
                BEGIN SELECT RAISE(ABORT,'Moderation history is append-only'); END;
            CREATE TRIGGER IF NOT EXISTS moderation_events_no_delete BEFORE DELETE ON moderation_events
                BEGIN SELECT RAISE(ABORT,'Moderation history is append-only'); END;
            CREATE TRIGGER IF NOT EXISTS moderation_revocations_no_update BEFORE UPDATE ON moderation_revoked_sessions
                BEGIN SELECT RAISE(ABORT,'Session revocations are permanent'); END;
            CREATE TRIGGER IF NOT EXISTS moderation_revocations_no_delete BEFORE DELETE ON moderation_revoked_sessions
                BEGIN SELECT RAISE(ABORT,'Session revocations are permanent'); END;
            CREATE TRIGGER IF NOT EXISTS moderation_report_index_no_update BEFORE UPDATE ON moderation_report_index
                BEGIN SELECT RAISE(ABORT,'Report identity is immutable'); END;
            CREATE TRIGGER IF NOT EXISTS moderation_report_index_no_delete BEFORE DELETE ON moderation_report_index
                BEGIN SELECT RAISE(ABORT,'Report identity is immutable'); END;
            CREATE TRIGGER IF NOT EXISTS moderation_reports_no_update BEFORE UPDATE ON local_reports
                BEGIN SELECT RAISE(ABORT,'Report receipts are append-only'); END;
            CREATE TRIGGER IF NOT EXISTS moderation_reports_no_delete BEFORE DELETE ON local_reports
                BEGIN SELECT RAISE(ABORT,'Report receipts are append-only'); END;
            CREATE TRIGGER IF NOT EXISTS moderation_news_no_rewrite BEFORE UPDATE ON moderation_news
                WHEN NEW.news_id IS NOT OLD.news_id OR NEW.text IS NOT OLD.text
                  OR NEW.date_label IS NOT OLD.date_label OR NEW.created_at IS NOT OLD.created_at
                  OR NEW.expires_at IS NOT OLD.expires_at OR NEW.active != 0
                BEGIN SELECT RAISE(ABORT,'News content is immutable; archive it instead'); END;
            CREATE TRIGGER IF NOT EXISTS moderation_news_no_delete BEFORE DELETE ON moderation_news
                BEGIN SELECT RAISE(ABORT,'News history cannot be deleted'); END;
        """)
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(moderation_accounts)")}
        if "staff_label" not in columns:
            self.db.execute("ALTER TABLE moderation_accounts ADD COLUMN staff_label TEXT NOT NULL DEFAULT ''")
        # The compatible legacy table may already contain reports. Index those
        # original keys once at startup, including malformed historical values.
        with self.store.atomic():
            for row in self.db.execute("SELECT guid,target,option FROM local_reports"):
                self._index_report(row["guid"], row["target"], row["option"])

    def _now(self):
        value = self.clock()
        require(type(value) in (int, float) and math.isfinite(value)
                and 0 <= value <= MAX_UTC, "Moderation clock is unavailable", 503)
        return value

    def _atomic(self):
        require(self.db.atomic_depth > 0 and self.db.in_transaction,
                "Moderation mutation requires the caller's Store.atomic()", 409)

    def _mutation(self, actor, request_id, reason):
        self._atomic()
        require(current_actor() is None, "Player credentials cannot authorize moderation", 403)
        require(isinstance(actor, dict) and isinstance(actor.get("id"), str)
                and OPERATOR_ID.fullmatch(actor["id"])
                and actor.get("role") in ("owner", "admin", "moderator"),
                "A verified management actor is required", 403)
        require(isinstance(request_id, str) and REQUEST_ID.fullmatch(request_id),
                "Invalid moderation request ID")
        wire_text(reason, "moderation reason")
        require(self.db.execute("SELECT 1 FROM moderation_events WHERE request_id=?",
                                (request_id,)).fetchone() is None,
                "Moderation request was already committed; replay its management receipt", 409)
        return int(self._now())

    def _account(self, account_id):
        wire_text(account_id, "account ID", 128)
        require(self.db.execute("SELECT 1 FROM profiles WHERE ps4_id=?", (account_id,)).fetchone()
                is not None, "Account not found", 404)

    def _policy(self, account_id):
        row = self.db.execute("SELECT * FROM moderation_accounts WHERE ps4_id=?", (account_id,)).fetchone()
        return dict(row) if row else {"ps4_id": account_id, "ban_enabled": 0,
                                     "ban_expires_at": None, "ban_reason": "",
                                     "mute_enabled": 0, "mute_expires_at": None, "mute_reason": "",
                                     "staff_label": ""}

    def _online(self, account_id):
        row = self.db.execute("SELECT online FROM profile_state WHERE ps4_id=?", (account_id,)).fetchone()
        return row[0] if row else 0

    @staticmethod
    def _active(policy, kind, now):
        return bool(policy[kind + "_enabled"] and
                    (policy[kind + "_expires_at"] is None or now < policy[kind + "_expires_at"]))

    def status(self, account_id):
        self._account(account_id)
        policy, now = self._policy(account_id), self._now()
        return {"account_id": account_id,
                "banned": self._active(policy, "ban", now),
                "ban_expires_at": policy["ban_expires_at"], "ban_reason": policy["ban_reason"],
                "muted": self._active(policy, "mute", now),
                "mute_expires_at": policy["mute_expires_at"], "mute_reason": policy["mute_reason"],
                "role": "player", "staff_label": policy["staff_label"],
                "maintenance": self.maintenance_minutes()}

    def ensure_allowed(self, account_id, guid=None):
        # Called before a new account/session is inserted too. No account()
        # lookup, current_guid() recursion, row creation or expiry cleanup.
        wire_text(account_id, "account ID", 128)
        require(not self._active(self._policy(account_id), "ban", self._now()),
                "Account is banned", 403)
        if guid is not None:
            session_token(guid, status=403)
            require(self.db.execute("SELECT 1 FROM moderation_revoked_sessions WHERE guid=?", (guid,)).fetchone()
                    is None, "Session has been revoked", 403)
        return True

    def _expires(self, expires_at):
        require(expires_at is None or (type(expires_at) is int
                and self._now() < expires_at <= MAX_UTC),
                "Expiry must be a future UTC integer second or null")

    def _event(self, request_id, actor, operation, target, reason, before, after, now):
        self.db.execute("""INSERT INTO moderation_events
            (request_id,actor_id,actor_role,operation,target_id,reason,before_json,after_json,created_at)
            VALUES(?,?,?,?,?,?,?,?,?)""",
            (request_id, actor["id"], actor["role"], operation, target, reason,
             canonical(before), canonical(after), now))

    def _revoke(self, account_id, guids, request_id, reason, now):
        added = []
        for guid in guids:
            session_token(guid)
            cursor = self.db.execute("INSERT OR IGNORE INTO moderation_revoked_sessions VALUES(?,?,?,?,?)",
                                     (guid, account_id, request_id, now, reason))
            if cursor.rowcount: added.append(guid)
        return added

    def _set_policy(self, account_id, kind, enabled, *, expires_at, reason, actor, request_id):
        now = self._mutation(actor, request_id, reason)
        self._account(account_id)
        if enabled: self._expires(expires_at)
        before = {**self._policy(account_id), "online": self._online(account_id)}
        self.db.execute("INSERT OR IGNORE INTO moderation_accounts(ps4_id) VALUES(?)", (account_id,))
        # kind is only a private constant supplied by the four public methods.
        self.db.execute("UPDATE moderation_accounts SET " + kind + "_enabled=?," + kind +
                        "_expires_at=?," + kind + "_reason=? WHERE ps4_id=?",
                        (int(enabled), expires_at if enabled else None, reason if enabled else "", account_id))
        revoked = []
        if enabled and kind == "ban":
            guids = [r[0] for r in self.db.execute("SELECT guid FROM sessions WHERE ps4_id=? ORDER BY guid", (account_id,))]
            revoked = self._revoke(account_id, guids, request_id, reason, now)
            self.db.execute("UPDATE profile_state SET online=0 WHERE ps4_id=?", (account_id,))
        after = {**self._policy(account_id), "online": self._online(account_id)}
        changed = before != after or bool(revoked)
        after = {**after, "newly_revoked_guids": revoked}
        self._event(request_id, actor, kind if enabled else "un" + kind, account_id,
                    reason, before, after, now)
        return before, after, changed

    def ban(self, account_id, *, expires_at=None, reason, actor, request_id):
        return self._set_policy(account_id, "ban", True, expires_at=expires_at,
                                reason=reason, actor=actor, request_id=request_id)

    def unban(self, account_id, *, reason, actor, request_id):
        return self._set_policy(account_id, "ban", False, expires_at=None,
                                reason=reason, actor=actor, request_id=request_id)

    def mute(self, account_id, *, expires_at=None, reason, actor, request_id):
        return self._set_policy(account_id, "mute", True, expires_at=expires_at,
                                reason=reason, actor=actor, request_id=request_id)

    def unmute(self, account_id, *, reason, actor, request_id):
        return self._set_policy(account_id, "mute", False, expires_at=None,
                                reason=reason, actor=actor, request_id=request_id)

    def set_staff_label(self, account_id, label, *, reason, actor, request_id):
        now = self._mutation(actor, request_id, reason)
        require(actor["role"] == "owner", "Only an owner may assign a player display label", 403)
        self._account(account_id)
        wire_text(label, "staff display label", 32, empty=True)
        require("<" not in label and ">" not in label, "Staff display labels must be plain text")
        before = {"account_id": account_id, "staff_label": self._policy(account_id)["staff_label"]}
        self.db.execute("INSERT OR IGNORE INTO moderation_accounts(ps4_id) VALUES(?)", (account_id,))
        self.db.execute("UPDATE moderation_accounts SET staff_label=? WHERE ps4_id=?", (label, account_id))
        after = {"account_id": account_id, "staff_label": label}
        self._event(request_id, actor, "players.staff", account_id, reason, before, after, now)
        return before, after, before != after

    def kick(self, account_id, *, guid=None, reason, actor, request_id):
        now = self._mutation(actor, request_id, reason)
        self._account(account_id)
        row = self.db.execute("SELECT guid FROM sessions WHERE ps4_id=? ORDER BY created_at DESC,guid DESC LIMIT 1",
                              (account_id,)).fetchone()
        current = row[0] if row else None
        if guid is not None:
            session_token(guid)
            require(guid == current, "Kick target is not the account's current session", 409)
        before = {"account_id": account_id, "current_guid": current,
                  "revoked": bool(current and self.db.execute(
                      "SELECT 1 FROM moderation_revoked_sessions WHERE guid=?", (current,)).fetchone()),
                  "online": self._online(account_id)}
        revoked = self._revoke(account_id, [current] if current else [], request_id, reason, now)
        self.db.execute("UPDATE profile_state SET online=0 WHERE ps4_id=?", (account_id,))
        after = {**before, "revoked": bool(current), "newly_revoked_guids": revoked,
                 "online": self._online(account_id)}
        self._event(request_id, actor, "kick", account_id, reason, before, after, now)
        return before, after, bool(revoked) or before["online"] != after["online"]

    def maintenance_minutes(self):
        row = self.db.execute("SELECT end_at FROM moderation_maintenance WHERE singleton=1").fetchone()
        return max(0, math.ceil((row[0] - self._now()) / 60)) if row else 0

    def maintenance(self):
        row = self.db.execute("SELECT started_at,end_at,reason FROM moderation_maintenance WHERE singleton=1").fetchone()
        return {"started_at": row[0] if row else None, "end_at": row[1] if row else None,
                "reason": row[2] if row else "", "minutes": self.maintenance_minutes()}

    def set_maintenance(self, minutes, *, reason, actor, request_id):
        now = self._mutation(actor, request_id, reason)
        require(type(minutes) is int and 0 <= minutes <= 1440, "Maintenance minutes must be an integer from 0 to 1440")
        end = now + minutes * 60
        require(end <= MAX_UTC, "Maintenance deadline exceeds supported UTC range")
        before = self.maintenance()
        self.db.execute("INSERT INTO moderation_maintenance VALUES(1,?,?,?) ON CONFLICT(singleton) "
                        "DO UPDATE SET started_at=excluded.started_at,end_at=excluded.end_at,reason=excluded.reason",
                        (now, end, reason))
        after = self.maintenance()
        self._event(request_id, actor, "maintenance", "global", reason, before, after, now)
        return before, after, before != after

    def publish_news(self, text, expires_at=None, *, reason, actor, request_id):
        now = self._mutation(actor, request_id, reason)
        require(actor["role"] in ("owner", "admin"), "News publication requires an admin or owner", 403)
        wire_text(text, "news text", 1000)
        self._expires(expires_at)
        identity = str(uuid.UUID(hex=request_id))
        date_label = datetime.fromtimestamp(now, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        wire_text(date_label, "news UTC date", 64)
        self.db.execute("INSERT INTO moderation_news VALUES(?,?,?,?,?,1)",
                        (identity, text, date_label, now, expires_at))
        after = dict(self.db.execute("SELECT * FROM moderation_news WHERE news_id=?", (identity,)).fetchone())
        self._event(request_id, actor, "news.publish", identity, reason, None, after, now)
        return None, after, True

    def archive_news(self, identity, *, reason, actor, request_id):
        now = self._mutation(actor, request_id, reason)
        require(actor["role"] in ("owner", "admin"), "News archival requires an admin or owner", 403)
        require(isinstance(identity, str), "Invalid news ID")
        try:
            require(str(uuid.UUID(identity)) == identity, "Invalid news ID")
        except (ValueError, AttributeError):
            raise ProtocolError("Invalid news ID") from None
        row = self.db.execute("SELECT * FROM moderation_news WHERE news_id=?", (identity,)).fetchone()
        require(row is not None, "News not found", 404)
        before = dict(row)
        self.db.execute("UPDATE moderation_news SET active=0 WHERE news_id=? AND active=1", (identity,))
        after = {**before, "active": 0}
        self._event(request_id, actor, "news.archive", identity, reason, before, after, now)
        return before, after, before != after

    def news(self, limit=100):
        require(type(limit) is int and 1 <= limit <= 100, "News limit must be from 1 to 100")
        return [dict(row) for row in self.db.execute("SELECT * FROM moderation_news WHERE active=1 "
                "AND (expires_at IS NULL OR expires_at>?) ORDER BY created_at DESC,news_id DESC LIMIT ?",
                (self._now(), limit))]

    def _index_report(self, guid, target, option):
        identity = report_id(guid, target, option)
        self.db.execute("INSERT OR IGNORE INTO moderation_report_index VALUES(?,?,?,?)",
                        (identity, guid, target, option))
        row = self.db.execute("SELECT guid,target,option FROM moderation_report_index WHERE report_id=?", (identity,)).fetchone()
        require(row is not None and tuple(row) == (guid, target, option), "Report identity collision", 409)
        return identity

    def record_report(self, guid, target, option, text):
        self._atomic()
        require(isinstance(guid, str) and GUID.fullmatch(guid), "Invalid report session")
        session = self.db.execute("SELECT ps4_id FROM sessions WHERE guid=?", (guid,)).fetchone()
        require(session is not None, "Unknown report session", 403)
        require_actor(session[0])
        self.ensure_allowed(session[0], guid)
        latest = self.db.execute("SELECT guid FROM sessions WHERE ps4_id=? ORDER BY created_at DESC,guid DESC LIMIT 1",
                                 (session[0],)).fetchone()
        require(latest is not None and latest[0] == guid, "Report requires the current session", 403)
        wire_text(target, "report target", 128)
        wire_text(text, "report text", 512, empty=True)
        require(type(option) is int and 0 <= option <= 2, "Invalid report option")
        accepted = self.db.execute("INSERT OR IGNORE INTO local_reports VALUES(?,?,?,?,?)",
                                   (guid, target, option, text, self._now())).rowcount == 1
        self._index_report(guid, target, option)
        return accepted

    def reports(self, limit=100, offset=0):
        require(type(limit) is int and 1 <= limit <= 100 and type(offset) is int
                and 0 <= offset <= 1_000_000_000, "Invalid report pagination")
        return [dict(row) for row in self.db.execute("""SELECT i.report_id,r.guid,r.target,r.option,r.text,
            r.created_at,s.ps4_id AS reporter_account_id,COALESCE(v.status,'open') AS status,
            COALESCE(v.note,'') AS note,v.actor_id,v.updated_at
            FROM moderation_report_index i JOIN local_reports r USING(guid,target,option)
            LEFT JOIN sessions s ON s.guid=r.guid LEFT JOIN moderation_report_reviews v USING(report_id)
            ORDER BY r.created_at DESC,i.report_id LIMIT ? OFFSET ?""", (limit, offset))]

    def review_report(self, identity, status, note, *, reason, actor, request_id):
        now = self._mutation(actor, request_id, reason)
        require(isinstance(identity, str) and REPORT_ID.fullmatch(identity), "Invalid report ID")
        require(isinstance(status, str) and status in ("open", "resolved", "dismissed"), "Invalid report status")
        wire_text(note, "report review note", 512, empty=True)
        require(self.db.execute("SELECT 1 FROM moderation_report_index WHERE report_id=?", (identity,)).fetchone()
                is not None, "Report not found", 404)
        row = self.db.execute("SELECT status,note,actor_id,updated_at FROM moderation_report_reviews WHERE report_id=?", (identity,)).fetchone()
        before = dict(row) if row else {"status": "open", "note": "", "actor_id": None, "updated_at": None}
        self.db.execute("INSERT INTO moderation_report_reviews VALUES(?,?,?,?,?) ON CONFLICT(report_id) DO UPDATE SET "
                        "status=excluded.status,note=excluded.note,actor_id=excluded.actor_id,updated_at=excluded.updated_at",
                        (identity, status, note, actor["id"], now))
        after = {"status": status, "note": note, "actor_id": actor["id"], "updated_at": now}
        self._event(request_id, actor, "report.review", identity, reason, before, after, now)
        return before, after, before != after
