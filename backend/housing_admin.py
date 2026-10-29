"""Offline housing administration; never starts a listener or target process."""
import argparse
import json
from pathlib import Path

from housing import HousingStore
from state import Store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, required=True)
    actions = parser.add_subparsers(dest="action", required=True)
    bind = actions.add_parser("bind-space", help="Bind a verified scene/instance to an existing local account")
    bind.add_argument("owner_ps4_id")
    bind.add_argument("instance_id")
    bind.add_argument("psidglobal", help="Actual shipped scene bundle key")
    bind.add_argument("--logical-space-key", help="Exact personal-space navigator label; defaults to psidglobal")
    grant = actions.add_parser("grant-item", help="Grant an exact canonical shipped housing ID")
    grant.add_argument("ps4_id")
    grant.add_argument("item_id")
    grant.add_argument("--name")
    listing = actions.add_parser("list-items")
    listing.add_argument("ps4_id")
    actions.add_parser("catalog")
    actions.add_parser("space-catalog", help="List every shipped logical space and recovered wall/ceiling bounds")
    args = parser.parse_args()
    protocol = Path(__file__).resolve().parents[1] / "protocol"
    store = Store(args.state_dir / "preservation.sqlite3")
    try:
        housing = HousingStore(store, protocol)
        if args.action == "bind-space":
            result = housing.bind_space(args.instance_id, args.psidglobal, args.owner_ps4_id, args.logical_space_key)
        elif args.action == "grant-item":
            result = housing.grant_item(args.ps4_id, args.item_id, args.name)
        elif args.action == "list-items":
            result = housing.inventory(args.ps4_id)
        elif args.action == "catalog":
            result = list(housing.catalog.values())
        else:
            result = [{"logical_space_key": name, "wall_slots": housing.space_slots[name][0],
                       "ceiling_slots": housing.space_slots[name][1]}
                      for name in sorted(housing.space_names)]
        print(json.dumps(result, ensure_ascii=True, indent=2))
    finally:
        store.close()


if __name__ == "__main__":
    main()
