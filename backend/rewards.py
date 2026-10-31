"""Explicit local rewards, cinema capability and space-liveness contracts.

The wire shapes are recovered. Eligibility, reward definitions and local
entitlement grants are preservation policy configured by an administrator.
Importing this module starts no listener, process or connection.
"""
from __future__ import annotations

import json
import re
import time

from consumables import Consumables
from housing import HousingStore
from resources import ResourceCatalog, ResourceEntitlements
from wire import ProtocolError


ROUTES = {
    "CheckOwnGenericReward", "GenericReward", "RewardClothServlet",
    "RewardConsumeServlet", "SKLPromoServlet", "SKLPromoTriggerServlet",
    "checkRewardAvailableServlet", "CinemaInteractionNPServlet",
    "CheckIfSpaceStillExistServlet", "checkRewardGameServlet",
}
# Optional operator-defined grants behind recovered minigame success replies.
# The minigame module claims them; their own UI shows the reward, so no
# Reward4 notification is queued.  Trigger keys are closed shipped domains.
MINIGAME_CLAIM_ROUTES = {"checkRewardGameServlet", "SetCooldownServlet",
                         "XSpacesGamesType0Servlet", "Send_ArcheryCupidConsume"}
CONFIGURABLE = (ROUTES - {"CheckIfSpaceStillExistServlet", "CheckOwnGenericReward",
                          "SKLPromoTriggerServlet"}) | MINIGAME_CLAIM_ROUTES
CLAIM_ROUTES = {"GenericReward", "RewardClothServlet", "RewardConsumeServlet", "SKLPromoServlet"}
GRANT_KINDS = {"wardrobe", "companions", "locomotions", "housing", "coffee", "oktoberfest", "cinema"}
REWARD_TYPES = {
    "Halloween", "ArcheryBow", "ArcheryCarcaj", "Chess", "CastleSword",
    "PatricksDay2018", "Cube", "CampSilverLake0", "CampSilverLake1",
    "CampSilverLake2", "CampSilverLake3", "GhostWolf",
}
# checkRewardGameCoroutine @0x416a20 reads field 2 only for these typeGame
# names (Utils.RewardType plus FullGameManager ChronoRace); others finish.
REWARD_GAME_TYPES = REWARD_TYPES | {"ChronoRace"}
MINIGAME_TRIGGERS = {
    "SetCooldownServlet": {"0", "1", "2"},        # three shipped FootRace routes
    "XSpacesGamesType0Servlet": {"0"},            # all six SKL reward steps reached
    "Send_ArcheryCupidConsume": {"4"},            # all four Cupid hearts earned
}


def reward_game_key(type_game, stage):
    """Trigger key for checkRewardGameServlet: '<typeGame>:<stage>'."""
    return type_game + ":" + str(stage)


def _valid_minigame_trigger(route, trigger_key):
    if route == "checkRewardGameServlet":
        type_game, separator, stage = trigger_key.partition(":")
        return (separator == ":" and type_game in REWARD_GAME_TYPES
                and re.fullmatch(r"(0|[1-9][0-9]{0,3})", stage) is not None)
    return trigger_key in MINIGAME_TRIGGERS.get(route, ())


def token(value, label, limit=256):
    if not isinstance(value, str) or not value or len(value) > limit or "#" in value or "\x00" in value:
        raise ProtocolError("Invalid " + label)
    return value


def integer(value, label, minimum=0, maximum=2147483647):
    if not isinstance(value, str) or not re.fullmatch(r"-?[0-9]+", value):
        raise ProtocolError("Invalid " + label)
    result = int(value)
    if not minimum <= result <= maximum or value != str(result):
        raise ProtocolError("Invalid " + label)
    return result


class RewardService:
    def __init__(self, store, catalog, instances):
        self.store, self.catalog, self.instances = store, catalog, instances
        self.protocol_dir = catalog.protocol_dir
        store.db.executescript("""
            CREATE TABLE IF NOT EXISTS local_reward_definitions (
                route TEXT NOT NULL, trigger_key TEXT NOT NULL,
                enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
                grant_kind TEXT, item_id TEXT, gender TEXT, category TEXT,
                display_name TEXT, sprite_id INTEGER, units INTEGER, uses INTEGER,
                configured_at REAL NOT NULL, PRIMARY KEY(route,trigger_key));
            CREATE TABLE IF NOT EXISTS local_reward_claims (
                ps4_id TEXT NOT NULL REFERENCES profiles(ps4_id),
                route TEXT NOT NULL, trigger_key TEXT NOT NULL,
                outcome_json TEXT NOT NULL, claimed_at REAL NOT NULL,
                PRIMARY KEY(ps4_id,route,trigger_key));
            CREATE TABLE IF NOT EXISTS cinema_capabilities (
                ps4_id TEXT NOT NULL REFERENCES profiles(ps4_id),
                interaction_type INTEGER NOT NULL CHECK(interaction_type IN (0,1)),
                granted_at REAL NOT NULL, PRIMARY KEY(ps4_id,interaction_type));
        """)
        store.db.commit()
        self._resources = self._housing = self._consumables = None
        self.notifications = None
        promo_path = self.protocol_dir / "skl-promo-catalog.json"
        if not promo_path.exists():
            raise ProtocolError("Missing shipped SKL promo catalog", 500)
        promo_catalog = json.loads(promo_path.read_text(encoding="utf-8"))
        self.skl_promos = {}
        for record in promo_catalog.get("records", []):
            key = str(record.get("promo_id"))
            indices = record.get("valid_sprite_pair_indices")
            if (key in self.skl_promos or not isinstance(indices, list) or not indices
                    or any(type(x) is not int or x < 0 for x in indices)):
                raise ProtocolError("Invalid or ambiguous shipped SKL promo catalog", 500)
            self.skl_promos[key] = frozenset(indices)
        if set(self.skl_promos) != {str(x) for x in promo_catalog.get("promo_ids", [])}:
            raise ProtocolError("Incomplete shipped SKL promo catalog", 500)

    def configure(self, route, trigger_key, enabled=True, grant_kind=None, item_id=None,
                  gender=None, category=None, display_name=None, sprite_id=None,
                  units=1, uses=None):
        if route not in CONFIGURABLE:
            raise ProtocolError("Route is not locally configurable", 404)
        trigger_key = token(str(trigger_key), "reward trigger")
        if route == "RewardClothServlet":
            if trigger_key != "0":
                raise ProtocolError("The shipped cloth sender only emits reward 0")
        elif route == "SKLPromoServlet":
            integer(trigger_key, "numeric reward trigger")
            self._skl_promo(trigger_key)
        elif route in MINIGAME_CLAIM_ROUTES and not _valid_minigame_trigger(route, trigger_key):
            raise ProtocolError("Trigger is outside the shipped minigame reward domain")
        if route == "CinemaInteractionNPServlet":
            integer(trigger_key, "cinema interaction", 0, 1)
            grant_kind, item_id = "cinema", trigger_key
        elif route == "checkRewardAvailableServlet":
            # This route only gates reward UI. It never grants in the reviewed
            # client contract, so a definition carries availability only.
            if grant_kind is not None or item_id is not None:
                raise ProtocolError("Availability checks cannot grant an item")
            if trigger_key not in REWARD_TYPES:
                raise ProtocolError("Unknown shipped reward type")
        elif route in CLAIM_ROUTES or route in MINIGAME_CLAIM_ROUTES:
            if grant_kind not in GRANT_KINDS - {"cinema"} or not item_id:
                raise ProtocolError("Claim route requires an explicit supported entitlement target")
            if route == "RewardClothServlet" and grant_kind != "wardrobe":
                raise ProtocolError("The shipped cloth reward requires a wardrobe target")
            item_id = token(item_id, "reward item")
            if grant_kind == "wardrobe":
                self.catalog.resolve(item_id, gender, category)
            elif grant_kind in ("companions", "locomotions"):
                ResourceCatalog(self.protocol_dir).resolve(grant_kind, item_id)
            elif grant_kind == "housing":
                if item_id not in self.housing.catalog:
                    raise ProtocolError("Unknown shipped housing reward", 404)
            elif grant_kind in ("coffee", "oktoberfest"):
                if item_id != grant_kind or type(units) is not int or units <= 0 or type(uses) is not int or uses <= 0:
                    raise ProtocolError("Consumable reward requires matching kind, positive units and uses")
        if sprite_id is not None and (type(sprite_id) is not int or not 0 <= sprite_id <= 2147483647):
            raise ProtocolError("Invalid local promo sprite")
        if route == "SKLPromoServlet" and sprite_id is None:
            raise ProtocolError("SKL promo consume requires an explicit sprite ID")
        if route == "SKLPromoServlet" and sprite_id not in self._skl_promo(trigger_key):
            raise ProtocolError("Promo sprite pair is not present in the shipped trigger")
        for value, label in ((gender, "gender"), (category, "category"), (display_name, "display name")):
            if value is not None:
                token(value, label, 1024)
        with self.store.db:
            self.store.db.execute("""INSERT INTO local_reward_definitions
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(route,trigger_key) DO UPDATE SET
                enabled=excluded.enabled,grant_kind=excluded.grant_kind,item_id=excluded.item_id,
                gender=excluded.gender,category=excluded.category,display_name=excluded.display_name,
                sprite_id=excluded.sprite_id,units=excluded.units,uses=excluded.uses,
                configured_at=excluded.configured_at""",
                (route, trigger_key, bool(enabled), grant_kind, item_id, gender, category,
                 display_name, sprite_id, units, uses, time.time()))
        return self.definition(route, trigger_key)

    def definition(self, route, trigger_key):
        row = self.store.db.execute("SELECT * FROM local_reward_definitions WHERE route=? AND trigger_key=?",
                                    (route, str(trigger_key))).fetchone()
        return dict(row) if row else None

    @property
    def resources(self):
        if self._resources is None:
            self._resources = ResourceEntitlements(self.store, ResourceCatalog(self.protocol_dir))
        return self._resources

    @property
    def housing(self):
        if self._housing is None:
            self._housing = HousingStore(self.store, self.protocol_dir)
        return self._housing

    @property
    def consumables(self):
        if self._consumables is None:
            self._consumables = Consumables(self.store)
        return self._consumables

    def _skl_promo(self, trigger_key):
        value = self.skl_promos.get(str(trigger_key))
        if value is None:
            raise ProtocolError("Unknown shipped SKL promo trigger", 404)
        return value

    @staticmethod
    def _platform_session(profile, request):
        if profile["platform"] != request.platform:
            raise ProtocolError("Session platform does not match local account", 403)
        return profile

    def _required(self, route, trigger_key):
        value = self.definition(route, trigger_key)
        if value is None or not value["enabled"]:
            raise ProtocolError("No enabled local reward definition", 404)
        if route == "RewardClothServlet" and (str(trigger_key) != "0" or value["grant_kind"] != "wardrobe"):
            raise ProtocolError("Stored cloth reward is outside the shipped contract", 500)
        if route == "SKLPromoServlet" and value["sprite_id"] not in self._skl_promo(trigger_key):
            raise ProtocolError("Stored promo sprite is outside the shipped trigger", 500)
        if route == "checkRewardAvailableServlet" and str(trigger_key) not in REWARD_TYPES:
            raise ProtocolError("Stored reward type is outside the shipped enum", 500)
        if route in MINIGAME_CLAIM_ROUTES and not _valid_minigame_trigger(route, str(trigger_key)):
            raise ProtocolError("Stored minigame reward is outside the shipped domain", 500)
        return value

    def _claimed(self, ps4_id, route, trigger_key):
        return self.store.db.execute("SELECT outcome_json FROM local_reward_claims WHERE ps4_id=? AND route=? AND trigger_key=?",
                                     (ps4_id, route, str(trigger_key))).fetchone()

    def _grant(self, profile, definition):
        kind, item_id = definition["grant_kind"], definition["item_id"]
        if kind == "wardrobe":
            item = self.catalog.resolve(item_id, definition["gender"], definition["category"])
            self.store.grant(profile["ps4_id"], item, definition["display_name"])
        elif kind in ("companions", "locomotions"):
            self.resources.grant(profile["ps4_id"], kind, item_id, definition["display_name"])
        elif kind == "housing":
            self.housing.grant_item(profile["ps4_id"], item_id, definition["display_name"])
        elif kind in ("coffee", "oktoberfest"):
            self.consumables.grant(profile["ps4_id"], kind, definition["units"], definition["uses"])
        elif kind == "cinema":
            with self.store.db:
                self.store.db.execute("INSERT OR IGNORE INTO cinema_capabilities VALUES(?,?,?)",
                                      (profile["ps4_id"], int(item_id), time.time()))
        else:
            raise ProtocolError("Reward definition has no validated grant target", 500)
        return {"grant_kind": kind, "item_id": item_id}

    def _prepare_grant(self, definition):
        """Create lazy helper schemas before entering Store.atomic()."""
        kind = definition["grant_kind"]
        if kind in ("companions", "locomotions"):
            self.resources
        elif kind == "housing":
            self.housing
        elif kind in ("coffee", "oktoberfest"):
            self.consumables

    def _after_grant(self, _profile, _definition, _outcome):
        """Fault-injection seam used to prove grant/claim crash atomicity."""

    def _claim(self, profile, route, trigger_key):
        definition = self._required(route, trigger_key)
        self._prepare_grant(definition)
        prepared_kind = definition["grant_kind"]
        with self.store.atomic():
            # BEGIN IMMEDIATE serializes this recheck with every local writer.
            # Grant helpers enlist in the outer group, so neither entitlement
            # nor marker can survive alone after an exception or process crash.
            definition = self._required(route, trigger_key)
            if definition["grant_kind"] != prepared_kind:
                raise ProtocolError("Reward definition changed; retry claim", 409)
            existing = self._claimed(profile["ps4_id"], route, trigger_key)
            if existing:
                return False, json.loads(existing[0]), definition
            outcome = self._grant(profile, definition)
            self._after_grant(profile, definition, outcome)
            self.store.db.execute("INSERT INTO local_reward_claims VALUES(?,?,?,?,?)",
                                  (profile["ps4_id"], route, str(trigger_key),
                                   json.dumps(outcome, separators=(",", ":")), time.time()))
            if self.notifications is not None and route in CLAIM_ROUTES:
                self.notifications.enqueue_reward(profile["ps4_id"], "reward:" + route + ":" + str(trigger_key))
        return True, outcome, definition

    def prepare_optional_claim(self, route, trigger_key):
        """Outside Store.atomic(): True when an enabled minigame grant exists."""
        if route not in MINIGAME_CLAIM_ROUTES:
            raise ProtocolError("Not a minigame reward route", 500)
        definition = self.definition(route, trigger_key)
        if definition is None or not definition["enabled"]:
            return False
        self._prepare_grant(definition)
        return True

    def optional_claim(self, profile, route, trigger_key):
        """Claim a configured minigame grant once; True only for a fresh grant.

        May run inside the caller's Store.atomic() so the minigame state and the
        entitlement/claim marker commit together. Unconfigured keys grant nothing.
        """
        definition = self.definition(route, trigger_key)
        if definition is None or not definition["enabled"]:
            return False
        fresh, _outcome, _definition = self._claim(profile, route, trigger_key)
        return fresh

    def dispatch(self, command, request):
        if command not in ROUTES:
            raise ProtocolError("Reward route is not reconstructed", 501)
        if command == "checkRewardGameServlet":
            # checkRewardGameCoroutine @0x416a20: GUID#PS4ID#typeGame#stage ->
            # true#GUID#alreadyOwned. false shows the game's reward popup, true
            # (or an unknown name) shows nothing. Missing/disabled definitions
            # return true: suppress without a claim marker or fake grant.
            guid, ps4_id, type_game, stage = request.require(4)
            profile = self._platform_session(self.store.session(guid, ps4_id), request)
            token(type_game, "reward game type", 64)
            key = reward_game_key(type_game, integer(stage, "reward game stage", 0, 9999))
            if not _valid_minigame_trigger(command, key):
                return "true#" + guid + "#true"
            fresh = self.prepare_optional_claim(command, key) and self.optional_claim(profile, command, key)
            return "true#" + guid + "#" + str(not fresh).lower()
        if command == "CheckIfSpaceStillExistServlet":
            guid, ps4_id, instance_id = request.require(3)
            profile = self._platform_session(self.store.session(guid, ps4_id), request)
            token(instance_id, "space instance")
            allocation = self.store.db.execute("SELECT instance_id,psidglobal FROM allocations WHERE guid=?", (guid,)).fetchone()
            exists = bool(allocation and allocation[0] == instance_id and
                          self.instances.ready(psidglobal=allocation[1], instance_id=instance_id) is not None)
            return "true#" + str(exists).lower()
        guid, ps4_id, trigger_key = request.require(3)
        profile = self._platform_session(self.store.session(guid, ps4_id), request)
        token(trigger_key, "reward trigger")
        if command == "CinemaInteractionNPServlet":
            integer(trigger_key, "cinema interaction", 0, 1)
            self._claim(profile, command, trigger_key)
            return "true#" + guid + "#" + ps4_id + "#true"
        if command == "CheckOwnGenericReward":
            definition = self.definition("GenericReward", trigger_key)
            if definition is None or not definition["enabled"]:
                # Authored preservation policy: the native field-3 true branch
                # leaves this prompt hidden.  Do not create a claim marker or
                # pretend an entitlement was granted; GenericReward itself
                # still passes through _claim/_required and fails closed.
                return "false#" + guid + "#" + ps4_id + "#true"
            owned = self._claimed(ps4_id, "GenericReward", trigger_key) is not None
            return "false#" + guid + "#" + ps4_id + "#" + str(owned).lower()
        if command == "SKLPromoTriggerServlet":
            definition = self.definition("SKLPromoServlet", trigger_key)
            if definition is None or not definition["enabled"]:
                # Get_SKLPromoCheckToSetAvailable @0x3e96a0: field 3 true hides
                # the trigger, false calls SKLPromoTrigger.Show. Same silent
                # suppression as CheckOwnGenericReward; no claim is written.
                self._skl_promo(trigger_key)
                return "true#" + guid + "#" + ps4_id + "#true"
            self._required("SKLPromoServlet", trigger_key)
            consumed = self._claimed(ps4_id, "SKLPromoServlet", trigger_key) is not None
            return "true#" + guid + "#" + ps4_id + "#" + str(consumed).lower()
        if command == "checkRewardAvailableServlet":
            if trigger_key not in REWARD_TYPES:
                raise ProtocolError("Unknown shipped reward type")
            available = self.definition(command, trigger_key)
            return "true#" + guid + "#" + str(bool(available and available["enabled"])).lower()
        fresh, _outcome, definition = self._claim(profile, command, trigger_key)
        if command in ("GenericReward",):
            return "false#" + guid + "#" + ps4_id + "#" + str(fresh).lower()
        if command == "RewardClothServlet":
            integer(trigger_key, "cloth reward")
            return "false#" + guid + "#" + str(fresh).lower()
        if command == "SKLPromoServlet":
            return "true#" + guid + "#" + ps4_id + "#" + str(definition["sprite_id"])
        # RewardConsume has no payload beyond its generic validated identity prefix.
        return "true#" + guid + "#" + ps4_id

    def claims(self, ps4_id=None):
        sql = "SELECT * FROM local_reward_claims"
        args = ()
        if ps4_id is not None:
            sql, args = sql + " WHERE ps4_id=?", (ps4_id,)
        return [dict(x) for x in self.store.db.execute(sql + " ORDER BY ps4_id,route,trigger_key", args)]
