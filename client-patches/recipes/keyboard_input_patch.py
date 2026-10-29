"""Prepare a keyboard-compatible COPY of Nebula Realms globalgamemanagers.

Only the serialized InputManager object is changed.  The installed Steam file
is an immutable, hash-bound input and output paths under steamapps are refused.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

import UnityPy


ORIGINAL_SHA256 = "ecdebe7c899776956a4d5fb801f37f04128ec9bef72e744cd1e7fd5349ce8466"
UNITY_VERSION = "2021.3.9f1"
EXPECTED_AXES = 42
DEFAULT_COPY_SHA256 = "54c632afc0db42a5b39af4084428efbb28de6241c0aea7401a74eaac1dc822c6"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _object_hashes(env, exclude_path_id=None):
    return {
        f"{obj.path_id}:{obj.type.name}": _sha(obj.get_raw_data())
        for obj in env.objects if obj.path_id != exclude_path_id
    }


def _one_input_manager(env):
    found = [obj for obj in env.objects if obj.type.name == "InputManager"]
    if len(found) != 1:
        raise ValueError(f"Expected one InputManager object, found {len(found)}")
    return found[0]


def _one_named_axis(axes, name):
    found = [(number, axis) for number, axis in enumerate(axes) if axis["m_Name"] == name]
    if len(found) != 1:
        raise ValueError(f"Expected one {name!r} axis, found {len(found)}")
    return found[0]


def _keyboard_axis(template, name, negative, positive):
    axis = copy.deepcopy(template)
    axis.update({
        "m_Name": name,
        "descriptiveName": "",
        "descriptiveNegativeName": "",
        "negativeButton": negative,
        "positiveButton": positive,
        "altNegativeButton": "",
        "altPositiveButton": "",
        "gravity": 1000.0,
        "dead": template["dead"],
        "sensitivity": 1000.0,
        "snap": False,
        "invert": False,
        "type": 0,
        "axis": 0,
        "joyNum": 0,
    })
    return axis


def prepare(source: bytes, world_controls=False):
    if _sha(source) != ORIGINAL_SHA256:
        raise ValueError("Source SHA256 differs from the analyzed Steam build")

    env = UnityPy.load(source)
    if env.file.unity_version != UNITY_VERSION:
        raise ValueError("Unexpected Unity version")
    manager = _one_input_manager(env)
    original_tree = manager.read_typetree()
    original_axes = copy.deepcopy(original_tree["m_Axes"])
    if len(original_axes) != EXPECTED_AXES:
        raise ValueError(f"Expected {EXPECTED_AXES} axes, found {len(original_axes)}")
    submit_number, submit = _one_named_axis(original_axes, "Submit")
    _one_named_axis(original_axes, "dpad1_horizontal")
    _one_named_axis(original_axes, "dpad1_vertical")
    if submit["positiveButton"] != "" or submit["altPositiveButton"] != "joystick 1 button 0":
        raise ValueError("Submit bindings differ from the reviewed build")

    expected_axes = copy.deepcopy(original_axes)
    expected_axes[submit_number]["positiveButton"] = "return"
    expected_axes.extend([
        _keyboard_axis(submit, "dpad1_horizontal", "left", "right"),
        _keyboard_axis(submit, "dpad1_vertical", "down", "up"),
    ])
    if world_controls:
        # The shipped joystick vertical axes report stick-up as negative.
        # Preserve that sign convention for W/I so native consumers see the
        # same values as a physical PS4 controller.
        expected_axes.extend([
            _keyboard_axis(submit, "leftstick1horizontal", "a", "d"),
            _keyboard_axis(submit, "leftstick1vertical", "w", "s"),
            _keyboard_axis(submit, "rightstick1horizontal", "j", "l"),
            _keyboard_axis(submit, "rightstick1vertical", "i", "k"),
        ])
    modified_tree = copy.deepcopy(original_tree)
    modified_tree["m_Axes"] = expected_axes
    other_before = _object_hashes(env, manager.path_id)
    manager.save_typetree(modified_tree)
    output = env.file.save()

    check = UnityPy.load(output)
    if check.file.unity_version != UNITY_VERSION:
        raise ValueError("Unity version changed during serialization")
    check_manager = _one_input_manager(check)
    actual_tree = check_manager.read_typetree()
    if actual_tree.get("m_UsePhysicalKeys") != original_tree.get("m_UsePhysicalKeys"):
        raise ValueError("InputManager physical-key policy changed")
    actual_axes = actual_tree["m_Axes"]
    appended_count = 6 if world_controls else 2
    if actual_axes != expected_axes or len(actual_axes) != len(original_axes) + appended_count:
        raise ValueError("Serialized InputManager axis verification failed")
    other_after = _object_hashes(check, check_manager.path_id)
    if other_after != other_before:
        raise ValueError("A non-InputManager serialized object changed")

    output_sha256 = _sha(output)
    if not world_controls and output_sha256 != DEFAULT_COPY_SHA256:
        raise ValueError("Default keyboard copy drifted from its reviewed SHA256")
    changes = [
        {
            "axis_index": submit_number,
            "name": "Submit",
            "field": "positiveButton",
            "before": "",
            "after": "return",
            "preserved_alt_positive_button": "joystick 1 button 0",
        },
    ]
    changes.extend({"axis_index": len(original_axes) + number, **axis}
                   for number, axis in enumerate(actual_axes[len(original_axes):]))
    manifest = {
        "format_version": 1,
        "kind": "prepared_keyboard_input_globalgamemanagers_copy",
        "source_sha256": ORIGINAL_SHA256,
        "copy_sha256": output_sha256,
        "source_size": len(source),
        "copy_size": len(output),
        "unity_version": UNITY_VERSION,
        "input_manager_path_id": manager.path_id,
        "axes_before": len(original_axes),
        "axes_after": len(actual_axes),
        "mode": "menu_and_world_keyboard" if world_controls else "menu_keyboard",
        "world_controls": bool(world_controls),
        "changes": changes,
        "original_axis_rows_preserved_except_submit_positive_button": True,
        "original_joystick_dpad_rows_preserved": True,
        "non_input_manager_object_count": len(other_before),
        "all_non_input_manager_object_raw_hashes_preserved": True,
        "source_changed": False,
        "target_executed": False,
        "listeners_started": False,
        "runtime_proof": False,
        "limits": [
            "This is a private compatibility copy; the installed Steam asset is not changed.",
            "Static Unity serialization checks do not prove runtime input or login behavior.",
            "The patch adds keyboard Submit and navigation aliases; it does not emulate a PS4 controller.",
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
    parser.add_argument("--world-controls", action="store_true",
                        help="also append WASD and IJKL stick-axis rows")
    args = parser.parse_args(argv)
    try:
        source, destination, manifest_path = validate_paths(
            args.source, args.destination, args.manifest)
        before = _sha(source.read_bytes())
        output, manifest = prepare(source.read_bytes(), args.world_controls)
        if _sha(source.read_bytes()) != before:
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
        "axes_before": manifest["axes_before"],
        "axes_after": manifest["axes_after"],
        "source_changed": False,
        "target_executed": False,
        "runtime_proof": False,
    }))


if __name__ == "__main__":
    main()
