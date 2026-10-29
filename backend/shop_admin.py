"""Configure the offline preservation shop; never contacts Steam or a server."""
import argparse
import json
from pathlib import Path

from housing import HousingStore
from resources import ResourceCatalog, ResourceEntitlements
from shop import KINDS, Shop
from state import Catalog, Store
from wire import ProtocolError


ROOT = Path(__file__).resolve().parents[1]


def parser_for_cli():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, default=Path("work/server-state"))
    parser.add_argument("--protocol-dir", type=Path, default=ROOT / "protocol")
    parser.add_argument("--local-test-identities", action="store_true", help=(
        "Explicitly allow the two fixed local preservation test identities. "
        "Default is off; never use this for ordinary Steam accounts."))
    commands = parser.add_subparsers(dest="operation", required=True)

    wallet = commands.add_parser("wallet", help="Set an explicit local balance")
    wallet.add_argument("account_id")
    wallet.add_argument("crystals", type=int)
    wallet.add_argument("--np", type=int, default=0)
    wallet.add_argument("--level", type=int, default=0)

    show = commands.add_parser("wallet-show")
    show.add_argument("account_id")

    catalog = commands.add_parser("add-shop", help="Add/update local shop presentation")
    catalog.add_argument("shop_id")
    catalog.add_argument("type_shop", type=int, choices=range(4))
    catalog.add_argument("name")
    catalog.add_argument("--description", default="")
    catalog.add_argument("--url", default="")
    catalog.add_argument("--inactive", action="store_true")

    offer = commands.add_parser("add-offer", help="Add/update an explicitly priced offer")
    offer.add_argument("offer_id")
    offer.add_argument("kind", choices=KINDS)
    offer.add_argument("shop_id")
    offer.add_argument("type_id")
    offer.add_argument("gender_id", type=int)
    offer.add_argument("name")
    offer.add_argument("--item-id")
    offer.add_argument("--gender", choices=("MALE", "FEMALE"))
    offer.add_argument("--category")
    offer.add_argument("--image-path", default="", help=(
        "Derived from the shipped manifest for ordinary offers; required as a "
        "configured shipped thumbnail path for locally authored bundles"))
    offer.add_argument("--crystals", type=int, default=0)
    offer.add_argument("--np", type=int, default=0)
    offer.add_argument("--featured", action="store_true")
    offer.add_argument("--inactive", action="store_true")

    bundle = commands.add_parser("add-bundle-item")
    bundle.add_argument("bundle_offer_id")
    bundle.add_argument("child_offer_id")
    bundle.add_argument("--ordinal", type=int, default=0)

    commands.add_parser("list-offers")
    return parser


def main(argv=None):
    parser = parser_for_cli()
    args = parser.parse_args(argv)
    store = None
    try:
        store = Store(args.state_dir / "preservation.sqlite3",
                      local_test_identities=args.local_test_identities)
        catalog = Catalog(args.protocol_dir)
        resources = ResourceEntitlements(store, ResourceCatalog(args.protocol_dir))
        housing = HousingStore(store, args.protocol_dir)
        shop = Shop(store, catalog, resources, housing)
        if args.operation == "wallet":
            result = shop.set_wallet(args.account_id, args.crystals, args.np, args.level)
        elif args.operation == "wallet-show":
            result = shop.wallet(args.account_id)
        elif args.operation == "add-shop":
            shop.configure_shop(args.shop_id, args.type_shop, args.name,
                                args.description, args.url, not args.inactive)
            result = {"shop_id": args.shop_id, "configured": True}
        elif args.operation == "add-offer":
            shop.configure_offer(args.offer_id, args.kind, args.item_id,
                                 args.shop_id, args.type_id, args.gender_id,
                                 args.name, args.image_path, args.crystals, args.np,
                                 args.gender, args.category, args.featured,
                                 not args.inactive)
            result = next(row for row in shop.list_offers()
                          if row["offer_id"] == args.offer_id)
        elif args.operation == "add-bundle-item":
            shop.add_bundle_item(args.bundle_offer_id, args.child_offer_id, args.ordinal)
            result = {"bundle_offer_id": args.bundle_offer_id,
                      "child_offer_id": args.child_offer_id, "configured": True}
        else:
            result = shop.list_offers()
        print(json.dumps(result, ensure_ascii=True, indent=2))
    except (ProtocolError, OSError, ValueError) as exc:
        parser.exit(1, str(exc) + "\n")
    finally:
        if store is not None:
            store.close()


if __name__ == "__main__":
    main()
