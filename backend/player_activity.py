"""Login, session, IP and live server monitoring for operators.

Two halves share one SQLite schema in the backend's own database:

* ``ActivityRecorder`` captures login/session/IP events. It is attached to the
  running Backend's Store and fed by tiny, failure-isolated hooks (an HTTP
  response observer in server.py and an optional gateway spool). A monitoring
  failure never changes a game response: every hook catches and reports.
* ``PlayerActivity`` is the read-only operator view routed by management.py.

IP addresses and geolocation are operator-only data: they are returned by the
authenticated management API and never written to stdout diagnostics. Geo
lookups run in a background task (at most one request per second) and never on
a game request path. See docs/PRIVACY.md for retention and disclosure.
"""
from __future__ import annotations

import asyncio
import calendar
from collections import OrderedDict
import ipaddress
import json
import os
from pathlib import Path
import re
import sys
import time

GEOIP_DEFAULT_URL = "https://json.geoiplookup.io/{ip}"
GEO_REFRESH_SECONDS = 30 * 86400
GEO_RETRY_SECONDS = 3600
GEO_BACKOFF_SECONDS = 60
GEO_MAX_BYTES = 64 * 1024
TOUCH_INTERVAL = 30.0
TICK_INTERVAL = 5.0
IN_WORLD_FRESH = 30.0
PRUNE_INTERVAL = 86400.0
DEDUPE_SECONDS = 60.0
MAX_MEMORY_KEYS = 4096
MAX_INSTANCES_PER_SESSION = 64
FAILURE_TAIL_BYTES = 256 * 1024
FAILURE_FILES = ("backend-failures.jsonl", "gateway.jsonl")
SPOOL_PATTERN = re.compile(r"gateway-activity-[0-9]{8}\.jsonl\Z")
SPOOL_MAX_FILE = 16 * 1024 * 1024
SPOOL_READ_CHUNK = 1024 * 1024
GUID = re.compile(r"[0-9a-f]{32}\Z")
LOGIN_ROUTES = frozenset(("ChannelGUIDServlet", "N2UserExist", "UserExistsServlet", "N2AddUser"))
STATUS_REASONS = {400: "invalid_request", 401: "access_denied", 403: "access_denied", 404: "unknown_account",
                  409: "identity_conflict", 429: "rate_limited", 501: "unsupported", 503: "unavailable"}
GATEWAY_FAILURES = frozenset(("credential", "access_denied", "banned", "revoked_session", "allocation", "port",
                              "preamble", "rate", "instance", "moderation_unavailable", "changed"))
GEO_FIELDS = ("country", "country_code", "region", "city", "isp", "org", "asn", "timezone",
              "connection_type", "hostname")

SCHEMA = """
    CREATE TABLE IF NOT EXISTS activity_sessions (
        session_id INTEGER PRIMARY KEY AUTOINCREMENT,
        guid TEXT NOT NULL UNIQUE, account_id TEXT NOT NULL,
        ip TEXT, platform TEXT, client_version TEXT,
        started_at REAL NOT NULL, last_seen_at REAL NOT NULL, in_world_at REAL,
        ended_at REAL, end_reason TEXT,
        instances_json TEXT NOT NULL DEFAULT '[]',
        gateway_ip TEXT, gateway_connections INTEGER NOT NULL DEFAULT 0,
        gateway_closed_at REAL, gateway_close_reason TEXT);
    CREATE INDEX IF NOT EXISTS activity_sessions_account ON activity_sessions(account_id,started_at);
    CREATE INDEX IF NOT EXISTS activity_sessions_open ON activity_sessions(ended_at,last_seen_at);
    CREATE INDEX IF NOT EXISTS activity_sessions_started ON activity_sessions(started_at);
    CREATE INDEX IF NOT EXISTS activity_sessions_ip ON activity_sessions(ip);
    CREATE INDEX IF NOT EXISTS activity_sessions_gateway_ip ON activity_sessions(gateway_ip);
    CREATE TABLE IF NOT EXISTS activity_logins (
        event_id INTEGER PRIMARY KEY AUTOINCREMENT, created_at REAL NOT NULL,
        account_id TEXT, ip TEXT, route TEXT NOT NULL,
        result TEXT NOT NULL CHECK(result IN ('success','failure')), reason TEXT,
        platform TEXT, client_version TEXT, session_id INTEGER);
    CREATE INDEX IF NOT EXISTS activity_logins_created ON activity_logins(created_at);
    CREATE INDEX IF NOT EXISTS activity_logins_account ON activity_logins(account_id,created_at);
    CREATE INDEX IF NOT EXISTS activity_logins_ip ON activity_logins(ip);
    CREATE TABLE IF NOT EXISTS activity_geo (
        ip TEXT PRIMARY KEY, status TEXT NOT NULL CHECK(status IN ('ok','failed','private')),
        data_json TEXT, error TEXT, fetched_at REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS activity_peaks (
        hour INTEGER PRIMARY KEY, peak_online INTEGER NOT NULL, sampled_at REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS activity_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def _report(event, error):
    """Bounded diagnostics: exception type only, never values or addresses."""
    try:
        from diagnostic_logging import emit
        emit(event, ("activity", event, type(error).__name__), level="warning",
             task="player_activity", error_type=type(error).__name__)
    except Exception:
        try:
            print(json.dumps({"event": event, "error_type": type(error).__name__}), file=sys.stderr, flush=True)
        except Exception:
            pass


def _flag(value, default=True):
    if value is None or str(value).strip() == "":
        return default
    return str(value).strip().lower() not in ("0", "false", "no", "off", "disabled")


def _number(value, default, low, high):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return min(high, max(low, result)) if result == result else default


def normalize_ip(value):
    """Canonical text for a literal IPv4/IPv6 address, or None."""
    if not isinstance(value, str) or not value or len(value) > 64:
        return None
    try:
        address = ipaddress.ip_address(value.strip())
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return str(address)


def public_ip(value):
    ip = normalize_ip(value)
    return ip is not None and ipaddress.ip_address(ip).is_global


def trusted_networks(text):
    networks = []
    for part in (text or "127.0.0.0/8,::1/128").split(","):
        try:
            networks.append(ipaddress.ip_network(part.strip(), strict=False))
        except ValueError:
            continue
    return networks


def ensure_schema(db):
    if db.in_transaction or getattr(db, "atomic_depth", 0):
        raise RuntimeError("Activity schema requires an idle Store")
    db.executescript(SCHEMA)
    db.commit()


def _text(value, maximum=128):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        value = str(value)
    if not isinstance(value, str):
        return None
    value = "".join(c for c in value.strip() if c.isprintable())
    return value[:maximum] or None


def normalize_geo(raw):
    """Keep only coarse provider fields; latitude/longitude are not stored."""
    if not isinstance(raw, dict):
        return None
    asn = raw.get("asn") or raw.get("asn_number")
    if raw.get("asn_org") and raw.get("asn_number") and not raw.get("asn"):
        asn = "AS" + str(raw["asn_number"]) + " " + str(raw["asn_org"])
    value = {"country": raw.get("country_name") or raw.get("country"),
             "country_code": raw.get("country_code"), "region": raw.get("region"),
             "city": raw.get("city"), "isp": raw.get("isp"), "org": raw.get("org"), "asn": asn,
             "timezone": raw.get("timezone_name") or raw.get("timezone"),
             "connection_type": raw.get("connection_type"), "hostname": raw.get("hostname")}
    return {key: _text(value[key]) for key in GEO_FIELDS}


async def default_fetch(url, timeout=5.0):
    import aiohttp
    client_timeout = aiohttp.ClientTimeout(total=timeout)
    async with aiohttp.ClientSession(timeout=client_timeout) as session:
        async with session.get(url, headers={"Accept": "application/json"}, allow_redirects=False) as response:
            if response.status != 200:
                raise RuntimeError("Geo lookup HTTP status " + str(response.status))
            body = await response.content.read(GEO_MAX_BYTES + 1)
            if len(body) > GEO_MAX_BYTES:
                raise ValueError("Geo lookup response too large")
            return json.loads(body.decode("utf-8"))


class ActivityRecorder:
    def __init__(self, store, *, environ=None, clock=None, fetch=None):
        environ = os.environ if environ is None else environ
        self.store, self.db = store, store.db
        self.state_dir = Path(getattr(store, "state_dir", "."))
        self.clock = time.time if clock is None else clock
        self.fetch = default_fetch if fetch is None else fetch
        self.geo_enabled = _flag(environ.get("NEBULA_GEOIP_ENABLED"), True)
        url = environ.get("NEBULA_GEOIP_URL") or GEOIP_DEFAULT_URL
        self.geo_url = url if "{ip}" in url and url.startswith(("https://", "http://")) else GEOIP_DEFAULT_URL
        self.retention_days = _number(environ.get("NEBULA_ACTIVITY_RETENTION_DAYS"), 90.0, 1.0, 3650.0)
        self.idle_seconds = 60 * _number(environ.get("NEBULA_ACTIVITY_IDLE_MINUTES"), 5.0, 1.0, 1440.0)
        self.trusted = trusted_networks(environ.get("NEBULA_TRUSTED_PROXIES"))
        self.spool_dir = spool_directory(environ, self.state_dir / "logs")
        self.geo_last_error = None
        self.geo_backoff_until = 0.0
        self.geo_lookups = 0
        self._geo_queue = OrderedDict()
        self._touched = OrderedDict()
        self._versions = OrderedDict()
        self._dedupe = OrderedDict()
        self._last_tick = 0.0
        self._task = None
        ensure_schema(self.db)
        try:
            self.prune()
        except Exception as error:
            _report("activity_prune_failed", error)

    # ----------------------------------------------------------------- helpers
    @staticmethod
    def _remember(mapping, key, value):
        mapping[key] = value
        mapping.move_to_end(key)
        while len(mapping) > MAX_MEMORY_KEYS:
            mapping.popitem(last=False)

    def _idle_db(self):
        return not self.db.in_transaction and not getattr(self.db, "atomic_depth", 0)

    def _meta(self, key, default=None):
        row = self.db.execute("SELECT value FROM activity_meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def _set_meta(self, key, value):
        self.db.execute("INSERT INTO activity_meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (key, str(value)))

    def _duplicate(self, key, now):
        previous = self._dedupe.get(key)
        if previous is not None and now - previous < DEDUPE_SECONDS:
            return True
        self._remember(self._dedupe, key, now)
        return False

    def client_ip(self, request):
        """Peer address; X-Real-IP only when the TCP peer is a trusted proxy.

        X-Forwarded-For is ignored: nginx forwards a client-supplied value
        unchanged unless explicitly configured, so it is never authoritative.
        """
        peer = normalize_ip(getattr(request, "remote", None))
        if peer is None:
            return None
        address = ipaddress.ip_address(peer)
        if any(address in network for network in self.trusted):
            headers = getattr(request, "headers", {}) or {}
            forwarded = normalize_ip(headers.get("X-Real-IP"))
            if forwarded is not None:
                return forwarded
        return peer

    # ----------------------------------------------------------------- capture
    def record_login(self, *, account_id, ip, route, result, reason=None, platform=None,
                     client_version=None, session_id=None, now=None):
        now = self.clock() if now is None else now
        with self.db:
            self.db.execute("""INSERT INTO activity_logins(created_at,account_id,ip,route,result,reason,platform,
                client_version,session_id) VALUES(?,?,?,?,?,?,?,?,?)""",
                            (now, _text(account_id), normalize_ip(ip), _text(route, 64), result,
                             _text(reason, 64), _text(platform, 64), _text(client_version, 64), session_id))
        self.want_geo([ip])

    def start_session(self, guid, account_id, ip, *, platform=None, client_version=None,
                      route="ChannelGUIDServlet", now=None):
        now = self.clock() if now is None else now
        ip = normalize_ip(ip)
        client_version = client_version or self._versions.get(account_id)
        row = self.db.execute("SELECT session_id FROM activity_sessions WHERE guid=?", (guid,)).fetchone()
        if row is not None:
            with self.db:
                self.db.execute("""UPDATE activity_sessions SET last_seen_at=MAX(last_seen_at,?),
                    ip=COALESCE(ip,?) WHERE session_id=? AND ended_at IS NULL""", (now, ip, row[0]))
            return row[0]
        self.reconcile(now)
        with self.db:
            # A newer login supersedes any still-open session for this account.
            self.db.execute("""UPDATE activity_sessions SET ended_at=MAX(started_at,MIN(?,last_seen_at+?)),
                end_reason=CASE WHEN ?-last_seen_at<=? THEN 'replaced' ELSE 'timeout' END
                WHERE account_id=? AND ended_at IS NULL""",
                            (now, self.idle_seconds, now, self.idle_seconds, account_id))
            cursor = self.db.execute("""INSERT INTO activity_sessions(guid,account_id,ip,platform,client_version,
                started_at,last_seen_at) VALUES(?,?,?,?,?,?,?)""",
                                     (guid, account_id, ip, _text(platform, 64), _text(client_version, 64), now, now))
            session_id = cursor.lastrowid
            self.db.execute("""INSERT INTO activity_logins(created_at,account_id,ip,route,result,reason,platform,
                client_version,session_id) VALUES(?,?,?,?,'success',NULL,?,?,?)""",
                            (now, account_id, ip, route, _text(platform, 64), _text(client_version, 64), session_id))
        self._remember(self._touched, guid, now)
        self.want_geo([ip])
        return session_id

    def touch(self, guid, now=None):
        now = self.clock() if now is None else now
        last = self._touched.get(guid)
        if last is not None and now - last < TOUCH_INTERVAL:
            return
        self._remember(self._touched, guid, now)
        with self.db:
            self.db.execute("UPDATE activity_sessions SET last_seen_at=MAX(last_seen_at,?) WHERE guid=? AND ended_at IS NULL",
                            (now, guid))

    def _failure_reason(self, status, account_id=None, guid=None):
        try:
            if account_id:
                row = self.db.execute("SELECT ban_enabled,ban_expires_at FROM moderation_accounts WHERE ps4_id=?",
                                      (account_id,)).fetchone()
                if row and row[0] == 1 and (row[1] is None or row[1] > self.clock()):
                    return "banned"
            if guid and self.db.execute("SELECT 1 FROM moderation_revoked_sessions WHERE guid=?", (guid,)).fetchone():
                return "revoked_session"
        except Exception:
            pass
        if status >= 500 and status not in STATUS_REASONS:
            return "server_error"
        return STATUS_REASONS.get(status, "http_" + str(status))

    def observe(self, request, command, response):
        """Inspect one finished game HTTP exchange. Called after the response exists."""
        status = int(getattr(response, "status", 0) or 0)
        interesting = command in LOGIN_ROUTES or status == 200 or status in (401, 403)
        if not interesting or not self._idle_db():
            return
        from wire import Request, decrypt, session_guid
        try:
            parsed = Request.parse(decrypt(request.query["data"]))
        except Exception:
            parsed = None
        fields = parsed.fields if parsed is not None else ()
        platform = parsed.platform if parsed is not None else None
        ip = self.client_ip(request)
        now = self.clock()
        if command == "ChannelGUIDServlet" and len(fields) == 2:
            account_id, request_hash = fields
            if status == 200:
                guid = session_guid(account_id, request_hash)
                bound = self.db.execute("SELECT ps4_id FROM sessions WHERE guid=?", (guid,)).fetchone()
                if bound is not None and bound[0] == account_id:
                    self.start_session(guid, account_id, ip, platform=platform, now=now)
                return
            reason = self._failure_reason(status, account_id)
            if not self._duplicate(("login", ip, account_id, reason), now):
                self.record_login(account_id=account_id, ip=ip, route=command, result="failure", reason=reason,
                                  platform=platform, client_version=self._versions.get(account_id), now=now)
            return
        if command in ("N2UserExist", "UserExistsServlet") and len(fields) == 5:
            account_id, version = fields[3], fields[1]
            reason = None
            if status == 200:
                try:
                    reply = decrypt(response.text).split("#")
                    reason = "banned" if len(reply) > 4 and reply[4] == "true" else None
                except Exception:
                    reason = None
                if reason is None:
                    if _text(version, 64):
                        self._remember(self._versions, account_id, _text(version, 64))
                    return
            reason = reason or self._failure_reason(status, account_id)
            if not self._duplicate(("login", ip, account_id, reason), now):
                self.record_login(account_id=account_id, ip=ip, route=command, result="failure", reason=reason,
                                  platform=platform, client_version=_text(version, 64), now=now)
            return
        if command == "N2AddUser" and status != 200 and fields:
            reason = self._failure_reason(status, fields[0])
            if not self._duplicate(("login", ip, fields[0], reason), now):
                self.record_login(account_id=fields[0], ip=ip, route=command, result="failure", reason=reason,
                                  platform=platform, now=now)
            return
        guid = fields[0] if fields and GUID.fullmatch(fields[0]) else None
        if status == 200:
            if guid:
                self.touch(guid, now)
            return
        # 401/403 on an ordinary route: rejected credential, ban or revoked session.
        account_id = None
        if guid:
            row = self.db.execute("SELECT ps4_id FROM sessions WHERE guid=?", (guid,)).fetchone()
            account_id = row[0] if row else None
        reason = self._failure_reason(status, account_id, guid)
        if not self._duplicate(("denied", ip, account_id, reason), now):
            self.record_login(account_id=account_id, ip=ip, route=command, result="failure", reason=reason,
                              platform=platform, now=now)

    # --------------------------------------------------------------- lifecycle
    def reconcile(self, now=None):
        """Close open sessions that were revoked, superseded or went idle."""
        now = self.clock() if now is None else now
        if not self._idle_db():
            return
        with self.db:
            for row in self.db.execute("""SELECT a.session_id,a.started_at,r.revoked_at,
                    (SELECT operation FROM moderation_events e WHERE e.request_id=r.request_id LIMIT 1) AS operation
                    FROM activity_sessions a JOIN moderation_revoked_sessions r USING(guid)
                    WHERE a.ended_at IS NULL""").fetchall():
                reason = {"kick": "kicked", "ban": "banned"}.get(row["operation"], "revoked")
                ended = max(row["started_at"], min(float(row["revoked_at"]), now))
                self.db.execute("UPDATE activity_sessions SET ended_at=?,end_reason=? WHERE session_id=?",
                                (ended, reason, row["session_id"]))
            for row in self.db.execute("""SELECT a.session_id,a.started_at,a.last_seen_at,
                    (SELECT MIN(s.created_at) FROM sessions s WHERE s.ps4_id=a.account_id AND s.guid<>a.guid
                     AND s.created_at>=COALESCE((SELECT created_at FROM sessions o WHERE o.guid=a.guid),a.started_at)) AS newer
                    FROM activity_sessions a WHERE a.ended_at IS NULL""").fetchall():
                if row["newer"] is None:
                    continue
                newer = float(row["newer"])
                replaced = newer - row["last_seen_at"] <= self.idle_seconds
                ended = max(row["started_at"], min(newer if replaced else row["last_seen_at"], now))
                self.db.execute("UPDATE activity_sessions SET ended_at=?,end_reason=? WHERE session_id=?",
                                (ended, "replaced" if replaced else "timeout", row["session_id"]))
            for row in self.db.execute("""SELECT session_id,started_at,last_seen_at,in_world_at,gateway_closed_at,
                    gateway_close_reason FROM activity_sessions WHERE ended_at IS NULL AND last_seen_at<?""",
                                       (now - self.idle_seconds,)).fetchall():
                ended, reason = row["last_seen_at"], "timeout"
                closed = row["gateway_closed_at"]
                if closed is not None and closed >= (row["in_world_at"] or row["started_at"]) - 5:
                    ended = max(ended, min(float(closed), now))
                    reason = "gateway_close:" + (row["gateway_close_reason"] or "unknown")
                self.db.execute("UPDATE activity_sessions SET ended_at=?,end_reason=? WHERE session_id=?",
                                (max(row["started_at"], ended), reason, row["session_id"]))
            # N2AddUserOnline only ever sets the flag; clear it once no live session remains.
            self.db.execute("""UPDATE profile_state SET online=0 WHERE online=1 AND NOT EXISTS(
                SELECT 1 FROM activity_sessions a WHERE a.account_id=profile_state.ps4_id
                AND a.ended_at IS NULL AND a.last_seen_at>=?)""", (now - self.idle_seconds,))

    def online_count(self, now=None):
        now = self.clock() if now is None else now
        return self.db.execute("SELECT COUNT(DISTINCT account_id) FROM activity_sessions WHERE ended_at IS NULL AND last_seen_at>=?",
                               (now - self.idle_seconds,)).fetchone()[0]

    def tick(self, now=None):
        now = self.clock() if now is None else now
        if not self._idle_db():
            return
        presence = {}
        try:
            presence = self.store.presence()
        except Exception as error:
            _report("activity_presence_failed", error)
        with self.db:
            for guid in presence:
                self.db.execute("""UPDATE activity_sessions SET last_seen_at=MAX(last_seen_at,?),in_world_at=?
                    WHERE guid=? AND ended_at IS NULL""", (now, now, guid))
            try:
                rows = self.db.execute("""SELECT a.session_id,a.instances_json,l.instance_id,l.psidglobal,l.allocated_at
                    FROM activity_sessions a JOIN allocations l USING(guid) WHERE a.ended_at IS NULL""").fetchall()
            except Exception:
                rows = []
            for row in rows:
                try:
                    visited = json.loads(row["instances_json"] or "[]")
                except ValueError:
                    visited = []
                last = visited[-1] if visited else None
                if last and last.get("instance_id") == row["instance_id"] and last.get("allocated_at") == row["allocated_at"]:
                    continue
                visited.append({"instance_id": row["instance_id"], "psidglobal": row["psidglobal"],
                                "allocated_at": row["allocated_at"]})
                self.db.execute("UPDATE activity_sessions SET instances_json=? WHERE session_id=?",
                                (json.dumps(visited[-MAX_INSTANCES_PER_SESSION:], separators=(",", ":")),
                                 row["session_id"]))
        try:
            self.ingest_spool(now)
        except Exception as error:
            _report("activity_spool_failed", error)
        self.reconcile(now)
        online = self.online_count(now)
        hour = int(now // 3600)
        with self.db:
            self.db.execute("""INSERT INTO activity_peaks VALUES(?,?,?) ON CONFLICT(hour) DO UPDATE SET
                peak_online=MAX(peak_online,excluded.peak_online),sampled_at=excluded.sampled_at""", (hour, online, now))
        last_prune = float(self._meta("last_prune", "0") or 0)
        if now - last_prune >= PRUNE_INTERVAL:
            self.prune(now)

    def prune(self, now=None):
        now = self.clock() if now is None else now
        cutoff = now - self.retention_days * 86400
        with self.db:
            self.db.execute("DELETE FROM activity_logins WHERE created_at<?", (cutoff,))
            self.db.execute("DELETE FROM activity_sessions WHERE COALESCE(ended_at,last_seen_at)<?", (cutoff,))
            self.db.execute("DELETE FROM activity_peaks WHERE hour<?", (int(cutoff // 3600),))
            self.db.execute("""DELETE FROM activity_geo WHERE fetched_at<? OR ip NOT IN (
                SELECT ip FROM activity_sessions WHERE ip IS NOT NULL
                UNION SELECT gateway_ip FROM activity_sessions WHERE gateway_ip IS NOT NULL
                UNION SELECT ip FROM activity_logins WHERE ip IS NOT NULL)""", (cutoff,))
            self._set_meta("last_prune", now)

    # ------------------------------------------------------------ gateway spool
    def ingest_spool(self, now=None):
        if self.spool_dir is None or not self._idle_db():
            return
        now = self.clock() if now is None else now
        try:
            names = sorted(path.name for path in self.spool_dir.iterdir() if SPOOL_PATTERN.fullmatch(path.name))
        except OSError:
            return
        for name in names:
            path = self.spool_dir / name
            key = "spool:" + name
            offset = int(self._meta(key, "0") or 0)
            try:
                size = path.stat().st_size
                if size < offset:
                    offset = 0
                with path.open("rb") as handle:
                    handle.seek(offset)
                    chunk = handle.read(SPOOL_READ_CHUNK)
            except OSError:
                continue
            complete = chunk.rfind(b"\n") + 1
            for line in chunk[:complete].splitlines():
                try:
                    event = json.loads(line.decode("utf-8"))
                except (ValueError, UnicodeError):
                    continue
                if isinstance(event, dict):
                    self.gateway_event(event)
            with self.db:
                self._set_meta(key, offset + complete)
            if offset + complete >= size and name < "gateway-activity-" + time.strftime("%Y%m%d", time.gmtime(now)) + ".jsonl":
                try:
                    path.unlink()
                    with self.db:
                        self.db.execute("DELETE FROM activity_meta WHERE key=?", (key,))
                except OSError:
                    pass

    def gateway_event(self, event):
        when = event.get("time")
        when = float(when) if isinstance(when, (int, float)) and not isinstance(when, bool) else self.clock()
        ip, guid = normalize_ip(event.get("ip")), event.get("guid")
        account_id = _text(event.get("account_id"))
        reason = _text(event.get("reason"), 64) or "unknown"
        admitted = event.get("admitted") is True
        if admitted and isinstance(guid, str) and GUID.fullmatch(guid):
            with self.db:
                self.db.execute("""UPDATE activity_sessions SET gateway_ip=COALESCE(?,gateway_ip),
                    gateway_connections=gateway_connections+1,gateway_closed_at=?,gateway_close_reason=?,
                    last_seen_at=MAX(last_seen_at,?) WHERE guid=?""", (ip, when, reason, when, guid))
            self.want_geo([ip])
        elif not admitted and reason in GATEWAY_FAILURES:
            if not self._duplicate(("gateway", ip, account_id, reason), when):
                self.record_login(account_id=account_id, ip=ip, route="gateway", result="failure",
                                  reason=reason, now=when)

    # --------------------------------------------------------------------- geo
    def want_geo(self, ips):
        if not self.geo_enabled:
            return
        for ip in ips:
            ip = normalize_ip(ip)
            if ip is not None and public_ip(ip):
                self._geo_queue[ip] = None
                self._geo_queue.move_to_end(ip)
        while len(self._geo_queue) > MAX_MEMORY_KEYS:
            self._geo_queue.popitem(last=False)

    def geo_lookup(self, ips, queue=True):
        """{ip: (geo dict or None, status)} from cache; queue stale entries."""
        now = self.clock()
        ips = sorted({ip for ip in (normalize_ip(x) for x in ips) if ip})
        result, wanted = {}, []
        cached = {}
        for start in range(0, len(ips), 500):
            part = ips[start:start + 500]
            cached.update({row["ip"]: row for row in self.db.execute(
                "SELECT * FROM activity_geo WHERE ip IN (" + ",".join("?" * len(part)) + ")", part)})
        for ip in ips:
            if not public_ip(ip):
                result[ip] = (None, "private")
                continue
            row = cached.get(ip)
            if row is not None and row["status"] == "ok":
                try:
                    geo = json.loads(row["data_json"])
                except (TypeError, ValueError):
                    geo = None
                result[ip] = (geo, "ok")
                if now - row["fetched_at"] > GEO_REFRESH_SECONDS:
                    wanted.append(ip)
            elif not self.geo_enabled:
                result[ip] = (None, "disabled")
            elif row is not None and row["status"] == "failed":
                result[ip] = (None, "unavailable")
                if now - row["fetched_at"] > GEO_RETRY_SECONDS:
                    wanted.append(ip)
            else:
                result[ip] = (None, "pending")
                wanted.append(ip)
        if queue:
            self.want_geo(wanted)
        return result

    def _next_geo_candidate(self, now):
        while self._geo_queue:
            ip, _ = self._geo_queue.popitem(last=True)
            row = self.db.execute("SELECT status,fetched_at FROM activity_geo WHERE ip=?", (ip,)).fetchone()
            if row is None or (row[0] == "ok" and now - row[1] > GEO_REFRESH_SECONDS) or (
                    row[0] == "failed" and now - row[1] > GEO_RETRY_SECONDS):
                return ip
        rows = self.db.execute("""SELECT x.ip FROM (
                SELECT ip,last_seen_at AS t FROM activity_sessions WHERE ip IS NOT NULL
                UNION ALL SELECT gateway_ip,last_seen_at FROM activity_sessions WHERE gateway_ip IS NOT NULL
                UNION ALL SELECT ip,created_at FROM activity_logins WHERE ip IS NOT NULL) x
            LEFT JOIN activity_geo g ON g.ip=x.ip
            WHERE g.ip IS NULL OR (g.status='ok' AND g.fetched_at<?) OR (g.status='failed' AND g.fetched_at<?)
            GROUP BY x.ip ORDER BY MAX(x.t) DESC LIMIT 32""",
                               (now - GEO_REFRESH_SECONDS, now - GEO_RETRY_SECONDS)).fetchall()
        for (ip,) in rows:
            if public_ip(ip):
                return ip
            with self.db:
                self.db.execute("""INSERT INTO activity_geo(ip,status,data_json,error,fetched_at) VALUES(?,'private',NULL,NULL,?)
                    ON CONFLICT(ip) DO UPDATE SET status='private',fetched_at=excluded.fetched_at""", (ip, now))
        return None

    async def geo_step(self):
        """Resolve at most one IP. Returns the IP attempted, or None."""
        now = self.clock()
        if not self.geo_enabled or now < self.geo_backoff_until or not self._idle_db():
            return None
        ip = self._next_geo_candidate(now)
        if ip is None:
            return None
        self.geo_lookups += 1
        try:
            raw = await asyncio.wait_for(self.fetch(self.geo_url.replace("{ip}", ip)), 8)
            if not isinstance(raw, dict) or raw.get("success") is False:
                raise ValueError("Geo provider returned no result")
            geo, status, error = normalize_geo(raw), "ok", None
            self.geo_last_error = None
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            geo, status, error = None, "failed", type(exc).__name__
            self.geo_last_error = error
            self.geo_backoff_until = self.clock() + GEO_BACKOFF_SECONDS
        if self._idle_db():
            with self.db:
                self.db.execute("""INSERT INTO activity_geo(ip,status,data_json,error,fetched_at) VALUES(?,?,?,?,?)
                    ON CONFLICT(ip) DO UPDATE SET status=excluded.status,
                    data_json=CASE WHEN excluded.status='ok' THEN excluded.data_json ELSE activity_geo.data_json END,
                    error=excluded.error,fetched_at=excluded.fetched_at""",
                                (ip, status if status == "ok" else "failed",
                                 json.dumps(geo, separators=(",", ":")) if geo else None, error, self.clock()))
        return ip

    # ------------------------------------------------------------- background
    async def run(self):
        while True:
            try:
                now = self.clock()
                if now - self._last_tick >= TICK_INTERVAL:
                    self._last_tick = now
                    self.tick(now)
                await self.geo_step()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                _report("activity_background_failed", error)
            await asyncio.sleep(1.0)

    def start(self):
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(self.run())
        return self._task

    async def stop(self):
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except BaseException:
                pass


# ---------------------------------------------------------------- hook helpers
def recorder_for(store, **kwargs):
    recorder = getattr(store, "activity_recorder", None)
    if recorder is None:
        recorder = ActivityRecorder(store, **kwargs)
        store.activity_recorder = recorder
    return recorder


def attach_activity(backend):
    """Backend.__init__ hook. Never raises; returns the recorder or None."""
    try:
        return recorder_for(backend.store)
    except Exception as error:
        _report("activity_attach_failed", error)
        return None


def observe_request(backend, request, command, response):
    """Backend.handle hook. Never raises and never changes the response."""
    try:
        recorder = getattr(backend, "activity", None)
        if recorder is not None:
            recorder.observe(request, command, response)
    except Exception as error:
        _report("activity_capture_failed", error)


def start_activity(backend):
    try:
        recorder = getattr(backend, "activity", None)
        if recorder is not None:
            recorder.start()
    except Exception as error:
        _report("activity_start_failed", error)


async def stop_activity(backend):
    try:
        recorder = getattr(backend, "activity", None)
        if recorder is not None:
            await recorder.stop()
    except Exception as error:
        _report("activity_stop_failed", error)


def spool_directory(environ, default):
    """NEBULA_ACTIVITY_SPOOL_DIR overrides <state>/logs; 0/off disables the spool."""
    value = environ.get("NEBULA_ACTIVITY_SPOOL_DIR")
    if value is None or not value.strip():
        return Path(default) if default is not None else None
    return None if not _flag(value, True) else Path(value)


def gateway_activity(shared, state_dir=None, environ=None):
    """Gateway hook: append one connection summary to the operator spool.

    The spool lives in the gateway's only writable mount (<state>/logs) and is
    ingested then deleted by the backend. It is not a diagnostic log: stdout
    and gateway.jsonl never receive addresses or account IDs.
    """
    try:
        environ = os.environ if environ is None else environ
        directory = spool_directory(environ, Path(state_dir) / "logs" if state_dir is not None else None)
        if directory is None or not isinstance(shared, dict) or not directory.is_dir():
            return
        actor = shared.get("_activity_actor") or {}
        now = time.time()
        event = {"time": now, "event": "close", "connection_id": shared.get("connection_id"),
                 "ip": normalize_ip(shared.get("_activity_peer")),
                 "account_id": actor.get("account"), "guid": actor.get("guid"),
                 "instance_id": actor.get("instance"), "scene": actor.get("scene"),
                 "admitted": shared.get("_activity_admitted") is True,
                 "reason": shared.get("close_reason") or "unknown"}
        if "started" in shared:
            event["elapsed_ms"] = max(0, int((time.monotonic() - shared["started"]) * 1000))
        path = Path(directory) / ("gateway-activity-" + time.strftime("%Y%m%d", time.gmtime(now)) + ".jsonl")
        try:
            if path.stat().st_size > SPOOL_MAX_FILE:
                return
        except FileNotFoundError:
            pass
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, separators=(",", ":")) + "\n")
    except Exception as error:
        _report("gateway_activity_failed", error)


# ----------------------------------------------------------------- operator API
def _read_failures(state_dir, now, window=3600.0):
    directory = Path(state_dir) / "logs"
    sources, recent, counts, total = [], [], {}, 0
    for name in FAILURE_FILES:
        path = directory / name
        try:
            size = path.stat().st_size
            with path.open("rb") as handle:
                handle.seek(max(0, size - FAILURE_TAIL_BYTES))
                data = handle.read(FAILURE_TAIL_BYTES)
        except OSError:
            continue
        lines = data.splitlines()
        if size > FAILURE_TAIL_BYTES and lines:
            lines = lines[1:]  # first line is probably partial
        read = 0
        for line in lines:
            try:
                event = json.loads(line.decode("utf-8"))
            except (ValueError, UnicodeError):
                continue
            if not isinstance(event, dict):
                continue
            read += 1
            stamp = event.get("time", event.get("timestamp"))
            if isinstance(stamp, str):
                try:
                    stamp = calendar.timegm(time.strptime(stamp[:19], "%Y-%m-%dT%H:%M:%S"))
                except ValueError:
                    stamp = None
            if not isinstance(stamp, (int, float)) or isinstance(stamp, bool) or now - stamp > window:
                continue
            total += 1
            key = _text(event.get("reason") or event.get("event"), 64) or "unknown"
            counts[key] = counts.get(key, 0) + 1
            recent.append({"time": float(stamp), "source": name.rsplit(".", 1)[0],
                           **{field: _text(event.get(field), 128) if not isinstance(event.get(field), int)
                              else event.get(field)
                              for field in ("event", "reason", "route", "status", "stage", "task", "level")}})
        sources.append({"file": name, "events_read": read, "bytes": size})
    recent.sort(key=lambda row: row["time"], reverse=True)
    return {"available": bool(sources), "window_seconds": int(window), "sources": sources, "total": total,
            "by_reason": [{"reason": k, "count": v} for k, v in sorted(counts.items(), key=lambda x: (-x[1], x[0]))[:15]],
            "recent": recent[:20]}


def _read_json(path, limit=1024 * 1024):
    try:
        if path.stat().st_size > limit:
            return None
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def _memory_rss(pid):
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return None
    try:
        pages = int(Path("/proc/" + str(pid) + "/statm").read_text().split()[1])
        return pages * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError, IndexError, AttributeError):
        return None


class PlayerActivity:
    def __init__(self, manager):
        self.manager = manager
        self.service, self.db = manager.service, manager.db
        self.recorder = recorder_for(manager.store)

    # ---- shaping
    def _geo(self, rows, keys=("ip",)):
        lookup = self.recorder.geo_lookup([row.get(k) for row in rows for k in keys if row.get(k)])
        for row in rows:
            for key in keys:
                prefix = "" if key == "ip" else key[:-2]
                geo, status = lookup.get(normalize_ip(row.get(key)) or "", (None, None)) if row.get(key) else (None, None)
                row[prefix + "geo"], row[prefix + "geo_status"] = geo, status
        return rows

    def _session_items(self, rows, now):
        items = []
        for row in rows:
            row = dict(row)
            live = row["ended_at"] is None
            end = now if live else row["ended_at"]
            try:
                visited = json.loads(row.pop("instances_json") or "[]")
            except ValueError:
                visited = []
            row.pop("guid", None)
            items.append({**row, "live": live, "duration_seconds": max(0, int(round(end - row["started_at"]))),
                          "in_world": bool(live and row["in_world_at"] and now - row["in_world_at"] <= IN_WORLD_FRESH),
                          "instances": visited})
        self.manager._name_accounts(items)
        return self._geo(items, ("ip", "gateway_ip"))

    def _sessions_page(self, where, parameters, query, now):
        page = self.manager.page_sql("SELECT * FROM activity_sessions WHERE " + where
                                     + " ORDER BY started_at DESC,session_id DESC", parameters, query)
        page["items"] = self._session_items(page["items"], now)
        return page

    def _logins_page(self, where, parameters, query):
        from management import require
        result = query.get("result", "")
        require(result in ("", "success", "failure"), "Invalid login result filter")
        if result:
            where, parameters = where + " AND l.result=?", (*parameters, result)
        page = self.manager.page_sql("""SELECT l.event_id,l.created_at,l.account_id,p.username AS account_name,l.ip,
            l.result,l.reason,l.route,l.platform,l.client_version,l.session_id
            FROM activity_logins l LEFT JOIN profiles p ON p.ps4_id=l.account_id WHERE """ + where
                                     + " ORDER BY l.created_at DESC,l.event_id DESC", parameters, query)
        self._geo(page["items"])
        return page

    def _other_accounts(self, ip, exclude):
        rows = self.db.execute("""SELECT account_id,MAX(t) AS last_seen FROM (
                SELECT account_id,COALESCE(ended_at,last_seen_at) AS t FROM activity_sessions WHERE ip=? OR gateway_ip=?
                UNION ALL SELECT account_id,created_at FROM activity_logins WHERE ip=? AND account_id IS NOT NULL)
            WHERE account_id<>? GROUP BY account_id ORDER BY last_seen DESC LIMIT 25""", (ip, ip, ip, exclude or ""))
        return self.manager._name_accounts([dict(r) for r in rows])

    # ---- routes
    def read(self, parts, query):
        from management import require
        now = self.recorder.clock()
        try:
            self.recorder.reconcile(now)
        except Exception as error:
            _report("activity_reconcile_failed", error)
        if len(parts) == 3 and parts[0] == "users":
            account_id = parts[1]
            if parts[2] == "sessions":
                return self._sessions_page("account_id=?", (account_id,), query, now)
            if parts[2] == "logins":
                return self._logins_page("l.account_id=?", (account_id,), query)
            if parts[2] == "ips":
                return self.user_ips(account_id, query)
        if parts == ["monitor"]:
            return self.overview(now)
        if parts == ["monitor", "logins"]:
            search = query.get("q", "")
            require(isinstance(search, str) and len(search) <= 128, "Invalid login search")
            return self._logins_page("""(?='' OR instr(lower(COALESCE(p.username,'')),lower(?))>0
                OR instr(lower(COALESCE(l.ip,'')),lower(?))>0 OR instr(lower(COALESCE(l.account_id,'')),lower(?))>0)""",
                                     (search,) * 4, query)
        if len(parts) == 3 and parts[:2] == ["monitor", "ips"]:
            ip = normalize_ip(parts[2])
            require(ip is not None, "Invalid IP address")
            return self.ip_detail(ip, query, now)
        require(False, "Monitoring route not found", 404, "not_found")

    def user_ips(self, account_id, query):
        page = self.manager.page_sql("""SELECT ip,MIN(t0) AS first_seen,MAX(t1) AS last_seen,
                SUM(ok) AS login_count,SUM(bad) AS failed_login_count,SUM(s) AS session_count,
                MAX(gw) AS seen_on_gateway FROM (
              SELECT ip,started_at AS t0,COALESCE(ended_at,last_seen_at) AS t1,0 AS ok,0 AS bad,1 AS s,0 AS gw
                FROM activity_sessions WHERE account_id=? AND ip IS NOT NULL
              UNION ALL SELECT gateway_ip,started_at,COALESCE(ended_at,last_seen_at),0,0,0,1
                FROM activity_sessions WHERE account_id=? AND gateway_ip IS NOT NULL
              UNION ALL SELECT ip,created_at,created_at,0,result='failure',0,0
                FROM activity_logins WHERE account_id=? AND ip IS NOT NULL
              UNION ALL SELECT ip,created_at,created_at,result='success',0,0,0
                FROM activity_logins WHERE account_id=? AND ip IS NOT NULL)
            GROUP BY ip ORDER BY last_seen DESC,ip""", (account_id,) * 4, query)
        for item in page["items"]:
            item["seen_on_gateway"] = bool(item["seen_on_gateway"])
            item["other_accounts"] = self._other_accounts(item["ip"], account_id)
        self._geo(page["items"])
        return page

    def ip_detail(self, ip, query, now):
        accounts = [dict(r) for r in self.db.execute("""SELECT account_id,MIN(t0) AS first_seen,MAX(t1) AS last_seen,
                SUM(ok) AS login_count,SUM(bad) AS failed_login_count,SUM(s) AS session_count FROM (
              SELECT account_id,started_at AS t0,COALESCE(ended_at,last_seen_at) AS t1,0 AS ok,0 AS bad,1 AS s
                FROM activity_sessions WHERE ip=? OR gateway_ip=?
              UNION ALL SELECT account_id,created_at,created_at,result='success',result='failure',0
                FROM activity_logins WHERE ip=? AND account_id IS NOT NULL)
            GROUP BY account_id ORDER BY last_seen DESC LIMIT 200""", (ip, ip, ip))]
        self.manager._name_accounts(accounts)
        stats = self.db.execute("""SELECT MIN(t) AS first_seen,MAX(t) AS last_seen FROM (
                SELECT started_at AS t FROM activity_sessions WHERE ip=? OR gateway_ip=?
                UNION ALL SELECT COALESCE(ended_at,last_seen_at) FROM activity_sessions WHERE ip=? OR gateway_ip=?
                UNION ALL SELECT created_at FROM activity_logins WHERE ip=?)""", (ip,) * 5).fetchone()
        logins = self.db.execute("""SELECT COALESCE(SUM(result='success'),0),COALESCE(SUM(result='failure'),0)
            FROM activity_logins WHERE ip=?""", (ip,)).fetchone()
        geo, status = self.recorder.geo_lookup([ip])[ip]
        return {"ip": ip, "geo": geo, "geo_status": status, "first_seen": stats["first_seen"],
                "last_seen": stats["last_seen"], "login_count": logins[0], "failed_login_count": logins[1],
                "account_count": len(accounts), "accounts": accounts,
                "sessions": self._sessions_page("ip=? OR gateway_ip=?", (ip, ip), query, now)}

    def overview(self, now):
        idle = self.recorder.idle_seconds
        online_rows = self.db.execute("""SELECT a.*,l.instance_id AS current_instance_id,l.psidglobal AS current_world
            FROM activity_sessions a LEFT JOIN allocations l USING(guid)
            WHERE a.ended_at IS NULL AND a.last_seen_at>=? ORDER BY a.started_at""", (now - idle,)).fetchall()
        online = []
        for row in self._session_items(online_rows, now):
            geo = row.get("geo") or row.get("gateway_geo") or {}
            online.append({"session_id": row["session_id"], "account_id": row["account_id"],
                           "account_name": row["account_name"], "since": row["started_at"],
                           "last_seen_at": row["last_seen_at"], "duration_seconds": row["duration_seconds"],
                           "in_world": row["in_world"], "instance_id": row.get("current_instance_id"),
                           "world": row.get("current_world"), "platform": row["platform"],
                           "client_version": row["client_version"], "ip": row["ip"],
                           "ip_country": geo.get("country"), "ip_country_code": geo.get("country_code"),
                           "geo_status": row["geo_status"]})
        recent = self._logins_page("1=1", (), {"limit": "20"})["items"]
        day = now - 86400
        scalar = lambda sql, *args: self.db.execute(sql, args).fetchone()[0]
        peak = scalar("SELECT COALESCE(MAX(peak_online),0) FROM activity_peaks WHERE hour>=?", int(day // 3600))
        last_24h = {
            "unique_players": scalar("SELECT COUNT(DISTINCT account_id) FROM activity_sessions WHERE COALESCE(ended_at,?)>=?", now, day),
            "sessions": scalar("SELECT COUNT(*) FROM activity_sessions WHERE started_at>=?", day),
            "avg_session_seconds": int(round(scalar(
                "SELECT COALESCE(AVG(COALESCE(ended_at,?)-started_at),0) FROM activity_sessions WHERE started_at>=?", now, day))),
            "peak_concurrent": max(peak, len({row["account_id"] for row in online})),
            "logins": scalar("SELECT COUNT(*) FROM activity_logins WHERE created_at>=? AND result='success'", day),
            "failed_logins": scalar("SELECT COUNT(*) FROM activity_logins WHERE created_at>=? AND result='failure'", day),
            "unique_ips": scalar("""SELECT COUNT(DISTINCT ip) FROM (SELECT ip FROM activity_logins WHERE created_at>=?
                UNION SELECT ip FROM activity_sessions WHERE COALESCE(ended_at,?)>=?) WHERE ip IS NOT NULL""", day, now, day),
            "new_accounts": scalar("SELECT COUNT(*) FROM profiles WHERE created_at>=?", day),
        }
        try:
            failures = _read_failures(self.recorder.state_dir, now)
        except Exception as error:
            _report("activity_failures_read_failed", error)
            failures = {"available": False, "window_seconds": 3600, "sources": [], "total": 0, "by_reason": [], "recent": []}
        instances, queue = self._instances(now, online)
        return {"generated_at": now, "online_count": len(online), "online": online,
                "instances": instances, "queue": queue, "recent_logins": recent,
                "failures": failures, "last_24h": last_24h,
                "geo": {"enabled": self.recorder.geo_enabled, "provider": self.recorder.geo_url.split("/")[2],
                        "last_error": self.recorder.geo_last_error,
                        "backoff_until": self.recorder.geo_backoff_until or None,
                        "pending_lookups": len(self.recorder._geo_queue)},
                "capture": {"idle_timeout_seconds": int(idle), "retention_days": self.recorder.retention_days,
                            "gateway_spool_configured": self.recorder.spool_dir is not None,
                            "background_running": bool(self.recorder._task and not self.recorder._task.done())}}

    def _instances(self, now, online):
        state_dir = self.recorder.state_dir
        merged = {}

        def entry(instance_id):
            return merged.setdefault(instance_id, {
                "instance_id": instance_id, "world": None, "kind": None, "owner_account_id": None,
                "ready": False, "players": None, "maxusers": None, "tracked_players": 0,
                "heartbeat_age_seconds": None, "process_state": None, "pid": None, "port": None,
                "started_at": None, "last_health_at": None, "restart_count": None, "process_reason": None,
                "memory_rss_bytes": None, "desired_state": None, "active_demands": 0, "pending_reservations": 0})
        runtime = _read_json(state_dir / "managed-instance-runtime.json") or {}
        for row in runtime.get("instances", []) if isinstance(runtime.get("instances"), list) else []:
            if not isinstance(row, dict) or not isinstance(row.get("instance_id"), str):
                continue
            item = entry(row["instance_id"])
            item.update({"world": row.get("psidglobal"), "kind": row.get("kind"),
                         "owner_account_id": row.get("owner_ps4_id") or None, "process_state": row.get("state"),
                         "pid": row.get("pid"), "port": row.get("port"), "started_at": row.get("started_at"),
                         "last_health_at": row.get("last_health_at"), "restart_count": row.get("restart_count"),
                         "process_reason": _text(row.get("reason"), 200),
                         "memory_rss_bytes": _memory_rss(row.get("pid"))})
        desired = _read_json(state_dir / "desired-instances.json") or {}
        for row in desired.get("instances", []) if isinstance(desired.get("instances"), list) else []:
            if not isinstance(row, dict) or not isinstance(row.get("instance_id"), str):
                continue
            item = entry(row["instance_id"])
            item["world"] = item["world"] or row.get("psidglobal")
            item["kind"] = item["kind"] or row.get("kind")
            item["owner_account_id"] = item["owner_account_id"] or row.get("owner_ps4_id") or None
            item.update({"desired_state": row.get("desired_state"),
                         "active_demands": row.get("active_demands", 0),
                         "pending_reservations": row.get("pending_reservations", 0)})
        try:
            ready = self.service.instances.all_ready()
        except Exception:
            ready = []
        for row in ready:
            item = entry(row["instance_id"])
            item.update({"ready": True, "world": row.get("psidglobal"), "players": row.get("players"),
                         "maxusers": row.get("maxusers"), "port": item["port"] or row.get("port"),
                         "heartbeat_age_seconds": round(max(0.0, now - float(row.get("heartbeat", now))), 1)})
        for row in online:
            if row.get("instance_id"):
                entry(row["instance_id"])["tracked_players"] += 1
        items = [item for item in merged.values()
                 if item["ready"] or item["tracked_players"] or item["desired_state"] == "running"
                 or item["process_state"] not in (None, "stopped")]
        self.manager._name_accounts(items, "owner_account_id", "owner_account_name")
        items.sort(key=lambda x: (not x["ready"], -(x["players"] or 0), x["instance_id"]))
        queue = []
        try:
            queue = [dict(r) for r in self.db.execute("""SELECT s.ps4_id AS account_id,d.instance_id,d.psidglobal AS world,
                d.state,d.reserved_at,d.expires_at FROM instance_demands d JOIN sessions s ON s.guid=d.requester_guid
                WHERE d.state='pending' AND d.expires_at>? ORDER BY d.reserved_at""", (now,))]
        except Exception:
            queue = []
        for row in queue:
            row["waiting_seconds"] = max(0, int(now - row["reserved_at"]))
        self.manager._name_accounts(queue)
        return {"count": len(items), "running": sum(1 for x in items if x["ready"]), "items": items}, \
               {"count": len(queue), "items": queue}
