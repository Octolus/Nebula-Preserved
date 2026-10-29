"""Apply the additive public-access schema after taking a verified backup."""
import argparse
from pathlib import Path
import sqlite3
import sys

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "backend"))
from public_access import migrate
from backup_state import backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--backup-dir", type=Path, required=True)
    args = parser.parse_args()
    database = args.state_dir / "preservation.sqlite3"
    print("backup=" + str(backup(database, args.backup_dir, 14)))
    db = sqlite3.connect(database)
    try:
        db.execute("PRAGMA foreign_keys=ON")
        migrate(db)
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("post-migration quick_check failed")
    finally:
        db.close()
    print("migration=public-access-v2")


if __name__ == "__main__":
    main()
