"""Atomic reconstruction of the original two sparse housing-save requests.

No client batch token exists. One outstanding save per current owner session is
the recovered UI contract; contradictory observed requests fail closed.
"""
import asyncio
import hashlib
import json
import time
import uuid

from wire import ProtocolError, json_field

GROUND = ("aidasset", "aidasset_tx", "aidasset_ty", "aidasset_tz", "aidasset_r")
SHARED = ("psidglobal", "aidassetWall", "aidassetWallSlot", "aidassetCeiling", "aidassetCeilingSlot")
SAVE_SECONDS = 30.0
# The original success popup remains for two Unity seconds. This shorter window
# acknowledges transport duplicates and rejects an observable overlapping save.
ACK_SECONDS = 0.75
RECEIPT_SECONDS = 300.0


class HousingSavePending(ProtocolError):
    def __init__(self, coordinator, ticket, binding):
        super().__init__("Housing save is waiting for its original counterpart", 503)
        self.coordinator, self.ticket, self.binding = coordinator, ticket, dict(binding)


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def dispatch_housing_atomic(service, command, plaintext):
    """Keep original part1 HTTP response pending without blocking part0 arrival."""
    try:
        return service.dispatch(command, plaintext)
    except HousingSavePending as pending:
        if command != "HousingSavePresetServletParts":
            raise
        await pending.coordinator.wait(pending.ticket)
        return "#".join(("true", pending.ticket[1], pending.binding["owner_ps4_id"], "true"))


class AtomicHousingSaves:
    def __init__(self, housing):
        self.housing = housing
        self.store = housing.store
        self.clock = time.time
        self.store.db.executescript("""
            CREATE TABLE IF NOT EXISTS housing_save_stages (
                instance_id TEXT PRIMARY KEY REFERENCES housing_spaces,
                guid TEXT NOT NULL, owner_ps4_id TEXT NOT NULL,
                batch_id TEXT NOT NULL, shared_json TEXT NOT NULL,
                part0_json TEXT, part1_json TEXT, state TEXT NOT NULL,
                started_at REAL NOT NULL, deadline REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS housing_save_receipts (
                batch_id TEXT PRIMARY KEY, instance_id TEXT NOT NULL REFERENCES housing_spaces,
                guid TEXT NOT NULL, part0_sha256 TEXT NOT NULL, part1_sha256 TEXT NOT NULL,
                committed_at REAL NOT NULL);
        """)
        self.store.db.commit()

    def current(self, guid, scene, expected):
        binding = self.housing.allocated_binding(guid, scene, write=True)
        if any(binding[key] != expected[key] for key in
               ("instance_id", "owner_ps4_id", "psidglobal", "logical_space_key")):
            raise ProtocolError("Housing allocation changed during whole-layout save", 403)
        return binding

    def submit(self, guid, binding, value, part):
        now = self.clock()
        payload = json_field(value)
        common = json_field({**{key: value[key] for key in SHARED}, "ground_count": len(value["aidasset"])})
        instance = binding["instance_id"]
        failure = None
        pending = None
        with self.store.atomic():
            self.current(guid, value["psidglobal"], binding)
            row = self.store.db.execute("SELECT * FROM housing_save_stages WHERE instance_id=?", (instance,)).fetchone()
            if row and row["guid"] != guid:
                self.store.db.execute("DELETE FROM housing_save_stages WHERE instance_id=?", (instance,))
                row = None
            if row and (row["state"] == "blocked" or now >= row["deadline"]):
                self.store.db.execute("UPDATE housing_save_stages SET state='blocked' WHERE instance_id=?", (instance,))
                failure = ProtocolError("Ambiguous or expired housing save requires a fresh owner login", 409)
            if failure is None and row is None:
                receipt = self.store.db.execute(
                    "SELECT * FROM housing_save_receipts WHERE instance_id=? AND guid=? ORDER BY committed_at DESC,batch_id DESC LIMIT 1",
                    (instance, guid)).fetchone()
                if receipt and now < receipt["committed_at"] + ACK_SECONDS:
                    if digest(payload) != receipt["part" + part + "_sha256"]:
                        failure = ProtocolError("Previous housing save is still acknowledging; retry after its success popup", 409)
                    else:
                        return binding
                if failure is None:
                    batch = uuid.uuid4().hex
                    self.store.db.execute(
                        "INSERT INTO housing_save_stages VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (instance, guid, binding["owner_ps4_id"], batch, common, None, None, "open", now, now + SAVE_SECONDS))
                    row = self.store.db.execute("SELECT * FROM housing_save_stages WHERE instance_id=?", (instance,)).fetchone()
            if failure is None:
                old = row["part" + part + "_json"]
                if row["shared_json"] != common or (old is not None and old != payload):
                    self.store.db.execute("UPDATE housing_save_stages SET state='blocked' WHERE instance_id=?", (instance,))
                    failure = ProtocolError("Conflicting original housing parts; fresh owner login required", 409)
                else:
                    # Column choice is from save_part's exact fixed 0/1 allowlist.
                    column = "part0_json" if part == "0" else "part1_json"
                    self.store.db.execute("UPDATE housing_save_stages SET " + column + "=? WHERE instance_id=?", (payload, instance))
                    row = self.store.db.execute("SELECT * FROM housing_save_stages WHERE instance_id=?", (instance,)).fetchone()
                    if row["part0_json"] is not None and row["part1_json"] is not None:
                        first, second = json.loads(row["part0_json"]), json.loads(row["part1_json"])
                        layout = self.housing.empty_layout(value["psidglobal"])
                        for key in GROUND:
                            layout[key] = first[key][:100] + second[key][100:]
                        for key in SHARED:
                            layout[key] = first[key]
                        self.current(guid, value["psidglobal"], binding)
                        owned = {item["item_id"] for item in self.housing.inventory(binding["owner_ps4_id"])}
                        if any(item != "null" and item not in owned for item in
                               layout["aidasset"] + layout["aidassetWall"] + layout["aidassetCeiling"]):
                            raise ProtocolError("Housing entitlement changed before whole-layout commit", 403)
                        self.housing.validate_layout(binding, layout)
                        self.store.db.execute(
                            "INSERT INTO housing_layouts VALUES(?,?,?) ON CONFLICT(instance_id) DO UPDATE SET layout_json=excluded.layout_json,updated_at=excluded.updated_at",
                            (instance, json_field(layout), now))
                        self.store.db.execute("INSERT INTO housing_save_receipts VALUES(?,?,?,?,?,?)",
                                              (row["batch_id"], instance, guid, digest(row["part0_json"]), digest(row["part1_json"]), now))
                        self.store.db.execute("DELETE FROM housing_save_stages WHERE instance_id=?", (instance,))
                        # Bounded receipts allow already-waiting original part1
                        # callbacks to observe their own commit across a restart.
                        self.store.db.execute("DELETE FROM housing_save_receipts WHERE instance_id=? AND (committed_at<? OR batch_id NOT IN (SELECT batch_id FROM housing_save_receipts WHERE instance_id=? ORDER BY committed_at DESC,batch_id DESC LIMIT 16))",
                                              (instance, now - RECEIPT_SECONDS, instance))
                    elif part == "1":
                        pending = (instance, guid, row["batch_id"], row["deadline"])
        # Quarantine changes must commit before returning a protocol rejection.
        if failure:
            raise failure
        if pending:
            raise HousingSavePending(self, pending, binding)
        return binding

    def ready(self, ticket):
        instance, guid, batch, deadline = ticket
        with self.store.atomic():
            binding = self.housing.allocated_binding(guid, write=True)
            if binding["instance_id"] != instance:
                raise ProtocolError("Housing allocation changed while awaiting save", 403)
            if self.store.db.execute("SELECT 1 FROM housing_save_receipts WHERE batch_id=? AND instance_id=? AND guid=?", (batch, instance, guid)).fetchone():
                return True
            row = self.store.db.execute("SELECT * FROM housing_save_stages WHERE instance_id=?", (instance,)).fetchone()
            if not row or row["guid"] != guid or row["batch_id"] != batch or row["state"] != "open":
                raise ProtocolError("Original housing save became ambiguous", 409)
            if self.clock() >= deadline:
                self.store.db.execute("UPDATE housing_save_stages SET state='blocked' WHERE instance_id=?", (instance,))
                expired = True
            else:
                expired = False
        if expired:
            raise ProtocolError("Incomplete housing save expired; committed layout preserved", 503)
        return False

    async def wait(self, ticket):
        # No SQLite transaction or cross-request lock is held while sleeping.
        # A separate monotonic limit also bounds a wall-clock rollback.
        stop = time.monotonic() + SAVE_SECONDS + 1
        while not self.ready(ticket):
            if time.monotonic() >= stop:
                with self.store.atomic():
                    self.store.db.execute("UPDATE housing_save_stages SET state='blocked' WHERE instance_id=? AND guid=? AND batch_id=?", ticket[:3])
                raise ProtocolError("Housing save acknowledgement wait expired", 503)
            await asyncio.sleep(0.05)
