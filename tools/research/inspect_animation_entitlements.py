"""Inspect Nebula Realms animation-menu data without starting the game.

This intentionally separates authored menu entries from server entitlements.
An authored animation trigger is not evidence that an account owned an item.
Requires UnityPy; reads only ``resources.assets`` and saved static evidence.
"""
from __future__ import annotations

from _research_paths import workspace, output_root, game_path

import argparse
import hashlib
import json
import re
import struct
from pathlib import Path

import UnityPy


ROOT = workspace()
GROUPS = (
    "animations", "dances", "emotes", "gestures", "poses",
    "profilePictures", "bundles", "bundlesHousing",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def align4(value: int) -> int:
    return (value + 3) & ~3


class Reader:
    def __init__(self, data: bytes, offset: int = 32):
        self.data, self.pos = data, offset

    def u32(self) -> int:
        value = struct.unpack_from("<I", self.data, self.pos)[0]
        self.pos += 4
        return value

    def pptrs(self) -> list[dict[str, int]]:
        result = []
        for _ in range(self.u32()):
            file_id, path_id = struct.unpack_from("<iq", self.data, self.pos)
            self.pos += 12
            result.append({"file_id": file_id, "path_id": path_id})
        return result

    def string(self) -> str:
        size = self.u32()
        end = self.pos + size
        if end > len(self.data):
            raise ValueError("serialized string exceeds component")
        value = self.data[self.pos:end].decode("utf-8")
        self.pos = align4(end)
        return value

    def strings(self) -> list[str]:
        return [self.string() for _ in range(self.u32())]


def parse_inflater(raw: bytes) -> dict:
    # MonoBehaviour header is 32 bytes in this Unity 2021 resources.assets.
    r = Reader(raw)
    male = r.pptrs()
    female = r.pptrs()
    header = r.string()
    names = r.strings()
    anims = r.strings()
    if len(names) != len(anims):
        raise ValueError("entryNames and entryAnims are not parallel")
    return {
        "entry_header": header,
        "entry_names": names,
        "entry_anims": anims,
        "entries": [{"display_name": n, "animation_trigger": a} for n, a in zip(names, anims)],
        "gender_filter_clip_refs": {"male": male, "female": female},
    }


def declarations(dump: str) -> dict:
    result = {}
    for field in GROUPS:
        match = re.search(rf"public List<string> {re.escape(field)}; // (0x[0-9A-F]+)", dump)
        if match:
            result[field] = {"ids_field": field, "ids_offset": match.group(1)}
        name_field = field + "Name"
        match = re.search(rf"public List<string> {re.escape(name_field)}; // (0x[0-9A-F]+)", dump)
        if match:
            result.setdefault(field, {})["names_field"] = name_field
            result[field]["names_offset"] = match.group(1)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--game", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "results/protocol/animation-entitlements.json")
    args = parser.parse_args()
    data = args.game / "Nebula Realms_Data"
    resources = data / "resources.assets"
    global_assets = data / "globalgamemanagers.assets"
    dump_path = ROOT / "work/decompiled/dump.cs"
    manifests_path = ROOT / "work/evidence/assets/bundle-manifests.json"

    scripts_env = UnityPy.load(str(global_assets))
    scripts = {o.path_id: o.read() for o in scripts_env.objects if o.type.name == "MonoScript"}
    env = UnityPy.load(str(resources))
    objects = {o.path_id: o for o in env.objects}
    inflaters = []
    for obj in env.objects:
        if obj.type.name != "MonoBehaviour":
            continue
        base = obj.read(check_read=False)
        script = scripts.get(base.m_Script.m_PathID) if base.m_Script.m_FileID == 1 else None
        if not script or script.m_ClassName != "MenuWheelInflate":
            continue
        row = {"path_id": obj.path_id, "raw_sha256": hashlib.sha256(obj.get_raw_data()).hexdigest()}
        row.update(parse_inflater(obj.get_raw_data()))
        for refs in row["gender_filter_clip_refs"].values():
            for ref in refs:
                target = objects.get(ref["path_id"]) if ref["file_id"] == 0 else None
                ref["clip_name"] = target.read().m_Name if target and target.type.name == "AnimationClip" else None
        inflaters.append(row)

    manifests = json.loads(manifests_path.read_text(encoding="utf-8"))
    category_pattern = re.compile(r"(?:^|/)(animations?|dances?|emotes?|gestures?|poses?|profilepictures?)(?:/|$)", re.I)
    category_paths = sorted({asset for bundle in manifests for asset in bundle["assets"] if category_pattern.search(asset)})
    dump = dump_path.read_text(encoding="utf-8")
    native = {}
    for rva in ("4ba520", "4ba930", "4be9d0", "4bb570", "4bb5b0", "4bb090", "615f30", "6162f0", "634fb0"):
        path = ROOT / f"work/evidence/ghidra/functions/{rva}.c"
        if path.exists():
            native[rva] = {"path": path.relative_to(ROOT).as_posix(), "sha256": sha256(path)}

    result = {
        "scope": "Static, read-only shipped-client evidence. No game, server, listener, connection, or runtime target was started.",
        "sources": {
            "tool": {"path": Path(__file__).resolve().relative_to(ROOT).as_posix(), "sha256": sha256(Path(__file__).resolve())},
            "resources.assets": {"path": str(resources), "sha256": sha256(resources)},
            "globalgamemanagers.assets": {"path": str(global_assets), "sha256": sha256(global_assets)},
            "bundle_manifests": {"path": manifests_path.relative_to(ROOT).as_posix(), "sha256": sha256(manifests_path)},
            "dump": {"path": dump_path.relative_to(ROOT).as_posix(), "sha256": sha256(dump_path)},
            "native_pseudocode": native,
        },
        "get_purchases_parallel_fields": declarations(dump),
        "authored_menu_components": sorted(inflaters, key=lambda x: x["path_id"]),
        "manifest_category_asset_paths": category_paths,
        "classification": {
            "dances": "real response group and shipped authored menu; no shipped server-entitlement ID/name catalog recovered",
            "gestures": "real response group and shipped authored menu; no shipped server-entitlement ID/name catalog recovered",
            "poses": "real response group and shipped authored menu; no shipped server-entitlement ID/name catalog recovered",
            "animations": "real response group; consumer/catalog identity unresolved in bounded evidence",
            "emotes": "real response group; no distinct shipped MenuWheelEmotes class or catalog recovered",
            "profilePictures": "real response group; no local asset/category catalog recovered",
            "bundles": "real response group; bundle SKU/content mapping is opaque server catalog data",
            "bundlesHousing": "real response group; bundle SKU/content mapping is opaque server catalog data",
        },
        "ownership_boundary": "MenuWheelInflate entryNames/entryAnims are authored built-ins. They are display-name/animation-trigger pairs, not account ownership evidence and must not be auto-granted as purchases.",
        "implementation_decision": "Do not create a grant catalog from filenames or authored menu arrays. Keep paired lists initialized and empty until an original server catalog/capture identifies exact entitlement ID and display-name pairs.",
        "unknowns": [
            "Original account ownership, commercial labels, SKU IDs, prices, bundle contents, and entitlement policy.",
            "Whether legacy non-menu consumers use animations, emotes, or profilePictures in this build.",
            "Runtime interoperability was not tested under the static-only freeze.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"menu_components": len(inflaters), "manifest_category_paths": len(category_paths), "output": str(args.output)}))


if __name__ == "__main__":
    main()
