"""ItemData.id carries the shipped asset ID; purchases still resolve to offers.

Client evidence: EntryItem.Set (0x4aa380) stores ItemData.id as
EntryItem.itemSelected. EntryItem.OnClick (0x4a9790) passes it to the 3D try-on
loader SetShopBase.Init(itemSelected, tablename), and WardrobeWindow.buyItem
(0x4b8500), OnClickBuyNP and OnClickGift send the same value back to
NPShopBuyItemServlet and NPShopGiftItemServlet. Offline only; sockets forbidden.
"""
from collections import defaultdict
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
from shop import ITEM_DATA, Shop
from state import Catalog, Store
from wire import ProtocolError, Request


def decode_list(response):
    fields = response.split("#")
    return [decode_entry_fields(value, ITEM_DATA) for value in fields[4:4 + int(fields[3])]]


class ShopItemIds(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.protocol = ROOT / "protocol"
        cls.scratch = Path(tempfile.gettempdir()) / "nebula-preserved-tests" / "shop-item-ids"
        cls.scratch.mkdir(parents=True, exist_ok=True)
        cls.catalog = Catalog(cls.protocol)
        cls.resource_catalog = ResourceCatalog(cls.protocol)

    def setUp(self):
        self.no_network = patch.object(socket, "socket", side_effect=AssertionError("no network"))
        self.no_network.start()
        self.temp = tempfile.TemporaryDirectory(dir=self.scratch)
        self.store = Store(Path(self.temp.name) / "state.sqlite3")
        self.store.account("shop-a", "Alice")
        self.store.account("shop-b", "Bob")
        self.store.bind_session("shop-a", "guid-a")
        self.store.bind_session("shop-b", "guid-b")
        self.store.accept_friendship("shop-a", "shop-b")
        self.resources = ResourceEntitlements(self.store, self.resource_catalog)
        self.housing = HousingStore(self.store, self.protocol)
        self.shop = Shop(self.store, self.catalog, self.resources, self.housing)
        self.shop.configure_shop("avatar-shop", 0, "Avatar shop")
        self.shop.configure_shop("second-shop", 0, "Second avatar shop")
        self.shop.configure_shop("mixed", 1, "Mixed shop")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()
        self.no_network.stop()

    def call(self, route, *fields):
        return self.shop.dispatch(route, Request(tuple(map(str, fields)), "StandaloneWindows"))

    def wardrobe_offer(self, offer_id, item, shop="avatar-shop", crystals=20, np=7):
        self.shop.configure_offer(offer_id, "wardrobe", item["item_id"], shop, item["category"],
                                  0 if item["gender"] == "MALE" else 1, "Local item", "",
                                  crystals, np, item["gender"], item["category"], True)

    def listed(self, shop, item):
        return decode_list(self.call("GetItemAssetsDataServlet", "guid-a", "shop-a", shop,
                                     0 if item["gender"] == "MALE" else 1, item["category"]))

    def unique_item(self):
        counts = defaultdict(set)
        for row in self.catalog.items.values():
            counts[row["item_id"]].add((row["gender"], row["category"]))
        return next(row for row in self.catalog.items.values() if len(counts[row["item_id"]]) == 1)

    def test_lists_expose_asset_id_for_preview_and_keep_bundle_offer_id(self):
        item = self.unique_item()
        self.wardrobe_offer("wardrobe-offer", item)
        companion = self.resource_catalog.list("companions")[0]["item_id"]
        housing = next(iter(self.housing.catalog))
        self.shop.configure_offer("pet", "companions", companion, "mixed", "items", 0, "Pet", crystals=1)
        self.shop.configure_offer("chair", "housing", housing, "mixed", "items", 0, "Chair", crystals=1)
        self.shop.configure_offer("bundle", "bundle", None, "mixed", "bundles", 0, "Bundle",
                                  self.shop._offer("pet")["image_path"], crystals=2, featured=True)
        self.shop.add_bundle_item("bundle", "pet", 0)
        self.shop.add_bundle_item("bundle", "chair", 1)
        rows = self.listed("avatar-shop", item)
        self.assertEqual([(r["id"], r["tablename"]) for r in rows], [(item["item_id"], item["category"])])
        features = {r["id"]: r for r in decode_list(self.call("GetFeaturesServlet", "guid-a", "shop-a"))}
        self.assertTrue(features["bundle"]["isBundle"])
        self.assertEqual([r["id"] for r in decode_list(self.call(
            "NPShopBundleItemsServlet", "guid-a", "shop-a", "bundle"))], [companion, housing])

    def test_asset_id_buy_and_check_resolve_to_offer_and_legacy_ids_still_work(self):
        item = self.unique_item()
        self.wardrobe_offer("wardrobe-offer", item)
        self.shop.set_wallet("shop-a", 50, 0)
        key = self.listed("avatar-shop", item)[0]["id"]
        self.assertEqual(self.call("NPShopIsItemPurchasedServlet", "guid-a", "shop-a", key),
                         "true#guid-a#shop-a#False")
        self.assertEqual(self.call("NPShopBuyItemServlet", "guid-a", "shop-a", key, 20, 7, 0),
                         "true#guid-a#shop-a#OK")
        self.assertEqual(self.shop.wallet("shop-a")["crystals"], 30)
        self.assertEqual([tuple(r)[:2] for r in self.store.db.execute("SELECT * FROM shop_owned")],
                         [("shop-a", "wardrobe-offer")])  # durable key unchanged
        for sent in (key, "wardrobe-offer"):
            self.assertEqual(self.call("NPShopIsItemPurchasedServlet", "guid-a", "shop-a", sent),
                             "true#guid-a#shop-a#True")
            self.assertEqual(self.call("NPShopBuyItemServlet", "guid-a", "shop-a", sent, 20, 7, 0),
                             "true#guid-a#shop-a#ISPURCHASED")
        self.assertEqual(self.shop.wallet("shop-a")["crystals"], 30)

    def test_existing_offer_keyed_ownership_is_honoured_for_asset_ids(self):
        item = self.unique_item()
        self.wardrobe_offer("wardrobe-offer", item)
        self.shop.set_wallet("shop-b", 50, 0)
        # A row written before this change, keyed by offer ID only.
        self.assertEqual(self.call("NPShopBuyItemServlet", "guid-b", "shop-b", "wardrobe-offer", 20, 7, 0),
                         "true#guid-b#shop-b#OK")
        self.assertEqual(self.call("NPShopIsItemPurchasedServlet", "guid-b", "shop-b", item["item_id"]),
                         "true#guid-b#shop-b#True")

    def test_same_item_in_two_stores_is_selected_by_displayed_price(self):
        item = self.unique_item()
        self.wardrobe_offer("cheap", item, "avatar-shop", crystals=5, np=0)
        self.wardrobe_offer("dear", item, "second-shop", crystals=40, np=0)
        self.assertEqual(self.listed("second-shop", item)[0]["id"], item["item_id"])
        self.shop.set_wallet("shop-a", 100, 0)
        self.assertTrue(self.call("NPShopBuyItemServlet", "guid-a", "shop-a",
                                  item["item_id"], 40, 0, 0).endswith("#OK"))
        self.assertEqual(self.shop.wallet("shop-a")["crystals"], 60)
        self.assertEqual(self.store.db.execute("SELECT offer_id FROM shop_owned").fetchone()[0], "dear")
        with self.assertRaises(ProtocolError) as stale:
            self.call("NPShopBuyItemServlet", "guid-a", "shop-a", item["item_id"], 41, 0, 0)
        self.assertEqual(stale.exception.status, 409)

    def test_gift_accepts_asset_id(self):
        item = self.unique_item()
        self.wardrobe_offer("wardrobe-offer", item, crystals=12)
        self.shop.set_wallet("shop-a", 12, 0)
        self.assertEqual(self.call("NPShopGiftItemServlet", "guid-a", "shop-a", item["item_id"], "Bob", 12),
                         "true#guid-a#shop-a#OK#Bob#wardrobe-offer")
        self.assertEqual(self.shop.wallet("shop-a")["crystals"], 0)
        self.assertEqual(self.call("NPShopIsItemPurchasedServlet", "guid-b", "shop-b", item["item_id"]),
                         "true#guid-b#shop-b#True")

    def test_ambiguous_asset_ids_keep_offer_ids_and_refuse_guessing(self):
        by_id = defaultdict(list)
        for row in self.catalog.items.values():
            if row["gender"] == "MALE":
                by_id[row["item_id"]].append(row)
        rows = next(rows for rows in by_id.values() if len({r["category"] for r in rows}) > 1)[:2]
        self.wardrobe_offer("first", rows[0])
        self.wardrobe_offer("second", rows[1])
        for row, offer in zip(rows, ("first", "second")):
            self.assertEqual([r["id"] for r in self.listed("avatar-shop", row)], [offer])
        self.shop.set_wallet("shop-a", 50, 0)
        with self.assertRaises(ProtocolError) as ambiguous:
            self.call("NPShopBuyItemServlet", "guid-a", "shop-a", rows[0]["item_id"], 20, 7, 0)
        self.assertEqual(ambiguous.exception.status, 409)
        self.assertEqual(self.shop.wallet("shop-a")["crystals"], 50)
        self.assertTrue(self.call("NPShopBuyItemServlet", "guid-a", "shop-a", "second", 20, 7, 0).endswith("#OK"))

    def test_asset_id_colliding_with_another_offer_id_is_not_exposed(self):
        item, other = self.unique_item(), None
        for row in self.catalog.items.values():
            if row["item_id"] != item["item_id"] and row["gender"] == item["gender"]:
                other = row
                break
        self.wardrobe_offer(item["item_id"], other)  # operator offer ID equals an asset ID
        self.wardrobe_offer("plain", item)
        listed = {r["tablename"]: r["id"] for r in self.listed("avatar-shop", item)}
        self.assertEqual(listed[item["category"]], "plain")
        # The exact offer-ID match keeps precedence on every return path.
        self.assertEqual(self.shop._client_offer(item["item_id"])["offer_id"], item["item_id"])


if __name__ == "__main__":
    unittest.main()
