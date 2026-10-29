"""Reachability tests for the small manifest-backed local shop seed."""
from pathlib import Path
import json
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch


BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(ROOT / "tools"))

from avatar_entry_codec import decode_entry_fields
from housing import HousingStore
from resources import ResourceCatalog, ResourceEntitlements
from seed_local_shops import CLIENT_SHOP_URL_PREFIX, SHOP_SPECS, execute
from shop import ITEM_DATA, SHOP_DATA, TYPE_DATA, Shop
from state import Catalog, Store
from wire import Request


def entries(response, schema):
    fields = response.split("#")
    return [decode_entry_fields(value, schema) for value in fields[4:4 + int(fields[3])]]


def gender_ids(response):
    fields = response.split("#")
    return [int(fields[index]) for index in range(4, 4 + int(fields[3]), 2)]


class LocalShopSeed(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.protocol = ROOT / "protocol"
        cls.scratch = (Path(tempfile.gettempdir()) / "nebula-preserved-tests") / "offline-shop-seed-tests"
        cls.scratch.mkdir(parents=True, exist_ok=True)

    def setUp(self):
        self.no_network = patch.object(socket, "socket", side_effect=AssertionError(
            "No network in local shop seed tests"))
        self.no_network.start()
        self.temp = tempfile.TemporaryDirectory(dir=self.scratch)
        self.state = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()
        self.no_network.stop()

    def test_dry_run_does_not_create_requested_state(self):
        requested = self.state / "must-remain-absent"
        result = execute(self.protocol, requested, apply=False)
        self.assertEqual(result["mode"], "dry-run")
        self.assertIsNone(result["state_dir"])
        self.assertFalse(requested.exists())
        self.assertEqual([row["type_shop"] for row in result["shops"]], [0, 1, 2, 3])

    def test_applied_seed_is_reachable_through_native_shop_flow(self):
        result = execute(self.protocol, self.state, apply=True, account_id="seed-a",
                         starter_crystals=500, starter_np=200)
        self.assertEqual(result["wallet"]["crystals"], 500)
        store = Store(self.state / "preservation.sqlite3")
        try:
            store.account("seed-a", "Seeder")
            store.bind_session("seed-a", "seed-guid")
            catalog = Catalog(self.protocol)
            resource_catalog = ResourceCatalog(self.protocol)
            resources = ResourceEntitlements(store, resource_catalog)
            housing = HousingStore(store, self.protocol)
            shop = Shop(store, catalog, resources, housing)

            def call(route, *values):
                return shop.dispatch(route, Request(tuple(str(v) for v in values),
                                                    "StandaloneWindows"))

            shops = {}
            for type_shop in range(4):
                rows = entries(call("GetShopDataShopServlet", "seed-guid", "seed-a",
                                    "True", "False", type_shop), SHOP_DATA)
                self.assertEqual(len(rows), 1)
                expected_image = SHOP_SPECS[type_shop][3]
                self.assertEqual(len(CLIENT_SHOP_URL_PREFIX), 57)
                self.assertEqual(rows[0]["url"][57:-4], expected_image)
                self.assertEqual(rows[0]["url"][-4:], ".png")
                shops[type_shop] = rows[0]["id"]
            self.assertEqual(gender_ids(call("GetGenderDataShopServlet", "seed-guid", "seed-a",
                                             shops[0])), [0, 1, 2])
            self.assertEqual(gender_ids(call("GetGenderDataShopServlet", "seed-guid", "seed-a",
                                             shops[1])), [3])
            self.assertEqual(gender_ids(call("GetGenderDataShopServlet", "seed-guid", "seed-a",
                                             shops[2])), [5])
            self.assertEqual(gender_ids(call("GetGenderDataShopServlet", "seed-guid", "seed-a",
                                             shops[3])), [6])

            clothing_types = entries(call("GetShopTypeDataShopServlet", "seed-guid", "seed-a",
                                          shops[0], 0), TYPE_DATA)
            self.assertTrue(clothing_types)
            clothing = entries(call("GetItemAssetsDataServlet", "seed-guid", "seed-a",
                                    shops[0], 0, clothing_types[0]["typeID"]), ITEM_DATA)
            self.assertTrue(clothing)
            for shop_type, selected_id in ((1, 3), (2, 5), (3, 6)):
                direct = entries(call("GetShopTypeDataShopServlet", "seed-guid", "seed-a",
                                      shops[shop_type], selected_id), ITEM_DATA)
                self.assertTrue(direct)
        finally:
            store.close()

    @unittest.skip("Private extracted resource sprite inventory is not redistributed")
    def test_shop_card_urls_slice_to_shipped_resource_sprites(self):
        resource_rows = json.loads(((Path(tempfile.gettempdir()) / "nebula-preserved-tests") / "evidence" / "assets" /
                                    "resource-paths.json").read_text(encoding="utf-8"))
        paths = {row[0] for row in resource_rows}
        self.assertEqual(len(CLIENT_SHOP_URL_PREFIX), 57)
        for _shop_id, _type_shop, _name, image_id in SHOP_SPECS:
            self.assertIn("shops/" + image_id, paths)

        result = execute(self.protocol, self.state, apply=True)
        for row in result["shops"]:
            # Exact native EntryShop.Set operation: Substring(57, Length-61).
            self.assertEqual(row["url"][57:len(row["url"]) - 4],
                             row["image_resource_id"])

    def test_repair_only_updates_existing_local_shop_urls(self):
        execute(self.protocol, self.state, apply=True, account_id="seed-a",
                starter_crystals=321, starter_np=123)
        store = Store(self.state / "preservation.sqlite3")
        try:
            before_offers = [tuple(row) for row in store.db.execute(
                "SELECT * FROM shop_offers ORDER BY offer_id")]
            with store.db:
                store.db.execute("UPDATE shop_catalogs SET url='' WHERE shop_id LIKE 'local-preservation-%'")
                store.db.execute("INSERT INTO shop_catalogs VALUES(?,?,?,?,?,?)",
                                 ("unrelated-shop", 0, "Unrelated", "", "keep-me", 1))
        finally:
            store.close()

        repaired = execute(self.protocol, self.state, apply=True, repair_images=True)
        self.assertEqual(repaired["repair"]["matched"], 4)
        self.assertEqual(set(repaired["repair"]["updated"]),
                         {spec[0] for spec in SHOP_SPECS})
        store = Store(self.state / "preservation.sqlite3")
        try:
            self.assertEqual(tuple(store.db.execute(
                "SELECT crystals,np FROM shop_wallets WHERE ps4_id='seed-a'").fetchone()),
                             (321, 123))
            self.assertEqual([tuple(row) for row in store.db.execute(
                "SELECT * FROM shop_offers ORDER BY offer_id")], before_offers)
            self.assertEqual(store.db.execute(
                "SELECT url FROM shop_catalogs WHERE shop_id='unrelated-shop'").fetchone()[0],
                             "keep-me")
            for shop_id, _type_shop, _name, image_id in SHOP_SPECS:
                url = store.db.execute(
                    "SELECT url FROM shop_catalogs WHERE shop_id=?", (shop_id,)).fetchone()[0]
                self.assertEqual(url[57:-4], image_id)
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()

