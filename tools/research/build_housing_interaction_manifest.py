"""Build the trusted interaction manifest for grantable ground furniture.

This is an offline, read-only scanner.  It only opens bundles selected by the
effective HousingStore catalog intersection and never starts Unity or a server.
Verified-empty and unresolved/parse-failed prefabs are deliberately different
states: only the former may contribute an empty trusted registry.
"""

from __future__ import annotations

from _research_paths import workspace, output_root, game_path

import argparse
from collections import Counter
import gc
import hashlib
import json
from pathlib import Path
import re
from typing import Any

import UnityPy


ROOT = workspace()
DEFAULT_ASSET_ROOT = game_path('Nebula Realms_Data/StreamingAssets/StandaloneWindows')
HTTP_AUDIT = ROOT / "results/protocol/http-nonminigame-gap-audit.json"
PLACEMENT = ROOT / "results/protocol/housing-placement-contracts.json"
DUMP = ROOT / "work/decompiled/dump.cs"
DEFAULT_OUTPUT = ROOT / "results/protocol/housing-interaction-manifest.json"
NATIVE_EVIDENCE = {
    "LightTrigger.APITPRunIsActive": "453b60",
    "LightTrigger.APITPRunIsInactive": "453bc0",
    "NebulaSeat.Interact": "6159f0",
    "NebulaOccupable.Initialize": "612380",
    "NebulaOccupable.LeaveInteract": "612700",
    "AnimationTrigger.RemoteInteract": "35a740",
    "HousingFurnishing.SaveAtServer": "6bdb40",
    "GetComponentsInChildren wrapper": "865a20",
}

# Explicit preservation review.  Unknown subclasses never become ordinary by
# inheritance alone.  The three classes below are the only interactive classes
# observed in the effective ground catalog.
GENERIC_POLICY = {
    "LightTrigger": ("ordinary", "light_toggle"),
}
OCCUPABLE_POLICY = {
    "NebulaSeat": ("ordinary", "seat"),
    "Bench": ("ordinary", "animation_trigger_seat"),
}
DEFERRED_GENERIC = {
    "JG_CampSilverLake_Killer_Launcher",
    "JG_Ghost_Minigame",
    "JG_Ghost_Candle",
    "JG_SorcerersEyrie_Ingredient",
    "JG_SorcerersEyrie_PotionControl",
    "JG_SorcerersEyrie_RecipeControl",
}
NON_94_GENERIC = {"DayNightTrigger": "tcp30_daynight"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def class_bases(dump_text: str) -> dict[str, str]:
    return dict(
        re.findall(
            r"^public (?:abstract |sealed )?class ([A-Za-z_][A-Za-z0-9_]*)"
            r" : ([A-Za-z_][A-Za-z0-9_.]*)",
            dump_text,
            re.MULTILINE,
        )
    )


def derives(name: str, target: str, bases: dict[str, str]) -> bool:
    seen: set[str] = set()
    while name and name not in seen:
        if name == target:
            return True
        seen.add(name)
        name = bases.get(name, "")
    return False


def stable_instance_key(
    layout_digest: str,
    ground_array_index: int,
    item_id: str,
    sibling_index_chain: list[int],
    component_slot: int,
    registry_kind: str,
) -> str:
    """Identity used by the bridge; duplicate copies differ by array index."""
    if (
        not re.fullmatch(r"[0-9a-f]{64}", layout_digest)
        or ground_array_index < 0
        or not item_id
        or component_slot < 0
        or registry_kind not in {"generic", "occupable"}
        or any(type(index) is not int or index < 0 for index in sibling_index_chain)
    ):
        raise ValueError("invalid stable instance key fields")
    chain = "/".join(map(str, sibling_index_chain)) or "."
    return (
        f"furniture:{layout_digest}:{ground_array_index}:{item_id}:"
        f"{chain}:{component_slot}:{registry_kind}"
    )


def effective_ground_rows(http_document: dict[str, Any], placement: dict[str, Any]) -> list[dict[str, Any]]:
    contracts = placement.get("items", {})
    selected = []
    for row in http_document.get("housing_catalog", []):
        item_id = row.get("item_id")
        contract = contracts.get(item_id)
        if row.get("grantable") is not True or not isinstance(contract, dict):
            continue
        if contract.get("behaviour") != "ground":
            continue
        if (
            contract.get("table") != row.get("table")
            or contract.get("bundle") != row.get("bundle")
            or contract.get("manifest_sha256") != row.get("manifest_sha256")
        ):
            continue
        selected.append({**row, "contract": contract})
    selected.sort(key=lambda value: value["item_id"])
    if len({row["item_id"] for row in selected}) != len(selected):
        raise ValueError("duplicate effective ground item ID")
    return selected


def _reference(value: Any) -> tuple[int, int]:
    if isinstance(value, dict):
        return int(value.get("m_FileID", 0)), int(value.get("m_PathID", 0))
    return int(getattr(value, "file_id", getattr(value, "m_FileID", 0))), int(
        getattr(value, "path_id", getattr(value, "m_PathID", 0))
    )


"""Exact shipped Unity-2018 serialized missing-script placeholder recognition.

This is not an interaction allowlist. A recognized record has no script pointer,
type identity or serialized script payload and cannot name an executable class.
Unknown/non-null/extended/malformed MonoBehaviours remain unresolved.
"""
import hashlib
import struct


def null_script_placeholder(target, game_object, chain, slot):
    try:
        if target.type.name != 'MonoBehaviour':
            return None
        serialized = target.serialized_type
        if (serialized.class_id != 114 or serialized.is_stripped_type is not False or
                serialized.script_type_index != -1 or
                bytes(serialized.script_id) != bytes(16) or
                bytes(serialized.old_type_hash) != bytes(16) or
                any(getattr(serialized, key, None) is not None
                    for key in ('m_ClassName', 'm_NameSpace', 'm_AssemblyName'))):
            return None
        if (target.assets_file.name != game_object.assets_file.name or
                target.reader.endian != '<' or target.assets_file.header.version != 17 or
                not str(target.version).startswith('2018.4')):
            return None
        fields = target.read_typetree()
        if (set(fields) != {'m_GameObject', 'm_Enabled', 'm_Script', 'm_Name'} or
                fields['m_GameObject'] != {'m_FileID': 0, 'm_PathID': game_object.path_id} or
                fields['m_Script'] != {'m_FileID': 0, 'm_PathID': 0} or
                fields['m_Name'] != '' or type(fields['m_Enabled']) is not int or
                fields['m_Enabled'] not in (0, 1)):
            return None
        raw = target.get_raw_data()
        if len(raw) != 32:
            return None
        owner_file, owner_path, enabled, script_file, script_path, name_length = struct.unpack('<iqB3xiqi', raw)
        if (owner_file != 0 or owner_path != game_object.path_id or
                enabled != fields['m_Enabled'] or raw[13:16] != bytes(3) or
                script_file != 0 or script_path != 0 or name_length != 0):
            return None
        return {'classification': 'non_executable_missing_script_placeholder',
                'asset_file': target.assets_file.name, 'path_id': str(target.path_id),
                'game_object_path_id': str(game_object.path_id),
                'sibling_index_chain': list(chain), 'component_slot': slot,
                'script_reference': {'m_FileID': 0, 'm_PathID': 0},
                'serialized_bytes': len(raw), 'raw_sha256': hashlib.sha256(raw).hexdigest(),
                'script_type_index': -1, 'script_id': bytes(16).hex(),
                'old_type_hash': bytes(16).hex(), 'serialized_file_version': 17,
                'unity_version': str(target.version),
                'fallback_fields': sorted(fields)}
    except (AttributeError, KeyError, TypeError, ValueError, struct.error):
        return None


def inspect_prefab(row: dict[str, Any], asset_root: Path, bases: dict[str, str]) -> dict[str, Any]:
    item_id = row["item_id"]
    bundle_path = asset_root / row["bundle"]
    manifest_path = bundle_path.with_suffix(".manifest")
    base = {
        "item_id": item_id,
        "table": row["table"],
        "bundle": row["bundle"],
        "asset_path": row["asset_path"],
        "manifest_sha256": row["manifest_sha256"],
        "placement_cost": row["contract"]["placement_cost"],
        "serialized_size": row["contract"]["serialized_size"],
        "expected_matching_ground_components": row["contract"]["matching_component_count"],
        "admission": "deny",
        "interactions": [],
        "unresolved": [],
    }
    if not bundle_path.is_file() or not manifest_path.is_file():
        base.update(status="missing_source", source_error="bundle_or_manifest_missing")
        return base
    base["bundle_sha256"] = sha256(bundle_path)
    actual_manifest_hash = sha256(manifest_path)
    if actual_manifest_hash != row["manifest_sha256"]:
        base.update(status="source_mismatch", actual_manifest_sha256=actual_manifest_hash)
        return base
    manifest_text = manifest_path.read_text(encoding="utf-8-sig")
    expected_asset = row["asset_path"].lower()
    manifest_assets = {match.lower() for match in re.findall(r"(?m)^- (.+)$", manifest_text)}
    if expected_asset not in manifest_assets:
        base.update(status="source_mismatch", source_error="asset_path_not_in_manifest")
        return base

    try:
        env = UnityPy.load(str(bundle_path))
        containers = {name.lower(): pointer for name, pointer in env.container.items()}
        root_pointer = containers.get(expected_asset)
        if root_pointer is None:
            base.update(status="container_unresolved", source_error="exact_container_path_missing")
            return base
        root = root_pointer.deref()
        if root is None or root.type.name != "GameObject":
            base.update(status="container_unresolved", source_error="container_not_game_object")
            return base

        objects = {(obj.assets_file.name, obj.path_id): obj for obj in env.objects}
        visited: set[tuple[str, int]] = set()
        ground_ids: list[str] = []
        inactive_interactions: list[dict[str, Any]] = []
        missing_script_placeholders: list[dict[str, Any]] = []

        def unresolved(phase: str, obj: Any, chain: list[int], slot: int | None, error: Any) -> None:
            record = {
                "phase": phase,
                "asset_file": getattr(obj.assets_file, "name", None),
                "path_id": str(getattr(obj, "path_id", "")),
                "sibling_index_chain": chain,
                "component_slot": slot,
                "error": type(error).__name__ if isinstance(error, Exception) else str(error),
            }
            try:
                raw = obj.get_raw_data()
                record["raw_sha256"] = hashlib.sha256(raw).hexdigest()
                record["serialized_bytes"] = len(raw)
            except Exception:
                pass
            if phase == "script_resolution":
                try:
                    fallback = obj.read_typetree()
                    record["script_reference"] = fallback.get("m_Script")
                    record["fallback_fields"] = sorted(fallback)
                    serialized_type = obj.serialized_type
                    record["script_type_index"] = getattr(serialized_type, "script_type_index", None)
                    record["script_id"] = bytes(getattr(serialized_type, "script_id", b"")).hex()
                    record["old_type_hash"] = bytes(getattr(serialized_type, "old_type_hash", b"")).hex()
                except Exception as fallback_error:
                    record["fallback_error"] = type(fallback_error).__name__
            base["unresolved"].append(record)

        def walk(game_object: Any, chain: list[int], parent_active: bool) -> None:
            identity = (game_object.assets_file.name, game_object.path_id)
            if identity in visited:
                unresolved("hierarchy_cycle", game_object, chain, None, "cycle")
                return
            visited.add(identity)
            try:
                go_data = game_object.read_typetree()
            except Exception as error:
                unresolved("game_object_parse", game_object, chain, None, error)
                return
            active = parent_active and bool(go_data.get("m_IsActive"))
            transform = None
            components = go_data.get("m_Component", [])
            for slot, component in enumerate(components):
                ref = component.get("component", component) if isinstance(component, dict) else component
                file_id, path_id = _reference(ref)
                if file_id != 0 or not path_id:
                    unresolved("external_component", game_object, chain, slot, "external_or_null")
                    continue
                try:
                    target = ref.deref() if hasattr(ref, "deref") else None
                    if target is None:
                        # Typetree dictionaries do not retain a dereference helper.
                        target = objects.get((game_object.assets_file.name, path_id))
                    if target is None:
                        unresolved("component_resolution", game_object, chain, slot, "missing_local_component")
                        continue
                    if target.type.name in {"Transform", "RectTransform"}:
                        transform = target
                    if target.type.name != "MonoBehaviour":
                        continue
                    try:
                        component_base = target.read(check_read=False)
                        script = component_base.m_Script.deref_parse_as_object()
                        class_name = script.m_ClassName
                    except Exception as error:
                        placeholder = null_script_placeholder(target, game_object, chain, slot)
                        if placeholder is not None:
                            missing_script_placeholders.append(placeholder)
                        else:
                            unresolved("script_resolution", target, chain, slot, error)
                        continue
                    try:
                        fields = target.read_typetree()
                    except Exception as error:
                        unresolved("component_typetree", target, chain, slot, error)
                        continue
                    if class_name == "HousingAssetGround":
                        ground_ids.append(str(fields.get("id", "")))
                    kind = None
                    if derives(class_name, "GenericInteractable", bases):
                        kind = "generic"
                    elif derives(class_name, "NebulaOccupable", bases):
                        kind = "occupable"
                    if kind is None:
                        continue
                    if not active:
                        inactive_interactions.append(
                            {
                                "sibling_index_chain": chain,
                                "component_slot": slot,
                                "class": class_name,
                                "registry_kind": kind,
                            }
                        )
                        continue
                    if kind == "generic" and class_name in DEFERRED_GENERIC:
                        classification, behavior = "deferred_minigame", "deferred_native_subtype"
                    elif kind == "generic" and class_name in NON_94_GENERIC:
                        classification, behavior = "non_94_override", NON_94_GENERIC[class_name]
                    elif kind == "generic" and class_name in GENERIC_POLICY:
                        classification, behavior = GENERIC_POLICY[class_name]
                    elif kind == "occupable" and class_name in OCCUPABLE_POLICY:
                        classification, behavior = OCCUPABLE_POLICY[class_name]
                    else:
                        classification, behavior = "unreviewed", "unreviewed_native_subtype"
                    if kind == "generic" and not isinstance(fields.get("data"), list):
                        unresolved("generic_extension_schema", target, chain, slot, "data_array_missing")
                        continue
                    extension_count = len(fields["data"]) if kind == "generic" else 0
                    base["interactions"].append(
                        {
                            "semantic_prefab_key": (
                                f"{'/'.join(map(str, chain)) or '.'}|{class_name}|slot{slot}|{kind}"
                            ),
                            "registry_kind": kind,
                            "sibling_index_chain": chain,
                            "game_object_name": go_data.get("m_Name"),
                            "component_slot": slot,
                            "class": class_name,
                            "native_behavior": behavior,
                            "classification": classification,
                            "admission": "allow" if classification == "ordinary" else "deny",
                            "extension_arity": extension_count,
                            "enabled": bool(fields.get("m_Enabled", 1)),
                            "asset_file": target.assets_file.name,
                            "component_path_id": str(target.path_id),
                            "raw_sha256": hashlib.sha256(target.get_raw_data()).hexdigest(),
                        }
                    )
                except Exception as error:
                    unresolved("component_parse", game_object, chain, slot, error)
            if transform is None:
                unresolved("hierarchy", game_object, chain, None, "missing_transform")
                return
            try:
                transform_data = transform.read_typetree()
                children = transform_data.get("m_Children", [])
            except Exception as error:
                unresolved("transform_parse", transform, chain, None, error)
                return
            for index, child_ref in enumerate(children):
                file_id, path_id = _reference(child_ref)
                if file_id != 0 or not path_id:
                    unresolved("child_resolution", transform, chain + [index], None, "external_or_null_child")
                    continue
                try:
                    child_transform = child_ref.deref() if hasattr(child_ref, "deref") else None
                    if child_transform is None:
                        child_transform = objects.get((transform.assets_file.name, path_id))
                    child_data = child_transform.read_typetree()
                    go_ref = child_data.get("m_GameObject")
                    go_file, go_path = _reference(go_ref)
                    child_go = go_ref.deref() if hasattr(go_ref, "deref") else None
                    if child_go is None:
                        child_go = objects.get((child_transform.assets_file.name, go_path))
                    if go_file != 0 or child_go is None or child_go.type.name != "GameObject":
                        raise ValueError("child_transform_game_object_unresolved")
                    walk(child_go, chain + [index], active)
                except Exception as error:
                    unresolved("child_resolution", transform, chain + [index], None, error)

        walk(root, [], True)
        base["root_game_object_path_id"] = str(root.path_id)
        base["root_game_object_name"] = root.read_typetree().get("m_Name")
        base["active_graph_game_object_count"] = len(visited)
        base["canonical_graph_ground_ids"] = ground_ids
        base["inactive_interactions"] = inactive_interactions
        if missing_script_placeholders:
            base["non_executable_placeholders"] = missing_script_placeholders
        unique_semantic = {entry["semantic_prefab_key"] for entry in base["interactions"]}
        if len(unique_semantic) != len(base["interactions"]):
            base["unresolved"].append({"phase": "semantic_key", "error": "duplicate_key"})
        # Two shipped sofa bundles intentionally contain multiple ground
        # components.  Exact container selection identifies the canonical
        # prefab graph; multiple matching IDs inside that graph are evidence,
        # not ambiguity.  Zero matching IDs is the unsafe case.
        if ground_ids.count(item_id) < 1:
            base["unresolved"].append(
                {
                    "phase": "ground_identity",
                    "error": "canonical_graph_has_no_matching_item_id",
                    "matching_count": ground_ids.count(item_id),
                }
            )
        unreviewed = [entry for entry in base["interactions"] if entry["classification"] == "unreviewed"]
        if unreviewed:
            base["unresolved"].append({"phase": "policy", "error": "unreviewed_interaction_subclass"})
        if base["unresolved"]:
            base["status"] = "unresolved_denied"
            for entry in base["interactions"]:
                entry["subtype_admission"] = entry["admission"]
                entry["admission"] = "deny_item_unresolved"
        elif base["interactions"]:
            base["status"] = "interactive_verified"
            base["admission"] = "allow_reviewed_entries_only"
        else:
            base["status"] = "noninteractive_verified_empty"
            base["admission"] = "allow_empty_registry"
        return base
    except Exception as error:
        base.update(status="parse_failed", source_error=f"{type(error).__name__}:{error}")
        return base
    finally:
        if "env" in locals():
            del env
        gc.collect()


def validate_manifest(document: dict[str, Any]) -> None:
    if document.get("format_version") != 1 or document.get("effective_ground_item_count") != 1035:
        raise ValueError("unsupported or incomplete manifest")
    items = document.get("items")
    if not isinstance(items, list) or len(items) != 1035:
        raise ValueError("manifest item count mismatch")
    ids = [row.get("item_id") for row in items]
    if ids != sorted(ids) or len(ids) != len(set(ids)):
        raise ValueError("manifest item IDs are not unique and sorted")
    valid_status = {
        "interactive_verified",
        "noninteractive_verified_empty",
        "unresolved_denied",
        "parse_failed",
        "missing_source",
        "source_mismatch",
        "container_unresolved",
    }
    for row in items:
        if row.get("status") not in valid_status or not re.fullmatch(r"[0-9a-f]{64}", row.get("bundle_sha256", "")):
            raise ValueError("item status or bundle identity invalid")
        interactions = row.get("interactions", [])
        keys = [entry.get("semantic_prefab_key") for entry in interactions]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate prefab semantic key")
        if row["status"] == "noninteractive_verified_empty" and (interactions or row.get("unresolved")):
            raise ValueError("verified-empty item has interaction or unresolved evidence")
        if row["status"] == "interactive_verified" and (not interactions or row.get("unresolved")):
            raise ValueError("verified-interactive item is incomplete")
        if row["status"] not in {"interactive_verified", "noninteractive_verified_empty"} and row.get("admission") != "deny":
            raise ValueError("unresolved item is not denied")
        for entry in interactions:
            if entry.get("registry_kind") not in {"generic", "occupable"}:
                raise ValueError("invalid registry kind")
            if entry.get("admission") == "allow" and entry.get("classification") != "ordinary":
                raise ValueError("non-ordinary interaction admitted")
            if entry.get("registry_kind") == "occupable" and entry.get("extension_arity") != 0:
                raise ValueError("occupable extension arity is not zero")


def build(asset_root: Path) -> dict[str, Any]:
    http_document = json.loads(HTTP_AUDIT.read_text(encoding="utf-8-sig"))
    placement = json.loads(PLACEMENT.read_text(encoding="utf-8-sig"))
    dump_text = DUMP.read_text(encoding="utf-8")
    rows = effective_ground_rows(http_document, placement)
    if len(rows) != 1035:
        raise ValueError(f"effective ground scope changed: {len(rows)}")
    bases = class_bases(dump_text)
    items = []
    for index, row in enumerate(rows, 1):
        items.append(inspect_prefab(row, asset_root, bases))
        if index % 100 == 0:
            print(f"scanned {index}/{len(rows)}", flush=True)
    statuses = Counter(item["status"] for item in items)
    observed_classes = Counter(
        entry["class"] for item in items for entry in item.get("interactions", [])
    )
    admitted_classes = Counter(
        entry["class"]
        for item in items
        for entry in item.get("interactions", [])
        if entry.get("admission") == "allow"
    )
    result = {
        "format_version": 1,
        "scope": "Offline exact effective HousingStore ground catalog only; no target execution, game, UI, server, listener, connection or live state.",
        "effective_ground_item_count": len(items),
        "selection": {
            "rule": "http housing_catalog grantable=true intersect placement items with behaviour=ground and matching table/bundle/manifest hash",
            "http_audit_sha256": sha256(HTTP_AUDIT),
            "placement_contracts_sha256": sha256(PLACEMENT),
            "dump_sha256": sha256(DUMP),
            "tool_sha256": sha256(Path(__file__)),
            "unitypy_version": getattr(UnityPy, "__version__", "unknown"),
        },
        "semantic_key": {
            "prefab": "root-relative sibling-index chain + concrete class + zero-based GameObject component slot + registry kind",
            "instance": "layout digest + persisted ground array index + item ID + prefab semantic key",
            "duplicate_evidence": "Two copies of one item retain the same prefab key but have distinct persisted ground array indices.",
        },
        "policy": {
            "ordinary_generic_classes": sorted(GENERIC_POLICY),
            "ordinary_occupable_classes": sorted(OCCUPABLE_POLICY),
            "deferred_generic_classes": sorted(DEFERRED_GENERIC),
            "non_94_generic_classes": NON_94_GENERIC,
            "unknown_interaction_subclass": "deny",
            "null_script_placeholder": "Only exact 32-byte Unity-2018.4 base records with null script, absent type identity, no custom payload and exact owning GameObject are non-executable; all other unresolved scripts deny",
            "unresolved_or_parse_failed_item": "deny",
            "verified_empty_item": "allow an explicitly empty registry",
        },
        "native_evidence": [
            {
                "behavior": behavior,
                "rva": "0x" + rva,
                "path": f"work/evidence/ghidra/functions/{rva}.c",
                "sha256": sha256(ROOT / "work/evidence/ghidra/functions" / f"{rva}.c"),
            }
            for behavior, rva in NATIVE_EVIDENCE.items()
        ],
        "status_counts": dict(sorted(statuses.items())),
        "observed_interaction_class_counts": dict(sorted(observed_classes.items())),
        "admitted_interaction_class_counts": dict(sorted(admitted_classes.items())),
        "items": items,
    }
    validate_manifest(result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--asset-root", type=Path, default=DEFAULT_ASSET_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--validate", type=Path)
    args = parser.parse_args()
    if args.validate:
        document = json.loads(args.validate.read_text(encoding="utf-8-sig"))
        validate_manifest(document)
        print(json.dumps({"valid": True, "items": len(document["items"])}))
        return
    result = build(args.asset_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "status_counts": result["status_counts"]}))


if __name__ == "__main__":
    main()
