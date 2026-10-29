"""Bounded local economy administration for the Nebula preservation backend.

This module is deliberately separate from the canonical backend until the
integration manifest is approved.  It uses Shop's existing catalog validation,
atomic grant path and entitlement stores; it never accepts an unconfigured
item ID and never contacts or emulates Steam commerce.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from housing import HousingStore
from resources import ResourceCatalog, ResourceEntitlements
from shop import Shop, _uint
from state import Catalog, Store
from wire import ProtocolError


MAX_BALANCE = 2_147_483_647
REFRESH_ROUTES = (
    "GetShopInfoPlayerShop",
    "NPShopIsItemPurchasedServlet",
    "GetPurchases",
    "GetCompanionsServlet",
    "GetLocomotionsServlet",
)


def _existing_account(shop: Shop, account_id: str) -> None:
    if not isinstance(account_id, str) or not account_id or len(account_id) > 128:
        raise ProtocolError("Invalid local account identifier")
    if shop.store.db.execute(
            "SELECT 1 FROM profiles WHERE ps4_id=?", (account_id,)).fetchone() is None:
        raise ProtocolError("Unknown local account", 404)


def credit_wallet(shop: Shop, account_id: str, crystals: int = 0, np: int = 0) -> dict:
    """Atomically add explicit non-negative local credits to an existing account."""
    crystals = _uint(crystals, "crystal credit")
    np = _uint(np, "NP credit")
    if crystals == 0 and np == 0:
        raise ProtocolError("At least one positive local credit is required")
    with shop.store.atomic():
        _existing_account(shop, account_id)
        shop._ensure_wallet(account_id)
        before = shop.wallet(account_id)
        if before["crystals"] > MAX_BALANCE - crystals or before["np"] > MAX_BALANCE - np:
            raise ProtocolError("Local wallet credit would overflow", 409)
        changed = shop.store.db.execute(
            "UPDATE shop_wallets SET crystals=crystals+?,np=np+? WHERE ps4_id=?",
            (crystals, np, account_id),
        )
        if changed.rowcount != 1:
            raise ProtocolError("Local wallet changed during credit", 409)
        after = shop.wallet(account_id)
    return {
        "account_id": account_id,
        "operation": "credit",
        "delta": {"crystals": crystals, "np": np},
        "before": {"crystals": before["crystals"], "np": before["np"]},
        "after": {"crystals": after["crystals"], "np": after["np"]},
        "refresh_routes": list(REFRESH_ROUTES),
    }


def grant_offer(shop: Shop, account_id: str, offer_id: str,
                granted_by: str = "local-preservation-admin") -> dict:
    """Grant one configured manifest-backed offer without debiting a wallet."""
    _existing_account(shop, account_id)
    offer = shop._offer(offer_id)  # active configured offers only
    if not isinstance(granted_by, str) or not granted_by or len(granted_by) > 128:
        raise ProtocolError("Invalid local grant authority")
    granted = shop._record_grant(account_id, offer, "admin", granted_by)
    return {
        "account_id": account_id,
        "offer_id": offer_id,
        "kind": offer["kind"],
        "item_id": offer["item_id"],
        "result": "granted" if granted else "already_owned",
        "wallet_debited": False,
        "refresh_routes": list(REFRESH_ROUTES),
    }


def account_summary(shop: Shop, account_id: str) -> dict:
    _existing_account(shop, account_id)
    owned = [dict(row) for row in shop.store.db.execute(
        "SELECT offer_id,source,granted_by,created_at FROM shop_owned "
        "WHERE ps4_id=? ORDER BY offer_id", (account_id,))]
    return {
        "account_id": account_id,
        "wallet": shop.wallet(account_id),
        "owned_offers": owned,
        "wardrobe_item_ids": sorted(row["item_id"] for row in shop.store.inventory(account_id)),
        "companion_item_ids": sorted(row["item_id"] for row in
                                     shop.resources.list(account_id, "companions")),
        "locomotion_item_ids": sorted(row["item_id"] for row in
                                      shop.resources.list(account_id, "locomotions")),
        "housing_item_ids": sorted(row["item_id"] for row in shop.housing.inventory(account_id)),
        "refresh_routes": list(REFRESH_ROUTES),
    }


def parser_for_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--protocol-dir", type=Path, default=ROOT / "protocol")
    commands = parser.add_subparsers(dest="operation", required=True)
    credit = commands.add_parser("credit", help="add explicit local currency")
    credit.add_argument("account_id")
    credit.add_argument("--crystals", type=int, default=0)
    credit.add_argument("--np", type=int, default=0)
    grant = commands.add_parser("grant-offer", help="grant one configured offer")
    grant.add_argument("account_id")
    grant.add_argument("offer_id")
    grant.add_argument("--granted-by", default="local-preservation-admin")
    summary = commands.add_parser("account-summary")
    summary.add_argument("account_id")
    return parser


def main(argv=None) -> None:
    parser = parser_for_cli()
    args = parser.parse_args(argv)
    store = None
    try:
        store = Store(args.state_dir / "preservation.sqlite3")
        catalog = Catalog(args.protocol_dir)
        resources = ResourceEntitlements(store, ResourceCatalog(args.protocol_dir))
        housing = HousingStore(store, args.protocol_dir)
        shop = Shop(store, catalog, resources, housing)
        if args.operation == "credit":
            result = credit_wallet(shop, args.account_id, args.crystals, args.np)
        elif args.operation == "grant-offer":
            result = grant_offer(shop, args.account_id, args.offer_id, args.granted_by)
        else:
            result = account_summary(shop, args.account_id)
        print(json.dumps(result, indent=2, ensure_ascii=True))
    except (ProtocolError, OSError, ValueError) as exc:
        parser.exit(1, str(exc) + "\n")
    finally:
        if store is not None:
            store.close()


if __name__ == "__main__":
    main()
