#!/usr/bin/env python3
"""Package a compiled Windows x64 patcher; never build or include game bundles."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import struct
import tomllib
import zipfile

ARCHIVE = "nebula-preservation-patcher-windows-x64.zip"
EXECUTABLE = "nebula-preservation-patcher.exe"
TARGET = "x86_64-pc-windows-msvc"

README = """Nebula preservation patcher — Windows x64

This archive contains the Windows launcher and command-line patcher. It does not contain the
game, original assets, server files, a patch bundle, account credentials or
private test fixtures. Own and install the supported Steam game separately.

The generic CI EXE has no compiled deployment-specific bundle pin, server or CA.
It opens the launcher and discovers installed games, but cannot launch a game
until a reviewed release build supplies those inputs. CLI patching requires a
separately reviewed preservation bundle and published manifest SHA256. Do not use
release-input templates or test fixtures as a bundle. Read the source project's
patcher/README.md, docs/LAUNCHER.md and docs/PATCHER-RELEASE.md for supported versions and limits.

Start in PowerShell with:
  .\\nebula-preservation-patcher.exe gui
  .\\nebula-preservation-patcher.exe --help

For a reviewed DIRECT network bundle, review this dry run first:
  .\\nebula-preservation-patcher.exe patch --bundle "BUNDLE_FOLDER" --manifest-sha256 "PUBLISHED_MANIFEST_SHA256" --server "http://SERVER_IPV4:8080" --advertise-ip "SERVER_IPV4" --allow-provisional --dry-run

Keep the game closed. Repeat without --dry-run only after checking the intended
installation, server and bundle. HTTPS/remote transport has separate reviewed
configuration requirements; this direct example does not configure it. Retain
the tool's .nebula-preservation transaction receipts and backups for restore.

These builds are unsigned. Windows SmartScreen may show an unknown-publisher or
reputation warning. No code-signing certificate, signature or SmartScreen trust
is claimed. Check SHA256SUMS against the separately downloaded release checksum
file and obtain artifacts from the intended source. A checksum detects changed
bytes; it does not establish publisher identity by itself.

THIRD_PARTY_NOTICES.md and Cargo.lock identify dependency provenance. A project
license is included only when the maintainer has actually selected one; no
project-wide license is inferred from the absence of a LICENSE file.
"""


def require(value: bool, message: str) -> None:
    if not value:
        raise ValueError(message)


def direct(path: Path) -> Path:
    path = Path(os.path.abspath(path))
    for item in (path, *path.parents):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        require(not stat.S_ISLNK(info.st_mode) and not getattr(info, "st_file_attributes", 0) & 0x400,
                "Linked/reparse input or output is not supported")
    return path


def read(path: Path, limit: int) -> bytes:
    path = direct(path)
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_size <= limit, "Regular bounded input required")
        raw = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
    require(len(raw) <= limit and
            (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) ==
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns), "Input changed during packaging")
    return raw


def verify_pe(raw: bytes) -> None:
    require(len(raw) >= 128 and raw[:2] == b"MZ", "Compiled Windows PE executable required")
    offset = struct.unpack_from("<I", raw, 0x3C)[0]
    require(64 <= offset <= len(raw) - 26 and raw[offset:offset + 4] == b"PE\0\0", "Invalid PE header")
    machine, = struct.unpack_from("<H", raw, offset + 4)
    optional_size, flags, magic = struct.unpack_from("<HHH", raw, offset + 20)
    require(machine == 0x8664 and optional_size >= 112 and offset + 24 + optional_size <= len(raw) and
            flags & 0x2 and not flags & 0x2000 and magic == 0x20B, "Expected an executable Windows x64 PE32+ build")


def checksum(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def package(repository: Path, binary: Path, output: Path, *, commit: str | None = None) -> dict:
    repository, binary, output = direct(repository), direct(binary), direct(output)
    require(repository.is_dir() and binary.name == EXECUTABLE, "Explicit repository and patcher EXE required")
    require(not output.exists() and output.parent.is_dir(), "Output directory must be NEW with an existing parent")
    require(commit is None or re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", commit) is not None, "Invalid source commit")
    raw = read(binary, 64 * 1024 * 1024)
    verify_pe(raw)
    manifest = tomllib.loads(read(repository / "patcher/Cargo.toml", 128 * 1024).decode("utf-8"))
    require(manifest["package"]["name"] == "nebula-preservation-patcher", "Unexpected Cargo package")
    files = {EXECUTABLE: raw, "README.md": README.encode("utf-8"),
             "THIRD_PARTY_NOTICES.md": read(repository / "THIRD_PARTY_NOTICES.md", 2 * 1024 * 1024),
             "Cargo.lock": read(repository / "patcher/Cargo.lock", 2 * 1024 * 1024)}
    licenses = [repository / name for name in ("LICENSE", "LICENSE.md", "LICENSE.txt")
                if (repository / name).exists() or (repository / name).is_symlink()]
    require(len(licenses) <= 1, "Select one unambiguous project license file")
    if licenses:
        files[licenses[0].name] = read(licenses[0], 512 * 1024)
    files["BUILD-INFO.json"] = (json.dumps({"package": manifest["package"]["name"],
        "version": manifest["package"]["version"], "target": TARGET, "source_commit": commit,
        "code_signed": False, "game_or_patch_bundle_included": False,
        "project_license_included": bool(licenses)}, indent=2, sort_keys=True) + "\n").encode()
    files["SHA256SUMS"] = "".join(f"{checksum(data)}  {name}\n" for name, data in sorted(files.items())).encode()
    # Fixed ZIP metadata avoids leaking source paths, user names or local times.
    output.mkdir()
    archive = output / ARCHIVE
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for name, data in sorted(files.items()):
            item = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            item.compress_type = zipfile.ZIP_DEFLATED
            item.create_system = 3
            item.external_attr = 0o100644 << 16
            bundle.writestr(item, data)
    sums = output / "SHA256SUMS"
    with sums.open("x", encoding="ascii", newline="\n") as stream:
        stream.write(f"{checksum(archive.read_bytes())}  {ARCHIVE}\n")
    return {"archive": str(archive), "sha256": checksum(archive.read_bytes()),
            "files": sorted(files), "project_license_included": bool(licenses)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--commit")
    args = parser.parse_args(argv)
    print(json.dumps(package(args.repository, args.binary, args.output_dir, commit=args.commit), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
