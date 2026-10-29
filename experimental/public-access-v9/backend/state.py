"""Local preservation data. Policies here are replacements, not recovered server rules."""
import json
import math
from contextlib import contextmanager
import os
from pathlib import Path
import sqlite3
import time
import uuid

from wire import PLATFORMS, ProtocolError, json_field
from test_identity import reserved_id, reserved_name, validate_identity, validate_lookup_username
from public_access import require_actor


def canonical_platform(value):
    """Stored/snapshot names are canonical; native HTTP parameters are integers."""
    text = str(value)
    if text in PLATFORMS:
        return text
    for name, numeric in PLATFORMS.items():
        if text == str(numeric):
            return name
    raise ProtocolError("Unsupported relation platform")


# Deliberate local defaults. Field names/types are recovered; original server
# default values are not. Shop balances are explicit local preservation data.
DEFAULT_PREFS = {
    "mood": "0", "status": "", "DisplayOthersName": 1,
    "DisplayOthersStatus": 1, "DisplayOthersMood": 1, "DisplayMyName": 1,
    "DisplayMyStatus": 1, "DisplayMyMood": 1, "MasterVolume": 1.0,
    "Music": 1.0, "Fx": 1.0, "Ambient": 1.0, "InvertYAxis": 0,
    "ProfanityFilter": 1, "ChatFontSize": 20.0,
    "NameColorSelectedIndex_r": 1.0, "NameColorSelectedIndex_g": 1.0,
    "NameColorSelectedIndex_b": 1.0, "spaceTutorialPhase": "0",
    "editorTutorialPhase": "0", "velocityCam": 1.0,
    "notificationLoginFriend": 1,
}
PURCHASE_GROUPS = (
    "cloths", "locomotions", "animations", "companions", "dances", "emotes",
    "gestures", "poses", "personalspaces", "profilePictures", "housings",
    "bundles", "bundlesHousing",
)


class Catalog:
    def __init__(self, protocol_dir: Path):
        self.protocol_dir = protocol_dir
        self.items = {}
        file = protocol_dir / "avatar-asset-catalog.json"
        if file.exists():
            for item in json.loads(file.read_text(encoding="utf-8"))["items"]:
                if (item["gender"] in ("MALE", "FEMALE")
                        and item["category"] != "UNKNOWN"
                        and not item.get("category_conflict")):
                    self.items[(item["item_id"], item["gender"], item["category"])] = item

    def resolve(self, item_id, gender=None, category=None):
        choices = [v for (i, g, c), v in self.items.items()
                   if i == item_id and (gender is None or g == gender)
                   and (category is None or c == category)]
        if not choices:
            raise ProtocolError("Item has no unambiguous shipped wardrobe asset", 404)
        keys = {(x["gender"], x["category"]) for x in choices}
        if len(keys) != 1:
            raise ProtocolError("Item appears in multiple categories; supply gender and category")
        return choices[0]


class PreservationConnection(sqlite3.Connection):
    """Existing grant helpers enlist in an explicit outer atomic group.

    Outside Store.atomic(), standard SQLite context behavior is preserved.
    Schema setup must precede a group because executescript implicitly commits.
    """
    atomic_depth = 0
    atomic_failed = False

    def __exit__(self, exc_type, exc_value, traceback):
        if self.atomic_depth:
            if exc_type is not None:
                self.atomic_failed = True
            return False
        return super().__exit__(exc_type, exc_value, traceback)

    def commit(self):
        if not self.atomic_depth:
            return super().commit()

    def rollback(self):
        if self.atomic_depth:
            self.atomic_failed = True
            return
        return super().rollback()

    def executescript(self, sql_script, /):
        if self.atomic_depth:
            self.atomic_failed = True
            raise RuntimeError("Initialize schema before entering Store.atomic()")
        return super().executescript(sql_script)


class Store:
    def __init__(self, path: Path, *, local_test_identities=False):
        if type(local_test_identities) is not bool:
            raise TypeError("local_test_identities must be a Boolean")
        path.parent.mkdir(parents=True, exist_ok=True)
        self.state_dir = path.parent
        self.local_test_identities = local_test_identities
        self.db = sqlite3.connect(path, factory=PreservationConnection)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS profiles (
                ps4_id TEXT PRIMARY KEY, username TEXT NOT NULL,
                platform TEXT NOT NULL, gender TEXT NOT NULL DEFAULT 'MALE',
                created_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS sessions (
                guid TEXT PRIMARY KEY, ps4_id TEXT NOT NULL REFERENCES profiles,
                created_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS preferences (
                ps4_id TEXT NOT NULL REFERENCES profiles, key TEXT NOT NULL,
                value TEXT NOT NULL, PRIMARY KEY(ps4_id,key));
            CREATE TABLE IF NOT EXISTS entitlements (
                ps4_id TEXT NOT NULL REFERENCES profiles, item_id TEXT NOT NULL,
                gender TEXT NOT NULL, category TEXT NOT NULL, bundle TEXT NOT NULL,
                display_name TEXT NOT NULL, granted_at REAL NOT NULL,
                PRIMARY KEY(ps4_id,item_id,gender,category));
            CREATE TABLE IF NOT EXISTS presets (
                ps4_id TEXT NOT NULL REFERENCES profiles, name TEXT NOT NULL,
                gender TEXT NOT NULL, preset_json TEXT NOT NULL,
                assets_json TEXT NOT NULL, position_json TEXT NOT NULL,
                updated_at REAL NOT NULL, PRIMARY KEY(ps4_id,name,gender));
            CREATE TABLE IF NOT EXISTS profile_state (
                ps4_id TEXT PRIMARY KEY REFERENCES profiles, last_preset TEXT,
                in_wardrobe INTEGER NOT NULL DEFAULT 0,
                online INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS preset_selection (
                ps4_id TEXT NOT NULL REFERENCES profiles,
                gender TEXT NOT NULL, name TEXT NOT NULL,
                PRIMARY KEY(ps4_id,gender));
            CREATE TABLE IF NOT EXISTS relations (
                ps4_id TEXT NOT NULL REFERENCES profiles, target TEXT NOT NULL,
                target_platform TEXT NOT NULL, kind TEXT NOT NULL,
                PRIMARY KEY(ps4_id,target,target_platform,kind));
            CREATE TABLE IF NOT EXISTS allocations (
                guid TEXT PRIMARY KEY REFERENCES sessions,
                instance_id TEXT NOT NULL, psidglobal TEXT NOT NULL,
                ip TEXT NOT NULL, port INTEGER NOT NULL, allocated_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS positions (
                ps4_id TEXT PRIMARY KEY REFERENCES profiles,
                x REAL NOT NULL,y REAL NOT NULL,z REAL NOT NULL,updated_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS friend_events (
                event_id TEXT PRIMARY KEY, operation TEXT NOT NULL,
                actor_ps4_id TEXT NOT NULL REFERENCES profiles,
                other_ps4_id TEXT NOT NULL REFERENCES profiles,
                created_at REAL NOT NULL, processed_at REAL NOT NULL);
        """)
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(entitlements)")}
        if "asset_status" not in columns:
            self.db.execute("ALTER TABLE entitlements ADD COLUMN asset_status INTEGER NOT NULL DEFAULT 1")
        if "item_type" not in columns:
            self.db.execute("ALTER TABLE entitlements ADD COLUMN item_type INTEGER NOT NULL DEFAULT 1")
        state_columns = {row[1] for row in self.db.execute("PRAGMA table_info(profile_state)")}
        for name, declaration in (("wardrobe_instance_id", "TEXT NOT NULL DEFAULT ''"),
                                  ("wardrobe_updated_at", "REAL NOT NULL DEFAULT 0")):
            if name not in state_columns:
                self.db.execute("ALTER TABLE profile_state ADD COLUMN " + name + " " + declaration)
        self.db.execute("INSERT OR IGNORE INTO preset_selection SELECT p.ps4_id,p.gender,p.name FROM presets p JOIN profile_state s USING(ps4_id) WHERE p.name=s.last_preset")
        # Previous handlers stored the numeric native parameter directly. Keep
        # existing relations while exposing one representation to C# readers.
        for platform, numeric in PLATFORMS.items():
            self.db.execute("INSERT OR IGNORE INTO relations SELECT ps4_id,target,?,kind FROM relations WHERE target_platform=?", (platform, str(numeric)))
            self.db.execute("DELETE FROM relations WHERE target_platform=?", (str(numeric),))
        self.db.commit()

    def close(self):
        self.db.close()

    @contextmanager
    def atomic(self):
        """Commit all nested grants/debits/claim markers together or none.

        BEGIN IMMEDIATE serializes the read/recheck/write group across local
        connections. Child helpers retain their normal `with db` API; their
        contexts and explicit commits cannot commit this group early.
        """
        outer = self.db.atomic_depth == 0
        if outer:
            if self.db.in_transaction:
                raise RuntimeError("Commit earlier work before entering Store.atomic()")
            self.db.execute("BEGIN IMMEDIATE")
            self.db.atomic_failed = False
        self.db.atomic_depth += 1
        try:
            yield self.db
            if self.db.atomic_failed:
                raise ProtocolError("Atomic operation was aborted by a nested failure", 409)
        except BaseException:
            self.db.atomic_failed = True
            raise
        finally:
            self.db.atomic_depth -= 1
            if outer:
                try:
                    if self.db.atomic_failed:
                        self.db.rollback()
                    else:
                        try:
                            self.db.commit()
                        except BaseException:
                            self.db.rollback()
                            raise
                finally:
                    self.db.atomic_failed = False

    def account(self, ps4_id, username=None, platform="StandaloneWindows"):
        require_actor(ps4_id)
        if not ps4_id or len(ps4_id) > 128 or "#" in ps4_id:
            raise ProtocolError("Invalid local account identifier")
        username = validate_identity(ps4_id, username, self.local_test_identities)
        normalized_platform = canonical_platform(platform)
        with self.db:
            existing = self.db.execute(
                "SELECT username,platform FROM profiles WHERE ps4_id=?", (ps4_id,)
            ).fetchone()
            if existing is not None and username is not None:
                old_identity = (existing["username"], canonical_platform(existing["platform"]))
                new_identity = (username, normalized_platform)
                if old_identity != new_identity:
                    # Relations use the native username/platform identity rather
                    # than a profile foreign key.  Never guess which account an
                    # ambiguous identity means, and never merge a rename into an
                    # identity already owned by another local profile.
                    identities = {old_identity, new_identity}
                    collision = any(
                        (row["username"], canonical_platform(row["platform"])) in identities
                        for row in self.db.execute(
                            "SELECT username,platform FROM profiles WHERE ps4_id<>? AND username IN (?,?)",
                            (ps4_id, old_identity[0], new_identity[0]),
                        )
                    )
                    if collision:
                        raise ProtocolError("Local username/platform identity is ambiguous", 409)

                    # Preserve every inbound relationship kind, including the
                    # favorite marker paired with a friendship.  INSERT OR
                    # IGNORE only coalesces an already-identical relation row;
                    # there is no additional per-row metadata to discard.
                    self.db.execute(
                        """INSERT OR IGNORE INTO relations(ps4_id,target,target_platform,kind)
                           SELECT ps4_id,?,?,kind FROM relations
                           WHERE target=? AND target_platform=?""",
                        (*new_identity, *old_identity),
                    )
                    self.db.execute(
                        "DELETE FROM relations WHERE target=? AND target_platform=?",
                        old_identity,
                    )
            self.db.execute("INSERT OR IGNORE INTO profiles(ps4_id,username,platform,created_at) VALUES(?,?,?,?)",
                            (ps4_id, username or ps4_id, normalized_platform, time.time()))
            if username is not None:
                self.db.execute("UPDATE profiles SET username=?,platform=? WHERE ps4_id=?",
                                (username, normalized_platform, ps4_id))
            self.db.execute("INSERT OR IGNORE INTO profile_state(ps4_id) VALUES(?)", (ps4_id,))
        profile = dict(self.db.execute("SELECT * FROM profiles WHERE ps4_id=?", (ps4_id,)).fetchone())
        validate_identity(profile["ps4_id"], profile["username"], self.local_test_identities)
        return profile

    def bind_session(self, ps4_id, guid):
        require_actor(ps4_id)
        self.account(ps4_id)
        existing = self.db.execute("SELECT ps4_id FROM sessions WHERE guid=?", (guid,)).fetchone()
        if existing and existing[0] != ps4_id:
            raise ProtocolError("Session identifier is already bound", 409)
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO sessions VALUES(?,?,?)", (guid, ps4_id, time.time()))

    def session(self, guid, ps4_id=None):
        row = self.db.execute("SELECT p.* FROM sessions s JOIN profiles p USING(ps4_id) WHERE s.guid=?", (guid,)).fetchone()
        if not row or (ps4_id is not None and row["ps4_id"] != ps4_id):
            raise ProtocolError("Unknown or mismatched local session", 403)
        profile = dict(row)
        if ps4_id is not None:
            require_actor(profile["ps4_id"])
        validate_identity(profile["ps4_id"], profile["username"], self.local_test_identities)
        return profile

    def find_username(self, username, platform):
        validate_lookup_username(username, self.local_test_identities)
        rows = self.db.execute("SELECT * FROM profiles WHERE username=? AND platform=?", (username, canonical_platform(platform))).fetchall()
        if len(rows) > 1:
            raise ProtocolError("Local username/platform is ambiguous", 409)
        if not rows:
            return None
        profile = dict(rows[0])
        validate_identity(profile["ps4_id"], profile["username"], self.local_test_identities)
        return profile

    def relation_kinds(self, ps4_id, username, platform):
        return {row[0] for row in self.db.execute("SELECT kind FROM relations WHERE ps4_id=? AND target=? AND target_platform=?", (ps4_id, username, canonical_platform(platform)))}

    def _friendship(self, actor_id, other_id, remove=False):
        rows = [self.db.execute("SELECT * FROM profiles WHERE ps4_id=?", (value,)).fetchone() for value in (actor_id, other_id)]
        if actor_id == other_id or not all(rows):
            raise ProtocolError("Friendship requires two distinct local accounts")
        for owner, target in (rows, rows[::-1]):
            key = (owner["ps4_id"], target["username"], canonical_platform(target["platform"]))
            if remove:
                self.db.execute("DELETE FROM relations WHERE ps4_id=? AND target=? AND target_platform=? AND kind IN ('friend','favorite')", key)
            else:
                self.db.execute("INSERT OR IGNORE INTO relations VALUES(?,?,?,'friend')", key)

    def accept_friendship(self, actor_id, other_id):
        """Local persistence policy; callers must correlate request and approval."""
        with self.db:
            self._friendship(actor_id, other_id)

    def remove_friendship(self, actor_id, other_id):
        with self.db:
            self._friendship(actor_id, other_id, remove=True)
            # Record direct HTTP removal as well, so a delayed older Mirror
            # approval file cannot resurrect the removed relationship.
            now = time.time()
            self.db.execute("INSERT INTO friend_events VALUES(?,?,?,?,?,?)", (str(uuid.uuid4()), "remove_friendship", actor_id, other_id, now, now))

    def import_friend_events(self):
        """Apply immutable, correlated Mirror events once, without any sockets.

        Invalid/unsupported files remain unacknowledged. The event receipt and
        both directional relation changes share one SQLite transaction.
        """
        directory = self.state_dir / "friend-events"
        result = {"applied": 0, "seen": 0, "invalid": 0}
        if not directory.is_dir():
            return result
        pending = []
        pending_ids = {}
        for path in sorted(directory.glob("*.json")):
            try:
                if not 0 < path.stat().st_size <= 16384:
                    raise ValueError("Invalid friend event size")
                value = json.loads(path.read_text(encoding="utf-8-sig"))
                supplied_id = value["event_id"]
                event_id = str(uuid.UUID(supplied_id))
                if supplied_id not in (event_id, event_id.replace("-", "")) or path.name != supplied_id + ".json":
                    raise ValueError("Invalid friend event ID")
                operation = value["operation"]
                created_at = value["created_at"]
                if (value["format_version"] != 1 or value["policy"] != "correlated_online_request_v1"
                        or operation not in ("accept_friendship", "remove_friendship")
                        or isinstance(created_at, bool) or not isinstance(created_at, (float, int))
                        or not math.isfinite(created_at) or created_at < 0):
                    raise ValueError("Invalid friend event schema")
                actor, other = value["actor_ps4_id"], value["other_ps4_id"]
                if not isinstance(actor, str) or not isinstance(other, str):
                    raise ValueError("Invalid friend event accounts")
                existing = self.db.execute("SELECT operation,actor_ps4_id,other_ps4_id,created_at FROM friend_events WHERE event_id=?", (event_id,)).fetchone()
                if existing:
                    if tuple(existing) != (operation, actor, other, created_at):
                        raise ValueError("Conflicting friend event ID")
                    result["seen"] += 1
                    continue
                payload = (operation, actor, other, created_at)
                if event_id in pending_ids:
                    if pending_ids[event_id] != payload:
                        raise ValueError("Conflicting pending friend event ID")
                    result["seen"] += 1
                    continue
                pending_ids[event_id] = payload
                pending.append((created_at, operation == "remove_friendship", event_id, operation, actor, other))
                if len(pending) >= 4096:
                    break
            except (OSError, ValueError, TypeError, KeyError, AttributeError, ProtocolError):
                result["invalid"] += 1
        for created_at, remove, event_id, operation, actor, other in sorted(pending):
            try:
                with self.db:
                    latest = self.db.execute("SELECT created_at,operation,event_id FROM friend_events WHERE (actor_ps4_id=? AND other_ps4_id=?) OR (actor_ps4_id=? AND other_ps4_id=?) ORDER BY created_at DESC,(operation='remove_friendship') DESC,event_id DESC LIMIT 1", (actor, other, other, actor)).fetchone()
                    newer = latest is None or (created_at, remove, event_id) > (latest[0], latest[1] == "remove_friendship", latest[2])
                    if newer:
                        self._friendship(actor, other, remove=remove)
                    self.db.execute("INSERT INTO friend_events VALUES(?,?,?,?,?,?)", (event_id, operation, actor, other, created_at, time.time()))
                result["applied"] += 1
            except (ValueError, TypeError, ProtocolError):
                result["invalid"] += 1
        return result

    def instance_files(self, filename):
        """Root fixtures remain compatible; running instances use separate folders."""
        yield self.state_dir / filename
        yield from sorted((self.state_dir / "instances").glob("*/" + filename))

    def instance_document(self, path, list_key, fresh=True):
        try:
            value = json.loads(path.read_text(encoding="utf-8-sig"))
            generation = value["generation"]
            if (value["format_version"] != 1 or isinstance(generation, bool)
                    or not isinstance(generation, (int, float)) or not math.isfinite(generation)
                    or (fresh and not 0 <= time.time() - generation <= 15)
                    or not isinstance(value[list_key], list)):
                return None
            if path.parent != self.state_dir and value.get("instance_id") != path.parent.name:
                return None
            return value
        except (OSError, ValueError, TypeError, KeyError):
            return None

    def current_guid(self, ps4_id):
        row = self.db.execute("SELECT guid FROM sessions WHERE ps4_id=? ORDER BY created_at DESC,guid DESC LIMIT 1", (ps4_id,)).fetchone()
        return row[0] if row else None

    def presence(self):
        """Only fresh instance-authored presence establishes online status."""
        result = {}
        for path in self.instance_files("instance-presence.json"):
            value = self.instance_document(path, "players")
            if value is None:
                continue
            players = {}
            for entry in value["players"]:
                if not isinstance(entry, dict):
                    players = None
                    break
                guid, status = entry.get("guid"), entry.get("status")
                if (not isinstance(guid, str) or len(guid) != 32
                        or any(c not in "0123456789abcdef" for c in guid)
                        or type(status) is not int or status not in (0, 1, 3) or guid in players):
                    players = None
                    break
                session = self.db.execute("SELECT ps4_id FROM sessions WHERE guid=?", (guid,)).fetchone()
                if path.parent != self.state_dir:
                    allocation = self.db.execute("SELECT instance_id,psidglobal FROM allocations WHERE guid=?", (guid,)).fetchone()
                    if not allocation or tuple(allocation) != (value.get("instance_id"), value.get("psidglobal")):
                        continue
                if session and self.current_guid(session[0]) == guid:
                    players[guid] = status
            if players is not None:
                result.update(players)
        return result

    def wardrobe_active(self, ps4_id, guid=None, instance_id=None):
        row = self.db.execute("SELECT in_wardrobe,wardrobe_instance_id,wardrobe_updated_at FROM profile_state WHERE ps4_id=?", (ps4_id,)).fetchone()
        return bool(row and row[0] and 0 <= time.time() - row[2] <= 60
                    and (guid is None or self.current_guid(ps4_id) == guid)
                    and (instance_id is None or row[1] == instance_id))

    def wardrobe_delivery(self, instance_id, psidglobal):
        for path in self.instance_files("instance-avatar-state.json"):
            value = self.instance_document(path, "avatars")
            if (value is None or value.get("instance_id") != instance_id
                    or value.get("psidglobal") != psidglobal or value.get("listening") is not True
                    or value.get("wardrobe_delivery") != "mirror_after_avatar_ready_v1"):
                continue
            seen = set()
            valid = len(value["avatars"]) <= 32
            for avatar in value["avatars"]:
                if not isinstance(avatar, dict) or not isinstance(avatar.get("guid"), str):
                    valid = False
                    break
                guid = avatar["guid"]
                if len(guid) != 32 or any(c not in "0123456789abcdef" for c in guid) or guid in seen:
                    valid = False
                    break
                if (not isinstance(avatar.get("ps4_id"), str) or type(avatar.get("net_id")) is not int
                        or not 0 < avatar["net_id"] <= 4294967295
                        or any(type(avatar.get(k)) is not bool for k in ("connected", "announced", "in_wardrobe"))):
                    valid = False
                    break
                for key, axes in (("position", {"x", "y", "z"}), ("rotation", {"x", "y", "z", "w"}), ("scale", {"x", "y", "z"})):
                    vector = avatar.get(key)
                    if (not isinstance(vector, dict) or set(vector) != axes
                            or any(isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) for n in vector.values())):
                        valid = False
                        break
                seen.add(guid)
            if valid:
                return True
        return False

    def position(self, ps4_id):
        row = self.db.execute("SELECT x,y,z,updated_at FROM positions WHERE ps4_id=?", (ps4_id,)).fetchone()
        result = {"position": dict(zip(("x", "y", "z"), row[:3])) if row else {"x": 0.0, "y": 0.0, "z": 0.0},
                  "updated_at": row[3] if row else 0.0}
        guid = self.current_guid(ps4_id)
        allocation = self.db.execute("SELECT instance_id,psidglobal FROM allocations WHERE guid=?", (guid,)).fetchone()
        if not allocation:
            return result
        for path in self.instance_files("instance-poses.json"):
            value = self.instance_document(path, "poses", fresh=False)
            if value is None or (value.get("instance_id"), value.get("psidglobal")) != tuple(allocation):
                continue
            for pose in value["poses"]:
                if not isinstance(pose, dict) or pose.get("ps4_id") != ps4_id:
                    continue
                position, updated = pose.get("position"), pose.get("updated_at")
                if (not isinstance(position, dict) or set(position) != {"x", "y", "z"}
                        or isinstance(updated, bool) or not isinstance(updated, (int, float))
                        or not math.isfinite(updated) or not result["updated_at"] < updated <= time.time()
                        or any(isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n)
                               or abs(n) > 3.4028234663852886e38 for n in position.values())):
                    continue
                result = {"position": position, "updated_at": updated}
        return result

    def preferences(self, ps4_id):
        value = dict(DEFAULT_PREFS)
        for row in self.db.execute("SELECT key,value FROM preferences WHERE ps4_id=?", (ps4_id,)):
            value[row["key"]] = json.loads(row["value"])
        return value

    def save_preference(self, ps4_id, key, value):
        with self.db:
            self.db.execute("INSERT INTO preferences VALUES(?,?,?) ON CONFLICT(ps4_id,key) DO UPDATE SET value=excluded.value",
                            (ps4_id, key, json_field(value)))

    def grant(self, ps4_id, item, display_name=None, item_type=None):
        # CLI and validated local shop/reward policies call this primitive.
        # Callers group grants with their debit/claim using Store.atomic().
        self.account(ps4_id)
        if item_type is not None and item_type not in range(9):
            raise ProtocolError("Invalid local wardrobe interaction type")
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO entitlements(ps4_id,item_id,gender,category,bundle,display_name,granted_at,item_type) VALUES(?,?,?,?,?,?,?,?)",
                            (ps4_id, item["item_id"], item["gender"], item["category"],
                             item["bundle"], display_name or item["item_id"], time.time(), 1 if item_type is None else item_type))
            if item_type is not None:
                self.db.execute("UPDATE entitlements SET item_type=? WHERE ps4_id=? AND item_id=? AND gender=? AND category=?", (item_type, ps4_id, item["item_id"], item["gender"], item["category"]))
            if display_name is not None:
                self.db.execute("UPDATE entitlements SET display_name=? WHERE ps4_id=? AND item_id=? AND gender=? AND category=?", (display_name, ps4_id, item["item_id"], item["gender"], item["category"]))

    def inventory(self, ps4_id):
        return [dict(row) for row in self.db.execute(
            "SELECT * FROM entitlements WHERE ps4_id=? ORDER BY item_id,gender,category", (ps4_id,))]

    def purchases(self, ps4_id, guid):
        result = {"guid": guid}
        for group in PURCHASE_GROUPS:
            result[group] = []
            result[group + "Name"] = []
        seen = set()
        for row in self.inventory(ps4_id):
            if row["item_id"] not in seen:
                result["cloths"].append(row["item_id"])
                result["clothsName"].append(row["display_name"])
                seen.add(row["item_id"])
        return result

    def save_preset(self, ps4_id, name, gender, preset, assets, position):
        if gender not in ("MALE", "FEMALE"):
            raise ProtocolError("Unsupported avatar gender")
        with self.db:
            self.db.execute("INSERT INTO presets VALUES(?,?,?,?,?,?,?) ON CONFLICT(ps4_id,name,gender) DO UPDATE SET preset_json=excluded.preset_json,assets_json=excluded.assets_json,position_json=excluded.position_json,updated_at=excluded.updated_at",
                            (ps4_id, name, gender, json_field(preset), json_field(assets),
                             json_field(position), time.time()))
            self.db.execute("UPDATE profiles SET gender=? WHERE ps4_id=?", (gender, ps4_id))
            self.db.execute("INSERT INTO preset_selection VALUES(?,?,?) ON CONFLICT(ps4_id,gender) DO UPDATE SET name=excluded.name", (ps4_id, gender, name))

    def preset(self, ps4_id, gender, name=None):
        if name is None:
            row = self.db.execute("SELECT name FROM preset_selection WHERE ps4_id=? AND gender=?", (ps4_id, gender)).fetchone()
            if row:
                name = row[0]
            else:
                latest = self.db.execute("SELECT name FROM presets WHERE ps4_id=? AND gender=? ORDER BY updated_at DESC,name LIMIT 1", (ps4_id, gender)).fetchone()
                name = latest[0] if latest else None
        row = self.db.execute("SELECT * FROM presets WHERE ps4_id=? AND name=? AND gender=?", (ps4_id, name, gender)).fetchone()
        if not row:
            raise ProtocolError("A fully reconstructed avatar preset is not available", 501)
        return {**dict(row), "preset": json.loads(row["preset_json"]),
                "assets": json.loads(row["assets_json"]),
                "position": json.loads(row["position_json"])}

    def export_instance_accounts(self, state_dir):
        """Publish compatible account and relationship files by atomic replace."""
        self.import_friend_events()
        rows = [dict(row) for row in self.db.execute(
            """SELECT s.guid,p.ps4_id,p.username,p.platform,p.gender,s.created_at session_created_at,
            t.wardrobe_instance_id,t.wardrobe_updated_at,q.x,q.y,q.z,q.updated_at position_updated_at
            FROM sessions s JOIN profiles p USING(ps4_id) JOIN profile_state t USING(ps4_id)
            LEFT JOIN positions q USING(ps4_id)
            WHERE NOT EXISTS(SELECT 1 FROM sessions n WHERE n.ps4_id=s.ps4_id AND
              (n.created_at>s.created_at OR (n.created_at=s.created_at AND n.guid>s.guid))) ORDER BY s.guid""")]
        # A normal deployment never republishes reserved identities left by a
        # prior explicit local test run. Enabled mode still requires exact
        # fixed ID/name pairs; malformed rows fail closed instead of leaking.
        allowed_rows = []
        for account in rows:
            if not self.local_test_identities and (reserved_id(account["ps4_id"])
                                                   or reserved_name(account["username"])):
                continue
            validate_identity(account["ps4_id"], account["username"], self.local_test_identities)
            allowed_rows.append(account)
        rows = allowed_rows
        resources = getattr(self, "instance_resources", None)
        if resources is None:
            from resources import ResourceCatalog, ResourceEntitlements
            resources = ResourceEntitlements(self, ResourceCatalog(Path(__file__).resolve().parents[1] / "protocol"))
        for account in rows:
            account["wardrobe_active"] = self.wardrobe_active(account["ps4_id"], account["guid"])
            for axis in ("x", "y", "z"):
                account.pop(axis)
            position = self.position(account["ps4_id"])
            account["position"] = position["position"]
            account["position_updated_at"] = position["updated_at"]
            allocated = self.db.execute("SELECT instance_id FROM allocations WHERE guid=?", (account["guid"],)).fetchone()
            account["allocated_instance_id"] = allocated[0] if allocated else ""
            granted = resources.list(account["ps4_id"])
            account["companion_ids"] = [item["item_id"] for item in granted if item["kind"] == "companions"]
            account["locomotion_ids"] = [item["item_id"] for item in granted if item["kind"] == "locomotions"]
        relations = [dict(row) for row in self.db.execute(
            "SELECT ps4_id,target,target_platform,kind FROM relations WHERE target_platform IN ('PS4','StandaloneWindows') AND kind IN ('friend','favorite','block','silenced') ORDER BY ps4_id,target,target_platform,kind")]
        allowed_relations = []
        for relation in relations:
            owner = self.db.execute(
                "SELECT username FROM profiles WHERE ps4_id=?", (relation["ps4_id"],)).fetchone()
            if owner is None:
                raise ProtocolError("Relation owner profile is missing", 409)
            owner_name = owner[0]
            if not self.local_test_identities and (reserved_id(relation["ps4_id"])
                                                   or reserved_name(owner_name)
                                                   or reserved_name(relation["target"])):
                continue
            validate_identity(relation["ps4_id"], owner_name, self.local_test_identities)
            validate_lookup_username(relation["target"], self.local_test_identities)
            allowed_relations.append(relation)
        relations = allowed_relations
        generation = time.time()
        for filename, key, values in (("instance-accounts.json", "accounts", rows), ("instance-relations.json", "relations", relations)):
            path = state_dir / filename
            self._publish_snapshot(path, json_field({"format_version": 1, "generation": generation, key: values}))

    @staticmethod
    def _publish_snapshot(path, payload):
        """Replace one snapshot despite a short-lived Windows reader share race.

        Mirror readers request FileShare.Delete, but a running older build or a
        transient scanner can still hold the destination without delete share.
        A unique same-directory temporary prevents competing exporters from
        stealing each other's source file. Only Windows sharing/lock errors are
        retried; every other filesystem failure remains visible.
        """
        temporary = path.with_name("." + path.name + "." + uuid.uuid4().hex + ".tmp")
        try:
            with temporary.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            delays = (0.01, 0.02, 0.04, 0.08, 0.16, 0.32)
            for attempt in range(len(delays) + 1):
                try:
                    os.replace(temporary, path)
                    break
                except OSError as exc:
                    if getattr(exc, "winerror", None) not in (5, 32, 33) or attempt == len(delays):
                        raise
                    time.sleep(delays[attempt])
        finally:
            temporary.unlink(missing_ok=True)
