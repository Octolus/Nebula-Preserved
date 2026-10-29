"""Apply the proven wardrobe loop fix to a NEW binary copy; never overwrite input.

This changes no installation files, executes no target, and does not establish
game readiness. Patch evidence is protocol/tcp-wardrobe-patch.json.
"""
import argparse
import hashlib
import json
from pathlib import Path

ORIGINAL_SHA256 = "c4dd5db599e5e5ce4adf25f09ffe70ad10e0928adf6a2e862176d537026b44ac"
PATCHED_SHA256 = "29abe9dbf4f310ba72b4de19273da85c797e529fac6511ba40bb9f88314dc420"
OFFSET = 0x607323
BEFORE = bytes.fromhex("7d4e")
AFTER = bytes.fromhex("7f4e")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    destination = args.destination.resolve()
    if source == destination or destination.exists() or "steamapps" in [p.lower() for p in destination.parts]:
        parser.error("Destination must be a new file, separate from the source")
    manifest_path = args.manifest.resolve() if args.manifest else None
    if manifest_path is not None and (manifest_path in (source, destination) or manifest_path.exists()
            or manifest_path.suffix.lower() != ".json" or "steamapps" in [p.lower() for p in manifest_path.parts]):
        parser.error("Manifest must be a new separate JSON file outside steamapps")
    raw = bytearray(source.read_bytes())
    if hashlib.sha256(raw).hexdigest() != ORIGINAL_SHA256:
        parser.error("Source SHA256 differs from the analyzed Steam build; no output written")
    if raw[OFFSET:OFFSET + 2] != BEFORE:
        parser.error("Expected native branch bytes are absent; no output written")
    raw[OFFSET:OFFSET + 2] = AFTER
    if hashlib.sha256(raw).hexdigest() != PATCHED_SHA256:
        parser.error("Patched hash mismatch; no output written")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as output:
        output.write(raw)
    manifest = {"source_sha256": ORIGINAL_SHA256, "copy_sha256": PATCHED_SHA256,
                "patch": "GetAllInWardrobe loop includes final output element",
                "rva": "0x608323", "file_offset": hex(OFFSET),
                "before": BEFORE.hex(), "after": AFTER.hex(),
                "source_changed": False, "target_executed": False,
                "parity_proven": False}
    if manifest_path:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with manifest_path.open("x", encoding="utf-8") as output:
            output.write(json.dumps(manifest, indent=2))
    print(json.dumps(manifest, ensure_ascii=True))


if __name__ == "__main__":
    main()
