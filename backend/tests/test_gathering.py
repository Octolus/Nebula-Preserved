"""Pure offline tests for gathering wire shapes and explicit local policy."""
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

from gathering import Gathering
from housing import HousingStore
from resources import ResourceCatalog, ResourceEntitlements
from state import Catalog, Store
from wire import ProtocolError, Request


class GatheringContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = (Path(tempfile.gettempdir()) / "nebula-preserved-tests") / "work/offline-gathering-tests"
        cls.scratch.mkdir(parents=True, exist_ok=True)

    def setUp(self):
        self.no_network = patch.object(socket, "socket", side_effect=AssertionError("No network in gathering tests"))
        self.no_network.start()
        self.temp = tempfile.TemporaryDirectory(dir=self.scratch)
        self.path = Path(self.temp.name)
        self.store = Store(self.path / "state.sqlite3")
        self.store.account("account-a", "Player A")
        self.store.bind_session("account-a", "guid-a")
        protocol = ROOT / "protocol"
        self.catalog = Catalog(protocol)
        self.resource_catalog = ResourceCatalog(protocol)
        self.resources = ResourceEntitlements(self.store, self.resource_catalog)
        self.housing = HousingStore(self.store, protocol)
        self.clock = 1000.0
        self.source = Gathering(self.store, self.catalog, self.resources, self.housing,
                                now=lambda: self.clock)

    def tearDown(self):
        self.store.close(); self.temp.cleanup(); self.no_network.stop()

    def req(self, *fields):
        return Request(tuple(fields), "StandaloneWindows")

    def test_unconfigured_and_inactive_events_fail_closed(self):
        changes = self.store.db.total_changes
        # Native "no event running" answer (field 3 false), with no write.
        self.assertEqual(self.source.dispatch("Get_GatherStatus", self.req("guid-a", "account-a", "1")),
                         "true#guid-a#account-a#false#1#0")
        self.assertEqual(self.store.db.total_changes, changes)
        self.source.configure(1, "Christmas", active=False, max_items=5, cooldown_seconds=60)
        self.assertEqual(self.source.dispatch("Get_npGather", self.req("guid-a", "account-a", "Christmas", "5")),
                         "true#guid-a#account-a#0#60")
        with self.assertRaises(ProtocolError):
            self.source.dispatch("Get_npGather", self.req("guid-a", "account-a", "Christmas", "6"))

    def test_init_and_phase_have_distinct_native_field_order(self):
        self.source.configure(2, "Easter", active=True, max_items=4, phase=3)
        self.assertEqual(self.source.dispatch("Get_npGather", self.req("guid-a", "account-a", "Easter", "4")),
                         "true#guid-a#account-a#1#0#4")
        first = self.source.dispatch("Get_npGatherProcessItem",
            self.req("guid-a", "account-a", "Easter", "4", "2"))
        self.assertEqual(first, "true#guid-a#account-a#Easter#1#4#1")
        scene = self.source.dispatch("Send_GatherInitInSpace", self.req("guid-a", "account-a", "space-a", "2"))
        self.assertEqual(scene.split("#"),
                         ["true", "guid-a", "account-a", "2", "1", "3", "0"])
        phase = self.source.dispatch("Get_GatherPhaseGame",
                                     self.req("guid-a", "account-a", "2"))
        self.assertEqual(phase.split("#"),
                         ["true", "guid-a", "account-a", "2", "0", "1", "3"])
        self.assertEqual(self.source.dispatch("Get_GatherStatus", self.req("guid-a", "account-a", "2")),
                         "true#guid-a#account-a#true#2#1")

    def test_progress_is_bounded_and_identity_owned(self):
        self.source.configure(0, "Halloween", active=True, max_items=2)
        for _ in range(3):
            reply = self.source.dispatch("Get_npGatherProcessItem",
                self.req("guid-a", "account-a", "Halloween", "2", "0"))
        self.assertEqual(reply.split("#")[-3:], ["2", "2", "2"])
        with self.assertRaises(ProtocolError):
            self.source.dispatch("Get_GatherStatus", self.req("guid-a", "other", "0"))
        with self.assertRaises(ProtocolError):
            self.source.dispatch("Get_GatherStatus", self.req("guid-a", "account-a", "9"))

    def test_consume_and_reward_are_durable_and_idempotent(self):
        item_id = self.resource_catalog.list("companions")[0]["item_id"]
        self.source.configure(1, "Christmas", active=True, max_items=2,
            reward={"kind": "companion", "item_id": item_id, "name": "Local event reward"})
        first = self.source.dispatch("Get_GatherConsume",
            self.req("guid-a", "account-a", "1", "0"))
        second = self.source.dispatch("Get_GatherConsume",
            self.req("guid-a", "account-a", "1", "1"))
        self.assertEqual(first, "true#guid-a#account-a#1#1#0")
        self.assertEqual(second, "true#guid-a#account-a#1#2#0")
        # A replay carrying the stale pre-collection count is rejected.
        with self.assertRaises(ProtocolError):
            self.source.dispatch("Get_GatherConsume", self.req("guid-a", "account-a", "1", "1"))
        reward = self.source.dispatch("Get_GatherConsumeReward", self.req("guid-a", "account-a", "1", "2"))
        self.assertEqual(reward, "true#guid-a#account-a#1#0#1")
        self.assertEqual(self.resources.list("account-a", "companions")[0]["item_id"], item_id)
        with self.assertRaises(ProtocolError):
            self.source.dispatch("Get_GatherConsumeReward", self.req("guid-a", "account-a", "1", "2"))
        progress = self.store.db.execute("""SELECT current_items,rewards_earned,reward_claimed
            FROM gathering_progress WHERE ps4_id='account-a' AND type_id=1""").fetchone()
        self.assertEqual(tuple(progress), (0, 1, 1))

    def test_christmas_generic_branch_and_memorion_route_is_deferred(self):
        self.source.configure(1, "Christmas", active=True, max_items=5, phase=4)
        state0 = self.source.dispatch("Get_npGatherChristmas",
            self.req("guid-a", "account-a", "space-a", "0"))
        state1 = self.source.dispatch("Get_npGatherChristmas",
            self.req("guid-a", "account-a", "space-a", "1"))
        self.assertEqual(state0.split("#")[3:], ["0", "1", "0", "0", "0"])
        self.assertEqual(state1.split("#")[3:], ["1", "0", "2", "0", "0"])
        with self.assertRaises(ProtocolError):
            self.source.dispatch("Get_npGatherChristmas",
                self.req("guid-a", "account-a", "space-a", "2"))
        # The Christmas 2018 Memorion score route lives in backend/fullgame.py.
        self.assertFalse(hasattr(self.source, "route_Get_GatherChristmasGetSpacesCompleted"))

    def test_christmas_2018_scene_flags_are_unique_ordered_and_fail_closed(self):
        self.source.configure(4, "Christmas2018", active=True, max_items=5)
        nexus = self.req("guid-a", "account-a", "4", "Nexus")
        self.assertEqual(self.source.dispatch("Get_GatherConsume", nexus).split("#")[3:],
                         ["4", "1", "0"])
        self.assertEqual(self.source.dispatch("Get_GatherConsume", nexus).split("#")[3:],
                         ["4", "1", "0"])
        with self.assertRaises(ProtocolError):
            self.source.dispatch("Get_GatherConsume",
                                 self.req("guid-a", "account-a", "4", "Bowling"))
        for scene in ("LeafPark", "Dome", "Cube", "Beach"):
            self.source.dispatch("Get_GatherConsume",
                                 self.req("guid-a", "account-a", "4", scene))
        init = self.source.dispatch("Send_GatherInitInSpace",
            self.req("guid-a", "account-a", "Nexus", "4")).split("#")
        phase = self.source.dispatch("Get_GatherPhaseGame",
            self.req("guid-a", "account-a", "4")).split("#")
        self.assertEqual(init[3:], ["4", "5", "0", "0", "1", "1", "1", "1", "1"])
        self.assertEqual(phase[3:], ["4", "0", "5", "0", "1", "1", "1", "1", "1"])

    def test_event_reward_and_marker_rollback_together_after_grant_failure(self):
        item_id = self.resource_catalog.list("companions")[0]["item_id"]
        self.source.configure(1, "Christmas", active=True, max_items=2,
            reward={"kind": "companion", "item_id": item_id})
        self.source.set_progress("account-a", 1, current_items=2)
        original = self.source._grant_reward
        def fail_after_grant(*args):
            original(*args)
            raise RuntimeError("injected after event grant")
        with patch.object(self.source, "_grant_reward", side_effect=fail_after_grant):
            with self.assertRaises(RuntimeError):
                self.source.dispatch("Get_GatherConsumeReward", self.req("guid-a", "account-a", "1", "2"))
        self.store.close()
        self.store = Store(self.path / "state.sqlite3")
        self.resources = ResourceEntitlements(self.store, self.resource_catalog)
        self.housing = HousingStore(self.store, ROOT / "protocol")
        self.source = Gathering(self.store, self.catalog, self.resources, self.housing, now=lambda: self.clock)
        self.assertEqual(self.resources.list("account-a", "companions"), [])
        rolled_back = self.store.db.execute("""SELECT current_items,rewards_earned,reward_claimed
            FROM gathering_progress WHERE ps4_id='account-a' AND type_id=1""").fetchone()
        self.assertEqual(tuple(rolled_back), (2, 0, 0))
        self.source.dispatch("Get_GatherConsumeReward", self.req("guid-a", "account-a", "1", "2"))
        self.assertEqual([x["item_id"] for x in self.resources.list("account-a", "companions")], [item_id])

    def test_medieval_client_field_order_and_completion(self):
        self.assertEqual(self.source.dispatch("Get_GatherMedievalVillage",
            self.req("guid-a", "account-a", "638972000000000000")),
            "true#guid-a#account-a#0#0#0")
        self.source.set_medieval("account-a", active=True, amount_left=2)
        self.assertEqual(self.source.dispatch("Get_GatherMedievalVillage",
            self.req("guid-a", "account-a", "638972000000000001")),
            "true#guid-a#account-a#true#0#2")
        self.assertEqual(self.source.dispatch("Send_GatherMedievalVillageConsume",
            self.req("guid-a", "account-a", "638972000000000002")),
            "true#guid-a#account-a#1#0#1")
        self.assertEqual(self.source.dispatch("Send_GatherMedievalVillageConsume",
            self.req("guid-a", "account-a", "638972000000000003")),
            "true#guid-a#account-a#5#0#Completed")

    def test_configuration_validation_and_no_game_routes(self):
        self.assertEqual(len(Gathering.ROUTES), 10)
        self.assertNotIn("Get_GatherChristmasGetSpacesCompleted", Gathering.ROUTES)
        self.assertNotIn("Get_GatherArcheryCupid", Gathering.ROUTES)
        with self.assertRaises(ProtocolError): self.source.configure(9, "bad")
        with self.assertRaises(ProtocolError): self.source.configure(1, "bad#name")
        with self.assertRaises(ProtocolError): self.source.configure(1, "x", active="yes")
        with self.assertRaises(ProtocolError): self.source.configure(1, "x", reward={"kind": "coins", "item_id": "x"})
        with self.assertRaises(ProtocolError): self.source.dispatch("unknown", self.req())


if __name__ == "__main__": unittest.main()

