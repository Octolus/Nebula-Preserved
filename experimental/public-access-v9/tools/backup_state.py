"""Consistent, atomic SQLite backups with bounded retention."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def backup(source: Path, destination_dir: Path, keep: int) -> Path:
    source = source.resolve(strict=True)
    destination_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    final = destination_dir / ("preservation-" + stamp + ".sqlite3")
    if final.exists():
        raise RuntimeError("backup name collision")
    fd, temporary_name = tempfile.mkstemp(prefix=".backup-", suffix=".sqlite3",
                                          dir=destination_dir)
    os.close(fd)
    temporary = Path(temporary_name)
    src = sqlite3.connect("file:" + source.as_posix() + "?mode=ro", uri=True)
    dst = sqlite3.connect(temporary)
    try:
        src.backup(dst)
        if dst.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("backup quick_check failed")
        dst.close()
        src.close()
        os.chmod(temporary, 0o600)
        os.replace(temporary, final)
        directory_fd = os.open(destination_dir, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try: dst.close()
        except Exception: pass
        try: src.close()
        except Exception: pass
        temporary.unlink(missing_ok=True)
    receipt = final.with_suffix(".json")
    receipt.write_text(json.dumps({"format_version": 1, "database": final.name,
        "sha256": sha256(final), "created_utc": datetime.now(timezone.utc).isoformat()},
        sort_keys=True, indent=2) + "\n", encoding="utf-8")
    rows = sorted(destination_dir.glob("preservation-*.sqlite3"),
                  key=lambda p: p.stat().st_mtime, reverse=True)
    for old in rows[keep:]:
        old.with_suffix(".json").unlink(missing_ok=True)
        old.unlink()
    return final


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--keep", type=int, default=14)
    args = parser.parse_args()
    if not 1 <= args.keep <= 365:
        parser.error("--keep must be 1..365")
    print(backup(args.state_dir / "preservation.sqlite3", args.destination, args.keep))


if __name__ == "__main__":
    main()
