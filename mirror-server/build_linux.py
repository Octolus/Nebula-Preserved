#!/usr/bin/env python3
"""Build and hash the Linux dedicated server; never launch it."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import uuid


MARKER = "NEBULA_LINUX_SERVER_BUILD_SUCCESS"
EDITOR_VERSION = "6000.6.3f1"
PRESERVATION_NAMES = (
    "NebulaAnimationWire", "NebulaApplicationCrypto", "NebulaCoreReadiness",
    "NebulaInformationalNotifications", "NebulaInstanceAccounts",
    "NebulaInstancePresence", "NebulaInstanceServer", "NebulaInteractionRegistry",
    "NebulaMinigameState", "NebulaMirrorCommands", "NebulaMirrorProbe",
    "NebulaNotificationInbox", "NebulaResourceSelections", "NebulaSocialMailbox",
    "NebulaSocialRelationSnapshot", "NebulaSocialState", "NebulaSpawnState",
    "NebulaWorldState",
)
SOURCE_PATHS = tuple(sorted(
    [f"UnityProject/Assets/Preservation/{name}.cs" for name in PRESERVATION_NAMES] + [
        "UnityProject/Assets/Editor/PreservationBuild.cs",
        "UnityProject/Assets/Mirror/Runtime/Transports/Telepathy/Telepathy/Server.cs",
        "UnityProject/Assets/Mirror/Runtime/Transports/Telepathy/TelepathyTransport.cs",
    ]
))


class BuildError(ValueError):
    pass


def checked_path(path: Path, *, directory: bool = False, missing: bool = False) -> Path:
    """Reject links/reparse points in every existing path component."""
    path = Path(os.path.abspath(path))
    for component in reversed((path, *path.parents)):
        try:
            info = component.lstat()
        except FileNotFoundError:
            if missing:
                continue
            raise BuildError("Required build path is missing") from None
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise BuildError("Linked or reparse-point build paths are not allowed")
        if component != path and not stat.S_ISDIR(info.st_mode):
            raise BuildError("Build path has a non-directory parent")
    if path.exists():
        mode = path.stat().st_mode
        if not (stat.S_ISDIR(mode) if directory else stat.S_ISREG(mode)):
            raise BuildError("Build path has the wrong file type")
    elif not missing:
        raise BuildError("Required build path is missing")
    return path


def sha256(path: Path) -> str:
    checked_path(path)
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    after = checked_path(path).stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise BuildError("Build file changed while being hashed")
    return digest.hexdigest()


def tree_files(root: Path) -> list[Path]:
    checked_path(root, directory=True)
    result = []
    def traversal_failed(error):
        raise BuildError("Cannot enumerate the complete source/artifact tree") from error
    for parent, directories, names in os.walk(root, followlinks=False, onerror=traversal_failed):
        for name in directories:
            checked_path(Path(parent) / name, directory=True)
        for name in names:
            if name in (".", "..") or any(ord(char) < 32 or char in "\\:" for char in name):
                raise BuildError("Artifact/source filename cannot be represented as a safe relative path")
            result.append(checked_path(Path(parent) / name))
    return sorted(result, key=lambda path: path.relative_to(root).as_posix())


def source_hashes(root: Path) -> list[dict]:
    preservation = root / "UnityProject/Assets/Preservation"
    actual = {path.relative_to(root).as_posix() for path in tree_files(preservation)
              if path.suffix.lower() == ".cs"}
    expected = {p for p in SOURCE_PATHS if "/Preservation/" in p}
    if actual != expected:
        raise BuildError("Expected the reviewed set of 18 Preservation C# sources")
    return [{"path": relative, "sha256": sha256(root / relative)}
            for relative in SOURCE_PATHS]


def validate_elf(path: Path) -> None:
    checked_path(path)
    with path.open("rb") as stream:
        header = stream.read(64)
    if (len(header) != 64 or header[:7] != b"\x7fELF\x02\x01\x01" or
            int.from_bytes(header[16:18], "little") not in (2, 3) or
            int.from_bytes(header[18:20], "little") != 62 or
            int.from_bytes(header[20:24], "little") != 1 or
            int.from_bytes(header[52:54], "little") != 64):
        raise BuildError("Build is not an ELF64 little-endian x86-64 executable")
    if os.name != "nt" and not os.access(path, os.X_OK):
        raise BuildError("Linux server artifact is not executable")


def build(root: Path, unity: Path, *, run=None) -> dict:
    root = checked_path(root, directory=True)
    project = checked_path(root / "UnityProject", directory=True)
    unity = checked_path(unity)
    if os.name != "nt" and not os.access(unity, os.X_OK):
        raise BuildError("Unity editor is not executable")
    version = checked_path(project / "ProjectSettings/ProjectVersion.txt")
    if not re.search(r"^m_EditorVersion: " + re.escape(EDITOR_VERSION) + r"\s*$",
                     version.read_text(encoding="utf-8-sig"), re.MULTILINE):
        raise BuildError("Unity project version must match the reviewed editor version")
    output = root / "build-linux"
    checked_path(output, directory=True, missing=True)
    if output.exists():
        tree_files(output)  # Refuse linked outputs before invoking Unity.
    report_path = checked_path(root / "build-linux-validation.json", missing=True)
    lock = checked_path(root / ".build-linux.lock", missing=True)
    before = source_hashes(root)
    nonce = uuid.uuid4().hex
    log = checked_path(root / f"build-linux-{nonce}.log", missing=True)
    temporary = root / f".build-linux-validation-{nonce}.tmp"
    try:
        lock_stream = lock.open("x", encoding="utf-8")
    except FileExistsError:
        raise BuildError("Another build owns the build lock; inspect it before retrying") from None
    try:
        with lock_stream:
            lock_stream.write("Linux compile only\n")
            lock_stream.flush()
            with log.open("x", encoding="utf-8"):
                pass
            command = [str(unity), "-batchmode", "-nographics", "-quit",
                       "-projectPath", str(project), "-buildTarget", "Linux64",
                       "-standaloneBuildSubtarget", "Server", "-executeMethod",
                       "PreservationBuild.BuildLinuxServer", "-logFile", str(log)]
            process = (run or subprocess.run)(command, cwd=str(project), check=False,
                                             stdout=subprocess.DEVNULL,
                                             stderr=subprocess.STDOUT)
            if process.returncode != 0:
                raise BuildError(f"Unity Linux build failed with exit code {process.returncode}; see {log.name}")
            after = source_hashes(root)
            if before != after:
                raise BuildError("Sources changed during build; rebuild after edits settle")
            checked_path(log)
            if MARKER not in log.read_text(encoding="utf-8-sig", errors="replace"):
                raise BuildError(f"Unity exited without the Linux build-success marker; see {log.name}")
            executable = output / "NebulaServer.x86_64"
            assembly = output / "NebulaServer_Data/Managed/Assembly-CSharp.dll"
            validate_elf(executable)
            checked_path(assembly)
            artifacts = [{"path": path.relative_to(output).as_posix(),
                          "size": path.stat().st_size, "sha256": sha256(path)}
                         for path in tree_files(output)]
            if source_hashes(root) != before:
                raise BuildError("Sources changed during artifact verification")
            artifact_by_path = {row["path"]: row for row in artifacts}
            report = {
                "kind": "compile_only_linux_dedicated_server_build",
                "utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "unity_editor": EDITOR_VERSION, "exit_code": 0,
                "success_marker": MARKER, "target": "StandaloneLinux64",
                "subtarget": "Server", "scripting_backend": "Mono2x",
                "elf64_x86_64": True, "game_launched": False,
                "reconstructed_listener_started": False, "linux_runtime_tested": False,
                "sources_unchanged_during_build": True, "source_hashes": after,
                "artifacts": artifacts,
                "executable_sha256": artifact_by_path["NebulaServer.x86_64"]["sha256"],
                "managed_assembly_sha256": artifact_by_path[
                    "NebulaServer_Data/Managed/Assembly-CSharp.dll"]["sha256"],
                "networking_parity_proven": False,
            }
            checked_path(report_path, missing=True)
            with temporary.open("x", encoding="utf-8", newline="\n") as stream:
                json.dump(report, stream, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, report_path)
            return report
    finally:
        if temporary.exists() and not temporary.is_symlink():
            temporary.unlink()
        # Do not remove output artifacts or private build logs on failure.
        lock.unlink()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unity", required=True, type=Path, help="Path to the installed Unity editor executable")
    parser.add_argument("--build", action="store_true", help="Explicitly invoke Unity and validate its Linux build")
    args = parser.parse_args(argv)
    if not args.build:
        parser.error("--build is required to invoke Unity")
    try:
        report = build(Path(__file__).absolute().parent, args.unity)
    except (BuildError, OSError) as exc:
        parser.exit(1, f"Linux build validation failed: {exc}\n")
    print(json.dumps({"report": "build-linux-validation.json",
                      "artifacts": len(report["artifacts"]), "game_launched": False,
                      "linux_runtime_tested": False}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
