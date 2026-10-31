"""Apartment (personal space) ownership: native default, starter set, staff grants.

Recovered client behavior (RVAs in docs/research/managed-instance-lifecycle.md):
the native navigator always lists `Home` (NavigatorSelector.HOME, enabled
unconditionally by SetPersonalSpaces 0x47d5b0 and GetPersonalSpaces 0x3e86a0)
and enables every other apartment only when GetPurchases lists it under
`personalspaces`. Other apartments were shop products (category `PERSON`,
ShopManager.OnPersonalSpaceSelected 0x4adc20). No other free, promotional or
reward apartment was recovered, so every account owns `Home`, and the extra
starter apartments are an operator preservation policy
(`NEBULA_STARTER_APARTMENTS`).

Each starter apartment is applied once per account and recorded in
`starter_apartment_grants`; a later staff removal is never undone and a
shrunken configuration never removes anything. `Home` cannot be removed
because the client offers it to every player.
"""
import os
import time

from diagnostic_logging import emit
from housing import PERSONAL_SPACE_SCENES
from wire import ProtocolError

NATIVE_DEFAULT_APARTMENT = "Home"
# Preservation choice, not recovered entitlement: Home plus the two apartments
# with the strongest reviewed scene/runtime evidence (CliffApartment: reviewed
# empty generic baseline; LakeApartment: verified slots/floor areas and
# managed allocation runs).
DEFAULT_STARTER_APARTMENTS = ("Home", "CliffApartment", "LakeApartment")
POLICY_SOURCE = "starter_apartments_v1"


def starter_apartments(env=None):
    """Configured starter set; `Home` is always first and always included."""
    env = os.environ if env is None else env
    raw = (env.get("NEBULA_STARTER_APARTMENTS") or "").strip()
    names = [name.strip() for name in raw.split(",")] if raw else list(DEFAULT_STARTER_APARTMENTS)
    result = [NATIVE_DEFAULT_APARTMENT]
    for name in names:
        if not name:
            continue
        if name not in PERSONAL_SPACE_SCENES:
            raise ValueError("NEBULA_STARTER_APARTMENTS contains an unknown apartment: " + name[:64])
        if name not in result:
            result.append(name)
    return tuple(result)


class ApartmentPolicy:
    """Grant/remove apartment bindings and keep managed bookkeeping consistent.

    `lifecycle` is the managed instance lifecycle, or None in manual mode
    (where no apartment is provisioned automatically and staff grants only
    create bindings). Starter provisioning requires the managed lifecycle.
    """

    def __init__(self, store, housing, lifecycle=None, *, env=None, spaces=None):
        self.store, self.housing, self.lifecycle = store, housing, lifecycle
        if lifecycle is None:
            self.spaces = ()
        else:
            self.spaces = starter_apartments(env) if spaces is None else tuple(spaces)
            if self.spaces[:1] != (NATIVE_DEFAULT_APARTMENT,) or any(
                    name not in PERSONAL_SPACE_SCENES for name in self.spaces):
                raise ValueError("Starter apartments must start with Home and use shipped names")
        store.db.executescript("""
            CREATE TABLE IF NOT EXISTS starter_apartment_grants (
                ps4_id TEXT NOT NULL REFERENCES profiles,
                logical_space_key TEXT NOT NULL,
                instance_id TEXT NOT NULL,
                created_binding INTEGER NOT NULL CHECK(created_binding IN (0,1)),
                policy_source TEXT NOT NULL, granted_at REAL NOT NULL,
                PRIMARY KEY(ps4_id,logical_space_key));
        """)

    def _table(self, name):
        return self.store.db.execute(
            "SELECT 1 FROM sqlite_schema WHERE type='table' AND name=?", (name,)).fetchone() is not None

    def owned(self, ps4_id, key):
        row = self.store.db.execute(
            "SELECT instance_id FROM housing_spaces WHERE owner_ps4_id=? AND logical_space_key=?",
            (ps4_id, key)).fetchone()
        return self.housing.binding(row[0]) if row else None

    def _identity_conflict(self, ps4_id, key):
        """An existing binding whose managed row for this owner/space has another ID."""
        if self.lifecycle is None:
            return False
        binding = self.owned(ps4_id, key)
        row = self.store.db.execute(
            "SELECT instance_id FROM managed_instances WHERE owner_ps4_id=? AND logical_space_key=?",
            (ps4_id, key)).fetchone()
        return bool(binding and row and row[0] != binding["instance_id"])

    def bind(self, ps4_id, key):
        """Idempotently give one apartment; returns (binding, created)."""
        if key not in PERSONAL_SPACE_SCENES:
            raise ProtocolError("Unknown shipped personal-space navigator name", 404)
        if self._identity_conflict(ps4_id, key):
            raise ProtocolError("Apartment binding differs from its managed instance identity", 409)
        with self.store.atomic():
            binding, created = self.owned(ps4_id, key), False
            if binding is None:
                created = True
                managed = self.store.db.execute(
                    "SELECT instance_id FROM managed_instances WHERE kind='personal' AND owner_ps4_id=? "
                    "AND logical_space_key=?", (ps4_id, key)).fetchone() if self._table("managed_instances") else None
                if managed:
                    # A removed apartment keeps its stable managed identity
                    # (UNIQUE owner/space); a later grant reuses it.
                    binding = self.housing.bind_space(managed[0], PERSONAL_SPACE_SCENES[key], ps4_id, key)
                else:
                    binding = self.housing.ensure_binding(ps4_id, key)
            if self.lifecycle is not None:
                self.lifecycle.ensure_personal_instance(binding)
            return binding, created

    def provision(self, ps4_id):
        """Home always; each configured starter apartment once per account."""
        if not self.store.db.execute("SELECT 1 FROM profiles WHERE ps4_id=?", (ps4_id,)).fetchone():
            raise ProtocolError("Housing owner has no local account", 404)
        home = None
        with self.store.atomic():
            recorded = {row[0] for row in self.store.db.execute(
                "SELECT logical_space_key FROM starter_apartment_grants WHERE ps4_id=?", (ps4_id,))}
            for key in self.spaces:
                if key in recorded and key != NATIVE_DEFAULT_APARTMENT:
                    continue
                if self._identity_conflict(ps4_id, key):
                    # A hand-edited binding must not block login or startup;
                    # leave it unrecorded for an operator to reconcile.
                    emit("apartment_identity_conflict", ("apartment_identity_conflict", key),
                         level="warning", space=key)
                    continue
                binding, created = self.bind(ps4_id, key)
                if key == NATIVE_DEFAULT_APARTMENT:
                    home = binding
                if key not in recorded:
                    self.store.db.execute(
                        "INSERT INTO starter_apartment_grants VALUES(?,?,?,?,?,?)",
                        (ps4_id, key, binding["instance_id"], int(created), POLICY_SOURCE, time.time()))
        return home

    def backfill(self):
        """Startup migration: provision every account missing Home or a starter grant."""
        if not self.spaces:
            return 0
        marks = ",".join("?" * len(self.spaces))
        accounts = [row[0] for row in self.store.db.execute(
            f"""SELECT p.ps4_id FROM profiles p WHERE
                NOT EXISTS(SELECT 1 FROM housing_spaces h WHERE h.owner_ps4_id=p.ps4_id AND h.logical_space_key=?)
                OR (SELECT COUNT(*) FROM starter_apartment_grants g WHERE g.ps4_id=p.ps4_id
                    AND g.logical_space_key IN ({marks}))<?
                ORDER BY p.ps4_id""", (NATIVE_DEFAULT_APARTMENT, *self.spaces, len(self.spaces)))]
        for ps4_id in accounts:
            self.provision(ps4_id)
        return len(accounts)

    def in_use(self, instance_id):
        now, presence = time.time(), self.store.presence()
        if any(row[0] in presence for row in self.store.db.execute(
                "SELECT guid FROM allocations WHERE instance_id=?", (instance_id,))):
            return True
        if not self._table("instance_demands"):
            return False
        return any(float(row["expires_at"]) > now
                   and self.store.current_guid(row["ps4_id"]) == row["requester_guid"]
                   for row in self.store.db.execute(
                       """SELECT d.requester_guid,d.expires_at,s.ps4_id FROM instance_demands d
                       JOIN sessions s ON s.guid=d.requester_guid
                       WHERE d.instance_id=? AND d.state IN ('pending','allocated')""", (instance_id,)))

    def remove(self, ps4_id, key):
        """Revoke one apartment binding and its saved layout; returns the removed row."""
        if key == NATIVE_DEFAULT_APARTMENT:
            raise ProtocolError("Home is the native default apartment every player is offered; it cannot be removed", 409)
        with self.store.atomic():
            binding = self.owned(ps4_id, key)
            if binding is None:
                raise ProtocolError("Apartment is not owned", 404)
            instance_id = binding["instance_id"]
            stage = self.store.db.execute(
                "SELECT state FROM housing_save_stages WHERE instance_id=?", (instance_id,)).fetchone() \
                if self._table("housing_save_stages") else None
            if stage is not None and stage[0] == "open":
                raise ProtocolError("The owner is saving this apartment; retry shortly", 409)
            if self.in_use(instance_id):
                raise ProtocolError("Someone is in or entering this apartment; retry when it is empty", 409)
            layout = self.store.db.execute(
                "SELECT layout_json FROM housing_layouts WHERE instance_id=?", (instance_id,)).fetchone()
            for table in ("housing_save_receipts", "housing_save_stages", "housing_layouts"):
                if self._table(table):
                    self.store.db.execute(f"DELETE FROM {table} WHERE instance_id=?", (instance_id,))
            self.store.db.execute("DELETE FROM housing_spaces WHERE instance_id=?", (instance_id,))
            if self._table("instance_demands"):
                now = time.time()
                self.store.db.execute(
                    "UPDATE instance_demands SET state='cancelled',expires_at=?,updated_at=? "
                    "WHERE instance_id=? AND state<>'cancelled'", (now, now, instance_id))
            # The managed_instances row stays (stopped, no demand) so a later
            # grant reuses this stable identity.
            return {**binding, "layout_json": layout[0] if layout else None}
