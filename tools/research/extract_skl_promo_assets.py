"""Extract shipped SKL promo IDs and sprite-pair bounds without running Unity."""
from __future__ import annotations

from _research_paths import workspace, output_root, game_path

import argparse
import hashlib
import json
from pathlib import Path

import UnityPy


ROOT = workspace()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def main() -> None:
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--game", type=Path,
                        default=game_path(''))
    parser.add_argument("--inventory", type=Path,
                        default=ROOT / "work/evidence/world-interaction-assets.json")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "results/protocol/skl-promo-catalog.json")
    args = parser.parse_args()
    base = args.game / "Nebula Realms_Data/StreamingAssets/StandaloneWindows"
    inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
    expected = {row["bundle"]: row.get("class_counts", {}).get("SKLPromoTrigger", 0)
                for row in inventory["bundles"]
                if row.get("class_counts", {}).get("SKLPromoTrigger")}
    bundles = list(expected)
    records = []
    for bundle in bundles:
        path = base / bundle
        environment = UnityPy.load(str(path))
        for obj in environment.objects:
            if obj.type.name != "MonoBehaviour":
                continue
            try:
                header = obj.read(check_read=False)
                script = header.m_Script.deref_parse_as_object()
            except Exception:
                continue
            if script.m_ClassName != "SKLPromoTrigger":
                continue
            try:
                tree = obj.read_typetree()
                sprites = tree["aSprites"]
                if not isinstance(tree["id"], int) or not isinstance(sprites, list):
                    raise RuntimeError("SKL promo fields have unexpected serialized types")
                if len(sprites) == 0 or len(sprites) % 2:
                    raise RuntimeError("SKL promo sprite array is empty or not pair-aligned")
                if any(not isinstance(x, dict) or not x.get("m_PathID") for x in sprites):
                    raise RuntimeError("SKL promo sprite array contains an unresolved/null entry")
                game_object = header.m_GameObject.deref_parse_as_object()
                records.append({
                    "promo_id": tree["id"],
                    "bundle": bundle,
                    "bundle_sha256": digest(path),
                    "asset_file": obj.assets_file.name,
                    "component_path_id": obj.path_id,
                    "component_raw_sha256": hashlib.sha256(obj.get_raw_data()).hexdigest(),
                    "game_object_name": game_object.m_Name,
                    "sprite_count": len(sprites),
                    "valid_sprite_pair_indices": list(range(len(sprites) // 2)),
                    "sprite_references": sprites,
                })
            except Exception as exc:
                raise RuntimeError(f"Cannot parse {bundle} object {obj.path_id}: {exc}") from exc
    records.sort(key=lambda x: (x["promo_id"], x["bundle"], x["component_path_id"]))
    if not records:
        raise RuntimeError("No shipped SKLPromoTrigger components were recovered")
    recovered = {bundle: sum(x["bundle"] == bundle for x in records) for bundle in bundles}
    if recovered != expected:
        raise RuntimeError(f"SKL promo component count mismatch: expected {expected}, recovered {recovered}")
    ids = [x["promo_id"] for x in records]
    if len(ids) != len(set(ids)):
        raise RuntimeError("Duplicate shipped SKL promo IDs are ambiguous")
    result = {
        "format_version": 1,
        "scope": "Static UnityPy type-tree extraction; no Unity/game/server/listener/connection runtime",
        "native_consumer_rule": "SetSprites(i) reads aSprites[2*i] and aSprites[2*i+1]",
        "source_inventory": {"path": display_path(args.inventory), "sha256": digest(args.inventory)},
        "extractor": {"path": Path(__file__).relative_to(ROOT).as_posix(),
                      "sha256": digest(Path(__file__))},
        "promo_ids": ids,
        "records": records,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"promo_ids": ids, "records": len(records),
                      "output": str(args.output)}))


if __name__ == "__main__":
    main()
