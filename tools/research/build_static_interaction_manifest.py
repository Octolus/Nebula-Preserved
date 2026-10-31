"""Read shipped scene/logic bundles and build source-bound static registry keys.

No target execution or network access. Numeric runtime IDs are intentionally
absent. Initial registry keys use an exact, globally unique top-root name and a
relative sibling path; the native bridge must independently submit the complete
same set before the server can trust any numeric mapping.
"""
from __future__ import annotations

from _research_paths import workspace, output_root, game_path

import argparse
from collections import Counter
import gc
import hashlib
import json
from pathlib import Path
from typing import Any

import UnityPy

from build_housing_interaction_manifest import class_bases, derives, _reference

ROOT = workspace()
BASE = game_path('Nebula Realms_Data/StreamingAssets/StandaloneWindows')
PROTOCOL = ROOT / "results/protocol"
MANIFESTS = ROOT / "work/evidence/assets/bundle-manifests.json"
WORLD = ROOT / "work/evidence/world-interaction-assets.json"
DUMP = ROOT / "work/decompiled/dump.cs"
OUTPUT = PROTOCOL / "static-interaction-manifest.json"
NATIVE = ROOT / "work/evidence/ghidra/functions"

ORDINARY_GENERIC = frozenset({
    "LightTrigger", "JG_HousingRocket", "CarPlatform",
    "DayNightBasicCycle", "JacuzziGenericInteractable", "Shower",
    "JG_ChaletFireplaceInteractable", "JG_CampSilverLake_WeatherInteractable",
    "JG_CampSilverLake_Door", "JG_CampSilverLake_TimeInteractable",
    "JG_WeatherInteractable", "JG_DoorInteractable", "JG_Hollyridge_Decoration_Interactable",
    "JG_Hollyridge_Time_Interactable", "JG_Hollyridge_WeatherInteractable",
    "JG_ChaletSnowInteractable", "JG_ChaletTimeInteractable", "JG_SereneTimeInteractable",
    "JG_SorcerersEyrie_TimeInteractable", "JG_WoodlandTimeInteractable",
    "JG_WH_Fireplace", "JG_WH_Time",
})
DEFERRED_GENERIC = frozenset({
    "JG_CampSilverLake_Killer_Launcher", "JG_Ghost_Minigame", "JG_Ghost_Candle",
    "JG_SorcerersEyrie_Ingredient", "JG_SorcerersEyrie_PotionControl",
    "JG_SorcerersEyrie_RecipeControl",
})
SEPARATE_GENERIC = frozenset({"DayNightTrigger"})
# Concrete overrides must have their own exported body before admission.
OCCUPABLE_NATIVE = {
    "NebulaSeat": ("6159f0", "612700"),
    "AnimationTrigger": ("612670", "35a740", "612700"),
    "Bench": ("612670", "35a740", "612700"),
    "BenchCinema": ("44b870", "44b8a0"),
    "Jacuzzi": ("4530d0", "453110"),
    "Toilet": ("458c40", "458ce0"),
    "SeatSelection": ("457ce0", "457ea0"),
}
# Shipped public destinations: PreInitLOAD.NavigatorPublicSpaces plus the Nexus
# Cinema/SKL CustomSpaceTriggers. SteamPunk ships only its logic prefab (no
# s/steampunk scene bundle), so the client cannot load it.
PUBLIC_SCENES = ("Nexus", "LeafPark", "Beach", "Cinema", "Bowling", "Dome", "StoneLakeCastle", "Cube",
                 "GhostTown", "TheNebulianOpenHouse", "ZeroDistrict", "NebuHouseOpenHouse",
                 "WestValleyApartmentOpenHouse", "MedievalVillage", "SKL")
POLICY_NATIVE = ("451060", "451100", "5df620", "5decf0", "5deab0", "46fa80", "5e5b20", "44f580", "612380")


def sha256(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def normalized_anchor(name: str) -> str:
    """Match the bridge: strip only Unity's exact trailing clone marker."""
    return name[:-7] if name.endswith("(Clone)") else name


def classification(name: str, kind: str, native_available: set[str]) -> str | None:
    if kind == "occupable":
        required = OCCUPABLE_NATIVE.get(name)
        return "ordinary" if required and set(required) <= native_available else None
    if name in ORDINARY_GENERIC:
        return "ordinary"
    if name in DEFERRED_GENERIC:
        return "deferred_minigame"
    if name in SEPARATE_GENERIC:
        return "separate_protocol"
    return None


def null_script_placeholder(obj: Any) -> dict[str, Any] | None:
    """Do not turn arbitrary unresolved external script references into empties."""
    fields = obj.read_typetree()
    typ = obj.serialized_type
    script_hash = bytes(getattr(typ, "script_id", b"")).hex()
    type_hash = bytes(getattr(typ, "old_type_hash", b"")).hex()
    if (
        fields.get("m_Script") == {"m_FileID": 0, "m_PathID": 0}
        and set(fields) == {"m_GameObject", "m_Enabled", "m_Script", "m_Name"}
        and getattr(typ, "script_type_index", None) == -1
        and script_hash and type_hash and set(script_hash + type_hash) == {"0"}
        and len(obj.get_raw_data()) == 32
    ):
        return {"classification": "null_script_base_only", "serialized_bytes": 32,
                "script_type_index": -1, "script_id": script_hash, "old_type_hash": type_hash}
    return None


def scan_graph(objects: dict[tuple[str, int], Any], root: Any, source: str,
               bases: dict[str, str], native_available: set[str]) -> dict[str, Any]:
    result: dict[str, Any] = {"entries": [], "entry_evidence": [], "inactive": [],
                              "unresolved": [], "missing_script_placeholders": []}
    visited: set[tuple[str, int]] = set()
    root_fields = root.read_typetree()
    anchor = normalized_anchor(str(root_fields.get("m_Name", "")))
    result["root"] = anchor
    result["root_active"] = bool(root_fields.get("m_IsActive"))
    result["root_game_object_path_id"] = str(root.path_id)
    result["root_raw_sha256"] = hashlib.sha256(root.get_raw_data()).hexdigest()

    def resolve(ref: Any, owner: Any) -> Any:
        file_id, path_id = _reference(ref)
        if file_id != 0 or not path_id:
            raise ValueError("nonlocal_or_null_object_reference")
        target = objects.get((owner.assets_file.name, path_id))
        if target is None:
            raise ValueError("missing_local_object_reference")
        return target

    def error(phase: str, obj: Any, path: list[int], slot: int | None, detail: Any) -> None:
        result["unresolved"].append({"phase": phase, "source": source, "root": anchor,
            "path": path, "slot": slot, "asset_file": obj.assets_file.name,
            "object_path_id": str(obj.path_id), "raw_sha256": hashlib.sha256(obj.get_raw_data()).hexdigest(),
            "error": str(detail)})

    def walk(go: Any, path: list[int], parent_active: bool, ancestry: list[dict[str, Any]]) -> None:
        identity = (go.assets_file.name, go.path_id)
        if identity in visited:
            error("hierarchy", go, path, None, "duplicate_or_cyclic_game_object")
            return
        visited.add(identity)
        fields = go.read_typetree()
        active = parent_active and bool(fields.get("m_IsActive"))
        current_ancestor = {"game_object_name": fields.get("m_Name"),
            "game_object_path_id": str(go.path_id),
            "game_object_raw_sha256": hashlib.sha256(go.get_raw_data()).hexdigest(),
            "sibling_index_relative_to_parent": path[-1] if path else None}
        lineage = ancestry + [current_ancestor]
        transform = None
        for slot, component in enumerate(fields.get("m_Component", [])):
            try:
                ref = component.get("component", component)
                target = resolve(ref, go)
                if target.type.name in {"Transform", "RectTransform"}:
                    if transform is not None:
                        raise ValueError("multiple_transforms")
                    transform = target
                    current_ancestor["transform_path_id"] = str(target.path_id)
                    current_ancestor["transform_raw_sha256"] = hashlib.sha256(target.get_raw_data()).hexdigest()
                if target.type.name != "MonoBehaviour":
                    continue
                try:
                    base = target.read(check_read=False)
                    name = base.m_Script.deref_parse_as_object().m_ClassName
                except Exception as exc:
                    placeholder = null_script_placeholder(target)
                    if placeholder is not None:
                        result["missing_script_placeholders"].append({**placeholder,
                            "source": source, "root": anchor, "path": path, "slot": slot,
                            "active_in_hierarchy": active, "object_path_id": str(target.path_id),
                            "raw_sha256": hashlib.sha256(target.get_raw_data()).hexdigest()})
                    elif active:
                        error("script_resolution", target, path, slot, type(exc).__name__)
                    continue
                kind = ("generic" if derives(name, "GenericInteractable", bases) else
                        "occupable" if derives(name, "NebulaOccupable", bases) else None)
                if kind is None:
                    continue
                if not active:
                    result["inactive"].append({"source": source, "root": anchor,
                        "path": path, "class": name, "slot": slot, "kind": kind})
                    continue
                data = target.read_typetree()
                policy = classification(name, kind, native_available)
                if policy is None:
                    error("policy", target, path, slot, "unreviewed_class:" + name)
                    continue
                if kind == "generic" and not isinstance(data.get("data"), list):
                    error("extension_schema", target, path, slot, "data_array_missing")
                    continue
                arity = len(data["data"]) if kind == "generic" and policy != "separate_protocol" else 0
                entry = {"kind": kind, "source": source, "root": anchor, "path": path,
                         "class": name, "slot": slot, "classification": policy,
                         "extension_arity": arity}
                result["entries"].append(entry)
                result["entry_evidence"].append({**entry, "asset_file": target.assets_file.name,
                    "object_path_id": str(target.path_id),
                    "raw_sha256": hashlib.sha256(target.get_raw_data()).hexdigest(),
                    "game_object_name": fields.get("m_Name"),
                    "component_enabled": bool(data.get("m_Enabled", 1)),
                    "path_ancestry": lineage,
                    "serialized_extension_data": data.get("data") if kind == "generic" else None})
            except Exception as exc:
                if active:
                    error("component_parse", go, path, slot, f"{type(exc).__name__}:{exc}")
        if transform is None:
            error("hierarchy", go, path, None, "missing_transform")
            return
        for index, child_ref in enumerate(transform.read_typetree().get("m_Children", [])):
            try:
                child_transform = resolve(child_ref, transform)
                child_go = resolve(child_transform.read_typetree()["m_GameObject"], child_transform)
                walk(child_go, path + [index], active, lineage)
            except Exception as exc:
                if active:
                    error("child_parse", transform, path + [index], None, f"{type(exc).__name__}:{exc}")

    walk(root, [], True, [])
    result["visited_game_object_count"] = len(visited)
    return result


def inspect_bundle(row: dict[str, Any], source: str, base: Path,
                   bases: dict[str, str], native_available: set[str]) -> dict[str, Any]:
    path = base / row["bundle"]
    report: dict[str, Any] = {"source": source, "bundle": row["bundle"],
        "manifest_sha256": row["manifest_sha256"], "assets": row["assets"], "roots": [], "unresolved": []}
    if not path.is_file() or not path.with_suffix(".manifest").is_file():
        report["unresolved"].append({"phase": "source", "error": "bundle_or_manifest_missing"})
        return report
    report["bundle_sha256"] = sha256(path)
    if sha256(path.with_suffix(".manifest")) != row["manifest_sha256"]:
        report["unresolved"].append({"phase": "source", "error": "manifest_hash_mismatch"})
        return report
    try:
        env = UnityPy.load(str(path))
        objects = {(obj.assets_file.name, obj.path_id): obj for obj in env.objects}
        roots = []
        if source == "geometry":
            # Scene containers point to pathID0. Geometry .sharedAssets contains
            # referenced prototypes, not instantiated scene roots.
            files = {obj.assets_file.name for obj in env.objects if obj.type.name == "GameObject"
                     and obj.assets_file.name.startswith("BuildPlayer-")
                     and not obj.assets_file.name.endswith(".sharedAssets")}
            if len(files) != 1:
                raise ValueError("scene_serialized_file_ambiguous")
            scene_file = next(iter(files))
            report["serialized_scene_file"] = scene_file
            for obj in env.objects:
                if obj.assets_file.name != scene_file or obj.type.name not in {"Transform", "RectTransform"}:
                    continue
                data = obj.read_typetree()
                if _reference(data.get("m_Father")) == (0, 0):
                    file_id, path_id = _reference(data["m_GameObject"])
                    if file_id != 0 or not path_id:
                        raise ValueError("invalid_scene_root_reference")
                    roots.append(objects[(scene_file, path_id)])
        else:
            expected = [value for value in row["assets"] if value.lower().endswith(".prefab")]
            containers = {key.lower(): value for key, value in env.container.items()}
            if len(expected) != 1 or expected[0].lower() not in containers:
                raise ValueError("prefab_container_ambiguous")
            root = containers[expected[0].lower()].deref()
            if root.type.name != "GameObject":
                raise ValueError("prefab_container_not_game_object")
            roots.append(root)
        if not roots:
            raise ValueError("no_source_roots")
        for root in roots:
            report["roots"].append(scan_graph(objects, root, source, bases, native_available))
    except Exception as exc:
        report["unresolved"].append({"phase": "bundle_parse", "error": f"{type(exc).__name__}:{exc}"})
    finally:
        if "env" in locals():
            del env
        gc.collect()
    return report


def finalize_scene(scene: str, source_scene: str, sources: list[dict[str, Any]],
                   core: bool) -> dict[str, Any]:
    roots = [root for bundle in sources for root in bundle.get("roots", [])]
    counts = Counter(root["root"] for root in roots if root["root_active"])
    entries = [entry for root in roots for entry in root["entries"]]
    unresolved = [failure for bundle in sources for failure in bundle.get("unresolved", [])]
    unresolved += [failure for root in roots for failure in root["unresolved"]]
    # Runtime origin cannot prove source. Root name must be globally unique;
    # source is provenance only and may not disambiguate colliding names.
    for anchor, count in counts.items():
        if count != 1:
            unresolved.append({"phase": "anchor", "root": anchor, "error": "duplicate_active_top_root", "count": count})
    keys = [(e["kind"], e["root"], tuple(e["path"]), e["slot"], e["class"]) for e in entries]
    if len(keys) != len(set(keys)):
        unresolved.append({"phase": "semantic_key", "error": "duplicate_entry"})
    entries.sort(key=lambda e: (e["root"], e["kind"], e["path"], e["slot"], e["class"]))
    status = "unresolved" if unresolved else "complete_verified" if entries else "verified_empty"
    logic = next((row for row in sources if row["source"] == "logic"), {})
    return {"scene": scene, "source_inventory_scene": source_scene,
        "bundle_sha256": logic.get("bundle_sha256"), "status": status,
        "nonmini_core_v1": core, "entries": entries, "unresolved": unresolved,
        "active_anchor_counts": dict(sorted(counts.items())), "sources": sources,
        "mapping_gate": "Require exact complete initial native registry set; anchor names must each match exactly one active top root. Source is provenance only. Numeric IDs are supplied by the bound native client, never inferred here."}


def validate_manifest(document: dict[str, Any]) -> None:
    if (document.get("format_version") != 1 or document.get("target_execution") is not False
            or document.get("path_convention") != "anchor_relative_excludes_root_v1"):
        raise ValueError("invalid_manifest_header")
    scenes = document.get("scenes", [])
    if len(scenes) != 46 or len({row["scene"] for row in scenes}) != 46:
        raise ValueError("incomplete_canonical_scene_scope")
    if sum(row["nonmini_core_v1"] for row in scenes) != 43:
        raise ValueError("incomplete_core_scene_scope")
    for row in scenes:
        if row["status"] not in {"verified_empty", "complete_verified", "unresolved"}:
            raise ValueError("invalid_status")
        if row["status"] == "verified_empty" and (row["entries"] or row["unresolved"]):
            raise ValueError("false_verified_empty")
        if row["status"] == "complete_verified" and (not row["entries"] or row["unresolved"]):
            raise ValueError("false_verified_complete")
        if row["status"] == "unresolved" and not row["unresolved"]:
            raise ValueError("unresolved_without_evidence")
        for entry in row["entries"]:
            if entry["kind"] not in {"generic", "occupable"} or entry["classification"] not in {"ordinary", "deferred_minigame", "separate_protocol"}:
                raise ValueError("invalid_entry_policy")
            if entry["source"] not in {"geometry", "logic", "event"} or not entry["root"]:
                raise ValueError("invalid_anchor")
            if any(type(index) is not int or index < 0 for index in entry["path"]) or type(entry["slot"]) is not int or entry["slot"] < 0:
                raise ValueError("invalid_relative_key")
            if type(entry["extension_arity"]) is not int or entry["extension_arity"] < 0:
                raise ValueError("invalid_arity")
            if entry["kind"] == "occupable" and entry["extension_arity"] != 0:
                raise ValueError("occupable_extensions")
            if row["status"] != "unresolved" and row["active_anchor_counts"].get(entry["root"]) != 1:
                raise ValueError("unproven_unique_anchor")


def build(base: Path) -> dict[str, Any]:
    audit = json.loads((PROTOCOL / "http-nonminigame-gap-audit.json").read_text(encoding="utf-8-sig"))
    manifests = {row["bundle"]: row for row in json.loads(MANIFESTS.read_text(encoding="utf-8-sig"))}
    world = json.loads(WORLD.read_text(encoding="utf-8-sig"))
    if world["source_dump_sha256"] != sha256(DUMP):
        raise ValueError("source_dump_hash_mismatch")
    bases = class_bases(DUMP.read_text(encoding="utf-8"))
    available = {path.stem for path in NATIVE.glob("*.c")}
    logical_names = audit["personal_space_navigator_names"] + list(PUBLIC_SCENES)
    scenes = []
    for name in sorted(logical_names):
        sources = []
        for source, suffix in (("geometry", ""), ("logic", "logicprefab")):
            key = "s/" + name.lower() + suffix
            if key not in manifests:
                sources.append({"source": source, "bundle": key, "roots": [],
                    "unresolved": [{"phase": "source", "error": "source_manifest_missing"}]})
                continue
            sources.append(inspect_bundle(manifests[key], source, base, bases, available))
            if source == "logic":
                original = next(row for row in world["bundles"] if row["bundle"] == key)
                if sources[-1].get("bundle_sha256") != original["sha256"]:
                    sources[-1]["unresolved"].append({"phase": "source", "error": "prior_inventory_bundle_hash_mismatch"})
        event_key = "s/" + name.lower() + "spaceevent"
        if event_key in manifests or (base / event_key).exists():
            if event_key not in manifests:
                sources.append({"source": "event", "bundle": event_key, "roots": [],
                    "unresolved": [{"phase": "source", "error": "event_bundle_without_manifest_inventory"}]})
            else:
                sources.append(inspect_bundle(manifests[event_key], "event", base, bases, available))
        scene = "SorcerersEyrie1" if name == "SorcerersEyrie" else name
        row = finalize_scene(scene, name, sources, name not in {"CampSilverLake", "CutteridgeEstate", "SorcerersEyrie"})
        scenes.append(row)
        print(f"{scene}: {row['status']} entries={len(row['entries'])} unresolved={len(row['unresolved'])}", flush=True)
    native_rvas = set(POLICY_NATIVE)
    native_rvas.update(rva for values in OCCUPABLE_NATIVE.values() for rva in values)
    document = {"format_version": 1, "target_execution": False,
        "path_convention": "anchor_relative_excludes_root_v1",
        "scope": "46 canonical runtime scenes: fifteen admitted public scenes,28 core personal scenes and three deferred-minigame mixed personal scenes. Read-only shipped artifacts; no game,UI,server,listener,attach,connection or live state.",
        "source_evidence": {"dump_sha256": sha256(DUMP), "manifest_inventory_sha256": sha256(MANIFESTS),
            "world_inventory_sha256": sha256(WORLD), "tool_sha256": sha256(Path(__file__)),
            "generic_native_review_sha256": sha256(PROTOCOL / "tcp-world-interactions.json"),
            "unitypy_version": getattr(UnityPy, "__version__", "unknown"),
            "native": [{"rva": "0x" + rva, "sha256": sha256(NATIVE / (rva + ".c")) if rva in available else None} for rva in sorted(native_rvas)]},
        "key_contract": {"wire_anchor": "root", "source": "provenance only; never disambiguates duplicate roots",
            "root": "exact topmost Transform GameObject name, stripping only an exact trailing (Clone)",
            "root_uniqueness": "one active top root with that normalized name across all geometry,logic and event sources; missing/duplicate runtime anchor rejects whole map",
            "path": "Transform.m_Children sibling indices, excluding root; inactive siblings still occupy indices",
            "slot": "full GameObject.m_Component index, including Transform/native components",
            "enabled": "disabled MonoBehaviours on active GameObjects remain in FindObjectsOfType; inactive hierarchies excluded",
            "numeric_runtime_ids": "not inferred; exact-set native registration supplies IDs after trusted semantic comparison",
            "null_scripts": "Only null m_Script,base-only32bytes,script_type_index=-1 and zero script/type hashes are missing-script placeholders. Their exclusion from typed enumeration is source-based, with exact-set runtime check required.",
            "separate_protocol": "entry consumes registry enumeration but override sends another opcode; 94 relay denied",
            "original_server_policy": "unavailable; ordinary relay and exact source-bound admission are explicit preservation policy"},
        "reviewed_subtypes": {"ordinary_generic": sorted(ORDINARY_GENERIC),
            "deferred_generic": sorted(DEFERRED_GENERIC), "separate_protocol_generic": sorted(SEPARATE_GENERIC),
            "ordinary_occupable_native_rvas": OCCUPABLE_NATIVE,
            "occupable_override_review": "BenchCinema,Jacuzzi,Toilet call NebulaSeat.Interact and NebulaOccupable.LeaveInteract plus local UI/events; SeatSelection opens local animation menu and Leave calls NebulaOccupable. AnimationTrigger/Bench inherit NebulaOccupable.Interact; RemoteInteract is shared empty body35a740. No additional occupable wire extensions.",
            "generic_override_review": "All ordinary callbacks reviewed in tcp-world-interactions.json. Extension arity comes from exact serialized GenericInteractable.data array. DayNightTrigger.Interact44f580 emits30 and remains present but denied94."},
        "scenes": scenes,
        "summary": {"scenes": len(scenes), "core_scenes": sum(row["nonmini_core_v1"] for row in scenes),
            "statuses": dict(Counter(row["status"] for row in scenes)),
            "classes": dict(sorted(Counter(entry["class"] for row in scenes for entry in row["entries"]).items()))}}
    validate_manifest(document)
    return document


def main() -> None:
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--asset-root", type=Path, default=BASE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    result = build(args.asset_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
