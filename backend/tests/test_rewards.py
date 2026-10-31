"""Offline reward/cinema/liveness checks with socket construction forbidden."""
import json
from pathlib import Path
import socket
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(ROOT / "tools"))

from allocation import InstanceDirectory
from resources import ResourceCatalog, ResourceEntitlements
from rewards import RewardService
from state import Catalog, Store
from wire import ProtocolError, Request


class Rewards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog(ROOT / "protocol")
        cls.wardrobe = sorted(cls.catalog.items.values(), key=lambda x: (x["item_id"], x["gender"], x["category"]))[0]
        resource = ResourceCatalog(ROOT / "protocol")
        cls.companion = resource.list("companions")[0]["item_id"]
        cls.locomotion = resource.list("locomotions")[0]["item_id"]
        cls.scratch = (Path(tempfile.gettempdir()) / "nebula-preserved-tests") / "work/offline-tests"
        cls.scratch.mkdir(parents=True, exist_ok=True)

    def setUp(self):
        self.network = patch.object(socket, "socket", side_effect=AssertionError("Network forbidden"))
        self.network.start()
        self.temp = tempfile.TemporaryDirectory(dir=self.scratch)
        self.path = Path(self.temp.name)
        self.store = Store(self.path / "preservation.sqlite3")
        self.store.account("account-a", "Player A")
        self.guid = "a" * 32
        self.store.bind_session("account-a", self.guid)
        self.instances = InstanceDirectory(self.path)
        self.service = RewardService(self.store, self.catalog, self.instances)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()
        self.network.stop()

    @staticmethod
    def request(*fields):
        return Request(tuple(fields), "StandaloneWindows")

    def call(self, route, trigger):
        return self.service.dispatch(route, self.request(self.guid, "account-a", str(trigger)))

    def test_generic_check_claim_and_idempotent_wardrobe_grant(self):
        item = self.wardrobe
        self.service.configure("GenericReward", "generic-one", grant_kind="wardrobe",
            item_id=item["item_id"], gender=item["gender"], category=item["category"])
        self.assertEqual(self.call("CheckOwnGenericReward", "generic-one").split("#")[3], "false")
        self.assertEqual(self.call("GenericReward", "generic-one").split("#")[3], "true")
        self.assertEqual(self.call("GenericReward", "generic-one").split("#")[3], "false")
        self.assertEqual(self.call("CheckOwnGenericReward", "generic-one").split("#")[3], "true")
        self.assertEqual(len([x for x in self.store.inventory("account-a") if x["item_id"] == item["item_id"]]), 1)

    def test_missing_and_disabled_generic_check_suppresses_without_claim(self):
        item = self.wardrobe
        expected_suppression = ["false", self.guid, "account-a", "true"]

        changes = self.store.db.total_changes
        self.assertEqual(self.call("CheckOwnGenericReward", "not-configured").split("#"),
                         expected_suppression)
        self.assertEqual(self.store.db.total_changes, changes)
        self.assertEqual(self.service.claims("account-a"), [])
        self.assertEqual(self.store.inventory("account-a"), [])
        with self.assertRaises(ProtocolError) as missing_claim:
            self.call("GenericReward", "not-configured")
        self.assertEqual(missing_claim.exception.status, 404)
        self.assertEqual(self.store.db.total_changes, changes)

        self.service.configure("GenericReward", "disabled", enabled=False,
            grant_kind="wardrobe", item_id=item["item_id"], gender=item["gender"],
            category=item["category"])
        changes = self.store.db.total_changes
        self.assertEqual(self.call("CheckOwnGenericReward", "disabled").split("#"),
                         expected_suppression)
        with self.assertRaises(ProtocolError) as disabled_claim:
            self.call("GenericReward", "disabled")
        self.assertEqual(disabled_claim.exception.status, 404)
        self.assertEqual(self.store.db.total_changes, changes)
        self.assertEqual(self.service.claims("account-a"), [])
        self.assertEqual(self.store.inventory("account-a"), [])

        # Suppression is not durable ownership. Enabling the same definition
        # later exposes the native unowned branch and permits one real claim.
        self.service.configure("GenericReward", "disabled", enabled=True,
            grant_kind="wardrobe", item_id=item["item_id"], gender=item["gender"],
            category=item["category"])
        self.assertEqual(self.call("CheckOwnGenericReward", "disabled").split("#")[3],
                         "false")
        self.assertEqual(self.call("GenericReward", "disabled").split("#")[3], "true")
        self.assertEqual(self.call("CheckOwnGenericReward", "disabled").split("#")[3],
                         "true")
        self.assertEqual(len([x for x in self.store.inventory("account-a")
                              if x["item_id"] == item["item_id"]]), 1)

    def test_cloth_numeric_contract_and_no_unknown_success(self):
        item = self.wardrobe
        self.service.configure("RewardClothServlet", "0", grant_kind="wardrobe",
            item_id=item["item_id"], gender=item["gender"], category=item["category"])
        self.assertEqual(self.call("RewardClothServlet", "0").split("#"), ["false", self.guid, "true"])
        self.assertEqual(self.call("RewardClothServlet", "0").split("#")[2], "false")
        with self.assertRaises(ProtocolError):
            self.call("RewardClothServlet", "1")
        with self.assertRaises(ProtocolError):
            self.service.configure("RewardClothServlet", "1", grant_kind="wardrobe",
                item_id=item["item_id"], gender=item["gender"], category=item["category"])
        with self.assertRaises(ProtocolError):
            self.service.configure("RewardClothServlet", "0", grant_kind="companions", item_id=self.companion)
        with self.assertRaises(ProtocolError):
            self.service.configure("GenericReward", "bad", grant_kind="wardrobe", item_id="not-shipped")

    def test_reward_consume_grants_validated_companion_once(self):
        self.service.configure("RewardConsumeServlet", "companion-token", grant_kind="companions", item_id=self.companion)
        expected = "true#" + self.guid + "#account-a"
        self.assertEqual(self.call("RewardConsumeServlet", "companion-token"), expected)
        self.assertEqual(self.call("RewardConsumeServlet", "companion-token"), expected)
        grants = ResourceEntitlements(self.store, ResourceCatalog(ROOT / "protocol")).list("account-a", "companions")
        self.assertEqual([x["item_id"] for x in grants], [self.companion])
        self.assertEqual(len(self.service.claims("account-a")), 1)

    def test_consumable_grant_and_claim_marker_rollback_together_after_fault(self):
        self.service.configure("RewardConsumeServlet", "coffee-reward",
            grant_kind="coffee", item_id="coffee", units=2, uses=3)
        with patch.object(self.service, "_after_grant", side_effect=RuntimeError("injected crash window")):
            with self.assertRaisesRegex(RuntimeError, "injected crash window"):
                self.call("RewardConsumeServlet", "coffee-reward")

        # Reopen the durable state: neither the additive balance nor its claim
        # marker may have escaped the failed atomic group.
        self.store.close()
        self.store = Store(self.path / "preservation.sqlite3")
        self.instances = InstanceDirectory(self.path)
        self.service = RewardService(self.store, self.catalog, self.instances)
        self.assertIsNone(self.service.consumables.balance("account-a", "coffee"))
        self.assertEqual(self.service.claims("account-a"), [])

        expected = "true#" + self.guid + "#account-a"
        self.assertEqual(self.call("RewardConsumeServlet", "coffee-reward"), expected)
        self.assertEqual(self.call("RewardConsumeServlet", "coffee-reward"), expected)
        self.assertEqual(self.service.consumables.balance("account-a", "coffee")["units"], 2)
        self.assertEqual(len(self.service.claims("account-a")), 1)

    def test_unconfigured_skl_promo_trigger_is_hidden_without_writes(self):
        changes = self.store.db.total_changes
        self.assertEqual(self.call("SKLPromoTriggerServlet", "1").split("#"),
                         ["true", self.guid, "account-a", "true"])
        self.assertEqual(self.store.db.total_changes, changes)
        with self.assertRaises(ProtocolError):
            self.call("SKLPromoTriggerServlet", "99")  # not a shipped trigger
        with self.assertRaises(ProtocolError):
            self.call("SKLPromoServlet", "1")  # claiming still fails closed

    def test_skl_check_consume_sprite_and_locomotion(self):
        self.service.configure("SKLPromoServlet", "1", grant_kind="locomotions",
            item_id=self.locomotion, sprite_id=5)
        self.assertEqual(self.call("SKLPromoTriggerServlet", "1").split("#")[3], "false")
        self.assertEqual(self.call("SKLPromoServlet", "1").split("#"), ["true", self.guid, "account-a", "5"])
        self.assertEqual(self.call("SKLPromoTriggerServlet", "1").split("#")[3], "true")
        self.assertEqual(self.call("SKLPromoServlet", "1").split("#")[3], "5")
        grants = ResourceEntitlements(self.store, ResourceCatalog(ROOT / "protocol")).list("account-a", "locomotions")
        self.assertEqual([x["item_id"] for x in grants], [self.locomotion])
        with self.assertRaises(ProtocolError):
            self.service.configure("SKLPromoServlet", "7", grant_kind="locomotions",
                item_id=self.locomotion, sprite_id=0)
        with self.assertRaises(ProtocolError):
            self.service.configure("SKLPromoServlet", "1", grant_kind="locomotions",
                item_id=self.locomotion, sprite_id=6)

    def test_availability_is_explicit_configuration_only(self):
        self.assertEqual(self.call("checkRewardAvailableServlet", "Halloween").split("#")[2], "false")
        self.service.configure("checkRewardAvailableServlet", "Halloween")
        self.assertEqual(self.call("checkRewardAvailableServlet", "Halloween").split("#"), ["true", self.guid, "true"])
        self.service.configure("checkRewardAvailableServlet", "Halloween", enabled=False)
        self.assertEqual(self.call("checkRewardAvailableServlet", "Halloween").split("#")[2], "false")
        with self.assertRaises(ProtocolError):
            self.service.configure("checkRewardAvailableServlet", "Cube", grant_kind="wardrobe", item_id="x")
        with self.assertRaises(ProtocolError):
            self.service.configure("checkRewardAvailableServlet", "NotACompiledReward")
        with self.assertRaises(ProtocolError):
            self.call("checkRewardAvailableServlet", "NotACompiledReward")

    def test_cinema_requires_config_and_persists_capability(self):
        with self.assertRaises(ProtocolError):
            self.call("CinemaInteractionNPServlet", "0")
        self.service.configure("CinemaInteractionNPServlet", "0")
        expected = ["true", self.guid, "account-a", "true"]
        self.assertEqual(self.call("CinemaInteractionNPServlet", "0").split("#"), expected)
        self.assertEqual(self.call("CinemaInteractionNPServlet", "0").split("#"), expected)
        rows = self.store.db.execute("SELECT interaction_type FROM cinema_capabilities WHERE ps4_id=?", ("account-a",)).fetchall()
        self.assertEqual([x[0] for x in rows], [0])
        with self.assertRaises(ProtocolError):
            self.service.configure("CinemaInteractionNPServlet", "2")
        with self.assertRaises(ProtocolError):
            self.service.configure("CinemaInteractionNPServlet", "00")
        with self.assertRaises(ProtocolError):
            self.call("CinemaInteractionNPServlet", "-0")

    def test_space_liveness_is_current_allocation_and_fresh_ready_descriptor(self):
        instance = self.path / "instances" / "nexus-one"
        instance.mkdir(parents=True)
        status = {"format_version": 1, "protocol_complete": True, "listening": True,
            "heartbeat": time.time(), "ip": "127.0.0.1", "port": 28000,
            "instance_id": "nexus-one", "psidglobal": "Nexus", "maxusers": 32, "players": 1}
        (instance / "instance-status.json").write_text(json.dumps(status), encoding="utf-8")
        with self.store.db:
            self.store.db.execute("INSERT INTO allocations VALUES(?,?,?,?,?,?)",
                (self.guid, "nexus-one", "Nexus", "127.0.0.1", 28000, time.time()))
        self.assertEqual(self.call("CheckIfSpaceStillExistServlet", "nexus-one"), "true#true")
        self.assertEqual(self.call("CheckIfSpaceStillExistServlet", "other"), "true#false")
        status["psidglobal"] = "WrongWorld"
        (instance / "instance-status.json").write_text(json.dumps(status), encoding="utf-8")
        self.assertEqual(self.call("CheckIfSpaceStillExistServlet", "nexus-one"), "true#false")
        status["psidglobal"] = "Nexus"
        status["heartbeat"] = time.time() - 60
        (instance / "instance-status.json").write_text(json.dumps(status), encoding="utf-8")
        self.assertEqual(self.call("CheckIfSpaceStillExistServlet", "nexus-one"), "true#false")

    def test_wrong_session_field_count_and_unimplemented_route_rejected(self):
        with self.assertRaises(ProtocolError):
            self.service.dispatch("CinemaInteractionNPServlet", self.request("wrong", "account-a", "0"))
        with self.assertRaises(ProtocolError):
            self.service.dispatch("GenericReward", self.request(self.guid, "account-a"))
        with self.assertRaises(ProtocolError):
            self.service.dispatch("not-a-route", self.request(self.guid, "account-a", "x"))
        with self.assertRaises(ProtocolError):
            self.service.dispatch("checkRewardAvailableServlet",
                Request((self.guid, "account-a", "Cube"), "PS4"))


if __name__ == "__main__":
    unittest.main()

