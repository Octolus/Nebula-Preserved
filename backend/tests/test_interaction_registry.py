import json
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from interaction_registry import InteractionRegistryPublisher, _f32
from service import Service
from state import Catalog, Store


class InteractionRegistryTests(unittest.TestCase):
    def setUp(self):
        self.guard = patch.object(socket, "socket", side_effect=AssertionError("Sockets forbidden"))
        self.guard.start()
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "state.sqlite3")
        self.service = Service(self.store, Catalog(BACKEND.parent / "protocol"))
        self.publisher = InteractionRegistryPublisher(self.store, BACKEND.parent / "protocol")
        self.store.account("owner", "Owner")

    def tearDown(self):
        self.store.close(); self.temp.cleanup(); self.guard.stop()

    def row(self):
        return json.loads(self.publisher.export(self.root).read_text())["instances"][0]

    def test_mixed_static_profile_uses_unique_anchor_and_keeps_deferred_key(self):
        self.service.housing.bind_space("camp", "CampSilverLake", "owner")
        row = self.row()
        self.assertTrue(self.publisher.anchored_static)
        self.assertTrue(row["trusted"]); self.assertTrue(row["static_profile_available"])
        self.assertEqual(len(row["static_entries"]), 9)
        self.assertEqual({x["anchor"] for x in row["static_entries"]},{"CampSilverLakeLogicPREFAB"})
        self.assertEqual(sum(x["classification"] == "ordinary" for x in row["static_entries"]),8)
        self.assertEqual(sum(x["classification"] == "deferred_minigame" for x in row["static_entries"]),1)

    def test_layout_signature_compacts_f32_and_distinguishes_duplicates(self):
        self.service.housing.bind_space("home", "Home", "owner")
        chair = "A044fFy8Xtm2U2J1DuRolDt63P431gI8"
        self.service.housing.grant_item("owner", chair, "Chair")
        layout = self.service.housing.empty_layout("Home")
        layout["aidasset"] = [chair, "null", chair]
        layout["aidasset_tx"] = [-0.0, 0, 1.1]
        layout["aidasset_ty"] = [2, 0, 3]; layout["aidasset_tz"] = [4, 0, 5]
        layout["aidasset_r"] = [6, 0, 7]
        with self.store.db:
            self.store.db.execute("INSERT INTO housing_layouts VALUES(?,?,?)", ("home", json.dumps(layout), 1.0))
        row = self.row()
        self.assertTrue(row["static_profile_available"])
        self.assertEqual(len(row["static_entries"]),5)
        self.assertTrue(all(x["kind"] == "occupable" and x["anchor"] for x in row["static_entries"]))
        self.assertEqual([x["index"] for x in row["ground_sig"]], [0, 1])
        self.assertEqual(row["ground_sig"][0]["tx"], 0.0)
        self.assertEqual(row["ground_sig"][1]["tx"], _f32(1.1))
        self.assertEqual([x["ground_index"] for x in row["furniture_entries"]], [0, 1])

    def test_unresolved_manifest_item_denies_whole_instance(self):
        self.service.housing.bind_space("home", "Home", "owner")
        # An unresolved item remains forbidden even when the shipped catalog
        # is fully classified. Create the denied case explicitly in this fixture.
        item = dict(self.publisher.furniture["A044fFy8Xtm2U2J1DuRolDt63P431gI8"])
        item.update(status="unresolved_denied", admission="deny")
        self.publisher.furniture[item["item_id"]] = item
        self.service.housing.grant_item("owner", item["item_id"], "Unresolved")
        layout = self.service.housing.empty_layout("Home"); layout["aidasset"] = [item["item_id"]]
        for key in ("aidasset_tx", "aidasset_ty", "aidasset_tz", "aidasset_r"): layout[key] = [0.0]
        with self.store.db:
            self.store.db.execute("INSERT INTO housing_layouts VALUES(?,?,?)", ("home", json.dumps(layout), 1.0))
        row = self.row()
        self.assertFalse(row["trusted"])
        self.assertIn("layout_contains_unresolved_interaction_item", row["errors"])

    def test_public_instance_status_gets_descriptor_without_housing_owner(self):
        directory=self.root/'instances/public-nexus'; directory.mkdir(parents=True)
        (directory/'instance-status.json').write_text(json.dumps(dict(
            format_version=1,instance_id='public-nexus',psidglobal='Nexus')),encoding='utf-8')
        rows=json.loads(self.publisher.export(self.root).read_text())['instances']
        row=next(x for x in rows if x['instance_id']=='public-nexus')
        self.assertEqual(row['scene'],'Nexus'); self.assertEqual(row['owner_ps4_id'],'')
        self.assertTrue(row['trusted']); self.assertEqual(len(row['static_entries']),21)


if __name__ == "__main__": unittest.main()

