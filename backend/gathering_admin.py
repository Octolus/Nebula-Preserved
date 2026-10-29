"""Offline gathering/event administration. Never starts a listener."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from gathering import CHRISTMAS_2018_SCENES, Gathering, TYPE_NAMES
from housing import HousingStore
from resources import ResourceCatalog, ResourceEntitlements
from state import Catalog, Store
from wire import ProtocolError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, default=Path("work/server-state"))
    commands = parser.add_subparsers(dest="operation", required=True)
    configure = commands.add_parser("configure")
    configure.add_argument("type_id", type=int, choices=TYPE_NAMES)
    configure.add_argument("name")
    configure.add_argument("--active", action="store_true")
    configure.add_argument("--max-items", type=int, required=True)
    configure.add_argument("--initial-rewards", "--phase", dest="initial_rewards", type=int, default=0)
    configure.add_argument("--cooldown-seconds", type=int, default=0)
    configure.add_argument("--reward-kind", choices=("wardrobe", "companion", "locomotion", "housing"))
    configure.add_argument("--reward-item")
    configure.add_argument("--reward-gender")
    configure.add_argument("--reward-category")
    configure.add_argument("--reward-name")
    progress = commands.add_parser("set-progress")
    progress.add_argument("ps4_id"); progress.add_argument("type_id", type=int, choices=TYPE_NAMES)
    progress.add_argument("--current", type=int, default=0)
    progress.add_argument("--spaces", type=int, default=0)
    progress.add_argument("--rewards", type=int, default=0)
    progress.add_argument("--reward-claimed", action="store_true")
    scenes = commands.add_parser("set-scenes")
    scenes.add_argument("ps4_id")
    scenes.add_argument("scenes", nargs="*", choices=CHRISTMAS_2018_SCENES)
    medieval = commands.add_parser("set-medieval")
    medieval.add_argument("ps4_id"); medieval.add_argument("--active", action="store_true")
    medieval.add_argument("--amount-left", type=int, default=0)
    medieval.add_argument("--cooldown-until", type=float, default=0)
    commands.add_parser("list")
    args = parser.parse_args()
    protocol = ROOT / "protocol"
    store = None
    try:
        store = Store(args.state_dir / "preservation.sqlite3")
        catalog = Catalog(protocol); resources = ResourceEntitlements(store, ResourceCatalog(protocol))
        housing = HousingStore(store, protocol); gathering = Gathering(store, catalog, resources, housing)
        if args.operation == "configure":
            if bool(args.reward_kind) != bool(args.reward_item):
                raise ProtocolError("Reward kind and item must be supplied together")
            reward = None if not args.reward_kind else {k: v for k, v in {
                "kind": args.reward_kind, "item_id": args.reward_item, "gender": args.reward_gender,
                "category": args.reward_category, "name": args.reward_name}.items() if v is not None}
            result = gathering.configure(args.type_id, args.name, active=args.active,
                max_items=args.max_items, phase=args.initial_rewards,
                cooldown_seconds=args.cooldown_seconds, reward=reward)
        elif args.operation == "set-progress":
            gathering.set_progress(args.ps4_id, args.type_id, args.current, args.spaces,
                                   args.reward_claimed, args.rewards)
            result = {"updated": True}
        elif args.operation == "set-scenes":
            gathering.set_scenes(args.ps4_id, args.scenes)
            result = {"updated": True}
        elif args.operation == "set-medieval":
            gathering.set_medieval(args.ps4_id, active=args.active, amount_left=args.amount_left,
                                     cooldown_until=args.cooldown_until)
            result = {"updated": True}
        else:
            result = gathering.list_events()
        print(json.dumps(result, ensure_ascii=True, indent=2))
    except (ProtocolError, OSError, ValueError) as exc:
        parser.exit(1, str(exc) + "\n")
    finally:
        if store is not None: store.close()


if __name__ == "__main__": main()
