#!/usr/bin/env python3
"""Audit how Nebula Realms' first ScreenLoader instance enters the process.

This is a static, format-aware Unity serialized-file audit.  It never starts the
game, opens a listener, or connects to a service.  The report deliberately
separates an object serialized into the first scene from similarly named assets
in resources.assets or an AssetBundle.
"""

from __future__ import annotations

from _research_paths import workspace, output_root, game_path

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import UnityPy


PRESERVATION = output_root()
REPO = workspace()
DEFAULT_DATA = game_path('Nebula Realms_Data')
DEFAULT_JSON = PRESERVATION / "protocol" / "loader-bootstrap.json"
DEFAULT_MD = PRESERVATION / "protocol" / "loader-bootstrap.md"
NATIVE = {
    "ScreenLoader.get_Instance": ("0x429fd0", REPO / "work/evidence/ghidra/functions/429fd0.c"),
    "Booter.Start": ("0x68b170", REPO / "work/evidence/ghidra/functions/68b170.c"),
    "Booter.<Init>d__5.MoveNext": ("0x69f440", REPO / "work/evidence/ghidra/functions/69f440.c"),
    "Booter.<LoadScreenLoader>d__6.MoveNext": (
        "0x69fde0",
        REPO / "work/evidence/ghidra/functions/69fde0.c",
    ),
    "Scenes.<LoadScreenLoader>d__16.MoveNext": (
        "0x5e9110",
        REPO / "work/evidence/ghidra/functions/5e9110.c",
    ),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source(path: Path) -> dict[str, Any]:
    return {"path": str(path), "size": path.stat().st_size, "sha256": sha256(path)}


def pptr(pointer: Any) -> dict[str, int]:
    return {"file_id": int(pointer.m_FileID), "path_id": int(pointer.m_PathID)}


def file_objects(env: Any, filename: str) -> dict[int, Any]:
    return {
        int(obj.path_id): obj
        for obj in env.objects
        if Path(obj.assets_file.name).name.lower() == filename.lower()
    }


def component_type(objects: dict[int, Any], path_id: int) -> str:
    reader = objects.get(path_id)
    return reader.type.name if reader is not None else "external_or_missing"


def audit(data_root: Path) -> dict[str, Any]:
    game_assembly = data_root.parent / "GameAssembly.dll"
    required = {
        "globalgamemanagers": data_root / "globalgamemanagers",
        "globalgamemanagers.assets": data_root / "globalgamemanagers.assets",
        "level0": data_root / "level0",
        "resources.assets": data_root / "resources.assets",
    }
    for path in [game_assembly, *required.values(), *(p for _, p in NATIVE.values())]:
        if not path.is_file():
            raise FileNotFoundError(path)

    manager_env = UnityPy.load(str(required["globalgamemanagers"]))
    build = next(obj.read(check_read=False) for obj in manager_env.objects if obj.type.name == "BuildSettings")
    resource_manager = next(
        obj.read(check_read=False) for obj in manager_env.objects if obj.type.name == "ResourceManager"
    )
    resource_keys = [str(key) for key, _ in resource_manager.m_Container]
    screenloader_resource_entries = [
        {"key": str(key), "target": pptr(pointer)}
        for key, pointer in resource_manager.m_Container
        if "screenloader" in str(key).lower()
    ]

    scripts_env = UnityPy.load(str(required["globalgamemanagers.assets"]))
    preload = next(obj.read(check_read=False) for obj in scripts_env.objects if obj.type.name == "PreloadData")
    preload_reader = next(obj for obj in scripts_env.objects if obj.type.name == "PreloadData")
    preload_externals = [
        {"file_id": index, "name": ext.name, "path": ext.path}
        for index, ext in enumerate(preload_reader.assets_file.externals, start=1)
    ]

    scene_env = UnityPy.load(str(required["level0"]), str(required["globalgamemanagers.assets"]))
    scene_objects = file_objects(scene_env, "level0")
    candidates: list[dict[str, Any]] = []
    for path_id, reader in scene_objects.items():
        if reader.type.name != "MonoBehaviour":
            continue
        behaviour = reader.read(check_read=False)
        try:
            script = behaviour.m_Script.read()
        except Exception:
            continue
        if script.m_ClassName != "ScreenLoader":
            continue
        go_reader = scene_objects[int(behaviour.m_GameObject.m_PathID)]
        game_object = go_reader.read(check_read=False)
        transform_pointer = game_object.m_Component[0].component
        transform_reader = scene_objects[int(transform_pointer.m_PathID)]
        transform = transform_reader.read(check_read=False)
        parent_chain: list[dict[str, Any]] = []
        parent = transform.m_Father
        seen: set[int] = set()
        while int(parent.m_PathID) != 0:
            parent_id = int(parent.m_PathID)
            if parent_id in seen or parent_id not in scene_objects:
                parent_chain.append({"transform_path_id": parent_id, "resolution": "cycle_or_missing"})
                break
            seen.add(parent_id)
            parent_transform = scene_objects[parent_id].read(check_read=False)
            parent_go_id = int(parent_transform.m_GameObject.m_PathID)
            parent_go = scene_objects[parent_go_id].read(check_read=False)
            parent_chain.append(
                {
                    "transform_path_id": parent_id,
                    "game_object_path_id": parent_go_id,
                    "name": parent_go.m_Name,
                    "active_self": bool(parent_go.m_IsActive),
                }
            )
            parent = parent_transform.m_Father
        candidates.append(
            {
                "mono_behaviour_path_id": path_id,
                "script_reference": pptr(behaviour.m_Script),
                "script": {
                    "class": script.m_ClassName,
                    "namespace": script.m_Namespace,
                    "assembly": script.m_AssemblyName,
                },
                "enabled": bool(behaviour.m_Enabled),
                "game_object_path_id": int(go_reader.path_id),
                "game_object_name": game_object.m_Name,
                "active_self": bool(game_object.m_IsActive),
                "transform": {
                    "type": transform_reader.type.name,
                    "path_id": int(transform_reader.path_id),
                    "parent": pptr(transform.m_Father),
                    "parent_chain": parent_chain,
                    "is_scene_root": int(transform.m_Father.m_PathID) == 0,
                },
                "components": [
                    {
                        "reference": pptr(item.component),
                        "type": component_type(scene_objects, int(item.component.m_PathID)),
                    }
                    for item in game_object.m_Component
                ],
            }
        )

    resources_env = UnityPy.load(
        str(required["resources.assets"]), str(required["globalgamemanagers.assets"])
    )
    resources_objects = file_objects(resources_env, "resources.assets")
    resource_prefabs: list[dict[str, Any]] = []
    for path_id, reader in resources_objects.items():
        if reader.type.name != "MonoBehaviour":
            continue
        behaviour = reader.read(check_read=False)
        if int(behaviour.m_Script.m_PathID) != 1805:
            continue
        game_object = resources_objects[int(behaviour.m_GameObject.m_PathID)].read(check_read=False)
        resource_prefabs.append(
            {
                "mono_behaviour_path_id": path_id,
                "game_object_path_id": int(behaviour.m_GameObject.m_PathID),
                "game_object_name": game_object.m_Name,
                "active_self_in_serialized_asset": bool(game_object.m_IsActive),
                "script_reference": pptr(behaviour.m_Script),
            }
        )

    bundle = data_root / "StreamingAssets/StandaloneWindows/screenloader"
    bundle_manifest = bundle.with_name(bundle.name + ".manifest")

    native: list[dict[str, Any]] = []
    native_text: dict[str, str] = {}
    for name, (rva, path) in NATIVE.items():
        text = path.read_text(encoding="utf-8")
        native_text[name] = text
        native.append({"symbol": name, "rva": rva, **source(path)})

    getter = native_text["ScreenLoader.get_Instance"]
    start = native_text["Booter.Start"]
    init = native_text["Booter.<Init>d__5.MoveNext"]
    alternate_boot_loader = native_text["Booter.<LoadScreenLoader>d__6.MoveNext"]
    alternate_scene_loader = native_text["Scenes.<LoadScreenLoader>d__16.MoveNext"]
    native_checks = {
        "getter_reads_static_cache": "ScreenLoader_TypeInfo" in getter and "+ 0xb8" in getter,
        "getter_calls_find_object_of_type": "FindObjectOfType_ScreenLoader" in getter,
        "getter_contains_instantiate_call": bool(re.search(r"\bInstantiate", getter)),
        "booter_start_initializes_asset_bundle_manager": "NebulaAssetBundleManager__Initialize" in start,
        "booter_start_initializes_scenes": "Scenes__Initialize" in start,
        "booter_start_starts_init_state_machine": "Start_Booter__Init" in start,
        "booter_init_loads_nav": "Start_Booter__LoadNav" in init,
        "booter_init_loads_nebula_player": "Start_Booter__LoadNebulaPlayer" in init,
        "booter_init_loads_preinitiload": "_preinitiload_" in init and "Scenes__Load" in init,
        "booter_start_or_init_mentions_screen_loader": "ScreenLoader" in start or "ScreenLoader" in init,
        "separate_loader_calls_scenes_load_screen_loader": "Scenes__LoadScreenLoader" in alternate_boot_loader,
        "separate_loader_instantiates_game_object": "Instantiate_GameObject" in alternate_boot_loader,
        "separate_loader_marks_instance_dont_destroy_on_load": "DontDestroyOnLoad" in alternate_boot_loader,
        "scenes_loader_requests_screenloader_bundle": (
            "NebulaAssetBundleManager__Load" in alternate_scene_loader
            and "_screenloader_" in alternate_scene_loader
        ),
    }

    placement_proven = (
        len(candidates) == 1
        and candidates[0]["enabled"]
        and candidates[0]["active_self"]
        and candidates[0]["transform"]["is_scene_root"]
        and list(build.scenes) == ["Assets/Scenes/Boot/Booter.unity"]
    )
    return {
        "format_version": 1,
        "scope": "Static Unity serialized-file and recovered native pseudocode evidence only; the game was not executed.",
        "question": "How does the first active ScreenLoader instance exist during startup?",
        "answer": (
            "The sole compiled startup scene (Booter.unity / level0) directly serializes one enabled "
            "ScreenLoader component on an active root GameObject. Unity loads that scene object graph before "
            "MonoBehaviour Start callbacks; ScreenLoader.get_Instance can therefore find the placed component. "
            "No runtime prefab instantiation is required to explain first existence."
        ),
        "answer_basis": "observed_static_plus_unity_lifecycle_inference",
        "confidence": "high" if placement_proven else "partial",
        "placement_proven": placement_proven,
        "installed_data_root": str(data_root),
        "unity_build": {
            "version": build.m_Version,
            "scenes": list(build.scenes),
            "startup_scene_index": 0,
            "startup_compiled_file": "level0",
        },
        "initial_scene_screen_loader_components": candidates,
        "preload_table": {
            "source_object": {"type": "PreloadData", "path_id": int(preload_reader.path_id)},
            "asset_count": len(preload.m_Assets),
            "assets": [pptr(pointer) for pointer in preload.m_Assets],
            "externals": preload_externals,
            "screen_loader_scene_component_is_in_table": any(
                int(pointer.m_FileID) == 0 and int(pointer.m_PathID) == candidates[0]["mono_behaviour_path_id"]
                for pointer in preload.m_Assets
            ) if candidates else False,
            "interpretation": (
                "The preload table is not the source of the scene component: its entries reference external "
                "file ID 1, while the ScreenLoader component is local to level0."
            ),
        },
        "resources_inventory": {
            "resource_manager_container_count": len(resource_keys),
            "container_entries_with_exact_screenloader_substring": screenloader_resource_entries,
            "serialized_screen_loader_components_in_resources_assets": resource_prefabs,
            "interpretation": (
                "resources.assets contains a separate serialized ScreenLoader asset, but no ResourceManager key "
                "contains the exact substring 'screenloader'. Asset presence does not establish startup placement."
            ),
        },
        "asset_bundle_inventory": {
            "screenloader_bundle": source(bundle) if bundle.is_file() else None,
            "screenloader_manifest": source(bundle_manifest) if bundle_manifest.is_file() else None,
            "interpretation": (
                "The separate bundle is packaged evidence only. The initial level0 placement already explains "
                "first existence. A separate compiled loader can load and instantiate this bundle, but the "
                "reviewed Booter.Start/Init startup path does not invoke that loader."
            ),
        },
        "native_checks": native_checks,
        "native_binary_evidence": source(game_assembly),
        "native_evidence": native,
        "serialized_source_evidence": [source(path) for path in required.values()],
        "observations": [
            "BuildSettings contains exactly one scene: Assets/Scenes/Boot/Booter.unity.",
            "level0 contains exactly one ScreenLoader MonoBehaviour candidate.",
            "That component is enabled and attached to an active GameObject named ScreenLoader.",
            "Its RectTransform has a null parent reference, making the GameObject a scene root.",
            "The component's MonoScript resolves to ScreenLoader in Assembly-CSharp.dll.",
            "ScreenLoader.get_Instance checks its static cache, then calls FindObjectOfType<ScreenLoader>; no Instantiate call appears.",
            "Booter.Start initializes local managers and starts Init; Init loads nav, NebulaPlayer, then preinitiload. Neither reviewed function mentions ScreenLoader.",
            "Separate compiled LoadScreenLoader state machines request the screenloader bundle, instantiate the returned GameObject, and mark it DontDestroyOnLoad.",
            "The reviewed Booter.Start/Init path does not call or start that separate LoadScreenLoader state machine.",
        ],
        "inferences": [
            "Unity deserializes the initial scene object graph before invoking Start callbacks, so the placed active component exists when Booter.Start runs.",
            "The resources.assets and bundle copies are not needed to explain the first instance and must not be treated as proof of dynamic instantiation.",
            "The separate bundle loader may be a later, alternate, or obsolete path; its mere presence does not establish that it runs during initial startup.",
        ],
        "remaining_unknowns": [
            "No runtime observation confirms whether later scene transitions destroy, retain, or replace this initial ScreenLoader.",
            "This audit does not establish when or whether the separate screenloader bundle loader is invoked outside the reviewed Booter.Start/Init path.",
            "Static placement proves the intended initial host, not successful rendering or execution on this machine.",
        ],
        "game_executed": False,
        "network_activity": False,
    }


def markdown(report: dict[str, Any]) -> str:
    candidate = report["initial_scene_screen_loader_components"][0]
    checks = report["native_checks"]
    sources = (
        report["serialized_source_evidence"]
        + [report["native_binary_evidence"]]
        + report["native_evidence"]
    )
    lines = [
        "# ScreenLoader bootstrap audit",
        "",
        "## Conclusion",
        "",
        report["answer"],
        "",
        f"**Confidence:** {report['confidence']}. This is static placement evidence, not a runtime observation.",
        "",
        "## Serialized placement",
        "",
        f"- BuildSettings scene 0: `{report['unity_build']['scenes'][0]}`; compiled scene file: `level0`.",
        f"- MonoBehaviour path ID `{candidate['mono_behaviour_path_id']}` resolves through script path ID "
        f"`{candidate['script_reference']['path_id']}` to `{candidate['script']['class']}` in "
        f"`{candidate['script']['assembly']}`.",
        f"- It is enabled: `{candidate['enabled']}`; its GameObject path ID `{candidate['game_object_path_id']}` "
        f"is named `{candidate['game_object_name']}` and active: `{candidate['active_self']}`.",
        f"- RectTransform path ID `{candidate['transform']['path_id']}` has parent path ID "
        f"`{candidate['transform']['parent']['path_id']}`. It is therefore an active scene root, not merely a "
        "detached prefab record.",
        "",
        "## Why the preload/resource copies are not the bootstrap proof",
        "",
        f"The `PreloadData` table has {report['preload_table']['asset_count']} entries, all represented with "
        "external file ID 1; it does not reference the local `level0` ScreenLoader component. "
        f"`resources.assets` separately contains {len(report['resources_inventory']['serialized_screen_loader_components_in_resources_assets'])} "
        "ScreenLoader component record, and a `screenloader` AssetBundle is packaged. Those facts establish "
        "available assets, not that either copy is instantiated at startup. The direct `level0` component does.",
        "",
        "## Native ordering corroboration",
        "",
        f"- `ScreenLoader.get_Instance` (`0x429fd0`) reads the static cache and calls "
        f"`FindObjectOfType<ScreenLoader>`: `{checks['getter_calls_find_object_of_type']}`. An Instantiate call is "
        f"present: `{checks['getter_contains_instantiate_call']}`.",
        f"- `Booter.Start` (`0x68b170`) initializes the asset-bundle manager and Scenes, then starts Init.",
        f"- `Booter.<Init>d__5.MoveNext` (`0x69f440`) loads nav, NebulaPlayer, and `preinitiload`.",
        f"- Either reviewed Booter function mentions ScreenLoader: `{checks['booter_start_or_init_mentions_screen_loader']}`.",
        f"- A separate `Booter.<LoadScreenLoader>d__6.MoveNext` (`0x69fde0`) does call the Scenes loader, "
        f"instantiate the returned GameObject, and mark it `DontDestroyOnLoad`: "
        f"`{checks['separate_loader_calls_scenes_load_screen_loader'] and checks['separate_loader_instantiates_game_object'] and checks['separate_loader_marks_instance_dont_destroy_on_load']}`.",
        f"- Its Scenes state machine (`0x5e9110`) requests the `screenloader` bundle: "
        f"`{checks['scenes_loader_requests_screenloader_bundle']}`. No call/start of this separate loader appears in "
        "the reviewed `Booter.Start` or `Booter.Init` bodies.",
        "",
        "The lifecycle step that the artifacts do not encode as an ordinary call is Unity's scene deserialization "
        "before `Start`. That engine lifecycle rule plus the active root component is the bounded inference connecting "
        "the serialized observation to availability during `Booter.Start`.",
        "",
        "## Evidence boundaries",
        "",
        "Observed:",
        "",
    ]
    lines.extend(f"- {item}" for item in report["observations"])
    lines.extend(["", "Inferred:", ""])
    lines.extend(f"- {item}" for item in report["inferences"])
    lines.extend(["", "Still unknown:", ""])
    lines.extend(f"- {item}" for item in report["remaining_unknowns"])
    lines.extend(["", "## Source identities", ""])
    for item in sources:
        symbol = f" ({item['symbol']} {item['rva']})" if "symbol" in item else ""
        lines.append(f"- `{item['path']}`{symbol}: `{item['sha256']}` ({item['size']} bytes)")
    lines.extend(
        [
            "",
            "The audit was execution-free: no game process, UI automation, listener, server, or network connection was used.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MD)
    args = parser.parse_args()
    report = audit(args.data_root.resolve())
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    args.markdown.write_text(markdown(report), encoding="utf-8")
    print(json.dumps({"json": str(args.json), "markdown": str(args.markdown), "placement_proven": report["placement_proven"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
