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

    def authenticate(self, authorization: str | None) -> str:
        prefix = SCHEME + " "
        if not isinstance(authorization, str) or not authorization.startswith(prefix):
            raise AccessDenied("Account credential required")
        payload = authorization[len(prefix):]
        if payload.count(".") != 1:
            raise AccessDenied("Invalid account credential")
        encoded_account, token = payload.split(".", 1)
        account = _decode_account(encoded_account)
        row = self.db.execute("""SELECT salt,verifier FROM public_access_credentials
            WHERE ps4_id=? AND revoked_at IS NULL""", (account,)).fetchone()
        if row is None:
            # Do comparable password work for unknown/revoked accounts.
            _derive(token, b"\0" * 16)
            raise AccessDenied("Invalid account credential")
        if not hmac.compare_digest(_derive(token, bytes(row["salt"])), bytes(row["verifier"])):
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
