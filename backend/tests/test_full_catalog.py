"""Complete manifest-backed catalog coverage, transactions and native DTOs."""
import json
import importlib.util
import hashlib
import sqlite3
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "tools")]
from avatar_entry_codec import decode_entry_fields
from catalog_inventory import CatalogInventory, POLICY, STORE_TYPE_ALIASES, identity, offer_id, preview_fields, seed_full_catalog
from management import Management, ManagementError
from seed_local_shops import seed
from service import Service
from shop import ITEM_DATA, TYPE_DATA
from state import Catalog, Store
from wire import ProtocolError, Request, decrypt, encrypt


class FullCatalog(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "preservation.sqlite3")
        self.service = Service(self.store, Catalog(ROOT / "protocol"))

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def call(self, route, *values):
        return self.service.shop.dispatch(route, Request(tuple(map(str, values)), "StandaloneWindows"))

    def test_complete_coverage_excludes_controls_and_retains_unicode_and_generic_metadata(self):
        result = seed_full_catalog(self.service)
        self.assertEqual(result["after"]["grantable"], 7688)
        self.assertEqual(result["after"]["offered"], 7688)
        self.assertEqual(result["after"]["unoffered"], 0)
        self.assertEqual(result["after"]["excluded_removal_controls"], 20)
        rows = CatalogInventory(self.service).items
        self.assertEqual(len([r for r in rows if not r["own_thumbnail_known"]]), 2)
        unicode_row = next(r for r in rows if r["item_id"] == "A52F4P60JdJJ25KÑ7M8TR0ÑJ2XF2EV82")
        self.assertIn(unicode_row["item_id"], unicode_row["thumbnail_path"])
        self.assertIn("filename", unicode_row["asset_metadata"])
        self.assertIn("manifest_asset_text", unicode_row["asset_metadata"])
        expected_key = hashlib.sha256(unicode_row["thumbnail_path"].replace("\\", "/").lower().encode("utf-8")).hexdigest()
        self.assertEqual(unicode_row["preview_key"], expected_key)
        self.assertEqual(unicode_row["preview_url"], "/api/catalog-preview/" + expected_key)
        self.assertEqual(unicode_row["provenance"]["historical_store"], "unknown")
        self.assertIsNone(unicode_row["original_name"])
        rare = [r for r in rows if r["category"] in STORE_TYPE_ALIASES]
        self.assertEqual(len(rare), 4)
        for row in rare:
            offer = self.store.db.execute("SELECT category,type_id FROM shop_offers WHERE offer_id=?", (offer_id(row),)).fetchone()
            self.assertEqual(offer["category"], row["category"])
            self.assertEqual(offer["type_id"], STORE_TYPE_ALIASES[row["category"]])

    def test_existing_offers_player_state_and_repeated_import_are_unchanged(self):
        seed(self.service.shop, self.service.catalog, self.service.resources.catalog, self.service.housing)
        self.store.account("catalog-preservation-user", "Catalog Tester")
        self.service.shop.set_wallet("catalog-preservation-user", 1234, 567)
        old = [tuple(r) for r in self.store.db.execute("SELECT * FROM shop_offers ORDER BY offer_id")]
        result = seed_full_catalog(self.service)
        self.assertEqual(result["preserved_existing_offers"], 15)
        self.assertEqual(result["created_offers"], 7674)
        for row in old:
            self.assertEqual(tuple(self.store.db.execute("SELECT * FROM shop_offers WHERE offer_id=?", (row[0],)).fetchone()), row)
        before = self.store.db.serialize()
        repeated = seed_full_catalog(self.service)
        self.assertEqual(repeated["created_offers"], 0)
        self.assertEqual(repeated["created_shops"], 0)
        self.assertEqual(self.store.db.serialize(), before)
        self.assertEqual(self.service.shop.wallet("catalog-preservation-user")["crystals"], 1234)
        self.assertEqual(self.store.inventory("catalog-preservation-user"), [])

    def test_import_failure_rolls_back_both_store_and_offer_rows(self):
        before = self.store.db.serialize()
        original = self.service.shop.configure_offer
        calls = []
        def fail(*args, **kwargs):
            calls.append(1)
            if len(calls) == 4:
                raise RuntimeError("Injected fourth offer failure")
            return original(*args, **kwargs)
        with patch.object(self.service.shop, "configure_offer", side_effect=fail):
            with self.assertRaisesRegex(RuntimeError, "fourth"):
                seed_full_catalog(self.service)
        self.assertEqual(self.store.db.serialize(), before)

    def test_offer_coverage_is_read_under_writer_lock(self):
        rival = sqlite3.connect(Path(self.temp.name) / "preservation.sqlite3", timeout=0)
        original = CatalogInventory.snapshot
        attempts = []
        def snapshot(inventory):
            if not attempts:
                self.assertTrue(self.store.db.in_transaction)
                with self.assertRaisesRegex(sqlite3.OperationalError, "locked"):
                    rival.execute("INSERT INTO shop_catalogs VALUES('rival',0,'Rival','','',1)")
                rival.rollback()
                attempts.append(True)
            return original(inventory)
        try:
            with patch.object(CatalogInventory, "snapshot", snapshot):
                result = seed_full_catalog(self.service)
            self.assertEqual(result["after"]["offered"], 7688)
            self.assertEqual(attempts, [True])
        finally:
            rival.close()

    def test_existing_inactive_offer_is_not_bypassed_or_repriced(self):
        seed_full_catalog(self.service)
        oid = self.store.db.execute("SELECT offer_id FROM shop_offers LIMIT 1").fetchone()[0]
        with self.store.db:
            self.store.db.execute("UPDATE shop_offers SET active=0,np=98,name='Operator choice' WHERE offer_id=?", (oid,))
        result = seed_full_catalog(self.service)
        self.assertEqual(result["created_offers"], 0)
        self.assertEqual(result["inactive_existing_items"], 1)
        self.assertEqual(tuple(self.store.db.execute("SELECT active,np,name FROM shop_offers WHERE offer_id=?", (oid,)).fetchone()), (0, 98, "Operator choice"))

    def test_native_shop_navigation_reaches_every_offer_exactly_once(self):
        seed_full_catalog(self.service)
        self.store.account("catalog-client", "Catalog Client")
        self.store.bind_session("catalog-client", "catalog-guid")
        reached = set()
        def decode(response, schema):
            encrypted = encrypt(response)
            self.assertLess(len(encrypted.encode("ascii")), 8 * 1024 * 1024)
            self.assertEqual(decrypt(encrypted), response)
            fields = response.split("#")
            self.assertEqual(len(fields), int(fields[3]) + 4)
            return [decode_entry_fields(value, schema) for value in fields[4:]]
        for store in self.store.db.execute("SELECT shop_id FROM shop_catalogs ORDER BY shop_id").fetchall():
            sid = store[0]
            fields = self.call("GetGenderDataShopServlet", "catalog-guid", "catalog-client", sid).split("#")
            for index in range(4, len(fields), 2):
                gender = int(fields[index])
                response = self.call("GetShopTypeDataShopServlet", "catalog-guid", "catalog-client", sid, gender)
                if gender in (0, 1):
                    for category in decode(response, TYPE_DATA):
                        for row in decode(self.call("GetItemAssetsDataServlet", "catalog-guid", "catalog-client", sid, gender, category["typeID"]), ITEM_DATA):
                            self.assertNotIn(row["id"], reached); reached.add(row["id"])
                else:
                    for row in decode(response, ITEM_DATA):
                        self.assertNotIn(row["id"], reached); reached.add(row["id"])
        self.assertEqual(len(reached), 7688)

    def test_generated_offer_purchases_both_currencies_alias_unicode_and_fresh_process_state(self):
        seed_full_catalog(self.service)
        self.store.account("catalog-buyer", "Catalog Buyer")
        self.store.bind_session("catalog-buyer", "catalog-guid")
        self.service.shop.set_wallet("catalog-buyer", 10000, 10000)
        selected = []
        for kind in ("wardrobe", "companions", "housing", "locomotions"):
            selected.extend(dict(r) for r in self.store.db.execute("SELECT * FROM shop_offers WHERE kind=? ORDER BY offer_id LIMIT 2", (kind,)))
        for predicate in (lambda r: r["category"] in STORE_TYPE_ALIASES,
                          lambda r: "Ñ" in r["item_id"]):
            row = next(r for r in CatalogInventory(self.service).items if predicate(r)
                       and offer_id(r) not in {o["offer_id"] for o in selected})
            selected.append(dict(self.store.db.execute("SELECT * FROM shop_offers WHERE offer_id=?", (offer_id(row),)).fetchone()))
        expected = {"crystals": 10000, "np": 10000}
        for index, row in enumerate(selected):
            option = index % 2
            args = ("catalog-guid", "catalog-buyer", row["offer_id"], row["crystals"], row["np"], option)
            self.assertTrue(self.call("NPShopBuyItemServlet", *args).endswith("#OK"))
            currency = "np" if option else "crystals"; expected[currency] -= row[currency]
            self.assertEqual({k: self.service.shop.wallet("catalog-buyer")[k] for k in expected}, expected)
            self.assertTrue(self.call("NPShopBuyItemServlet", *args).endswith("#ISPURCHASED"))
        self.assertEqual(len(self.store.inventory("catalog-buyer")), 4)
        self.assertEqual(len(self.service.resources.list("catalog-buyer", "companions")), 2)
        self.assertEqual(len(self.service.resources.list("catalog-buyer", "locomotions")), 2)
        self.assertEqual(len(self.service.housing.inventory("catalog-buyer")), 2)
        self.store.close()
        self.store = Store(Path(self.temp.name) / "preservation.sqlite3")
        self.service = Service(self.store, Catalog(ROOT / "protocol"))
        self.store.bind_session("catalog-buyer", "fresh-catalog-guid")
        self.assertEqual({k: self.service.shop.wallet("catalog-buyer")[k] for k in expected}, expected)
        for row in selected:
            self.assertTrue(self.call("NPShopIsItemPurchasedServlet", "fresh-catalog-guid", "catalog-buyer", row["offer_id"]).endswith("#True"))
        for row in self.store.inventory("catalog-buyer"):
            asset = self.service.catalog.resolve(row["item_id"], row["gender"], row["category"])
            self.assertIn(row["item_id"], asset["requested_resource_path"])

    def test_metadata_search_filters_paging_and_live_offer_changes(self):
        seed_full_catalog(self.service)
        manager = Management(self.store, self.service, b"fake-catalog-test-token-not-a-real-secret", [{"id": "owner", "role": "owner", "enabled": True}])
        response = manager.catalog({"kind": "all", "limit": "2"})
        self.assertEqual(response["total"], 7688)
        self.assertEqual(len(response["items"]), 2)
        self.assertEqual(response["counts"]["wardrobe"], 6210)
        self.assertEqual(response["coverage"]["offered"], 7688)
        next_page = manager.catalog({"kind": "all", "limit": "2", "cursor": response["next_cursor"]})
        self.assertNotEqual(response["items"][0]["item_id"], next_page["items"][0]["item_id"])
        row = next(r for r in CatalogInventory(self.service).items if "Ñ" in r["item_id"])
        hit = manager.catalog({"kind": "all", "q": row["item_id"]})
        self.assertEqual(hit["total"], 1)
        self.assertEqual(hit["items"][0]["item_id"], row["item_id"])
        filtered = manager.catalog({"kind": "wardrobe", "gender": "FEMALE", "category": "CLOTH_BODY_FEET", "store_id": POLICY + "-wardrobe"})
        self.assertTrue(filtered["total"] > 0)
        self.assertTrue(all(r["gender"] == "FEMALE" and r["category"] == "CLOTH_BODY_FEET" for r in filtered["items"]))
        with self.store.db:
            self.store.db.execute("UPDATE shop_offers SET crystals=777 WHERE offer_id=?", (hit["items"][0]["offers"][0]["offer_id"],))
        self.assertEqual(manager.catalog({"kind": "all", "q": row["item_id"]})["items"][0]["offers"][0]["crystals"], 777)
        for query in ({"kind": "invalid"}, {"q": "x" * 129}, {"gender": ["MALE"]}):
            with self.assertRaises(ManagementError): manager.catalog(query)

    def test_offer_id_collision_and_missing_thumbnail_fail_closed(self):
        inventory = CatalogInventory(self.service)
        row, other = inventory.items[:2]
        self.service.shop.configure_shop("collision-store", 1, "Operator store")
        self.service.shop.configure_offer(offer_id(row), other["kind"], other["item_id"], "collision-store", "items", 3, "Existing unrelated offer")
        before = self.store.db.serialize()
        with self.assertRaisesRegex(ProtocolError, "collision"):
            seed_full_catalog(self.service)
        self.assertEqual(self.store.db.serialize(), before)
        with patch.object(self.service.shop, "_thumbnail", side_effect=ProtocolError("Missing manifest")):
            with self.assertRaisesRegex(ProtocolError, "unresolved thumbnail"):
                seed_full_catalog(self.service)
        self.assertEqual(self.store.db.serialize(), before)

    def test_docker_enables_full_catalog_and_can_explicitly_opt_out(self):
        spec = importlib.util.spec_from_file_location("catalog_entrypoint", ROOT / "deployment/docker/entrypoint.py")
        entrypoint = importlib.util.module_from_spec(spec); spec.loader.exec_module(entrypoint)
        env = {name: "a" * 64 for name in ("NEBULA_BUILD_REPORT_SHA256", "NEBULA_SERVER_SHA256", "NEBULA_MANAGED_SHA256")}
        backend, _supervisor, _config = entrypoint.plan(env)
        self.assertEqual(backend[backend.index("--catalog-policy") + 1], POLICY)
        backend, _supervisor, _config = entrypoint.plan({**env, "NEBULA_CATALOG_POLICY": "none"})
        self.assertEqual(backend[backend.index("--catalog-policy") + 1], "none")
        with self.assertRaisesRegex(ValueError, "catalog policy"):
            entrypoint.plan({**env, "NEBULA_CATALOG_POLICY": "guess-original-prices"})

    def test_artwork_is_read_only_metadata_not_a_store_or_entitlement(self):
        manager = Management(self.store, self.service, b"fake-catalog-test-token-not-a-real-secret", [{"id": "owner", "role": "owner", "enabled": True}])
        response = manager.catalog({"kind": "shop_artwork", "limit": "1"})
        self.assertEqual(response["total"], 1205)
        self.assertEqual(response["counts"]["all"], 7688)
        self.assertFalse(response["items"][0]["grantable"])
        self.assertFalse(response["items"][0]["historical_store_membership_known"])
        self.assertEqual(response["items"][0]["offers"], [])
        resource_key = response["items"][0]["resource_key"]
        self.assertEqual(response["items"][0]["preview_key"], hashlib.sha256(resource_key.replace("\\", "/").lower().encode("utf-8")).hexdigest())
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM shop_catalogs").fetchone()[0], 0)

    def test_preview_keys_are_opaque_deterministic_and_preserve_resource_identity(self):
        path = "MALE/CLOTH_HEAD_HAT/ExactÑID/ExactÑIDThumbnail.png"
        fields = preview_fields(path)
        self.assertEqual(fields, preview_fields(path.lower().replace("/", "\\")))
        self.assertRegex(fields["preview_url"], r"^/api/catalog-preview/[0-9a-f]{64}$")
        self.assertNotEqual(fields, preview_fields(path + " "))
        self.assertNotEqual(preview_fields("Shops/shop"), preview_fields("Shops/shop.png"))
        self.assertEqual(preview_fields(None), {"preview_key": None, "preview_url": None})
        rows = CatalogInventory(self.service).items
        fallback = [r for r in rows if not r["own_thumbnail_known"]]
        self.assertEqual(len(fallback), 2)
        self.assertTrue(all(r["thumbnail_source"] == "generic_shipped_shop_icon" for r in fallback))
        self.assertEqual(fallback[0]["preview_key"], fallback[1]["preview_key"])
        self.assertTrue(all(r["preview_key"] and r["preview_url"] for r in rows))


if __name__ == "__main__":
    unittest.main()
