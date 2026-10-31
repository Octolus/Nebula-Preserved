#!/usr/bin/env python3
"""Recover shipped per-item component fields; NOT commercial metadata.

Reads the original item bundles of a legally installed game with UnityPy and
records, per canonical catalog identity, every MonoBehaviour's script class and
its scalar serialized fields (for example ``HighHeel._type``,
``HandType._type``, ``Locomotion.typeGender``/``MaxSpeed``) plus
AnimatorController names. Output is private research JSONL outside this
repository; tools/build_item_catalog_metadata.py turns it into the committed
protocol/item-catalog-metadata.json. Nothing is written to the game or to any
server database and nothing is fetched.

Unlike tools/recover_item_asset_metadata.py this scans every manifest-backed
wardrobe identity, including rows whose category evidence conflicts and rows
without a recovered gender/category, so the builder can decide them from
shipped evidence instead of silently dropping them.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
from pathlib import Path


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def scalars(tree):
    """Top-level scalar serialized fields only; Unity bookkeeping is skipped."""
    return {key: value for key, value in tree.items()
            if not key.startswith("m_") and isinstance(value, (bool, int, float, str))
            and not (isinstance(value, str) and len(value) > 256)}


def inspect(path):
    import UnityPy
    env = UnityPy.load(str(path))
    result = {"sha256": digest(path), "components": [], "animator_controllers": [], "errors": []}
    for obj in env.objects:
        try:
            if obj.type.name == "MonoBehaviour":
                tree = obj.read_typetree()
                data = obj.read()
                script = None
                try:
                    if data.m_Script:
                        script = getattr(data.m_Script.read(), "m_ClassName", None)
                except Exception:
                    script = None
                result["components"].append({"path_id": obj.path_id, "class": script,
                                             "field_names": sorted(k for k in tree if not k.startswith("m_")),
                                             "scalars": scalars(tree)})
            elif obj.type.name == "AnimatorController":
                name = getattr(obj.read(), "m_Name", None)
                if name:
                    result["animator_controllers"].append({"path_id": obj.path_id, "name": name})
        except Exception as error:
            result["errors"].append({"type": obj.type.name, "path_id": obj.path_id, "error": str(error)[:200]})
    result["components"].sort(key=lambda c: c["path_id"])
    result["animator_controllers"].sort(key=lambda c: c["path_id"])
    return result


def inspect_bundle(job):
    root, bundle, expected = job
    path = (root / bundle).resolve(strict=True)
    if not path.is_relative_to(root):
        raise ValueError("Bundle escapes original data directory")
    manifest = Path(str(path) + ".manifest")
    actual = digest(manifest)
    if expected and actual != expected:
        raise ValueError("Manifest differs from pinned catalog: " + bundle)
    return {"bundle": bundle, "manifest_sha256": actual, **inspect(path)}


def identities(protocol):
    """Every manifest-backed identity, conflicts and unknown rows included."""
    rows = []
    wardrobe = json.loads((protocol / "avatar-asset-catalog.json").read_text(encoding="utf-8"))
    for row in wardrobe["items"]:
        rows.append({"identity": ["wardrobe", row["item_id"], row.get("gender"), row.get("category")],
                     "bundle": row["bundle"], "manifest_sha256": row.get("manifest_sha256"),
                     "asset_path": row.get("asset_path")})
    resources = json.loads((protocol / "resource-entitlements.json").read_text(encoding="utf-8"))
    for row in resources["items"]:
        rows.append({"identity": [row["kind"], row["item_id"], None, row["table"]], "bundle": row["bundle"],
                     "manifest_sha256": row.get("manifest_sha256"), "asset_path": row.get("asset_path")})
    housing = json.loads((protocol / "housing-placement-contracts.json").read_text(encoding="utf-8"))
    for item_id, row in sorted(housing["items"].items()):
        rows.append({"identity": ["housing", item_id, None, row["table"]], "bundle": row["bundle"],
                     "manifest_sha256": row.get("manifest_sha256"), "asset_path": None})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-data", type=Path, required=True, help="Original game's *_Data directory")
    parser.add_argument("--output", type=Path, required=True, help="Private JSONL output outside repository")
    parser.add_argument("--workers", type=int, default=1, choices=range(1, 9), help="Bounded parser processes")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    if output.is_relative_to(repo):
        parser.error("Research output must be outside repository")
    if output.exists():
        parser.error("Output exists; choose a new file for a new scan")
    root = (args.game_data / "StreamingAssets" / "StandaloneWindows").resolve(strict=True)
    rows = identities(repo / "protocol")
    bundles = {}
    for row in rows:
        previous = bundles.setdefault(row["bundle"], row["manifest_sha256"])
        if previous != row["manifest_sha256"]:
            raise SystemExit("Conflicting manifest pins for bundle " + row["bundle"])
    output.parent.mkdir(parents=True, exist_ok=True)
    jobs = [(root, bundle, pin) for bundle, pin in sorted(bundles.items())]
    by_bundle = {}
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for index, record in enumerate(pool.map(inspect_bundle, jobs, chunksize=4)):
            by_bundle[record["bundle"]] = record
            if index % 500 == 0:
                print(index + 1, "of", len(jobs), "bundles inspected", flush=True)
    with output.open("x", encoding="utf-8") as target:
        for row in rows:
            record = by_bundle[row["bundle"]]
            target.write(json.dumps({"identity": row["identity"], "asset_path": row["asset_path"], **record},
                                    ensure_ascii=True, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
