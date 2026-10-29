"""Validate the exact-build native hook sites for the interaction registry bridge.

This is an offline inspector.  It never loads GameAssembly, starts the game, writes
to a process, or modifies its input.  The optional JSON output must be a new file.
"""
from __future__ import annotations

from _research_paths import workspace, output_root, game_path

import argparse
import hashlib
import json
from pathlib import Path
import struct

import pefile


EXPECTED_SHA256 = "c4dd5db599e5e5ce4adf25f09ffe70ad10e0928adf6a2e862176d537026b44ac"

CALL_SITES = (
    ("initial_occupable", 0x5EAEC7, 0x612380, "occupable", "initial"),
    ("initial_generic", 0x5EAF1D, 0x451060, "generic", "initial"),
    ("save_occupable", 0x6BEAB7, 0x612380, "occupable", "save"),
    ("save_generic", 0x6BEB17, 0x451060, "generic", "save"),
    ("load_occupable", 0x6CBC4A, 0x612380, "occupable", "load"),
    ("load_generic", 0x6CBC8E, 0x451060, "generic", "load"),
    ("initial_ready", 0x5EAFE1, 0x141C4B0, "ready", "initial"),
    ("save_ready", 0x6BEC57, 0x3A6A20, "ready", "save"),
)

REQUIRED_EXPORTS = (
    "il2cpp_domain_get",
    "il2cpp_domain_get_assemblies",
    "il2cpp_assembly_get_image",
    "il2cpp_class_from_name",
    "il2cpp_class_get_method_from_name",
    "il2cpp_runtime_invoke",
    "il2cpp_object_get_class",
    "il2cpp_class_get_name",
    "il2cpp_class_get_namespace",
    "il2cpp_string_new_utf16",
    "il2cpp_thread_attach",
    "il2cpp_thread_current",
)

REQUIRED_IMPORTS = (
    "GetModuleHandleW",
    "GetProcAddress",
    "GetModuleFileNameW",
    "LoadLibraryExW",
)

FUNCTION_PROBES = {
    "on_connected_move_next": 0x5EA6E0,
    "housing_save_at_server": 0x6BDB40,
    "housing_load_move_next": 0x6C95D0,
    "housing_load_callback": 0x6CBC4A,
}

NATIVE_HELPER_PROBES = {
    "GameObject.GetComponentsInternal": (
        0x1B87670,
        bytes.fromhex("48895c240848896c2410488974241857"),
        "RCX GameObject, RDX Type, R8/R9 flags, stack flags/list/MethodInfo -> array",
    ),
}

REPLACEMENT_SITES = (
    (
        "load_ready",
        0x6CA8DC,
        bytes.fromhex("488b5028488b4840ff5018"),
        "Replace the delegate argument loads and indirect call with one rel32 wrapper call plus six NOPs. The wrapper emulates call [RAX+0x18] with RCX=[RAX+0x40], RDX=[RAX+0x28], then commits HOUSING_LOAD with owner R15.",
    ),
)


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _runtime_bounds(pe: pefile.PE, rva: int) -> dict[str, str] | None:
    for entry in pe.DIRECTORY_ENTRY_EXCEPTION:
        row = entry.struct
        if row.BeginAddress <= rva < row.EndAddress:
            return {
                "begin_rva": hex(row.BeginAddress),
                "end_rva": hex(row.EndAddress),
                "unwind_rva": hex(row.UnwindData),
            }
    return None


def inspect(path: Path) -> dict:
    raw = path.read_bytes()
    digest = sha256(raw)
    if digest != EXPECTED_SHA256:
        raise ValueError(f"unsupported GameAssembly SHA-256: {digest}")

    pe = pefile.PE(data=raw, fast_load=False)
    if pe.FILE_HEADER.Machine != 0x8664 or pe.OPTIONAL_HEADER.Magic != 0x20B:
        raise ValueError("expected an AMD64 PE32+ image")

    hooks = []
    for name, rva, target, kind, source in CALL_SITES:
        offset = pe.get_offset_from_rva(rva)
        encoded = raw[offset : offset + 5]
        if len(encoded) != 5 or encoded[0] != 0xE8:
            raise ValueError(f"{name} at {rva:#x} is not a direct rel32 call")
        actual = rva + 5 + struct.unpack_from("<i", encoded, 1)[0]
        if actual != target:
            raise ValueError(f"{name} target is {actual:#x}, expected {target:#x}")
        hooks.append(
            {
                "name": name,
                "call_rva": hex(rva),
                "file_offset": hex(offset),
                "bytes": encoded.hex(),
                "target_rva": hex(target),
                "kind": kind,
                "source": source,
            }
        )

    replacement_hooks = []
    for name, rva, expected, contract in REPLACEMENT_SITES:
        offset = pe.get_offset_from_rva(rva)
        actual = raw[offset : offset + len(expected)]
        if actual != expected:
            raise ValueError(f"{name} replacement bytes differ at {rva:#x}")
        replacement_hooks.append(
            {
                "name": name,
                "rva": hex(rva),
                "file_offset": hex(offset),
                "length": len(expected),
                "bytes": expected.hex(),
                "contract": contract,
            }
        )

    exports = {row.name.decode(): row.address for row in pe.DIRECTORY_ENTRY_EXPORT.symbols if row.name}
    export_rows = {}
    for name in REQUIRED_EXPORTS:
        if name not in exports:
            raise ValueError(f"missing IL2CPP export: {name}")
        export_rows[name] = hex(exports[name])

    imports = {}
    for directory in pe.DIRECTORY_ENTRY_IMPORT:
        dll = directory.dll.decode()
        for row in directory.imports:
            if row.name and row.name.decode() in REQUIRED_IMPORTS:
                imports[row.name.decode()] = {
                    "dll": dll,
                    "iat_rva": hex(row.address - pe.OPTIONAL_HEADER.ImageBase),
                }
    missing_imports = sorted(set(REQUIRED_IMPORTS) - set(imports))
    if missing_imports:
        raise ValueError(f"missing loader imports: {', '.join(missing_imports)}")

    functions = {name: _runtime_bounds(pe, rva) for name, rva in FUNCTION_PROBES.items()}
    if any(value is None for value in functions.values()):
        raise ValueError("one or more probe RVAs are absent from the PE exception table")

    native_helpers = {}
    for name, (rva, expected, abi) in NATIVE_HELPER_PROBES.items():
        offset = pe.get_offset_from_rva(rva)
        actual = raw[offset : offset + len(expected)]
        if actual != expected:
            raise ValueError(f"{name} helper prefix differs at {rva:#x}")
        native_helpers[name] = {
            "rva": hex(rva),
            "file_offset": hex(offset),
            "prefix": actual.hex(),
            "abi": abi,
        }

    return {
        "format_version": 1,
        "scope": "Static/offline exact-build hook inspection; no target execution or mutation.",
        "source": {"path": str(path), "sha256": digest, "size": len(raw)},
        "architecture": "AMD64 PE32+ / Windows x64 ABI",
        "direct_call_hooks": hooks,
        "replacement_hooks": replacement_hooks,
        "il2cpp_exports": export_rows,
        "loader_imports": imports,
        "runtime_function_entries": functions,
        "native_helper_probes": native_helpers,
        "conclusions": {
            "record_wrapper_abi": "At all six registration calls RCX is the component and EDX is zero MethodInfo. A wrapper can call the original first, read the component's virtual ID getter, then call the bridge while preserving nonvolatile registers and unwindability.",
            "initial_commit": "0x5eafe1 is after the occupable scan, generic scan, and SpaceGameManager initialization.",
            "save_commit": "0x6bec57 is the unique successful HousingNETGcloud.Send_SavePreset call after both saved-ground registration loops.",
            "load_commit": "0x6ca8dc begins the final completion delegate invocation after ValidateAllGroundAssetTriggers and the complete LightTrigger initialization loop. The original indirect delegate call must be emulated before bridge commit.",
            "dll_bootstrap": "Resolve an absolute sibling NebulaRegistryBridge.dll from GameAssembly's directory with GetModuleFileNameW and LoadLibraryExW; call no IL2CPP API from DllMain.",
            "component_enumeration": "Use non-generic GameObject.GetComponentsInternal at 0x1b87670 with the Component System.Type recovered from IL2CPP parent metadata and the exact eight-argument native ABI.",
            "rejected_generic_overload": "Do not use MethodInfo slot 0x252de38: runtime proved it resolves to a closed method at 0x877040 with an incompatible List<Component> return / IEnumerable RGCTX specialization.",
        },
        "rejected_shortcut": "Deterministic occupable IDs alone are unsafe: native receivers index the dense occupables list by ID, registration appends duplicates, and Occupable.Initialize emits opcode 8 immediately.",
        "target_executed": False,
        "input_modified": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-assembly", required=True, type=Path)
    parser.add_argument("--output", type=Path, help="optional new JSON report")
    args = parser.parse_args()
    source = args.game_assembly.resolve(strict=True)
    report = inspect(source)
    rendered = json.dumps(report, indent=2) + "\n"
    if args.output:
        output = args.output.resolve()
        if output.exists() or output == source or "steamapps" in [part.lower() for part in output.parts]:
            parser.error("--output must be a new file outside Steam")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
