"""Offline credential administration; never opens a listener."""
import argparse
import json
import os
from pathlib import Path
import stat

from public_access import AccessAuthority, STEAM_ID64
from state import Store


def require_operator_key(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise SystemExit("operator key must be an accessible non-symlink file") from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
            raise SystemExit("operator key must be a regular file with mode 0600")
        if hasattr(os, "getuid") and info.st_uid not in (0, os.getuid()):
            raise SystemExit("operator key must be owned by root or the invoking account")
        secret = os.read(descriptor, 4097)
        if len(secret) < 32 or len(secret) > 4096:
            raise SystemExit("operator key must contain 32 to 4096 random bytes")
        return secret
    finally:
        os.close(descriptor)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--operator-key-file", type=Path, required=True)
    sub = parser.add_subparsers(dest="operation", required=True)
    sub.add_parser("init-operator")
    provision = sub.add_parser("provision-account")
    provision.add_argument("steam_id64")
    provision.add_argument("username")
    provision.add_argument("--platform", choices=("StandaloneWindows", "PS4"),
                           default="StandaloneWindows")
    issue = sub.add_parser("issue")
    issue.add_argument("steam_id64")
    issue.add_argument("--provenance-kind", choices=("operator-note",))
    issue.add_argument("--provenance-evidence-sha256")
    revoke = sub.add_parser("revoke")
    revoke.add_argument("steam_id64")
    args = parser.parse_args(argv)
    operator_secret = require_operator_key(args.operator_key_file)
    db_path = args.state_dir / "preservation.sqlite3"
    store = Store(db_path)
    try:
        authority = AccessAuthority(store.db)
        if args.operation == "init-operator":
            authority.initialize_operator(operator_secret)
            print(json.dumps({"operator_initialized": True}))
        elif args.operation == "provision-account":
            authority.verify_operator(operator_secret)
            if not STEAM_ID64.fullmatch(args.steam_id64):
                raise ValueError("Public preservation accounts require SteamID64")
            with store.atomic():
                profile = store.account(args.steam_id64, args.username, args.platform)
            print(json.dumps({"steam_id64": profile["ps4_id"],
                              "username": profile["username"],
                              "platform": profile["platform"],
                              "provisioned": True}, ensure_ascii=True))
        elif args.operation == "issue":
            authority.verify_operator(operator_secret)
            credential = authority.issue(
                args.steam_id64, provenance_kind=args.provenance_kind,
                provenance_evidence_sha256=args.provenance_evidence_sha256)
            # The plaintext credential is intentionally emitted exactly once.
            print(json.dumps({"steam_id64": args.steam_id64,
                              "authorization": credential}, ensure_ascii=True))
        else:
            authority.verify_operator(operator_secret)
            print(json.dumps({"steam_id64": args.steam_id64,
                              "revoked": authority.revoke(args.steam_id64)}))
    finally:
        store.close()


if __name__ == "__main__":
    main()
