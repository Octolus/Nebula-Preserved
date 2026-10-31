"""HTTP minigame score, cooldown, XP and small-event contracts.

Wire layouts come from the shipped client (RVAs in
docs/research/minigame-contracts.md). Leaderboard size, score bounds,
cooldown lengths, NP awards and event state are explicit local preservation
policy: the original server rules are not recoverable from the client.
Importing this module opens no socket and starts no process.
"""
from __future__ import annotations

import math
import re
import time

from public_access import require_actor
from wire import ProtocolError, Request


ROUTES = frozenset((
    "AddScoreArcheryServlet", "GetBestScoreArcheryServlet", "GetLeaderboardArcheryServlet",
    "AddScoreBoatMiniGameServlet", "GetBestScoreBoatMiniGameServlet",
    "GetLeaderboardBoatMiniGameServlet", "GetCooldownServlet", "SetCooldownServlet",
    "AddXPServlet", "Get_GatherArcheryCupid", "Send_ArcheryCupidConsume",
    "XSpacesGamesType0Servlet",
))

# XPNET.TypeXPGame (Send_AddXP @0x44a1f0 sends the numeric value).
XP_GAME_TYPES = {
    0: "MiniGolf", 1: "Pool", 2: "Pinball", 3: "BoardGames", 4: "Bowling",
    5: "ChronoRace", 6: "Archery", 7: "Darts", 8: "FootRace", 9: "Memorion",
    10: "KartRace", 11: "ArcheryCupid", 12: "LightBikeBattle",
}

TICKS_PER_SECOND = 10_000_000
LEADERBOARD_ROWS = 10  # Client builds rows dynamically; no shipped limit exists.
ARCHERY_MAX_SCORE = 100_000  # Local plausibility bound; the reward threshold is 600.
# BoatMiniGame.FormatTime @0x544110 renders nothing at <= 1 s and Int32-parses
# whole seconds; bound to one second .. one day of DateTime ticks.
BOAT_MIN_TICKS = TICKS_PER_SECOND + 1
BOAT_MAX_TICKS = 86_400 * TICKS_PER_SECOND
FOOTRACE_ROUTES = 3       # leafparklogicprefab FootRaceManager.gameRoutes/panelRewards
CUPID_SPAWN_POINTS = 6    # medievalvillagelogicprefab ArcheryCupidManager.aSpawnPoints
CUPID_HEARTS = 4          # ArcheryCupidManager.hearts; 4 opens the rewarded panel
SKL_REWARD_STEPS = 6      # UISKLResult.SetResult: >= 6 completes all 10 reward images
MAX_SECONDS = 31_536_000
MAX_NP_BALANCE = 2_147_483_647

SETTINGS = {
    # name: (minimum, maximum, default)
    "footrace_cooldown_seconds": (0, MAX_SECONDS, 0),
    "skl_cooldown_seconds": (0, MAX_SECONDS, 0),
    "cupid_active": (0, 1, 0),
    "cupid_fires": (1, CUPID_SPAWN_POINTS, CUPID_SPAWN_POINTS),
    # A finished Cupid round only stops on the client when cooldown > 0.
    "cupid_cooldown_seconds": (1, MAX_SECONDS, 86_400),
    **{f"xp_np_{value}": (0, 1_000_000, 0) for value in XP_GAME_TYPES},
}


def _integer(text, label, minimum, maximum):
    if not isinstance(text, str) or not re.fullmatch(r"-?[0-9]+", text):
        raise ProtocolError("Invalid " + label)
    value = int(text)
    if str(value) != text or not minimum <= value <= maximum:
        raise ProtocolError("Invalid " + label)
    return value


def _remaining_ticks(until, now):
    return max(0, int(math.ceil((until - now) * TICKS_PER_SECOND)))


class Minigames:
    ROUTES = ROUTES

    def __init__(self, store, rewards, now=time.time):
        self.store, self.rewards, self.now = store, rewards, now
        store.db.executescript("""
            CREATE TABLE IF NOT EXISTS minigame_settings (
                name TEXT PRIMARY KEY, value INTEGER NOT NULL, updated_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS minigame_best_scores (
                ps4_id TEXT NOT NULL REFERENCES profiles(ps4_id),
                game TEXT NOT NULL CHECK(game IN ('archery','boat')),
                score INTEGER NOT NULL CHECK(score>0), achieved_at REAL NOT NULL,
                PRIMARY KEY(ps4_id,game));
            CREATE INDEX IF NOT EXISTS minigame_best_scores_rank
                ON minigame_best_scores(game,score,achieved_at);
            CREATE TABLE IF NOT EXISTS minigame_footrace (
                ps4_id TEXT PRIMARY KEY REFERENCES profiles(ps4_id),
                last_finish_at REAL NOT NULL, completed INTEGER NOT NULL CHECK(completed IN (0,1)),
                route_index INTEGER, updated_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS minigame_skl_progress (
                ps4_id TEXT PRIMARY KEY REFERENCES profiles(ps4_id),
                progress INTEGER NOT NULL CHECK(progress BETWEEN 0 AND 6),
                last_inserted_at REAL NOT NULL, updated_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS minigame_cupid_progress (
                ps4_id TEXT PRIMARY KEY REFERENCES profiles(ps4_id),
                amount_left INTEGER NOT NULL CHECK(amount_left BETWEEN 0 AND 6),
                hearts INTEGER NOT NULL CHECK(hearts BETWEEN 0 AND 4),
                cooldown_until REAL NOT NULL, updated_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS minigame_xp_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                ps4_id TEXT NOT NULL REFERENCES profiles(ps4_id),
                game_type INTEGER NOT NULL CHECK(game_type BETWEEN 0 AND 12),
                np_awarded INTEGER NOT NULL CHECK(np_awarded>=0), created_at REAL NOT NULL);
        """)
        store.db.commit()

    # ----- operator policy -------------------------------------------------
    def setting(self, name):
        if name not in SETTINGS:
            raise ProtocolError("Unknown minigame setting", 404)
        row = self.store.db.execute("SELECT value FROM minigame_settings WHERE name=?", (name,)).fetchone()
        return row[0] if row else SETTINGS[name][2]

    def settings(self):
        return {name: self.setting(name) for name in sorted(SETTINGS)}

    def configure(self, name, value):
        if name not in SETTINGS:
            raise ProtocolError("Unknown minigame setting", 404)
        minimum, maximum, _default = SETTINGS[name]
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise ProtocolError(f"{name} must be an integer {minimum}..{maximum}")
        with self.store.db:
            self.store.db.execute("""INSERT INTO minigame_settings VALUES(?,?,?)
                ON CONFLICT(name) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at""",
                (name, value, self.now()))
        return self.settings()

    # ----- shared request helpers ------------------------------------------
    def dispatch(self, command: str, request: Request) -> str:
        if command not in ROUTES:
            raise ProtocolError("Unknown minigame route", 501)
        return getattr(self, "route_" + command)(request)

    def _identity(self, request, count, *, writer=False):
        fields = request.require(count)
        profile = self.store.session(fields[0], fields[1])
        if profile["platform"] != request.platform:
            raise ProtocolError("Session platform does not match local account", 403)
        require_actor(profile["ps4_id"])
        if writer and self.store.current_guid(profile["ps4_id"]) != fields[0]:
            raise ProtocolError("Historical session cannot change current account state", 403)
        return fields, profile

    @staticmethod
    def _prefix(fields):
        # Archery/Boat/FootRace/Cupid/SKL senders check true and SessionGUID;
        # the Cupid and NETGCloudSpace senders also require field 2 == PS4ID.
        return "true#" + fields[0] + "#" + fields[1]

    @staticmethod
    def _client_ticks(text):
        # Cupid senders append DateTime.Now.Ticks; it is informational only.
        return _integer(text, "client DateTime ticks", 0, 9_999_999_999_999_999_999)

    # ----- Archery and Boat scores ----------------------------------------
    def _best(self, ps4_id, game):
        row = self.store.db.execute("SELECT score FROM minigame_best_scores WHERE ps4_id=? AND game=?",
                                    (ps4_id, game)).fetchone()
        return row[0] if row else 0

    def _record(self, ps4_id, game, score, better):
        with self.store.atomic():
            current = self._best(ps4_id, game)
            if current == 0 or better(score, current):
                self.store.db.execute("""INSERT INTO minigame_best_scores VALUES(?,?,?,?)
                    ON CONFLICT(ps4_id,game) DO UPDATE SET score=excluded.score,
                    achieved_at=excluded.achieved_at""", (ps4_id, game, score, self.now()))

    def leaderboard(self, game):
        order = "DESC" if game == "archery" else "ASC"
        rows = self.store.db.execute(f"""SELECT p.username,b.score FROM minigame_best_scores b
            JOIN profiles p USING(ps4_id) WHERE b.game=?
            ORDER BY b.score {order},b.achieved_at,b.ps4_id""", (game,))
        result = []
        for username, score in rows:
            # Rows are split on '#' and then '!'; such names cannot be represented.
            if not username or "#" in username or "!" in username:
                continue
            result.append((username, score))
            if len(result) == LEADERBOARD_ROWS:
                break
        return result

    def _leaderboard_reply(self, fields, game):
        # ArcheryGameManager.SetLeaderboardInfo @0x52be80 / BoatMiniGame
        # .SetLeaderboardInfo @0x545170: rows from field 2, each "name!score",
        # rank = index-1. "true#GUID" alone renders an empty board.
        rows = "".join("#" + name + "!" + str(score) for name, score in self.leaderboard(game))
        return "true#" + fields[0] + rows

    def route_AddScoreArcheryServlet(self, request):
        fields, profile = self._identity(request, 3, writer=True)
        score = _integer(fields[2], "archery score", 1, ARCHERY_MAX_SCORE)
        self._record(profile["ps4_id"], "archery", score, lambda new, old: new > old)
        # Get_Send_AddScoreArchery is a shared no-op callback (0x35a740).
        return self._prefix(fields)

    def route_GetBestScoreArcheryServlet(self, request):
        fields, profile = self._identity(request, 2)
        # Get_Get_BestScoreArchery @0x432c30: Int32 field 3; -1 is an error.
        return self._prefix(fields) + "#" + str(self._best(profile["ps4_id"], "archery"))

    def route_GetLeaderboardArcheryServlet(self, request):
        fields, _profile = self._identity(request, 2)
        return self._leaderboard_reply(fields, "archery")

    def route_AddScoreBoatMiniGameServlet(self, request):
        fields, profile = self._identity(request, 3, writer=True)
        ticks = _integer(fields[2], "boat time", BOAT_MIN_TICKS, BOAT_MAX_TICKS)
        self._record(profile["ps4_id"], "boat", ticks, lambda new, old: new < old)
        best = self._best(profile["ps4_id"], "boat")
        rank = 1 + self.store.db.execute(
            "SELECT COUNT(*) FROM minigame_best_scores WHERE game='boat' AND score<?", (best,)).fetchone()[0]
        # Get_Send_AddScoreBoatMiniGame @0x431850: non-empty field 2 activates
        # RankingPosition and field 3 becomes its text.
        return self._prefix(fields) + "#" + str(rank)

    def route_GetBestScoreBoatMiniGameServlet(self, request):
        fields, profile = self._identity(request, 2)
        # @0x4313e0: Int64 ticks in field 3; 0 means no time (FormatTime -> "").
        return self._prefix(fields) + "#" + str(self._best(profile["ps4_id"], "boat"))

    def route_GetLeaderboardBoatMiniGameServlet(self, request):
        fields, _profile = self._identity(request, 2)
        return self._leaderboard_reply(fields, "boat")

    # ----- FootRace -------------------------------------------------------
    def route_GetCooldownServlet(self, request):
        fields, profile = self._identity(request, 3)
        if fields[2] != "FootRace":
            raise ProtocolError("Unsupported cooldown game")
        row = self.store.db.execute("SELECT last_finish_at FROM minigame_footrace WHERE ps4_id=?",
                                    (profile["ps4_id"],)).fetchone()
        remaining = 0
        if row:
            remaining = _remaining_ticks(row[0] + self.setting("footrace_cooldown_seconds"), self.now())
        # Get_InitializeGame @0x56e8a0: Int64 field 3 < 0 opens the race menu;
        # >= 0 starts CoolDownTimer with that many DateTime ticks.
        return self._prefix(fields) + "#" + (str(remaining) if remaining > 0 else "-1")

    def route_SetCooldownServlet(self, request):
        count = len(request.fields)
        if count == 5:
            # Send_FinishGame @0x56f610: GUID#PS4ID#FootRace#routeIndex#true
            fields, profile = self._identity(request, 5, writer=True)
            route_index = _integer(fields[3], "route index", 0, FOOTRACE_ROUTES - 1)
            if fields[4] != "true":
                raise ProtocolError("Invalid race completion flag")
            completed = True
        elif count == 4:
            # FootRaceManager.Update @0x570460 time-out: GUID#PS4ID#FootRace#false
            fields, profile = self._identity(request, 4, writer=True)
            if fields[3] != "false":
                raise ProtocolError("Invalid race completion flag")
            route_index, completed = None, False
        else:
            raise ProtocolError("Invalid field count")
        if fields[2] != "FootRace":
            raise ProtocolError("Unsupported cooldown game")
        trigger = None if route_index is None else str(route_index)
        reward = completed and self.rewards.prepare_optional_claim("SetCooldownServlet", trigger)
        with self.store.atomic():
            self.store.db.execute("""INSERT INTO minigame_footrace VALUES(?,?,?,?,?)
                ON CONFLICT(ps4_id) DO UPDATE SET last_finish_at=excluded.last_finish_at,
                completed=excluded.completed,route_index=excluded.route_index,
                updated_at=excluded.updated_at""",
                (profile["ps4_id"], self.now(), int(completed), route_index, self.now()))
            fresh = bool(reward) and self.rewards.optional_claim(profile, "SetCooldownServlet", trigger)
        # Get_FinishGame @0x56dee0 needs 5 fields: field 3 Boolean (false shows
        # "Time up!"), field 4 Boolean (true shows panelRewards[routeIndex]).
        return self._prefix(fields) + "#" + str(completed).lower() + "#" + str(fresh).lower()

    # ----- XP -------------------------------------------------------------
    def route_AddXPServlet(self, request):
        fields, profile = self._identity(request, 3, writer=True)
        game_type = _integer(fields[2], "XP game type", 0, 12)
        award = self.setting(f"xp_np_{game_type}")
        ps4_id = profile["ps4_id"]
        with self.store.atomic():
            self.store.db.execute("INSERT OR IGNORE INTO shop_wallets(ps4_id) VALUES(?)", (ps4_id,))
            before = self.store.db.execute("SELECT np FROM shop_wallets WHERE ps4_id=?", (ps4_id,)).fetchone()[0]
            award = max(0, min(award, MAX_NP_BALANCE - before))
            event_id = self.store.db.execute(
                "INSERT INTO minigame_xp_events(ps4_id,game_type,np_awarded,created_at) VALUES(?,?,?,?)",
                (ps4_id, game_type, award, self.now())).lastrowid
            if award:
                self.store.db.execute("UPDATE shop_wallets SET np=np+? WHERE ps4_id=?", (award, ps4_id))
                if self.store.db.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='management_wallet_ledger'").fetchone():
                    self.store.db.execute("""INSERT INTO management_wallet_ledger
                        (request_id,actor_id,account_id,currency,delta,before_balance,after_balance,reason,created_at)
                        VALUES(?,?,?,?,?,?,?,?,?)""",
                        ("minigame-xp:" + str(event_id), "system:minigame-xp", ps4_id, "np", award,
                         before, before + award, "AddXPServlet " + XP_GAME_TYPES[game_type], self.now()))
        # Get_GetAddXP @0x449fe0 Int32-parses field 2; > 0 shows "+ N NP".
        return "true#" + fields[0] + "#" + str(award)

    # ----- Archery Cupid (Medieval Village) -------------------------------
    def _cupid_row(self, ps4_id):
        row = self.store.db.execute("SELECT * FROM minigame_cupid_progress WHERE ps4_id=?", (ps4_id,)).fetchone()
        return dict(row) if row else {"ps4_id": ps4_id, "amount_left": 0, "hearts": 0, "cooldown_until": 0.0}

    def _cupid_save(self, row):
        self.store.db.execute("""INSERT INTO minigame_cupid_progress VALUES(?,?,?,?,?)
            ON CONFLICT(ps4_id) DO UPDATE SET amount_left=excluded.amount_left,hearts=excluded.hearts,
            cooldown_until=excluded.cooldown_until,updated_at=excluded.updated_at""",
            (row["ps4_id"], row["amount_left"], row["hearts"], row["cooldown_until"], self.now()))

    def route_Get_GatherArcheryCupid(self, request):
        fields, profile = self._identity(request, 3)
        self._client_ticks(fields[2])
        prefix = self._prefix(fields)
        # Get_ArcheryCupidIsActive @0x529990: active Boolean, cooldown Double
        # seconds, fires Int32, hearts Int32 (4 opens the rewarded panel).
        if not self.setting("cupid_active"):
            return prefix + "#false#0#0#0"
        with self.store.atomic():
            row = self._cupid_row(profile["ps4_id"])
            if row["hearts"] >= CUPID_HEARTS:
                return prefix + "#true#0#0#" + str(CUPID_HEARTS)
            remaining = int(math.ceil(row["cooldown_until"] - self.now()))
            if remaining > 0:
                return prefix + "#true#" + str(remaining) + "#0#" + str(row["hearts"])
            if row["amount_left"] <= 0:
                row["amount_left"] = self.setting("cupid_fires")
                self._cupid_save(row)
        return prefix + "#true#0#" + str(row["amount_left"]) + "#" + str(row["hearts"])

    def route_Send_ArcheryCupidConsume(self, request):
        fields, profile = self._identity(request, 3, writer=True)
        self._client_ticks(fields[2])
        reward = self.rewards.prepare_optional_claim("Send_ArcheryCupidConsume", str(CUPID_HEARTS))
        with self.store.atomic():
            row = self._cupid_row(profile["ps4_id"])
            if (not self.setting("cupid_active") or row["hearts"] >= CUPID_HEARTS
                    or row["cooldown_until"] > self.now() or row["amount_left"] <= 0):
                raise ProtocolError("Archery Cupid round is unavailable", 409)
            row["amount_left"] -= 1
            cooldown = 0
            if row["amount_left"] == 0:
                row["hearts"] += 1
                cooldown = self.setting("cupid_cooldown_seconds")
                row["cooldown_until"] = self.now() + cooldown
            self._cupid_save(row)
            if row["hearts"] == CUPID_HEARTS and cooldown and reward:
                self.rewards.optional_claim(profile, "Send_ArcheryCupidConsume", str(CUPID_HEARTS))
        # Get_ArcheryCupidConsume @0x529780: fires left, hearts, cooldown
        # Double. Only fires == 0 with cooldown > 0 ends the round on the client.
        return (self._prefix(fields) + "#" + str(row["amount_left"]) + "#" + str(row["hearts"])
                + "#" + str(cooldown))

    # ----- SKL goal (Nexus / SKL space) -----------------------------------
    def route_XSpacesGamesType0Servlet(self, request):
        fields, profile = self._identity(request, 3, writer=True)
        if fields[2] != "0":
            raise ProtocolError("Unsupported XSpaces game type")
        cooldown_seconds = self.setting("skl_cooldown_seconds")
        reward = self.rewards.prepare_optional_claim("XSpacesGamesType0Servlet", "0")
        with self.store.atomic():
            row = self.store.db.execute("SELECT * FROM minigame_skl_progress WHERE ps4_id=?",
                                        (profile["ps4_id"],)).fetchone()
            progress, last = (row["progress"], row["last_inserted_at"]) if row else (0, None)
            inserted = (progress < SKL_REWARD_STEPS and
                        (last is None or self.now() >= last + cooldown_seconds))
            if inserted:
                progress, last = progress + 1, self.now()
                self.store.db.execute("""INSERT INTO minigame_skl_progress VALUES(?,?,?,?)
                    ON CONFLICT(ps4_id) DO UPDATE SET progress=excluded.progress,
                    last_inserted_at=excluded.last_inserted_at,updated_at=excluded.updated_at""",
                    (profile["ps4_id"], progress, last, self.now()))
                if progress == SKL_REWARD_STEPS and reward:
                    self.rewards.optional_claim(profile, "XSpacesGamesType0Servlet", "0")
            remaining = 0
            if progress < SKL_REWARD_STEPS and last is not None:
                remaining = _remaining_ticks(last + cooldown_seconds, self.now())
        # Get_SKLMiniGameSuccess @0x3e9550 -> UISKLResult.ShowResult @0x5c26b0:
        # field 4 reward step (Int32), 5 isInserted (Boolean), 6 cooldown in
        # DateTime ticks (Double, divided by 1e7). Integer text is culture-safe.
        return (self._prefix(fields) + "#0#" + str(progress) + "#" + str(inserted).lower()
                + "#" + str(remaining))
