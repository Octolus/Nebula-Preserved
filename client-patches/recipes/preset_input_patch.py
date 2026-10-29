"""Prepare a private CharacterEditor bundle copy that focuses preset-name input.

The patch appends one existing Unity Button persistent-call record.  It never
writes to the installed Steam bundle and fails closed on source or layout drift.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

import UnityPy


ORIGINAL_SHA256 = "5d1713e79b4e5bab090a3d57eb4d4c4139999629bb4a2038412a6cb92d1b02e0"
COPY_SHA256 = "9a2cdcaa9ac356fe95df9b5a5ad5df6bba93330ad1591685553031729628d3c4"
ASSET_FILE = "BuildPlayer-CharacterEditor"
ASSET_UNITY_VERSION = "2018.4.36f1"
BUTTON_PATH_ID = 22207
BUTTON_GAMEOBJECT_PATH_ID = 1603
INPUT_PATH_ID = 38565
INPUT_GAMEOBJECT_PATH_ID = 5152
SAVE_COMPONENT_PATH_ID = 38388
MAIN_EVENT_SYSTEM_PATH_ID = 14998
PC_SAVE_EVENT_SYSTEM_PATH_ID = 15015


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _asset_file(env):
    found = [value for name, value in env.file.files.items()
             if name == ASSET_FILE and hasattr(value, "objects")]
    if len(found) != 1:
        raise ValueError(f"Expected one {ASSET_FILE} serialized file, found {len(found)}")
    return found[0]


def _tree(asset_file, path_id, expected_type=None):
    obj = asset_file.objects.get(path_id)
    if obj is None or (expected_type is not None and obj.type.name != expected_type):
        raise ValueError(f"Unexpected object at path ID {path_id}")
    return obj, obj.read_typetree()


def _call_signature(call):
    return (call["m_Target"]["m_FileID"], call["m_Target"]["m_PathID"],
            call["m_MethodName"], call["m_Mode"], call["m_CallState"])


def _snapshot(env, exclude=None):
    result = {}
    for filename, child in env.file.files.items():
        if hasattr(child, "objects"):
            for path_id, obj in child.objects.items():
                if exclude == (filename, path_id):
                    continue
                result[f"{filename}:{path_id}:{obj.type.name}"] = _sha(obj.get_raw_data())
        else:
            # The streamed resource is not a serialized object, but must also
            # survive the bundle rewrite byte-for-byte.
            position = child.Position
            child.Position = 0
            data = child.read_bytes(child.Length)
            child.Position = position
            result[f"{filename}:stream"] = _sha(data)
    return result


def _schema_rows(serialized_type):
    return [(node.m_Level, node.m_Type, node.m_Name, node.m_ByteSize,
             node.m_Version, node.m_TypeFlags, node.m_Index, node.m_MetaFlag)
            for node in serialized_type.nodes.traverse()]


def _end_edit_schema_node(serialized_type, name):
    found = [node for node in serialized_type.nodes.traverse() if node.m_Name == name]
    if len(found) != 1:
        raise ValueError(f"Expected one serialized {name} node, found {len(found)}")
    return found[0]


def _validate_contract(asset_file):
    if asset_file.unity_version != ASSET_UNITY_VERSION:
        raise ValueError("CharacterEditor serialized Unity version drifted")
    button, button_tree = _tree(asset_file, BUTTON_PATH_ID, "MonoBehaviour")
    if (button_tree["m_GameObject"] != {"m_FileID": 0, "m_PathID": BUTTON_GAMEOBJECT_PATH_ID}
            or button_tree["m_Script"] != {"m_FileID": 1, "m_PathID": 360}):
        raise ValueError("Save Preset Button identity drifted")
    _, button_go = _tree(asset_file, BUTTON_GAMEOBJECT_PATH_ID, "GameObject")
    if button_go["m_Name"] != "BTNMENU_SavePreset":
        raise ValueError("Save Preset Button GameObject drifted")
    calls = button_tree["m_OnClick"]["m_PersistentCalls"]["m_Calls"]
    expected = [
        (0, 16799, "onClickBTNMENU_SavePreset", 1, 2),
        (0, SAVE_COMPONENT_PATH_ID, "Show", 1, 2),
    ]
    if [_call_signature(call) for call in calls] != expected:
        raise ValueError("Save Preset Button calls drifted")

    _, input_tree = _tree(asset_file, INPUT_PATH_ID, "MonoBehaviour")
    if (input_tree["m_GameObject"] != {"m_FileID": 0, "m_PathID": INPUT_GAMEOBJECT_PATH_ID}
            or input_tree["m_Script"] != {"m_FileID": 1, "m_PathID": 353}
            or input_tree["m_LineType"] != 0 or input_tree["m_ReadOnly"] != 0):
        raise ValueError("Preset InputField identity or edit policy drifted")
    end_calls = input_tree["m_OnEndEdit"]["m_PersistentCalls"]["m_Calls"]
    if len(end_calls) != 1 or _call_signature(end_calls[0]) != (
            0, SAVE_COMPONENT_PATH_ID, "OnSavePreset", 1, 2):
        raise ValueError("Preset InputField OnEndEdit contract drifted")
    input_type = asset_file.objects[INPUT_PATH_ID].serialized_type
    _end_edit_schema_node(input_type, "m_OnEndEdit")
    if any(node.m_Name == "m_OnDidEndEdit" for node in input_type.nodes.traverse()):
        raise ValueError("Preset InputField already contains the runtime end-edit field")
    _, input_go = _tree(asset_file, INPUT_GAMEOBJECT_PATH_ID, "GameObject")
    if input_go["m_Name"] != "InputFieldSavePresetName" or input_go["m_IsActive"] is not False:
        raise ValueError("Preset InputField GameObject drifted")

    _, save_tree = _tree(asset_file, SAVE_COMPONENT_PATH_ID, "MonoBehaviour")
    if (save_tree["eventSystem"]["m_PathID"] != MAIN_EVENT_SYSTEM_PATH_ID
            or save_tree["BTNMENU_SavePreset"]["m_PathID"] != BUTTON_GAMEOBJECT_PATH_ID
            or save_tree["inputField"]["m_PathID"] != INPUT_PATH_ID):
        raise ValueError("SavePresetName references drifted")
    _, pc_event = _tree(asset_file, PC_SAVE_EVENT_SYSTEM_PATH_ID, "MonoBehaviour")
    if pc_event["m_FirstSelected"] != {"m_FileID": 0, "m_PathID": INPUT_GAMEOBJECT_PATH_ID}:
        raise ValueError("PC preset EventSystem first selection drifted")
    _, pc_event_go = _tree(asset_file, pc_event["m_GameObject"]["m_PathID"], "GameObject")
    if pc_event_go["m_Name"] != "EventSystemPCSavePreset" or pc_event_go["m_IsActive"] is not True:
        raise ValueError("PC preset EventSystem activation drifted")
    return button, button_tree, calls, input_type


def prepare(source: bytes):
    if _sha(source) != ORIGINAL_SHA256:
        raise ValueError("Source SHA256 differs from the analyzed CharacterEditor bundle")
    env = UnityPy.load(source)
    asset_file = _asset_file(env)
    button, button_tree, calls, input_type = _validate_contract(asset_file)
    original_calls = copy.deepcopy(calls)
    original_schema = _schema_rows(input_type)
    child_names_before = sorted(env.file.files)
    before = _snapshot(env, (ASSET_FILE, BUTTON_PATH_ID))

    focus_call = copy.deepcopy(calls[1])
    focus_call["m_Target"]["m_PathID"] = INPUT_PATH_ID
    focus_call["m_MethodName"] = "ActivateInputField"
    button_tree["m_OnClick"]["m_PersistentCalls"]["m_Calls"].append(focus_call)
    button.save_typetree(button_tree)
    # In the 2021 runtime, m_OnEndEdit is a legacy alias for m_OnSubmit;
    # DeactivateInputField invokes the distinct m_OnDidEndEdit slot.  The
    # UnityEvent<string> payload shape is unchanged, so migrate its type-tree
    # name without touching the serialized listener bytes.
    _end_edit_schema_node(input_type, "m_OnEndEdit").m_Name = "m_OnDidEndEdit"
    output = env.file.save("original")
    if _sha(output) != COPY_SHA256:
        raise ValueError("Prepared preset-input copy drifted from its reviewed SHA256")

    check = UnityPy.load(output)
    if sorted(check.file.files) != child_names_before:
        raise ValueError("Bundle child-file inventory changed")
    check_asset = _asset_file(check)
    check_button, check_tree = _tree(check_asset, BUTTON_PATH_ID, "MonoBehaviour")
    actual = check_tree["m_OnClick"]["m_PersistentCalls"]["m_Calls"]
    if actual[:2] != original_calls or len(actual) != 3 or _call_signature(actual[2]) != (
            0, INPUT_PATH_ID, "ActivateInputField", 1, 2):
        raise ValueError("Serialized focus call verification failed")
    if _snapshot(check, (ASSET_FILE, BUTTON_PATH_ID)) != before:
        raise ValueError("An object or streamed resource outside the Button changed")
    if check_asset.unity_version != ASSET_UNITY_VERSION:
        raise ValueError("Serialized Unity version changed")
    check_input = check_asset.objects[INPUT_PATH_ID]
    _end_edit_schema_node(check_input.serialized_type, "m_OnDidEndEdit")
    if any(node.m_Name == "m_OnEndEdit" for node in check_input.serialized_type.nodes.traverse()):
        raise ValueError("Legacy end-edit field remained after migration")
    expected_schema = list(original_schema)
    old_index = next(number for number, row in enumerate(expected_schema)
                     if row[2] == "m_OnEndEdit")
    expected_schema[old_index] = (*expected_schema[old_index][:2], "m_OnDidEndEdit",
                                  *expected_schema[old_index][3:])
    if _schema_rows(check_input.serialized_type) != expected_schema:
        raise ValueError("InputField type tree changed beyond the exact field rename")
    migrated_tree = check_input.read_typetree()
    migrated_calls = migrated_tree["m_OnDidEndEdit"]["m_PersistentCalls"]["m_Calls"]
    if len(migrated_calls) != 1 or _call_signature(migrated_calls[0]) != (
            0, SAVE_COMPONENT_PATH_ID, "OnSavePreset", 1, 2):
        raise ValueError("Migrated runtime end-edit listener verification failed")

    manifest = {
        "format_version": 1,
        "kind": "prepared_preset_input_charactereditor_copy",
        "source_sha256": ORIGINAL_SHA256,
        "copy_sha256": COPY_SHA256,
        "source_size": len(source),
        "copy_size": len(output),
        "asset_file": ASSET_FILE,
        "asset_unity_version": ASSET_UNITY_VERSION,
        "changed_object": {
            "path_id": BUTTON_PATH_ID,
            "game_object_path_id": BUTTON_GAMEOBJECT_PATH_ID,
            "game_object_name": "BTNMENU_SavePreset",
            "original_calls_preserved": True,
            "appended_call": {
                "target_path_id": INPUT_PATH_ID,
                "target_game_object_path_id": INPUT_GAMEOBJECT_PATH_ID,
                "target_game_object_name": "InputFieldSavePresetName",
                "method": "ActivateInputField",
                "order": 3,
            },
        },
        "changed_type_tree": {
            "object_path_id": INPUT_PATH_ID,
            "serialized_type_id": check_input.type_id,
            "before_field": "m_OnEndEdit",
            "after_field": "m_OnDidEndEdit",
            "event_payload_bytes_changed": False,
            "all_other_type_tree_nodes_preserved": True
        },
        "active_pc_save_event_system_path_id": PC_SAVE_EVENT_SYSTEM_PATH_ID,
        "pc_save_event_system_first_selected_path_id": INPUT_GAMEOBJECT_PATH_ID,
        "preserved_raw_entries": len(before),
        "all_other_serialized_objects_and_streamed_resources_preserved": True,
        "source_changed": False,
        "target_executed": False,
        "runtime_retested": False,
        "limits": [
            "Static UnityEvent and native InputField review supports focus activation; runtime behavior remains untested.",
            "The patch does not alter preset serialization, HTTP requests, controller bindings, or the Steam bundle.",
            "The rewritten bundle retains original compression flags but is not byte-layout-identical to the source bundle.",
        ],
    }
    return output, manifest


def validate_paths(source: Path, destination: Path, manifest: Path):
    source = source.resolve(strict=True)
    destination = destination.resolve()
    manifest = manifest.resolve()
    if destination == source or destination.exists() or "steamapps" in [p.lower() for p in destination.parts]:
        raise ValueError("Destination must be a new file separate from the source and outside steamapps")
    if (manifest in (source, destination) or manifest.exists() or manifest.suffix.lower() != ".json"
            or "steamapps" in [p.lower() for p in manifest.parts]):
        raise ValueError("Manifest must be a new separate JSON file outside steamapps")
    return source, destination, manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        source, destination, manifest_path = validate_paths(
            args.source, args.destination, args.manifest)
        original = source.read_bytes()
        output, manifest = prepare(original)
        if _sha(source.read_bytes()) != ORIGINAL_SHA256:
            raise ValueError("Source changed while preparing the copy")
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as stream:
        stream.write(output)
    manifest["source_path"] = str(source)
    manifest["copy_path"] = str(destination)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({
        "copy_sha256": manifest["copy_sha256"],
        "changed_object_path_id": BUTTON_PATH_ID,
        "preserved_raw_entries": manifest["preserved_raw_entries"],
        "source_changed": False,
        "target_executed": False,
        "runtime_retested": False,
    }))


if __name__ == "__main__":
    main()
