"""Opt-in first-claim preservation registration, not Steam verification.

Steam IDs are supplied by the launcher and are not proof of Valve ownership.
Never enable this policy when verified Steam identity is a requirement. Existing
profiles, credentials and banned accounts cannot be claimed or reset here.
"""
import hashlib
import hmac
import ipaddress
import json
import time

from public_access import AccessDenied, SCHEME, STEAM_ID64, TOKEN, _b64_account
from wire import ProtocolError


MAX_BODY = 1024


class EnrollmentError(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code


class Enrollment:
    def __init__(self, store, authority, *, clock=time.time, per_ip=8, global_hourly=100, maximum=1000):
        self.store, self.db, self.authority, self.clock = store, store.db, authority, clock
        self.per_ip, self.global_hourly, self.maximum = per_ip, global_hourly, maximum
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
                raise EnrollmentError(409, "account_unavailable") from None
            profile = self.db.execute("SELECT 1 FROM profiles WHERE ps4_id=?", (account,)).fetchone()
            credential = self.db.execute("SELECT 1 FROM public_access_credentials WHERE ps4_id=?", (account,)).fetchone()
            existing = self.db.execute("SELECT 1 FROM preservation_enrollments WHERE ps4_id=?", (account,)).fetchone()
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
