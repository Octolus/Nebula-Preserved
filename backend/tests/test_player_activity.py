"""Operator activity monitoring: capture, inference, geo cache and API shape.

No sockets or real network: the geo fetcher is an injected coroutine and every
HTTP exchange is a synthetic request/response object.
"""
import asyncio
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
import uuid

BASE = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(BASE / "backend"), str(BASE / "tools")]
import management as M
import player_activity as A
from service import Service
from state import Store, Catalog
from wire import encrypt, session_guid

TOKEN = b"not-a-real-secret-temporary-test-token-12345"
ACCOUNT = "activity-test-account"
OTHER = "activity-other-account"
OPERATORS = [{"id": role, "role": role, "enabled": True} for role in ("owner", "admin", "moderator")]
ACTOR = {"id": "admin", "role": "admin"}
# Global unicast literals used only as opaque cache keys; no request is sent.
IP1, IP2, PRIVATE = "1.1.1.1", "9.9.9.9", "10.1.2.3"
HASH1, HASH2 = "a" * 64, "b" * 64


class Clock:
    def __init__(self):
        self.now = time.time()

    def __call__(self):
        return self.now


class FakeFetch:
    def __init__(self, fail=False):
        self.urls, self.fail = [], fail

    async def __call__(self, url):
        self.urls.append(url)
        if self.fail:
            raise OSError("egress blocked")
        return {"success": True, "ip": url.rsplit("/", 1)[1], "country_name": "Exampleland", "country_code": "EX",
                "region": "North", "city": "Sample City", "isp": "Example ISP", "org": "Example Org",
                "asn": "AS64500 Example", "timezone_name": "UTC", "latitude": 1.5, "longitude": 2.5}


def http_request(plaintext, remote="127.0.0.1", headers=None):
    return SimpleNamespace(remote=remote, headers=headers or {}, query={"data": encrypt(plaintext)})


def http_response(status=200, reply="true#"):
    return SimpleNamespace(status=status, text=encrypt(reply))


class ActivityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name)
        self.store = Store(self.state / "preservation.sqlite3")
        self.addCleanup(self.store.close)
        self.service = Service(self.store, Catalog(BASE / "protocol"), core_test_profile="nonmini-semantic-v1")
        self.store.account(ACCOUNT, "PreservationPlayer")
        self.store.account(OTHER, "OtherPlayer")
        self.clock, self.fetch = Clock(), FakeFetch()
        self.recorder = self.make_recorder()
        self.manager = M.Management(self.store, self.service, TOKEN, OPERATORS)
        self.assertIs(self.manager.activity.recorder, self.recorder)

    def make_recorder(self, environ=None, fetch=None):
        environ = {"NEBULA_ACTIVITY_IDLE_MINUTES": "5", **(environ or {})}
        recorder = A.ActivityRecorder(self.store, environ=environ, clock=self.clock, fetch=fetch or self.fetch)
        self.store.activity_recorder = recorder
        return recorder

    def advance(self, seconds):
        self.clock.now += seconds

    def bind(self, account, request_hash, ip=IP1, remote="127.0.0.1"):
        """Simulate ChannelGUIDServlet: the service binds, then the hook observes."""
        guid = session_guid(account, request_hash)
        self.store.bind_session(account, guid)
        with self.store.db:
            self.store.db.execute("UPDATE sessions SET created_at=? WHERE guid=?", (self.clock.now, guid))
        self.recorder.observe(http_request(account + "#" + request_hash + "#StandaloneWindows", remote,
                                           {"X-Real-IP": ip}), "ChannelGUIDServlet", http_response())
        return guid

    def read(self, tail, **query):
        return self.manager.read(tail, query, ACTOR)

    # ------------------------------------------------------------ capture
    def test_session_start_end_and_duration(self):
        first = self.bind(ACCOUNT, HASH1)
        page = self.read("users/" + ACCOUNT + "/sessions")
        self.assertEqual(page["total"], 1)
        item = page["items"][0]
        self.assertTrue(item["live"])
        self.assertIsNone(item["ended_at"])
        self.assertEqual((item["ip"], item["platform"], item["account_name"]), (IP1, "StandaloneWindows", "PreservationPlayer"))
        self.assertNotIn("guid", item)
        self.advance(120)
        self.recorder.observe(http_request(first + "#" + ACCOUNT + "#StandaloneWindows"), "N2UpdateUserOnline", http_response())
        self.advance(60)
        self.bind(ACCOUNT, HASH2, IP2)
        page = self.read("users/" + ACCOUNT + "/sessions")
        self.assertEqual(page["total"], 2)
        newest, older = page["items"]
        self.assertTrue(newest["live"])
        self.assertEqual(older["end_reason"], "replaced")
        self.assertEqual(older["duration_seconds"], 180)
        logins = self.read("users/" + ACCOUNT + "/logins")
        self.assertEqual([x["result"] for x in logins["items"]], ["success", "success"])
        self.assertEqual(logins["items"][0]["route"], "ChannelGUIDServlet")

    def test_client_version_and_banned_login_failure(self):
        version_request = http_request("PreservationPlayer#1.2.3#false#" + ACCOUNT + "#nonce#StandaloneWindows")
        self.recorder.observe(version_request, "N2UserExist", http_response(reply=ACCOUNT + "##preservation#false#false##"))
        self.bind(ACCOUNT, HASH1)
        self.assertEqual(self.read("users/" + ACCOUNT + "/sessions")["items"][0]["client_version"], "1.2.3")
        self.recorder.observe(version_request, "N2UserExist",
                              http_response(reply=ACCOUNT + "##preservation#false#true#null#reason"))
        failure = self.read("users/" + ACCOUNT + "/logins", result="failure")
        self.assertEqual(failure["total"], 1)
        self.assertEqual((failure["items"][0]["reason"], failure["items"][0]["route"]), ("banned", "N2UserExist"))
        self.recorder.observe(http_request(ACCOUNT + "#" + HASH2 + "#StandaloneWindows", "127.0.0.1", {"X-Real-IP": IP2}),
                              "ChannelGUIDServlet", http_response(403, "ERROR"))
        self.assertEqual(self.read("users/" + ACCOUNT + "/logins", result="failure")["total"], 2)

    def test_timeout_and_gateway_close_inference(self):
        self.bind(ACCOUNT, HASH1)
        self.advance(299)
        self.assertTrue(self.read("users/" + ACCOUNT + "/sessions")["items"][0]["live"])
        self.advance(2)
        item = self.read("users/" + ACCOUNT + "/sessions")["items"][0]
        self.assertEqual((item["live"], item["end_reason"], item["duration_seconds"]), (False, "timeout", 0))

        guid = self.bind(OTHER, HASH2)
        self.advance(100)
        self.recorder.gateway_event({"time": self.clock.now, "admitted": True, "guid": guid, "account_id": OTHER,
                                     "ip": IP2, "reason": "stream_eof"})
        self.advance(400)
        item = self.read("users/" + OTHER + "/sessions")["items"][0]
        self.assertEqual(item["end_reason"], "gateway_close:stream_eof")
        self.assertEqual(item["duration_seconds"], 100)
        self.assertEqual((item["gateway_ip"], item["gateway_connections"]), (IP2, 1))

    def test_online_flag_clears_when_no_live_session_remains(self):
        def flags():
            return dict(self.store.db.execute("SELECT ps4_id,online FROM profile_state WHERE ps4_id IN (?,?)",
                                              (ACCOUNT, OTHER)).fetchall())
        self.bind(ACCOUNT, HASH1)
        with self.store.db:
            self.store.db.execute("UPDATE profile_state SET online=1")  # N2AddUserOnline for both; OTHER never had a session
        self.recorder.reconcile(self.clock.now)
        self.assertEqual(flags(), {ACCOUNT: 1, OTHER: 0})
        self.advance(299)
        self.recorder.reconcile(self.clock.now)
        self.assertEqual(flags()[ACCOUNT], 1)
        self.advance(2)
        self.recorder.reconcile(self.clock.now)
        self.assertEqual(flags(), {ACCOUNT: 0, OTHER: 0})
        self.assertEqual(self.read("users", status="online")["total"], 0)

    def test_kick_ends_session(self):
        guid = self.bind(ACCOUNT, HASH1)
        with self.store.atomic():
            self.store.moderation.kick(ACCOUNT, guid=guid, reason="Temporary test", actor=ACTOR,
                                       request_id=uuid.uuid4().hex)
        item = self.read("users/" + ACCOUNT + "/sessions")["items"][0]
        self.assertEqual(item["end_reason"], "kicked")
        self.recorder.observe(http_request(guid + "#" + ACCOUNT + "#StandaloneWindows", "127.0.0.1", {"X-Real-IP": IP1}),
                              "N2UpdateUserOnline", http_response(403, "ERROR"))
        failure = self.read("users/" + ACCOUNT + "/logins", result="failure")["items"][0]
        self.assertEqual(failure["reason"], "revoked_session")

    def test_proxy_header_trust_rules(self):
        ip = lambda remote, headers: self.recorder.client_ip(SimpleNamespace(remote=remote, headers=headers))
        self.assertEqual(ip("127.0.0.1", {"X-Real-IP": IP1}), IP1)
        self.assertEqual(ip("::1", {"X-Real-IP": IP2}), IP2)
        self.assertEqual(ip("203.0.113.9", {"X-Real-IP": IP1}), "203.0.113.9")
        self.assertEqual(ip("127.0.0.1", {"X-Forwarded-For": IP1}), "127.0.0.1")
        self.assertEqual(ip("127.0.0.1", {"X-Real-IP": "not-an-ip"}), "127.0.0.1")
        self.assertEqual(ip("::ffff:198.51.100.7", {}), "198.51.100.7")
        self.assertIsNone(ip(None, {"X-Real-IP": IP1}))
        custom = self.make_recorder({"NEBULA_TRUSTED_PROXIES": "172.16.0.0/12"})
        self.assertEqual(custom.client_ip(SimpleNamespace(remote="172.18.0.1", headers={"X-Real-IP": IP1})), IP1)
        self.assertEqual(custom.client_ip(SimpleNamespace(remote="127.0.0.1", headers={"X-Real-IP": IP1})), "127.0.0.1")

    def test_ip_aggregation_and_other_accounts(self):
        self.bind(ACCOUNT, HASH1, IP1)
        self.advance(10)
        self.bind(ACCOUNT, HASH2, IP2)
        self.advance(10)
        self.bind(OTHER, "c" * 64, IP1)
        ips = self.read("users/" + ACCOUNT + "/ips")
        self.assertEqual(ips["total"], 2)
        by_ip = {row["ip"]: row for row in ips["items"]}
        self.assertEqual(by_ip[IP1]["login_count"], 1)
        self.assertEqual(by_ip[IP1]["session_count"], 1)
        self.assertEqual([(x["account_id"], x["account_name"]) for x in by_ip[IP1]["other_accounts"]],
                         [(OTHER, "OtherPlayer")])
        self.assertEqual(by_ip[IP2]["other_accounts"], [])
        detail = self.read("monitor/ips/" + IP1)
        self.assertEqual(detail["account_count"], 2)
        self.assertEqual(detail["sessions"]["total"], 2)
        self.assertEqual(detail["login_count"], 2)
        feed = self.read("monitor/logins", q="otherplay")
        self.assertEqual([x["account_name"] for x in feed["items"]], ["OtherPlayer"])
        self.assertEqual(self.read("monitor/logins", q=IP2)["total"], 1)
        self.assertEqual(set(feed), {"items", "total", "next_cursor", "limit"})
        with self.assertRaises(M.ManagementError):
            self.read("monitor/ips/not-an-ip")
        with self.assertRaises(M.ManagementError):
            self.read("monitor/logins", result="maybe")

    # ---------------------------------------------------------------- geo
    def test_geo_cache_refresh_private_and_failure(self):
        self.bind(ACCOUNT, HASH1, IP1)
        self.assertEqual(self.read("users/" + ACCOUNT + "/sessions")["items"][0]["geo_status"], "pending")
        self.assertEqual(asyncio.run(self.recorder.geo_step()), IP1)
        self.assertEqual(self.fetch.urls, ["https://json.geoiplookup.io/" + IP1])
        item = self.read("users/" + ACCOUNT + "/sessions")["items"][0]
        self.assertEqual(item["geo_status"], "ok")
        self.assertEqual(item["geo"]["country_code"], "EX")
        self.assertEqual(set(item["geo"]), set(A.GEO_FIELDS))
        self.assertNotIn("latitude", json.dumps(item["geo"]))
        self.assertIsNone(asyncio.run(self.recorder.geo_step()))
        self.assertEqual(len(self.fetch.urls), 1)
        self.advance(31 * 86400)
        self.recorder.geo_lookup([IP1])
        self.assertEqual(asyncio.run(self.recorder.geo_step()), IP1)
        self.assertEqual(len(self.fetch.urls), 2)

        self.recorder.record_login(account_id=OTHER, ip=PRIVATE, route="test", result="failure")
        self.assertIsNone(asyncio.run(self.recorder.geo_step()))
        self.assertEqual(self.recorder.geo_lookup([PRIVATE])[PRIVATE], (None, "private"))
        self.assertEqual(len(self.fetch.urls), 2)

        failing = FakeFetch(fail=True)
        recorder = self.make_recorder(fetch=failing)
        recorder.record_login(account_id=OTHER, ip=IP2, route="test", result="failure")
        self.assertEqual(asyncio.run(recorder.geo_step()), IP2)
        self.assertEqual(recorder.geo_lookup([IP2])[IP2], (None, "unavailable"))
        self.assertEqual(recorder.geo_last_error, "OSError")
        self.assertIsNone(asyncio.run(recorder.geo_step()))  # backoff: no hammering when egress is blocked
        self.assertEqual(len(failing.urls), 1)

        disabled = self.make_recorder({"NEBULA_GEOIP_ENABLED": "0"}, fetch=failing)
        disabled.record_login(account_id=OTHER, ip="8.8.4.4", route="test", result="failure")
        self.assertIsNone(asyncio.run(disabled.geo_step()))
        self.assertEqual(disabled.geo_lookup(["8.8.4.4"])["8.8.4.4"], (None, "disabled"))
        custom = self.make_recorder({"NEBULA_GEOIP_URL": "https://geo.example.invalid/v1/{ip}?f=json"})
        self.assertEqual(custom.geo_url, "https://geo.example.invalid/v1/{ip}?f=json")

    # ------------------------------------------------------------ monitor
    def test_monitor_overview_shape(self):
        guid = self.bind(ACCOUNT, HASH1, IP1)
        with self.store.db:
            self.store.db.execute("INSERT INTO allocations VALUES(?,?,?,?,?,?)",
                                  (guid, "public-nexus", "Nexus", "127.0.0.1", 28000, self.clock.now))
        self.recorder.tick(self.clock.now)
        self.recorder.record_login(account_id=OTHER, ip=IP2, route="ChannelGUIDServlet", result="failure",
                                   reason="banned")
        (self.state / "logs").mkdir()
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        (self.state / "logs" / "backend-failures.jsonl").write_text(
            "partial-garbage\n" + json.dumps({"event": "request_failed", "reason": "server_error", "route": "X",
                                              "status": 500, "timestamp": stamp}) + "\n", encoding="utf-8")
        (self.state / "managed-instance-runtime.json").write_text(json.dumps({"format_version": 1, "instances": [
            {"instance_id": "public-nexus", "kind": "public", "psidglobal": "Nexus", "state": "running",
             "pid": None, "port": 28000, "started_at": self.clock.now - 50, "restart_count": 0}]}), encoding="utf-8")
        view = self.read("monitor")
        self.assertEqual(set(view), {"generated_at", "online_count", "online", "instances", "queue", "recent_logins",
                                     "failures", "last_24h", "geo", "capture"})
        self.assertEqual(view["online_count"], 1)
        online = view["online"][0]
        self.assertEqual((online["account_name"], online["instance_id"], online["world"]),
                         ("PreservationPlayer", "public-nexus", "Nexus"))
        self.assertIn("ip_country", online)
        instance = view["instances"]["items"][0]
        self.assertEqual((instance["instance_id"], instance["process_state"], instance["tracked_players"]),
                         ("public-nexus", "running", 1))
        self.assertEqual(view["queue"], {"count": 0, "items": []})
        self.assertEqual([x["result"] for x in view["recent_logins"]], ["failure", "success"])
        self.assertEqual(view["failures"]["total"], 1)
        self.assertEqual(view["failures"]["by_reason"], [{"reason": "server_error", "count": 1}])
        day = view["last_24h"]
        self.assertEqual((day["unique_players"], day["sessions"], day["logins"], day["failed_logins"],
                          day["peak_concurrent"]), (1, 1, 1, 1, 1))
        visited = self.read("users/" + ACCOUNT + "/sessions")["items"][0]["instances"]
        self.assertEqual([x["instance_id"] for x in visited], ["public-nexus"])
        with self.assertRaises(M.ManagementError) as error:
            self.read("monitor/unknown")
        self.assertEqual(error.exception.status, 404)

    def test_presence_keeps_session_alive(self):
        guid = self.bind(ACCOUNT, HASH1)
        self.store.presence = lambda: {guid: 1}
        self.advance(400)
        self.recorder.tick(self.clock.now)
        item = self.read("users/" + ACCOUNT + "/sessions")["items"][0]
        self.assertTrue(item["live"] and item["in_world"])

    # --------------------------------------------------- retention/spool
    def test_retention_pruning(self):
        self.recorder.record_login(account_id=ACCOUNT, ip=IP1, route="test", result="success",
                                   now=self.clock.now - 100 * 86400)
        self.bind(OTHER, HASH2, IP2)
        with self.store.db:
            self.store.db.execute("INSERT INTO activity_geo VALUES(?,?,?,?,?)", (IP1, "ok", "{}", None, self.clock.now))
            self.store.db.execute("UPDATE activity_sessions SET ended_at=?,last_seen_at=? WHERE account_id=?",
                                  (self.clock.now - 95 * 86400, self.clock.now - 95 * 86400, OTHER))
        self.recorder.prune(self.clock.now)
        db = self.store.db
        self.assertEqual(db.execute("SELECT COUNT(*) FROM activity_logins WHERE account_id=?", (ACCOUNT,)).fetchone()[0], 0)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM activity_sessions").fetchone()[0], 0)
        self.assertIsNone(db.execute("SELECT 1 FROM activity_geo WHERE ip=?", (IP1,)).fetchone())
        short = self.make_recorder({"NEBULA_ACTIVITY_RETENTION_DAYS": "1"})
        self.assertEqual(short.retention_days, 1.0)

    def test_gateway_spool_round_trip(self):
        guid = self.bind(ACCOUNT, HASH1, IP1)
        logs = self.state / "logs"
        A.gateway_activity({"connection_id": "c1"}, self.state)  # no logs dir: silently nothing
        logs.mkdir()
        shared = {"connection_id": "c2", "started": time.monotonic(), "_activity_peer": IP2, "_activity_admitted": True,
                  "_activity_actor": {"account": ACCOUNT, "guid": guid, "instance": "i", "scene": "Nexus"},
                  "close_reason": "stream_eof"}
        A.gateway_activity(shared, self.state)
        A.gateway_activity({"connection_id": "c3", "_activity_peer": IP1, "close_reason": "credential"}, self.state)
        A.gateway_activity(shared, self.state, environ={"NEBULA_ACTIVITY_SPOOL_DIR": "off"})
        spools = list(logs.glob("gateway-activity-*.jsonl"))
        self.assertEqual(len(spools), 1)
        self.assertEqual(len(spools[0].read_text(encoding="utf-8").splitlines()), 2)
        self.recorder.tick(self.clock.now)
        item = self.read("users/" + ACCOUNT + "/sessions")["items"][0]
        self.assertEqual((item["gateway_ip"], item["gateway_close_reason"]), (IP2, "stream_eof"))
        gateway = self.read("monitor/logins", result="failure")["items"][0]
        self.assertEqual((gateway["route"], gateway["reason"], gateway["ip"]), ("gateway", "credential", IP1))
        self.recorder.tick(self.clock.now)  # offsets persist: no duplicates
        self.assertEqual(self.read("monitor/logins", result="failure")["total"], 1)

    # ---------------------------------------------------------- isolation
    def test_hook_failures_never_break_requests(self):
        class Exploding:
            def observe(self, *_args):
                raise RuntimeError("monitoring down")
        backend = SimpleNamespace(activity=Exploding())
        response = http_response()
        self.assertIsNone(A.observe_request(backend, http_request("x#StandaloneWindows"), "Any", response))
        A.observe_request(SimpleNamespace(), None, "Any", None)
        self.assertIsNone(A.attach_activity(SimpleNamespace(store=SimpleNamespace(db=None))))
        A.gateway_activity(None, self.state)
        A.gateway_activity({"_activity_actor": "garbage"}, self.state / "missing")
        # Undecryptable or malformed inputs are tolerated by the recorder itself.
        self.recorder.observe(SimpleNamespace(remote="127.0.0.1", headers={}, query={"data": "!!"}),
                              "ChannelGUIDServlet", http_response(403, "ERROR"))
        with self.store.atomic():
            # Inside a game transaction the recorder must not commit or write.
            self.recorder.observe(http_request(ACCOUNT + "#" + HASH1 + "#StandaloneWindows"),
                                  "ChannelGUIDServlet", http_response())
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM activity_sessions").fetchone()[0], 0)

    def test_backend_handle_survives_monitoring_failure(self):
        import io
        import server
        from wire import decrypt

        class Success:
            ROUTES = {"Success"}

            @staticmethod
            def dispatch(_command, _plaintext):
                return "true#session#OK"

        class Exploding:
            def observe(self, *_args):
                raise RuntimeError("monitoring down")
        backend = server.Backend.__new__(server.Backend)
        backend.service, backend.access, backend.log = Success(), None, io.StringIO()
        backend.publish_state = lambda: None
        backend.activity = Exploding()
        request = SimpleNamespace(path="/Success", method="GET", query={"data": encrypt("x#StandaloneWindows")},
                                  remote="127.0.0.1", headers={})
        response = asyncio.run(backend.handle(request))
        self.assertEqual(response.status, 200)
        self.assertEqual(decrypt(response.text), "true#session#OK")


if __name__ == "__main__":
    unittest.main()
