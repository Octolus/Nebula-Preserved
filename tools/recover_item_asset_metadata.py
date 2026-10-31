#!/usr/bin/env python3
"""Recover typed internal asset names; these are NOT historical shop names.

Requires UnityPy. Run against a legally installed game. Output is private research
data and must be outside this repository. Does not change game or server files.
tools/build_item_display_metadata.py turns this JSONL into the derived display
labels in protocol/item-display-metadata.json.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
from pathlib import Path
import sys
import tempfile


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def strings(value, field=""):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from strings(child, field + "/" + str(key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from strings(child, field + "/" + str(index))
    elif isinstance(value, str) and value:
        yield {"field": field, "value": value}


def inspect(path):
    import UnityPy
    env = UnityPy.load(str(path))
    result = {"sha256": digest(path), "bytes": path.stat().st_size,
              "types": dict(Counter(obj.type.name for obj in env.objects)),
              "names": [], "text_assets": [], "component_strings": [], "errors": []}
    wanted = {"GameObject", "Mesh", "Material", "AnimationClip", "AnimatorController", "Avatar", "TextAsset", "Texture2D", "Sprite"}
    for obj in env.objects:
        try:
            if obj.type.name in wanted:
                data = obj.read()
                name = getattr(data, "m_Name", None)
                if name:
                    result["names"].append({"type": obj.type.name, "path_id": obj.path_id, "name": name})
                if obj.type.name == "TextAsset":
                    value = data.m_Script
                    if isinstance(value, bytes):
                        value = value.decode("utf-8", "surrogateescape")
                    result["text_assets"].append({"path_id": obj.path_id, "name": name, "text": value})
            elif obj.type.name == "MonoBehaviour":
                tree = obj.read_typetree()
                values = list(strings(tree))
                if values:
                    result["component_strings"].append({"path_id": obj.path_id, "values": values})
        except Exception as error:
            result["errors"].append({"type": obj.type.name, "path_id": obj.path_id, "error": str(error)[:200]})
    return result


def inspect_item(job):
    root, row = job
    identity = [row["kind"], row["item_id"], row.get("gender"), row.get("category")]
    path = (root / row["bundle"]).resolve(strict=True)
    if not path.is_relative_to(root):
        raise ValueError("Bundle escapes original data directory")
    manifest = Path(str(path) + ".manifest")
    expected = row.get("manifest_sha256")
    actual = digest(manifest)
    if expected and actual != expected:
        raise ValueError("Manifest differs from pinned catalog: " + row["bundle"])
    return {"identity": identity, "bundle": row["bundle"], "asset_path": row["asset_path"],
            "manifest_sha256": actual, "historical_name": None,
            "name_source": "typed_internal_unity_asset_name", **inspect(path)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-data", type=Path, required=True, help="Original game's *_Data directory")
    parser.add_argument("--output", type=Path, required=True, help="Private JSONL output outside repository (append/resume)")
    parser.add_argument("--kinds", nargs="+", default=["wardrobe", "companions", "locomotions", "housing"], choices=["wardrobe", "companions", "locomotions", "housing"])
    parser.add_argument("--workers", type=int, default=1, choices=range(1, 9), help="Bounded parser processes (default 1)")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    if output.is_relative_to(repo):
        parser.error("Research output must be outside repository")
    root = (args.game_data / "StreamingAssets" / "StandaloneWindows").resolve(strict=True)
    sys.path.insert(0, str(repo / "backend"))
    from state import Catalog, Store
    from service import Service
    from catalog_inventory import CatalogInventory
    output.parent.mkdir(parents=True, exist_ok=True)
    # A fresh scratch store never reads the live service's database.
    with tempfile.TemporaryDirectory(prefix="metadata-scratch-", dir=output.parent) as scratch:
        store = Store(Path(scratch) / "catalog.sqlite3")
        try:
            rows = CatalogInventory(Service(store, Catalog(repo / "protocol"))).items
        finally:
            store.close()
    done = set()
    if output.exists():
        for line in output.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)  # Refuse a truncated output instead of hiding it.
            done.add(tuple(row["identity"]))
    pending = [(root, row) for row in rows if row["kind"] in args.kinds and
               (row["kind"], row["item_id"], row.get("gender"), row.get("category")) not in done]
    with output.open("a", encoding="utf-8") as target, ProcessPoolExecutor(max_workers=args.workers) as pool:
        for index, record in enumerate(pool.map(inspect_item, pending, chunksize=1)):
            target.write(json.dumps(record, ensure_ascii=True) + "\n")
            target.flush()
            if index % 100 == 0:
                print(len(done) + index + 1, "catalog rows inspected", flush=True)


if __name__ == "__main__":
    main()
