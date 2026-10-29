"""Offline checks for native wardrobe category-removal control tiles."""
import copy
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

from avatar_entry_codec import encode_value_texts
from service import Service
from state import Catalog, Store
from wire import ProtocolError, session_guid


class WardrobeRemoval(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog(ROOT / "protocol")
        cls.document = json.loads((ROOT / "protocol/wardrobe-removal-sentinels.json").read_text(encoding="utf-8"))
        declarations = json.loads((ROOT / "protocol/bootstrap-response-contracts.json").read_text(encoding="utf-8"))["json_and_enum_declarations"]
        cls.fields = {
            gender: next(row for row in declarations if row["name"] == "JsonClasses.Preset" + gender.title() + "Json")["fields"]
            for gender in ("MALE", "FEMALE")
        }
        cls.scratch = (Path(tempfile.gettempdir()) / "nebula-preserved-tests") / "work/offline-tests"
        cls.scratch.mkdir(parents=True, exist_ok=True)

    def setUp(self):
        self.no_network = patch.object(socket, "socket", side_effect=AssertionError("No network in wardrobe removal tests"))
        self.no_network.start()
        self.temp = tempfile.TemporaryDirectory(dir=self.scratch)
        self.database = Path(self.temp.name) / "state.sqlite3"
        self.store = Store(self.database)
        self.service = Service(self.store, self.catalog)
        self.account = "offline-wardrobe-removal"
        self.guid = self.login("a")
        self.service.shop.set_wallet(self.account, 500, 200, 4)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()
        self.no_network.stop()

    def call(self, route, *fields):
        return self.service.dispatch(route, "#".join(fields) + "#StandaloneWindows")

    def login(self, nonce):
        self.call("N2UserExist", "Offline Removal", "v72", "false", self.account, "1.25")
        self.call("ChannelGUIDServlet", self.account, nonce * 64)
        return session_guid(self.account, nonce * 64)

    def serialize(self, preset, gender):
        values = []
        for field in self.fields[gender]:
            value = preset[field["name"]]
            if value is None:
                values.append(None)
            elif "float" in field["type_and_modifiers"]:
                values.append(format(value, ".9g"))
            else:
                values.append(value)
        return encode_value_texts(values)

    def inventory_snapshot(self):
        return [tuple(sorted(row.items())) for row in self.store.inventory(self.account)]

    def test_all_thirty_manifest_backed_controls_appear_only_in_ordinary_view(self):
        self.assertEqual(len(self.document["sentinels"]), 30)
        self.assertEqual(len({row["item_id"] for row in self.document["sentinels"]}), 30)
        self.assertEqual(sum(row.get("evidence_kind") == "thumbnail_control"
                             for row in self.document["sentinels"]), 10)
        before_inventory = self.inventory_snapshot()
        before_wallet = self.service.shop.wallet(self.account)
        for sentinel in self.document["sentinels"]:
            with self.subTest(item_id=sentinel["item_id"]):
                numeric_gender = "0" if sentinel["gender"] == "MALE" else "1"
                ordinary = self.call("GetInfoServlet", "0", self.guid, self.account, numeric_gender,
                                     sentinel["category"], "0").split("!")
                ids, statuses, names, item_types = [field.split("#") if field else [] for field in ordinary[2:6]]
                index = ids.index(sentinel["item_id"])
                self.assertEqual(ids.count(sentinel["item_id"]), 1)
                self.assertEqual((statuses[index], names[index], item_types[index]), ("1", "Remove", "1"))
                for view in ("1", "2"):
                    response = self.call("GetInfoServlet", "0", self.guid, self.account, numeric_gender,
                                         sentinel["category"], view).split("!")
                    self.assertNotIn(sentinel["item_id"], response[2].split("#"))
        self.assertEqual(self.inventory_snapshot(), before_inventory)
        self.assertEqual(self.service.shop.wallet(self.account), before_wallet)
        unknown = self.call("GetInfoServlet", "0", self.guid, self.account, "0", "not-a-category", "0")
        self.assertEqual(unknown, "true!" + self.guid + "!!!!!MALE")

    def test_every_control_is_bound_to_exact_shipped_manifest_evidence(self):
        manifests = ((Path(tempfile.gettempdir()) / "nebula-preserved-tests") /
                     "work/evidence/assets/bundle-manifests.json")
        if not manifests.is_file():
            self.skipTest("Private extracted bundle manifests are not redistributed; native provenance test")
        by_asset = {}
        for manifest in json.loads(manifests.read_text(encoding="utf-8")):
            for asset_path in manifest["assets"]:
                by_asset[asset_path] = manifest
        wearable_count = 0
        thumbnail_count = 0
        for sentinel in self.document["sentinels"]:
            with self.subTest(item_id=sentinel["item_id"]):
                if sentinel.get("evidence_kind", "wearable_manifest") == "thumbnail_control":
                    thumbnail_count += 1
                    evidence = by_asset[sentinel["thumbnail_asset_path"]]
                    self.assertEqual(evidence["bundle"], sentinel["bundle"])
                    self.assertEqual(evidence["manifest_sha256"], sentinel["manifest_sha256"])
                    self.assertEqual(evidence["assets"], [sentinel["thumbnail_asset_path"]])
                else:
                    wearable_count += 1
                    asset = self.catalog.resolve(sentinel["item_id"], sentinel["gender"], sentinel["category"])
                    self.assertEqual(asset["bundle"], sentinel["bundle"])
                    self.assertEqual(asset["manifest_sha256"], sentinel["manifest_sha256"])
        self.assertEqual((wearable_count, thumbnail_count), (20, 10))

    def test_all_menu_triggered_sentinel_mutations_are_rejected(self):
        before_inventory = self.inventory_snapshot()
        before_wallet = self.service.shop.wallet(self.account)
        for sentinel in self.document["sentinels"]:
            for status in ("0", "1", "2", "3"):
                with self.subTest(item_id=sentinel["item_id"], status=status):
                    with self.assertRaises(ProtocolError) as error:
                        self.call("WardrobeOptionItemServlet", self.guid, self.account,
                                  sentinel["item_id"], status)
                    self.assertEqual(error.exception.status, 403)
        self.assertEqual(self.inventory_snapshot(), before_inventory)
        self.assertEqual(self.service.shop.wallet(self.account), before_wallet)

    def test_preexisting_sentinel_entitlement_cannot_leak_or_be_mutated(self):
        sentinel = self.document["sentinels"][0]
        asset = self.catalog.resolve(sentinel["item_id"], sentinel["gender"], sentinel["category"])
        self.store.grant(self.account, asset, "Invalid historical sentinel row")
        with self.store.db:
            self.store.db.execute("UPDATE entitlements SET asset_status=2 WHERE ps4_id=? AND item_id=?",
                                  (self.account, sentinel["item_id"]))
        numeric_gender = "0" if sentinel["gender"] == "MALE" else "1"
        for view in ("1", "2"):
            response = self.call("GetInfoServlet", "0", self.guid, self.account, numeric_gender,
                                 sentinel["category"], view).split("!")
            self.assertNotIn(sentinel["item_id"], response[2].split("#"))
        ordinary = self.call("GetInfoServlet", "0", self.guid, self.account, numeric_gender,
                             sentinel["category"], "0").split("!")
        self.assertEqual(ordinary[2].split("#").count(sentinel["item_id"]), 1)
        with self.assertRaises(ProtocolError):
            self.call("WardrobeOptionItemServlet", self.guid, self.account, sentinel["item_id"], "1")

    def test_remove_equipped_hat_save_reload_preserves_entitlement_and_wallet(self):
        sentinel_id = "G4q7p8V2H2W23CPU285X2d6r05vU0aCY"
        hat = next(item for (_, gender, category), item in self.catalog.items.items()
                   if gender == "MALE" and category == "CLOTH_HEAD_HAT"
                   and item["kind"] == "FBX" and item["item_id"] != sentinel_id)
        self.store.grant(self.account, hat, "Owned test hat")
        preset = copy.deepcopy(self.store.preset(self.account, "MALE")["preset"])
        slot = next(index for index in range(1, 41) if preset["item" + str(index)] == "null")
        preset["item" + str(slot)] = hat["item_id"]
        self.assertEqual(self.call("N2SavePreset", self.guid, self.account, "Hat Equipped", "0",
                                   self.serialize(preset, "MALE")), "true#true")
        equipped = self.store.preset(self.account, "MALE", "Hat Equipped")["preset"]
        active = [equipped["item" + str(index)] for index in range(1, 41)
                  if equipped["item" + str(index)] not in ("null", hat["item_id"])]
        removed = copy.deepcopy(equipped)
        for index in range(1, 41):
            removed["item" + str(index)] = active[index - 1] if index <= len(active) else "null"
        before_inventory = self.inventory_snapshot()
        before_wallet = self.service.shop.wallet(self.account)
        self.assertEqual(self.call("N2SavePreset", self.guid, self.account, "Hat Removed", "0",
                                   self.serialize(removed, "MALE")), "true#true")

        self.store.close()
        self.store = Store(self.database)
        self.service = Service(self.store, self.catalog)
        self.guid = self.login("b")
        saved = self.store.preset(self.account, "MALE", "Hat Removed")
        self.assertNotIn(hat["item_id"], [saved["preset"]["item" + str(index)] for index in range(1, 41)])
        self.assertNotIn(hat["item_id"], saved["assets"]["data"].split("!"))
        self.assertEqual(self.inventory_snapshot(), before_inventory)
        self.assertEqual(self.service.shop.wallet(self.account), before_wallet)
        normal_ids = self.call("GetInfoServlet", "0", self.guid, self.account, "0", "CLOTH_HEAD_HAT", "0").split("!")[2].split("#")
        self.assertIn(hat["item_id"], normal_ids)
        self.assertIn(sentinel_id, normal_ids)

    def test_sentinel_is_not_an_owned_item_and_cannot_be_saved_as_equipment(self):
        sentinel_id = "G4q7p8V2H2W23CPU285X2d6r05vU0aCY"
        self.assertNotIn(sentinel_id, {row["item_id"] for row in self.store.inventory(self.account)})
        preset = copy.deepcopy(self.store.preset(self.account, "MALE")["preset"])
        slot = next(index for index in range(1, 41) if preset["item" + str(index)] == "null")
        preset["item" + str(slot)] = sentinel_id
        with self.assertRaises(ProtocolError):
            self.call("N2SavePreset", self.guid, self.account, "Invalid sentinel equipment", "0",
                      self.serialize(preset, "MALE"))


if __name__ == "__main__":
    unittest.main()

