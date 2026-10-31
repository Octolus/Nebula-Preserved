"""Per-account public-access credentials for the preservation backend.

This module does not validate Steam ownership tickets. Operator-issued
credentials require a provisioned SteamID64 profile; opt-in first registration
is a separate unverified preservation policy in enrollment.py. Optional
provenance is not Valve verification. The HTTP adapter must place the
authenticated account in ``actor_scope`` before dispatching a game request;
Store.account/session/bind_session then enforce that actor binding.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import hmac
import re
import secrets
import sqlite3
import time


STEAM_ID64 = re.compile(r"7656119[0-9]{10}\Z")
TOKEN = re.compile(r"[A-Za-z0-9_-]{43}\Z")
VERIFIED_CACHE_SIZE = 4096
VERIFIED_CACHE_SECONDS = 900.0
SCHEME = "Nebula-Account-v1"
_ACTOR = ContextVar("nebula_authenticated_account", default=None)
_GIFT_GRANT = ContextVar("nebula_validated_gift_recipient_grant", default=None)


class AccessDenied(Exception):
    pass


def migrate(db: sqlite3.Connection) -> None:
    """Install the additive credential schema in an already-open Store DB."""
    db.executescript("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            name TEXT PRIMARY KEY, applied_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS public_access_credentials (
            ps4_id TEXT PRIMARY KEY REFERENCES profiles(ps4_id) ON DELETE CASCADE,
            salt BLOB NOT NULL CHECK(length(salt)=16),
            verifier BLOB NOT NULL CHECK(length(verifier)=32),
            provenance_kind TEXT CHECK(provenance_kind IS NULL OR
                provenance_kind='operator-note'),
            provenance_evidence_sha256 TEXT CHECK(provenance_evidence_sha256 IS NULL OR
                length(provenance_evidence_sha256)=64),
            created_at REAL NOT NULL,
            revoked_at REAL
        );
        CREATE TABLE IF NOT EXISTS public_access_operator (
            singleton INTEGER PRIMARY KEY CHECK(singleton=1),
            salt BLOB NOT NULL CHECK(length(salt)=16),
            verifier BLOB NOT NULL CHECK(length(verifier)=32),
            created_at REAL NOT NULL
        );
    """)
    db.execute("INSERT OR IGNORE INTO schema_migrations(name,applied_at) VALUES(?,?)",
               ("public-access-v2", time.time()))
    db.commit()


def _derive(token: str, salt: bytes) -> bytes:
    if not TOKEN.fullmatch(token):
        raise AccessDenied("Invalid account credential")
    return hashlib.scrypt(token.encode("ascii"), salt=salt, n=1 << 15,
                          r=8, p=1, maxmem=64 * 1024 * 1024, dklen=32)


def _b64_account(ps4_id: str) -> str:
    return base64.urlsafe_b64encode(ps4_id.encode("ascii")).decode("ascii").rstrip("=")


def _decode_account(value: str) -> str:
    if not value or len(value) > 64:
        raise AccessDenied("Invalid account credential")
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        account = raw.decode("ascii")
    except (ValueError, UnicodeError) as exc:
        raise AccessDenied("Invalid account credential") from exc
    if not STEAM_ID64.fullmatch(account):
        raise AccessDenied("Invalid account credential")
    return account


class AccessAuthority:
    def __init__(self, db: sqlite3.Connection, *, allow_migrate: bool = False):
        self.db = db
        if allow_migrate:
            migrate(db)
        try:
            ready = db.execute(
                "SELECT 1 FROM schema_migrations WHERE name='public-access-v2'"
            ).fetchone()
            db.execute("SELECT provenance_kind,provenance_evidence_sha256 "
                       "FROM public_access_credentials LIMIT 1").fetchone()
            db.execute("SELECT 1 FROM public_access_operator LIMIT 1").fetchone()
        except sqlite3.DatabaseError as exc:
            raise RuntimeError("Run migrate_public_access.py before enabling public access") from exc
        if ready is None:
            raise RuntimeError("Public-access schema migration is not recorded")
        # Every game request carries the credential. One scrypt derivation is
        # ~100 ms and 32 MiB on the event loop, which capped a 1-CPU host at
        # ~10 game requests/s. Remember successful derivations under a
        # process-secret HMAC, bound to the exact stored salt+verifier, so a
        # revoked or rotated row is re-derived (and rejected) at once.
        self._verified_key = secrets.token_bytes(32)
        self._verified: dict[bytes, tuple[bytes, float]] = {}

    def _verify(self, kind: str, account: str, token: str, salt: bytes, verifier: bytes) -> bool:
        key = hmac.new(self._verified_key, "\0".join((kind, account, token)).encode("ascii"),
                       hashlib.sha256).digest()
        bound = hashlib.sha256(salt + verifier).digest()
        now = time.monotonic()
        cached = self._verified.get(key)
        if cached is not None and cached[1] > now and hmac.compare_digest(cached[0], bound):
            return True
        if not hmac.compare_digest(_derive(token, salt), verifier):
            self._verified.pop(key, None)
            return False
        if len(self._verified) >= VERIFIED_CACHE_SIZE:
            for stale in [k for k, (_b, expires) in self._verified.items() if expires <= now]:
                del self._verified[stale]
            while len(self._verified) >= VERIFIED_CACHE_SIZE:
                del self._verified[next(iter(self._verified))]
        self._verified[key] = (bound, now + VERIFIED_CACHE_SECONDS)
        return True

    @staticmethod
    def _derive_operator(secret: bytes, salt: bytes) -> bytes:
        if not isinstance(secret, bytes) or len(secret) < 32:
            raise AccessDenied("Invalid operator credential")
        return hashlib.scrypt(secret, salt=salt, n=1 << 15, r=8, p=1,
                              maxmem=64 * 1024 * 1024, dklen=32)

    def initialize_operator(self, secret: bytes) -> None:
        if self.db.execute("SELECT 1 FROM public_access_operator WHERE singleton=1").fetchone():
            raise ValueError("Operator credential is already initialized")
        salt = secrets.token_bytes(16)
        verifier = self._derive_operator(secret, salt)
        with self.db:
            self.db.execute("INSERT INTO public_access_operator VALUES(1,?,?,?)",
                            (salt, verifier, time.time()))

    def verify_operator(self, secret: bytes) -> None:
        row = self.db.execute(
            "SELECT salt,verifier FROM public_access_operator WHERE singleton=1"
        ).fetchone()
        if row is None:
            raise AccessDenied("Operator credential is not initialized")
        if not hmac.compare_digest(
                self._derive_operator(secret, bytes(row["salt"])), bytes(row["verifier"])):
            raise AccessDenied("Invalid operator credential")

    def issue(self, ps4_id: str, *, provenance_kind: str | None = None,
              provenance_evidence_sha256: str | None = None) -> str:
        if not STEAM_ID64.fullmatch(ps4_id):
            raise ValueError("Public preservation accounts require SteamID64")
        supplied_provenance = provenance_kind is not None or provenance_evidence_sha256 is not None
        if supplied_provenance and (provenance_kind != "operator-note" or
                not isinstance(provenance_evidence_sha256, str) or
                not re.fullmatch(r"[0-9a-f]{64}", provenance_evidence_sha256) or
                provenance_evidence_sha256 == "0" * 64):
            raise ValueError("Optional provenance requires operator-note plus a nonzero lowercase SHA-256")
        if self.db.execute("SELECT 1 FROM profiles WHERE ps4_id=?", (ps4_id,)).fetchone() is None:
            raise ValueError("Provision the existing preservation profile before issuing access")
        token = secrets.token_urlsafe(32)
        salt = secrets.token_bytes(16)
        verifier = _derive(token, salt)
        with self.db:
            self.db.execute("""INSERT INTO public_access_credentials
                (ps4_id,salt,verifier,provenance_kind,provenance_evidence_sha256,created_at,revoked_at)
                VALUES(?,?,?,?,?,?,NULL)
                ON CONFLICT(ps4_id) DO UPDATE SET salt=excluded.salt,
                    verifier=excluded.verifier, provenance_kind=excluded.provenance_kind,
                    provenance_evidence_sha256=excluded.provenance_evidence_sha256,
                    created_at=excluded.created_at, revoked_at=NULL""",
                (ps4_id, salt, verifier, provenance_kind,
                 provenance_evidence_sha256, time.time()))
        return SCHEME + " " + _b64_account(ps4_id) + "." + token

    def revoke(self, ps4_id: str) -> bool:
        with self.db:
            cursor = self.db.execute(
                "UPDATE public_access_credentials SET revoked_at=? WHERE ps4_id=? AND revoked_at IS NULL",
                (time.time(), ps4_id))
        return cursor.rowcount == 1

    def issue_new(self, ps4_id: str, token: str) -> str:
        """Register a client-generated secret once, inside the caller's group.

        Unlike the operator rotation method, this cannot replace any existing
        credential. The enrollment adapter owns first-profile authorization.
        """
        if not STEAM_ID64.fullmatch(ps4_id) or not TOKEN.fullmatch(token):
            raise ValueError("Invalid new preservation account")
        if not getattr(self.db, "atomic_depth", 0):
            raise RuntimeError("New-account access requires an atomic group")
        salt = secrets.token_bytes(16)
        verifier = _derive(token, salt)
        self.db.execute("""INSERT INTO public_access_credentials
            (ps4_id,salt,verifier,provenance_kind,provenance_evidence_sha256,created_at,revoked_at)
            VALUES(?,?,?,NULL,NULL,?,NULL)""", (ps4_id, salt, verifier, time.time()))
        return SCHEME + " " + _b64_account(ps4_id) + "." + token

    def configure_claim_trust(self, enabled: bool) -> None:
        """Backend-owned policy shared with independent native gateway readers."""
        if type(enabled) is not bool:
            raise TypeError("Claim trust policy must be Boolean")
        exists = self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='public_access_claim_policy'").fetchone()
        if not enabled and exists is None:
            return
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS public_access_claim_policy (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                enabled INTEGER NOT NULL CHECK(enabled IN (0,1))
            );
            CREATE TABLE IF NOT EXISTS public_access_claimed_devices (
                ps4_id TEXT NOT NULL REFERENCES profiles(ps4_id) ON DELETE CASCADE,
                key_hash TEXT NOT NULL CHECK(length(key_hash)=64),
                salt BLOB NOT NULL CHECK(length(salt)=16),
                verifier BLOB NOT NULL CHECK(length(verifier)=32),
                created_at REAL NOT NULL, revoked_at REAL,
                PRIMARY KEY(ps4_id,key_hash)
            );
        """)
        with self.db:
            self.db.execute("INSERT INTO public_access_claim_policy VALUES(1,?) ON CONFLICT(singleton) DO UPDATE SET enabled=excluded.enabled", (int(enabled),))

    def claim_trust_enabled(self) -> bool:
        exists = self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='public_access_claim_policy'").fetchone()
        if exists is None:
            return False
        row = self.db.execute("SELECT enabled FROM public_access_claim_policy WHERE singleton=1").fetchone()
        return row is not None and row[0] == 1

    def add_claimed_device(self, ps4_id: str, token: str) -> str:
        """Add one trust-policy device without touching the primary credential."""
        if not getattr(self.db, "atomic_depth", 0) or not self.claim_trust_enabled():
            raise RuntimeError("Claimed device requires enabled trust policy and atomic group")
        if not STEAM_ID64.fullmatch(ps4_id) or not TOKEN.fullmatch(token):
            raise ValueError("Invalid claimed preservation account")
        digest = hashlib.sha256(token.encode("ascii")).hexdigest()
        row = self.db.execute("SELECT revoked_at FROM public_access_claimed_devices WHERE ps4_id=? AND key_hash=?", (ps4_id, digest)).fetchone()
        if row is None:
            if self.db.execute("SELECT count(*) FROM public_access_claimed_devices WHERE ps4_id=?", (ps4_id,)).fetchone()[0] >= 64:
                raise ValueError("Claimed device capacity reached")
            salt = secrets.token_bytes(16)
            self.db.execute("INSERT INTO public_access_claimed_devices VALUES(?,?,?,?,?,NULL)",
                            (ps4_id, digest, salt, _derive(token, salt), time.time()))
        elif row["revoked_at"] is not None:
            # Trusting the claimed ID deliberately permits a fresh claim even
            # after a device revocation. Account bans are checked by enrollment.
            self.db.execute("UPDATE public_access_claimed_devices SET revoked_at=NULL WHERE ps4_id=? AND key_hash=?", (ps4_id, digest))
        return SCHEME + " " + _b64_account(ps4_id) + "." + token

    def claimed_device_key(self, ps4_id: str, authorization: str) -> str | None:
        """Lookup only; the caller authenticates before trusting this marker."""
        if not self.claim_trust_enabled():
            return None
        token = authorization.rsplit(".", 1)[-1]
        digest = hashlib.sha256(token.encode("ascii")).hexdigest()
        row = self.db.execute("SELECT 1 FROM public_access_claimed_devices WHERE ps4_id=? AND key_hash=? AND revoked_at IS NULL", (ps4_id, digest)).fetchone()
        return digest if row is not None else None

    def credential_fingerprint(self, ps4_id: str, claimed_device: str | None = None) -> str:
        """Revalidate the exact credential used by a gateway connection."""
        if claimed_device is None:
            row = self.db.execute("SELECT salt,verifier FROM public_access_credentials WHERE ps4_id=? AND revoked_at IS NULL", (ps4_id,)).fetchone()
        else:
            if not re.fullmatch(r"[0-9a-f]{64}", claimed_device) or not self.claim_trust_enabled():
                raise AccessDenied("Claimed device access is disabled")
            row = self.db.execute("SELECT salt,verifier FROM public_access_claimed_devices WHERE ps4_id=? AND key_hash=? AND revoked_at IS NULL", (ps4_id, claimed_device)).fetchone()
        if row is None:
            raise AccessDenied("Credential is no longer active")
        return hashlib.sha256(bytes(row["salt"]) + bytes(row["verifier"])).hexdigest()

    def authenticate(self, authorization: str | None) -> str:
        prefix = SCHEME + " "
        if not isinstance(authorization, str) or not authorization.startswith(prefix):
            raise AccessDenied("Account credential required")
        payload = authorization[len(prefix):]
        if payload.count(".") != 1:
            raise AccessDenied("Invalid account credential")
        encoded_account, token = payload.split(".", 1)
        account = _decode_account(encoded_account)
        if not TOKEN.fullmatch(token):
            raise AccessDenied("Invalid account credential")
        if self.claim_trust_enabled():
            alias = self.db.execute("""SELECT salt,verifier FROM public_access_claimed_devices
                WHERE ps4_id=? AND key_hash=? AND revoked_at IS NULL""",
                (account, hashlib.sha256(token.encode("ascii")).hexdigest())).fetchone()
            if alias is not None:
                if not self._verify("device", account, token, bytes(alias["salt"]), bytes(alias["verifier"])):
                    raise AccessDenied("Invalid account credential")
                sanction = self.db.execute("SELECT ban_enabled,ban_expires_at FROM moderation_accounts WHERE ps4_id=?", (account,)).fetchone()
                if sanction is not None and sanction["ban_enabled"] == 1 and (
                        sanction["ban_expires_at"] is None or time.time() < sanction["ban_expires_at"]):
                    raise AccessDenied("Account is banned")
                return account
        row = self.db.execute("""SELECT salt,verifier FROM public_access_credentials
            WHERE ps4_id=? AND revoked_at IS NULL""", (account,)).fetchone()
        if row is None:
            # Do comparable password work for unknown/revoked accounts.
            _derive(token, b"\0" * 16)
            raise AccessDenied("Invalid account credential")
        if not self._verify("account", account, token, bytes(row["salt"]), bytes(row["verifier"])):
            raise AccessDenied("Invalid account credential")
        return account


@contextmanager
def actor_scope(ps4_id: str):
    token = _ACTOR.set(ps4_id)
    try:
        yield
    finally:
        _ACTOR.reset(token)


def require_actor(ps4_id: str) -> None:
    actor = _ACTOR.get()
    if actor is not None and actor != ps4_id:
        raise AccessDenied("Authenticated account differs from request identity")


def current_actor() -> str | None:
    return _ACTOR.get()


@contextmanager
def gift_recipient_grant(store, sender_ps4_id: str, recipient_ps4_id: str):
    """Permit one validated recipient lookup during the existing gift debit.

    Shop enters this only after its current-session, offer, price, friendship,
    block and balance checks inside Store.atomic(). It never changes the
    authenticated actor or permits foreign session/rename/bootstrap requests.
    """
    require_actor(sender_ps4_id)
    if store.db.atomic_depth <= 0 or not store.db.in_transaction:
        raise AccessDenied("Gift grant requires its existing atomic transaction")
    token = _GIFT_GRANT.set((store, sender_ps4_id, recipient_ps4_id))
    try:
        yield
    finally:
        _GIFT_GRANT.reset(token)


def _gift_recipient_lookup(store, ps4_id: str, username) -> bool:
    """Only the exact store's existing recipient, without profile mutation."""
    capability = _GIFT_GRANT.get()
    actor = _ACTOR.get()
    return (username is None and actor is not None and capability is not None
            and capability[0] is store and capability[1] == actor
            and capability[2] == ps4_id and store.db.atomic_depth > 0
            and store.db.in_transaction)
