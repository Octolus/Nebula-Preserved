"""Configurable local preservation state for retired gathering/event routes.

Wire layouts come from the shipped client. Event schedules, limits and rewards
are explicit local policy because the original service data is unavailable.
Importing this module opens no socket and starts no process.
"""
from __future__ import annotations

import json
import math
import time

from wire import ProtocolError, Request


TYPE_NAMES = {
    0: "Halloween", 1: "Christmas", 2: "Easter", 3: "Halloween2018",
    4: "Christmas2018", 5: "Halloween2019", 6: "Christmas2019",
    7: "Halloween2020", 8: "Christmas2020",
}

# Christmas 2018's five flags are read directly into these client fields.
# They belong to the retired cross-space challenge; no other PSID is accepted.
CHRISTMAS_2018_SCENES = ("Nexus", "LeafPark", "Dome", "Cube", "Beach")


class Gathering:
    ROUTES = {
        "Get_GatherConsume", "Get_GatherConsumeReward", "Get_GatherMedievalVillage",
        "Get_GatherPhaseGame", "Get_GatherStatus", "Get_npGather",
        "Get_npGatherChristmas", "Get_npGatherProcessItem",
        "Send_GatherInitInSpace", "Send_GatherMedievalVillageConsume",
    }

    def __init__(self, store, catalog, resources, housing, now=time.time):
        self.store, self.catalog = store, catalog
        self.resources, self.housing, self.now = resources, housing, now
        store.db.executescript("""
            CREATE TABLE IF NOT EXISTS gathering_events (
                type_id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE,
                active INTEGER NOT NULL, max_items INTEGER NOT NULL,
                phase INTEGER NOT NULL, cooldown_seconds INTEGER NOT NULL,
                reward_json TEXT, updated_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS gathering_progress (
                ps4_id TEXT NOT NULL REFERENCES profiles,
                type_id INTEGER NOT NULL REFERENCES gathering_events,
                current_items INTEGER NOT NULL DEFAULT 0,
                rewards_earned INTEGER NOT NULL DEFAULT 0,
                spaces_completed INTEGER NOT NULL DEFAULT 0,
                reward_claimed INTEGER NOT NULL DEFAULT 0,
                last_consume_at REAL NOT NULL DEFAULT 0,
                updated_at REAL NOT NULL,
                PRIMARY KEY(ps4_id,type_id));
            CREATE TABLE IF NOT EXISTS gathering_scenes (
                ps4_id TEXT NOT NULL REFERENCES profiles,
                type_id INTEGER NOT NULL REFERENCES gathering_events,
                psidglobal TEXT NOT NULL,
                completed_at REAL NOT NULL,
                PRIMARY KEY(ps4_id,type_id,psidglobal));
            CREATE TABLE IF NOT EXISTS gathering_medieval (
                ps4_id TEXT PRIMARY KEY REFERENCES profiles,
                active INTEGER NOT NULL DEFAULT 0,
                amount_left INTEGER NOT NULL DEFAULT 0,
                cooldown_until REAL NOT NULL DEFAULT 0,
                updated_at REAL NOT NULL);
        """)
        columns = {row[1] for row in store.db.execute("PRAGMA table_info(gathering_progress)")}
        if "rewards_earned" not in columns:
            store.db.execute(
                "ALTER TABLE gathering_progress ADD COLUMN rewards_earned INTEGER NOT NULL DEFAULT 0")
        store.db.commit()

    def dispatch(self, command: str, request: Request) -> str:
        if command not in self.ROUTES:
            raise ProtocolError("Unknown gathering route", 501)
        return getattr(self, "route_" + command)(request)

    @staticmethod
    def _integer(value, name, minimum=0, maximum=2_147_483_647):
        try:
            number = int(value, 10)
        except (TypeError, ValueError) as exc:
            raise ProtocolError("Invalid " + name) from exc
        if str(number) != value or not minimum <= number <= maximum:
            raise ProtocolError("Invalid " + name)
        return number

    def _identity(self, request, count):
        fields = request.require(count)
        profile = self.store.session(fields[0], fields[1])
        return fields, profile

    def _type(self, text):
        value = self._integer(text, "gathering type", 0, 8)
        if value not in TYPE_NAMES:
            raise ProtocolError("Unknown gathering type")
        return value

    @staticmethod
    def _token(value, name, maximum=256):
        if not isinstance(value, str) or not value or len(value) > maximum or "#" in value:
            raise ProtocolError("Invalid " + name)
        return value

    def _consume_identity(self, request, *, reward=False):
        """Parse the sender's type-dependent 3/4-field request variants."""
        fields = request.fields
        if len(fields) not in (3, 4):
            raise ProtocolError("Invalid field count")
        profile = self.store.session(fields[0], fields[1])
        type_id = self._type(fields[2])
        counted = {1, 2, 3, 5, 7}
        short = {4, 6, 8} if reward else {6, 8}
        if type_id in counted:
            if len(fields) != 4:
                raise ProtocolError("Missing client gathering count")
            client_count = self._integer(fields[3], "client gathering count", 0, 1_000_000)
        elif type_id == 4 and not reward:
            if len(fields) != 4:
                raise ProtocolError("Missing Christmas 2018 scene value")
            client_count = self._token(fields[3], "Christmas 2018 PSID")
        elif type_id in short:
            if len(fields) != 3:
                raise ProtocolError("Unexpected gathering request field")
            client_count = None
        else:
            raise ProtocolError("Unsupported gathering consume type", 409)
        return fields, profile, type_id, client_count

    def _event(self, type_id, profile, create_progress=True):
        event = self.store.db.execute(
            "SELECT * FROM gathering_events WHERE type_id=?", (type_id,)).fetchone()
        if not event:
            raise ProtocolError("Gathering event is not locally configured", 404)
        if create_progress:
            with self.store.atomic():
                self.store.db.execute(
                    """INSERT OR IGNORE INTO gathering_progress
                    (ps4_id,type_id,rewards_earned,updated_at) VALUES(?,?,?,?)""",
                    (profile["ps4_id"], type_id, event["phase"], self.now()))
        progress = self.store.db.execute(
            "SELECT * FROM gathering_progress WHERE ps4_id=? AND type_id=?",
            (profile["ps4_id"], type_id)).fetchone()
        return dict(event), dict(progress) if progress else None

    @staticmethod
    def _reply(guid, ps4_id, *values):
        return "true#" + guid + "#" + ps4_id + "#" + "#".join(str(x) for x in values)

    def _active(self, event):
        return bool(event["active"])

    def _cooldown(self, event, progress):
        if not progress["last_consume_at"]:
            return 0
        return max(0, int(math.ceil(
            event["cooldown_seconds"] - (self.now() - progress["last_consume_at"]))))

    def _scene_flags(self, ps4_id, type_id):
        completed = {row[0] for row in self.store.db.execute(
            "SELECT psidglobal FROM gathering_scenes WHERE ps4_id=? AND type_id=?",
            (ps4_id, type_id))}
        return [1 if scene in completed else 0 for scene in CHRISTMAS_2018_SCENES]

    def configure(self, type_id, name, *, active=False, max_items=0, phase=0,
                  cooldown_seconds=0, reward=None):
        if (isinstance(type_id, bool) or type_id not in TYPE_NAMES or not isinstance(active, bool)
                or not isinstance(name, str) or not name or len(name) > 128 or "#" in name):
            raise ProtocolError("Invalid gathering event configuration")
        for value, label, limit in ((max_items, "max items", 1_000_000),
                                    (phase, "initial rewards earned", 1_000_000),
                                    (cooldown_seconds, "cooldown", 31_536_000)):
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= limit:
                raise ProtocolError("Invalid " + label)
        reward_text = None
        if reward is not None:
            reward_text = json.dumps(self._validate_reward(reward), sort_keys=True, separators=(",", ":"))
        collision = self.store.db.execute(
            "SELECT type_id FROM gathering_events WHERE name=? AND type_id<>?", (name, type_id)).fetchone()
        if collision:
            raise ProtocolError("Gathering event name is already configured", 409)
        with self.store.db:
            self.store.db.execute("""INSERT INTO gathering_events VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(type_id) DO UPDATE SET name=excluded.name,active=excluded.active,
                max_items=excluded.max_items,phase=excluded.phase,
                cooldown_seconds=excluded.cooldown_seconds,reward_json=excluded.reward_json,
                updated_at=excluded.updated_at""",
                (type_id, name, int(bool(active)), max_items, phase,
                 cooldown_seconds, reward_text, self.now()))
        return self.event(type_id)

    def event(self, type_id):
        row = self.store.db.execute("SELECT * FROM gathering_events WHERE type_id=?", (type_id,)).fetchone()
        if not row:
            raise ProtocolError("Gathering event is not locally configured", 404)
        value = dict(row)
        value["reward"] = json.loads(value.pop("reward_json")) if value["reward_json"] else None
        value["type_name"] = TYPE_NAMES[type_id]
        value["active"] = bool(value["active"])
        value["initial_rewards_earned"] = value["phase"]
        return value

    def list_events(self):
        return [self.event(row[0]) for row in self.store.db.execute(
            "SELECT type_id FROM gathering_events ORDER BY type_id")]

    @staticmethod
    def _validate_reward(value):
        if not isinstance(value, dict) or set(value) - {"kind", "item_id", "gender", "category", "name"}:
            raise ProtocolError("Invalid gathering reward")
        kind, item_id = value.get("kind"), value.get("item_id")
        if kind not in ("wardrobe", "companion", "locomotion", "housing") or not isinstance(item_id, str) or not item_id or len(item_id) > 256 or "#" in item_id:
            raise ProtocolError("Invalid gathering reward")
        for key in ("gender", "category", "name"):
            if key in value and (not isinstance(value[key], str) or len(value[key]) > 256 or "#" in value[key]):
                raise ProtocolError("Invalid gathering reward metadata")
        return value

    def set_progress(self, ps4_id, type_id, current_items=0, spaces_completed=0,
                     reward_claimed=False, rewards_earned=0):
        if not isinstance(reward_claimed, bool):
            raise ProtocolError("Invalid reward claimed marker")
        self.store.account(ps4_id)
        event, _ = self._event(type_id, {"ps4_id": ps4_id}, False)
        for value, label in ((current_items, "current items"),
                             (spaces_completed, "spaces completed"),
                             (rewards_earned, "rewards earned")):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ProtocolError("Invalid " + label)
        current_items = min(current_items, event["max_items"])
        with self.store.db:
            self.store.db.execute("""INSERT INTO gathering_progress
                (ps4_id,type_id,current_items,rewards_earned,spaces_completed,reward_claimed,last_consume_at,updated_at)
                VALUES(?,?,?,?,?,?,0,?) ON CONFLICT(ps4_id,type_id) DO UPDATE SET
                current_items=excluded.current_items,spaces_completed=excluded.spaces_completed,
                rewards_earned=excluded.rewards_earned,reward_claimed=excluded.reward_claimed,
                updated_at=excluded.updated_at""",
                (ps4_id, type_id, current_items, rewards_earned, spaces_completed,
                 int(bool(reward_claimed)), self.now()))

    def set_scenes(self, ps4_id, scenes):
        self.store.account(ps4_id)
        event, _ = self._event(4, {"ps4_id": ps4_id})
        scenes = tuple(scenes)
        if len(set(scenes)) != len(scenes) or any(scene not in CHRISTMAS_2018_SCENES for scene in scenes):
            raise ProtocolError("Invalid Christmas 2018 scene configuration")
        with self.store.db:
            self.store.db.execute(
                "DELETE FROM gathering_scenes WHERE ps4_id=? AND type_id=4", (ps4_id,))
            self.store.db.executemany(
                "INSERT INTO gathering_scenes VALUES(?,4,?,?)",
                [(ps4_id, scene, self.now()) for scene in scenes])
            self.store.db.execute(
                "UPDATE gathering_progress SET current_items=?,spaces_completed=?,updated_at=? WHERE ps4_id=? AND type_id=4",
                (min(len(scenes), event["max_items"]), len(scenes), self.now(), ps4_id))

    def _grant_reward(self, ps4_id, event):
        if not event["reward_json"]:
            raise ProtocolError("Event has no configured local reward", 409)
        reward = self._validate_reward(json.loads(event["reward_json"]))
        kind, item_id = reward["kind"], reward["item_id"]
        if kind == "wardrobe":
            item = self.catalog.resolve(item_id, reward.get("gender"), reward.get("category"))
            self.store.grant(ps4_id, item, display_name=reward.get("name"))
        elif kind in ("companion", "locomotion"):
            self.resources.grant(ps4_id, kind + "s", item_id, reward.get("name"))
        else:
            self.housing.grant_item(ps4_id, item_id, reward.get("name"))

    def route_Get_npGather(self, request):
        fields, profile = self._identity(request, 4)
        name, client_total = fields[2], self._integer(fields[3], "client gathering total", 0, 1_000_000)
        row = self.store.db.execute("SELECT type_id FROM gathering_events WHERE name=?", (name,)).fetchone()
        if not row:
            raise ProtocolError("Gathering name is not locally configured", 404)
        event, progress = self._event(row[0], profile)
        if client_total != event["max_items"]:
            raise ProtocolError("Client gathering total differs from local configuration", 409)
        if not self._active(event):
            return self._reply(fields[0], fields[1], 0, event["cooldown_seconds"])
        return self._reply(fields[0], fields[1], 1, progress["current_items"], event["max_items"])

    def route_Get_npGatherProcessItem(self, request):
        fields, profile = self._identity(request, 5)
        name, total, type_id = fields[2], self._integer(fields[3], "client gathering total", 0, 1_000_000), self._type(fields[4])
        event, progress = self._event(type_id, profile)
        if name != event["name"] or total != event["max_items"] or not self._active(event):
            raise ProtocolError("Gathering event is inactive or client configuration differs", 409)
        current = min(event["max_items"], progress["current_items"] + 1)
        with self.store.db:
            self.store.db.execute("UPDATE gathering_progress SET current_items=?,updated_at=? WHERE ps4_id=? AND type_id=?",
                                  (current, self.now(), profile["ps4_id"], type_id))
        return self._reply(fields[0], fields[1], name, current, event["max_items"], current)

    def route_Get_GatherStatus(self, request):
        fields, profile = self._identity(request, 3)
        type_id = self._type(fields[2])
        if not self.store.db.execute("SELECT 1 FROM gathering_events WHERE type_id=?", (type_id,)).fetchone():
            # Get_GatherStatus @0x3f0470 returns before touching any UI when
            # field 3 is false: the native "no event running" answer, where a
            # 404 only reached the client's error path. Nothing is written.
            return self._reply(fields[0], fields[1], "false", type_id, 0)
        event, progress = self._event(type_id, profile)
        return self._reply(fields[0], fields[1], str(self._active(event)).lower(), type_id, progress["current_items"])

    def route_Send_GatherInitInSpace(self, request):
        fields, profile = self._identity(request, 4)
        self._token(fields[2], "space identifier")
        type_id = self._type(fields[3]); event, progress = self._event(type_id, profile)
        # Native callback order: type, current gather, rewards earned, cooldown.
        values = [type_id, progress["current_items"], progress["rewards_earned"],
                  self._cooldown(event, progress)]
        if type_id == 4:
            values.extend(self._scene_flags(profile["ps4_id"], type_id))
        return self._reply(fields[0], fields[1], *values)

    def route_Get_GatherPhaseGame(self, request):
        fields, profile = self._identity(request, 3)
        type_id = self._type(fields[2]); event, progress = self._event(type_id, profile)
        # This callback uses a different order from InitInSpace.
        values = [type_id, self._cooldown(event, progress),
                  progress["current_items"], progress["rewards_earned"]]
        if type_id == 4:
            values.extend(self._scene_flags(profile["ps4_id"], type_id))
        return self._reply(fields[0], fields[1], *values)

    def route_Get_GatherConsume(self, request):
        fields, profile, type_id, client_value = self._consume_identity(request)
        event, progress = self._event(type_id, profile)
        if not self._active(event) or self._cooldown(event, progress):
            raise ProtocolError("Gathering event is inactive or cooling down", 409)
        if type_id == 4:
            if client_value not in CHRISTMAS_2018_SCENES:
                raise ProtocolError("PSID is not part of the Christmas 2018 challenge", 409)
            # The shipped sender supplies psidglobal. Its unique key makes a
            # repeated completion idempotent instead of counting one space twice.
            with self.store.atomic():
                self.store.db.execute(
                    "INSERT OR IGNORE INTO gathering_scenes VALUES(?,4,?,?)",
                    (profile["ps4_id"], client_value, self.now()))
                current = self.store.db.execute(
                    "SELECT COUNT(*) FROM gathering_scenes WHERE ps4_id=? AND type_id=4",
                    (profile["ps4_id"],)).fetchone()[0]
                current = min(event["max_items"], current)
                self.store.db.execute(
                    """UPDATE gathering_progress SET current_items=?,spaces_completed=?,updated_at=?
                    WHERE ps4_id=? AND type_id=4""",
                    (current, current, self.now(), profile["ps4_id"]))
            return self._reply(fields[0], fields[1], type_id, current,
                               progress["rewards_earned"])
        if client_value is not None and client_value != progress["current_items"]:
            raise ProtocolError("Client gathering count differs from durable progress", 409)
        # Item triggers call this route when collecting an object; the callback
        # displays the returned count and opens reward collection at its target.
        current = min(event["max_items"], progress["current_items"] + 1)
        with self.store.db:
            self.store.db.execute(
                "UPDATE gathering_progress SET current_items=?,updated_at=? WHERE ps4_id=? AND type_id=?",
                (current, self.now(), profile["ps4_id"], type_id))
        return self._reply(fields[0], fields[1], type_id, current,
                           progress["rewards_earned"])

    def route_Get_GatherConsumeReward(self, request):
        fields, profile, type_id, client_count = self._consume_identity(request, reward=True)
        # Recheck progress under the same write lock as the grant and marker.
        # Existing entitlement helpers enlist in this explicit atomic group.
        with self.store.atomic():
            event, progress = self._event(type_id, profile)
            if client_count is not None and client_count != progress["current_items"]:
                raise ProtocolError("Client gathering count differs from durable progress", 409)
            if not self._active(event) or progress["current_items"] < event["max_items"] or progress["reward_claimed"]:
                raise ProtocolError("Gathering reward is unavailable or already claimed", 409)
            self._grant_reward(profile["ps4_id"], event)
            rewards_earned = progress["rewards_earned"] + 1
            self.store.db.execute("""UPDATE gathering_progress SET current_items=0,
                rewards_earned=?,reward_claimed=1,last_consume_at=?,updated_at=?
                WHERE ps4_id=? AND type_id=?""",
                (rewards_earned, self.now(), self.now(), profile["ps4_id"], type_id))
        return self._reply(fields[0], fields[1], type_id, 0, rewards_earned)

    def route_Get_npGatherChristmas(self, request):
        fields, profile = self._identity(request, 4)
        self._token(fields[2], "space identifier")
        state = self._integer(fields[3], "Christmas state", 0, 1)
        event, progress = self._event(1, profile)
        if not self._active(event):
            return self._reply(fields[0], fields[1], state, 0, 0,
                               event["cooldown_seconds"], progress["current_items"])
        if state == 0:
            return self._reply(fields[0], fields[1], 0, 1, 0, 0,
                               progress["current_items"])
        # The state-1 consumer requires response index5 == 2 and reads the
        # cooldown from index6.
        return self._reply(fields[0], fields[1], 1, 0, 2,
                           self._cooldown(event, progress), progress["current_items"])

    def route_Get_GatherMedievalVillage(self, request):
        fields, profile = self._identity(request, 3)
        self._integer(fields[2], "client DateTime ticks", 0, 9_999_999_999_999_999_999)
        row = self.store.db.execute("SELECT * FROM gathering_medieval WHERE ps4_id=?", (profile["ps4_id"],)).fetchone()
        if not row:
            return self._reply(fields[0], fields[1], 0, 0, 0)
        cooldown = max(0, int(math.ceil(row["cooldown_until"] - self.now())))
        # Consumer690c60 parses bool, Double cooldown seconds, Int32 amount.
        return self._reply(fields[0], fields[1],
                           str(bool(row["active"]) and cooldown == 0).lower(),
                           cooldown, row["amount_left"])

    def route_Send_GatherMedievalVillageConsume(self, request):
        fields, profile = self._identity(request, 3)
        self._integer(fields[2], "client DateTime ticks", 0, 9_999_999_999_999_999_999)
        row = self.store.db.execute("SELECT * FROM gathering_medieval WHERE ps4_id=?", (profile["ps4_id"],)).fetchone()
        if not row or not row["active"] or row["cooldown_until"] > self.now() or row["amount_left"] <= 0:
            raise ProtocolError("Medieval gathering is unavailable", 409)
        remaining = row["amount_left"] - 1
        with self.store.db:
            self.store.db.execute("UPDATE gathering_medieval SET amount_left=?,updated_at=? WHERE ps4_id=?",
                                  (remaining, self.now(), profile["ps4_id"]))
        # Consumer690b10 reads result code, cooldown seconds and popup text.
        # Code5 is the client's completed/cooldown branch.
        return self._reply(fields[0], fields[1], 5 if remaining == 0 else 1,
                           0, "Completed" if remaining == 0 else remaining)

    def set_medieval(self, ps4_id, *, active=False, amount_left=0, cooldown_until=0):
        self.store.account(ps4_id)
        if (not isinstance(active, bool) or isinstance(amount_left, bool)
                or not isinstance(amount_left, int) or not 0 <= amount_left <= 1_000_000
                or isinstance(cooldown_until, bool) or not isinstance(cooldown_until, (int, float))
                or not math.isfinite(cooldown_until) or cooldown_until < 0):
            raise ProtocolError("Invalid Medieval gathering configuration")
        with self.store.db:
            self.store.db.execute("""INSERT INTO gathering_medieval VALUES(?,?,?,?,?)
                ON CONFLICT(ps4_id) DO UPDATE SET active=excluded.active,amount_left=excluded.amount_left,
                cooldown_until=excluded.cooldown_until,updated_at=excluded.updated_at""",
                (ps4_id, int(bool(active)), amount_left, float(cooldown_until), self.now()))

