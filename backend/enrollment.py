"""Opt-in first-claim preservation registration, not Steam verification.

Steam IDs are supplied by the launcher and are not proof of Valve ownership.
Never enable this policy when verified Steam identity is a requirement. Existing
credentials are never reset. The optional claimed-ID policy lets additional
devices access an existing profile; account bans apply under either policy.
"""
import hashlib
import hmac
import ipaddress
import json
import os
import time

from public_access import AccessDenied, SCHEME, STEAM_ID64, TOKEN, _b64_account, _derive
from wire import ProtocolError


MAX_BODY = 1024


class EnrollmentError(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code


def _env_int(env, name, low, high):
    raw = env.get(name, "").strip()
    if not raw:
        return None
    value = int(raw)
    if not low <= value <= high:
        raise ValueError(name + " is outside its supported range")
    return value


def enrollment_policy(env=None):
    """Operator limits; empty values keep the documented per-policy defaults."""
    env = os.environ if env is None else env
    protected = [value.strip() for value in env.get("NEBULA_PROTECTED_ACCOUNTS", "").split(",") if value.strip()]
    if any(not STEAM_ID64.fullmatch(value) for value in protected):
        raise ValueError("NEBULA_PROTECTED_ACCOUNTS must list SteamID64 values")
    staff = env.get("NEBULA_PROTECT_STAFF_ACCOUNTS", "1").strip() or "1"
    if staff not in ("0", "1"):
        raise ValueError("NEBULA_PROTECT_STAFF_ACCOUNTS must be 0 or 1")
    return {"maximum": _env_int(env, "NEBULA_ENROLLMENT_MAX_ACCOUNTS", 0, 10 ** 7),
            "per_ip": _env_int(env, "NEBULA_ENROLLMENT_PER_IP_HOURLY", 1, 10 ** 6),
            "global_hourly": _env_int(env, "NEBULA_ENROLLMENT_GLOBAL_HOURLY", 1, 10 ** 7),
            "protect_staff": staff == "1", "protected_accounts": frozenset(protected)}


class Enrollment:
    def __init__(self, store, authority, *, clock=time.time, per_ip=None, global_hourly=None, maximum=None,
                 trust_steam_id=False, protect_staff=None, protected_accounts=None, env=None):
        self.store, self.db, self.authority, self.clock = store, store.db, authority, clock
        if type(trust_steam_id) is not bool:
            raise TypeError("Trust Steam ID policy must be Boolean")
        policy = enrollment_policy(env)
        per_ip = policy["per_ip"] if per_ip is None else per_ip
        global_hourly = policy["global_hourly"] if global_hourly is None else global_hourly
        maximum = policy["maximum"] if maximum is None else maximum
        self.trust_steam_id = trust_steam_id
        self.per_ip = (120 if trust_steam_id else 8) if per_ip is None else per_ip
        self.global_hourly = (1200 if trust_steam_id else 100) if global_hourly is None else global_hourly
        self.maximum = 1000 if maximum is None else maximum
        # Trusted claims never reach these accounts without the primary credential.
        self.protect_staff = policy["protect_staff"] if protect_staff is None else bool(protect_staff)
        self.protected_accounts = frozenset(
            policy["protected_accounts"] if protected_accounts is None else protected_accounts)
        operator = self.db.execute("SELECT verifier FROM public_access_operator WHERE singleton=1").fetchone()
        if operator is None:
            raise RuntimeError("Initialize account operator authority before enabling enrollment")
        self.pepper = bytes(operator["verifier"])
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS preservation_enrollments (
                ps4_id TEXT PRIMARY KEY REFERENCES profiles(ps4_id),
                provenance_kind TEXT NOT NULL CHECK(provenance_kind='preservation-unverified-steam-claim'),
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS preservation_enrollment_limits (
                bucket TEXT NOT NULL, window INTEGER NOT NULL, attempts INTEGER NOT NULL,
                PRIMARY KEY(bucket, window)
            );
        """)
        self.db.commit()
        self.authority.configure_claim_trust(trust_steam_id)

    def _table(self, name):
        return self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()

    def protected(self, account):
        """Operator-listed, dashboard-operator-linked or staff-labelled accounts."""
        if account in self.protected_accounts:
            return True
        if not self.protect_staff:
            return False
        if self._table("management_operator_accounts") and self.db.execute(
                "SELECT 1 FROM management_operator_accounts WHERE account_id=?", (account,)).fetchone():
            return True
        if not self._table("moderation_accounts") or "staff_label" not in {
                row[1] for row in self.db.execute("PRAGMA table_info(moderation_accounts)")}:
            return False
        row = self.db.execute("SELECT staff_label FROM moderation_accounts WHERE ps4_id=?", (account,)).fetchone()
        return bool(row and row[0].strip())

    def primary_credential_matches(self, account, key):
        row = self.db.execute("SELECT salt,verifier FROM public_access_credentials WHERE ps4_id=? AND revoked_at IS NULL",
                              (account,)).fetchone()
        derived = _derive(key, b"\0" * 16 if row is None else bytes(row["salt"]))
        return row is not None and hmac.compare_digest(derived, bytes(row["verifier"]))

    def rate_limit(self, peer):
        try:
            address = str(ipaddress.ip_address(peer))
        except (ValueError, TypeError):
            raise EnrollmentError(400, "invalid_request") from None
        bucket = hmac.new(self.pepper, address.encode(), hashlib.sha256).hexdigest()
        window = int(self.clock()) // 3600
        with self.store.atomic():
            self.db.execute("DELETE FROM preservation_enrollment_limits WHERE window<?", (window - 1,))
            for name, maximum in ((bucket, self.per_ip), ("global", self.global_hourly)):
                value = self.db.execute("SELECT attempts FROM preservation_enrollment_limits WHERE bucket=? AND window=?", (name, window)).fetchone()
                if value is not None and value[0] >= maximum:
                    raise EnrollmentError(429, "registration_rate_limited")
            for name in (bucket, "global"):
                self.db.execute("""INSERT INTO preservation_enrollment_limits VALUES(?,?,1)
                    ON CONFLICT(bucket,window) DO UPDATE SET attempts=attempts+1""", (name, window))

    def register(self, body, peer):
        # Charge malformed and conflicting requests too. This short transaction
        # commits independently, so a refused registration cannot reset limits.
        self.rate_limit(peer)
        if (not isinstance(body, dict) or set(body) != {"steam_id", "enrollment_key"}
                or not isinstance(body.get("steam_id"), str)
                or not STEAM_ID64.fullmatch(body["steam_id"])
                or not isinstance(body.get("enrollment_key"), str)
                or not TOKEN.fullmatch(body["enrollment_key"])):
            raise EnrollmentError(400, "invalid_request")
        account, key = body["steam_id"], body["enrollment_key"]
        authorization = SCHEME + " " + _b64_account(account) + "." + key
        with self.store.atomic():
            try:
                self.store.moderation.ensure_allowed(account)
            except ProtocolError:
                raise EnrollmentError(409, "account_banned" if self.trust_steam_id else "account_unavailable") from None
            profile = self.db.execute("SELECT 1 FROM profiles WHERE ps4_id=?", (account,)).fetchone()
            credential = self.db.execute("SELECT 1 FROM public_access_credentials WHERE ps4_id=?", (account,)).fetchone()
            existing = self.db.execute("SELECT 1 FROM preservation_enrollments WHERE ps4_id=?", (account,)).fetchone()
            if self.trust_steam_id:
                created = profile is None
                if not created and self.protected(account):
                    # Protected accounts keep strict semantics: only the exact
                    # primary credential (a lost-response retry) is accepted.
                    if not self.primary_credential_matches(account, key):
                        raise EnrollmentError(409, "account_unavailable")
                    return {"steam_id": account, "authorization": authorization, "created": False,
                            "steam_identity_verified": False}
                if created:
                    if self.db.execute("SELECT count(*) FROM preservation_enrollments").fetchone()[0] >= self.maximum:
                        raise EnrollmentError(429, "registration_capacity_reached")
                    self.store.account(account)
                    self.db.execute("INSERT INTO preservation_enrollments VALUES(?,?,?)",
                                    (account, "preservation-unverified-steam-claim", self.clock()))
                try:
                    authorization = self.authority.add_claimed_device(account, key)
                except ValueError:
                    raise EnrollmentError(429, "registration_capacity_reached") from None
                return {"steam_id": account, "authorization": authorization, "created": created,
                        "steam_identity_verified": False}
            if profile is not None or credential is not None or existing is not None:
                if profile is None or credential is None or existing is None:
                    raise EnrollmentError(409, "account_unavailable")
                try:
                    self.authority.authenticate(authorization)
                except AccessDenied:
                    raise EnrollmentError(409, "account_unavailable") from None
                created = False
            else:
                if self.db.execute("SELECT count(*) FROM preservation_enrollments").fetchone()[0] >= self.maximum:
                    raise EnrollmentError(429, "registration_capacity_reached")
                self.store.account(account)
                authorization = self.authority.issue_new(account, key)
                self.db.execute("INSERT INTO preservation_enrollments VALUES(?,?,?)",
                                (account, "preservation-unverified-steam-claim", self.clock()))
                created = True
        return {"steam_id": account, "authorization": authorization, "created": created,
                "steam_identity_verified": False}


def decode_body(raw):
    def unique(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError("duplicate")
            obj[key] = value
        return obj
    if len(raw) > MAX_BODY:
        raise ValueError("size")
    return json.loads(raw.decode("utf-8"), object_pairs_hook=unique)
