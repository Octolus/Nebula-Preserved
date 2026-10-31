"""Apartments are sold in the native Spaces shop tab and grant real bindings."""
import json
import os
from pathlib import Path
import socket
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(BACKEND), str(BACKEND.parent / "tools")]
from avatar_entry_codec import decode_entry_fields
from catalog_inventory import POLICY, STORE_SPECS, CatalogInventory, seed_full_catalog
from housing import PERSONAL_SPACE_SCENES
from management import Management
from service import Service
from shop import ITEM_DATA, Shop
from space_shop import SHOP_FILE, SHOP_ID_BY_SPACE, SHOP_SPACES
from state import Catalog, Store
from wire import Request, session_guid

TOKEN = b"synthetic-apartment-shop-token-000000001"
OPERATORS = [{"id": role, "role": role, "enabled": True} for role in ("owner", "admin", "moderator")]
STORE_ID = POLICY + "-personal_spaces"


class ApartmentShopTests(unittest.TestCase):
    def setUp(self):
        guard = patch.object(socket, "socket", side_effect=AssertionError("sockets forbidden"))
        guard.start()
        self.addCleanup(guard.stop)
        env = patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("NEBULA_STARTER_APARTMENTS", None)  # default: Home, CliffApartment, LakeApartment
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.store = Store(self.root / "preservation.sqlite3")
        self.addCleanup(self.store.close)
        self.service = Service(self.store, Catalog(BACKEND.parent / "protocol"),
                               core_test_profile="nonmini-semantic-v1", managed_instances=True)
        self.manager = Management(self.store, self.service, TOKEN, OPERATORS)
        self.counter = 0
        # Only the apartment store, exactly as the catalog policy seeds it.
        spec = STORE_SPECS["personal_spaces"]
        self.service.shop.configure_shop(STORE_ID, spec[0], "Preservation Apartments")
        for row in CatalogInventory(self.service).items:
            if row["kind"] == "personal_spaces":
                self.service.shop.configure_offer(POLICY + "-" + row["item_id"], "personal_spaces", row["item_id"],
                                                  STORE_ID, row["store_category"], spec[5], row["name"],
                                                  crystals=spec[3], np=spec[4])

    def login(self, account_id, username=None):
        self.service.dispatch("N2UserExist", "#".join(
            (username or account_id, "v72", "false", account_id, "nonce", "StandaloneWindows")))
        request_hash = (account_id.encode().hex() + "0" * 64)[:64]
        self.service.dispatch("ChannelGUIDServlet", "#".join((account_id, request_hash, "StandaloneWindows")))
        return session_guid(account_id, request_hash)

    def shop(self, route, *values):
        return self.service.shop.dispatch(route, Request(tuple(map(str, values)), "StandaloneWindows"))

    def items(self, guid, account):
        response = self.shop("GetItemAssetsDataServlet", guid, account, STORE_ID, 4, "PERSON").split("#")
        self.assertEqual(len(response), int(response[3]) + 4)
        return [decode_entry_fields(value, ITEM_DATA) for value in response[4:]]

    def purchases(self, guid, account):
        data = json.loads(self.service.dispatch("GetPurchases", guid + "#StandaloneWindows").split("#", 2)[2])
        return list(zip(data["personalspaces"], data["personalspacesName"]))

    def owned(self, account):
        return set(self.service.housing.personal_spaces(account))

    def command(self, tail, body, role="admin"):
        self.counter += 1
        return self.manager.command(tail, body, {"Authorization": "Bearer " + TOKEN.decode(),
                                                 "X-Management-Actor": role,
                                                 "Idempotency-Key": f"apartment-shop-{self.counter:08}"})

    # ---- recovered mapping and catalog policy --------------------------------
    def test_mapping_covers_every_loadable_apartment_except_home(self):
        self.assertEqual(set(SHOP_ID_BY_SPACE), set(PERSONAL_SPACE_SCENES) - {"Home"})
        document = json.loads(SHOP_FILE.read_text(encoding="utf-8"))
        self.assertEqual([r.get("logical_space_key") for r in document["not_offered"]][0], "Home")
        for item_id, row in SHOP_SPACES.items():
            self.assertEqual(row["thumbnail_path"], "PersonalSpaces/" + item_id + "/" + item_id + "Thumbnail.png")
            self.assertEqual(row["thumbnail_resource_key"], row["thumbnail_path"][:-4].lower())
            self.assertGreaterEqual(row["screenshot_count"], 1)

    def test_catalog_seed_adds_one_active_offer_per_apartment(self):
        store = Store(self.root / "seeded.sqlite3")
        self.addCleanup(store.close)
        service = Service(store, Catalog(BACKEND.parent / "protocol"))
        seed_full_catalog(service)
        shop = dict(store.db.execute("SELECT * FROM shop_catalogs WHERE shop_id=?", (STORE_ID,)).fetchone())
        self.assertEqual((shop["type_shop"], shop["name"], shop["active"]), (2, "Preservation Apartments", 1))
        self.assertTrue(shop["url"].endswith("/bluewavehideout.png"))
        offers = [dict(r) for r in store.db.execute("SELECT * FROM shop_offers WHERE kind='personal_spaces'")]
        self.assertEqual({o["item_id"] for o in offers}, set(SHOP_SPACES))
        self.assertTrue(all((o["shop_id"], o["gender_id"], o["type_id"], o["crystals"], o["np"], o["active"])
                            == (STORE_ID, 4, "PERSON", 150, 75, 1) for o in offers))
        names = {o["item_id"]: o["name"] for o in offers}
        self.assertEqual(names[SHOP_ID_BY_SPACE["CliffApartment"]], "Cliff Apartment")
        manager = Management(store, service, TOKEN, OPERATORS)
        rows = manager.catalog({"kind": "personal_spaces", "limit": "100"})
        self.assertEqual(rows["total"], 30)
        self.assertTrue(all(r["shop_reachable"] and r["shop_path_correct"] for r in rows["items"]))
        self.assertEqual(manager.store_management.read("stores/" + STORE_ID, {})["kind"], "personal_spaces") \
            if hasattr(manager, "store_management") else None

    # ---- native list contract -------------------------------------------------
    def test_spaces_tab_lists_shop_ids_thumbnails_and_owned_state(self):
        guid = self.login("buyer")
        genders = self.shop("GetGenderDataShopServlet", guid, "buyer", STORE_ID).split("#")
        self.assertEqual(genders[3:], ["2", "4", "True"])
        items = {row["id"]: row for row in self.items(guid, "buyer")}
        self.assertEqual(set(items), set(SHOP_SPACES))
        cliff = items[SHOP_ID_BY_SPACE["CliffApartment"]]
        self.assertEqual((cliff["imagePath"], cliff["tablename"], cliff["gender"], cliff["isBundle"]),
                         (SHOP_SPACES[cliff["id"]]["thumbnail_path"], "PERSON", "PersonalSpace", False))
        self.assertEqual((cliff["crystals"], cliff["np"]), (150, 75))
        # Starter apartments are already owned and cannot be bought again.
        self.assertTrue(self.shop("NPShopIsItemPurchasedServlet", guid, "buyer", cliff["id"]).endswith("#True"))
        greenhouse = SHOP_ID_BY_SPACE["Greenhouse"]
        self.assertTrue(self.shop("NPShopIsItemPurchasedServlet", guid, "buyer", greenhouse).endswith("#False"))
        self.service.shop.set_wallet("buyer", 1000, 0)
        self.assertTrue(self.shop("NPShopBuyItemServlet", guid, "buyer", cliff["id"], 150, 75, 0).endswith("#ISPURCHASED"))
        self.assertEqual(self.service.shop.wallet("buyer")["crystals"], 1000)

    # ---- purchase, gift and staff paths --------------------------------------------
    def test_purchase_creates_binding_managed_instance_and_navigator_entry(self):
        guid = self.login("buyer")
        greenhouse = SHOP_ID_BY_SPACE["Greenhouse"]
        self.assertTrue(self.shop("NPShopBuyItemServlet", guid, "buyer", greenhouse, 150, 75, 0).endswith("#NOCRYSTALS"))
        self.assertNotIn("Greenhouse", self.owned("buyer"))
        self.service.shop.set_wallet("buyer", 200, 80)
        self.assertEqual(self.shop("NPShopBuyItemServlet", guid, "buyer", greenhouse, 150, 75, 1),
                         "true#" + guid + "#buyer#OK")
        self.assertEqual((self.service.shop.wallet("buyer")["crystals"], self.service.shop.wallet("buyer")["np"]), (200, 5))
        self.assertIn("Greenhouse", self.owned("buyer"))
        binding = self.service.apartments.owned("buyer", "Greenhouse")
        managed = self.store.db.execute("SELECT kind,psidglobal FROM managed_instances WHERE instance_id=?",
                                        (binding["instance_id"],)).fetchone()
        self.assertEqual(tuple(managed), ("personal", "Greenhouse"))
        self.assertIn((greenhouse, "Greenhouse"), self.purchases(guid, "buyer"))
        self.assertIn(("Home", "Home"), self.purchases(guid, "buyer"))
        navigator = self.service.dispatch("GetPersonalSpacesServlet", guid + "#buyer#StandaloneWindows")
        self.assertIn("Greenhouse", navigator.split("#")[3].split("!"))
        # Idempotent: a retry is ISPURCHASED without another debit.
        self.assertTrue(self.shop("NPShopBuyItemServlet", guid, "buyer", greenhouse, 150, 75, 0).endswith("#ISPURCHASED"))
        self.assertEqual(self.service.shop.wallet("buyer")["crystals"], 200)
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM housing_spaces WHERE owner_ps4_id='buyer' "
                                               "AND logical_space_key='Greenhouse'").fetchone()[0], 1)
        # After a staff removal the apartment can be bought again, on the same instance.
        self.command("users/buyer/character/housing/remove", {"space_key": "Greenhouse"})
        self.assertTrue(self.shop("NPShopIsItemPurchasedServlet", guid, "buyer", greenhouse).endswith("#False"))
        self.assertTrue(self.shop("NPShopBuyItemServlet", guid, "buyer", greenhouse, 150, 75, 0).endswith("#OK"))
        self.assertEqual(self.service.apartments.owned("buyer", "Greenhouse")["instance_id"], binding["instance_id"])

    def test_gift_and_staff_offer_grant_create_bindings(self):
        sender = self.login("sender", "Sender")
        self.login("friend", "Friend")
        self.store.accept_friendship("sender", "friend")
        self.service.shop.set_wallet("sender", 500)
        crypt = SHOP_ID_BY_SPACE["TheCrypt"]
        response = self.shop("NPShopGiftItemServlet", sender, "sender", crypt, "Friend", 150)
        self.assertEqual(response.split("#")[3:5], ["OK", "Friend"])
        self.assertIn("TheCrypt", self.owned("friend"))
        self.assertNotIn("TheCrypt", self.owned("sender"))
        self.assertEqual(self.shop("NPShopGiftItemServlet", sender, "sender", crypt, "Friend", 150).split("#")[3],
                         "ISPURCHASED")
        self.assertEqual(self.service.shop.wallet("sender")["crystals"], 350)
        result = self.command("users/sender/items", {"kind": "offer", "offer_id": POLICY + "-" + SHOP_ID_BY_SPACE["Waterfall"]})
        self.assertTrue(result["changed"])
        self.assertIn("Waterfall", self.owned("sender"))
        grant = {"kind": "personal_spaces", "item_id": SHOP_ID_BY_SPACE["LeChalet"]}
        self.assertTrue(self.command("users/sender/items", grant)["changed"])
        self.assertFalse(self.command("users/sender/items", grant)["changed"])
        self.assertIn("LeChalet", self.owned("sender"))

    def test_staff_can_reprice_and_hide_an_apartment_offer(self):
        guid = self.login("buyer")
        offer = POLICY + "-" + SHOP_ID_BY_SPACE["Greenhouse"]
        self.command("store-offers/" + offer, {"crystals": 500, "np": 0})
        row = next(r for r in self.items(guid, "buyer") if r["id"] == SHOP_ID_BY_SPACE["Greenhouse"])
        self.assertEqual((row["crystals"], row["np"]), (500, 0))
        self.command("store-offers/" + offer, {"active": False})
        self.assertNotIn(SHOP_ID_BY_SPACE["Greenhouse"], {r["id"] for r in self.items(guid, "buyer")})

    def test_offers_reject_wrong_tab_and_unknown_ids(self):
        with self.assertRaisesRegex(Exception, "Spaces tab"):
            self.service.shop.configure_offer("bad-tab", "personal_spaces", SHOP_ID_BY_SPACE["Greenhouse"],
                                              STORE_ID, "items", 5, "Greenhouse")
        with self.assertRaisesRegex(Exception, "Unknown shipped apartment"):
            self.service.shop.configure_offer("bad-id", "personal_spaces", "Greenhouse", STORE_ID, "PERSON", 4, "Greenhouse")

    # ---- schema migration -------------------------------------------------------
    def test_older_offer_table_is_rebuilt_without_losing_rows(self):
        path = self.root / "older.sqlite3"
        db = sqlite3.connect(path)
        db.executescript("""
            CREATE TABLE profiles (ps4_id TEXT PRIMARY KEY, username TEXT NOT NULL, platform TEXT NOT NULL,
                gender TEXT NOT NULL DEFAULT 'MALE', created_at REAL NOT NULL);
            INSERT INTO profiles VALUES('old','Old','StandaloneWindows','MALE',0);
            CREATE TABLE shop_catalogs (shop_id TEXT PRIMARY KEY, type_shop INTEGER NOT NULL
                CHECK(type_shop BETWEEN 0 AND 3), name TEXT NOT NULL, description TEXT NOT NULL,
                url TEXT NOT NULL, active INTEGER NOT NULL CHECK(active IN (0,1)));
            INSERT INTO shop_catalogs VALUES('s',2,'Old','','',1);
            CREATE TABLE shop_offers (offer_id TEXT PRIMARY KEY, kind TEXT NOT NULL
                CHECK(kind IN ('wardrobe','companions','locomotions','housing','bundle')),
                item_id TEXT, gender TEXT, category TEXT,
                shop_id TEXT NOT NULL REFERENCES shop_catalogs(shop_id),
                type_id TEXT NOT NULL, gender_id INTEGER NOT NULL, name TEXT NOT NULL, image_path TEXT NOT NULL,
                crystals INTEGER NOT NULL CHECK(crystals>=0), np INTEGER NOT NULL CHECK(np>=0),
                featured INTEGER NOT NULL CHECK(featured IN (0,1)), active INTEGER NOT NULL CHECK(active IN (0,1)),
                created_at REAL NOT NULL);
            INSERT INTO shop_offers VALUES('o','housing','x',NULL,NULL,'s','items',5,'Old','Housing/T/x/xThumbnail.png',1,2,0,1,0);
            CREATE TABLE shop_owned (ps4_id TEXT NOT NULL REFERENCES profiles(ps4_id),
                offer_id TEXT NOT NULL REFERENCES shop_offers(offer_id), source TEXT NOT NULL
                CHECK(source IN ('buy','gift','admin')), granted_by TEXT, created_at REAL NOT NULL,
                PRIMARY KEY(ps4_id,offer_id));
            INSERT INTO shop_owned VALUES('old','o','buy',NULL,0);
        """)
        db.commit()
        db.close()
        store = Store(path)
        self.addCleanup(store.close)
        shop = Shop(store, None, None, None)
        sql = store.db.execute("SELECT sql FROM sqlite_schema WHERE name='shop_offers'").fetchone()[0]
        self.assertIn("'personal_spaces'", sql)
        self.assertEqual(tuple(store.db.execute("SELECT offer_id,kind,crystals,np FROM shop_offers").fetchone()),
                         ("o", "housing", 1, 2))
        self.assertEqual(store.db.execute("SELECT COUNT(*) FROM shop_owned").fetchone()[0], 1)
        self.assertEqual(store.db.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        self.assertIsNone(store.db.execute("PRAGMA foreign_key_check").fetchone())
        Shop(store, None, None, None)  # second open is a no-op
        self.assertIsNotNone(shop)


if __name__ == "__main__":
    unittest.main()
