"""Consistent, verified state backups with day/deploy retention and an optional off-host hook.

Each backup set is `preservation-<UTC stamp>[-deploy]` with:
  .sqlite3        online SQLite backup (quick_check verified)
  .state.tar.gz   per-instance JSON state (<state>/instance-*.json and
                  <state>/instances/*/instance-*.json), re-read and hash verified
  .json           receipt written last; a set without it is incomplete
Retention keeps the newest set of each UTC day for --keep-days days plus the
newest --keep-deploy deploy-triggered sets, so repeated deploys cannot flush
daily history. Legacy `preservation-<stamp>.sqlite3` sets count as scheduled.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import tarfile
import tempfile

SET_NAME = re.compile(r"preservation-(\d{8}T\d{6}Z)(-deploy)?\.sqlite3\Z")
KINDS = ("scheduled", "deploy")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_dir(directory: Path) -> None:
    if os.name == "nt":
        return
    directory_fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _publish(temporary: Path, final: Path) -> None:
    os.chmod(temporary, 0o600)
    os.replace(temporary, final)
    _fsync_dir(final.parent)


def _temporary(directory: Path, suffix: str) -> Path:
    fd, name = tempfile.mkstemp(prefix=".backup-", suffix=suffix, dir=directory)
    os.close(fd)
    return Path(name)


def state_files(state_dir: Path) -> list[Path]:
    """Per-instance JSON state; atomically replaced by their writers, so each read is whole."""
    files = list(state_dir.glob("instance-*.json")) + list(state_dir.glob("instances/*/instance-*.json"))
    return sorted((path for path in files if path.is_file() and not path.is_symlink()),
                  key=lambda path: path.relative_to(state_dir).as_posix())


def _backup_database(source: Path, temporary: Path) -> None:
    src = sqlite3.connect("file:" + source.as_posix() + "?mode=ro", uri=True)
    dst = sqlite3.connect(temporary)
    try:
        src.backup(dst)
        if dst.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("backup quick_check failed")
    finally:
        dst.close()
        src.close()


def _archive_state(state_dir: Path, temporary: Path) -> list[dict]:
    rows = []
    with tarfile.open(temporary, "w:gz") as archive:
        for path in state_files(state_dir):
            try:
                data = path.read_bytes()
            except FileNotFoundError:
                continue  # Instance removed between listing and read.
            name = path.relative_to(state_dir).as_posix()
            try:
                json.loads(data.decode("utf-8"))
                valid = True
            except (UnicodeDecodeError, ValueError):
                valid = False  # Preserve evidence; the receipt flags it.
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.mtime = len(data), 0o600, int(path.stat().st_mtime)
            archive.addfile(info, io.BytesIO(data))
            rows.append({"path": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                         "json_valid": valid})
    # Verify by re-reading the written archive, not the in-memory copy.
    with tarfile.open(temporary, "r:gz") as archive:
        members = {member.name: member for member in archive.getmembers()}
        if sorted(members) != [row["path"] for row in rows]:
            raise RuntimeError("state archive member list does not verify")
        for row in rows:
            stream = archive.extractfile(members[row["path"]])
            if stream is None or hashlib.sha256(stream.read()).hexdigest() != row["sha256"]:
                raise RuntimeError("state archive content does not verify")
    return rows


def backup_sets(destination_dir: Path) -> list[dict]:
    sets = []
    for path in destination_dir.glob("preservation-*.sqlite3"):
        match = SET_NAME.fullmatch(path.name)
        if match:
            created = datetime.strptime(match.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
            sets.append({"database": path, "created": created,
                         "kind": "deploy" if match.group(2) else "scheduled"})
    return sorted(sets, key=lambda row: (row["created"], row["database"].name), reverse=True)


def retained(sets: list[dict], now: datetime, keep_days: int, keep_deploy: int) -> set[Path]:
    keep = {sets[0]["database"]} if sets else set()
    first_day = (now - timedelta(days=keep_days - 1)).date()
    seen_days = set()
    for row in sets:  # Newest first: the first set seen for a day is that day's newest.
        day = row["created"].date()
        if day >= first_day and day not in seen_days:
            seen_days.add(day)
            keep.add(row["database"])
    keep.update(row["database"] for row in [row for row in sets if row["kind"] == "deploy"][:keep_deploy])
    return keep


def prune(destination_dir: Path, now: datetime, keep_days: int, keep_deploy: int) -> list[str]:
    sets = backup_sets(destination_dir)
    keep = retained(sets, now, keep_days, keep_deploy)
    removed = []
    for row in sets:
        if row["database"] not in keep:
            database = row["database"]
            for path in (database.with_suffix(".json"), database.with_suffix(".state.tar.gz"), database):
                path.unlink(missing_ok=True)
            removed.append(database.name)
    return removed


def backup(state_dir: Path, destination_dir: Path, *, keep_days: int = 14, keep_deploy: int = 5,
           kind: str = "scheduled", now: datetime | None = None) -> Path:
    if kind not in KINDS:
        raise ValueError("unknown backup kind")
    source = (state_dir / "preservation.sqlite3").resolve(strict=True)
    state_dir = state_dir.resolve(strict=True)
    destination_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    now = now or datetime.now(timezone.utc)
    base = "preservation-" + now.strftime("%Y%m%dT%H%M%SZ") + ("-deploy" if kind == "deploy" else "")
    final = destination_dir / (base + ".sqlite3")
    archive = destination_dir / (base + ".state.tar.gz")
    receipt = destination_dir / (base + ".json")
    if any(path.exists() for path in (final, archive, receipt)):
        raise RuntimeError("backup name collision")
    temporaries = [_temporary(destination_dir, ".sqlite3"), _temporary(destination_dir, ".tar.gz"),
                   _temporary(destination_dir, ".json")]
    try:
        _backup_database(source, temporaries[0])
        files = _archive_state(state_dir, temporaries[1])
        _publish(temporaries[0], final)
        _publish(temporaries[1], archive)
        temporaries[2].write_text(json.dumps({
            "format_version": 2, "kind": kind, "database": final.name, "sha256": sha256(final),
            "state_archive": archive.name, "state_archive_sha256": sha256(archive),
            "state_files": files, "created_utc": now.isoformat()}, sort_keys=True, indent=2) + "\n",
            encoding="utf-8")
        _publish(temporaries[2], receipt)
    except BaseException:
        for path in (final, archive):
            path.unlink(missing_ok=True)
        raise
    finally:
        for path in temporaries:
            path.unlink(missing_ok=True)
    prune(destination_dir, now, keep_days, keep_deploy)
    return final


def run_offsite(final: Path, *, hook: Path | None = None, command: str = "", timeout: float = 1800) -> int | None:
    """Optional off-host copy after a complete, verified set. Disabled unless configured."""
    argv = None
    if hook is not None and hook.is_file():
        argv, shell = [str(hook)], False
    elif command.strip():
        argv, shell = command, True
    if argv is None:
        return None
    env = {**os.environ, "NEBULA_BACKUP_DIR": str(final.parent), "NEBULA_BACKUP_DATABASE": str(final),
           "NEBULA_BACKUP_STATE_ARCHIVE": str(final.with_suffix(".state.tar.gz")),
           "NEBULA_BACKUP_RECEIPT": str(final.with_suffix(".json"))}
    return subprocess.run(argv, shell=shell, env=env, timeout=timeout, check=False,
                          stdin=subprocess.DEVNULL).returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--keep-days", "--keep", dest="keep_days", type=int, default=14,
                        help="newest set per UTC day for this many days (--keep is the legacy alias)")
    parser.add_argument("--keep-deploy", type=int, default=5, help="newest deploy-triggered sets kept")
    parser.add_argument("--kind", choices=KINDS, default="scheduled")
    parser.add_argument("--offsite-hook", type=Path,
                        help="executable run after success when it exists (no shell)")
    parser.add_argument("--offsite-timeout", type=float, default=1800)
    args = parser.parse_args()
    if not 1 <= args.keep_days <= 365 or not 0 <= args.keep_deploy <= 100:
        parser.error("--keep-days must be 1..365 and --keep-deploy 0..100")
    final = backup(args.state_dir, args.destination, keep_days=args.keep_days,
                   keep_deploy=args.keep_deploy, kind=args.kind)
    print(final)
    code = run_offsite(final, hook=args.offsite_hook,
                       command=os.environ.get("NEBULA_BACKUP_OFFSITE_COMMAND", ""),
                       timeout=args.offsite_timeout)
    if code:
        # The verified local set is kept; fail the unit so the copy failure is visible.
        raise SystemExit("off-host copy hook failed with exit code " + str(code))


if __name__ == "__main__":
    main()
