"""Plan or explicitly seed a small, reachable local preservation shop catalog.

Dry-run is the default.  --apply requires an explicit --state-dir.  All names,
prices and balances below are local preservation policy, never retired-service
commercial data.  Shipped item IDs/categories/thumbnails remain manifest-backed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
import sys
sys.path.insert(0, str(BACKEND))

from housing import HousingStore
from resources import ResourceCatalog, ResourceEntitlements
from shop import Shop
from state import Catalog, Store


CLIENT_SHOP_URL_PREFIX = "http://127.0.0.1:8080/preservation/shop-image-padding/v1/"
SHOP_SPECS = (
    ("local-preservation-clothing", 0, "Local Preservation Clothing",
     "00456nmbhjg345tglcdfbt650234rtgf"),
    ("local-preservation-companions", 1, "Local Preservation Companions",
     "0056yhjnbmg456y3k3gbvnf96o7wdecf"),
    ("local-preservation-furniture", 2, "Local Preservation Furniture",
     "00653925e2aa48958861cad67fb8ce78"),
    ("local-preservation-locomotions", 3, "Local Preservation Locomotions",
     "0095gbnhmgtr4556yuhjnmqwe345tbg9"),
)
WARDROBE_CATEGORIES = (
    "CLOTH_BODY_TORSO", "CLOTH_BODY_LEGS", "CLOTH_BODY_FEET",
    "CLOTH_HEAD_HAIRSTYLE",
)
LOCAL_PRICES = {
    "wardrobe": (25, 10), "companions": (40, 20),
    "housing": (30, 15), "locomotions": (35, 15), "bundle": (60, 25),
}
GENDER_IDS = {"MALE": 0, "FEMALE": 1}


def shop_image_url(resource_id):
    """Build the inert carrier consumed by EntryShop.Set's fixed slice.

    The native client never requests this URL.  It takes characters 57..-4,
    prepends ``Shops/``, and loads that shipped Resources sprite locally.
    """
    if len(CLIENT_SHOP_URL_PREFIX) != 57:
        raise RuntimeError("Local shop image carrier prefix must be exactly 57 characters")
    if not resource_id or "/" in resource_id or "#" in resource_id:
        raise RuntimeError("Invalid shipped shop sprite ID")
    return CLIENT_SHOP_URL_PREFIX + resource_id + ".png"


def _label(value):
    return value.replace("CLOTH_BODY_", "").replace("CLOTH_HEAD_", "").replace("_", " ").title()


def _choose_assets(catalog, resource_catalog, housing):
    wardrobe = []
    for gender in ("MALE", "FEMALE"):
        for category in WARDROBE_CATEGORIES:
            choices = sorted((row for row in catalog.items.values()
                              if row["gender"] == gender and row["category"] == category),
                             key=lambda row: row["item_id"])
            if choices:
                wardrobe.append(choices[0])
    companions = resource_catalog.list("companions")[:2]
    locomotions = resource_catalog.list("locomotions")[:2]
    furniture = [housing.catalog[key] for key in sorted(housing.catalog)[:2]]
    if len(wardrobe) < 4 or not companions or not locomotions or not furniture:
        raise RuntimeError("Representative shipped shop assets are incomplete")
    return wardrobe, companions, locomotions, furniture


def seed(shop, catalog, resource_catalog, housing, account_id=None,
         starter_crystals=0, starter_np=0):
    """Idempotently configure the validated representative local catalog."""
    for shop_id, type_shop, name, image_id in SHOP_SPECS:
        shop.configure_shop(shop_id, type_shop, name,
                            "Administrator-authored local preservation offers",
                            shop_image_url(image_id))

    wardrobe, companions, locomotions, furniture = _choose_assets(
        catalog, resource_catalog, housing)
    plan = {"shops": [], "offers": [], "bundle_items": [], "wallet": None}
    for shop_id, type_shop, name, image_id in SHOP_SPECS:
        plan["shops"].append({"shop_id": shop_id, "type_shop": type_shop, "name": name,
                              "image_resource_id": image_id,
                              "url": shop_image_url(image_id)})

    for index, row in enumerate(wardrobe):
        gender = row["gender"]
        offer_id = f"local-clothing-{gender.lower()}-{index + 1}"
        crystals, np = LOCAL_PRICES["wardrobe"]
        label = f"Local {gender.title()} {_label(row['category'])}"
        shop.configure_offer(offer_id, "wardrobe", row["item_id"],
                             SHOP_SPECS[0][0], row["category"], GENDER_IDS[gender],
                             label, crystals=crystals, np=np, gender=gender,
                             category=row["category"], featured=index < 2)
        plan["offers"].append({"offer_id": offer_id, "kind": "wardrobe",
                               "item_id": row["item_id"], "gender_id": GENDER_IDS[gender],
                               "type_id": row["category"], "crystals": crystals, "np": np})

    child_ids = []
    for kind, rows, spec_index, gender_id in (
            ("companions", companions, 1, 3),
            ("housing", furniture, 2, 5),
            ("locomotions", locomotions, 3, 6)):
        for index, row in enumerate(rows):
            singular = {"companions": "companion", "housing": "furniture",
                        "locomotions": "locomotion"}[kind]
            offer_id = f"local-{singular}-{index + 1}"
            crystals, np = LOCAL_PRICES[kind]
            shop.configure_offer(offer_id, kind, row["item_id"],
                                 SHOP_SPECS[spec_index][0], "items", gender_id,
                                 f"Local {singular.title()} {index + 1}",
                                 crystals=crystals, np=np, featured=index == 0)
            plan["offers"].append({"offer_id": offer_id, "kind": kind,
                                   "item_id": row["item_id"], "gender_id": gender_id,
                                   "type_id": "items", "crystals": crystals, "np": np})
            if index == 0 and kind in ("companions", "locomotions"):
                child_ids.append(offer_id)

    first_child = shop._offer(child_ids[0])
    crystals, np = LOCAL_PRICES["bundle"]
    shop.configure_offer("local-starter-bundle", "bundle", None, SHOP_SPECS[0][0],
                         "bundles", 2, "Local Companion + Locomotion Bundle",
                         first_child["image_path"], crystals=crystals, np=np, featured=True)
    plan["offers"].append({"offer_id": "local-starter-bundle", "kind": "bundle",
                           "item_id": None, "gender_id": 2, "type_id": "bundles",
                           "crystals": crystals, "np": np})
    for ordinal, child_id in enumerate(child_ids):
        shop.add_bundle_item("local-starter-bundle", child_id, ordinal)
        plan["bundle_items"].append({"bundle_offer_id": "local-starter-bundle",
                                     "child_offer_id": child_id, "ordinal": ordinal})

    if account_id is not None:
        wallet = shop.set_wallet(account_id, starter_crystals, starter_np)
        plan["wallet"] = {"account_id": account_id, "crystals": wallet["crystals"],
                          "np": wallet["np"]}
    return plan


def repair_shop_images(store):
    """Repair only already-seeded local shop URL fields; create nothing else."""
    repaired = []
    with store.db:
        for shop_id, _type_shop, _name, image_id in SHOP_SPECS:
            row = store.db.execute(
                "SELECT url FROM shop_catalogs WHERE shop_id=?", (shop_id,)).fetchone()
            if row is None:
                continue
            url = shop_image_url(image_id)
            if row["url"] != url:
                store.db.execute("UPDATE shop_catalogs SET url=? WHERE shop_id=?",
                                 (url, shop_id))
                repaired.append(shop_id)
    return {"shops": [], "offers": [], "bundle_items": [], "wallet": None,
            "repair": {"matched": sum(1 for spec in SHOP_SPECS if store.db.execute(
                "SELECT 1 FROM shop_catalogs WHERE shop_id=?", (spec[0],)).fetchone()),
                       "updated": repaired}}


def execute(protocol_dir, state_dir=None, apply=False, account_id=None,
            starter_crystals=0, starter_np=0, repair_images=False):
    if apply and state_dir is None:
        raise ValueError("--apply requires an explicit --state-dir")
    temporary = None
    if not apply:
        temporary = tempfile.TemporaryDirectory(prefix="nebula-shop-seed-")
        state_dir = Path(temporary.name)
    state_dir = Path(state_dir)
    store = Store(state_dir / "preservation.sqlite3")
    try:
        catalog = Catalog(Path(protocol_dir))
        resource_catalog = ResourceCatalog(Path(protocol_dir))
        resources = ResourceEntitlements(store, resource_catalog)
        housing = HousingStore(store, Path(protocol_dir))
        shop = Shop(store, catalog, resources, housing)
        result = (repair_shop_images(store) if repair_images else
                  seed(shop, catalog, resource_catalog, housing, account_id,
                       starter_crystals, starter_np))
        result.update({"mode": "applied" if apply else "dry-run",
                       "state_dir": str(state_dir) if apply else None,
                       "policy": ("existing local shop image fields only" if repair_images else
                                  "local preservation labels, prices and balances")})
        return result
    finally:
        store.close()
        if temporary is not None:
            temporary.cleanup()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol-dir", type=Path, default=ROOT / "protocol")
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--account-id", help="optional local account to receive an explicit balance")
    parser.add_argument("--starter-crystals", type=int, default=0)
    parser.add_argument("--starter-np", type=int, default=0)
    parser.add_argument("--repair-shop-images", action="store_true",
                        help="only repair URL fields on existing local-preservation shops")
    args = parser.parse_args(argv)
    if (args.starter_crystals or args.starter_np) and args.account_id is None:
        parser.error("starter balances require --account-id")
    if args.repair_shop_images and (args.account_id is not None or
                                    args.starter_crystals or args.starter_np):
        parser.error("shop image repair cannot change an account balance")
    try:
        result = execute(args.protocol_dir, args.state_dir, args.apply, args.account_id,
                         args.starter_crystals, args.starter_np, args.repair_shop_images)
    except (ValueError, OSError, RuntimeError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
