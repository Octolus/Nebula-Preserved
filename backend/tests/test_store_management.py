"""Disposable database tests of audited store administration and native DTOs."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "tools")]
from avatar_entry_codec import decode_entry_fields
from catalog_inventory import CatalogInventory, POLICY, seed_full_catalog
from management import Management, ManagementError, MAX_BALANCE
from seed_local_shops import seed
from service import Service
from shop import ITEM_DATA, SHOP_DATA
from state import Catalog, Store
from wire import ProtocolError, Request


TOKEN = b"synthetic-store-management-service-token-0001"
ACCOUNT = "store-management-fixture-player"
OPERATORS = [{"id": role, "role": role, "enabled": True} for role in ("owner", "admin", "moderator")]


def snapshot(db):
    return {name: sorted((tuple(r) for r in db.execute('SELECT * FROM "' + name + '"')), key=repr)
            for (name,) in db.execute("SELECT name FROM sqlite_schema WHERE type='table'")
            if not name.startswith("sqlite_")}


class StoreManagementContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog(ROOT / "protocol")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "state.sqlite3")
        self.service = Service(self.store, self.catalog)
        seed(self.service.shop, self.service.catalog, self.service.resources.catalog, self.service.housing)
        self.manager = Management(self.store, self.service, TOKEN, OPERATORS)
        self.store.account(ACCOUNT, "Store Fixture")
        self.store.bind_session(ACCOUNT, "store-fixture-guid")
        self.counter = 0
        self.companion = dict(self.store.db.execute("SELECT * FROM shop_offers WHERE kind='companions' LIMIT 1").fetchone())

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def headers(self, role="admin", key=None):
        self.counter += 1
        return {"Authorization": "Bearer " + TOKEN.decode(), "X-Management-Actor": role,
                "Idempotency-Key": key or f"store-management-{self.counter:08}"}

    def command(self, route, body, role="admin", key=None):
        return self.manager.command(route, {"reason": "Synthetic store administration", **body}, self.headers(role, key))

    def call(self, route, *fields):
        return self.service.shop.dispatch(route, Request(tuple(map(str, fields)), "StandaloneWindows"))

    def native_items(self, shop_id):
        result = self.call("GetShopTypeDataShopServlet", "store-fixture-guid", ACCOUNT, shop_id, 3).split("#")
        return [decode_entry_fields(value, ITEM_DATA) for value in result[4:]]

    def test_store_collection_pagination_search_and_read_permissions(self):
        actor = self.manager.actor(self.headers("moderator"), "read")
        page = self.manager.read("stores", {"limit": "2"}, actor)
        self.assertEqual(page["total"], 4)
        self.assertEqual(len(page["items"]), 2)
        later = self.manager.read("stores", {"limit": "2", "cursor": page["next_cursor"]}, actor)
        self.assertEqual(len(later["items"]), 2)
        self.assertEqual({r["kind"] for r in page["items"] + later["items"]}, {"wardrobe", "housing", "companions", "locomotions"})
        detail = self.manager.read("stores/" + self.companion["shop_id"], {}, actor)
        self.assertIs(type(detail["active"]), bool)
        self.assertGreater(detail["total_offers"], 0)
        found = self.manager.read("stores", {"q": "companions"}, actor)
        self.assertEqual(len(found["items"]), 1)

    def test_store_create_edit_is_audited_idempotent_and_immediately_native(self):
        body = {"type_shop": 1, "name": "Community Companions", "description": "Current community collection", "active": True}
        created = self.command("stores/community-companions", body, key="same-store-command")
        replay = self.command("stores/community-companions", body, key="same-store-command")
        self.assertTrue(created["changed"])
        self.assertTrue(replay["replayed"])
        self.assertEqual(created["audit_id"], replay["audit_id"])
        result = self.call("GetShopDataShopServlet", "store-fixture-guid", ACCOUNT, "True", "False", 1).split("#")
        native = [decode_entry_fields(v, SHOP_DATA) for v in result[4:]]
        self.assertTrue(any(r["name"] == body["name"] and r["desciption"] == body["description"] for r in native))
        self.command("stores/community-companions", {"name": "Renamed collection", "active": False})
        result = self.call("GetShopDataShopServlet", "store-fixture-guid", ACCOUNT, "True", "False", 1).split("#")
        self.assertFalse(any(decode_entry_fields(v, SHOP_DATA)["id"] == "community-companions" for v in result[4:]))

    def test_offer_create_derives_exact_native_fields_and_refuses_identity_reassignment(self):
        asset = self.service.resources.catalog.list("companions")[0]
        self.command("stores/new-companion-store", {"type_shop": 1, "name": "Companions"})
        result = self.command("store-offers/new-companion-offer", {"kind": "companions", "item_id": asset["item_id"],
            "shop_id": "new-companion-store", "name": "Community label", "crystals": 0, "np": MAX_BALANCE, "active": True, "featured": False})
        after = result["after"]
        self.assertEqual((after["gender_id"], after["type_id"]), (3, "items"))
        self.assertEqual(after["image_path"], self.service.shop._thumbnail("companions", asset["item_id"], asset))
        self.assertEqual(self.native_items("new-companion-store")[0]["name"], "Community label")
        with self.assertRaises(ManagementError) as error:
            self.command("store-offers/new-companion-offer", {"item_id": "different"})
        self.assertEqual(error.exception.status, 409)
        detail = self.manager.read("store-offers/new-companion-offer", {}, {"id": "admin", "role": "admin"})
        self.assertTrue(detail["preview_url"].startswith("/api/catalog-preview/"))
        self.assertEqual(detail["name_source"], "operator_configured")

    def test_offer_updates_refresh_native_name_price_availability_and_purchase_validation(self):
        oid, sid = self.companion["offer_id"], self.companion["shop_id"]
        self.service.shop.set_wallet(ACCOUNT, 500, 100)
        self.command("store-offers/" + oid, {"name": "Operator companion", "crystals": 17, "np": 3, "featured": True})
        native = next(r for r in self.native_items(sid) if r["id"] == self.companion["item_id"])
        self.assertEqual((native["name"], native["crystals"], native["np"]), ("Operator companion", 17, 3))
        with self.assertRaises(ProtocolError) as stale:
            self.call("NPShopBuyItemServlet", "store-fixture-guid", ACCOUNT, oid, self.companion["crystals"], self.companion["np"], 0)
        self.assertEqual(stale.exception.status, 409)
        self.assertEqual(self.service.shop.wallet(ACCOUNT)["crystals"], 500)
        self.assertTrue(self.call("NPShopBuyItemServlet", "store-fixture-guid", ACCOUNT, oid, 17, 3, 0).endswith("#OK"))
        owned_before = [tuple(r) for r in self.store.db.execute("SELECT * FROM resource_entitlements")]
        self.command("store-offers/" + oid, {"active": False})
        self.assertFalse(any(r["id"] == self.companion["item_id"] for r in self.native_items(sid)))
        self.assertEqual(owned_before, [tuple(r) for r in self.store.db.execute("SELECT * FROM resource_entitlements")])
        self.assertEqual(self.service.shop.wallet(ACCOUNT)["crystals"], 483)

    def test_kind_incompatible_store_and_populated_type_changes_are_atomic(self):
        before = snapshot(self.store.db)
        for route, body in [("stores/" + self.companion["shop_id"], {"type_shop": 0}),
                            ("store-offers/" + self.companion["offer_id"], {"shop_id": "local-preservation-clothing"})]:
            with self.assertRaises(ManagementError) as error:
                self.command(route, body)
            self.assertEqual(error.exception.status, 409)
            self.assertEqual(before, snapshot(self.store.db))

    def test_strict_bools_prices_text_ids_and_field_allowlists(self):
        before = snapshot(self.store.db)
        invalid = [{"crystals": x} for x in (True, -1, 1.1, "2", MAX_BALANCE + 1, None)]
        invalid += [{"active": x} for x in (0, 1, "true", None)]
        invalid += [{"featured": 1}, {"name": "bad#wire"}, {"name": "hidden\u202evalue"}, {"name": ""},
                    {"image_path": "https://untrusted.invalid/image"}, {"gender_id": 0}, {"delete": True}]
        for body in invalid:
            with self.subTest(body=body), self.assertRaises((ManagementError, ProtocolError)):
                self.command("store-offers/" + self.companion["offer_id"], body)
            self.assertEqual(before, snapshot(self.store.db))
        for identity in ("../escape", "a/b", "%2e", "x#y", "a" * 129):
            with self.assertRaises(ManagementError):
                self.manager.stores.change("stores", identity, {"name": "No", "type_shop": 1})
        with self.assertRaises(ManagementError):
            self.command("stores/new", {"type_shop": True, "name": "No"})

    def test_moderators_cannot_modify_or_replay_catalog_commands(self):
        before = snapshot(self.store.db)
        with self.assertRaises(ManagementError) as error:
            self.command("store-offers/" + self.companion["offer_id"], {"active": False}, role="moderator")
        self.assertEqual(error.exception.status, 403)
        self.assertEqual(before, snapshot(self.store.db))
        body = {"name": "Owner edit"}
        self.command("store-offers/" + self.companion["offer_id"], body, role="owner", key="owner-edit-replay")
        with self.store.db:
            self.store.db.execute("UPDATE management_operators SET enabled=0 WHERE operator_id='owner'")
        with self.assertRaises(ManagementError) as error:
            self.command("store-offers/" + self.companion["offer_id"], body, role="owner", key="owner-edit-replay")
        self.assertEqual(error.exception.status, 403)

    def test_idempotency_conflict_and_failed_audit_rollback_configuration_and_provenance(self):
        route = "store-offers/" + self.companion["offer_id"]
        self.command(route, {"np": 1}, key="store-idempotency-1")
        before = snapshot(self.store.db)
        with self.assertRaises(ManagementError) as conflict:
            self.command(route, {"np": 2}, key="store-idempotency-1")
        self.assertEqual(conflict.exception.status, 409)
        with patch.object(self.manager, "_audit", side_effect=RuntimeError("Injected audit failure")):
            with self.assertRaisesRegex(RuntimeError, "audit failure"):
                self.command(route, {"name": "Not committed", "crystals": 1})
        self.assertEqual(before, snapshot(self.store.db))

    def test_unknown_control_items_and_new_bundles_are_not_listable(self):
        before = snapshot(self.store.db)
        control = next(iter(self.service.wardrobe_removal_sentinels.values()))
        for body in [dict(kind="wardrobe", item_id=control["item_id"], gender=control["gender"], category=control["category"], shop_id="local-preservation-clothing"),
                     dict(kind="companions", item_id="not-shipped", shop_id=self.companion["shop_id"]),
                     dict(kind="bundle", shop_id="local-preservation-clothing")]:
            with self.assertRaises(ManagementError):
                self.command("store-offers/unreviewed-offer", {"name": "No", **body})
        self.assertEqual(before, snapshot(self.store.db))

    def test_existing_bundle_terms_can_change_without_membership_or_identity_changes(self):
        row = self.store.db.execute("SELECT * FROM shop_offers WHERE kind='bundle'").fetchone()
        self.assertIsNotNone(row)
        children = [tuple(r) for r in self.store.db.execute("SELECT * FROM shop_bundle_items")]
        result = self.command("store-offers/" + row["offer_id"], {"name": "Community bundle", "crystals": 2, "active": False})
        self.assertEqual(result["after"]["name"], "Community bundle")
        self.assertEqual(children, [tuple(r) for r in self.store.db.execute("SELECT * FROM shop_bundle_items")])

    def test_operator_provenance_survives_full_catalog_reseed_and_service_reopen(self):
        seed_full_catalog(self.service)
        oid = self.store.db.execute("SELECT offer_id FROM shop_offers WHERE offer_id LIKE ? LIMIT 1", (POLICY + "-%",)).fetchone()[0]
        sid = self.store.db.execute("SELECT shop_id FROM shop_offers WHERE offer_id=?", (oid,)).fetchone()[0]
        self.command("store-offers/" + oid, {"name": "Operator descriptive label", "crystals": 7})
        self.command("stores/" + sid, {"name": "Operator store", "active": False})
        before = snapshot(self.store.db)
        result = seed_full_catalog(self.service)
        self.assertEqual((result["created_shops"], result["created_offers"]), (0, 0))
        self.assertEqual(before, snapshot(self.store.db))
        data = self.manager.read("store-offers/" + oid, {}, {"id": "admin", "role": "admin"})
        self.assertEqual(data["name_source"], "operator_configured")
        self.assertEqual(data["price_source"], "operator_configured")
        self.assertEqual(data["store_assignment_source"], "preservation_policy")
        self.assertIsNone(data["original_name"])
        self.store.close()
        self.store = Store(Path(self.temp.name) / "state.sqlite3")
        self.service = Service(self.store, self.catalog)
        self.manager = Management(self.store, self.service, TOKEN, OPERATORS)
        reopened = self.manager.read("store-offers/" + oid, {}, {"id": "admin", "role": "admin"})
        self.assertEqual(reopened["name"], "Operator descriptive label")
        self.assertEqual(reopened["name_source"], "operator_configured")

    def test_noop_edits_retain_provenance_but_still_record_audit(self):
        oid = self.companion["offer_id"]
        audits = self.store.db.execute("SELECT COUNT(*) FROM management_audit").fetchone()[0]
        result = self.command("store-offers/" + oid, {"name": self.companion["name"]})
        self.assertFalse(result["changed"])
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM management_catalog_overrides").fetchone()[0], 0)
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM management_audit").fetchone()[0], audits + 1)


if __name__ == "__main__":
    unittest.main()
