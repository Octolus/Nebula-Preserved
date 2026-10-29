"""Grant and inspect local preservation consumables (no purchases/payments)."""
import argparse
import json
from pathlib import Path

from consumables import Consumables, KINDS
from state import Store
from wire import ProtocolError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, default=Path("work/server-state"))
    commands = parser.add_subparsers(dest="operation", required=True)
    grant = commands.add_parser("grant", help="Add explicit local units")
    grant.add_argument("account_id")
    grant.add_argument("kind", choices=KINDS)
    grant.add_argument("units", type=int)
    grant.add_argument("--uses", type=int, required=True,
                       help="prop uses per issued unit; original default is unknown")
    grant.add_argument("--price", default="1", help="local UI display string")
    grant.add_argument("--price-type", default="local token", help="local UI display string")
    grant.add_argument("--reward-index", type=int, default=0)
    grant.add_argument("--rewarded", action="store_true")
    listing = commands.add_parser("list")
    listing.add_argument("account_id")
    args = parser.parse_args()
    store = None
    try:
        store = Store(args.state_dir / "preservation.sqlite3")
        source = Consumables(store)
        if args.operation == "grant":
            result = source.grant(args.account_id, args.kind, args.units, args.uses,
                                  args.price, args.price_type,
                                  args.reward_index, args.rewarded)
        else:
            result = source.list(args.account_id)
        print(json.dumps(result, ensure_ascii=True, indent=2))
    except (ProtocolError, OSError, ValueError) as exc:
        parser.exit(1, str(exc) + "\n")
    finally:
        if store is not None:
            store.close()


if __name__ == "__main__":
    main()
