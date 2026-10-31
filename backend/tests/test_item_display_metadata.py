"""Item display-name recovery, provenance and idempotent offer backfill.

Fixtures only: no game installation or private research scan is required.
"""
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "tools")]
import build_item_display_metadata as builder
import catalog_inventory
from catalog_inventory import (CatalogInventory, POLICY, clean_text, display_fields, identity,
                               load_item_metadata, offer_id, seed_full_catalog)
from service import Service
from state import Catalog, Store
from wire import ProtocolError

BUNNY = "A0IQgRXmw2UMG8T5UGrVE022o7Id25GU"


def scan_record(identity_row, names, components=()):
    return {"identity": identity_row, "bundle": "02/" + identity_row[1].lower(), "sha256": "ab" * 32,
            "manifest_sha256": "cd" * 32, "names": [{"type": t, "path_id": i, "name": n} for i, (t, n) in enumerate(names)],
            "component_strings": list(components)}


class Derivation(unittest.TestCase):
    def test_companion_label_comes_from_its_own_typed_object_names(self):
        record = scan_record(["companions", BUNNY, None, "COMPANIONS"], [
            ("GameObject", "EasterBunny_Mesh"), ("GameObject", BUNNY), ("GameObject", "Shoulder_R"),
            ("Mesh", "EasterBunny_Mesh"), ("Texture2D", "EasterBunny_CLR"), ("Material", "EasterBunny_Mat"),
            ("AnimatorController", "Companion"), ("AnimationClip", "EasterBunny_Idle01"),
            ("Avatar", "EasterBunny_RigAvatar")])
        derived, _alternatives = builder.derive(record)
        self.assertEqual(derived["label"], "Easter Bunny")
        self.assertEqual(derived["confidence"], "high")
        self.assertTrue(all(BUNNY not in e["name"] for e in derived["evidence"]))

    def test_ids_bones_markers_and_generic_names_are_never_labels(self):
        for raw in (BUNNY, "S_0_" + BUNNY + "_lod0", "FBX_" + BUNNY + "Avatar", "ch_r_shoulder_jnt", "Female_Root",
                    "BadPositionMarker", "polySurface2", "pPipe4", "Take 001", "normal", "lambert2", "Root",
                    "CFX4_SpaceThruster AddSoft", "Trigger_Bench", "PATA_DEL_DER_01"):
            self.assertIsNone(builder.stem(raw, BUNNY), raw)
        self.assertEqual(builder.stem("MedievalTrousers_Shader_Base_Color", BUNNY)[1], "Medieval Trousers")
        self.assertEqual(builder.stem("Chicken_Idle01Avatar", BUNNY)[1], "Chicken")

    def test_build_is_deterministic_and_never_claims_original_names(self):
        rows = [scan_record(["housing", "HouseItem00000000000000000000001", None, "HOUSING_LIGHT"],
                            [("GameObject", "Xmas19F_Table_Lamp_01"), ("Mesh", "Xmas19F_Table_Lamp_01"),
                             ("Material", "Lamp_Mat")],
                            [{"path_id": 5, "values": [{"field": "/ShowText", "value": "Switch on"}]}]),
                scan_record(["wardrobe", "Wear0000000000000000000000000001", "MALE", "CLOTH_HEAD_HAT"],
                            [("Mesh", "Wear0000000000000000000000000001_lod0"), ("Material", "normal")])]
        identities = [builder.identity_key(*r["identity"]) for r in rows]
        first = builder.render(builder.build(rows, identities, "fixture.jsonl", "00" * 32))
        second = builder.render(builder.build(list(reversed(rows)), list(reversed(identities)), "fixture.jsonl", "00" * 32))
        self.assertEqual(first, second)
        document = json.loads(first)
        lamp, hat = sorted(document["items"], key=lambda r: r["kind"])
        self.assertEqual((lamp["derived_name"], lamp["season_hint"], lamp["interaction_labels"]),
                         ("Xmas 19F Table Lamp 01", "Christmas", ["Switch on"]))
        self.assertIsNone(hat["derived_name"])
        for entry in document["items"]:
            self.assertIsNone(entry["original_name"])
            self.assertIsNone(entry["description"])
        self.assertEqual(document["coverage"]["housing"]["derived_name"], 1)
        with self.assertRaises(ValueError):
            builder.build(rows, identities[:1], "fixture.jsonl", "00" * 32)


class DisplayFields(unittest.TestCase):
    def test_original_then_derived_then_preservation_label(self):
        derived = display_fields({"derived_name": "Easter Bunny"}, "Preserved Companions X")
        self.assertEqual((derived["name"], derived["name_source"], derived["original_name"]),
                         ("Easter Bunny", "derived_asset_name", None))
        original = display_fields({"original_name": "Shipped", "derived_name": "Easter Bunny"}, "Preserved X")
        self.assertEqual((original["name"], original["name_source"]), ("Shipped", "original_shipped_string"))
        missing = display_fields(None, "Preserved Companions X")
        self.assertEqual((missing["name"], missing["display_name"], missing["name_source"]),
                         ("Preserved Companions X", None, "preservation_label"))

    def test_wire_unsafe_text_is_rejected(self):
        for value in ("a#b", "line\x00", "x" * 200, "", "   ", None, 7):
            self.assertIsNone(clean_text(value))
        self.assertEqual(clean_text("  Easter   Bunny "), "Easter Bunny")
        self.assertEqual(display_fields({"derived_name": "Bad#Name"}, "Fallback")["name"], "Fallback")

    def test_metadata_file_is_validated(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(load_item_metadata(directory), {})
            path = Path(directory) / catalog_inventory.METADATA_FILE
            entry = {"kind": "companions", "item_id": BUNNY, "derived_name": "Easter Bunny"}
            path.write_text(json.dumps({"format_version": 1, "items": [entry]}), encoding="utf-8")
            self.assertEqual(load_item_metadata(directory)[identity(entry)]["derived_name"], "Easter Bunny")
            path.write_text(json.dumps({"format_version": 1, "items": [entry, entry, {}]}), encoding="utf-8")
            with self.assertRaises(ProtocolError):
                load_item_metadata(directory)
            path.write_text(json.dumps({"format_version": 2, "items": []}), encoding="utf-8")
            with self.assertRaises(ProtocolError):
                load_item_metadata(directory)


class OfferBackfill(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "preservation.sqlite3")
        self.service = Service(self.store, Catalog(ROOT / "protocol"))
        self.items = {(r["kind"], r["item_id"]): r for r in CatalogInventory(self.service).items if r["kind"] != "wardrobe"}
        picks = sorted(self.items)[:3]
        self.rows = [self.items[k] for k in picks]
        self.fixture = {identity(r): {"kind": r["kind"], "item_id": r["item_id"], "derived_name": "Fixture " + str(i),
                                      "derived_name_confidence": "high", "provenance": {"bundle": r["bundle"]}}
                        for i, r in enumerate(self.rows)}

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def seed(self, metadata):
        with patch.object(catalog_inventory, "load_item_metadata", return_value=metadata):
            return seed_full_catalog(self.service)

    def name(self, row):
        return self.store.db.execute("SELECT name FROM shop_offers WHERE offer_id=?", (offer_id(row),)).fetchone()[0]

    def test_new_offers_and_catalog_rows_use_the_best_available_name(self):
        result = self.seed(self.fixture)
        self.assertEqual(result["relabelled_offers"], 0)
        self.assertEqual(self.name(self.rows[0]), "Fixture 0")
        with patch.object(catalog_inventory, "load_item_metadata", return_value=self.fixture):
            assets, offers, _stores, _counts, _summary = CatalogInventory(self.service).snapshot()
        row = next(a for a in assets if identity(a) == identity(self.rows[0]))
        self.assertEqual((row["display_name"], row["name_source"], row["provenance"]["display_name"]),
                         ("Fixture 0", "derived_asset_name", "derived_asset_name"))
        self.assertIsNone(row["original_name"])
        self.assertEqual(row["item_metadata"]["source_file"], "protocol/item-display-metadata.json")
        self.assertEqual(row["offers"][0]["listing_name_basis"], "item_display_name")
        self.assertEqual(row["offers"][0]["name_source"], "preservation_label")
        other = next(a for a in assets if a["kind"] == "wardrobe")
        self.assertEqual(other["name"], other["preservation_label"])

    def test_backfill_renames_only_untouched_generated_offers_and_is_idempotent(self):
        self.seed({})
        legacy = [self.name(r) for r in self.rows]
        self.assertTrue(all(name.startswith("Preserved ") for name in legacy))
        self.store.account("metadata-owner", "Owner")
        self.service.shop.set_wallet("metadata-owner", 99, 7)
        self.store.db.execute("INSERT INTO shop_owned VALUES(?,?,?,?,?)",
                              ("metadata-owner", offer_id(self.rows[0]), "admin", "fixture", time.time()))
        # Operator edits: the second offer was repriced (name untouched), the
        # third renamed. Neither may be overwritten by the backfill.
        self.store.db.execute("""CREATE TABLE IF NOT EXISTS management_catalog_overrides (
            entity_kind TEXT NOT NULL, entity_id TEXT NOT NULL, changed_fields TEXT NOT NULL,
            updated_at REAL NOT NULL, PRIMARY KEY(entity_kind,entity_id))""")
        self.store.db.execute("UPDATE shop_offers SET crystals=3 WHERE offer_id=?", (offer_id(self.rows[1]),))
        self.store.db.execute("UPDATE shop_offers SET name='Operator label' WHERE offer_id=?", (offer_id(self.rows[2]),))
        self.store.db.executemany("INSERT INTO management_catalog_overrides VALUES('offer',?,?,1)",
                                  [(offer_id(self.rows[1]), '["crystals"]'), (offer_id(self.rows[2]), '["name"]')])
        self.store.db.commit()
        columns = "offer_id,kind,item_id,gender,category,shop_id,type_id,gender_id,image_path,crystals,np,featured,active,created_at"
        before = [tuple(r) for r in self.store.db.execute("SELECT " + columns + " FROM shop_offers ORDER BY offer_id")]
        owned = [tuple(r) for r in self.store.db.execute("SELECT * FROM shop_owned")]

        result = self.seed(self.fixture)
        self.assertEqual((result["relabelled_offers"], result["created_offers"]), (1, 0))
        self.assertEqual([self.name(r) for r in self.rows], ["Fixture 0", legacy[1], "Operator label"])
        self.assertEqual(before, [tuple(r) for r in self.store.db.execute("SELECT " + columns + " FROM shop_offers ORDER BY offer_id")])
        self.assertEqual(owned, [tuple(r) for r in self.store.db.execute("SELECT * FROM shop_owned")])
        self.assertEqual(self.service.shop.wallet("metadata-owner")["crystals"], 99)

        snapshot = self.store.db.serialize()
        repeated = self.seed(self.fixture)
        self.assertEqual((repeated["relabelled_offers"], repeated["created_offers"], repeated["created_shops"]), (0, 0, 0))
        self.assertEqual(self.store.db.serialize(), snapshot)


class CommittedMetadata(unittest.TestCase):
    """The checked-in generated file joins the catalog and stays wire-safe."""

    def test_generated_file_matches_catalog_identities_and_policy(self):
        path = ROOT / "protocol" / catalog_inventory.METADATA_FILE
        if not path.exists():
            self.skipTest("Generated item display metadata is not present")
        document = json.loads(path.read_text(encoding="utf-8"))
        temp = tempfile.TemporaryDirectory()
        store = Store(Path(temp.name) / "catalog.sqlite3")
        try:
            items = CatalogInventory(Service(store, Catalog(ROOT / "protocol"))).items
        finally:
            store.close()
            temp.cleanup()
        catalog = {identity(r) for r in items}
        entries = {identity(e): e for e in document["items"]}
        self.assertEqual(len(entries), len(document["items"]))
        self.assertLessEqual(set(entries), catalog)
        for key, entry in entries.items():
            if entry["derived_name"] is not None:
                self.assertEqual(clean_text(entry["derived_name"], 80), entry["derived_name"])
                self.assertNotIn(entry["item_id"].lower(), entry["derived_name"].lower())
                self.assertEqual(entry["name_source"], "derived_asset_name")
                self.assertTrue(entry["provenance"]["derived_name"]["objects"])
            if entry["original_name"] is not None:
                self.assertIn("original_name", entry["provenance"])
        # Apartment names come from protocol/personal-space-shop.json, not this file.
        named = sum(r["display_name"] is not None for r in items if r["kind"] != "personal_spaces")
        self.assertEqual(named, sum(c.get("derived_name", 0) for c in document["coverage"].values()))


if __name__ == "__main__":
    unittest.main()
