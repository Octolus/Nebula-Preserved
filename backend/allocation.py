"""Same-host instance files with one explicitly admitted advertised IPv4.

Address configuration never turns an incomplete core into a ready instance.
"""
import ipaddress
import json
import math
from pathlib import Path
import re
import time

from wire import ProtocolError


# Exact shipped navigator names, combined with the separately reviewed static
# registry exclusions in NebulaWorldState.SceneInventory.ForSpace. A visible
# navigator entry is not ownership; personal instances additionally need the
# fresh backend binding below. Keep the C# readiness policy in agreement.
_PROTOCOL = Path(__file__).resolve().parents[1] / "protocol"
_PERSONAL_NAMES = frozenset(json.loads((_PROTOCOL / "http-nonminigame-gap-audit.json").read_text(
    encoding="utf-8"))["personal_space_navigator_names"])
NONMINI_PERSONAL_SCENES = _PERSONAL_NAMES - {"CampSilverLake", "CutteridgeEstate", "SorcerersEyrie"}
NONMINI_SEMANTIC_PERSONAL_SCENES = (_PERSONAL_NAMES - {"SorcerersEyrie"}) | {"SorcerersEyrie1"}
# Shipped public destinations: PreInitLOAD.NavigatorPublicSpaces plus the Nexus
# Cinema/SKL triggers. SteamPunk ships no s/steampunk scene bundle. Requires the
# rebuilt scene runtime whose NebulaCoreReadiness.publicScenes lists the same set.
NONMINI_PUBLIC_SCENES = frozenset({
    "Nexus", "LeafPark", "Beach", "Cinema", "Bowling", "Dome", "StoneLakeCastle", "Cube",
    "GhostTown", "TheNebulianOpenHouse", "ZeroDistrict", "NebuHouseOpenHouse",
    "WestValleyApartmentOpenHouse", "MedievalVillage", "SKL"})
# Shipped minigame managers (gameTables lengths) per scene; must equal
# NebulaCoreReadiness.SceneTables. Other scenes expose none. Darts in Bowling
# sits under an inactive object in the shipped prefab and is unreachable.
MINIGAME_SCENE_TABLES = {
    "StoneLakeCastle": {"board_tables": 8, "darts_tables": 0, "pool_tables": 0, "bowling_lanes": 0},
    "Bowling": {"board_tables": 0, "darts_tables": 3, "pool_tables": 9, "bowling_lanes": 12},
}
_NO_MINIGAME_TABLES = {"board_tables": 0, "darts_tables": 0, "pool_tables": 0, "bowling_lanes": 0}


def minigame_tables_match(value):
    """Status table counts equal the scene's shipped managers exactly."""
    expected = MINIGAME_SCENE_TABLES.get(value.get("psidglobal"), _NO_MINIGAME_TABLES)
    for key, count in expected.items():
        # Runtimes older than the pool/bowling relay omit those keys.
        actual = value.get(key, 0) if key in ("pool_tables", "bowling_lanes") else value.get(key)
        if type(actual) is not int or actual != count:
            return False
    return True


_MIXED_SEMANTIC_COUNTS = {
    "CampSilverLake": (9, 8, 1),
    "CutteridgeEstate": (5, 4, 1),
    "SorcerersEyrie1": (12, 1, 11),
}


def ipv4_address(value, *, wildcard=False):
    """Canonical IPv4 literal; no DNS, legacy short forms or implicit targets."""
    if not isinstance(value, str):
        raise ValueError("IPv4 address must be a dotted decimal string")
    try:
        address = ipaddress.IPv4Address(value)
    except ipaddress.AddressValueError as exc:
        raise ValueError("Expected a canonical dotted decimal IPv4 address") from exc
    if str(address) != value:
        raise ValueError("IPv4 address must be canonical dotted decimal")
    first = address.packed[0]
    if (first == 0 and not (wildcard and address.is_unspecified)) or first >= 224:
        raise ValueError("Expected a unicast IPv4 address" + (" or 0.0.0.0" if wildcard else ""))
    return str(address)


def network_port(value):
    if type(value) is not int or not 1 <= value <= 65535:
        raise ValueError("Port must be an integer in 1..65535")
    return value


def validation_profile(value):
    if value is not None and value not in ("nexus-core-v1", "nonmini-core-v1", "nonmini-semantic-v1"):
        raise ValueError("Unsupported core test profile")
    return value


class InstanceDirectory:
    def __init__(self, state_dir, advertised_ip="127.0.0.1", core_test_profile=None):
        self.state_dir = Path(state_dir)
        self.path = self.state_dir / "instance-status.json"  # legacy single-instance format
        self.advertised_ip = advertised_ip
        self.core_test_profile = core_test_profile

    @property
    def core_test_profile(self):
        return self._core_test_profile

    @core_test_profile.setter
    def core_test_profile(self, value):
        self._core_test_profile = validation_profile(value)

    @property
    def advertised_ip(self):
        return self._advertised_ip

    @advertised_ip.setter
    def advertised_ip(self, value):
        # Configuration, not a descriptor-supplied redirect. Keep the same
        # object referenced by Service and RewardService when configuring it.
        self._advertised_ip = ipv4_address(value)

    def _nonmini_binding(self, value):
        """A descriptor cannot confer apartment ownership on itself."""
        path = self.state_dir / "instance-housing.json"
        try:
            if path.stat().st_size > 4 * 1024 * 1024:
                return False
            snapshot = json.loads(path.read_text(encoding="utf-8-sig"))
            if (type(snapshot.get("format_version")) is not int or snapshot["format_version"] != 1
                    or isinstance(snapshot.get("generation"), bool)):
                return False
            generated = float(snapshot["generation"])
            if not math.isfinite(generated) or not 0 <= time.time() - generated <= 15:
                return False
            bindings = snapshot["bindings"]
            if not isinstance(bindings, list) or any(not isinstance(row, dict) for row in bindings):
                return False
            matches = [row for row in bindings if row.get("instance_id") == value.get("instance_id")]
            if len(matches) != 1:
                return False
            binding = matches[0]
            owner = binding.get("owner_ps4_id")
            return (value.get("housing_bound") is True and isinstance(owner, str) and bool(owner)
                    and len(owner) <= 256 and not any(c in owner for c in "#\x00")
                    and value.get("housing_owner") == owner
                    and binding.get("psidglobal") == value.get("psidglobal")
                    and binding.get("logical_space_key") in _PERSONAL_NAMES)
        except (OSError, ValueError, TypeError, KeyError):
            return False

    def _nonmini_scene(self, value):
        if value.get("scene_registry_verified") is not True:
            return False
        scene = value.get("psidglobal")
        if scene in NONMINI_PUBLIC_SCENES:
            return value.get("housing_bound") is False and value.get("housing_owner") == ""
        return scene in NONMINI_PERSONAL_SCENES and self._nonmini_binding(value)

    def _semantic_registry(self, value):
        """Require a fresh backend-authored, complete semantic descriptor."""
        path = self.state_dir / "instance-interactions.json"
        try:
            if path.stat().st_size > 32 * 1024 * 1024:
                return False
            snapshot = json.loads(path.read_text(encoding="utf-8-sig"))
            if snapshot.get("format_version") != 1 or isinstance(snapshot.get("generation"), bool):
                return False
            generated = float(snapshot["generation"])
            if not math.isfinite(generated) or not 0 <= time.time() - generated <= 15:
                return False
            matches = [row for row in snapshot.get("instances", []) if isinstance(row, dict) and
                       row.get("instance_id") == value.get("instance_id")]
            if len(matches) != 1:
                return False
            row = matches[0]
            entries = row.get("static_entries")
            if (row.get("scene") != value.get("psidglobal") or row.get("trusted") is not True or
                    row.get("static_profile_available") is not True or not isinstance(row.get("epoch"), str) or
                    not row["epoch"] or not isinstance(entries, list) or
                    not isinstance(row.get("furniture_entries"), list) or not isinstance(row.get("ground_sig"), list)):
                return False
            expected = _MIXED_SEMANTIC_COUNTS.get(row["scene"])
            if expected:
                ordinary = sum(item.get("classification") == "ordinary" for item in entries if isinstance(item, dict))
                deferred = sum(item.get("classification") == "deferred_minigame" for item in entries if isinstance(item, dict))
                if (len(entries), ordinary, deferred) != expected:
                    return False
            return True
        except (OSError, ValueError, TypeError, KeyError):
            return False

    def _semantic_scene(self, value):
        if (value.get("scene_registry_verified") is not True or
                value.get("interaction_bridge_required") is not True or
                value.get("interaction_registry_trusted") is not True or
                not self._semantic_registry(value)):
            return False
        scene = value.get("psidglobal")
        if scene in NONMINI_PUBLIC_SCENES:
            return value.get("housing_bound") is False and value.get("housing_owner") == ""
        return scene in NONMINI_SEMANTIC_PERSONAL_SCENES and self._nonmini_binding(value)

    def _read(self, path, expected_id=None):
        try:
            if path.stat().st_size > 65536:
                return None
            value = json.loads(path.read_text(encoding="utf-8-sig"))
            if (type(value["format_version"]) is not int or value["format_version"] != 1 or
                    value.get("listening") is not True):
                return None
            complete = (value.get("protocol_complete") is True and
                        ("game_ready" not in value or value["game_ready"] is True))
            scope_matches = (self.core_test_profile == "nexus-core-v1" and value.get("psidglobal") == "Nexus"
                             or self.core_test_profile == "nonmini-core-v1" and self._nonmini_scene(value)
                             or self.core_test_profile == "nonmini-semantic-v1" and self._semantic_scene(value))
            core_candidate = (scope_matches and self.core_test_profile is not None and
                              value.get("readiness_scope") == self.core_test_profile and
                              value.get("core_test_eligible") is True and value.get("listener_bound") is True and
                              value.get("game_ready") is False and value.get("protocol_complete") is False and
                              value.get("networking_parity") == "unproven" and
                              minigame_tables_match(value))
            if not (complete or core_candidate):
                return None
            if isinstance(value["heartbeat"], bool):
                return None
            heartbeat = float(value["heartbeat"])
            if not math.isfinite(heartbeat) or not 0 <= time.time() - heartbeat <= 15:
                return None
            if ipv4_address(value["ip"]) != self.advertised_ip:
                return None
            network_port(value["port"])
            if "bind" in value:
                ipv4_address(value["bind"], wildcard=True)
            if (not isinstance(value["instance_id"], str) or
                not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value["instance_id"]) or
                (expected_id is not None and value["instance_id"] != expected_id)):
                return None
            if (not isinstance(value["psidglobal"], str) or not value["psidglobal"] or
                len(value["psidglobal"]) > 128 or any(x in value["psidglobal"] for x in "#\x00/\\")):
                return None
            if (type(value["maxusers"]) is not int or value["maxusers"] != 32 or
                type(value["players"]) is not int or not 0 <= value["players"] <= 32):
                return None
            return value
        except (OSError, ValueError, TypeError, KeyError):
            return None

    def all_ready(self):
        """Fresh complete instances, or a bilateral explicit Nexus test scope.

        Root legacy descriptors remain supported. New instances have separate
        lock/status/presence/avatar files under instances/<instance_id>/ while
        sharing account, entitlement and relationship snapshots at the root.
        A public advertised address does not relocate these files or cause a
        backend connection. Only the configured exact address is admitted.
        """
        candidates = []
        legacy = self._read(self.path)
        if legacy is not None:
            candidates.append(legacy)
        registry = self.state_dir / "instances"
        try:
            for directory in sorted(registry.iterdir()):
                if not directory.is_dir() or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", directory.name):
                    continue
                # Do not follow a state registry junction/symlink outside its
                # explicitly selected directory.
                if directory.resolve().parent != registry.resolve():
                    continue
                value = self._read(directory / "instance-status.json", directory.name)
                if value is not None:
                    candidates.append(value)
        except OSError:
            pass
        # Duplicate IDs or endpoints are ambiguous configuration. Never select
        # one arbitrarily based on filesystem iteration order.
        ids = [x["instance_id"] for x in candidates]
        endpoints = [(x["ip"], x["port"]) for x in candidates]
        return sorted((x for x in candidates if ids.count(x["instance_id"]) == 1 and
                       endpoints.count((x["ip"], x["port"])) == 1),
                      key=lambda x: (x["players"], x["instance_id"]))

    def ready(self, psidglobal=None, instance_id=None, exclude_instance=None):
        for value in self.all_ready():
            if ((psidglobal is None or value["psidglobal"] == psidglobal) and
                (instance_id is None or value["instance_id"] == instance_id) and
                (exclude_instance is None or value["instance_id"] != exclude_instance)):
                return value
        return None

    def require(self, psidglobal=None, instance_id=None, exclude_instance=None):
        instance = self.ready(psidglobal, instance_id, exclude_instance)
        if instance is None:
            raise ProtocolError("No instance eligible for the configured readiness scope is registered", 503)
        return instance
