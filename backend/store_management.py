"""Audited operator configuration of the reconstructed native store catalog.

This module owns no listener. Management supplies its existing transaction,
authorization, idempotency and append-only audit boundaries. Asset identities
and thumbnail/native routing fields are always derived from recovered catalogs.
"""
from __future__ import annotations

import json
import re
import time
import unicodedata

from catalog_inventory import CatalogInventory, POLICY, SHOP_IMAGE_PREFIX, STORE_SPECS, identity
from management import MAX_BALANCE, fields, require


IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
# First kind per native store type: apartments share the HOUSING type with furniture.
TYPE_KINDS = {}
for _kind, _spec in STORE_SPECS.items():
    TYPE_KINDS.setdefault(_spec[0], _kind)
TYPE_LABELS = {0: "Clothing & customization", 1: "Companions", 2: "Furniture", 3: "Locomotions"}


def identifier(value):
    require(isinstance(value, str) and IDENTIFIER.fullmatch(value), "Invalid catalog record ID")
    return value


def wire_text(value, label, *, maximum=128, empty=False):
    require(isinstance(value, str) and len(value) <= maximum and (empty or bool(value.strip()))
            and "#" not in value and not any(unicodedata.category(c).startswith("C") for c in value),
            "Invalid " + label)
    return value


def integer(value, label, maximum=MAX_BALANCE):
    require(type(value) is int and 0 <= value <= maximum, "Invalid " + label)
    return value


def boolean(value, label):
    require(type(value) is bool, "Invalid " + label)
    return value


class StoreManagement:
    def __init__(self, manager):
        self.manager = manager
        self.service, self.db = manager.service, manager.db
        # Additive provenance only. Original commercial metadata remains unknown.
        self.db.execute("""CREATE TABLE IF NOT EXISTS management_catalog_overrides (
            entity_kind TEXT NOT NULL CHECK(entity_kind IN ('store','offer')),
            entity_id TEXT NOT NULL, changed_fields TEXT NOT NULL, updated_at REAL NOT NULL,
            PRIMARY KEY(entity_kind,entity_id))""")
        self.db.commit()

    def _mark(self, kind, key, before, after):
        changed = sorted(k for k in after if before is None or before.get(k) != after[k])
        if not changed:
            return
        row = self.db.execute("SELECT changed_fields FROM management_catalog_overrides WHERE entity_kind=? AND entity_id=?", (kind, key)).fetchone()
        previous = json.loads(row[0]) if row else []
        self.db.execute("""INSERT INTO management_catalog_overrides VALUES(?,?,?,?)
            ON CONFLICT(entity_kind,entity_id) DO UPDATE SET
            changed_fields=excluded.changed_fields,updated_at=excluded.updated_at""",
            (kind, key, json.dumps(sorted(set(previous) | set(changed))), time.time()))

    def _override(self, kind, key):
        row = self.db.execute("SELECT changed_fields FROM management_catalog_overrides WHERE entity_kind=? AND entity_id=?", (kind, key)).fetchone()
        return json.loads(row[0]) if row else []

    def _store(self, key):
        identifier(key)
        row = self.db.execute("SELECT * FROM shop_catalogs WHERE shop_id=?", (key,)).fetchone()
        require(row is not None, "Store not found", 404, "not_found")
        return dict(row)

    def _store_view(self, row):
        counts = self.db.execute("SELECT COUNT(*),COALESCE(SUM(active),0) FROM shop_offers WHERE shop_id=?", (row["shop_id"],)).fetchone()
        overrides = self._override("store", row["shop_id"])
        generated = row["shop_id"].startswith(POLICY + "-")
        kinds = {r[0] for r in self.db.execute("SELECT DISTINCT kind FROM shop_offers WHERE shop_id=?", (row["shop_id"],))}
        kind = ("personal_spaces" if kinds == {"personal_spaces"} or row["shop_id"] == POLICY + "-personal_spaces"
                else TYPE_KINDS[row["type_shop"]])
        return {**row, "active": bool(row["active"]), "kind": kind,
                "type_label": "Apartments" if kind == "personal_spaces" else TYPE_LABELS[row["type_shop"]],
                "total_offers": counts[0],
                "active_offers": counts[1], "operator_fields": overrides,
                "name_source": "operator_configured" if "name" in overrides or not generated else "preservation_label",
                "store_source": "preservation_policy" if generated else "operator_configured",
                "historical_store_known": False}

    def read(self, tail, query):
        parts = tail.split("/")
        if tail == "stores":
            search = query.get("q", "")
            require(isinstance(search, str) and len(search) <= 128, "Invalid store search")
            rows = [self._store_view(dict(row)) for row in self.db.execute("SELECT * FROM shop_catalogs ORDER BY type_shop,name,shop_id")]
            if search:
                rows = [r for r in rows if search.casefold() in " ".join(str(r[k]) for k in ("shop_id", "name", "description", "kind", "type_label")).casefold()]
            limit, offset = self.manager.pagination(query)
            return {"items": rows[offset:offset + limit], "total": len(rows), "limit": limit,
                    "next_cursor": str(offset + limit) if offset + limit < len(rows) else None}
        if len(parts) == 2 and parts[0] == "stores":
            return self._store_view(self._store(parts[1]))
        if len(parts) == 2 and parts[0] == "store-offers":
            key = identifier(parts[1])
            result = self.manager.catalog({"kind": "offer", "q": key, "limit": "100"})
            row = next((row for row in result["items"] if row["offer_id"] == key), None)
            # A search page is not an identity authority; fall back to direct
            # lookup plus the exact canonical asset when many IDs share a prefix.
            if row is None:
                offer = self.db.execute("SELECT * FROM shop_offers WHERE offer_id=?", (key,)).fetchone()
                require(offer is not None, "Store offer not found", 404, "not_found")
                inventory = getattr(self.manager, "_catalog_inventory", None) or CatalogInventory(self.service)
                assets, offers, _stores, _counts, _summary = inventory.snapshot()
                row = next(r for r in offers if r["offer_id"] == key)
                asset = next((r for r in assets if identity(r) == identity(row)), {})
                row = {**asset, **row, "offers": [row]}
            return row
        return None

    def change(self, kind, key, body):
        require(kind in ("stores", "store-offers"), "Store management route not found", 404, "not_found")
        identifier(key)
        return self._change_store(key, body) if kind == "stores" else self._change_offer(key, body)

    def _change_store(self, key, body):
        fields(body, ("reason", "type_shop", "name", "description", "active"))
        old = self.db.execute("SELECT * FROM shop_catalogs WHERE shop_id=?", (key,)).fetchone()
        before = dict(old) if old else None
        value = {"description": "", "active": True, **(before or {}), **{k: v for k, v in body.items() if k != "reason"}}
        type_shop = integer(value.get("type_shop"), "store type", 3)
        name = wire_text(value.get("name"), "store name")
        description = wire_text(value["description"], "store description", maximum=512, empty=True)
        active = boolean(body["active"], "store availability") if "active" in body else bool(value["active"])
        if before and before["type_shop"] != type_shop:
            require(not self.db.execute("SELECT 1 FROM shop_offers WHERE shop_id=?", (key,)).fetchone(),
                    "A populated store's type cannot be changed", 409, "conflict")
        spec = STORE_SPECS[TYPE_KINDS[type_shop]]
        url = before["url"] if before and before["type_shop"] == type_shop else SHOP_IMAGE_PREFIX + spec[2] + ".png"
        self.service.shop.configure_shop(key, type_shop, name, description, url, active)
        after = self._store(key)
        self._mark("store", key, before, after)
        return before, after, before != after

    def _change_offer(self, key, body):
        fields(body, ("reason", "kind", "item_id", "gender", "category", "shop_id", "name", "crystals", "np", "featured", "active"))
        old = self.db.execute("SELECT * FROM shop_offers WHERE offer_id=?", (key,)).fetchone()
        before = dict(old) if old else None
        value = {"crystals": 0, "np": 0, "active": True, "featured": False,
                 **(before or {}), **{k: v for k, v in body.items() if k != "reason"}}
        kind = value.get("kind")
        require(kind in (*STORE_SPECS, "bundle"), "Unsupported store item kind")
        if before:
            for field in ("kind", "item_id", "gender", "category"):
                require(field not in body or body[field] == before[field],
                        "An existing offer's asset identity cannot be changed", 409, "conflict")
        require(before is not None or kind != "bundle", "New bundle definitions require separate native review", 409, "conflict")
        store = self._store(identifier(value.get("shop_id")))
        if kind == "bundle":
            old_store = self._store(before["shop_id"])
            require(store["type_shop"] == old_store["type_shop"], "Bundle store type must remain compatible", 409, "conflict")
            image_path, type_id, gender_id = before["image_path"], before["type_id"], before["gender_id"]
        else:
            require(store["type_shop"] == STORE_SPECS[kind][0], "Item kind does not match this store", 409, "conflict")
            # Resolve through the complete canonical catalog to exclude removal
            # controls and reject ambiguous wardrobe variants before any write.
            inventory = getattr(self.manager, "_catalog_inventory", None)
            if inventory is None:
                inventory = self.manager._catalog_inventory = CatalogInventory(self.service)
            candidates = [r for r in inventory.items if r["kind"] == kind and r["item_id"] == value.get("item_id")
                          and (kind != "wardrobe" or ((not value.get("gender") or r["gender"] == value["gender"])
                               and (not value.get("category") or r["category"] == value["category"])))]
            require(len(candidates) == 1, "A unique shipped item and exact character/category variant are required", 404 if not candidates else 409,
                    "not_found" if not candidates else "conflict")
            asset = candidates[0]
            value["gender"], value["category"] = asset["gender"], asset["category"] if kind == "wardrobe" else None
            type_id = asset["store_category"]
            gender_id = {"MALE": 0, "FEMALE": 1}[asset["gender"]] if kind == "wardrobe" else STORE_SPECS[kind][5]
            image_path = asset["thumbnail_path"]
        name = wire_text(value.get("name"), "item name")
        crystals, np = integer(value["crystals"], "crystal price"), integer(value["np"], "Nebula Points price")
        active = boolean(body["active"], "item availability") if "active" in body else bool(value["active"])
        featured = boolean(body["featured"], "featured flag") if "featured" in body else bool(value["featured"])
        self.service.shop.configure_offer(key, kind, value.get("item_id"), store["shop_id"], type_id, gender_id, name,
                                          image_path=image_path, crystals=crystals, np=np,
                                          gender=value.get("gender"), category=value.get("category"), featured=featured, active=active)
        after = dict(self.db.execute("SELECT * FROM shop_offers WHERE offer_id=?", (key,)).fetchone())
        self._mark("offer", key, before, after)
        return before, after, before != after
