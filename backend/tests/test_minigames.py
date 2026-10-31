"""Offline HTTP minigame contract checks. No sockets, game process or listener."""
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

from management import Management
from minigames import (BOAT_MAX_TICKS, BOAT_MIN_TICKS, LEADERBOARD_ROWS, ROUTES as MINIGAME_ROUTES,
                       TICKS_PER_SECOND)
from rewards import CONFIGURABLE
from service import Service
from state import Catalog, Store
from wire import ProtocolError, session_guid


class Clock:
    def __init__(self, value=1_800_000_000.0):
        self.value = value

    def __call__(self):
        return self.value


class Minigames(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog(ROOT / "protocol")
        cls.wardrobe = sorted(cls.catalog.items.values(),
                              key=lambda x: (x["item_id"], x["gender"], x["category"]))[0]
        cls.scratch = (Path(tempfile.gettempdir()) / "nebula-preserved-tests") / "work/offline-minigame-tests"
        cls.scratch.mkdir(parents=True, exist_ok=True)

    def setUp(self):
        self.no_network = patch.object(socket, "socket", side_effect=AssertionError("Network is forbidden"))
        self.no_network.start()
        self.temp = tempfile.TemporaryDirectory(dir=self.scratch)
        self.path = Path(self.temp.name)
        self.file = self.path / "state.sqlite3"
        self.store = Store(self.file)
        self.service = Service(self.store, self.catalog)
        self.clock = Clock()
        self.service.minigames.now = self.clock
        self.a = self.login("mini-a", "Alice")
        self.b = self.login("mini-b", "Bob")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()
        self.no_network.stop()

    def call(self, route, *fields):
        return self.service.dispatch(route, "#".join(fields) + "#StandaloneWindows")

    def login(self, account, username):
        self.call("N2UserExist", username, "v72", "false", account, "1.25")
        digest = (account.encode().hex() * 64)[:64]
        self.assertEqual(self.call("ChannelGUIDServlet", account, digest), "true#")
        return session_guid(account, digest)

    def reopen(self):
        self.store.close()
        self.store = Store(self.file)
        self.service = Service(self.store, self.catalog)
        self.service.minigames.now = self.clock

    def assertRejected(self, route, *fields, status=None):
        with self.assertRaises(ProtocolError) as caught:
            self.call(route, *fields)
        if status is not None:
            self.assertEqual(caught.exception.status, status)

    # ---------------------------------------------------------------- routing
    def test_routes_are_dispatched_by_service(self):
        self.assertEqual(len(MINIGAME_ROUTES), 12)
        self.assertLessEqual(MINIGAME_ROUTES | {"checkRewardGameServlet"}, self.service.ROUTES)
        for route in ("GetLeaderboardServlet", "SetLeaderboardServlet", "AddStatisticsServlet",
                      "MemorionServlet", "Get_GatherChristmasGetSpacesCompleted"):
            self.assertNotIn(route, MINIGAME_ROUTES)

    # ---------------------------------------------------------------- archery
    def test_archery_best_score_leaderboard_and_persistence(self):
        self.assertEqual(self.call("GetBestScoreArcheryServlet", self.a, "mini-a"), f"true#{self.a}#mini-a#0")
        self.assertEqual(self.call("GetLeaderboardArcheryServlet", self.a, "mini-a"), f"true#{self.a}")
        self.assertEqual(self.call("AddScoreArcheryServlet", self.a, "mini-a", "450"), f"true#{self.a}#mini-a")
        self.call("AddScoreArcheryServlet", self.a, "mini-a", "300")  # never lowers the best
        self.call("AddScoreArcheryServlet", self.b, "mini-b", "620")
        self.reopen()
        self.assertEqual(self.call("GetBestScoreArcheryServlet", self.a, "mini-a").split("#"),
                         ["true", self.a, "mini-a", "450"])
        reply = self.call("GetLeaderboardArcheryServlet", self.a, "mini-a").split("#")
        self.assertEqual(reply, ["true", self.a, "Bob!620", "Alice!450"])
        # SetLeaderboardContent @0x52cf70 needs >= 2 '!' parts; Int32 score.
        for row in reply[2:]:
            name, score = row.split("!")
            self.assertTrue(name)
            int(score)

    def test_archery_validation(self):
        for score in ("0", "-1", "100001", "+5", "05", "1.5", ""):
            self.assertRejected("AddScoreArcheryServlet", self.a, "mini-a", score)
        self.assertRejected("AddScoreArcheryServlet", self.a, "mini-b", "10", status=403)
        self.assertRejected("AddScoreArcheryServlet", self.a, "mini-a", status=400)
        self.assertRejected("GetBestScoreArcheryServlet", "f" * 32, "mini-a", status=403)
        # A newer session for the same account makes the old GUID read-only.
        newer = session_guid("mini-a", "b" * 64)
        self.store.bind_session("mini-a", newer)
        self.assertRejected("AddScoreArcheryServlet", self.a, "mini-a", "10", status=403)
        self.call("AddScoreArcheryServlet", newer, "mini-a", "10")

    def test_leaderboard_is_bounded_and_skips_unrepresentable_names(self):
        for i in range(LEADERBOARD_ROWS + 3):
            account = f"lb-{i:02d}"
            guid = self.login(account, f"P{i:02d}" if i != 0 else "Bad!Name")
            self.call("AddScoreArcheryServlet", guid, account, str(100 + i))
        rows = self.call("GetLeaderboardArcheryServlet", self.a, "mini-a").split("#")[2:]
        self.assertEqual(len(rows), LEADERBOARD_ROWS)
        self.assertEqual(rows[0], "P12!112")
        self.assertNotIn("Bad!Name!100", rows)

    # ------------------------------------------------------------------- boat
    def test_boat_lower_time_wins_and_rank_reply(self):
        self.assertEqual(self.call("GetBestScoreBoatMiniGameServlet", self.a, "mini-a"), f"true#{self.a}#mini-a#0")
        slow, fast = str(95 * TICKS_PER_SECOND), str(61 * TICKS_PER_SECOND + 1234)
        self.assertEqual(self.call("AddScoreBoatMiniGameServlet", self.a, "mini-a", slow),
                         f"true#{self.a}#mini-a#1")
        self.assertEqual(self.call("AddScoreBoatMiniGameServlet", self.b, "mini-b", fast),
                         f"true#{self.b}#mini-b#1")
        reply = self.call("AddScoreBoatMiniGameServlet", self.a, "mini-a", str(99 * TICKS_PER_SECOND))
        self.assertEqual(reply.split("#")[3], "2")  # a worse time keeps the best and rank
        self.reopen()
        self.assertEqual(self.call("GetBestScoreBoatMiniGameServlet", self.a, "mini-a").split("#")[3], slow)
        self.assertEqual(self.call("GetLeaderboardBoatMiniGameServlet", self.b, "mini-b").split("#"),
                         ["true", self.b, "Bob!" + fast, "Alice!" + slow])

    def test_boat_validation(self):
        for ticks in (str(BOAT_MIN_TICKS - 1), str(BOAT_MAX_TICKS + 1), "-5", "abc"):
            self.assertRejected("AddScoreBoatMiniGameServlet", self.a, "mini-a", ticks)
        self.call("AddScoreBoatMiniGameServlet", self.a, "mini-a", str(BOAT_MIN_TICKS))

    # --------------------------------------------------------------- footrace
    def test_footrace_cooldown_and_finish_variants(self):
        self.assertEqual(self.call("GetCooldownServlet", self.a, "mini-a", "FootRace"), f"true#{self.a}#mini-a#-1")
        self.assertEqual(self.call("SetCooldownServlet", self.a, "mini-a", "FootRace", "1", "true"),
                         f"true#{self.a}#mini-a#true#false")
        # Default local policy has no cooldown: the race is available again.
        self.assertEqual(self.call("GetCooldownServlet", self.a, "mini-a", "FootRace").split("#")[3], "-1")
        self.service.minigames.configure("footrace_cooldown_seconds", 600)
        self.assertEqual(self.call("SetCooldownServlet", self.a, "mini-a", "FootRace", "false"),
                         f"true#{self.a}#mini-a#false#false")
        self.clock.value += 100
        self.reopen()
        self.service.minigames.now = self.clock
        self.assertEqual(self.call("GetCooldownServlet", self.a, "mini-a", "FootRace").split("#")[3],
                         str(500 * TICKS_PER_SECOND))
        self.clock.value += 500
        self.assertEqual(self.call("GetCooldownServlet", self.a, "mini-a", "FootRace").split("#")[3], "-1")

    def test_footrace_route_reward_is_optional_and_claimed_once(self):
        item = self.wardrobe
        self.service.rewards.configure("SetCooldownServlet", "2", grant_kind="wardrobe",
            item_id=item["item_id"], gender=item["gender"], category=item["category"])
        self.assertEqual(self.call("SetCooldownServlet", self.a, "mini-a", "FootRace", "0", "true").split("#")[4], "false")
        self.assertEqual(self.call("SetCooldownServlet", self.a, "mini-a", "FootRace", "2", "true").split("#")[4], "true")
        self.assertEqual(self.call("SetCooldownServlet", self.a, "mini-a", "FootRace", "2", "true").split("#")[4], "false")
        owned = [x for x in self.store.inventory("mini-a") if x["item_id"] == item["item_id"]]
        self.assertEqual(len(owned), 1)
        with self.assertRaises(ProtocolError):
            self.service.rewards.configure("SetCooldownServlet", "3", grant_kind="wardrobe",
                item_id=item["item_id"], gender=item["gender"], category=item["category"])

    def test_footrace_validation(self):
        self.assertRejected("GetCooldownServlet", self.a, "mini-a", "Archery")
        self.assertRejected("SetCooldownServlet", self.a, "mini-a", "FootRace", "3", "true")
        self.assertRejected("SetCooldownServlet", self.a, "mini-a", "FootRace", "0", "false")
        self.assertRejected("SetCooldownServlet", self.a, "mini-a", "FootRace", "true")
        self.assertRejected("SetCooldownServlet", self.a, "mini-a", "FootRace")

    # --------------------------------------------------------------------- XP
    def test_add_xp_defaults_to_no_award(self):
        self.assertEqual(self.call("AddXPServlet", self.a, "mini-a", "6"), f"true#{self.a}#0")
        self.assertEqual(self.service.shop.wallet("mini-a")["np"], 0)
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM minigame_xp_events").fetchone()[0], 1)
        for value in ("13", "-1", "Archery", "06"):
            self.assertRejected("AddXPServlet", self.a, "mini-a", value)

    def test_add_xp_award_credits_wallet_and_management_ledger(self):
        Management(self.store, self.service, b"not-a-real-secret-temporary-test-token-12345",
                   [{"id": "owner", "role": "owner", "enabled": True}])
        self.service.minigames.configure("xp_np_8", 25)
        self.assertEqual(self.call("AddXPServlet", self.a, "mini-a", "8"), f"true#{self.a}#25")
        self.assertEqual(self.call("AddXPServlet", self.a, "mini-a", "8"), f"true#{self.a}#25")
        self.assertEqual(self.service.shop.wallet("mini-a")["np"], 50)
        ledger = [dict(x) for x in self.store.db.execute(
            "SELECT * FROM management_wallet_ledger WHERE account_id='mini-a' ORDER BY ledger_id")]
        self.assertEqual([(x["currency"], x["delta"], x["before_balance"], x["after_balance"]) for x in ledger],
                         [("np", 25, 0, 25), ("np", 25, 25, 50)])
        self.assertTrue(all(x["reason"] == "AddXPServlet FootRace" for x in ledger))
        with self.assertRaises(ProtocolError):
            self.service.minigames.configure("xp_np_13", 1)
        with self.assertRaises(ProtocolError):
            self.service.minigames.configure("xp_np_8", -1)

    # ------------------------------------------------------------------ cupid
    def test_cupid_inactive_by_default_hides_trigger(self):
        self.assertEqual(self.call("Get_GatherArcheryCupid", self.a, "mini-a", "638000000000000000"),
                         f"true#{self.a}#mini-a#false#0#0#0")
        self.assertRejected("Send_ArcheryCupidConsume", self.a, "mini-a", "638000000000000000", status=409)

    def test_cupid_rounds_hearts_cooldown_and_reward(self):
        item = self.wardrobe
        self.service.rewards.configure("Send_ArcheryCupidConsume", "4", grant_kind="wardrobe",
            item_id=item["item_id"], gender=item["gender"], category=item["category"])
        self.service.minigames.configure("cupid_active", 1)
        self.service.minigames.configure("cupid_fires", 2)
        self.service.minigames.configure("cupid_cooldown_seconds", 3600)
        ticks = "638000000000000000"
        for heart in range(1, 5):
            self.assertEqual(self.call("Get_GatherArcheryCupid", self.a, "mini-a", ticks),
                             f"true#{self.a}#mini-a#true#0#2#{heart - 1}")
            self.assertEqual(self.call("Send_ArcheryCupidConsume", self.a, "mini-a", ticks),
                             f"true#{self.a}#mini-a#1#{heart - 1}#0")
            self.assertEqual(self.call("Send_ArcheryCupidConsume", self.a, "mini-a", ticks),
                             f"true#{self.a}#mini-a#0#{heart}#3600")
            if heart < 4:
                self.clock.value += 1800
                self.assertEqual(self.call("Get_GatherArcheryCupid", self.a, "mini-a", ticks),
                                 f"true#{self.a}#mini-a#true#1800#0#{heart}")
                self.assertRejected("Send_ArcheryCupidConsume", self.a, "mini-a", ticks, status=409)
                self.clock.value += 1800
        self.assertEqual(self.call("Get_GatherArcheryCupid", self.a, "mini-a", ticks),
                         f"true#{self.a}#mini-a#true#0#0#4")
        self.assertRejected("Send_ArcheryCupidConsume", self.a, "mini-a", ticks, status=409)
        self.assertEqual(len([x for x in self.store.inventory("mini-a") if x["item_id"] == item["item_id"]]), 1)
        with self.assertRaises(ProtocolError):
            self.service.minigames.configure("cupid_fires", 7)
        with self.assertRaises(ProtocolError):
            self.service.minigames.configure("cupid_cooldown_seconds", 0)

    # -------------------------------------------------------------------- SKL
    def test_skl_progress_cooldown_and_completion_reward(self):
        item = self.wardrobe
        self.service.rewards.configure("XSpacesGamesType0Servlet", "0", grant_kind="wardrobe",
            item_id=item["item_id"], gender=item["gender"], category=item["category"])
        self.assertEqual(self.call("XSpacesGamesType0Servlet", self.a, "mini-a", "0"),
                         f"true#{self.a}#mini-a#0#1#true#0")
        self.service.minigames.configure("skl_cooldown_seconds", 60)
        self.clock.value += 60
        self.assertEqual(self.call("XSpacesGamesType0Servlet", self.a, "mini-a", "0"),
                         f"true#{self.a}#mini-a#0#2#true#{60 * TICKS_PER_SECOND}")
        self.clock.value += 15
        self.assertEqual(self.call("XSpacesGamesType0Servlet", self.a, "mini-a", "0"),
                         f"true#{self.a}#mini-a#0#2#false#{45 * TICKS_PER_SECOND}")
        for step in range(3, 7):
            self.clock.value += 60
            reply = self.call("XSpacesGamesType0Servlet", self.a, "mini-a", "0").split("#")
            self.assertEqual(reply[4:6], [str(step), "true"])
        self.assertEqual(reply[6], "0")
        self.reopen()
        self.clock.value += 600
        self.assertEqual(self.call("XSpacesGamesType0Servlet", self.a, "mini-a", "0"),
                         f"true#{self.a}#mini-a#0#6#false#0")
        self.assertEqual(len([x for x in self.store.inventory("mini-a") if x["item_id"] == item["item_id"]]), 1)
        self.assertRejected("XSpacesGamesType0Servlet", self.a, "mini-a", "1")

    # ------------------------------------------------------- checkRewardGame
    def test_check_reward_game_claims_configured_reward_once(self):
        item = self.wardrobe
        self.assertEqual(self.call("checkRewardGameServlet", self.a, "mini-a", "ArcheryBow", "0"),
                         f"true#{self.a}#true")
        self.assertEqual(self.call("checkRewardGameServlet", self.a, "mini-a", "MiniGolf", "2"),
                         f"true#{self.a}#true")
        self.service.rewards.configure("checkRewardGameServlet", "ArcheryBow:0", grant_kind="wardrobe",
            item_id=item["item_id"], gender=item["gender"], category=item["category"])
        self.assertEqual(self.call("checkRewardGameServlet", self.a, "mini-a", "ArcheryBow", "0"),
                         f"true#{self.a}#false")
        self.assertEqual(self.call("checkRewardGameServlet", self.a, "mini-a", "ArcheryBow", "0"),
                         f"true#{self.a}#true")
        self.assertEqual(self.call("checkRewardGameServlet", self.b, "mini-b", "ArcheryBow", "0"),
                         f"true#{self.b}#false")
        self.assertEqual(len([x for x in self.store.inventory("mini-a") if x["item_id"] == item["item_id"]]), 1)
        self.assertRejected("checkRewardGameServlet", self.a, "mini-a", "ArcheryBow", "01")
        self.assertRejected("checkRewardGameServlet", self.a, "mini-a", "ArcheryBow")
        self.assertRejected("checkRewardGameServlet", self.a, "mini-b", "ArcheryBow", "0", status=403)
        for bad in ("Unknown:0", "ArcheryBow", "ArcheryBow:x", "ChronoRace:10000"):
            with self.assertRaises(ProtocolError):
                self.service.rewards.configure("checkRewardGameServlet", bad, grant_kind="wardrobe",
                    item_id=item["item_id"], gender=item["gender"], category=item["category"])
        self.assertIn("checkRewardGameServlet", CONFIGURABLE)


class MinigameAdminEntrypoint(unittest.TestCase):
    def test_settings_cli_from_clean_process(self):
        import json
        import os
        import subprocess
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        with tempfile.TemporaryDirectory() as scratch:
            state = Path(scratch) / "state"

            def run(*arguments, success=True):
                result = subprocess.run([sys.executable, str(BACKEND / "minigame_admin.py"),
                                         "--state-dir", str(state), *arguments],
                                        cwd=scratch, env=environment, text=True,
                                        capture_output=True, timeout=30)
                if success:
                    self.assertEqual(0, result.returncode, result.stderr)
                    return json.loads(result.stdout)
                self.assertNotEqual(0, result.returncode)

            self.assertEqual(run("settings")["cupid_active"], 0)
            self.assertEqual(run("set", "footrace_cooldown_seconds", "120")["footrace_cooldown_seconds"], 120)
            run("set", "cupid_fires", "7", success=False)
            self.assertEqual(run("leaderboard", "boat"), [])


if __name__ == "__main__":
    unittest.main()
