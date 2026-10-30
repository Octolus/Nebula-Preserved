"""Manifest-backed item metadata and explicit preservation store policy.

Asset identities/categories are recovered. Commercial names, store membership
and prices are unknown. No asset bytes, remote URLs or ownership are inferred.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter

from wire import ProtocolError


POLICY = "preservation-catalog-v1"
KINDS = ("wardrobe", "companions", "locomotions", "housing")
# Four canonical assets use categories absent from the shipped type-icon list.
# Grouping is preservation UI policy; entitlement and resource categories stay
# byte-exact and ItemData.tablename continues to carry the canonical category.
STORE_TYPE_ALIASES = {"CLOTH_BODY_HAND": "CLOTH_BODY_HANDS", "CLOTH_BODY_TORSOLEGS": "CLOTH_BODY_TORSO_LEGS"}
SHOP_IMAGE_PREFIX = "http://127.0.0.1:8080/preservation/shop-image-padding/v1/"
STORE_SPECS = {
    "wardrobe": (0, "Clothing", "00456nmbhjg345tglcdfbt650234rtgf", 25, 10, None),
    "companions": (1, "Companions", "0056yhjnbmg456y3k3gbvnf96o7wdecf", 40, 20, 3),
    "housing": (2, "Furniture", "00653925e2aa48958861cad67fb8ce78", 30, 15, 5),
    "locomotions": (3, "Locomotions", "0095gbnhmgtr4556yuhjnmqwe345tbg9", 35, 15, 6),
}
NOTE = ("Shipped manifests establish asset IDs, categories and resource paths. "
        "Original commercial names, prices and store assignments are unknown. "
        "Preservation stores, labels and prices are explicitly authored policy.")


def label(value):
    return (value or "").replace("CLOTH_BODY_", "").replace("CLOTH_HEAD_", "").replace("HOUSING_", "").replace("_", " ").title()


def identity(row):
    wardrobe = row["kind"] == "wardrobe"
    return (row["kind"], row["item_id"], (row.get("gender") or "") if wardrobe else "",
            (row.get("category") or "") if wardrobe else "")


def offer_id(row):
    digest = hashlib.sha256(json.dumps(identity(row), ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()
    return POLICY + "-" + digest[:32]


def preview_fields(resource_path):
    """Opaque lookup key only; never reads a file or establishes availability.

    Item paths retain their .png suffix. Shop artwork uses its extensionless
    ResourceManager key. The private extractor follows this exact normalization;
    the server resolves only an allowlisted image index, not this resource path.
    """
    if not isinstance(resource_path, str) or not resource_path:
        return {"preview_key": None, "preview_url": None}
    normalized = resource_path.replace("\\", "/").lower()
    key = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return {"preview_key": key, "preview_url": "/api/catalog-preview/" + key}


class CatalogInventory:
    def __init__(self, service):
        self.service = service
        self.items = []
        evidence = service.catalog.protocol_dir / "catalog-recovery-provenance.json"
        recovered = json.loads(evidence.read_text(encoding="utf-8")) if evidence.exists() else {}
        self.artwork = [{**row, "kind": "shop_artwork", "item_id": row["resource_key"],
                         **preview_fields(row["resource_key"]),
                         "resource_path": row["resource_key"], "asset_path": None,
                         "thumbnail_path": None, "offers": [], "grantable": False,
                         "shop_ready": False, "unavailable_reason": "Artwork identity does not establish a store or item entitlement",
                         "provenance": {"asset_identity": "shipped_resource_table", "historical_store": "unknown"},
                         "source_catalog": "catalog-recovery-provenance.json"}
                        for row in recovered.get("shop_artwork", [])]
        self.field_availability = recovered.get("field_availability", {})
        controls = {r["item_id"] for r in service.wardrobe_removal_sentinels.values()}
        self.excluded_removal_controls = sum(x["item_id"] in controls for x in service.catalog.items.values())
        groups = [("wardrobe", [x for x in service.catalog.items.values() if x["item_id"] not in controls]),
                  ("companions", service.resources.catalog.list("companions")),
                  ("locomotions", service.resources.catalog.list("locomotions")),
                  ("housing", list(service.housing.catalog.values()))]
        for kind, rows in groups:
            for asset in rows:
                category = asset.get("category") if kind == "wardrobe" else asset.get("table")
                row = {"kind": kind, "item_id": asset["item_id"],
                       "gender": asset.get("gender") if kind == "wardrobe" else None,
                       "category": category, "category_label": label(category) or label(kind),
                       "store_category": STORE_TYPE_ALIASES.get(category, category) if kind == "wardrobe" else "items",
                       "store_category_source": "preservation_compatibility_alias" if kind == "wardrobe" and category in STORE_TYPE_ALIASES else "shipped_category",
                       "bundle": asset.get("bundle"), "asset_path": asset.get("asset_path"),
                       "asset_metadata": dict(asset),
                       "resource_path": asset.get("requested_resource_path"),
                       "manifest_sha256": asset.get("manifest_sha256"),
                       "bundle_size": asset.get("bundle_size"), "dependencies": asset.get("dependencies", []),
                       "category_evidence": asset.get("category_evidence", []),
                       "placement_cost": asset.get("placement_cost"), "placement_behaviour": asset.get("behaviour"),
                       "grantable": True, "original_name": None, "original_store": None, "original_price": None,
                       "source_catalog": {"wardrobe": "avatar-asset-catalog.json", "housing": "http-nonminigame-gap-audit.json"}.get(kind, "resource-entitlements.json"),
                       "provenance": {"asset_identity": "shipped_manifest", "display_name": "preservation_label",
                                      "historical_store": "unknown", "historical_price": "unknown"}}
                row["name"] = "Preserved " + row["category_label"] + " " + row["item_id"]
                try:
                    row["thumbnail_path"] = service.shop._thumbnail(kind, asset["item_id"], asset)
                    row["own_thumbnail_known"] = row["thumbnail_path"] != "Shops/shop.png"
                    row["thumbnail_source"] = "shipped_item_manifest" if row["own_thumbnail_known"] else "generic_shipped_shop_icon"
                    row["shop_ready"], row["unavailable_reason"] = True, None
                except ProtocolError as exc:
                    row["thumbnail_path"] = None
                    row["shop_ready"], row["unavailable_reason"] = False, str(exc)
                row.update(preview_fields(row["thumbnail_path"]))
                self.items.append(row)
        self.items.sort(key=identity)
        if len({identity(row) for row in self.items}) != len(self.items):
            raise ProtocolError("Duplicate canonical catalog identity", 501)

    def snapshot(self):
        stores = {r["shop_id"]: dict(r) for r in self.service.store.db.execute("SELECT * FROM shop_catalogs ORDER BY shop_id")}
        offers = [dict(r) for r in self.service.store.db.execute("SELECT * FROM shop_offers ORDER BY offer_id")]
        by_item = {}
        for row in offers:
            store = stores[row["shop_id"]]
            generated = row["offer_id"].startswith(POLICY + "-")
            row.update(shop_name=store["name"], type_shop=store["type_shop"],
                       store_active=bool(store["active"]), price_source="preservation_policy" if generated else "operator_configured",
                       name_source="preservation_label" if generated else "operator_configured",
                       store_assignment_source="preservation_policy" if generated else "operator_configured")
            by_item.setdefault(identity(row), []).append(row)
        rows = [{**row, "offers": by_item.get(identity(row), [])} for row in self.items]
        counts = dict(Counter(row["kind"] for row in rows)); counts.update(all=len(rows), offer=len(offers), shop_artwork=len(self.artwork))
        summary = {"grantable": len(rows), "shop_ready": sum(r["shop_ready"] for r in rows),
                   "offered": sum(any(o["active"] and o["store_active"] for o in r["offers"]) for r in rows),
                   "excluded_removal_controls": self.excluded_removal_controls}
        summary["unoffered"] = summary["grantable"] - summary["offered"]
        return rows, offers, stores, counts, summary


def seed_full_catalog(service):
    """Fill uncovered validated assets atomically; never update existing rows.

    Existing offers (including disabled offers) are operator authority and are
    not repriced, reassigned, re-enabled or replaced. An inactive-only asset is
    reported as such rather than bypassed with a new offer.
    """
    inventory = CatalogInventory(service)
    created_shops = created_offers = 0
    with service.store.atomic():
        rows, offers, _stores, counts, before = inventory.snapshot()
        if any(not row["shop_ready"] for row in rows):
            raise ProtocolError("Full catalog contains an unresolved thumbnail; no offers imported", 501)
        existing = {}
        for row in offers:
            existing.setdefault(identity(row), []).append(row)
        planned = [row for row in rows if identity(row) not in existing]
        needed = {row["kind"] for row in planned}
        for kind in sorted(needed):
            spec = STORE_SPECS[kind]
            sid = POLICY + "-" + kind
            expected = (sid, spec[0], "Preservation " + spec[1], NOTE, SHOP_IMAGE_PREFIX + spec[2] + ".png", 1)
            current = service.store.db.execute("SELECT * FROM shop_catalogs WHERE shop_id=?", (sid,)).fetchone()
            if current is not None and tuple(current) != expected:
                raise ProtocolError("Preservation catalog store conflicts with operator configuration", 409)
            if current is None:
                service.shop.configure_shop(sid, spec[0], expected[2], NOTE, expected[4])
                created_shops += 1
        for row in planned:
            kind = row["kind"]; spec = STORE_SPECS[kind]; oid = offer_id(row)
            if service.store.db.execute("SELECT 1 FROM shop_offers WHERE offer_id=?", (oid,)).fetchone():
                raise ProtocolError("Preservation catalog offer identity collision", 409)
            service.shop.configure_offer(oid, kind, row["item_id"], POLICY + "-" + kind,
                                         row["store_category"],
                                         {"MALE": 0, "FEMALE": 1}[row["gender"]] if kind == "wardrobe" else spec[5],
                                         row["name"], crystals=spec[3], np=spec[4],
                                         gender=row["gender"] if kind == "wardrobe" else None,
                                         category=row["category"] if kind == "wardrobe" else None)
            created_offers += 1
    _rows, _offers, _stores, _counts, after = inventory.snapshot()
    return {"policy": POLICY, "metadata_note": NOTE, "counts": _counts, "before": before,
            "after": after, "created_shops": created_shops, "created_offers": created_offers,
            "preserved_existing_offers": len(offers),
            "inactive_existing_items": sum(bool(r["offers"]) and not any(o["active"] and o["store_active"] for o in r["offers"]) for r in rows)}
