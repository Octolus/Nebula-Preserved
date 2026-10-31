"""Recovered housing HTTP DTOs with explicit local ownership and persistence.

Catalog availability does not imply ownership. Bindings and grants are local
admin decisions. Importing or calling this module never opens a socket.
"""
import json
import math
from pathlib import Path
import re
import sqlite3
import sys
import time
import uuid

# Housing administration can be the process entry point. Do not depend on the
# HTTP service importing avatar first to make the shared wire codec available.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from avatar_entry_codec import decode_entry_fields
from wire import ProtocolError, json_field
from housing_atomic import AtomicHousingSaves
from public_access import require_actor
from space_shop import SHOP_ID_BY_SPACE


HOUSING_FIELDS = [
    {"name": "psidglobal", "type": "string"},
    *[{"name": name, "type": {"array": kind}} for name, kind in (
        ("aidasset", "string"), ("aidasset_tx", "float"), ("aidasset_ty", "float"),
        ("aidasset_tz", "float"), ("aidasset_r", "float"),
        ("aidassetWall", "string"), ("aidassetWallSlot", "int"),
        ("aidassetCeiling", "string"), ("aidassetCeilingSlot", "int"),
        ("atablename", "string"))],
]
TYPE_TABLES = {0: "HOUSING_WALLHANGING", 1: "HOUSING_CHAIR", 2: "HOUSING_FOOTSTOOL",
               3: "HOUSING_TABLE", 4: "HOUSING_FLOORING", 5: "HOUSING_ORNAMENT",
               6: "HOUSING_LAMP", 7: "HOUSING_LIGHT", 8: "HOUSING_SOFA",
               9: "HOUSING_APPLIANCE", 10: "HOUSING_STORAGE"}

# Recovered client placement rules, not retired-service economics. Every
# canonical shipped prefab has serialized HousingAsset.size 0 or 1, and each
# Register*Asset method converts 0 to 1 before adding it to occupied space.
MAX_PLACEMENT_SPACE = 200

# Case-exact Unity scene names recovered from the shipped scene bundles.  The
# navigator key is also the scene name except for the authored Eyrie scene.
# Keeping this mapping here prevents an administrator typo (or an invented
# alias) from becoming a trusted personal-instance binding.
PERSONAL_SPACE_SCENES = {
    name: ("SorcerersEyrie1" if name == "SorcerersEyrie" else name)
    for name in (
        "Home", "Greenhouse", "Waterfall", "StarCrawlers", "BlueWaveHideout",
        "DressingRoom", "CutteridgeEstate", "TheMoonlightRoom", "LeChalet",
        "LakeApartment", "SereneGarden", "WoodlandClearing", "TheNebulian",
        "SorcerersEyrie", "ZeroDistrictDen", "CampSilverLake", "FlyingDevice",
        "Deadquarters", "HollyridgeEstate", "WinterSnowGlobe", "TokyoApartment",
        "NebuHouse", "WestValleyApartment", "WhisperingHillsMansion",
        "CliffApartment", "TheCrypt", "ForgottenStation", "GreekSummerHouse",
        "MountainHideout", "GingerbreadHouse", "WindMillFarmHouse",
    )
}


def wire_text(value, label):
    if not isinstance(value, str) or not value or len(value) > 256 or any(c in value for c in "#!\x00"):
        raise ProtocolError("Invalid " + label)
    return value


class HousingStore:
    def __init__(self, store, protocol_dir):
        self.store = store
        protocol_dir = Path(protocol_dir)
        document = json.loads((protocol_dir / "http-nonminigame-gap-audit.json").read_text(encoding="utf-8"))
        placement = json.loads((protocol_dir / "housing-placement-contracts.json").read_text(encoding="utf-8"))
        if placement.get("format_version") != 1 or placement.get("max_placement_space") != MAX_PLACEMENT_SPACE:
            raise ProtocolError("Unsupported housing placement evidence", 501)
        placement_items = placement.get("items", {})
        self.catalog = {}
        for row in document["housing_catalog"]:
            item_id, table = row["item_id"], row["table"]
            contract = placement_items.get(item_id)
            suffix = "ResourcesART/Housing/" + table + "/" + item_id + "/FBX/" + item_id + ".prefab"
            if (row.get("grantable") is True and table in TYPE_TABLES.values()
                    and row["bundle"] == "01/" + item_id.lower()
                    and row["asset_path"] in ("Assets/" + suffix, "Assets/ART/" + suffix)
                    and isinstance(contract, dict) and contract.get("table") == table
                    and contract.get("bundle") == row["bundle"]
                    and contract.get("manifest_sha256") == row["manifest_sha256"]
                    and contract.get("behaviour") in ("ground", "floor", "wall", "ceiling")
                    and type(contract.get("placement_cost")) is int
                    and 1 <= contract["placement_cost"] <= MAX_PLACEMENT_SPACE):
                wire_text(item_id, "housing ID")
                if item_id in self.catalog:
                    raise ProtocolError("Duplicate canonical housing ID", 501)
                self.catalog[item_id] = {**row, "behaviour": contract["behaviour"],
                                         "placement_cost": contract["placement_cost"]}
        self.space_names = set(document["personal_space_navigator_names"])
        spaces = placement.get("personal_spaces", {})
        self.space_slots = {name: (value.get("wall_slots"), value.get("ceiling_slots"))
                            for name, value in spaces.items() if isinstance(value, dict)}
        if (self.space_names != set(self.space_slots)
                or self.space_names != set(PERSONAL_SPACE_SCENES)
                or any(type(n) is not int or n < 0 for pair in self.space_slots.values() for n in pair)):
            raise ProtocolError("Personal-space placement metadata is incomplete", 501)
        if not set(SHOP_ID_BY_SPACE) <= self.space_names:
            raise ProtocolError("Personal-space shop evidence names an unknown space", 501)
        store.db.executescript("""
            CREATE TABLE IF NOT EXISTS housing_spaces (
                instance_id TEXT PRIMARY KEY, logical_space_key TEXT NOT NULL,
                psidglobal TEXT NOT NULL, owner_ps4_id TEXT NOT NULL REFERENCES profiles,
                created_at REAL NOT NULL, UNIQUE(owner_ps4_id,logical_space_key));
            CREATE TABLE IF NOT EXISTS housing_entitlements (
                ps4_id TEXT NOT NULL REFERENCES profiles, item_id TEXT NOT NULL,
                display_name TEXT NOT NULL, granted_at REAL NOT NULL,
                PRIMARY KEY(ps4_id,item_id));
            CREATE TABLE IF NOT EXISTS housing_layouts (
                instance_id TEXT PRIMARY KEY REFERENCES housing_spaces,
                layout_json TEXT NOT NULL, updated_at REAL NOT NULL);
        """)
        store.db.commit()
        self.atomic_saves = AtomicHousingSaves(self)

    def bind_space(self, instance_id, psidglobal, owner_ps4_id, logical_space_key=None):
        if not isinstance(instance_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", instance_id):
            raise ProtocolError("Invalid housing instance ID")
        wire_text(psidglobal, "housing scene key")
        logical_space_key = logical_space_key or psidglobal
        if logical_space_key not in self.space_names:
            raise ProtocolError("Unknown shipped personal-space navigator name", 404)
        if psidglobal != PERSONAL_SPACE_SCENES[logical_space_key]:
            raise ProtocolError("Housing scene key does not match the shipped personal-space scene", 409)
        if not self.store.db.execute("SELECT 1 FROM profiles WHERE ps4_id=?", (owner_ps4_id,)).fetchone():
            raise ProtocolError("Housing owner has no local account", 404)
        existing = self.binding(instance_id)
        if existing and (existing["psidglobal"], existing["owner_ps4_id"], existing["logical_space_key"]) != (psidglobal, owner_ps4_id, logical_space_key):
            raise ProtocolError("Housing binding already exists; migration must be explicit", 409)
        try:
            with self.store.db:
                self.store.db.execute("INSERT OR IGNORE INTO housing_spaces VALUES(?,?,?,?,?)", (instance_id, logical_space_key, psidglobal, owner_ps4_id, time.time()))
        except sqlite3.IntegrityError as exc:
            raise ProtocolError("Owner already has this logical personal-space binding", 409) from exc
        return self.binding(instance_id)

    def ensure_binding(self, owner_ps4_id, logical_space_key):
        """Return one stable opaque binding for an authorized owner/space.

        Entitlement is a caller policy. This helper only makes the binding
        concurrency-safe and never exposes an account identity in its ID.
        """
        if logical_space_key not in self.space_names:
            raise ProtocolError("Unknown shipped personal-space navigator name", 404)
        if not self.store.db.execute("SELECT 1 FROM profiles WHERE ps4_id=?", (owner_ps4_id,)).fetchone():
            raise ProtocolError("Housing owner has no local account", 404)
        with self.store.atomic():
            row = self.store.db.execute(
                "SELECT instance_id FROM housing_spaces WHERE owner_ps4_id=? AND logical_space_key=?",
                (owner_ps4_id, logical_space_key)).fetchone()
            if row:
                return self.binding(row[0])
            instance_id = "apt-" + uuid.uuid4().hex
            self.store.db.execute(
                "INSERT INTO housing_spaces VALUES(?,?,?,?,?)",
                (instance_id, logical_space_key, PERSONAL_SPACE_SCENES[logical_space_key],
                 owner_ps4_id, time.time()))
            return self.binding(instance_id)

    def binding(self, instance_id):
        row = self.store.db.execute("SELECT * FROM housing_spaces WHERE instance_id=?", (instance_id,)).fetchone()
        if not row:
            return None
        value = dict(row)
        if (value["logical_space_key"] not in PERSONAL_SPACE_SCENES
                or value["psidglobal"] != PERSONAL_SPACE_SCENES[value["logical_space_key"]]):
            raise ProtocolError("Stored housing binding is not a case-exact shipped scene", 409)
        return value

    def export_bindings(self, state_dir):
        """Publish the exact account-owned personal-instance trust registry.

        This is a read-only database operation.  Mirror consumes the immutable
        snapshot; it must not infer housing ownership from a scene name alone.
        """
        state_dir = Path(state_dir)
        state_dir.mkdir(parents=True, exist_ok=True)
        bindings = []
        for row in self.store.db.execute(
                """SELECT h.instance_id,h.psidglobal,h.owner_ps4_id,h.logical_space_key,
                p.ps4_id AS known_owner FROM housing_spaces h
                LEFT JOIN profiles p ON p.ps4_id=h.owner_ps4_id
                ORDER BY h.instance_id"""):
            value = dict(row)
            if value.pop("known_owner") is None:
                raise ProtocolError("Housing binding owner has no local account", 409)
            if (value["logical_space_key"] not in PERSONAL_SPACE_SCENES
                    or value["psidglobal"] != PERSONAL_SPACE_SCENES[value["logical_space_key"]]):
                raise ProtocolError("Housing binding is not a case-exact shipped scene", 409)
            bindings.append(value)
        snapshot = {"format_version": 1, "generation": time.time(), "bindings": bindings}
        path = state_dir / "instance-housing.json"
        self.store._publish_snapshot(path, json_field(snapshot))
        return path

    def personal_spaces(self, ps4_id):
        return [row[0] for row in self.store.db.execute("SELECT logical_space_key FROM housing_spaces WHERE owner_ps4_id=? ORDER BY logical_space_key", (ps4_id,))]

    def resolve_load(self, ps4_id, requested_key, desired_guid=""):
        if desired_guid:
            allocation = self.store.db.execute(
                """SELECT a.instance_id,s.ps4_id FROM allocations a
                JOIN sessions s USING(guid) WHERE a.guid=?""", (desired_guid,)).fetchone()
            binding = self.binding(allocation["instance_id"]) if allocation else None
            if allocation and not binding and requested_key not in self.space_names:
                # Native InviteToJoin also targets a friend in a shared world
                # (psidglobal and GUID from N2GetPsidglobalAndGuidByUsernamePlatform).
                # No apartment authority applies; the caller pins the friend's
                # exact public instance and validates its presence.
                return None
            if not binding or allocation["ps4_id"] != binding["owner_ps4_id"]:
                raise ProtocolError("Invite target is not the personal-space owner", 403)
            if (self.store.current_guid(binding["owner_ps4_id"]) != desired_guid
                    or desired_guid not in self.store.presence()):
                raise ProtocolError("Invite target has no fresh current-session presence", 503)
            if requested_key not in (binding["logical_space_key"], binding["psidglobal"]):
                raise ProtocolError("Invite target differs from requested personal space", 409)
            return binding
        row = self.store.db.execute("SELECT * FROM housing_spaces WHERE owner_ps4_id=? AND (logical_space_key=? OR psidglobal=?)", (ps4_id, requested_key, requested_key)).fetchall()
        if len(row) > 1:
            raise ProtocolError("Personal-space selection is ambiguous", 409)
        if row:
            return dict(row[0])
        if requested_key in self.space_names:
            raise ProtocolError("Personal space has no explicit local ownership binding", 403)
        return None

    def grant_item(self, ps4_id, item_id, display_name=None):
        if item_id not in self.catalog:
            raise ProtocolError("Unknown or conflicting shipped housing asset", 404)
        label = wire_text(display_name or item_id, "housing display name")
        self.store.account(ps4_id)
        with self.store.db:
            self.store.db.execute("INSERT INTO housing_entitlements VALUES(?,?,?,?) ON CONFLICT(ps4_id,item_id) DO UPDATE SET display_name=excluded.display_name", (ps4_id, item_id, label, time.time()))
        return self.catalog[item_id]

    def inventory(self, ps4_id, table=None):
        values = []
        for row in self.store.db.execute("SELECT * FROM housing_entitlements WHERE ps4_id=? ORDER BY item_id", (ps4_id,)):
            item = self.catalog.get(row["item_id"])
            if item and (table is None or item["table"] == table):
                values.append({**item, "display_name": row["display_name"]})
        return values

    def purchase_fields(self, ps4_id):
        items = self.inventory(ps4_id)
        spaces = self.personal_spaces(ps4_id)
        # Persistency.AssetData pairs asset and name; the navigator and
        # ContainsPurchasedPersonalspace match the name, the shop the asset ID.
        # Home has no shop ID, so its navigator name doubles as the asset.
        return {"housings": [x["item_id"] for x in items], "housingsName": [x["display_name"] for x in items],
                "personalspaces": [SHOP_ID_BY_SPACE.get(key, key) for key in spaces], "personalspacesName": spaces}

    def allocated_binding(self, guid, psidglobal=None, write=False):
        profile = self.store.session(guid)
        require_actor(profile["ps4_id"])
        # Historical sessions remain in the audit tables but cannot authorize
        # either owner or visitor housing requests after a fresh login.
        if self.store.current_guid(profile["ps4_id"]) != guid:
            raise ProtocolError("Historical session cannot access this housing instance", 403)
        allocation = self.store.db.execute("SELECT instance_id,psidglobal FROM allocations WHERE guid=?", (guid,)).fetchone()
        binding = self.binding(allocation[0]) if allocation else None
        if not binding or allocation[1] != binding["psidglobal"] or (psidglobal is not None and psidglobal != binding["psidglobal"]):
            raise ProtocolError("No personal-space allocation matches this housing request", 403)
        if write and (binding["owner_ps4_id"] != profile["ps4_id"] or self.store.current_guid(profile["ps4_id"]) != guid):
            raise ProtocolError("Only the current owning account may save this housing layout", 403)
        return binding

    @staticmethod
    def empty_layout(psidglobal):
        return {field["name"]: psidglobal if field["name"] == "psidglobal" else [] for field in HOUSING_FIELDS}

    def load(self, binding):
        row = self.store.db.execute("SELECT layout_json FROM housing_layouts WHERE instance_id=?", (binding["instance_id"],)).fetchone()
        layout = json.loads(row[0]) if row else self.empty_layout(binding["psidglobal"])
        # Sparse counterpart placeholders are storage only, never item IDs.
        keep = [i for i, item in enumerate(layout["aidasset"]) if item != "null"]
        for key in ("aidasset", "aidasset_tx", "aidasset_ty", "aidasset_tz", "aidasset_r"):
            layout[key] = [layout[key][i] for i in keep]
        ids = layout["aidasset"] + layout["aidassetCeiling"] + layout["aidassetWall"]
        layout["atablename"] = [self.catalog[item]["table"] for item in ids]
        return layout

    def validate_layout(self, binding, layout):
        ground = [item for item in layout["aidasset"] if item != "null"]
        wall, ceiling = layout["aidassetWall"], layout["aidassetCeiling"]
        items = ground + wall + ceiling
        if any(item not in self.catalog for item in items):
            raise ProtocolError("Housing layout contains an unknown catalog item")
        if sum(self.catalog[item]["placement_cost"] for item in items) > MAX_PLACEMENT_SPACE:
            raise ProtocolError("Housing layout exceeds recovered 200-space client budget")
        # SaveAtServer6bdb40 concatenates groundAssets and floorAssets into
        # the same aidasset/transform channel. Slots remain class-specific.
        for items, behaviours in ((ground, {"ground", "floor"}), (wall, {"wall"}), (ceiling, {"ceiling"})):
            if any(item not in self.catalog or self.catalog[item]["behaviour"] not in behaviours for item in items):
                raise ProtocolError("Housing item is stored in the wrong native placement class")
        wall_count, ceiling_count = self.space_slots[binding["logical_space_key"]]
        for slots, count, label in ((layout["aidassetWallSlot"], wall_count, "wall"),
                                    (layout["aidassetCeilingSlot"], ceiling_count, "ceiling")):
            if any(slot >= count for slot in slots):
                raise ProtocolError("Housing layout exceeds shipped " + label + " slot bounds")

    def save_part(self, guid, text, part):
        if part not in ("0", "1"):
            raise ProtocolError("Invalid native housing part number")
        try:
            value = decode_entry_fields(text, HOUSING_FIELDS, max_array_elements=200)
        except (ValueError, TypeError, OverflowError) as exc:
            raise ProtocolError("Malformed housing EntryData") from exc
        binding = self.allocated_binding(guid, value["psidglobal"], write=True)
        keys = ("aidasset", "aidasset_tx", "aidasset_ty", "aidasset_tz", "aidasset_r")
        if any(not isinstance(value[key], list) for key in keys) or any(len(value[key]) != len(value["aidasset"]) for key in keys):
            raise ProtocolError("Housing floor arrays have inconsistent lengths")
        for ids, slots in (("aidassetWall", "aidassetWallSlot"), ("aidassetCeiling", "aidassetCeilingSlot")):
            if (not isinstance(value[ids], list) or not isinstance(value[slots], list)
                    or len(value[ids]) != len(value[slots]) or len(set(value[slots])) != len(value[slots])
                    or any(type(slot) is not int or slot < 0 for slot in value[slots])):
                raise ProtocolError("Invalid housing slot arrays")
        owned = {row["item_id"] for row in self.inventory(binding["owner_ps4_id"])}
        for item in value["aidasset"] + value["aidassetWall"] + value["aidassetCeiling"]:
            if item != "null" and item not in owned:
                raise ProtocolError("Housing layout contains an ungranted item", 403)
        if any(item == "null" for item in value["aidassetWall"] + value["aidassetCeiling"]):
            raise ProtocolError("Housing slot IDs cannot be counterpart padding")
        start, stop = (0, min(100, len(value["aidasset"]))) if part == "0" else (100, len(value["aidasset"]))
        for i in range(len(value["aidasset"])):
            if not start <= i < stop and (value["aidasset"][i] != "null" or any(value[key][i] != 0 for key in keys[1:])):
                raise ProtocolError("Housing counterpart fields differ from native sparse padding")
            for key in keys[1:]:
                scalar = value[key][i]
                if isinstance(scalar, bool) or not isinstance(scalar, (int, float)) or not math.isfinite(scalar):
                    raise ProtocolError("Invalid housing transform")
        if value["atablename"] is not None:
            raise ProtocolError("Native housing save leaves atablename null")
        return self.atomic_saves.submit(guid, binding, value, part)
