"""Configure explicit local preservation rewards; no listener or purchase API."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from allocation import InstanceDirectory
from rewards import CONFIGURABLE, GRANT_KINDS, REWARD_TYPES, RewardService
from state import Catalog, Store
from wire import ProtocolError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, default=Path("work/server-state"))
    commands = parser.add_subparsers(dest="operation", required=True)
    configure = commands.add_parser("configure")
    configure.add_argument("route", choices=sorted(CONFIGURABLE))
    configure.add_argument("trigger")
    configure.add_argument("--grant-kind", choices=sorted(GRANT_KINDS))
    configure.add_argument("--item-id")
    configure.add_argument("--gender", choices=("MALE", "FEMALE"))
    configure.add_argument("--category")
    configure.add_argument("--name")
    configure.add_argument("--sprite-id", type=int)
    configure.add_argument("--units", type=int, default=1)
    configure.add_argument("--uses", type=int)
    configure.add_argument("--disabled", action="store_true")
    claims = commands.add_parser("claims")
    claims.add_argument("--account")
    commands.add_parser("definitions")
    commands.add_parser("catalog")
    args = parser.parse_args()
    store = Store(args.state_dir / "preservation.sqlite3")
    try:
        service = RewardService(store, Catalog(ROOT / "protocol"), InstanceDirectory(args.state_dir))
        if args.operation == "configure":
            result = service.configure(args.route, args.trigger, not args.disabled,
                args.grant_kind, args.item_id, args.gender, args.category, args.name,
                args.sprite_id, args.units, args.uses)
        elif args.operation == "claims":
            result = service.claims(args.account)
        elif args.operation == "definitions":
            result = [dict(x) for x in store.db.execute(
                "SELECT * FROM local_reward_definitions ORDER BY route,trigger_key")]
        else:
            result = {
                "RewardClothServlet": {"triggers": ["0"], "grant_kinds": ["wardrobe"]},
                "checkRewardAvailableServlet": {"reward_types": sorted(REWARD_TYPES)},
                "SKLPromoServlet": {key: sorted(value) for key, value in sorted(service.skl_promos.items())},
                "CinemaInteractionNPServlet": {"0": "Ticket", "1": "PopCorn"},
            }
        print(json.dumps(result, ensure_ascii=True, indent=2))
    except (ProtocolError, OSError, ValueError) as exc:
        parser.exit(1, str(exc) + "\n")
    finally:
        store.close()


if __name__ == "__main__":
    main()
