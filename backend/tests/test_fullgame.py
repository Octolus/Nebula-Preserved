"""Offline full-game lobby, leaderboard and Memorion contracts (no sockets)."""
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

from avatar_entry_codec import decode_entry_fields, encode_entry_fields, encode_value_texts
from fullgame import (FRIEND_LIST, FullGames, MINIGOLF_LAST_SCORE, MINIGOLF_LEADERBOARD_ENTRY,
                      MINIGOLF_STATISTIC, hhmmss)
from service import Service
from state import Catalog, Store
from wire import ProtocolError, session_guid

PS4 = "offline-account-a"


class FullGameContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog(ROOT / "protocol")
        cls.scratch = (Path(tempfile.gettempdir()) / "nebula-preserved-tests") / "work/offline-fullgame-tests"
        cls.scratch.mkdir(parents=True, exist_ok=True)

    def setUp(self):
        self.no_network = patch.object(socket, "socket", side_effect=AssertionError("No network in full-game tests"))
        self.no_network.start()
        self.temp = tempfile.TemporaryDirectory(dir=self.scratch)
        self.store = Store(Path(self.temp.name) / "state.sqlite3")
        self.service = Service(self.store, self.catalog)
        self.guid = self.login(PS4, "Golfer", "a")
        self.online = {}
        self.service.fullgames.presence = lambda: self.online

    def tearDown(self):
        self.store.close(); self.temp.cleanup(); self.no_network.stop()

    def call(self, route, *fields):
        return self.service.dispatch(route, "#".join(fields) + "#StandaloneWindows")

    def login(self, account, username, seed):
        self.call("N2UserExist", username, "v72", "false", account, "1.25")
        digest = seed * 64
        self.assertEqual(self.call("ChannelGUIDServlet", account, digest), "true#")
        return session_guid(account, digest)

    def fails(self, status, route, *fields):
        with self.assertRaises(ProtocolError) as caught:
            self.call(route, *fields)
        self.assertEqual(caught.exception.status, status)

    def golf(self, guid, ps4, hits, seconds, stage=1):
        stat = encode_entry_fields({"hits": hits, "seconds": seconds, "totalSecs": sum(seconds),
                                    "totalHits": sum(hits), "stage": stage}, MINIGOLF_STATISTIC)
        return self.call("AddStatisticsServlet", guid, ps4, "0", stat)

    def test_routes_are_integrated(self):
        self.assertTrue(FullGames.ROUTES <= self.service.ROUTES)
        self.assertEqual(len(FullGames.ROUTES), 14)
        # MemorionTrigger.Start reads GetIinitInfosNeeded field3 (isMemorionActive).
        self.assertEqual(self.call("GetIinitInfosNeededServlet", self.guid, PS4).split("#")[3], "true")

    def test_active_stages_unlock_every_shipped_stage(self):
        self.assertEqual(self.call("GetActiveStagesServlet", self.guid, PS4, "0"),
                         "#".join(["true", self.guid, PS4, "0", "3"]))
        self.assertEqual(self.call("GetActiveStagesServlet", self.guid, PS4, "8").split("#")[4], "3")
        self.fails(400, "GetActiveStagesServlet", self.guid, PS4, "1")  # ChronoRace has no lobby client.
        self.fails(403, "GetActiveStagesServlet", "f" * 32, PS4, "0")

    def test_minigolf_statistics_rank_personal_best_and_last_score(self):
        hits, seconds = [3] * 18, [10] * 18
        reply = self.golf(self.guid, PS4, hits, seconds).split("#")
        # Consumer @0x513de0 needs >= 8 fields: bool, hits, Int32 seconds, rank.
        self.assertEqual(reply, ["true", self.guid, PS4, "0", "true", "54", "180", "1"])
        worse = self.golf(self.guid, PS4, [4] * 18, seconds).split("#")
        self.assertEqual(worse[4:], ["false", "72", "180", "1"])
        other = self.login("offline-account-b", "Rival", "b")
        self.assertEqual(self.golf(other, "offline-account-b", [2] * 18, [5] * 18).split("#")[4:],
                         ["true", "36", "90", "1"])
        board = self.call("GetFullGameLeaderboardServlet", self.guid, PS4, "0", "1", "False").split("#")
        self.assertEqual(board[:7], ["true", self.guid, PS4, "0", "1", "False", "2"])
        rows = [decode_entry_fields(x, MINIGOLF_LEADERBOARD_ENTRY) for x in board[7:]]
        self.assertEqual(rows, [{"name": "Rival", "hits": 36, "time": "00:01:30"},
                                {"name": "Golfer", "hits": 54, "time": "00:03:00"}])
        last = self.call("GetLastScoreServlet", self.guid, PS4, "0").split("#")
        self.assertEqual(len(last), 5)
        score = decode_entry_fields(last[4], MINIGOLF_LAST_SCORE)
        self.assertEqual(score, {"hits": [4] * 18, "totalHits": 72, "stage": 1, "rank": 2,
                                 "bestHits": 54, "totalTime": "00:03:00"})
        space = self.call("GetLeaderboardServlet", self.guid, PS4, "MiniGolf", "1")
        self.assertEqual(space, "Rival!36!00:01:30#Golfer!54!00:03:00")

    def test_statistics_validation_and_unreachable_kart(self):
        self.fails(400, "AddStatisticsServlet", self.guid, PS4, "0", "garbage")
        bad = encode_entry_fields({"hits": [3], "seconds": [1], "totalSecs": 1, "totalHits": 4, "stage": 1},
                                  MINIGOLF_STATISTIC)
        self.fails(400, "AddStatisticsServlet", self.guid, PS4, "0", bad)
        self.fails(400, "GetActiveStagesServlet", self.guid, PS4, "8x")
        self.fails(400, "AddStatisticsServlet", self.guid, PS4, "8", encode_value_texts(["1", "1", "12.5"]))
        stale = self.login(PS4, "Golfer", "c")  # A newer session supersedes self.guid.
        self.assertNotEqual(stale, self.guid)
        self.fails(403, "AddStatisticsServlet", self.guid, PS4, "0",
                   encode_entry_fields({"hits": [1], "seconds": [1], "totalSecs": 1, "totalHits": 1, "stage": 1},
                                       MINIGOLF_STATISTIC))

    def test_empty_boards_and_missing_last_score(self):
        self.assertEqual(self.call("GetFullGameLeaderboardServlet", self.guid, PS4, "8", "2", "True"),
                         "#".join(["true", self.guid, PS4, "8", "2", "True", "0"]))
        self.fails(400, "GetFullGameLeaderboardServlet", self.guid, PS4, "0", "4", "True")
        self.fails(404, "GetLastScoreServlet", self.guid, PS4, "8")
        self.fails(404, "GetLeaderboardServlet", self.guid, PS4, "Pinball", "2")
        self.fails(400, "GetLeaderboardServlet", self.guid, PS4, "Pinball", "3")
        self.fails(400, "GetLeaderboardServlet", self.guid, PS4, "Archery", "1")
        self.fails(400, "GetLeaderboardServlet", "")  # Unsupported types send empty plaintext.

    def test_chronorace_set_leaderboard_and_empty_kart_request(self):
        self.assertEqual(self.call("SetLeaderboardServlet", self.guid, PS4, "ChronoRace", "61500", "2"),
                         "true#" + self.guid + "#" + PS4)
        self.call("SetLeaderboardServlet", self.guid, PS4, "ChronoRace", "70000", "2")
        other = self.login("offline-account-b", "Rival", "b")
        self.call("SetLeaderboardServlet", other, "offline-account-b", "ChronoRace", "59000", "2")
        self.assertEqual(self.call("GetLeaderboardServlet", self.guid, PS4, "ChronoRace", "2"),
                         "Rival!59000#Golfer!61500")
        # Kart results (0x50bf00) call the same coroutine, which sends empty plaintext.
        self.assertEqual(self.service.dispatch("SetLeaderboardServlet", "#StandaloneWindows"), "true#")
        self.fails(400, "SetLeaderboardServlet", self.guid, PS4, "KartRace", "1000", "1")
        self.fails(400, "SetLeaderboardServlet", self.guid, PS4, "ChronoRace", "1000", "4")

    def test_multiplayer_lobby_without_a_game_host(self):
        self.assertEqual(self.call("GetOpenGamesServlet", self.guid, PS4, "8"),
                         "#".join(["true", self.guid, PS4, "0"]))
        self.assertEqual(self.call("AddToPoolFullGameServlet", self.guid, PS4, "8", "game-1"),
                         "#".join(["true", self.guid, PS4, "false"]))
        self.assertEqual(self.call("CheckIsAvailableToJoinFullGameServlet", self.guid, PS4, "8", "game-1"),
                         "#".join(["true", self.guid, PS4, "2"]))
        # OpenGameEntry: id_game, ip, port, stage, isPublic, totalPlayers, state, type, extra, players.
        tokens = [None, None, "0", "2", "1", "2", "0", "KartRace", "3",
                  "1", "guid-x", "Friend", "null", "0", "Waiting", "0"]
        entry = encode_value_texts(tokens)
        reply = self.call("CreateGameServlet", self.guid, PS4, "8", "2", entry).split("#")
        self.assertEqual(reply[:4], ["true", self.guid, PS4, "2"])
        self.assertEqual(reply[4], encode_value_texts([None, None, "-1"] + tokens[3:]))
        self.fails(400, "CreateGameServlet", self.guid, PS4, "8", "2", encode_value_texts(["x", "y"]))
        self.fails(400, "CreateGameServlet", self.guid, PS4, "8", "0", entry)

    def test_invite_friend_list_lists_online_friends(self):
        friend = self.login("offline-account-b", "Buddy", "b")
        self.login("offline-account-c", "Away", "c")
        for target in ("Buddy", "Away"):
            self.store.db.execute("INSERT INTO relations VALUES(?,?,?,?)",
                                  (PS4, target, "StandaloneWindows", "friend"))
        self.store.db.commit()
        empty = self.call("GetInviteFriendList", self.guid, PS4, "0").split("#")
        self.assertEqual(len(empty), 4)
        self.assertEqual(decode_entry_fields(empty[3], FRIEND_LIST), {"names": [], "stages": [], "guids": []})
        self.online = {friend: 0}
        listed = self.call("GetInviteFriendList", self.guid, PS4, "0").split("#")
        self.assertEqual(decode_entry_fields(listed[3], FRIEND_LIST),
                         {"names": ["Buddy"], "stages": [3], "guids": [friend]})

    def test_memorion_score_leaderboard_and_christmas_2018_flow(self):
        self.assertEqual(self.call("MemorionServlet", self.guid, PS4, "7", "638972000000000000"),
                         "#".join(["true", self.guid, PS4, "7", "7"]))
        self.assertEqual(self.call("MemorionServlet", self.guid, PS4, "4", "638972000000000001").split("#")[3:],
                         ["4", "7"])
        self.assertEqual(self.call("GetLeaderboardServlet", self.guid, PS4, "Memorion", "1"), "Golfer!7")
        self.fails(400, "MemorionServlet", self.guid, PS4, "-1", "638972000000000000")
        ticks = "638972000000000002"
        self.assertEqual(self.call("Get_BRAINMEMORION", self.guid, PS4, ticks).split("#")[3], "-1")
        self.fails(409, "Get_GatherChristmasGetSpacesCompleted", self.guid, PS4, "4", ticks)
        self.service.gathering.configure(4, "Christmas2018", active=True, max_items=5)
        self.store.db.execute("INSERT INTO allocations VALUES(?,?,?,?,?,?)",
                              (self.guid, "inst-1", "LeafPark", "127.0.0.1", 7777, 0.0))
        self.store.db.commit()
        self.assertEqual(self.call("Get_BRAINMEMORION", self.guid, PS4, ticks).split("#")[3], "0")
        # Only the level most recently returned by MemorionServlet is accepted.
        self.fails(409, "Get_GatherChristmasGetSpacesCompleted", self.guid, PS4, "9", ticks)
        self.assertEqual(self.call("Get_GatherChristmasGetSpacesCompleted", self.guid, PS4, "4", ticks),
                         "#".join(["true", self.guid, PS4, "4", "0"]))
        self.call("Get_GatherConsume", self.guid, PS4, "4", "LeafPark")
        self.assertEqual(self.call("Get_BRAINMEMORION", self.guid, PS4, ticks).split("#")[3], "1")
        self.assertEqual(self.call("Get_GatherChristmasGetSpacesCompleted", self.guid, PS4, "4", ticks).split("#")[4],
                         "1")

    def test_time_format_matches_client_formatter(self):
        self.assertEqual(hhmmss(0), "00:00:00")
        self.assertEqual(hhmmss(3725), "01:02:05")
        self.assertEqual(hhmmss(36000), "10:00:00")


if __name__ == "__main__":
    unittest.main()
