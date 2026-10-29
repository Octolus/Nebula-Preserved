"""Offline shop contract and replacement-policy tests; sockets are forbidden."""
import json
from pathlib import Path
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
from shop import GENDER_DATA, ITEM_DATA, SHOP_DATA, TYPE_DATA, Shop
from state import Catalog, Store
from wire import ProtocolError, Request


def decode_list(response, schema):
    fields = response.split("#")
    count = int(fields[3])
    return [decode_entry_fields(value, schema) for value in fields[4:4 + count]]


def decode_gender_pairs(response):
    fields = response.split("#")
    scalar_count = int(fields[3])
    if scalar_count % 2 or len(fields) != 4 + scalar_count:
        raise AssertionError("native GetGenderData pair framing is invalid")
    return [{"genderID": int(fields[i]), "show": fields[i + 1] == "True"}
            for i in range(4, len(fields), 2)]


class ShopContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.protocol = ROOT / "protocol"
        cls.scratch = (Path(tempfile.gettempdir()) / "nebula-preserved-tests") / "offline-shop-tests"
        cls.scratch.mkdir(parents=True, exist_ok=True)
        cls.catalog = Catalog(cls.protocol)
        cls.resource_catalog = ResourceCatalog(cls.protocol)

    def setUp(self):
        self.no_network = patch.object(socket, "socket", side_effect=AssertionError(
            "No network in static shop checks"))
        self.no_network.start()
        self.temp = tempfile.TemporaryDirectory(dir=self.scratch)
        self.state = Path(self.temp.name)
        self.store = Store(self.state / "state.sqlite3")
        self.store.account("shop-a", "Alice")
        self.store.account("shop-b", "Bob")
        self.store.bind_session("shop-a", "guid-a")
        self.store.bind_session("shop-b", "guid-b")
        self.resources = ResourceEntitlements(self.store, self.resource_catalog)
        self.housing = HousingStore(self.store, self.protocol)
        self.shop = Shop(self.store, self.catalog, self.resources, self.housing)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()
        self.no_network.stop()

    @staticmethod
    def request(*fields):
        return Request(tuple(str(value) for value in fields), "StandaloneWindows")

    def call(self, route, *fields):
        return self.shop.dispatch(route, self.request(*fields))

    def reopen(self):
        self.store.close()
        self.store = Store(self.state / "state.sqlite3")
        self.resources = ResourceEntitlements(self.store, self.resource_catalog)
        self.housing = HousingStore(self.store, self.protocol)
        self.shop = Shop(self.store, self.catalog, self.resources, self.housing)

    def wardrobe(self):
        return next(iter(self.catalog.items.values()))

    def configure_wardrobe(self, offer_id="wardrobe-offer", crystals=20, np=7,
                           featured=True):
        item = self.wardrobe()
        self.shop.configure_shop("avatar-shop", 0, "Local avatar shop",
                                 "Administrator-authored preservation offers")
        self.shop.configure_offer(offer_id, "wardrobe", item["item_id"],
                                  "avatar-shop", item["category"], 0, "Local wardrobe item",
                                  "", crystals, np, item["gender"],
                                  item["category"], featured)
        return item

    def test_exact_empty_catalog_forms_for_all_list_consumers(self):
        cases = [
            ("GetFeaturesServlet", ("guid-a", "shop-a"), ITEM_DATA),
            ("GetShopDataShopServlet", ("guid-a", "shop-a", "True", "False", 0), SHOP_DATA),
            ("GetGenderDataShopServlet", ("guid-a", "shop-a", "none"), GENDER_DATA),
            ("GetShopTypeDataShopServlet", ("guid-a", "shop-a", "none", 0), TYPE_DATA),
            ("GetItemAssetsDataServlet", ("guid-a", "shop-a", "none", 0, "none"), ITEM_DATA),
        ]
        for route, fields, schema in cases:
            response = self.call(route, *fields)
            self.assertEqual(response, "true#guid-a#shop-a#0")
            self.assertEqual(decode_list(response, schema), [])

    def test_catalog_dtos_only_expose_explicit_local_offers(self):
        item = self.configure_wardrobe(crystals=31, np=9)
        shops = decode_list(self.call("GetShopDataShopServlet", "guid-a", "shop-a",
                                      "True", "False", 0), SHOP_DATA)
        self.assertEqual(shops[0]["name"], "Local avatar shop")
        self.assertEqual(shops[0]["desciption"],
                         "Administrator-authored preservation offers")
        self.assertEqual(decode_gender_pairs(self.call("GetGenderDataShopServlet", "guid-a",
                                                       "shop-a", "avatar-shop")),
                         [{"genderID": 0, "show": True}])
        types = decode_list(self.call("GetShopTypeDataShopServlet", "guid-a", "shop-a",
                                      "avatar-shop", 0), TYPE_DATA)
        self.assertEqual(types, [{"shopID": "avatar-shop", "typeID": item["category"],
                                  "gender": "0"}])
        offers = decode_list(self.call("GetItemAssetsDataServlet", "guid-a", "shop-a",
                                       "avatar-shop", 0, item["category"]), ITEM_DATA)
        self.assertEqual(offers[0]["id"], "wardrobe-offer")
        self.assertEqual((offers[0]["crystals"], offers[0]["np"]), (31, 9))
        self.assertEqual(offers[0]["tablename"], item["category"])
        self.assertEqual(offers[0]["gender"], item["gender"])
        self.assertEqual(offers[0]["imagePath"],
                         f"{item['gender']}/{item['category']}/{item['item_id']}/"
                         f"{item['item_id']}Thumbnail.png")
        self.assertEqual(decode_list(self.call("GetFeaturesServlet", "guid-a", "shop-a"),
                                     ITEM_DATA)[0]["id"], "wardrobe-offer")

    def test_wallet_buy_is_server_priced_idempotent_and_persistent(self):
        item = self.configure_wardrobe(crystals=20, np=7)
        self.shop.set_wallet("shop-a", 50, 8, 3)
        self.assertEqual(self.call("GetShopInfoPlayerShop", "guid-a", "shop-a"),
                         "true#guid-a#shop-a#Alice#8#50")
        with self.assertRaisesRegex(ProtocolError, "Displayed price"):
            self.call("NPShopBuyItemServlet", "guid-a", "shop-a", "wardrobe-offer",
                      0, 0, 0)
        self.assertEqual(self.shop.wallet("shop-a")["crystals"], 50)
        self.assertEqual(self.call("NPShopBuyItemServlet", "guid-a", "shop-a",
                                   "wardrobe-offer", 20, 7, 0),
                         "true#guid-a#shop-a#OK")
        self.assertEqual(self.shop.wallet("shop-a")["crystals"], 30)
        self.assertTrue(any(row["item_id"] == item["item_id"]
                            for row in self.store.inventory("shop-a")))
        self.assertEqual(self.call("NPShopIsItemPurchasedServlet", "guid-a", "shop-a",
                                   "wardrobe-offer"), "true#guid-a#shop-a#True")
        self.assertEqual(self.call("NPShopBuyItemServlet", "guid-a", "shop-a",
                                   "wardrobe-offer", 20, 7, 0),
                         "true#guid-a#shop-a#ISPURCHASED")
        self.assertEqual(self.shop.wallet("shop-a")["crystals"], 30)
        reopened = Shop(self.store, self.catalog, self.resources, self.housing)
        self.assertEqual(reopened.wallet("shop-a")["crystals"], 30)

    def test_np_option_and_insufficient_statuses(self):
        self.configure_wardrobe(crystals=100, np=7)
        self.shop.set_wallet("shop-a", 3, 6)
        self.assertTrue(self.call("NPShopBuyItemServlet", "guid-a", "shop-a",
                                  "wardrobe-offer", 100, 7, 0).endswith("#NOCRYSTALS"))
        self.assertTrue(self.call("NPShopBuyItemServlet", "guid-a", "shop-a",
                                  "wardrobe-offer", 100, 7, 1).endswith("#NOXP"))
        self.shop.set_wallet("shop-a", 3, 7)
        self.assertTrue(self.call("NPShopBuyItemServlet", "guid-a", "shop-a",
                                  "wardrobe-offer", 100, 7, 1).endswith("#OK"))
        self.assertEqual(self.shop.wallet("shop-a")["np"], 0)

    def test_buy_failure_after_entitlement_insert_rolls_back_everything(self):
        self.configure_wardrobe(crystals=20, np=0)
        self.shop.set_wallet("shop-a", 20)
        original = self.shop._grant

        def fail_after_grant(ps4_id, offer):
            original(ps4_id, offer)
            raise RuntimeError("injected failure after entitlement insert")

        with patch.object(self.shop, "_grant", side_effect=fail_after_grant):
            with self.assertRaisesRegex(RuntimeError, "injected failure"):
                self.call("NPShopBuyItemServlet", "guid-a", "shop-a",
                          "wardrobe-offer", 20, 0, 0)
        self.assertEqual(self.shop.wallet("shop-a")["crystals"], 20)
        self.assertEqual(self.store.inventory("shop-a"), [])
        self.assertIsNone(self.store.db.execute(
            "SELECT 1 FROM shop_owned WHERE ps4_id='shop-a'").fetchone())
        self.reopen()
        self.assertEqual(self.shop.wallet("shop-a")["crystals"], 20)
        self.assertEqual(self.store.inventory("shop-a"), [])
        self.assertIsNone(self.store.db.execute(
            "SELECT 1 FROM shop_owned WHERE ps4_id='shop-a'").fetchone())
        self.assertTrue(self.call("NPShopBuyItemServlet", "guid-a", "shop-a",
                                  "wardrobe-offer", 20, 0, 0).endswith("#OK"))

    def test_gift_requires_friend_and_never_uses_client_price(self):
        self.configure_wardrobe(crystals=12)
        self.shop.set_wallet("shop-a", 40)
        with self.assertRaisesRegex(ProtocolError, "not a local friend"):
            self.call("NPShopGiftItemServlet", "guid-a", "shop-a", "wardrobe-offer",
                      "Bob", 12)
        self.store.accept_friendship("shop-a", "shop-b")
        with self.assertRaisesRegex(ProtocolError, "Displayed gift price"):
            self.call("NPShopGiftItemServlet", "guid-a", "shop-a", "wardrobe-offer",
                      "Bob", 0)
        self.assertEqual(self.shop.wallet("shop-a")["crystals"], 40)
        response = self.call("NPShopGiftItemServlet", "guid-a", "shop-a",
                             "wardrobe-offer", "Bob", 12)
        self.assertEqual(response, "true#guid-a#shop-a#OK#Bob#wardrobe-offer")
        self.assertEqual(self.shop.wallet("shop-a")["crystals"], 28)

    def test_gift_failure_after_entitlement_insert_rolls_back_everything(self):
        self.configure_wardrobe(crystals=12)
        self.shop.set_wallet("shop-a", 40)
        self.store.accept_friendship("shop-a", "shop-b")
        original = self.shop._grant

        def fail_after_grant(ps4_id, offer):
            original(ps4_id, offer)
            raise RuntimeError("injected gift failure after entitlement insert")

        with patch.object(self.shop, "_grant", side_effect=fail_after_grant):
            with self.assertRaisesRegex(RuntimeError, "injected gift failure"):
                self.call("NPShopGiftItemServlet", "guid-a", "shop-a",
                          "wardrobe-offer", "Bob", 12)
        self.assertEqual(self.shop.wallet("shop-a")["crystals"], 40)
        self.assertEqual(self.store.inventory("shop-b"), [])
        self.assertIsNone(self.store.db.execute(
            "SELECT 1 FROM shop_owned WHERE ps4_id='shop-b'").fetchone())
        self.reopen()
        self.assertEqual(self.shop.wallet("shop-a")["crystals"], 40)
        self.assertEqual(self.store.inventory("shop-b"), [])
        self.assertTrue(self.call("NPShopGiftItemServlet", "guid-a", "shop-a",
                                  "wardrobe-offer", "Bob", 12).endswith(
                                      "#OK#Bob#wardrobe-offer"))
        self.assertEqual(self.call("NPShopGiftItemServlet", "guid-a", "shop-a",
                                   "wardrobe-offer", "Bob", 12),
                         "true#guid-a#shop-a#ISPURCHASED#Bob#wardrobe-offer")
        self.assertEqual(self.shop.wallet("shop-a")["crystals"], 28)

    def test_bundle_grants_manifest_backed_resource_and_housing(self):
        companion = self.resource_catalog.list("companions")[0]["item_id"]
        housing = next(iter(self.housing.catalog))
        self.shop.configure_shop("mixed", 1, "Mixed local shop")
        self.shop.configure_offer("pet", "companions", companion, "mixed", "items", 0,
                                  "Local companion", crystals=1)
        self.shop.configure_offer("chair", "housing", housing, "mixed", "items", 0,
                                  "Local housing item", crystals=1)
        pet_offer = self.shop._offer("pet")
        self.shop.configure_offer("bundle", "bundle", None, "mixed", "bundles", 0,
                                  "Local bundle", pet_offer["image_path"], crystals=10)
        self.shop.add_bundle_item("bundle", "pet", 0)
        self.shop.add_bundle_item("bundle", "chair", 1)
        rows = decode_list(self.call("NPShopBundleItemsServlet", "guid-a", "shop-a",
                                     "bundle"), ITEM_DATA)
        self.assertEqual([row["id"] for row in rows], ["pet", "chair"])
        self.shop.set_wallet("shop-a", 10)
        with patch.object(self.housing, "grant_item",
                          side_effect=RuntimeError("injected later bundle child failure")):
            with self.assertRaisesRegex(RuntimeError, "later bundle child"):
                self.call("NPShopBuyItemServlet", "guid-a", "shop-a", "bundle",
                          10, 0, 0)
        self.assertEqual(self.shop.wallet("shop-a")["crystals"], 10)
        self.assertEqual(self.resources.list("shop-a", "companions"), [])
        self.assertEqual(self.housing.inventory("shop-a"), [])
        self.assertIsNone(self.store.db.execute(
            "SELECT 1 FROM shop_owned WHERE ps4_id='shop-a' AND offer_id='bundle'").fetchone())
        self.reopen()
        self.assertEqual(self.shop.wallet("shop-a")["crystals"], 10)
        self.assertEqual(self.resources.list("shop-a", "companions"), [])
        self.assertEqual(self.housing.inventory("shop-a"), [])
        self.assertTrue(self.call("NPShopBuyItemServlet", "guid-a", "shop-a", "bundle",
                                  10, 0, 0).endswith("#OK"))
        self.assertEqual(self.resources.list("shop-a", "companions")[0]["item_id"], companion)
        self.assertEqual(self.housing.inventory("shop-a")[0]["item_id"], housing)

    def test_sync_is_read_only_and_cannot_mint_or_spend(self):
        self.shop.set_wallet("shop-a", 17, 4, 2)
        before = dict(self.shop.wallet("shop-a"))
        self.assertEqual(self.call("NPShopSyncCrystalsServlet", "guid-a", "shop-a",
                                   "untrusted-receipt", "", 9_223_372_036_854_775_807),
                         "true#guid-a#shop-a#Alice#4#17")
        self.assertEqual(self.shop.wallet("shop-a"), before)

    def test_direct_item_gender_ids_use_itemdata_not_typedata(self):
        companion = self.resource_catalog.list("companions")[0]
        self.shop.configure_shop("companions", 1, "Local companions")
        self.shop.configure_offer("pet", "companions", companion["item_id"],
                                  "companions", "items", 2, "Local companion")
        response = self.call("GetShopTypeDataShopServlet", "guid-a", "shop-a",
                             "companions", 2)
        rows = decode_list(response, ITEM_DATA)
        self.assertEqual(rows[0]["id"], "pet")
        self.assertEqual(rows[0]["imagePath"],
                         f"COMPANIONS/{companion['item_id']}/"
                         f"{companion['item_id']}Thumbnail.png")

    def test_gift_name_resolves_unique_cross_platform_friend(self):
        self.configure_wardrobe(crystals=12)
        self.store.account("shop-c", "Carol", "PS4")
        self.store.accept_friendship("shop-a", "shop-c")
        self.shop.set_wallet("shop-a", 12)
        self.assertEqual(self.call("NPShopGiftItemServlet", "guid-a", "shop-a",
                                   "wardrobe-offer", "Carol", 12),
                         "true#guid-a#shop-a#OK#Carol#wardrobe-offer")
        self.assertEqual(len(self.store.inventory("shop-c")), 1)

    def test_invalid_catalog_ids_cannot_be_configured(self):
        self.shop.configure_shop("bad", 0, "Bad test shop")
        with self.assertRaises(ProtocolError):
            self.shop.configure_offer("bad", "companions", "fabricated", "bad", "t", 0,
                                      "Fabricated")
        self.assertEqual(self.shop.list_offers(), [])
        item = self.wardrobe()
        with self.assertRaisesRegex(ProtocolError, "gender ID"):
            self.shop.configure_offer("wrong-gender", "wardrobe", item["item_id"],
                                      "bad", item["category"],
                                      1 if item["gender"] == "MALE" else 0,
                                      "Wrong gender", "",
                                      gender=item["gender"], category=item["category"])
        with self.assertRaisesRegex(ProtocolError, "reuse a configured shipped"):
            self.shop.configure_offer("fake-bundle", "bundle", None, "bad", "bundles", 2,
                                      "Fake bundle", "COMPANIONS/fake/fakeThumbnail.png")


if __name__ == "__main__":
    unittest.main()

