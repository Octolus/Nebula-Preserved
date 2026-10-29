"""Read-only Unity asset/config inventory for a locally installed Nebula Realms.

Requires UnityPy. Never edits the game or extracts large media payloads.
"""
from __future__ import annotations

from _research_paths import workspace, output_root, game_path

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

import UnityPy


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(4 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def save(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=True, indent=2), encoding="utf-8")


def extract_bundle_configs(data: Path, out: Path) -> None:
    """Capture parsed custom component trees from startup/player/navigation bundles."""
    root = data / "StreamingAssets" / "StandaloneWindows"
    summaries = []
    for name in ["s/preinitiload", "s/initload", "s/login", "s/charactereditor", "s/nebulaplayer", "nav"]:
        path = root / name
        env = UnityPy.load(str(path))
        result = {"bundle": name, "sha256": sha256(path), "containers": list(env.container),
                  "object_types": dict(Counter(o.type.name for o in env.objects)), "components": []}
        for obj in env.objects:
            if obj.type.name != "MonoBehaviour":
                continue
            try:
                base = obj.read(check_read=False)
                script = base.m_Script.deref_parse_as_object()
                if script.m_AssemblyName != "Assembly-CSharp.dll" and not script.m_AssemblyName.startswith("Mirror"):
                    continue
                result["components"].append({"asset_file": obj.assets_file.name, "path_id": obj.path_id,
                                              "class": script.m_ClassName, "namespace": script.m_Namespace,
                                              "raw_sha256": hashlib.sha256(obj.get_raw_data()).hexdigest(),
                                              "fields": obj.read_typetree()})
            except Exception as exc:
                result["components"].append({"asset_file": obj.assets_file.name, "path_id": obj.path_id,
                                              "error": str(exc)})
        save(out / (name.replace("/", "-") + "-components.json"), result)
        summaries.append({k: result[k] for k in ["bundle", "sha256", "containers", "object_types"]})
    save(out / "selected-bundles.json", summaries)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--game", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--bundles-only", action="store_true")
    args = parser.parse_args()
    data = args.game / "Nebula Realms_Data"
    bundles = data / "StreamingAssets" / "StandaloneWindows"
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    if args.bundles_only:
        extract_bundle_configs(data, out)
        print("Parsed startup/player/navigation bundle components.")
        return

    manifests = []
    for path in sorted(bundles.rglob("*.manifest")):
        text = path.read_text(encoding="utf-8-sig")
        sections = re.split(r"(?m)^Assets:\s*$", text, maxsplit=1)
        assets, dependencies = [], []
        if len(sections) == 2:
            asset_part, _, dependency_part = sections[1].partition("Dependencies:")
            assets = re.findall(r"(?m)^- (.+)$", asset_part)
            dependencies = re.findall(r"(?m)^- (.+)$", dependency_part)
        bundle = path.with_suffix("")
        manifests.append({
            "bundle": bundle.relative_to(bundles).as_posix(),
            "bundle_size": bundle.stat().st_size if bundle.exists() else None,
            "manifest_sha256": sha256(path),
            "crc": re.search(r"(?m)^CRC: (\d+)$", text).group(1),
            "assets": assets, "dependencies": dependencies,
        })
    save(out / "bundle-manifests.json", manifests)

    global_env = UnityPy.load(str(data / "globalgamemanagers"))
    resource_paths = next(o for o in global_env.objects if o.type.name == "ResourceManager").read_typetree()["m_Container"]
    save(out / "resource-paths.json", resource_paths)
    build = next(o for o in global_env.objects if o.type.name == "BuildSettings").read_typetree()
    save(out / "build-settings.json", {k: build[k] for k in ["scenes", "m_Version", "isDebugBuild"]})

    # Base MonoBehaviour metadata is available even where custom type trees are stripped.
    env = UnityPy.load(str(data / "resources.assets"))
    objects = list(env.objects)
    text_assets = []
    for obj in objects:
        if obj.type.name != "TextAsset":
            continue
        parsed = obj.read()
        if parsed.m_Name not in ["AssetBundleServerURL", "BillingMode"]:
            continue
        text = parsed.m_Script
        if isinstance(text, bytes):
            text = text.decode("utf-8", "replace")
        text_assets.append({"file": "resources.assets", "path_id": obj.path_id, "name": parsed.m_Name,
                            "text": text, "payload_sha256": hashlib.sha256(text.encode()).hexdigest()})
    save(out / "text-configs.json", text_assets)

    global_assets = UnityPy.load(str(data / "globalgamemanagers.assets"))
    scripts = {}
    for obj in global_assets.objects:
        if obj.type.name == "MonoScript":
            parsed = obj.read()
            scripts[obj.path_id] = {"class": parsed.m_ClassName, "namespace": parsed.m_Namespace,
                                    "assembly": parsed.m_AssemblyName}
    save(out / "mono-scripts.json", scripts)
    gameobjects = {obj.path_id: obj.read().m_Name for obj in objects if obj.type.name == "GameObject"}
    behaviours = []
    for obj in objects:
        if obj.type.name != "MonoBehaviour":
            continue
        parsed = obj.read(check_read=False)
        script = scripts.get(parsed.m_Script.m_PathID) if parsed.m_Script.m_FileID == 1 else None
        record = {"path_id": obj.path_id, "name": parsed.m_Name,
                  "gameobject_path_id": parsed.m_GameObject.m_PathID,
                  "gameobject_name": gameobjects.get(parsed.m_GameObject.m_PathID),
                  "script_file_id": parsed.m_Script.m_FileID, "script_path_id": parsed.m_Script.m_PathID,
                  "script": script, "raw_size": obj.byte_size}
        if script and re.search(r"server|network|config|manager|database|world|space|avatar|character|assetbundle", script["class"], re.I):
            raw = obj.get_raw_data()
            record["ascii_strings_untyped"] = [{"offset": m.start(), "text": m.group().decode("ascii")}
                                                 for m in re.finditer(rb"[\x20-\x7e]{5,}", raw)]
            record["raw_sha256"] = hashlib.sha256(raw).hexdigest()
        behaviours.append(record)
    save(out / "resource-behaviours.json", behaviours)
    summary = {"unity_version": build["m_Version"], "main_scenes": build["scenes"],
               "bundle_count": len(manifests), "total_bundle_bytes": sum(x["bundle_size"] or 0 for x in manifests),
               "resource_object_types": dict(Counter(o.type.name for o in objects)),
               "resource_paths_count": len(resource_paths),
               "scene_bundles": [x for x in manifests if x["bundle"].startswith("s/")],
               "identities": [{"file": name, "sha256": sha256(data / name)}
                              for name in ["globalgamemanagers", "globalgamemanagers.assets", "resources.assets"]]}
    save(out / "summary.json", summary)
    print(json.dumps({k: summary[k] for k in ["unity_version", "bundle_count", "total_bundle_bytes", "resource_paths_count"]}))


if __name__ == "__main__":
    main()
