"""Internal operator API. No listener, credentials or database opens on import.

Dashboard roles are local administration policy, not game privilege flags.
All mutations enlist existing Service/Store helpers in one SQLite atomic group.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import sqlite3
import time
import uuid

from aiohttp import web

from allocation import ipv4_address, network_port
from public_access import AccessDenied, current_actor
from wire import ProtocolError

PREFIX = "/management/v1"
OPERATOR_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{7,127}\Z")
# Moderators act on individual players. Admins add server-wide availability,
# mass relocation and economy/data powers. Owners add access control and the
# staff badge (display identity). See docs/MODERATION-CAPABILITIES.md.
_MODERATOR = ("read", "moderation.ban", "moderation.kick", "moderation.mute", "moderation.reports",
              "moderation.move", "moderation.profile")
_ADMIN = _MODERATOR + ("wallet.adjust", "items.grant", "catalog.manage", "players.data", "users.rename",
                       "moderation.maintenance", "moderation.news", "moderation.server_status",
                       "moderation.disconnect")
PERMISSIONS = {
    "moderator": frozenset(_MODERATOR),
    "admin": frozenset(_ADMIN),
    "owner": frozenset(_ADMIN + ("operators.manage", "players.staff")),
}
MAX_BALANCE = 2_147_483_647
MAX_BODY = 16 * 1024


class ManagementError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code = status, code


def require(value, message, status=400, code="invalid_request"):
    if not value:
        raise ManagementError(status, code, message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def text(value, label, *, maximum=128):
    require(isinstance(value, str) and bool(value.strip()) and len(value) <= maximum
            and not any(ord(c) < 32 or ord(c) == 127 for c in value), "Invalid " + label)
    return value


def fields(body, allowed):
    require(isinstance(body, dict) and not (body.keys() - set(allowed)), "Unexpected request fields")
    return body


def strict_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate JSON field")
        result[key] = value
    return result


def secret_file(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), "A regular management token file is required")
    raw = path.read_bytes()
    require(len(raw) <= 1024, "Management token file is too large")
    raw = raw.rstrip(b"\r\n")
    require(32 <= len(raw) <= 512 and all(33 <= c <= 126 for c in raw),
            "Management token must contain 32 to 512 printable non-space characters")
    return raw


def operator_file(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 65536,
            "A regular bounded operator configuration file is required")
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=strict_object)
    except (ValueError, UnicodeError):
        raise ManagementError(400, "invalid_request", "Invalid operator configuration") from None
    require(isinstance(value, dict) and set(value) == {"operators"}
            and isinstance(value["operators"], list) and 1 <= len(value["operators"]) <= 100,
            "Operator configuration requires an explicit operator list")
    result = []
    for row in value["operators"]:
        fields(row, ("id", "role", "enabled", "password_scrypt"))
        identity, role, enabled = row.get("id"), row.get("role"), row.get("enabled", True)
        require(isinstance(identity, str) and OPERATOR_ID.fullmatch(identity)
                and isinstance(role, str) and role in PERMISSIONS and type(enabled) is bool, "Invalid operator identity, role or enabled flag")
        result.append({"id": identity, "role": role, "enabled": enabled})
    require(len({x["id"] for x in result}) == len(result), "Duplicate operator identity")
    require(any(x["enabled"] and x["role"] == "owner" for x in result), "At least one enabled owner is required")
    return result


class Management:
    def __init__(self, store, service, token, operators):
        require(isinstance(token, bytes) and 32 <= len(token) <= 512, "Explicit management token required")
        require(service.store is store, "Management must share the running backend Store and Service")
        require(current_actor() is None, "Player authentication cannot initialize management", 403, "forbidden")
        self.store, self.service, self.token = store, service, token
        self.db = store.db
        self._migrate()
        self._bootstrap(operators)
        from store_management import StoreManagement
        from player_data import PlayerData
        from player_activity import PlayerActivity
        from game_admin import GameAdmin
        self.stores = StoreManagement(self)
        self.player_data = PlayerData(self)
        self.activity = PlayerActivity(self)
        self.game_admin = GameAdmin(self)

    def _migrate(self):
        require(not self.db.in_transaction and not self.db.atomic_depth, "Management schema requires an idle Store")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS management_operators (
                operator_id TEXT PRIMARY KEY, role TEXT NOT NULL CHECK(role IN ('owner','admin','moderator')),
                enabled INTEGER NOT NULL CHECK(enabled IN (0,1)), created_at REAL NOT NULL, updated_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS management_audit (
                audit_id INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT NOT NULL UNIQUE,
                actor_id TEXT NOT NULL, actor_role TEXT NOT NULL, operation TEXT NOT NULL,
                target_id TEXT NOT NULL, reason TEXT NOT NULL, before_json TEXT NOT NULL,
                after_json TEXT NOT NULL, created_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS management_requests (
                actor_id TEXT NOT NULL, idempotency_key TEXT NOT NULL, request_sha256 TEXT NOT NULL,
                response_json TEXT NOT NULL, created_at REAL NOT NULL,
                PRIMARY KEY(actor_id,idempotency_key));
            CREATE TABLE IF NOT EXISTS management_wallet_ledger (
                ledger_id INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT NOT NULL UNIQUE,
                actor_id TEXT NOT NULL, account_id TEXT NOT NULL REFERENCES profiles(ps4_id),
                currency TEXT NOT NULL CHECK(currency IN ('crystals','np')), delta INTEGER NOT NULL,
                before_balance INTEGER NOT NULL, after_balance INTEGER NOT NULL, reason TEXT NOT NULL,
                created_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS management_operator_accounts (
                operator_id TEXT PRIMARY KEY REFERENCES management_operators(operator_id),
                account_id TEXT NOT NULL UNIQUE REFERENCES profiles(ps4_id));
            CREATE TRIGGER IF NOT EXISTS management_audit_no_update BEFORE UPDATE ON management_audit
                BEGIN SELECT RAISE(ABORT,'Management audit is append-only'); END;
            CREATE TRIGGER IF NOT EXISTS management_audit_no_delete BEFORE DELETE ON management_audit
                BEGIN SELECT RAISE(ABORT,'Management audit is append-only'); END;
            CREATE TRIGGER IF NOT EXISTS management_requests_no_update BEFORE UPDATE ON management_requests
                BEGIN SELECT RAISE(ABORT,'Management request receipts are append-only'); END;
            CREATE TRIGGER IF NOT EXISTS management_requests_no_delete BEFORE DELETE ON management_requests
                BEGIN SELECT RAISE(ABORT,'Management request receipts are append-only'); END;
            CREATE TRIGGER IF NOT EXISTS management_ledger_no_update BEFORE UPDATE ON management_wallet_ledger
                BEGIN SELECT RAISE(ABORT,'Management wallet ledger is append-only'); END;
            CREATE TRIGGER IF NOT EXISTS management_ledger_no_delete BEFORE DELETE ON management_wallet_ledger
                BEGIN SELECT RAISE(ABORT,'Management wallet ledger is append-only'); END;
        """)

    def _bootstrap(self, operators):
        require(isinstance(operators, list) and operators, "Explicit operator bootstrap required")
        cleaned = []
        for row in operators:
            fields(row, ("id", "role", "enabled", "password_scrypt"))
            require(isinstance(row.get("id"), str) and OPERATOR_ID.fullmatch(row["id"])
                    and isinstance(row.get("role"), str) and row["role"] in PERMISSIONS
                    and type(row.get("enabled")) is bool, "Invalid operator bootstrap")
            cleaned.append({"id": row["id"], "role": row["role"], "enabled": row["enabled"]})
        require(len({row["id"] for row in cleaned}) == len(cleaned), "Duplicate operator identity")
        with self.store.atomic():
            if not self.db.execute("SELECT 1 FROM management_operators LIMIT 1").fetchone():
                require(any(x.get("role") == "owner" and x.get("enabled") is True for x in operators),
                        "At least one enabled owner is required")
                for row in cleaned:
                    now = time.time()
                    self.db.execute("INSERT INTO management_operators VALUES(?,?,?,?,?)",
                                    (row["id"], row["role"], int(row["enabled"]), now, now))
                    self._audit(uuid.uuid4().hex, "bootstrap", "owner", "operators.bootstrap", row["id"],
                                "Explicit operator file initialization", None, row)
            require(self.db.execute("SELECT 1 FROM management_operators WHERE role='owner' AND enabled=1").fetchone(),
                    "No enabled management owner exists")

    def actor(self, headers, permission="read"):
        require(current_actor() is None, "Player credentials cannot authorize management", 403, "forbidden")
        authorization = headers.get("Authorization", "")
        candidate = authorization[7:].encode("utf-8") if isinstance(authorization, str) and authorization.startswith("Bearer ") else b""
        require(hmac.compare_digest(candidate, self.token), "Management authentication required", 401, "unauthorized")
        identity = headers.get("X-Management-Actor", "")
        require(isinstance(identity, str) and OPERATOR_ID.fullmatch(identity), "An enabled management operator is required", 403, "forbidden")
        row = self.db.execute("SELECT operator_id,role,enabled FROM management_operators WHERE operator_id=?", (identity,)).fetchone()
        require(row is not None and row["enabled"] == 1 and permission in PERMISSIONS[row["role"]],
                "Management permission denied", 403, "forbidden")
        return {"id": row["operator_id"], "role": row["role"]}

    def profile(self, account_id):
        text(account_id, "account ID")
        row = self.db.execute("""SELECT p.ps4_id AS account_id,p.username,p.platform,p.gender,p.created_at,
            COALESCE(s.online,0) AS online,
            (SELECT MAX(created_at) FROM sessions WHERE ps4_id=p.ps4_id) AS last_login_at,
            (SELECT MAX(updated_at) FROM presets WHERE ps4_id=p.ps4_id) AS last_avatar_save_at
            FROM profiles p LEFT JOIN profile_state s USING(ps4_id) WHERE p.ps4_id=?""", (account_id,)).fetchone()
        require(row is not None, "Account not found", 404, "not_found")
        return dict(row)

    @staticmethod
    def pagination(query):
        limit, offset = query.get("limit", "25"), query.get("cursor", "0")
        require(isinstance(limit, str) and re.fullmatch(r"[0-9]{1,3}", limit)
                and 1 <= int(limit) <= 100, "Limit must be between 1 and 100")
        require(isinstance(offset, str) and re.fullmatch(r"[0-9]{1,9}", offset), "Invalid pagination cursor")
        return int(limit), int(offset)

    def page_sql(self, sql, parameters, query):
        limit, offset = self.pagination(query)
        total = self.db.execute("SELECT COUNT(*) FROM (" + sql + ")", parameters).fetchone()[0]
        items = [dict(r) for r in self.db.execute(sql + " LIMIT ? OFFSET ?", (*parameters, limit, offset))]
        return {"items": items, "next_cursor": str(offset + limit) if offset + limit < total else None,
                "total": total, "limit": limit}

    def owned(self, account_id, query):
        self.profile(account_id)
        sql = """SELECT 'wardrobe' AS kind,item_id,gender,category,display_name,granted_at FROM entitlements WHERE ps4_id=?
            UNION ALL SELECT kind,item_id,NULL,NULL,display_name,granted_at FROM resource_entitlements WHERE ps4_id=?
            UNION ALL SELECT 'housing',item_id,NULL,NULL,display_name,granted_at FROM housing_entitlements WHERE ps4_id=?
            ORDER BY kind,item_id,gender,category"""
        result = self.page_sql(sql, (account_id,) * 3, query)
        result["items"] = self._with_assets(result["items"])
        return result

    def _with_assets(self, rows):
        """Join recovered catalog photos/labels onto ownership-shaped rows."""
        from catalog_inventory import CatalogInventory, identity
        if not hasattr(self, "_catalog_inventory"):
            self._catalog_inventory = CatalogInventory(self.service)
        assets, _offers, _stores, _counts, _summary = self._catalog_inventory.snapshot()
        lookup = {identity(row): row for row in assets}
        joined = []
        for row in rows:
            if row.get("kind") not in ("wardrobe", "companions", "locomotions", "housing") or not row.get("item_id"):
                joined.append({**row, "catalog_known": False})
                continue
            asset = lookup.get(identity(row), {})
            merged = {**asset, **row, "category": row.get("category") or asset.get("category"),
                      "gender": row.get("gender") or asset.get("gender"), "catalog_known": bool(asset)}
            # Ownership rows often store the raw ID as their name; prefer the catalog's readable one.
            if row.get("display_name") in (None, "", row.get("item_id")) and asset.get("display_name"):
                merged["display_name"] = asset["display_name"]
            joined.append(merged)
        return joined

    def feed(self, since):
        """Recent server activity for the panel's live view, oldest first, bounded."""
        now = time.time()
        since = max(since, now - 3600)
        rows = []
        q = lambda sql: [dict(r) for r in self.db.execute(sql, (since,))]
        for row in q("""SELECT 'login' AS type,s.created_at AS at,s.ps4_id AS account_id,p.username AS account_name
                FROM sessions s LEFT JOIN profiles p USING(ps4_id) WHERE s.created_at>? ORDER BY s.created_at DESC LIMIT 50"""):
            rows.append(row)
        for row in q("""SELECT 'purchase' AS type,s.created_at AS at,s.ps4_id AS account_id,p.username AS account_name,
                s.source,o.name AS item_name,o.kind FROM shop_owned s LEFT JOIN profiles p USING(ps4_id)
                LEFT JOIN shop_offers o USING(offer_id) WHERE s.created_at>? ORDER BY s.created_at DESC LIMIT 50"""):
            rows.append(row)
        for row in q("""SELECT 'staff' AS type,created_at AS at,operation,target_id,actor_id,reason
                FROM management_audit WHERE created_at>? ORDER BY audit_id DESC LIMIT 50"""):
            rows.append(row)
        for row in q("""SELECT 'report' AS type,r.created_at AS at,r.target,s.ps4_id AS account_id,p.username AS account_name
                FROM local_reports r LEFT JOIN sessions s ON s.guid=r.guid LEFT JOIN profiles p ON p.ps4_id=s.ps4_id
                WHERE r.created_at>? ORDER BY r.created_at DESC LIMIT 50"""):
            rows.append(row)
        self._name_targets([r for r in rows if r["type"] == "staff"])
        rows.sort(key=lambda r: r["at"] or 0)
        return {"items": rows[-100:], "server_time": now,
                "online": self.db.execute("SELECT COUNT(*) FROM profile_state WHERE online=1").fetchone()[0]}

    def _presence(self, account_id, profile):
        """Scene the player's current session is allocated to, if they are online."""
        if not profile.get("online"):
            return {"current_scene": None, "current_instance_id": None, "current_scene_owner": None}
        row = self.db.execute("""SELECT l.psidglobal,l.instance_id FROM sessions s JOIN allocations l USING(guid)
            WHERE s.ps4_id=? ORDER BY l.allocated_at DESC LIMIT 1""", (account_id,)).fetchone()
        if row is None:
            return {"current_scene": None, "current_instance_id": None, "current_scene_owner": None}
        owner = self.db.execute("SELECT owner_ps4_id FROM housing_spaces WHERE instance_id=?", (row[1],)).fetchone()             if self.db.execute("SELECT 1 FROM sqlite_schema WHERE name='housing_spaces'").fetchone() else None
        return {"current_scene": row[0], "current_instance_id": row[1],
                "current_scene_owner": self._usernames([owner[0]]).get(owner[0]) if owner else None}

    def _usernames(self, ids):
        ids = sorted({value for value in ids if isinstance(value, str) and value})
        if not ids:
            return {}
        marks = ",".join("?" * len(ids))
        return dict(self.db.execute("SELECT ps4_id,username FROM profiles WHERE ps4_id IN (" + marks + ")", ids))

    def _name_accounts(self, rows, key="account_id", name="account_name"):
        names = self._usernames(row.get(key) for row in rows)
        for row in rows:
            row[name] = names.get(row.get(key))
        return rows

    def _name_targets(self, rows):
        """Readable target names for audit/moderation rows; IDs stay for linking."""
        targets = [row.get("target_id") for row in rows]
        ids = sorted({t for t in targets if isinstance(t, str) and t})
        players = self._usernames(ids)

        def lookup(table, key):
            if not ids:
                return {}
            return dict(self.db.execute("SELECT " + key + ",name FROM " + table + " WHERE " + key
                                        + " IN (" + ",".join("?" * len(ids)) + ")", ids))
        stores, offers = lookup("shop_catalogs", "shop_id"), lookup("shop_offers", "offer_id")
        for row in rows:
            target, operation = row.get("target_id"), str(row.get("operation") or "")
            if operation.startswith("operators."):
                kind, label = "operator", target
            elif operation.startswith("report."):
                kind, label = "report", None
            elif operation.startswith("moderation.news") or operation.startswith("news."):
                kind, label = "news", None
            elif operation.startswith("moderation.maintenance") or operation.startswith("maintenance."):
                kind, label = "server", "Maintenance notice"
            elif operation in ("moderation.server_status", "server.status"):
                kind, label = "server", "Server availability"
            elif operation in ("moderation.disconnect", "disconnect.all", "instance.evacuate"):
                kind, label = ("server", "All connected players") if target in ("server", "global") else ("instance", target)
            elif target in players:
                kind, label = "player", players[target]
            elif target in stores:
                kind, label = "store", stores[target]
            elif target in offers:
                kind, label = "listing", offers[target]
            else:
                kind, label = None, None
            row["target_type"], row["target_name"] = kind, label
        return rows

    def read(self, tail, query, actor):
        if tail == "health":
            return {"service": "nebula-management", "status": "ok", "schema_version": 1}
        if tail == "me":
            return {**actor, "permissions": sorted(PERMISSIONS[actor["role"]])}
        if tail == "roles":
            return {"items": [{"id": role, "permissions": sorted(permissions)}
                              for role, permissions in PERMISSIONS.items()]}
        parts = tail.split("/")
        if self.game_admin.handles_read(parts):
            return self.game_admin.read(parts, query, actor)
        if tail == "capabilities":
            return {**self.game_admin.capabilities(actor, PERMISSIONS),
                    "dashboard_roles": list(PERMISSIONS), "game_roles_supported": [],
                    "game_privilege_mutation_supported": False, "game_developer_flag_grant_supported": False,
                    "grant_kinds": ["wardrobe", "companions", "locomotions", "housing", "personal_spaces", "offer"],
                    "currency_kinds": ["crystals", "np"], "historical_purchase_price_retained": False,
                    "public_access_credential_management_supported": False,
                    "catalog_management_supported": True,
                    "store_types": [{"value": 0, "kind": "wardrobe", "label": "Clothing & customization"},
                                    {"value": 1, "kind": "companions", "label": "Companions"},
                                    {"value": 2, "kind": "housing", "label": "Furniture"},
                                    {"value": 3, "kind": "locomotions", "label": "Locomotions"}],
                    "moderation_supported": True,
                    "moderation_actions": ["ban", "unban", "kick", "mute", "unmute", "move",
                                           "clear-profile"],
                    "server_status_supported": True, "player_relocation_supported": True,
                    "announcement_supported": False,
                    "news_supported": True, "staff_labels_supported": True,
                    "operator_account_links_supported": True,
                    "moderation_delivery": "Committed policy is not a client display acknowledgement"}
        if tail == "moderation/status":
            return {"maintenance_minutes": self.service.moderation.maintenance_minutes(),
                    "server_status": self.service.moderation.server_status()["status"],
                    "game_roles_supported": [], "announcement_supported": False}
        if tail == "moderation/events":
            result = self.page_sql("SELECT * FROM moderation_events ORDER BY event_id DESC", (), query)
            for row in result["items"]:
                row["before"] = json.loads(row.pop("before_json"))
                row["after"] = json.loads(row.pop("after_json"))
            self._name_targets(result["items"])
            return result
        if tail == "moderation/reports":
            limit, offset = self.pagination(query)
            total = self.db.execute("SELECT COUNT(*) FROM local_reports").fetchone()[0]
            items = self._name_accounts(self.service.moderation.reports(limit=limit, offset=offset),
                                        "reporter_account_id", "reporter_name")
            # A report names a player by username; resolve it only when unambiguous.
            for item in items:
                matches = self.db.execute("SELECT ps4_id FROM profiles WHERE lower(username)=lower(?) LIMIT 2",
                                          (item.get("target") or "",)).fetchall()
                item["target_account_id"] = matches[0][0] if len(matches) == 1 else None
            return {"items": items, "total": total, "limit": limit,
                    "next_cursor": str(offset + limit) if offset + limit < total else None}
        if tail == "moderation/active":
            now = self.service.moderation._now()
            result = self.page_sql("""SELECT m.ps4_id AS account_id,p.username AS account_name,
                m.ban_enabled=1 AND (m.ban_expires_at IS NULL OR m.ban_expires_at>?) AS banned,m.ban_expires_at,m.ban_reason,
                m.mute_enabled=1 AND (m.mute_expires_at IS NULL OR m.mute_expires_at>?) AS muted,m.mute_expires_at,m.mute_reason,
                (SELECT actor_id FROM moderation_events e WHERE e.target_id=m.ps4_id ORDER BY event_id DESC LIMIT 1) AS last_actor_id,
                (SELECT created_at FROM moderation_events e WHERE e.target_id=m.ps4_id ORDER BY event_id DESC LIMIT 1) AS last_action_at
                FROM moderation_accounts m LEFT JOIN profiles p USING(ps4_id)
                WHERE (m.ban_enabled=1 AND (m.ban_expires_at IS NULL OR m.ban_expires_at>?))
                   OR (m.mute_enabled=1 AND (m.mute_expires_at IS NULL OR m.mute_expires_at>?))
                ORDER BY last_action_at DESC,account_id""", (now, now, now, now), query)
            return result
        if tail == "feed":
            since = query.get("since", "0")
            require(isinstance(since, str) and re.fullmatch(r"[0-9]{1,12}(?:\.[0-9]{1,20})?", since), "Invalid feed cursor")
            return self.feed(float(since))
        if tail == "moderation/news":
            return self.page_sql("SELECT * FROM moderation_news ORDER BY created_at DESC,news_id DESC", (), query)
        if tail == "stats":
            scalar = lambda sql: self.db.execute(sql).fetchone()[0]
            return {"users": scalar("SELECT COUNT(*) FROM profiles"),
                    "online": scalar("SELECT COUNT(*) FROM profile_state WHERE online=1"),
                    "purchases": scalar("SELECT COUNT(*) FROM shop_owned WHERE source='buy'"),
                    "gift_grants": scalar("SELECT COUNT(*) FROM shop_owned WHERE source='gift'"),
                    "admin_offer_grants": scalar("SELECT COUNT(*) FROM shop_owned WHERE source='admin'"),
                    "crystals": scalar("SELECT COALESCE(SUM(crystals),0) FROM shop_wallets"),
                    "np": scalar("SELECT COALESCE(SUM(np),0) FROM shop_wallets"),
                    "audit_entries": scalar("SELECT COUNT(*) FROM management_audit"),
                    "banned": self.db.execute("SELECT COUNT(*) FROM moderation_accounts WHERE ban_enabled=1 AND (ban_expires_at IS NULL OR ban_expires_at>?)", (self.service.moderation._now(),)).fetchone()[0],
                    "muted": self.db.execute("SELECT COUNT(*) FROM moderation_accounts WHERE mute_enabled=1 AND (mute_expires_at IS NULL OR mute_expires_at>?)", (self.service.moderation._now(),)).fetchone()[0],
                    "open_reports": scalar("SELECT COUNT(*) FROM moderation_report_index i LEFT JOIN moderation_report_reviews v USING(report_id) WHERE COALESCE(v.status,'open')='open'")}
        if tail == "users":
            search = query.get("q", "")
            require(isinstance(search, str) and len(search) <= 128, "Invalid account search")
            # instr gives literal substring matching; %, _ and SQL syntax are data.
            status = query.get("status", "")
            require(status in ("", "online", "banned", "muted", "restricted"), "Invalid player status filter")
            now = self.service.moderation._now()
            sql = """SELECT * FROM (SELECT p.ps4_id AS account_id,p.username,p.platform,p.gender,p.created_at,
                COALESCE(s.online,0) AS online,COALESCE(w.crystals,0) AS crystals,COALESCE(w.np,0) AS np,
                (SELECT MAX(created_at) FROM sessions WHERE ps4_id=p.ps4_id) AS last_login_at,
                COALESCE(m.ban_enabled=1 AND (m.ban_expires_at IS NULL OR m.ban_expires_at>?),0) AS banned,
                COALESCE(m.mute_enabled=1 AND (m.mute_expires_at IS NULL OR m.mute_expires_at>?),0) AS muted
                FROM profiles p LEFT JOIN profile_state s USING(ps4_id) LEFT JOIN shop_wallets w USING(ps4_id)
                LEFT JOIN moderation_accounts m USING(ps4_id)
                WHERE instr(lower(p.ps4_id),lower(?))>0 OR instr(lower(p.username),lower(?))>0)"""
            sql += {"": "", "online": " WHERE online=1", "banned": " WHERE banned=1", "muted": " WHERE muted=1",
                    "restricted": " WHERE banned=1 OR muted=1"}[status]
            return self.page_sql(sql + " ORDER BY online DESC,COALESCE(last_login_at,created_at) DESC,account_id",
                                 (now, now, search, search), query)
        if tail == "operators":
            require(actor["role"] == "owner", "Only an owner may list dashboard operators", 403, "forbidden")
            result = self.page_sql("SELECT o.operator_id AS id,o.role,o.enabled,o.created_at,o.updated_at,l.account_id FROM management_operators o LEFT JOIN management_operator_accounts l USING(operator_id) ORDER BY o.operator_id", (), query)
            self._name_accounts(result["items"])
            return result
        if tail == "audit":
            result = self.page_sql("SELECT * FROM management_audit ORDER BY audit_id DESC", (), query)
            for row in result["items"]:
                row["before"] = json.loads(row.pop("before_json"));row["after"] = json.loads(row.pop("after_json"))
            self._name_targets(result["items"])
            return result
        if tail == "transactions":
            result = self.page_sql("SELECT * FROM management_wallet_ledger ORDER BY ledger_id DESC", (), query)
            self._name_accounts(result["items"])
            return result
        if tail == "purchases":
            result = self.page_sql("""SELECT s.ps4_id AS account_id,p.username AS account_name,s.offer_id,s.source,
                s.granted_by,s.created_at,o.kind,o.item_id,o.gender,o.category,o.name,o.shop_id,c.name AS store_name,
                o.crystals AS current_offer_crystals,o.np AS current_offer_np FROM shop_owned s
                LEFT JOIN profiles p USING(ps4_id) LEFT JOIN shop_offers o USING(offer_id)
                LEFT JOIN shop_catalogs c ON c.shop_id=o.shop_id ORDER BY s.created_at DESC,s.offer_id""", (), query)
            result["items"] = self._with_assets(result["items"])
            return result
        if tail == "catalog":
            return self.catalog(query)
        parts = tail.split("/")
        if tail == "stores" or (len(parts) == 2 and parts[0] in ("stores", "store-offers")):
            return self.stores.read(tail, query)
        if parts[0] == "monitor" or (len(parts) >= 3 and parts[0] == "users" and parts[2] in ("sessions", "logins", "ips")):
            if parts[0] == "users":
                self.profile(parts[1])
            return self.activity.read(parts, query)
        if len(parts) >= 3 and parts[0] == "users" and parts[2] == "character":
            self.profile(parts[1])
            return self.player_data.read(parts[1], parts[3:], query)
        if len(parts) in (2, 3) and parts[0] == "users":
            account_id = parts[1];profile = self.profile(account_id)
            if len(parts) == 2:
                moderation = self.service.moderation.status(account_id)
                return {**profile, "wallet": self.service.shop.wallet(account_id),
                        "banned": moderation["banned"], "muted": moderation["muted"],
                        "ban_expires_at": moderation["ban_expires_at"], "mute_expires_at": moderation["mute_expires_at"],
                        "staff_label": moderation["staff_label"], **self._presence(account_id, profile)}
            if parts[2] == "wallet":
                return self.service.shop.wallet(account_id)
            if parts[2] == "moderation":
                return {**self.service.moderation.status(account_id), "username": profile["username"]}
            if parts[2] == "owned":
                return self.owned(account_id, query)
            if parts[2] == "transactions":
                return self.page_sql("SELECT * FROM management_wallet_ledger WHERE account_id=? ORDER BY ledger_id DESC", (account_id,), query)
            if parts[2] == "audit":
                result = self.page_sql("""SELECT * FROM management_audit WHERE target_id=? AND operation IN
                    ('wallet.adjust','items.grant','users.rename','moderation.ban','moderation.kick','moderation.mute','moderation.unban','moderation.unmute','players.staff','players.data','moderation.move','moderation.profile')
                    ORDER BY audit_id DESC""", (account_id,), query)
                for row in result["items"]:
                    row["before"] = json.loads(row.pop("before_json"))
                    row["after"] = json.loads(row.pop("after_json"))
                return result
            if parts[2] == "purchases":
                result = self.page_sql("""SELECT s.offer_id,s.source,s.granted_by,s.created_at,o.kind,o.item_id,o.gender,
                    o.category,o.name,o.shop_id,c.name AS store_name,
                    o.crystals AS current_offer_crystals,o.np AS current_offer_np FROM shop_owned s
                    LEFT JOIN shop_offers o USING(offer_id) LEFT JOIN shop_catalogs c ON c.shop_id=o.shop_id
                    WHERE s.ps4_id=? ORDER BY s.created_at DESC,s.offer_id""", (account_id,), query)
                result["items"] = self._with_assets(result["items"])
                for item in result["items"]:
                    item["historical_price_known"] = False
                return result
        raise ManagementError(404, "not_found", "Management route not found")

    def catalog(self, query):
        from catalog_inventory import CatalogInventory, KINDS, NOTE
        kind = query.get("kind", "wardrobe"); search = query.get("q", "")
        require(kind in (*KINDS, "offer", "all", "shop_artwork"), "Unsupported grant kind")
        require(isinstance(search, str) and len(search) <= 128, "Invalid item search")
        for key in ("gender", "category", "store_id"):
            require(isinstance(query.get(key, ""), str) and len(query.get(key, "")) <= 128,
                    "Invalid catalog filter")
        if not hasattr(self, "_catalog_inventory"):
            self._catalog_inventory = CatalogInventory(self.service)
        assets, offers, stores, counts, summary = self._catalog_inventory.snapshot()
        by_item = {(r["kind"], r["item_id"], r.get("gender") or "",
                    (r.get("category") or "") if r["kind"] == "wardrobe" else ""): r for r in assets}
        if kind == "offer":
            values = []
            for offer in offers:
                key = (offer["kind"], offer["item_id"], offer.get("gender") or "",
                       (offer.get("category") or "") if offer["kind"] == "wardrobe" else "")
                asset = by_item.get(key, {})
                values.append({**asset, **offer, "offers": [offer],
                               "thumbnail_path": offer["image_path"],
                               "historical_price_known": False})
        elif kind == "shop_artwork":
            values = self._catalog_inventory.artwork
        else:
            values = [r for r in assets if kind == "all" or r["kind"] == kind]
        categories = sorted({(r["category"], r["category_label"]) for r in values if r.get("category")})
        genders = sorted({r["gender"] for r in values if r.get("gender")})
        def matches(row):
            if query.get("gender") and row.get("gender") != query["gender"]: return False
            if query.get("category") and row.get("category") != query["category"]: return False
            if query.get("store_id") and not any(o["shop_id"] == query["store_id"] for o in row.get("offers", [])): return False
            searchable = [row.get(k) or "" for k in ("item_id", "offer_id", "name", "readable_name", "resource_path", "category", "category_label", "bundle", "asset_path")]
            searchable.extend(o["shop_name"] for o in row.get("offers", []))
            return search.casefold() in " ".join(searchable).casefold()
        values = [r for r in values if matches(r)]
        values.sort(key=lambda r: (r.get("offer_id") or "", r.get("kind") or "", r.get("item_id") or "", r.get("gender") or "", r.get("category") or ""))
        limit, offset = self.pagination(query)
        return {"items": values[offset:offset + limit], "total": len(values), "limit": limit,
                "next_cursor": str(offset + limit) if offset + limit < len(values) else None,
                "counts": counts, "coverage": summary, "metadata_note": NOTE,
                "field_availability": self._catalog_inventory.field_availability,
                "filters": {"genders": genders, "categories": [{"value": k, "label": v} for k, v in categories],
                            "stores": [{"id": r["shop_id"], "name": r["name"], "type_shop": r["type_shop"]} for r in stores.values()]}}

    def _audit(self, request_id, actor_id, actor_role, operation, target, reason, before, after):
        cursor = self.db.execute("""INSERT INTO management_audit
            (request_id,actor_id,actor_role,operation,target_id,reason,before_json,after_json,created_at)
            VALUES(?,?,?,?,?,?,?,?,?)""", (request_id, actor_id, actor_role, operation, target, reason, canonical(before), canonical(after), time.time()))
        return cursor.lastrowid

    def command(self, tail, body, headers):
        result = self._command(tail, body, headers)
        # Database authority commits first. Replays also retry a failed snapshot
        # publication without duplicating the audited mutation.
        publish = getattr(self.service, "publish_runtime_state", None)
        if publish is not None:
            try:
                publish()
                result["runtime_sync"] = "snapshot_published"
            except (OSError, ValueError, ProtocolError):
                result["runtime_sync"] = "pending"
        return result

    def _command(self, tail, body, headers):
        parts = tail.split("/")
        game_route = self.game_admin.route(parts)
        if game_route is not None:
            permission, target = game_route
        elif len(parts) == 3 and parts[0] == "users":
            permission = {"wallet-adjustments": "wallet.adjust", "items": "items.grant", "rename": "users.rename",
                          "ban": "moderation.ban", "unban": "moderation.ban", "kick": "moderation.kick",
                          "mute": "moderation.mute", "unmute": "moderation.mute", "staff-label": "players.staff"}.get(parts[2])
            target = parts[1]
        elif len(parts) >= 4 and parts[0] == "users" and parts[2] == "character":
            permission, target = "players.data", parts[1]
        elif tail == "moderation/maintenance":
            permission, target = "moderation.maintenance", "server"
        elif len(parts) == 3 and parts[:2] == ["moderation", "reports"]:
            permission, target = "moderation.reports", parts[2]
        elif tail == "moderation/news" or (len(parts) == 4 and parts[:2] == ["moderation", "news"] and parts[3] == "archive"):
            permission, target = "moderation.news", parts[2] if len(parts) == 4 else "server"
        elif len(parts) == 2 and parts[0] == "operators":
            permission, target = "operators.manage", parts[1]
        elif len(parts) == 3 and parts[0] == "operators" and parts[2] == "player-link":
            permission, target = "operators.manage", parts[1]
        elif len(parts) == 2 and parts[0] in ("stores", "store-offers"):
            permission, target = "catalog.manage", parts[1]
        else:
            permission = None
        require(permission is not None, "Management route not found", 404, "not_found")
        actor = self.actor(headers, permission)
        key = headers.get("Idempotency-Key", "")
        require(isinstance(key, str) and KEY.fullmatch(key), "A bounded Idempotency-Key of at least eight characters is required")
        # Moderation and access changes need a stated reason; routine economy,
        # catalog and save-data edits are still audited but may omit it.
        if permission.startswith("moderation.") or permission in ("players.staff", "operators.manage")                 or body.get("reason") not in (None, ""):
            reason = text(body.get("reason"), "audit reason", maximum=512)
        else:
            reason = "No reason given"
        fingerprint = hashlib.sha256(canonical({"method": "POST", "route": tail, "body": body}).encode()).hexdigest()
        with self.store.atomic():
            actor = self.actor(headers, permission)  # Recheck authorization under the write lock.
            old = self.db.execute("SELECT request_sha256,response_json FROM management_requests WHERE actor_id=? AND idempotency_key=?", (actor["id"], key)).fetchone()
            if old is not None:
                require(hmac.compare_digest(old["request_sha256"], fingerprint), "Idempotency key was used for another command", 409, "conflict")
                result = json.loads(old["response_json"]);result["replayed"] = True
                return result
            request_id = uuid.uuid4().hex
            if game_route is not None:
                before, after, changed = self.game_admin.command(parts, body, actor, request_id, reason)
            elif permission == "wallet.adjust":
                before, after, changed = self._wallet(target, body, actor, request_id, reason)
            elif permission == "items.grant":
                before, after, changed = self._grant(target, body, actor)
            elif permission == "users.rename":
                before, after, changed = self._rename(target, body)
            elif permission == "catalog.manage":
                before, after, changed = self.stores.change(parts[0], target, body)
            elif permission == "players.data":
                self.profile(target)
                before, after, changed = self.player_data.change(target, parts[3:], body, actor, request_id)
            elif permission == "players.staff":
                fields(body, ("label", "reason"));self.profile(target)
                before, after, changed = self.service.moderation.set_staff_label(
                    target, body.get("label"), reason=reason, actor=actor, request_id=request_id)
            elif permission.startswith("moderation."):
                if permission == "moderation.reports":
                    fields(body, ("status", "note", "reason"))
                    before, after, changed = self.service.moderation.review_report(
                        target, body.get("status"), body.get("note", ""),
                        reason=reason, actor=actor, request_id=request_id)
                elif permission == "moderation.news":
                    arguments = {"reason": reason, "actor": actor, "request_id": request_id}
                    if len(parts) == 4:
                        fields(body, ("reason",))
                        before, after, changed = self.service.moderation.archive_news(target, **arguments)
                    else:
                        fields(body, ("text", "expires_at", "reason"))
                        before, after, changed = self.service.moderation.publish_news(
                            body.get("text"), body.get("expires_at"), **arguments)
                else:
                    before, after, changed = self._moderate(target, parts[-1], body, actor, request_id, reason)
            elif len(parts) == 3 and parts[0] == "operators" and parts[2] == "player-link":
                before, after, changed = self._operator_player_link(target, body)
            else:
                before, after, changed = self._operator(target, body)
            # Record the action taken, not just the permission (unban/unmute share ban/mute permissions).
            operation = ("moderation." + parts[2]) if parts[0] == "users" and parts[2] in ("unban", "unmute") else permission
            audit_id = self._audit(request_id, actor["id"], actor["role"], operation, target, reason, before, after)
            result = {"request_id": request_id, "audit_id": audit_id, "operation": permission,
                      "account_id": target if parts[0] == "users" else None,
                      "operator_id": target if parts[0] == "operators" else None,
                      "store_id": target if parts[0] == "stores" else None,
                      "offer_id": target if parts[0] == "store-offers" else None,
                      "before": before, "after": after, "changed": changed, "replayed": False}
            self.db.execute("INSERT INTO management_requests VALUES(?,?,?,?,?)", (actor["id"], key, fingerprint, canonical(result), time.time()))
            return result

    def _moderate(self, target, action, body, actor, request_id, reason):
        moderation = self.service.moderation
        if action == "maintenance":
            fields(body, ("minutes", "reason"))
            return moderation.set_maintenance(body.get("minutes"), reason=reason,
                                              actor=actor, request_id=request_id)
        self.profile(target)
        self.protect_target(target, actor)
        fields(body, ("expires_at", "reason") if action in ("ban", "mute") else ("reason",))
        arguments = {"reason": reason, "actor": actor, "request_id": request_id}
        if action in ("ban", "mute"):
            arguments["expires_at"] = body.get("expires_at")
        return getattr(moderation, action)(target, **arguments)

    def protect_target(self, target, actor):
        """Explicitly linked enabled operators are only actionable by a higher rank (or an owner)."""
        linked_operator = self.db.execute("SELECT o.role FROM management_operators o JOIN management_operator_accounts l USING(operator_id) WHERE l.account_id=? AND o.enabled=1", (target,)).fetchone()
        if linked_operator is not None and actor["role"] != "owner":
            rank = {"moderator": 1, "admin": 2, "owner": 3}
            require(rank[actor["role"]] > rank[linked_operator["role"]],
                    "An operator may not sanction an equal or higher enabled operator", 403, "forbidden")

    def _operator_player_link(self, target, body):
        fields(body, ("account_id", "reason"))
        require("account_id" in body, "An explicit account ID or null is required")
        require(self.db.execute("SELECT 1 FROM management_operators WHERE operator_id=?", (target,)).fetchone(),
                "Dashboard operator not found", 404, "not_found")
        account_id = body.get("account_id")
        row = self.db.execute("SELECT account_id FROM management_operator_accounts WHERE operator_id=?", (target,)).fetchone()
        before = {"operator_id": target, "account_id": row[0] if row else None}
        if account_id is None:
            self.db.execute("DELETE FROM management_operator_accounts WHERE operator_id=?", (target,))
        else:
            self.profile(account_id)
            conflict = self.db.execute("SELECT operator_id FROM management_operator_accounts WHERE account_id=?", (account_id,)).fetchone()
            require(conflict is None or conflict[0] == target, "Player is linked to another operator", 409, "conflict")
            self.db.execute("INSERT INTO management_operator_accounts VALUES(?,?) ON CONFLICT(operator_id) DO UPDATE SET account_id=excluded.account_id", (target, account_id))
        after = {"operator_id": target, "account_id": account_id}
        return before, after, before != after

    def _wallet(self, target, body, actor, request_id, reason):
        fields(body, ("currency", "delta", "reason"));self.profile(target)
        currency, delta = body.get("currency"), body.get("delta")
        require(currency in ("crystals", "np") and type(delta) is int and -MAX_BALANCE <= delta <= MAX_BALANCE and delta != 0,
                "A supported currency and nonzero signed integer delta are required")
        before = self.service.shop.wallet(target);balance = before[currency] + delta
        require(0 <= balance <= MAX_BALANCE, "Wallet adjustment exceeds the supported balance range", 409, "conflict")
        values = dict(before);values[currency] = balance
        after = self.service.shop.set_wallet(target, values["crystals"], values["np"], values["level"])
        self.db.execute("""INSERT INTO management_wallet_ledger
            (request_id,actor_id,account_id,currency,delta,before_balance,after_balance,reason,created_at)
            VALUES(?,?,?,?,?,?,?,?,?)""", (request_id, actor["id"], target, currency, delta, before[currency], after[currency], reason, time.time()))
        return before, after, True

    def _grant(self, target, body, actor):
        fields(body, ("kind", "item_id", "offer_id", "gender", "category", "reason"));self.profile(target)
        kind = body.get("kind")
        if kind == "offer":
            require(set(body) <= {"kind", "offer_id", "reason"}, "Offer grants accept an offer ID only")
            offer_id = text(body.get("offer_id"), "offer ID")
            offer = self.db.execute("SELECT * FROM shop_offers WHERE offer_id=?", (offer_id,)).fetchone()
            require(offer is not None and offer["active"] == 1, "Active configured offer not found", 404, "not_found")
            offer = dict(offer);owned = self.service.shop._underlying_owned(target, offer)
            before = {"kind": kind, "offer_id": offer_id, "owned": owned}
            changed = self.service.shop._record_grant(target, offer, "admin", actor["id"])
            return before, {**before, "owned": True}, changed
        require("offer_id" not in body, "Asset grants do not accept an offer ID")
        item_id = text(body.get("item_id"), "item ID")
        if kind == "wardrobe":
            asset = self.service.catalog.resolve(item_id, body.get("gender"), body.get("category"))
            require(not any(row["item_id"] == item_id for row in self.service.wardrobe_removal_sentinels.values()),
                    "Wardrobe removal controls are not grantable items")
            key = {"kind": kind, "item_id": item_id, "gender": asset["gender"], "category": asset["category"]}
            owned = self.db.execute("SELECT 1 FROM entitlements WHERE ps4_id=? AND item_id=? AND gender=? AND category=?", (target, item_id, asset["gender"], asset["category"])).fetchone() is not None
            if not owned:
                self.store.grant(target, asset)
        elif kind in ("companions", "locomotions"):
            require(not ({"gender", "category"} & body.keys()), "Resource grant has no gender/category")
            self.service.resources.catalog.resolve(kind, item_id);key = {"kind": kind, "item_id": item_id}
            owned = self.db.execute("SELECT 1 FROM resource_entitlements WHERE ps4_id=? AND kind=? AND item_id=?", (target, kind, item_id)).fetchone() is not None
            if not owned:
                self.service.resources.grant(target, kind, item_id)
        elif kind == "housing":
            require(not ({"gender", "category"} & body.keys()), "Housing grant has no gender/category")
            require(item_id in self.service.housing.catalog, "Shipped housing item not found", 404, "not_found")
            key = {"kind": kind, "item_id": item_id}
            owned = self.db.execute("SELECT 1 FROM housing_entitlements WHERE ps4_id=? AND item_id=?", (target, item_id)).fetchone() is not None
            if not owned:
                self.service.housing.grant_item(target, item_id)
        elif kind == "personal_spaces":
            # Apartment by its shop ID: the same binding a purchase creates.
            require(not ({"gender", "category"} & body.keys()), "Apartment grant has no gender/category")
            from space_shop import SHOP_SPACES
            require(item_id in SHOP_SPACES, "Shipped apartment not found", 404, "not_found")
            space = SHOP_SPACES[item_id]["logical_space_key"]
            key = {"kind": kind, "item_id": item_id, "space_key": space}
            owned = self.service.apartments.owned(target, space) is not None
            if not owned:
                self.service.apartments.bind(target, space)
        else:
            raise ManagementError(400, "invalid_request", "Unsupported grant kind")
        return {**key, "owned": owned}, {**key, "owned": True}, not owned

    def _rename(self, target, body):
        fields(body, ("username", "reason"));before = self.profile(target)
        username = text(body.get("username"), "username", maximum=64)
        if before["username"] != username:
            # The original Store method preserves inbound social relationships
            # and rejects ambiguous identities inside this outer transaction.
            self.store.account(target, username, before["platform"])
        after = self.profile(target)
        return before, after, before != after

    def _operator(self, target, body):
        fields(body, ("role", "enabled", "reason"))
        require(OPERATOR_ID.fullmatch(target), "Invalid operator ID")
        role, enabled = body.get("role"), body.get("enabled")
        require(isinstance(role, str) and role in PERMISSIONS and type(enabled) is bool, "Explicit role and enabled flag required")
        row = self.db.execute("SELECT operator_id AS id,role,enabled FROM management_operators WHERE operator_id=?", (target,)).fetchone()
        before = dict(row) if row is not None else None
        now = time.time()
        self.db.execute("""INSERT INTO management_operators VALUES(?,?,?,?,?)
            ON CONFLICT(operator_id) DO UPDATE SET role=excluded.role,enabled=excluded.enabled,updated_at=excluded.updated_at""", (target, role, int(enabled), now, now))
        require(self.db.execute("SELECT 1 FROM management_operators WHERE role='owner' AND enabled=1").fetchone(),
                "Cannot disable or demote the last enabled owner", 409, "conflict")
        after = {"id": target, "role": role, "enabled": int(enabled)}
        return before, after, before != after

    async def handle(self, request):
        try:
            require("Origin" not in request.headers, "Management is a server-to-server API", 403, "forbidden")
            actor = self.actor(request.headers)
            tail = request.match_info.get("tail", "")
            if request.method == "GET":
                result = self.read(tail, request.query, actor)
            elif request.method == "POST":
                require(request.content_type == "application/json", "JSON content type required", 415, "invalid_request")
                require(request.content_length is None or request.content_length <= MAX_BODY, "Request body is too large", 413, "invalid_request")
                raw = await request.read();require(len(raw) <= MAX_BODY, "Request body is too large", 413, "invalid_request")
                try:
                    body = json.loads(raw.decode("utf-8"), object_pairs_hook=strict_object,
                                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Non-finite JSON")))
                except (ValueError, UnicodeError):
                    raise ManagementError(400, "invalid_request", "Invalid JSON body") from None
                require(isinstance(body, dict), "JSON object required")
                result = self.command(tail, body, request.headers)
            else:
                raise ManagementError(405, "method_not_allowed", "Use GET or POST for this API")
            return web.json_response({"data": result}, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
        except ManagementError as error:
            return web.json_response({"error": {"code": error.code, "message": str(error)}}, status=error.status,
                                     headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
        except (ProtocolError, AccessDenied) as error:
            status = error.status if isinstance(error, ProtocolError) else 403
            code = {403: "forbidden", 404: "not_found", 409: "conflict"}.get(status, "invalid_request")
            return web.json_response({"error": {"code": code, "message": str(error)}}, status=status, headers={"Cache-Control": "no-store"})
        except web.HTTPRequestEntityTooLarge:
            return web.json_response({"error": {"code": "invalid_request", "message": "Request body is too large"}}, status=413)
        except sqlite3.OperationalError:
            return web.json_response({"error": {"code": "temporarily_unavailable", "message": "Retry this command with the same idempotency key"}}, status=503, headers={"Cache-Control": "no-store"})
        except sqlite3.IntegrityError:
            return web.json_response({"error": {"code": "conflict", "message": "The command could not be committed"}}, status=409, headers={"Cache-Control": "no-store"})


async def start_management(backend, environ=None):
    """Called only by explicit running Backend startup; separate internal port."""
    environ = os.environ if environ is None else environ
    token_path, operators_path = environ.get("NEBULA_ADMIN_TOKEN_FILE"), environ.get("NEBULA_ADMIN_OPERATORS_FILE")
    if not token_path and not operators_path:
        return None
    require(token_path and operators_path, "Both management secret files must be configured")
    bind = ipv4_address(environ.get("NEBULA_ADMIN_BIND", "127.0.0.1"), wildcard=True)
    port_text = environ.get("NEBULA_ADMIN_PORT", "8090")
    require(isinstance(port_text, str) and re.fullmatch(r"[0-9]{1,5}", port_text), "Invalid management port")
    port = network_port(int(port_text))
    require(port != backend.port, "Management must use a separate internal port")
    controller = Management(backend.store, backend.service, secret_file(token_path), operator_file(operators_path))
    app = web.Application(client_max_size=MAX_BODY)
    app.router.add_route("*", PREFIX + "/{tail:.*}", controller.handle)
    runner = web.AppRunner(app, access_log=None)
    try:
        await runner.setup()
        await web.TCPSite(runner, bind, port).start()
    except BaseException:
        await runner.cleanup()
        raise
    return runner


async def stop_management(backend):
    runner = getattr(backend, "management_runner", None)
    if runner is not None:
        await runner.cleanup()
        backend.management_runner = None
