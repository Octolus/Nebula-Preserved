"""Backend-owned desired instance state; never launches or connects to a process."""
import json
from pathlib import Path
import re
import time
import uuid

from allocation import NONMINI_PUBLIC_SCENES
from wire import ProtocolError, json_field


PENDING_RENEW_SECONDS = 15.0
ALLOCATED_GRACE_SECONDS = 30.0
OPAQUE_PERSONAL_ID = re.compile(r"apt-[0-9a-f]{32}\Z")


class ManagedInstanceLifecycle:
    """Durable demand authority for an explicitly managed deployment.

    Fresh instance-status descriptors remain the sole readiness authority. This
    class publishes intent for a separate supervisor and never trusts its
    runtime/lease journal when allocating a client.
    """

    def __init__(self, store, housing, instances, readiness_profile):
        if readiness_profile != "nonmini-semantic-v1":
            raise ValueError("Managed instances require nonmini-semantic-v1 readiness on both services")
        self.store = store
        self.housing = housing
        self.instances = instances
        self.readiness_profile = readiness_profile
        self.store.db.executescript("""
            CREATE TABLE IF NOT EXISTS managed_lifecycle_config (
                key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS managed_account_policy (
                ps4_id TEXT PRIMARY KEY REFERENCES profiles,
                default_home INTEGER NOT NULL CHECK(default_home IN (0,1)),
                policy_source TEXT NOT NULL, created_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS managed_instances (
                instance_id TEXT PRIMARY KEY,
                kind TEXT NOT NULL CHECK(kind IN ('public','personal')),
                psidglobal TEXT NOT NULL,
                owner_ps4_id TEXT REFERENCES profiles,
                logical_space_key TEXT,
                desired_state TEXT NOT NULL CHECK(desired_state IN ('running','stopped')),
                adopted_existing INTEGER NOT NULL CHECK(adopted_existing IN (0,1)),
                created_at REAL NOT NULL, updated_at REAL NOT NULL,
                CHECK((kind='public' AND owner_ps4_id IS NULL AND logical_space_key IS NULL)
                   OR (kind='personal' AND owner_ps4_id IS NOT NULL AND logical_space_key IS NOT NULL)),
                UNIQUE(owner_ps4_id,logical_space_key));
            CREATE TABLE IF NOT EXISTS instance_demands (
                requester_guid TEXT PRIMARY KEY REFERENCES sessions,
                instance_id TEXT NOT NULL REFERENCES managed_instances,
                psidglobal TEXT NOT NULL, requested_key TEXT NOT NULL,
                desired_owner_guid TEXT NOT NULL DEFAULT '',
                state TEXT NOT NULL CHECK(state IN ('pending','allocated','cancelled')),
                reserved_at REAL NOT NULL, expires_at REAL NOT NULL, updated_at REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS instance_demands_instance_state
                ON instance_demands(instance_id,state,expires_at);
        """)
        with self.store.db:
            self.store.db.execute(
                "INSERT OR IGNORE INTO managed_lifecycle_config VALUES('enabled_at',?)", (str(time.time()),))
        self.enabled_at = float(self.store.db.execute(
            "SELECT value FROM managed_lifecycle_config WHERE key='enabled_at'").fetchone()[0])

    def _ensure_instance(self, instance_id, kind, psidglobal, owner_ps4_id=None,
                         logical_space_key=None, adopted_existing=False):
        row = self.store.db.execute(
            "SELECT * FROM managed_instances WHERE instance_id=?", (instance_id,)).fetchone()
        expected = (kind, psidglobal, owner_ps4_id, logical_space_key)
        if row:
            actual = (row["kind"], row["psidglobal"], row["owner_ps4_id"], row["logical_space_key"])
            if actual != expected:
                raise ProtocolError("Managed instance identity conflicts with stored authority", 409)
            return dict(row)
        now = time.time()
        self.store.db.execute(
            "INSERT INTO managed_instances VALUES(?,?,?,?,?,'running',?,?,?)",
            (instance_id, kind, psidglobal, owner_ps4_id, logical_space_key,
             int(adopted_existing), now, now))
        return dict(self.store.db.execute(
            "SELECT * FROM managed_instances WHERE instance_id=?", (instance_id,)).fetchone())

    def provision_account(self, ps4_id):
        """Apply the explicit local default-Home policy only to managed-era accounts."""
        profile = self.store.db.execute("SELECT created_at FROM profiles WHERE ps4_id=?", (ps4_id,)).fetchone()
        if not profile:
            raise ProtocolError("Housing owner has no local account", 404)
        with self.store.atomic():
            policy = self.store.db.execute(
                "SELECT * FROM managed_account_policy WHERE ps4_id=?", (ps4_id,)).fetchone()
            if policy:
                if policy["default_home"]:
                    binding = self.housing.ensure_binding(ps4_id, "Home")
                    self._ensure_instance(binding["instance_id"], "personal", binding["psidglobal"],
                                          ps4_id, binding["logical_space_key"],
                                          OPAQUE_PERSONAL_ID.fullmatch(binding["instance_id"]) is None)
                    return binding
                return None
            if float(profile["created_at"]) < self.enabled_at:
                self.store.db.execute(
                    "INSERT INTO managed_account_policy VALUES(?,0,'preexisting_before_managed_mode',?)",
                    (ps4_id, time.time()))
                return None
            binding = self.housing.ensure_binding(ps4_id, "Home")
            self._ensure_instance(binding["instance_id"], "personal", binding["psidglobal"],
                                  ps4_id, binding["logical_space_key"],
                                  OPAQUE_PERSONAL_ID.fullmatch(binding["instance_id"]) is None)
            self.store.db.execute(
                "INSERT INTO managed_account_policy VALUES(?,1,'managed_default_home_v1',?)",
                (ps4_id, time.time()))
            return binding

    def _is_current(self, guid):
        row = self.store.db.execute("SELECT ps4_id FROM sessions WHERE guid=?", (guid,)).fetchone()
        return bool(row and self.store.current_guid(row[0]) == guid)

    def _allocation_exact(self, guid, instance_id, psidglobal):
        row = self.store.db.execute(
            "SELECT instance_id,psidglobal FROM allocations WHERE guid=?", (guid,)).fetchone()
        return bool(row and tuple(row) == (instance_id, psidglobal))

    def _reservation_count(self, instance_id, now, presence, exclude_guid=None):
        count = 0
        for row in self.store.db.execute(
                "SELECT requester_guid,state,expires_at,psidglobal FROM instance_demands "
                "WHERE instance_id=? AND state IN ('pending','allocated')", (instance_id,)):
            guid = row["requester_guid"]
            if guid == exclude_guid:
                continue
            if float(row["expires_at"]) <= now or not self._is_current(guid):
                continue
            if row["state"] == "pending" or guid not in presence:
                count += 1
        return count

    def _present_allocation_count(self, instance_id, psidglobal, presence, exclude_guid=None):
        return sum(guid != exclude_guid and self._allocation_exact(guid, instance_id, psidglobal)
                   for guid in presence)

    def _poll_has_capacity(self, demand, now, presence):
        """Count other occupants/reservations; the requester already owns its slot."""
        guid = demand["requester_guid"]
        instance_id, scene = demand["instance_id"], demand["psidglobal"]
        descriptor = self.instances.ready(instance_id=instance_id, psidglobal=scene)
        reservations = self._reservation_count(instance_id, now, presence, guid)
        present_others = self._present_allocation_count(
            instance_id, scene, presence, exclude_guid=guid)
        if descriptor is None:
            return present_others + reservations < 32
        self_present = guid in presence and self._allocation_exact(guid, instance_id, scene)
        reported_others = max(0, int(descriptor["players"]) - int(self_present))
        return (max(reported_others, present_others) + reservations
                < int(descriptor["maxusers"]))

    def _upsert_demand(self, guid, instance_id, psidglobal, requested_key, desired_owner_guid, now):
        self.store.db.execute(
            """INSERT INTO instance_demands VALUES(?,?,?,?,?,'pending',?,?,?)
            ON CONFLICT(requester_guid) DO UPDATE SET
              instance_id=excluded.instance_id,psidglobal=excluded.psidglobal,
              requested_key=excluded.requested_key,desired_owner_guid=excluded.desired_owner_guid,
              state='pending',reserved_at=excluded.reserved_at,
              expires_at=excluded.expires_at,updated_at=excluded.updated_at""",
            (guid, instance_id, psidglobal, requested_key, desired_owner_guid,
             now, now + PENDING_RENEW_SECONDS, now))
        self.store.db.execute(
            "UPDATE managed_instances SET desired_state='running',updated_at=? WHERE instance_id=?",
            (now, instance_id))

    def request_load(self, fields, profile):
        """Accept native loading and durably reserve one exact managed target."""
        guid, _account, requested_key, _testing, exclude_instance, desired_owner_guid = fields
        if self.store.current_guid(profile["ps4_id"]) != guid:
            raise ProtocolError("Historical session cannot request a managed instance", 403)
        binding = self.housing.resolve_load(profile["ps4_id"], requested_key, desired_owner_guid)
        scene = binding["psidglobal"] if binding else ("Nexus" if requested_key == "Login" else requested_key)
        if not binding and scene not in NONMINI_PUBLIC_SCENES:
            raise ProtocolError("Scene is outside managed non-mini readiness", 404)
        now = time.time()
        presence = self.store.presence()
        with self.store.atomic():
            previous = self.store.db.execute(
                "SELECT * FROM instance_demands WHERE requester_guid=? AND state IN ('pending','allocated')",
                (guid,)).fetchone()
            if binding:
                instance_id = binding["instance_id"]
                if exclude_instance and instance_id == exclude_instance:
                    raise ProtocolError("Exact personal instance was excluded by the request", 503)
                self._ensure_instance(instance_id, "personal", scene, binding["owner_ps4_id"],
                                      binding["logical_space_key"],
                                      OPAQUE_PERSONAL_ID.fullmatch(instance_id) is None)
                previous_live = bool(previous and float(previous["expires_at"]) > now
                                     and self._is_current(guid))
                same_reservation = bool(previous_live and previous["instance_id"] == instance_id
                                        and previous["psidglobal"] == scene
                                        and previous["desired_owner_guid"] == desired_owner_guid)
                descriptor = self.instances.ready(instance_id=instance_id, psidglobal=scene)
                players = 0 if descriptor is None else max(
                    descriptor["players"], self._present_allocation_count(instance_id, scene, presence))
                reservations = self._reservation_count(instance_id, now, presence, guid)
                if not same_reservation and players + reservations >= 32:
                    return guid + "#false#true"
            else:
                instance_id = None
                previous_live = bool(previous and float(previous["expires_at"]) > now
                                     and self._is_current(guid))
                if (previous_live and previous["psidglobal"] == scene
                        and previous["desired_owner_guid"] == ""
                        and previous["instance_id"] != exclude_instance):
                    managed = self.store.db.execute(
                        "SELECT 1 FROM managed_instances WHERE instance_id=? AND kind='public' AND psidglobal=?",
                        (previous["instance_id"], scene)).fetchone()
                    if managed:
                        instance_id = previous["instance_id"]
                ready_by_id = {row["instance_id"]: row for row in self.instances.all_ready()
                               if row["psidglobal"] == scene and row["instance_id"] != exclude_instance}
                if instance_id is None:
                    for candidate in ready_by_id.values():
                        reservations = self._reservation_count(candidate["instance_id"], now, presence, guid)
                        present = self._present_allocation_count(
                            candidate["instance_id"], candidate["psidglobal"], presence)
                        if max(candidate["players"], present) + reservations < candidate["maxusers"]:
                            instance_id = candidate["instance_id"]
                            self._ensure_instance(instance_id, "public", scene, adopted_existing=True)
                            break
                if instance_id is None:
                    rows = self.store.db.execute(
                        "SELECT * FROM managed_instances WHERE kind='public' AND psidglobal=? "
                        "AND instance_id<>? ORDER BY instance_id", (scene, exclude_instance or "")).fetchall()
                    for row in rows:
                        descriptor = ready_by_id.get(row["instance_id"])
                        reservations = self._reservation_count(row["instance_id"], now, presence, guid)
                        players = 0
                        if descriptor:
                            present = self._present_allocation_count(
                                descriptor["instance_id"], descriptor["psidglobal"], presence)
                            players = max(descriptor["players"], present)
                        if players + reservations < (descriptor["maxusers"] if descriptor else 32):
                            instance_id = row["instance_id"]
                            break
                if instance_id is None:
                    instance_id = "pub-" + uuid.uuid4().hex
                    self._ensure_instance(instance_id, "public", scene)
            self._upsert_demand(guid, instance_id, scene, requested_key, desired_owner_guid, now)
        return guid + "#false#false"

    def _visitor_still_valid(self, demand, requester_ps4_id, presence):
        binding = self.housing.binding(demand["instance_id"])
        if not binding:
            return demand["desired_owner_guid"] == ""
        if demand["desired_owner_guid"]:
            owner_guid = demand["desired_owner_guid"]
            return (self.store.current_guid(binding["owner_ps4_id"]) == owner_guid
                    and owner_guid in presence
                    and self._allocation_exact(owner_guid, demand["instance_id"], demand["psidglobal"]))
        return binding["owner_ps4_id"] == requester_ps4_id

    def poll(self, guid, profile):
        if self.store.current_guid(profile["ps4_id"]) != guid:
            raise ProtocolError("Historical session cannot poll a managed instance", 403)
        demand = self.store.db.execute(
            "SELECT * FROM instance_demands WHERE requester_guid=?", (guid,)).fetchone()
        if not demand or demand["state"] == "cancelled":
            return guid + "#false"
        now = time.time()
        presence = self.store.presence()
        if not self._visitor_still_valid(demand, profile["ps4_id"], presence):
            with self.store.db:
                self.store.db.execute(
                    "UPDATE instance_demands SET expires_at=?,updated_at=? WHERE requester_guid=?",
                    (now, now, guid))
            return guid + "#false"
        # An expired demand no longer reserved capacity while other requests
        # were admitted. Do not revive it above the target's limit: leaving it
        # expired lets those accepted requests finish instead of deadlocking
        # every poller behind a 33rd reservation. There is no recovered native
        # terminal envelope for this poll state, so it remains pending false.
        if (float(demand["expires_at"]) <= now
                and not self._poll_has_capacity(demand, now, presence)):
            return guid + "#false"
        with self.store.db:
            self.store.db.execute(
                "UPDATE instance_demands SET expires_at=?,updated_at=? WHERE requester_guid=?",
                (now + PENDING_RENEW_SECONDS, now, guid))
        instance = self.instances.ready(instance_id=demand["instance_id"], psidglobal=demand["psidglobal"])
        if instance is None:
            return guid + "#false"
        # Use the same requester-excluding arithmetic after renewal. Counting
        # its newly renewed demand on top of an exact present player would
        # otherwise reject a legitimate repeat poll at a full target.
        if not self._poll_has_capacity(demand, now, presence):
            return guid + "#false"
        with self.store.atomic():
            fresh = self.store.db.execute(
                "SELECT * FROM instance_demands WHERE requester_guid=?", (guid,)).fetchone()
            if (not fresh or fresh["instance_id"] != instance["instance_id"]
                    or fresh["psidglobal"] != instance["psidglobal"]):
                return guid + "#false"
            self.store.db.execute(
                """INSERT INTO allocations VALUES(?,?,?,?,?,?)
                ON CONFLICT(guid) DO UPDATE SET instance_id=excluded.instance_id,
                psidglobal=excluded.psidglobal,ip=excluded.ip,port=excluded.port,
                allocated_at=excluded.allocated_at""",
                (guid, instance["instance_id"], instance["psidglobal"], instance["ip"],
                 int(instance["port"]), now))
            self.store.db.execute(
                "UPDATE instance_demands SET state='allocated',expires_at=?,updated_at=? WHERE requester_guid=?",
                (now + ALLOCATED_GRACE_SECONDS, now, guid))
        return "#".join((guid, "true", instance["instance_id"], instance["psidglobal"],
                         instance["ip"], str(instance["port"])))

    def export_desired(self, state_dir):
        """Publish intent only; a supervisor runtime journal is never read here."""
        now = time.time()
        presence = self.store.presence()
        rows = []
        with self.store.db:
            for demand in self.store.db.execute(
                    "SELECT * FROM instance_demands WHERE state IN ('pending','allocated')"):
                guid = demand["requester_guid"]
                if not self._is_current(guid):
                    self.store.db.execute(
                        "UPDATE instance_demands SET state='cancelled',expires_at=?,updated_at=? WHERE requester_guid=?",
                        (now, now, guid))
                elif demand["state"] == "allocated":
                    if not self._allocation_exact(guid, demand["instance_id"], demand["psidglobal"]):
                        self.store.db.execute(
                            "UPDATE instance_demands SET state='cancelled',expires_at=?,updated_at=? WHERE requester_guid=?",
                            (now, now, guid))
                    elif guid in presence:
                        self.store.db.execute(
                            "UPDATE instance_demands SET expires_at=?,updated_at=? WHERE requester_guid=?",
                            (now + ALLOCATED_GRACE_SECONDS, now, guid))
            for managed in self.store.db.execute("SELECT * FROM managed_instances ORDER BY instance_id"):
                demands = [row for row in self.store.db.execute(
                    "SELECT requester_guid,state,expires_at FROM instance_demands WHERE instance_id=? "
                    "AND state IN ('pending','allocated')", (managed["instance_id"],))
                    if float(row["expires_at"]) > now and self._is_current(row["requester_guid"])]
                active_allocations = sum(
                    guid in presence and self._allocation_exact(guid, managed["instance_id"], managed["psidglobal"])
                    for guid in presence)
                pending_reservations = sum(
                    row["state"] == "pending" or row["requester_guid"] not in presence for row in demands)
                desired = "running" if demands or active_allocations else "stopped"
                self.store.db.execute(
                    "UPDATE managed_instances SET desired_state=?,updated_at=? WHERE instance_id=?",
                    (desired, now, managed["instance_id"]))
                rows.append({
                    "instance_id": managed["instance_id"], "kind": managed["kind"],
                    "psidglobal": managed["psidglobal"],
                    "owner_ps4_id": managed["owner_ps4_id"] or "",
                    "logical_space_key": managed["logical_space_key"] or "",
                    "desired_state": desired, "active_demands": len(demands),
                    "pending_reservations": pending_reservations,
                    "active_allocations": active_allocations,
                    "adopted_existing": bool(managed["adopted_existing"]),
                    "readiness_profile": self.readiness_profile,
                })
        snapshot = {"format_version": 1, "generation": now, "managed": True, "instances": rows}
        path = Path(state_dir) / "desired-instances.json"
        self.store._publish_snapshot(path, json_field(snapshot))
        return path
