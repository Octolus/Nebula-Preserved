"""Full-game lobby, score/leaderboard and Memorion HTTP contracts.

Wire layouts are recovered from the shipped client (Steam build 11018722); the
RVAs below name the request builders and response consumers. Score storage,
ranking order, row limits and the absence of a multiplayer game host are
explicit local preservation policy (docs/research/minigame-contracts.md).
Nothing here grants entitlements. Importing this module opens no socket.
"""
from __future__ import annotations

import json
import math
import re
import time

from avatar_entry_codec import decode_entry_fields, encode_entry_fields, encode_value_texts, take_value
from gathering import CHRISTMAS_2018_SCENES
from wire import ProtocolError

# FullGameManager.Type (dump TypeDefIndex 1385).
MINIGOLF, CHRONORACE, PINBALL, KARTRACE, MEMORION = 0, 1, 2, 8, 9
TYPE_NAMES = {MINIGOLF: "MiniGolf", CHRONORACE: "ChronoRace", PINBALL: "Pinball",
              KARTRACE: "KartRace", MEMORION: "Memorion"}
TYPE_IDS = {name: type_id for type_id, name in TYPE_NAMES.items()}

# Stage catalogs come from shipped asset bundles, not server data:
# UIFullGameLeaderboardSpaces.contents lengths (nexus ChronoRace 3, bowling
# Pinball 2, leafpark KartRace 3 and Memorion 1) and minigolfstage_1..3.
STAGE_COUNTS = {MINIGOLF: 3, CHRONORACE: 3, PINBALL: 2, KARTRACE: 3, MEMORION: 1}
# Only KartGameNETGCloud and MiniGolfNETGCloud derive from FullGameNETGCloud.
LOBBY_TYPES = {MINIGOLF, KARTRACE}
# Lower-is-better boards; Pinball and Memorion rank the highest value first.
ASCENDING = {MINIGOLF: True, CHRONORACE: True, KARTRACE: True, PINBALL: False, MEMORION: False}

LEADERBOARD_ROWS = 10  # Authored policy: the retired server's row limit is unknown.
MINIGOLF_HOLES = 18    # MiniGolfManager.SetHoleStatistic finishes after hole index 0x11.
MAX_TICKS = 9_999_999_999_999_999_999

MINIGOLF_STATISTIC = [  # MiniGolfNETGCloud.InfoAddStatistic public field order.
    {"name": "hits", "type": {"array": "int"}},
    {"name": "seconds", "type": {"array": "int"}},
    {"name": "totalSecs", "type": "int"},
    {"name": "totalHits", "type": "int"},
    {"name": "stage", "type": "int"},
]
MINIGOLF_LEADERBOARD_ENTRY = [
    {"name": "name", "type": "string"}, {"name": "hits", "type": "int"},
    {"name": "time", "type": "string"}]
MINIGOLF_LAST_SCORE = [
    {"name": "hits", "type": {"array": "int"}}, {"name": "totalHits", "type": "int"},
    {"name": "stage", "type": "int"}, {"name": "rank", "type": "int"},
    {"name": "bestHits", "type": "int"}, {"name": "totalTime", "type": "string"}]
FRIEND_LIST = [
    {"name": "names", "type": {"array": "string"}},
    {"name": "stages", "type": {"array": "int"}},
    {"name": "guids", "type": {"array": "string"}}]


def hhmmss(total_seconds):
    """FullGameNETGCloud.FormatStringTime(HHmmss) @0x4e6a70: zero-padded H:M:S."""
    minutes = total_seconds // 60
    parts = (minutes // 60, minutes % 60, total_seconds % 60)
    return ":".join(("0" if part < 10 else "") + str(part) for part in parts)


def integer(text, label, minimum, maximum):
    if not isinstance(text, str) or not re.fullmatch(r"-?[0-9]+", text):
        raise ProtocolError("Invalid " + label)
    value = int(text)
    if str(value) != text or not minimum <= value <= maximum:
        raise ProtocolError("Invalid " + label)
    return value


class FullGames:
    ROUTES = {
        "AddToPoolFullGameServlet", "CheckIsAvailableToJoinFullGameServlet",
        "CreateGameServlet", "GetOpenGamesServlet", "GetInviteFriendList",
        "GetActiveStagesServlet", "GetLastScoreServlet", "GetFullGameLeaderboardServlet",
        "AddStatisticsServlet", "GetLeaderboardServlet", "SetLeaderboardServlet",
        "MemorionServlet", "Get_BRAINMEMORION", "Get_GatherChristmasGetSpacesCompleted",
    }

    def __init__(self, store, now=time.time):
        self.store, self.now = store, now
        self.presence = store.presence
        store.db.executescript("""
            CREATE TABLE IF NOT EXISTS fullgame_best_scores (
                ps4_id TEXT NOT NULL REFERENCES profiles(ps4_id),
                game_type INTEGER NOT NULL, stage INTEGER NOT NULL,
                score INTEGER NOT NULL, tiebreak INTEGER NOT NULL,
                detail_json TEXT NOT NULL, achieved_at REAL NOT NULL,
                PRIMARY KEY(ps4_id,game_type,stage));
            CREATE TABLE IF NOT EXISTS fullgame_last_results (
                ps4_id TEXT NOT NULL REFERENCES profiles(ps4_id),
                game_type INTEGER NOT NULL, stage INTEGER NOT NULL,
                score INTEGER NOT NULL, tiebreak INTEGER NOT NULL,
                detail_json TEXT NOT NULL, achieved_at REAL NOT NULL,
                PRIMARY KEY(ps4_id,game_type));
        """)
        store.db.commit()

    def dispatch(self, command, request):
        if command not in self.ROUTES:
            raise ProtocolError("Full-game route is not reconstructed", 501)
        return getattr(self, "route_" + command)(request)

    # Identity -----------------------------------------------------------------
    def _identity(self, request, count, *, write=False):
        fields = request.require(count)
        profile = self.store.session(fields[0], fields[1])
        if profile["platform"] != request.platform:
            raise ProtocolError("Session platform does not match local account", 403)
        if write and self.store.current_guid(profile["ps4_id"]) != fields[0]:
            raise ProtocolError("Historical session cannot record a score", 403)
        return fields, profile

    @staticmethod
    def _lobby_type(text):
        value = integer(text, "full-game type", 0, 9)
        if value not in LOBBY_TYPES:
            raise ProtocolError("Full-game type has no FullGameNETGCloud client")
        return value

    @staticmethod
    def _reply(guid, ps4_id, *values):
        values = [str(value) for value in values]
        if any("#" in value for value in values):
            raise ProtocolError("Value cannot be represented in full-game framing")
        return "#".join(["true", guid, ps4_id, *values])

    # Score storage --------------------------------------------------------------
    def _better(self, game_type, score, tiebreak, row):
        if row is None:
            return True
        if ASCENDING[game_type]:
            return (score, tiebreak) < (row["score"], row["tiebreak"])
        return (score, -tiebreak) > (row["score"], -row["tiebreak"])

    def _record(self, profile, game_type, stage, score, tiebreak=0, detail=None):
        """Store the latest result and keep the personal best; returns isBest."""
        detail_json = json.dumps(detail or {}, separators=(",", ":"), sort_keys=True)
        at = self.now()
        with self.store.atomic():
            self.store.db.execute(
                """INSERT INTO fullgame_last_results VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(ps4_id,game_type) DO UPDATE SET stage=excluded.stage,score=excluded.score,
                tiebreak=excluded.tiebreak,detail_json=excluded.detail_json,achieved_at=excluded.achieved_at""",
                (profile["ps4_id"], game_type, stage, score, tiebreak, detail_json, at))
            best = self.store.db.execute(
                "SELECT * FROM fullgame_best_scores WHERE ps4_id=? AND game_type=? AND stage=?",
                (profile["ps4_id"], game_type, stage)).fetchone()
            improved = self._better(game_type, score, tiebreak, best)
            if improved:
                self.store.db.execute(
                    """INSERT INTO fullgame_best_scores VALUES(?,?,?,?,?,?,?)
                    ON CONFLICT(ps4_id,game_type,stage) DO UPDATE SET score=excluded.score,
                    tiebreak=excluded.tiebreak,detail_json=excluded.detail_json,achieved_at=excluded.achieved_at""",
                    (profile["ps4_id"], game_type, stage, score, tiebreak, detail_json, at))
        return improved

    def _board(self, game_type, stage):
        order = "ASC" if ASCENDING[game_type] else "DESC"
        return [dict(row) for row in self.store.db.execute(
            f"""SELECT b.*,p.username FROM fullgame_best_scores b JOIN profiles p USING(ps4_id)
            WHERE b.game_type=? AND b.stage=?
            ORDER BY b.score {order},b.tiebreak {order},b.achieved_at,b.ps4_id""",
            (game_type, stage))]

    def _rank(self, game_type, stage, ps4_id):
        for index, row in enumerate(self._board(game_type, stage)):
            if row["ps4_id"] == ps4_id:
                return index + 1
        return 0

    @staticmethod
    def _displayable(name):
        return "#" not in name and "!" not in name

    # FullGameNETGCloud solo routes (OnSend @0x4edf40: true + SessionGUID) ----------
    def route_GetActiveStagesServlet(self, request):
        # Sender @0x4e9300; consumers @0x4e77e0 / Kart @0x500080 parse index4 and
        # call UIFullGameStages.InitPanel @0x50a630 (0 => 1, >= count => all).
        fields, _ = self._identity(request, 3)
        game_type = self._lobby_type(fields[2])
        # Preservation choice: every shipped stage is available. The shipped Kart
        # client never reports a finished race (no InfoAddStatistic is built), so
        # a completion-gated rule could never unlock Kart stages 2 and 3.
        return self._reply(fields[0], fields[1], game_type, STAGE_COUNTS[game_type])

    def route_AddStatisticsServlet(self, request):
        # Sender @0x4e89e0: GUID#PS4ID#gameTypeInt#EntryData(InfoAddStatistic).
        fields, profile = self._identity(request, 4, write=True)
        game_type = self._lobby_type(fields[2])
        if game_type != MINIGOLF:
            # KartGameNETGCloud.InfoAddStatistic is never instantiated by the
            # shipped client (no TypeInfo metadata usage); only MiniGolf reports.
            raise ProtocolError("Kart statistics are not emitted by the shipped client")
        try:
            stat = decode_entry_fields(fields[3], MINIGOLF_STATISTIC, max_array_elements=MINIGOLF_HOLES)
        except (ValueError, TypeError) as exc:
            raise ProtocolError("Invalid MiniGolf statistic") from exc
        hits, seconds = stat["hits"], stat["seconds"]
        if (hits is None or seconds is None or len(hits) != len(seconds) or not hits
                or any(not 0 <= x <= 1000 for x in hits) or any(not 0 <= x <= 86_400 for x in seconds)
                or stat["totalHits"] != sum(hits) or stat["totalSecs"] != sum(seconds)
                or stat["totalHits"] <= 0 or not 1 <= stat["stage"] <= STAGE_COUNTS[MINIGOLF]):
            # SetHoleStatistic @0x523d20 sums the per-hole arrays into the totals.
            raise ProtocolError("Inconsistent MiniGolf statistic")
        stage = stat["stage"]
        improved = self._record(profile, MINIGOLF, stage, stat["totalHits"], stat["totalSecs"],
                                {"hits": hits, "seconds": seconds})
        rank = self._rank(MINIGOLF, stage, profile["ps4_id"])
        # Consumer @0x513de0: [4] Boolean new-record flag, [5] hits text,
        # [6] Int32 seconds for FormatStringTime, [7] rank text.
        return self._reply(fields[0], fields[1], MINIGOLF, str(improved).lower(),
                           stat["totalHits"], stat["totalSecs"], rank)

    def route_GetFullGameLeaderboardServlet(self, request):
        # Sender @0x4e9d00: GUID#PS4ID#gameTypeInt#arguments(stage)#Boolean.
        fields, _ = self._identity(request, 5)
        game_type = self._lobby_type(fields[2])
        stage = integer(fields[3], "leaderboard stage", 1, STAGE_COUNTS[game_type])
        if fields[4] not in ("True", "False"):
            raise ProtocolError("Invalid leaderboard panel flag")
        entries = []
        for row in self._board(game_type, stage):
            if len(entries) == LEADERBOARD_ROWS:
                break
            if not self._displayable(row["username"]):
                continue
            if game_type == MINIGOLF:
                entries.append(encode_entry_fields(
                    {"name": row["username"], "hits": row["score"], "time": hhmmss(row["tiebreak"])},
                    MINIGOLF_LEADERBOARD_ENTRY))
        # Kart has no rows: its shipped client never reports a result.
        # Consumers @0x514710/@0x500690: [4] stage label, [6] count, [7..] entries.
        return self._reply(fields[0], fields[1], game_type, fields[3], fields[4],
                           len(entries), *entries)

    def route_GetLastScoreServlet(self, request):
        # Sender @0x4e99b0; consumers @0x514140 / Kart @0x500210 read index4.
        fields, profile = self._identity(request, 3)
        game_type = self._lobby_type(fields[2])
        row = self.store.db.execute(
            "SELECT * FROM fullgame_last_results WHERE ps4_id=? AND game_type=?",
            (profile["ps4_id"], game_type)).fetchone()
        if row is None:
            # Error path @0x4e7be0 retries MAX_TRIES then reopens the main menu.
            raise ProtocolError("No local last score", 404)
        detail = json.loads(row["detail_json"])
        best = self.store.db.execute(
            "SELECT score FROM fullgame_best_scores WHERE ps4_id=? AND game_type=? AND stage=?",
            (profile["ps4_id"], game_type, row["stage"])).fetchone()
        entry = encode_entry_fields({
            "hits": detail["hits"], "totalHits": row["score"], "stage": row["stage"],
            "rank": self._rank(game_type, row["stage"], profile["ps4_id"]),
            "bestHits": best["score"] if best else row["score"],
            "totalTime": hhmmss(row["tiebreak"])}, MINIGOLF_LAST_SCORE)
        return self._reply(fields[0], fields[1], game_type, entry)

    # Multiplayer lobby ---------------------------------------------------------
    def route_GetInviteFriendList(self, request):
        # Sender @0x4e9650; consumer @0x4e7b30 deserializes index3 as
        # FriendListEntries {names[], stages[], guids[]} (count = names.Length).
        fields, profile = self._identity(request, 3)
        game_type = self._lobby_type(fields[2])
        presence = self.presence()
        names, guids = [], []
        for relation in self.store.db.execute(
                "SELECT target,target_platform FROM relations WHERE ps4_id=? AND kind='friend' ORDER BY target,target_platform",
                (profile["ps4_id"],)):
            target = self.store.find_username(relation["target"], relation["target_platform"])
            if not target or not self._displayable(target["username"]):
                continue
            guid = self.store.current_guid(target["ps4_id"])
            # Preservation choice: only friends with a live session are listed,
            # because the GUID is the invite address.
            if guid in presence:
                names.append(target["username"])
                guids.append(guid)
        entry = encode_entry_fields({"names": names, "stages": [STAGE_COUNTS[game_type]] * len(names),
                                     "guids": guids}, FRIEND_LIST)
        return self._reply(fields[0], fields[1], entry)

    def route_GetOpenGamesServlet(self, request):
        # Sender @0x4ea240; consumer @0x4e83c0: index3 count, entries from index4.
        fields, _ = self._identity(request, 3)
        self._lobby_type(fields[2])
        # No full-game multiplayer host exists locally, so no game is ever open.
        return self._reply(fields[0], fields[1], 0)

    def route_CreateGameServlet(self, request):
        # Sender @0x4e8e00: GUID#PS4ID#gameTypeInt#totalPlayers(byte)#EntryData(OpenGameEntry).
        fields, _ = self._identity(request, 5, write=True)
        self._lobby_type(fields[2])
        total_players = integer(fields[3], "player count", 1, 255)
        raw = fields[4].encode("utf-16le", "surrogatepass")
        tokens, offset = [], 0
        try:
            while offset < len(raw):
                if len(tokens) == 1024:
                    raise ValueError("too many tokens")
                value, end = take_value(raw, offset)
                tokens.append((value, raw[offset:end].decode("utf-16le", "surrogatepass")))
                offset = end
        except ValueError as exc:
            raise ProtocolError("Invalid OpenGameEntry stream") from exc
        if len(tokens) < 8:
            raise ProtocolError("Truncated OpenGameEntry stream")
        # OpenGameEntry public order: id_game, ip, port, ... (dump TypeDefIndex 1397).
        # Consumer @0x4e7320: port == -1 returns the creator to the create panel;
        # any other port starts LaunchMultiScene against ip:port. No local host
        # exists, so the client's own entry is echoed with port -1.
        entry = tokens[0][1] + tokens[1][1] + encode_value_texts(["-1"]) + "".join(t[1] for t in tokens[3:])
        return self._reply(fields[0], fields[1], total_players, entry)

    def route_AddToPoolFullGameServlet(self, request):
        # Coroutine @0x4ec1c0: GUID#PS4ID#gameTypeInt#id_game; index3 Boolean.Parse.
        fields, _ = self._identity(request, 4)
        self._lobby_type(fields[2])
        # No open game exists: false is the client's "Game is full" branch.
        return self._reply(fields[0], fields[1], "false")

    def route_CheckIsAvailableToJoinFullGameServlet(self, request):
        # Coroutine @0x4ecd80: index3 Int32 (0 wait, 1 join, 2 refresh list).
        fields, _ = self._identity(request, 4)
        self._lobby_type(fields[2])
        return self._reply(fields[0], fields[1], 2)

    # NETGCloudSpace in-space leaderboards (no generic header) -------------------
    def route_GetLeaderboardServlet(self, request):
        # Coroutine @0x401860 builds GUID#PS4ID#TypeName#stage for types 0/1/2/8/9.
        # Consumer @0x3eb040 splits the whole body by '#', each row by '!'.
        fields, _ = self._identity(request, 4)
        game_type = TYPE_IDS.get(fields[2])
        if game_type is None:
            raise ProtocolError("Leaderboard type has no space consumer")
        stage = integer(fields[3], "leaderboard stage", 1, STAGE_COUNTS[game_type])
        rows = []
        for row in self._board(game_type, stage):
            if len(rows) == LEADERBOARD_ROWS:
                break
            if not self._displayable(row["username"]):
                continue
            if game_type == MINIGOLF:
                rows.append(row["username"] + "!" + str(row["score"]) + "!" + hhmmss(row["tiebreak"]))
            else:  # ChronoRace/KartRace milliseconds; Pinball/Memorion score text.
                rows.append(row["username"] + "!" + str(row["score"]))
        if not rows:
            # The consumer has no empty-board representation: any body without
            # a '!' row raises after clearing the board. Fail explicitly.
            raise ProtocolError("Leaderboard has no local rows", 404)
        return "#".join(rows)

    def route_SetLeaderboardServlet(self, request):
        # Coroutine @0x401100 sends GUID#PS4ID#ChronoRace#value#stage only for
        # ChronoRace; other callers (Kart results @0x50bf00) send an empty
        # plaintext. The response body is never read.
        if request.fields == ("",):
            return "true#"  # Write-free acknowledgement of the empty client request.
        fields, profile = self._identity(request, 5, write=True)
        if fields[2] != "ChronoRace":
            raise ProtocolError("Only ChronoRace submits a space leaderboard value")
        value = integer(fields[3], "ChronoRace milliseconds", 1, 86_400_000)
        stage = integer(fields[4], "ChronoRace stage", 1, STAGE_COUNTS[CHRONORACE])
        self._record(profile, CHRONORACE, stage, value)
        return self._reply(fields[0], fields[1])

    # Memorion ---------------------------------------------------------------------
    def route_MemorionServlet(self, request):
        # UIMemorionGame.SendScore @0x5ac040 / Gather variant @0x691e30:
        # GUID#PS4ID#level#DateTime. Consumers @0x5aba40 / @0x691c30 read
        # [3] level and [4] best level (UIMemorionScore.SetScore).
        fields, profile = self._identity(request, 4, write=True)
        level = integer(fields[2], "Memorion level", 0, 100_000)
        integer(fields[3], "client DateTime ticks", 0, MAX_TICKS)
        self._record(profile, MEMORION, 1, level)
        best = self.store.db.execute(
            "SELECT score FROM fullgame_best_scores WHERE ps4_id=? AND game_type=? AND stage=1",
            (profile["ps4_id"], MEMORION)).fetchone()["score"]
        return self._reply(fields[0], fields[1], level, best)

    def _christmas_2018(self):
        row = self.store.db.execute("SELECT active FROM gathering_events WHERE type_id=4").fetchone()
        return bool(row and row["active"])

    def _completed_scenes(self, ps4_id):
        return {row[0] for row in self.store.db.execute(
            "SELECT psidglobal FROM gathering_scenes WHERE ps4_id=? AND type_id=4", (ps4_id,))}

    def route_Get_BRAINMEMORION(self, request):
        # NETGcloudNPGather.Send_TriggerBRAINMEMORION @0x3f5260: GUID#PS4ID#DateTime.
        # Consumer @0x3f08c0: [3] -1 no challenge, 0 offer, 1 already completed.
        fields, profile = self._identity(request, 3)
        integer(fields[2], "client DateTime ticks", 0, MAX_TICKS)
        allocation = self.store.db.execute("SELECT psidglobal FROM allocations WHERE guid=?",
                                           (fields[0],)).fetchone()
        scene = allocation["psidglobal"] if allocation else None
        if not self._christmas_2018() or scene not in CHRISTMAS_2018_SCENES:
            state = -1
        else:
            state = 1 if scene in self._completed_scenes(profile["ps4_id"]) else 0
        return self._reply(fields[0], fields[1], state)

    def route_Get_GatherChristmasGetSpacesCompleted(self, request):
        # Sender @0x3f1d60 (level from MemorionServlet [3]): GUID#PS4ID#level#DateTime.
        # Consumer @0x3ef0c0: [3] score, [4] index into GatherChristmas2018.aRewardsID
        # ([5,7,9,11,15,25] in leafparklogicprefab); score >= threshold consumes.
        fields, profile = self._identity(request, 4)
        level = integer(fields[2], "Memorion level", 0, 100_000)
        integer(fields[3], "client DateTime ticks", 0, MAX_TICKS)
        if not self._christmas_2018():
            raise ProtocolError("Christmas 2018 gathering is not active", 409)
        last = self.store.db.execute(
            "SELECT score FROM fullgame_last_results WHERE ps4_id=? AND game_type=?",
            (profile["ps4_id"], MEMORION)).fetchone()
        if last is None or last["score"] != level:
            raise ProtocolError("Memorion level was not recorded by MemorionServlet", 409)
        completed = len(self._completed_scenes(profile["ps4_id"]) & set(CHRISTMAS_2018_SCENES))
        return self._reply(fields[0], fields[1], level, min(completed, len(CHRISTMAS_2018_SCENES)))
