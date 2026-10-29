"""Local coffee/Oktoberfest entitlements and one-use TCP handoff receipts.

The wire shapes are recovered client contracts.  Balances, display labels,
receipt lifetime and prop use counts are explicit preservation-server policy;
they are not claims about the retired service's economy.
"""
import json
import math
import os
from pathlib import Path
import time
import uuid

from wire import ProtocolError


KINDS = ("coffee", "oktoberfest")
RECEIPT_POLICY = "local_consumable_receipt_v1"
MAX_RECEIPT_SIZE = 16_384


def _kind(value):
    if value not in KINDS:
        raise ProtocolError("Unsupported consumable (picnic/minigames are deferred)", 404)
    return value


def _positive_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= 2_147_483_647:
        raise ProtocolError(f"{name} must be a positive Int32")
    return value


def _nonnegative_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 2_147_483_647:
        raise ProtocolError(f"{name} must be a non-negative Int32")
    return value


def _wire_text(value, name):
    if not isinstance(value, str) or not value or len(value) > 128 or "#" in value:
        raise ProtocolError(f"Invalid {name}")
    return value


def read_receipt(path: Path):
    """Strictly validate the immutable JSON handed to the Mirror instance."""
    if not 0 < path.stat().st_size <= MAX_RECEIPT_SIZE:
        raise ValueError("Invalid receipt size")
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    expected = {"format_version", "policy", "receipt_id", "guid", "ps4_id",
                "kind", "table_id", "use_count", "reward_index",
                "issued_at", "expires_at"}
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError("Invalid receipt schema")
    receipt_id = value["receipt_id"]
    if (not isinstance(receipt_id, str) or len(receipt_id) != 32
            or uuid.UUID(hex=receipt_id).hex != receipt_id
            or path.name != receipt_id + ".json"):
        raise ValueError("Invalid receipt ID")
    if value["format_version"] != 1 or value["policy"] != RECEIPT_POLICY:
        raise ValueError("Invalid receipt version or policy")
    if value["kind"] not in KINDS or value["table_id"] != 0:
        raise ValueError("Invalid receipt consumable")
    for name in ("guid", "ps4_id"):
        if not isinstance(value[name], str) or not value[name] or len(value[name]) > 128:
            raise ValueError("Invalid receipt identity")
    _positive_int(value["use_count"], "use_count")
    _nonnegative_int(value["reward_index"], "reward_index")
    for name in ("issued_at", "expires_at"):
        number = value[name]
        if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number):
            raise ValueError("Invalid receipt timestamp")
    if value["issued_at"] < 0 or value["expires_at"] <= value["issued_at"]:
        raise ValueError("Invalid receipt lifetime")
    return value


def claim_receipt_file(state_dir: Path, receipt_id: str, guid: str,
                       ps4_id: str, kind: str, now=None):
    """Offline reference for the C# exclusive-move claim algorithm."""
    _kind(kind)
    try:
        canonical = uuid.UUID(hex=receipt_id).hex
    except (ValueError, AttributeError, TypeError) as exc:
        raise ProtocolError("Invalid receipt", 403) from exc
    if canonical != receipt_id:
        raise ProtocolError("Invalid receipt", 403)
    source = Path(state_dir) / "consumable-receipts" / (receipt_id + ".json")
    target_dir = Path(state_dir) / "consumable-claims"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / source.name
    try:
        value = read_receipt(source)
        instant = time.time() if now is None else now
        if (value["guid"] != guid or value["ps4_id"] != ps4_id
                or value["kind"] != kind or instant > value["expires_at"]):
            raise ProtocolError("Receipt identity, kind or lifetime mismatch", 403)
        os.rename(source, target)  # same-volume, no-overwrite exclusive claim
    except (FileNotFoundError, FileExistsError, OSError, ValueError, ProtocolError) as exc:
        raise ProtocolError("Receipt is invalid, missing, or already claimed", 403) from exc
    return value["use_count"]


class Consumables:
    def __init__(self, store, receipt_ttl=300.0):
        self.store = store
        self.db = store.db
        self.state_dir = Path(store.state_dir)
        if (isinstance(receipt_ttl, bool) or not isinstance(receipt_ttl, (int, float))
                or not math.isfinite(receipt_ttl) or not 1 <= receipt_ttl <= 86_400):
            raise ValueError("receipt_ttl must be between 1 and 86400 seconds")
        self.receipt_ttl = float(receipt_ttl)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS consumable_balances (
                ps4_id TEXT NOT NULL REFERENCES profiles,
                kind TEXT NOT NULL CHECK(kind IN ('coffee','oktoberfest')),
                units INTEGER NOT NULL CHECK(units>=0),
                prop_use_count INTEGER NOT NULL CHECK(prop_use_count>0),
                price_display TEXT NOT NULL, price_type_display TEXT NOT NULL,
                reward_index INTEGER NOT NULL CHECK(reward_index>=0),
                rewarded INTEGER NOT NULL CHECK(rewarded IN (0,1)),
                updated_at REAL NOT NULL, PRIMARY KEY(ps4_id,kind));
            CREATE TABLE IF NOT EXISTS consumable_receipts (
                receipt_id TEXT PRIMARY KEY, ps4_id TEXT NOT NULL REFERENCES profiles,
                guid TEXT NOT NULL,
                kind TEXT NOT NULL CHECK(kind IN ('coffee','oktoberfest')),
                table_id INTEGER NOT NULL CHECK(table_id=0),
                use_count INTEGER NOT NULL CHECK(use_count>0),
                reward_index INTEGER NOT NULL CHECK(reward_index>=0),
                issued_at REAL NOT NULL, expires_at REAL NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('prepared','pending','claimed','cancelled')),
                claimed_at REAL);
        """)
        self.db.commit()

    def grant(self, ps4_id, kind, units, prop_use_count, price_display="1",
              price_type_display="local token", reward_index=0, rewarded=False):
        """Add locally-authored units and set their stable prop-use policy."""
        self.store.account(ps4_id)
        kind = _kind(kind)
        units = _positive_int(units, "units")
        prop_use_count = _positive_int(prop_use_count, "prop_use_count")
        reward_index = _nonnegative_int(reward_index, "reward_index")
        price_display = _wire_text(price_display, "price display")
        price_type_display = _wire_text(price_type_display, "price type display")
        if not isinstance(rewarded, bool):
            raise ProtocolError("rewarded must be boolean")
        now = time.time()
        with self.db:
            self.db.execute("""
                INSERT INTO consumable_balances VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(ps4_id,kind) DO UPDATE SET
                  units=consumable_balances.units+excluded.units,
                  prop_use_count=excluded.prop_use_count,
                  price_display=excluded.price_display,
                  price_type_display=excluded.price_type_display,
                  reward_index=excluded.reward_index,rewarded=excluded.rewarded,
                  updated_at=excluded.updated_at
            """, (ps4_id, kind, units, prop_use_count, price_display,
                    price_type_display, reward_index, int(rewarded), now))
        return self.balance(ps4_id, kind)

    def balance(self, ps4_id, kind):
        kind = _kind(kind)
        row = self.db.execute("SELECT * FROM consumable_balances WHERE ps4_id=? AND kind=?",
                              (ps4_id, kind)).fetchone()
        return dict(row) if row else None

    def list(self, ps4_id):
        return [dict(row) for row in self.db.execute(
            "SELECT * FROM consumable_balances WHERE ps4_id=? ORDER BY kind", (ps4_id,))]

    def _authorize(self, ps4_id, guid, kind, table_id):
        self.store.session(guid, ps4_id)
        _kind(kind)
        if isinstance(table_id, bool) or table_id != 0:
            raise ProtocolError("Coffee/Oktoberfest require tableID 0")

    def price_response(self, ps4_id, guid, kind, table_id):
        self._authorize(ps4_id, guid, kind, table_id)
        row = self.balance(ps4_id, kind)
        if row is None:
            price, price_type, amount, rewarded = "1", "local token", "0", "false"
        else:
            price, price_type = row["price_display"], row["price_type_display"]
            amount, rewarded = str(row["units"]), "true" if row["rewarded"] else "false"
        return "#".join(("true", guid, ps4_id, kind, "", price, price_type, amount, rewarded))

    def issue_response(self, ps4_id, guid, kind, table_id, now=None):
        self._authorize(ps4_id, guid, kind, table_id)
        instant = time.time() if now is None else float(now)
        if not math.isfinite(instant) or instant < 0:
            raise ProtocolError("Invalid issue time")
        receipt_id = uuid.uuid4().hex
        with self.store.atomic():
            if self.store.current_guid(ps4_id) != guid:
                raise ProtocolError("Consumable issue requires the current account session", 403)
            row = self.db.execute("SELECT * FROM consumable_balances WHERE ps4_id=? AND kind=?",
                                  (ps4_id, kind)).fetchone()
            if row is None or row["units"] <= 0:
                return "#".join(("true", guid, ps4_id, kind, "", "false", "", "0"))
            self.db.execute("UPDATE consumable_balances SET units=units-1,updated_at=? WHERE ps4_id=? AND kind=?",
                            (instant, ps4_id, kind))
            expires = instant + self.receipt_ttl
            self.db.execute("INSERT INTO consumable_receipts VALUES(?,?,?,?,?,?,?,?,?,'prepared',NULL)",
                            (receipt_id, ps4_id, guid, kind, 0, row["prop_use_count"],
                             row["reward_index"], instant, expires))
        payload = {"format_version": 1, "policy": RECEIPT_POLICY,
                   "receipt_id": receipt_id, "guid": guid, "ps4_id": ps4_id,
                   "kind": kind, "table_id": 0,
                   "use_count": row["prop_use_count"],
                   "reward_index": row["reward_index"],
                   "issued_at": instant, "expires_at": expires}
        try:
            self._publish(payload)
        except Exception:
            with self.db:
                changed = self.db.execute("UPDATE consumable_receipts SET status='cancelled' WHERE receipt_id=? AND status='prepared'", (receipt_id,)).rowcount
                if changed:
                    self.db.execute("UPDATE consumable_balances SET units=units+1 WHERE ps4_id=? AND kind=?", (ps4_id, kind))
            raise
        with self.db:
            self.db.execute("UPDATE consumable_receipts SET status='pending' WHERE receipt_id=? AND status='prepared'", (receipt_id,))
        return "#".join(("true", guid, ps4_id, kind, "", "true", receipt_id,
                         str(row["reward_index"])))

    def _publish(self, payload):
        directory = self.state_dir / "consumable-receipts"
        directory.mkdir(parents=True, exist_ok=True)
        final = directory / (payload["receipt_id"] + ".json")
        temporary = directory / ("." + payload["receipt_id"] + ".tmp")
        data = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.rename(temporary, final)

    def import_claims(self):
        result = {"applied": 0, "seen": 0, "invalid": 0}
        directory = self.state_dir / "consumable-claims"
        if not directory.is_dir():
            return result
        for path in sorted(directory.glob("*.json")):
            try:
                value = read_receipt(path)
                row = self.db.execute("SELECT * FROM consumable_receipts WHERE receipt_id=?",
                                      (value["receipt_id"],)).fetchone()
                if row is None or any(row[key] != value[key] for key in
                    ("ps4_id", "guid", "kind", "table_id", "use_count", "reward_index", "issued_at", "expires_at")):
                    raise ValueError("Unknown or conflicting claim")
                if row["status"] == "claimed":
                    result["seen"] += 1
                    continue
                if row["status"] not in ("prepared", "pending"):
                    raise ValueError("Receipt cannot be claimed")
                with self.db:
                    self.db.execute("UPDATE consumable_receipts SET status='claimed',claimed_at=? WHERE receipt_id=?",
                                    (time.time(), value["receipt_id"]))
                result["applied"] += 1
            except (OSError, ValueError, ProtocolError, KeyError, TypeError):
                result["invalid"] += 1
        return result
