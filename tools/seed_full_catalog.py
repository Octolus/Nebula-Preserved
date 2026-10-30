"""Plan or atomically import every validated item. Never changes player state."""
from pathlib import Path
import argparse
import json
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from catalog_inventory import seed_full_catalog
from service import Service
from state import Catalog, Store


def execute(protocol_dir, state_dir=None, apply=False):
    if apply and state_dir is None:
        raise ValueError("--apply requires an explicit --state-dir")
    temporary = tempfile.TemporaryDirectory(prefix="nebula-full-catalog-") if not apply else None
    store = None
    try:
        directory = Path(state_dir) if apply else Path(temporary.name)
        if apply and not (directory / "preservation.sqlite3").is_file():
            raise ValueError("Apply requires an existing initialized preservation database")
        store = Store(directory / "preservation.sqlite3")
        service = Service(store, Catalog(Path(protocol_dir)))
        result = seed_full_catalog(service)
        return {**result, "mode": "applied" if apply else "dry-run"}
    finally:
        if store is not None:
            store.close()
        if temporary is not None:
            temporary.cleanup()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol-dir", type=Path, default=ROOT / "protocol")
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        print(json.dumps(execute(args.protocol_dir, args.state_dir, args.apply), indent=2))
    except (ValueError, RuntimeError, OSError) as exc:
        parser.exit(1, str(exc) + "\n")


if __name__ == "__main__":
    main()
