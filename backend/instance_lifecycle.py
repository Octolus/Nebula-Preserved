"""Backend-owned desired instance state; never launches or connects to a process."""
import json
import os
from pathlib import Path
import re
import time
import uuid

from allocation import NONMINI_PUBLIC_SCENES
from apartments import ApartmentPolicy
from wire import ProtocolError, json_field


PENDING_RENEW_SECONDS = 15.0
ALLOCATED_GRACE_SECONDS = 30.0
OPAQUE_PERSONAL_ID = re.compile(r"apt-[0-9a-f]{32}\Z")
DEFAULT_IDLE_SECONDS = {"public": 900.0, "personal": 60.0}


def _bounded_env(env, name, default, low, high, cast=float):
    raw = env.get(name, "")
    if raw == "":
        return default
    value = cast(raw)
    if not low <= value <= high:
        raise ValueError(name + " is outside its supported range")
    return value


def lifecycle_policy(env=None):
    """Operator knobs shared by backend demand admission and supervisor idle stops."""
    env = os.environ if env is None else env
    personal_default = _bounded_env(env, "NEBULA_IDLE_TTL", DEFAULT_IDLE_SECONDS["personal"], 0, 86400)
    return {
        "idle_seconds": {
            "public": _bounded_env(env, "NEBULA_PUBLIC_WORLD_IDLE_SECONDS", DEFAULT_IDLE_SECONDS["public"], 0, 86400),
            "personal": _bounded_env(env, "NEBULA_PERSONAL_WORLD_IDLE_SECONDS", personal_default, 0, 86400)},
        # None disables admission control (unknown supervisor budget).
        "max_worlds": _bounded_env(env, "NEBULA_MAX_PROCESSES", None, 1, 32, int),
    }


class ManagedInstanceLifecycle:
    """Durable demand authority for an explicitly managed deployment.

    Fresh instance-status descriptors remain the sole readiness authority. This
    class publishes intent for a separate supervisor and never trusts its
    runtime/lease journal when allocating a client.
    """

    def __init__(self, store, housing, instances, readiness_profile, *, env=None):
        if readiness_profile != "nonmini-semantic-v1":
            raise ValueError("Managed instances require nonmini-semantic-v1 readiness on both services")
        self.store = store
        self.housing = housing
        self.instances = instances
        self.readiness_profile = readiness_profile
        policy = lifecycle_policy(env)
        self.idle_seconds, self.max_worlds = policy["idle_seconds"], policy["max_worlds"]
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
        if "last_active_at" not in {row[1] for row in self.store.db.execute("PRAGMA table_info(managed_instances)")}:
            # Idle grace evidence only; NULL (never active) is never kept running.
            self.store.db.execute("ALTER TABLE managed_instances ADD COLUMN last_active_at REAL")
        with self.store.db:
            self.store.db.execute(
                "INSERT OR IGNORE INTO managed_lifecycle_config VALUES('enabled_at',?)", (str(time.time()),))
        self.enabled_at = float(self.store.db.execute(
            "SELECT value FROM managed_lifecycle_config WHERE key='enabled_at'").fetchone()[0])
        # Every account (existing and new) owns Home plus the configured
        # starter apartments; the startup backfill is recorded per account.
        self.apartments = ApartmentPolicy(store, housing, self, env=env)
        self.apartments.backfill()

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
            "INSERT INTO managed_instances(instance_id,kind,psidglobal,owner_ps4_id,logical_space_key,"
            "desired_state,adopted_existing,created_at,updated_at) VALUES(?,?,?,?,?,'running',?,?,?)",
            (instance_id, kind, psidglobal, owner_ps4_id, logical_space_key,
             int(adopted_existing), now, now))
        return dict(self.store.db.execute(
            "SELECT * FROM managed_instances WHERE instance_id=?", (instance_id,)).fetchone())

    def ensure_personal_instance(self, binding):
        """Managed bookkeeping for one personal binding (adopts legacy safe IDs)."""
        return self._ensure_instance(binding["instance_id"], "personal", binding["psidglobal"],
                                     binding["owner_ps4_id"], binding["logical_space_key"],
                                     OPAQUE_PERSONAL_ID.fullmatch(binding["instance_id"]) is None)

    def provision_account(self, ps4_id):
        """Give Home plus each configured starter apartment (once) to this account.

        `managed_account_policy` is kept only as the historical record of the
        earlier new-accounts-only Home policy; it no longer gates ownership.
        """
        return self.apartments.provision(ps4_id)

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

    def _committed_instances(self, now, presence, exclude_guid):
        """Worlds with another live demand or present player; idle-grace worlds stay evictable."""
        busy = {row["instance_id"] for row in self.store.db.execute(
                    "SELECT requester_guid,instance_id,expires_at FROM instance_demands "
                    "WHERE state IN ('pending','allocated')")
                if row["requester_guid"] != exclude_guid and float(row["expires_at"]) > now
                and self._is_current(row["requester_guid"])}
        for row in self.store.db.execute(
                "SELECT a.guid,a.instance_id FROM allocations a JOIN managed_instances m "
                "ON m.instance_id=a.instance_id AND m.psidglobal=a.psidglobal"):
            if row["guid"] != exclude_guid and row["guid"] in presence:
                busy.add(row["instance_id"])
        return busy

    def _no_free_world(self, guid, instance_id, scene, now, presence):
        """Native N2LoadSpace noFreeSlot is the only recovered server-busy envelope.

        N2SpaceLoading has no failure terminal (false always means retry), so
        refuse here instead of accepting a demand the bounded supervisor cannot
        launch. Running worlds and idle-grace worlds (evictable) never block.
        """
        if self.max_worlds is None or self.instances.ready(instance_id=instance_id, psidglobal=scene):
            return False
        busy = self._committed_instances(now, presence, guid)
        return instance_id not in busy and len(busy) >= self.max_worlds

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
            "UPDATE managed_instances SET desired_state='running',updated_at=?,last_active_at=? WHERE instance_id=?",
            (now, now, instance_id))

    def _public_invite_target(self, desired_guid, scene, exclude_instance, presence):
        """Exact shared instance of an invited friend's current, present session."""
        target = self.store.db.execute(
            "SELECT a.instance_id,a.psidglobal,s.ps4_id FROM allocations a JOIN sessions s USING(guid) "
            "WHERE a.guid=?", (desired_guid,)).fetchone()
        if (not target or target["psidglobal"] != scene or desired_guid not in presence
                or self.store.current_guid(target["ps4_id"]) != desired_guid
                or (exclude_instance and target["instance_id"] == exclude_instance)):
            raise ProtocolError("Requested player has no ready local instance", 503)
        instance_id = target["instance_id"]
        managed = self.store.db.execute(
            "SELECT kind,psidglobal FROM managed_instances WHERE instance_id=?", (instance_id,)).fetchone()
        if managed is None:
            if self.instances.ready(instance_id=instance_id, psidglobal=scene) is None:
                raise ProtocolError("Requested player has no ready local instance", 503)
            self._ensure_instance(instance_id, "public", scene, adopted_existing=True)
        elif (managed["kind"], managed["psidglobal"]) != ("public", scene):
            raise ProtocolError("Managed instance identity conflicts with stored authority", 409)
        return instance_id

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
                if not same_reservation and self._no_free_world(guid, instance_id, scene, now, presence):
                    return guid + "#false#true"
            elif desired_owner_guid:
                # Join a friend in a shared world: pin the friend's exact public
                # instance. A full or unlaunchable target uses native noFreeSlot.
                instance_id = self._public_invite_target(desired_owner_guid, scene, exclude_instance, presence)
                previous_live = bool(previous and float(previous["expires_at"]) > now
                                     and self._is_current(guid))
                same_reservation = bool(previous_live and previous["instance_id"] == instance_id
                                        and previous["psidglobal"] == scene
                                        and previous["desired_owner_guid"] == desired_owner_guid)
                descriptor = self.instances.ready(instance_id=instance_id, psidglobal=scene)
                players = 0 if descriptor is None else max(
                    descriptor["players"], self._present_allocation_count(instance_id, scene, presence))
                capacity = 32 if descriptor is None else int(descriptor["maxusers"])
                reservations = self._reservation_count(instance_id, now, presence, guid)
                if not same_reservation and (players + reservations >= capacity or
                                             self._no_free_world(guid, instance_id, scene, now, presence)):
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
                    if self._no_free_world(guid, instance_id, scene, now, presence):
                        return guid + "#false#true"
                    self._ensure_instance(instance_id, "public", scene)
                elif (instance_id not in ready_by_id
                      and not (previous_live and previous["instance_id"] == instance_id)
                      and self._no_free_world(guid, instance_id, scene, now, presence)):
                    return guid + "#false#true"
            self._upsert_demand(guid, instance_id, scene, requested_key, desired_owner_guid, now)
        return guid + "#false#false"

    def _visitor_still_valid(self, demand, requester_ps4_id, presence):
        binding = self.housing.binding(demand["instance_id"])
        if not binding:
            # Shared worlds carry no apartment authority; a friend-pinned public
            # demand stays valid even after that friend moves on. A visitor of
            # an apartment whose binding vanished does not.
            return demand["desired_owner_guid"] == "" or self.store.db.execute(
                "SELECT 1 FROM managed_instances WHERE instance_id=? AND kind='public'",
                (demand["instance_id"],)).fetchone() is not None
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
                last_active = managed["last_active_at"]
                if demands or active_allocations:
                    last_active = now
                # An empty world stays up for its kind's idle grace (public worlds
                # avoid cold starts); the supervisor may still evict it for demand.
                in_grace = (last_active is not None
                            and now - float(last_active) < self.idle_seconds[managed["kind"]])
                desired = "running" if demands or active_allocations or in_grace else "stopped"
                self.store.db.execute(
                    "UPDATE managed_instances SET desired_state=?,updated_at=?,last_active_at=? WHERE instance_id=?",
                    (desired, now, last_active, managed["instance_id"]))
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
