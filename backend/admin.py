"""Offline administration of local preservation accounts and wardrobe items."""
import argparse
import json
from pathlib import Path

from state import Catalog, Store
from avatar import neutral
from wire import ProtocolError

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--state-dir", type=Path, default=Path("work/server-state"))
    commands = p.add_subparsers(dest="operation", required=True)
    create = commands.add_parser("account")
    create.add_argument("account_id")
    create.add_argument("--name", required=True)
    grant = commands.add_parser("grant-item")
    grant.add_argument("account_id")
    grant.add_argument("item_id")
    grant.add_argument("--gender", choices=["MALE", "FEMALE"])
    grant.add_argument("--category")
    grant.add_argument("--name")
    grant.add_argument("--item-type", type=int, choices=range(9), default=None,
                       help="Local interaction type; original shop metadata is unknown")
    defaults = commands.add_parser("grant-default-items")
    defaults.add_argument("account_id")
    defaults.add_argument("--gender", choices=["MALE", "FEMALE"], required=True)
    inventory = commands.add_parser("inventory")
    inventory.add_argument("account_id")
    seed = commands.add_parser("seed-neutral-avatar")
    seed.add_argument("account_id")
    seed.add_argument("--gender", choices=["MALE", "FEMALE"], required=True)
    seed.add_argument("--name", default="Default")
    commands.add_parser("export-state")
    args = p.parse_args()
    store = Store(args.state_dir / "preservation.sqlite3")
    catalog = Catalog(ROOT / "protocol")
    try:
        if args.operation == "account":
            print(json.dumps(store.account(args.account_id, args.name), ensure_ascii=True, indent=2))
        elif args.operation == "grant-item":
            item = catalog.resolve(args.item_id, args.gender, args.category)
            store.grant(args.account_id, item, args.name, args.item_type)
            print("Granted local wardrobe item " + item["item_id"])
        elif args.operation == "grant-default-items":
            data = json.loads((ROOT / "protocol/avatar-default-catalog.json").read_text(encoding="utf-8"))
            items = data["defaults"][args.gender]["items"]
            for item in items:
                store.grant(args.account_id, catalog.resolve(item["item_id"], args.gender, item["category"]))
            print(f"Granted {len(items)} manifest-backed local default items")
        elif args.operation == "seed-neutral-avatar":
            store.account(args.account_id)
            preset, assets, position = neutral(ROOT / "protocol", args.account_id, args.gender, args.name)
            store.save_preset(args.account_id, args.name, args.gender, preset, assets, position)
            print("Saved reconstructed neutral avatar; original server appearance defaults are unknown")
        elif args.operation == "export-state":
            store.export_instance_accounts(args.state_dir)
            print("Exported local instance account bindings")
        else:
            print(json.dumps(store.inventory(args.account_id), ensure_ascii=True, indent=2))
    except ProtocolError as exc:
        p.exit(1, str(exc) + "\n")
    finally:
        store.export_instance_accounts(args.state_dir)
        store.close()


if __name__ == "__main__":
    main()
