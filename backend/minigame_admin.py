"""Offline HTTP minigame policy administration. Never starts a listener.

Optional item rewards behind minigame replies are configured with
rewards_admin.py (routes checkRewardGameServlet, SetCooldownServlet,
XSpacesGamesType0Servlet and Send_ArcheryCupidConsume).
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from allocation import InstanceDirectory
from minigames import SETTINGS, Minigames
from rewards import RewardService
from state import Catalog, Store
from wire import ProtocolError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, default=Path("work/server-state"))
    commands = parser.add_subparsers(dest="operation", required=True)
    configure = commands.add_parser("set")
    configure.add_argument("name", choices=sorted(SETTINGS))
    configure.add_argument("value", type=int)
    commands.add_parser("settings")
    board = commands.add_parser("leaderboard")
    board.add_argument("game", choices=("archery", "boat"))
    args = parser.parse_args()
    store = None
    try:
        store = Store(args.state_dir / "preservation.sqlite3")
        rewards = RewardService(store, Catalog(ROOT / "protocol"), InstanceDirectory(args.state_dir))
        minigames = Minigames(store, rewards)
        if args.operation == "set":
            result = minigames.configure(args.name, args.value)
        elif args.operation == "settings":
            result = minigames.settings()
        else:
            result = [{"rank": i + 1, "username": name, "score": score}
                      for i, (name, score) in enumerate(minigames.leaderboard(args.game))]
        print(json.dumps(result, ensure_ascii=True, indent=2))
    except (ProtocolError, OSError, ValueError) as exc:
        parser.exit(1, str(exc) + "\n")
    finally:
        if store is not None:
            store.close()


if __name__ == "__main__":
    main()
