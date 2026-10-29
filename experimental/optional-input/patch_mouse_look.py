"""Build an optional mouse-look InputManager variant from a user-supplied file.

This never installs the result.  It clones Unity's original Mouse X/Y rows as
aliases for the game's existing right-stick camera consumers and verifies that
every unrelated serialized object remains byte-identical.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

import UnityPy


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def direct_file(path: Path) -> Path:
    if path.is_symlink() or path.is_junction():
        raise ValueError("Input/output paths must not be links or junctions")
    return path


def unrelated_objects(environment, excluded: int) -> dict[str, str]:
    return {str(obj.path_id): digest(obj.get_raw_data())
            for obj in environment.objects if obj.path_id != excluded}


def build(raw: bytes, expected_sha256: str) -> tuple[bytes, list[dict]]:
    if digest(raw) != expected_sha256.lower():
        raise ValueError("Input hash differs from the explicitly reviewed baseline")
    environment = UnityPy.load(raw)
    managers = [obj for obj in environment.objects if obj.type.name == "InputManager"]
    if len(managers) != 1:
        raise ValueError("Expected exactly one InputManager")
    manager = managers[0]
    original = manager.read_typetree()
    axes = original.get("m_Axes")
    if not isinstance(axes, list) or not axes:
        raise ValueError("InputManager has no legacy axes")

    expected = copy.deepcopy(original)
    additions = []
    for source_name, target_name, invert in (
        ("Mouse X", "rightstick1horizontal", False),
        ("Mouse Y", "rightstick1vertical", True),
    ):
        source = [axis for axis in axes if axis.get("m_Name") == source_name]
        existing = [axis for axis in axes if axis.get("m_Name") == target_name]
        if len(source) != 1 or source[0].get("type") != 1 or not existing:
            raise ValueError("Required original mouse/right-stick axes are absent")
        row = copy.deepcopy(source[0])
        row.update(m_Name=target_name, invert=invert)
        additions.append(row)
    expected["m_Axes"].extend(additions)

    untouched = unrelated_objects(environment, manager.path_id)
    manager.save_typetree(expected)
    output = environment.file.save()
    check = UnityPy.load(output)
    checked = next(obj for obj in check.objects if obj.path_id == manager.path_id)
    if checked.read_typetree() != expected:
        raise ValueError("InputManager round-trip differs")
    if unrelated_objects(check, manager.path_id) != untouched:
        raise ValueError("An unrelated serialized object changed")
    return output, additions


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    source = direct_file(args.input.resolve(strict=True))
    output_path = direct_file(args.output)
    if output_path.exists():
        raise ValueError("Refusing to overwrite an existing output")
    raw = source.read_bytes()
    output, additions = build(raw, args.expected_sha256)
    # A second independent serialization is the determinism gate.
    if build(raw, args.expected_sha256)[0] != output:
        raise ValueError("Unity serialization was not deterministic")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(output)
    report = {
        "format_version": 1,
        "status": "staged_only_not_installed_or_runtime_verified",
        "input_sha256": digest(raw),
        "output_sha256": digest(output),
        "added_axes": additions,
        "unrelated_serialized_objects_preserved": True,
        "runtime_limits": [
            "camera direction and sensitivity still require native validation",
            "mouse UI behavior, focus, and cursor release are not established",
        ],
    }
    encoded = json.dumps(report, indent=2) + "\n"
    if args.report:
        report_path = direct_file(args.report)
        if report_path.exists():
            raise ValueError("Refusing to overwrite an existing report")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(encoded, encoding="utf-8", newline="\n")
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
