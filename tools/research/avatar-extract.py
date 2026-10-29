"""Recover avatar contracts from build-local IL2CPP metadata and Unity asset data.

Static only. This script never launches the target or changes its installation.
"""

from _research_paths import workspace, output_root, game_path
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from extract_protocol_metadata import parse_types


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, default=(workspace() / 'work'))
    parser.add_argument("--out", type=Path, default=(workspace() / 'results/protocol'))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    dump = args.work / "decompiled/dump.cs"
    types = parse_types(dump.read_text(encoding="utf-8-sig"))
    selected = [x for x in types if x["type_def_index"] < 2434 and re.search(
        r"Preset|PlayerPrefs|IdAssets|AssetInfo|Cloth|Wardrobe|Avatar|IndividualAssembler|Purchase|MANAGEREditor|LastPosJson|NETGcloud.*Editor", x["full_name"])]
    clean = [{k: v for k, v in x.items() if k != "raw"} for x in selected]
    (args.out / "avatar-metadata-schemas.json").write_text(json.dumps(clean, indent=2), encoding="utf-8")
    (args.out / "avatar-declarations.md").write_text("# Recovered avatar IL2CPP declarations\n\nThese are metadata declarations with stub method bodies, not reconstructed C# implementations.\n\n```csharp\n" + "\n".join(x["raw"] for x in selected) + "\n```\n", encoding="utf-8")
    print("\n".join(f'{x["type_def_index"]}: {x["full_name"]} ({len(x["fields"])} fields, {len(x["methods"])} methods)' for x in selected))
    manifest = {"source_sha256": hashlib.sha256(dump.read_bytes()).hexdigest(), "type_count": len(selected),
                "evidence_type": "IL2CPP declarations, not recovered C# bodies"}
    (args.out / "avatar-metadata-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
