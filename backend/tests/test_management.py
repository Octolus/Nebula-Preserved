"""No sockets or live state: actual approved Store/Service with temporary DBs."""
import asyncio
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

BASE = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(BASE / "backend"), str(BASE / "tools")]
import management as M
from public_access import actor_scope
from service import Service
from state import Store, Catalog
from wire import ProtocolError

TOKEN = b"not-a-real-secret-temporary-test-token-12345"
# These are fake local database keys, never Steam account IDs.
ACCOUNT = "management-test-account"
OTHER = "management-other-account"
OPERATORS = [{"id": role, "role": role, "enabled": True} for role in ("owner", "admin", "moderator")]


def headers(role="admin", key="test-key-0001"):
    return {"Authorization": "Bearer " + TOKEN.decode(), "X-Management-Actor": role, "Idempotency-Key": key}


def rows(db):
    return {name: sorted((tuple(row) for row in db.execute('SELECT * FROM "' + name + '"')), key=repr)
            for (name,) in db.execute("SELECT name FROM sqlite_schema WHERE type='table' ORDER BY name")
            if not name.startswith("sqlite_")}


class Request:
    def __init__(self, tail, *, method="GET", body=None, raw=None, auth=None, query=None, content_type="application/json"):
        self.method, self.match_info = method, {"tail": tail}
        self.headers = headers() if auth is None else auth
        self.query, self.content_type = query or {}, content_type
        self.raw = json.dumps(body).encode() if raw is None else raw
        self.content_length = len(self.raw)

    async def read(self):
        return self.raw


class ManagementTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / "preservation.sqlite3")
        self.addCleanup(self.store.close)
        self.service = Service(self.store, Catalog(BASE / "protocol"), core_test_profile="nonmini-semantic-v1")
        self.store.account(ACCOUNT, "PreservationPlayer")
        self.store.account(OTHER, "OtherPlayer")
        self.service.shop.set_wallet(ACCOUNT, 100, 20, 3)
        self.service.shop.set_wallet(OTHER, 77, 31, 4)
        self.manager = M.Management(self.store, self.service, TOKEN, OPERATORS)
        self.asset = next(x for x in self.service.catalog.items.values()
                          if x["item_id"] not in {r["item_id"] for r in self.service.wardrobe_removal_sentinels.values()})

    def command(self, action, body, *, role="admin", key="test-key-0001", account=ACCOUNT):
        return self.manager.command("users/" + account + "/" + action, {"reason": "Temporary test", **body}, headers(role, key))

    def assert_error(self, status, function, *args, **kwargs):
        with self.assertRaises(M.ManagementError) as error:
            function(*args, **kwargs)
        self.assertEqual(error.exception.status, status)

    def test_valid_service_token_and_enabled_actor_required(self):
        self.assert_error(401, self.manager.actor, {})
        self.assert_error(401, self.manager.actor, {"Authorization": "Bearer wrong", "X-Management-Actor": "owner"})
        self.assert_error(403, self.manager.actor, {"Authorization": "Bearer " + TOKEN.decode()})
        self.assert_error(403, self.manager.actor, headers("unknown"))
        self.assertEqual(self.manager.actor(headers("owner"))["role"], "owner")

    def test_player_context_cannot_use_service_credentials(self):
        with actor_scope(ACCOUNT):
            self.assert_error(403, self.manager.actor, headers("owner"))
            self.assert_error(403, self.command, "wallet-adjustments", {"currency": "crystals", "delta": 5})

    def test_role_header_is_not_authority(self):
        auth = headers("moderator");auth["X-Management-Role"] = "owner"
        self.assert_error(403, self.manager.command, "operators/evil", {"role": "owner", "enabled": True, "reason": "test"}, auth)

    def test_moderator_cannot_mutate_economy_or_identity(self):
        for action, body in (("wallet-adjustments", {"currency": "crystals", "delta": 5}),
                             ("items", {"kind": "housing", "item_id": next(iter(self.service.housing.catalog))}),
                             ("rename", {"username": "Changed"})):
            self.assert_error(403, self.command, action, body, role="moderator")
        self.assertEqual(self.manager.read("stats", {}, self.manager.actor(headers("moderator")))["users"], 2)

    def test_admin_cannot_manage_operators(self):
        self.assert_error(403, self.manager.command, "operators/new", {"role": "moderator", "enabled": True, "reason": "test"}, headers())
        self.assert_error(403, self.manager.read, "operators", {}, self.manager.actor(headers()))

    def test_operator_demotion_revocation_immediate_and_file_no_overwrite(self):
        self.manager.command("operators/admin", {"role": "moderator", "enabled": True, "reason": "test"}, headers("owner"))
        M.Management(self.store, self.service, TOKEN, OPERATORS)
        actor = self.manager.actor(headers())
        self.assertEqual(self.manager.read("me", {}, actor)["permissions"],
                         ["moderation.ban", "moderation.kick", "moderation.mute", "moderation.reports", "read"])
        self.manager.command("operators/admin", {"role": "moderator", "enabled": False, "reason": "test"}, headers("owner", "test-key-0002"))
        self.assert_error(403, self.manager.actor, headers())

    def test_last_owner_protection_rolls_back(self):
        before = rows(self.store.db)
        self.assert_error(409, self.manager.command, "operators/owner", {"role": "admin", "enabled": False, "reason": "test"}, headers("owner"))
        self.assertEqual(rows(self.store.db), before)

    def test_operator_password_never_persisted(self):
        self.assertNotIn("password", json.dumps(rows(self.store.db)))
        self.assertEqual(self.manager.read("roles", {}, self.manager.actor(headers()))["items"][0]["id"], "moderator")

    def test_wallet_idempotent_exact_ledger_and_other_account_unchanged(self):
        before = rows(self.store.db)
        one = self.command("wallet-adjustments", {"currency": "crystals", "delta": 9999})
        two = self.command("wallet-adjustments", {"currency": "crystals", "delta": 9999})
        self.assertTrue(one["changed"]);self.assertTrue(two["replayed"])
        self.assertEqual(one["request_id"], two["request_id"])
        wallet = self.service.shop.wallet(ACCOUNT)
        self.assertEqual((wallet["crystals"], wallet["np"], wallet["level"]), (10099, 20, 3))
        ledger = dict(self.store.db.execute("SELECT * FROM management_wallet_ledger").fetchone())
        self.assertEqual((ledger["delta"], ledger["before_balance"], ledger["after_balance"]), (9999, 100, 10099))
        after = rows(self.store.db)
        for table in before.keys() - {"shop_wallets", "management_audit", "management_requests", "management_wallet_ledger"}:
            self.assertEqual(before[table], after[table], table)
        self.assertEqual(self.service.shop.wallet(OTHER)["crystals"], 77)

    def test_key_conflict_and_actor_scoped_keys(self):
        self.command("wallet-adjustments", {"currency": "crystals", "delta": 1})
        self.assert_error(409, self.command, "wallet-adjustments", {"currency": "crystals", "delta": 2})
        self.command("wallet-adjustments", {"currency": "crystals", "delta": 2}, role="owner")
        self.assertEqual(self.service.shop.wallet(ACCOUNT)["crystals"], 103)

    def test_wallet_bounds_and_boolean_rejected_without_state_changes(self):
        before = rows(self.store.db)
        for delta in (True, 1.5, "2", 0, -101, M.MAX_BALANCE):
            self.assert_error(409 if type(delta) is int and delta in (-101, M.MAX_BALANCE) else 400,
                              self.command, "wallet-adjustments", {"currency": "crystals", "delta": delta})
        self.assertEqual(before, rows(self.store.db))

    def test_wallet_failure_after_nested_set_rolls_back_everything(self):
        before = rows(self.store.db)
        with patch.object(self.manager, "_audit", side_effect=RuntimeError("Injected audit failure")):
            with self.assertRaises(RuntimeError):
                self.command("wallet-adjustments", {"currency": "np", "delta": 5})
        self.assertEqual(before, rows(self.store.db))

    def test_concurrent_connections_same_key_commit_once(self):
        barrier = threading.Barrier(2)
        results, failures = [], []
        def run():
            store = None
            try:
                store = Store(Path(self.tmp.name) / "preservation.sqlite3")
                service = Service(store, Catalog(BASE / "protocol"))
                manager = M.Management(store, service, TOKEN, OPERATORS)
                barrier.wait(timeout=15)
                results.append(manager.command("users/" + ACCOUNT + "/wallet-adjustments",
                                               {"currency": "np", "delta": 7, "reason": "Concurrent request"}, headers()))
            except BaseException as error:
                failures.append(error);barrier.abort()
            finally:
                if store is not None:store.close()
        threads = [threading.Thread(target=run) for _ in range(2)]
        for thread in threads:thread.start()
        for thread in threads:thread.join(timeout=20)
        self.assertFalse(any(t.is_alive() for t in threads));self.assertEqual(failures, [])
        self.assertEqual(len(results), 2);self.assertEqual(sum(r["replayed"] for r in results), 1)
        self.assertEqual(self.service.shop.wallet(ACCOUNT)["np"], 27)
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM management_wallet_ledger").fetchone()[0], 1)

    def test_wallet_preserves_nonempty_preferences_preset_and_custom_durable_table(self):
        with self.store.db:
            self.store.db.execute("INSERT INTO preferences VALUES(?,?,?)", (ACCOUNT, "MasterVolume", "0.75"))
            self.store.db.execute("INSERT INTO presets VALUES(?,?,?,?,?,?,?)", (ACCOUNT, "Saved", "FEMALE", json.dumps({f"blend{i}": i / 100 for i in range(88)}), '["owned-item"]', '[0,1,2]', 123.0))
            self.store.db.execute("INSERT INTO preset_selection VALUES(?,?,?)", (ACCOUNT, "FEMALE", "Saved"))
            self.store.db.execute("CREATE TABLE sqlitex_durable(value TEXT)")
            self.store.db.execute("INSERT INTO sqlitex_durable VALUES('must remain')")
        before = rows(self.store.db)
        self.command("wallet-adjustments", {"currency": "np", "delta": -1})
        after = rows(self.store.db)
        for name in before.keys() - {"shop_wallets", "management_audit", "management_requests", "management_wallet_ledger"}:
            self.assertEqual(before[name], after[name], name)

    def test_item_manifest_grants_and_duplicate_no_metadata_changes(self):
        grants = [dict(kind="wardrobe", item_id=self.asset["item_id"], gender=self.asset["gender"], category=self.asset["category"]),
                  dict(kind="companions", item_id=self.service.resources.catalog.list("companions")[0]["item_id"]),
                  dict(kind="locomotions", item_id=self.service.resources.catalog.list("locomotions")[0]["item_id"]),
                  dict(kind="housing", item_id=next(iter(self.service.housing.catalog)))]
        for index, grant in enumerate(grants):
            one = self.command("items", grant, key=f"grant-key-{index:04}")
            before = rows(self.store.db)
            two = self.command("items", grant, key=f"grant-again-{index:04}")
            self.assertTrue(one["changed"]);self.assertFalse(two["changed"])
            after = rows(self.store.db)
            for table in ("entitlements", "resource_entitlements", "housing_entitlements"):
                self.assertEqual(before[table], after[table])
        self.assertEqual(self.manager.owned(ACCOUNT, {})["total"], 4)

    def test_unknown_item_and_game_role_mutations_rejected(self):
        before = rows(self.store.db)
        for kind in ("housing", "companions", "wardrobe", "admin", "vip"):
            with self.assertRaises((M.ManagementError, ProtocolError)):
                self.command("items", {"kind": kind, "item_id": "unshipped"})
        self.assert_error(404, self.manager.command, "users/" + ACCOUNT + "/flags", {"isDev": True, "reason": "test"}, headers())
        self.assertEqual(before, rows(self.store.db))

    def test_grant_rollback_includes_nested_entitlement(self):
        before = rows(self.store.db)
        with patch.object(self.manager, "_audit", side_effect=RuntimeError("Injected failure")):
            with self.assertRaises(RuntimeError):
                self.command("items", {"kind": "housing", "item_id": next(iter(self.service.housing.catalog))})
        self.assertEqual(before, rows(self.store.db))

    def test_offer_grant_uses_original_helper_preserves_wallet(self):
        shop = self.service.shop
        shop.configure_shop("testshop", 0, "Temporary shop")
        shop.configure_offer("testoffer", "wardrobe", self.asset["item_id"], "testshop", "0", 0 if self.asset["gender"] == "MALE" else 1,
                             "Temporary offer", gender=self.asset["gender"], category=self.asset["category"], crystals=50)
        before = shop.wallet(ACCOUNT)
        result = self.command("items", {"kind": "offer", "offer_id": "testoffer"})
        self.assertTrue(result["changed"]);self.assertEqual(shop.wallet(ACCOUNT), before)
        row = dict(self.store.db.execute("SELECT * FROM shop_owned").fetchone())
        self.assertEqual((row["source"], row["granted_by"]), ("admin", "admin"))
        purchase = self.manager.read("users/" + ACCOUNT + "/purchases", {}, self.manager.actor(headers()))["items"][0]
        self.assertFalse(purchase["historical_price_known"]);self.assertEqual(purchase["current_offer_crystals"], 50)

    def test_rename_preserves_social_relations_and_rejects_collision(self):
        with self.store.db:
            self.store.db.execute("INSERT INTO relations VALUES(?,?,?,?)", (OTHER, "PreservationPlayer", "StandaloneWindows", "friend"))
        result = self.command("rename", {"username": "RenamedPlayer"})
        self.assertTrue(result["changed"])
        self.assertEqual(self.store.db.execute("SELECT target FROM relations WHERE ps4_id=?", (OTHER,)).fetchone()[0], "RenamedPlayer")
        before = rows(self.store.db)
        with self.assertRaises(ProtocolError):
            self.command("rename", {"username": "OtherPlayer"}, key="rename-key-0002")
        self.assertEqual(before, rows(self.store.db))

    def test_audit_ledger_requests_are_append_only(self):
        self.command("wallet-adjustments", {"currency": "np", "delta": 1})
        for table in ("management_audit", "management_wallet_ledger", "management_requests"):
            for command in ('DELETE FROM "' + table + '"', 'UPDATE "' + table + '" SET created_at=0'):
                with self.assertRaises(sqlite3.IntegrityError):
                    with self.store.db:
                        self.store.db.execute(command)

    def test_reads_paginate_literal_search_and_do_not_write(self):
        before = rows(self.store.db);actor = self.manager.actor(headers("owner"))
        one = self.manager.read("users", {"limit": "1"}, actor)
        two = self.manager.read("users", {"limit": "1", "cursor": one["next_cursor"]}, actor)
        self.assertEqual(one["total"], 2);self.assertNotEqual(one["items"], two["items"])
        self.assertEqual(self.manager.read("users", {"q": "%' OR 1=1--"}, actor)["total"], 0)
        for tail in ("health", "me", "roles", "capabilities", "stats", "operators", "audit", "transactions", "users/" + ACCOUNT, "users/" + ACCOUNT + "/wallet", "users/" + ACCOUNT + "/owned", "users/" + ACCOUNT + "/purchases"):
            self.manager.read(tail, {}, actor)
        for kind in ("wardrobe", "companions", "locomotions", "housing", "offer"):
            self.assertIsInstance(self.manager.read("catalog", {"kind": kind}, actor)["items"], list)
        self.assertEqual(before, rows(self.store.db))

    def test_validation_missing_accounts_reason_unknown_fields_and_keys(self):
        self.assert_error(404, self.command, "wallet-adjustments", {"currency": "np", "delta": 1}, account="missing")
        self.assert_error(400, self.command, "wallet-adjustments", {"currency": "np", "delta": 1, "reason": ""})
        self.assert_error(400, self.command, "wallet-adjustments", {"currency": "np", "delta": 1, "level": 99})
        self.assert_error(400, self.command, "wallet-adjustments", {"currency": "np", "delta": 1}, key="short")
        self.assert_error(400, self.manager.command, "operators/new", {"role": {}, "enabled": True, "reason": "test"}, headers("owner"))
        for query in ({"limit": "101"}, {"limit": "0"}, {"cursor": "-1"}, {"cursor": "0 OR 1=1"}):
            self.assert_error(400, self.manager.pagination, query)

    def test_http_envelopes_and_origin_json_auth_limits(self):
        async def call(request):
            response = await self.manager.handle(request)
            return response.status, json.loads(response.body)
        status, body = asyncio.run(call(Request("me")))
        self.assertEqual(status, 200);self.assertEqual(body["data"]["role"], "admin")
        auth = headers();auth["Origin"] = "https://example.invalid"
        self.assertEqual(asyncio.run(call(Request("me", auth=auth)))[0], 403)
        for raw in (b'{"reason":"a","reason":"b"}', b'[]', b'{"delta":NaN}', b'\xff', b'x' * (M.MAX_BODY + 1)):
            status, body = asyncio.run(call(Request("users/" + ACCOUNT + "/wallet-adjustments", method="POST", raw=raw)))
            self.assertIn(status, (400, 413));self.assertIn("error", body)
        self.assertEqual(asyncio.run(call(Request("me", method="DELETE")))[0], 405)




if __name__ == "__main__":
    unittest.main(verbosity=2)
