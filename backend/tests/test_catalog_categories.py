"""Client category tree, identity resolution and recovered catalog metadata.

Fixtures and committed protocol data only: no game installation, private scan,
network or game process is required.
"""
import json
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "tools")]
from avatar_entry_codec import decode_entry_fields
import build_item_catalog_metadata as builder
import catalog_inventory
from catalog_inventory import (CLIENT_TYPE_MERGES, CLIENT_TYPE_SPRITES, CLOTH_CONTENT, HOUSING_MENU, POLICY,
                               STORE_TYPE_ALIASES, CatalogInventory, client_item_order, client_type_id,
                               client_type_ids, client_type_rank, identity, offer_id, seed_full_catalog)
from service import Service
from shop import ITEM_DATA, TYPE_DATA
from state import Catalog, Store
from wire import Request

WINGS_FEMALE = "C6q3hB7YjQesf1WMHd21aFrSc8t7M1wp"
WINGS_MALE = "DveUuvrYbcy1Rq5Pk46ql7jDs4p8FUfU"


def decode(response, schema):
    fields = response.split("#")
    assert len(fields) == int(fields[3]) + 4, "native list framing"
    return [decode_entry_fields(value, schema) for value in fields[4:]]


class Seeded(unittest.TestCase):
    """One seeded disposable database shared by read-only checks."""

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.store = Store(Path(cls.temp.name) / "preservation.sqlite3")
        cls.service = Service(cls.store, Catalog(ROOT / "protocol"))
        cls.result = seed_full_catalog(cls.service)
        cls.rows, cls.offers, cls.stores, cls.counts, cls.summary = CatalogInventory(cls.service).snapshot()
        cls.store.account("category-client", "Category Client")
        cls.store.bind_session("category-client", "category-guid")

    @classmethod
    def tearDownClass(cls):
        cls.store.close()
        cls.temp.cleanup()

    def call(self, route, *values):
        return self.service.shop.dispatch(route, Request(tuple(map(str, values)), "StandaloneWindows"))


class ClientTypeTree(Seeded):
    def test_type_constants_match_the_recovered_native_sprite_list(self):
        evidence = json.loads((ROOT / "protocol/catalog-recovery-provenance.json").read_text(encoding="utf-8"))
        rows = evidence["native_item_type_sprites"]["rows"]
        self.assertEqual(tuple(r["sprite_name"] for r in sorted(rows, key=lambda r: r["index"])), CLIENT_TYPE_SPRITES)
        self.assertEqual(len(CLOTH_CONTENT), 31)
        self.assertEqual(client_type_id("CLOTH_BODY_WRISTBANDL"), "CLOTH_BODY_WRISTBAND")
        self.assertEqual(client_type_id("CLOTH_HEAD_EARRINGR"), "CLOTH_HEAD_EARRING")
        self.assertEqual(client_type_id("CLOTH_BODY_RINGSL"), "CLOTH_BODY_RINGS")
        self.assertEqual(client_type_id("CLOTH_BODY_HAND"), "CLOTH_BODY_HANDS")
        for unknown in ("CLOTH_HEAD_PIERCINGS", "items", "", None, "CLOTH_BODY_WRISTBANDX"):
            self.assertIsNone(client_type_id(unknown))
        self.assertEqual(client_type_ids(["CLOTH_HEAD_HAT", "items", "CLOTH_BODY_WRISTBANDR",
                                          "CLOTH_BODY_WRISTBANDL", "CLOTH_BODY_TORSO"]),
                         ["CLOTH_BODY_TORSO", "CLOTH_HEAD_HAT", "CLOTH_BODY_WRISTBAND"])
        self.assertLess(client_type_rank("FCLOTH_BODY_FEET"), client_type_rank("CLOTH_BODY_HANDS"))

    def test_every_wardrobe_row_has_a_client_icon_type_and_exact_slot(self):
        wardrobe = [r for r in self.rows if r["kind"] == "wardrobe"]
        self.assertEqual(len(wardrobe), 6234)
        for row in wardrobe:
            self.assertIn(row["store_category"], CLIENT_TYPE_SPRITES)
            if row["category"] in CLIENT_TYPE_MERGES:
                self.assertEqual(row["store_category_source"], "client_type_icon_merge")
                self.assertEqual(row["subcategory"], row["category"])
                self.assertIn(row["slot_side"], ("left", "right"))
            elif row["category"] in STORE_TYPE_ALIASES:
                self.assertEqual(row["store_category_source"], "preservation_compatibility_alias")
            else:
                self.assertEqual(row["store_category"], row["category"])
            self.assertEqual(row["gender_variant"], row["gender"])
            self.assertEqual(row["shop_path"]["gender_id"], {"MALE": 0, "FEMALE": 1}[row["gender"]])
            self.assertEqual(row["shop_path"]["type_id"], row["store_category"])
        self.assertEqual(sum(r["category"] in CLIENT_TYPE_MERGES for r in wardrobe), 489)

    def test_native_navigation_lists_only_client_types_in_enum_order_and_reaches_everything(self):
        self.assertEqual(self.result["retyped_offers"], 0)
        reached = {}
        clothing = POLICY + "-wardrobe"
        for gender in (0, 1):
            types = [row["typeID"] for row in decode(self.call("GetShopTypeDataShopServlet", "category-guid",
                                                               "category-client", clothing, gender), TYPE_DATA)]
            self.assertTrue(set(types) <= set(CLIENT_TYPE_SPRITES))
            self.assertEqual(len(types), len(set(types)))
            self.assertEqual(types, sorted(types, key=client_type_rank))
            self.assertIn("CLOTH_BODY_WRISTBAND", types)
            self.assertIn("CLOTH_HEAD_EARRING", types)
            for type_id in types:
                items = decode(self.call("GetItemAssetsDataServlet", "category-guid", "category-client",
                                         clothing, gender, type_id), ITEM_DATA)
                self.assertTrue(items)
                self.assertEqual(items, client_item_order(items))
                for item in items:
                    self.assertEqual(client_type_id(item["tablename"]), type_id)
                    self.assertNotIn(item["id"], reached)
                    reached[item["id"]] = (gender, type_id, item["tablename"])
        for kind in ("companions", "housing", "locomotions"):
            sid, tab = POLICY + "-" + kind, catalog_inventory.STORE_SPECS[kind][5]
            items = decode(self.call("GetShopTypeDataShopServlet", "category-guid", "category-client", sid, tab), ITEM_DATA)
            self.assertEqual(items, client_item_order(items))
            for item in items:
                reached[item["id"]] = (tab, None, item["tablename"])
        # Spaces tab: EntryGender.OnClick case 4 requests type PERSON directly.
        for item in decode(self.call("GetItemAssetsDataServlet", "category-guid", "category-client",
                                     POLICY + "-personal_spaces", 4, "PERSON"), ITEM_DATA):
            self.assertEqual(item["tablename"], "PERSON")
            reached[item["id"]] = (4, "PERSON", item["tablename"])
        housing = [v[2] for v in reached.values() if v[0] == 5]
        self.assertEqual(housing, sorted(housing, key=HOUSING_MENU.index))
        self.assertEqual(len(reached), 7742)
        self.assertEqual(self.summary["reachable_expected_path"], 7742)
        ambiguous = self.service.shop._ambiguous_item_ids()
        self.assertEqual(len(ambiguous), 8)  # MALE IDs shipped under two categories
        for row in self.rows:
            self.assertTrue(row["shop_path_correct"], identity(row))
            # ItemData.id is the asset ID unless that ID names several local items.
            key = offer_id(row) if row["item_id"] in ambiguous else row["item_id"]
            self.assertEqual(reached[key][2], row["category"])

    def test_sort_order_is_a_dense_client_tree_position(self):
        orders = sorted(r["sort_order"] for r in self.rows)
        self.assertEqual(orders, list(range(len(self.rows))))
        ranked = sorted(self.rows, key=lambda r: r["sort_order"])
        keys = [(r["shop_path"]["type_shop"], r["shop_path"]["gender_id"], r["shop_path"]["type_rank"]) for r in ranked]
        self.assertEqual(keys, sorted(keys))


class IdentityResolution(Seeded):
    def test_manifest_decided_conflicts_are_valid_and_undecided_rows_stay_out(self):
        by_id = {}
        for row in self.rows:
            if row["kind"] == "wardrobe":
                by_id.setdefault(row["item_id"], []).append(row)
        female = by_id[WINGS_FEMALE]
        self.assertEqual([(r["gender"], r["category"]) for r in female], [("FEMALE", "CLOTH_BODY_TORSO_APPAREL")])
        self.assertEqual(female[0]["identity_resolution"]["resolution"], "single_loadable_category")
        self.assertEqual(female[0]["identity_resolution"]["thumbnail_only_categories"], ["CLOTH_HEAD_FACEITEM"])
        self.assertIn("/CLOTH_BODY_TORSO_APPAREL/", female[0]["thumbnail_path"])
        male = sorted(by_id[WINGS_MALE], key=lambda r: r["category"])
        self.assertEqual([r["category"] for r in male], ["CLOTH_BODY_TORSO_APPAREL", "CLOTH_HEAD_FACEITEM"])
        for row in male:
            self.assertEqual(row["identity_resolution"]["resolution"], "multiple_loadable_categories")
            self.assertIn("/" + row["category"] + "/", row["thumbnail_path"])
            self.assertEqual(len(row["also_in_categories"]), 1)
        self.assertEqual(sum(bool(r.get("identity_resolution")) for r in self.rows), 24)
        self.assertEqual(sum(len(r["also_in_categories"]) == 1 for r in self.rows if r["kind"] == "wardrobe"), 16)
        metadata = json.loads((ROOT / "protocol/item-catalog-metadata.json").read_text(encoding="utf-8"))
        unloadable = {r["item_id"] for r in metadata["unloadable_wardrobe_rows"]}
        self.assertEqual(len(unloadable), 9)
        self.assertFalse(unloadable & {r["item_id"] for r in self.rows})
        controls = {r["item_id"] for r in self.service.wardrobe_removal_sentinels.values()}
        self.assertFalse(controls & {r["item_id"] for r in self.rows})
        self.assertEqual(self.summary["excluded_removal_controls"], 20)

    def test_resolution_rule_uses_only_the_items_own_manifest_folders(self):
        base = "Assets/ResourcesART/Wardrobe_EAB/"
        item = "Fixture000000000000000000000001"
        row = {"item_id": item, "gender": "MALE", "category": "CLOTH_HEAD_HAT", "category_conflict": True,
               "category_evidence": [
                   ["MALE", "CLOTH_HEAD_HAT", base + "MALE/CLOTH_HEAD_HAT/" + item + "/FBX/" + item + ".prefab"],
                   ["MALE", "CLOTH_HEAD_HAT", base + "MALE/CLOTH_HEAD_HAT/" + item + "/" + item + "Thumbnail.png"],
                   ["MALE", "CLOTH_HEAD_NECK", base + "MALE/CLOTH_HEAD_NECK/" + item + "/" + item + "Thumbnail.png"]]}
        neck = {**row, "category": "CLOTH_HEAD_NECK"}
        decisions = {d["category"]: d for d in builder.wardrobe_resolutions({"items": [row, neck]})}
        self.assertEqual(decisions["CLOTH_HEAD_HAT"]["decision"], "valid")
        self.assertEqual(decisions["CLOTH_HEAD_HAT"]["resolution"], "single_loadable_category")
        self.assertEqual(decisions["CLOTH_HEAD_NECK"]["decision"], "excluded")

    def test_applying_resolutions_is_idempotent_and_preserves_formatting(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "avatar-asset-catalog.json"
            shutil.copyfile(ROOT / "protocol/avatar-asset-catalog.json", path)
            before = path.read_bytes()
            self.assertEqual(builder.apply_wardrobe_resolutions(path), (0, 24))
            self.assertEqual(path.read_bytes(), before)


class RecoveredMetadata(Seeded):
    def test_component_fields_are_attached_to_the_right_categories(self):
        wardrobe = [r for r in self.rows if r["kind"] == "wardrobe"]
        heels = [r for r in wardrobe if r["heel_type"]]
        hands = [r for r in wardrobe if r["hand_type"]]
        self.assertGreater(len(heels), 800)
        self.assertGreater(len(hands), 400)
        self.assertTrue(all(r["category"] == "CLOTH_BODY_FEET" and r["heel_type"] in
                            ("HighHeel0", "HighHeel1", "HighHeel2", "HighHeel3") for r in heels))
        self.assertTrue(all(r["category"].startswith("CLOTH_BODY_HANDITEM") for r in hands))
        self.assertTrue(all(r["subcategory"] == r["heel_type"] for r in heels))
        locomotions = [r for r in self.rows if r["kind"] == "locomotions"]
        self.assertTrue(all(isinstance(r["locomotion_max_speed"], float) for r in locomotions))
        self.assertTrue(all("Locomotion" in r["component_classes"] for r in locomotions))
        housing = [r for r in self.rows if r["kind"] == "housing"]
        for row in housing:
            placement = row["housing_placement"]
            self.assertEqual(row["category_enum"]["value"], HOUSING_MENU.index(row["category"]))
            self.assertIn(placement["behaviour"], ("ground", "wall", "ceiling"))
            self.assertIn(placement["slot_kind"], ("floor_areas", "wall_slots", "ceiling_slots"))
            self.assertEqual(placement["max_placement_space"], 200)
            self.assertEqual(row["subcategory"], placement["behaviour"])
        self.assertEqual(sum(bool(r["interaction_classes"]) for r in housing), 345)
        conflicts = [r for r in housing if r["housing_placement"]["serialized_tablename_conflict"]]
        self.assertEqual(len(conflicts), 2)

    def test_derived_values_are_labelled_and_never_claim_commercial_facts(self):
        for row in self.rows:
            sources = row["metadata_sources"]
            self.assertIn("store_category", sources)
            if row["variant_family"]:
                self.assertEqual(row["variant_basis"], "derived_identical_internal_mesh_names")
                self.assertGreaterEqual(row["variant_family_size"], 2)
                self.assertIn("derived", sources["variant_family"])
            if row["housing_group"]:
                self.assertIn("derived", sources["housing_group"])
            self.assertIsNone(row["original_store"])
            self.assertIsNone(row["original_price"])
        families = {}
        for row in self.rows:
            if row["variant_family"]:
                families.setdefault(row["variant_family"], set()).add((row["kind"], row["gender"], row["category"]))
        self.assertTrue(all(len(v) == 1 for v in families.values()))

    def test_committed_metadata_covers_the_catalog_and_declares_unrecovered_fields(self):
        document = json.loads((ROOT / "protocol/item-catalog-metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(document["format_version"], 1)
        self.assertTrue(document["field_status"]["rarity_tier"].startswith("not_recovered"))
        entries = {identity(e) for e in document["items"]}
        # Apartments are not bundle-backed; their metadata is personal-space-shop.json.
        self.assertTrue({identity(r) for r in self.rows if r["kind"] != "personal_spaces"} <= entries)
        self.assertTrue(all(r["catalog_metadata"] for r in self.rows))

    def test_component_builder_is_deterministic(self):
        record = {"identity": ["wardrobe", "Fixture000000000000000000000002", "FEMALE", "CLOTH_BODY_FEET"],
                  "bundle": "04/fixture", "sha256": "ab" * 32, "manifest_sha256": "cd" * 32,
                  "components": [{"path_id": 7, "class": "HighHeel", "field_names": ["_type"], "scalars": {"_type": 2}},
                                 {"path_id": 8, "class": "Outline", "field_names": [], "scalars": {}}],
                  "animator_controllers": []}
        first = builder.component_fields(record)
        self.assertEqual(first, builder.component_fields(json.loads(json.dumps(record))))
        self.assertEqual(first[0]["heel_type"], "HighHeel2")
        self.assertEqual(first[0]["component_classes"], ["HighHeel"])


class TypeRealignment(unittest.TestCase):
    """Legacy generated offers move to client type IDs; operator edits never."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "preservation.sqlite3")
        self.service = Service(self.store, Catalog(ROOT / "protocol"))

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def call(self, route, *values):
        return self.service.shop.dispatch(route, Request(tuple(map(str, values)), "StandaloneWindows"))

    def test_legacy_type_ids_are_realigned_idempotently_without_touching_operator_or_player_state(self):
        seed_full_catalog(self.service)
        rows = [r for r in CatalogInventory(self.service).items if r["category"] in CLIENT_TYPE_MERGES]
        legacy, edited = rows[:3], rows[3]
        db = self.store.db
        for row in rows:
            db.execute("UPDATE shop_offers SET type_id=? WHERE offer_id=?", (row["category"], offer_id(row)))
        db.execute("""CREATE TABLE IF NOT EXISTS management_catalog_overrides (
            entity_kind TEXT NOT NULL, entity_id TEXT NOT NULL, changed_fields TEXT NOT NULL,
            updated_at REAL NOT NULL, PRIMARY KEY(entity_kind,entity_id))""")
        db.execute("UPDATE shop_offers SET crystals=1,name='Operator wristband' WHERE offer_id=?", (offer_id(edited),))
        db.execute("INSERT INTO management_catalog_overrides VALUES('offer',?,?,1)",
                   (offer_id(edited), '["crystals","name"]'))
        self.store.account("category-owner", "Owner")
        self.store.bind_session("category-owner", "owner-guid")
        self.service.shop.set_wallet("category-owner", 55, 6)
        db.execute("INSERT INTO shop_owned VALUES(?,?,?,?,?)",
                   ("category-owner", offer_id(legacy[0]), "admin", "fixture", time.time()))
        db.commit()
        # The legacy and operator offers are still listed under the client's
        # merged type, and the unknown raw IDs are never sent as TypeData.
        types = [r["typeID"] for r in decode(self.call("GetShopTypeDataShopServlet", "owner-guid", "category-owner",
                                                       POLICY + "-wardrobe", 0), TYPE_DATA)]
        self.assertTrue(set(types) <= set(CLIENT_TYPE_SPRITES))
        gender = {"MALE": 0, "FEMALE": 1}[edited["gender"]]
        listed = {r["id"] for r in decode(self.call("GetItemAssetsDataServlet", "owner-guid", "category-owner",
                                                    POLICY + "-wardrobe", gender, edited["store_category"]), ITEM_DATA)}
        self.assertIn(edited["item_id"], listed)
        columns = "offer_id,name,crystals,np,shop_id,active,featured,image_path,gender_id"
        before = [tuple(r) for r in db.execute("SELECT " + columns + " FROM shop_offers ORDER BY offer_id")]
        owned = [tuple(r) for r in db.execute("SELECT * FROM shop_owned")]
        result = seed_full_catalog(self.service)
        self.assertEqual((result["retyped_offers"], result["created_offers"]), (len(rows) - 1, 0))
        self.assertEqual(db.execute("SELECT type_id FROM shop_offers WHERE offer_id=?", (offer_id(edited),)).fetchone()[0],
                         edited["category"])
        for row in legacy:
            self.assertEqual(db.execute("SELECT type_id FROM shop_offers WHERE offer_id=?", (offer_id(row),)).fetchone()[0],
                             row["store_category"])
        self.assertEqual(before, [tuple(r) for r in db.execute("SELECT " + columns + " FROM shop_offers ORDER BY offer_id")])
        self.assertEqual(owned, [tuple(r) for r in db.execute("SELECT * FROM shop_owned")])
        self.assertEqual(self.service.shop.wallet("category-owner")["crystals"], 55)
        snapshot = db.serialize()
        again = seed_full_catalog(self.service)
        self.assertEqual((again["retyped_offers"], again["created_offers"], again["relabelled_offers"]), (0, 0, 0))
        self.assertEqual(db.serialize(), snapshot)


if __name__ == "__main__":
    unittest.main()
