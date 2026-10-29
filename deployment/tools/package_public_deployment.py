"""Build a hash-manifested archive from an already merged integration tree.

This tool never installs, enables, starts, or contacts anything.  It refuses a
tree that does not contain the public-access integration markers.
"""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile


REQUIRED = (
    "backend/server.py", "backend/state.py", "backend/public_access.py",
    "backend/public_access_admin.py", "tools/instance_supervisor.py",
    "backend/economy_admin.py", "client-auth/NebulaPublicAccess.dll",
    "client-auth/unitywebrequest-get-calls.json",
    "tools/backup_state.py", "tools/migrate_public_access.py",
    "deployment/instance-supervisor/nebula-managed-http.service",
    "deployment/instance-supervisor/nebula-instance-supervisor.service",
)


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--integrated-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.integrated_root.resolve(strict=True)
    for relative in REQUIRED:
        if not (root / relative).is_file():
            parser.error("integrated tree is missing " + relative)
    server = (root / "backend/server.py").read_text(encoding="utf-8")
    if "--public-access" not in server or "actor_scope" not in server:
        parser.error("server public-access integration is absent")
    rows = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            parser.error("symlinks are not permitted: " + str(path))
        if path.is_file() and "__pycache__" not in path.parts:
            rows.append({"path": path.relative_to(root).as_posix(),
                         "bytes": path.stat().st_size, "sha256": digest(path)})
    manifest = {"format_version": 1,
                "archive_timestamp": 0,
                "public_access": "per-account-credential-v1",
                "steam_ticket_validation": False,
                "files": rows}
    payload = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
                for row in rows:
                    path = root / row["path"]
                    info = archive.gettarinfo(
                        str(path), arcname="nebula-preservation/" + row["path"])
                    info.uid = info.gid = 0
                    info.uname = info.gname = "root"
                    info.mtime = 0
                    with path.open("rb") as stream:
                        archive.addfile(info, stream)
                info = tarfile.TarInfo("nebula-preservation/MANIFEST.json")
                info.size = len(payload)
                info.mode = 0o644
                info.mtime = 0
                archive.addfile(info, io.BytesIO(payload))
    print(json.dumps({"archive": str(args.output), "sha256": digest(args.output),
                      "files": len(rows)}, sort_keys=True))


if __name__ == "__main__":
    main()
