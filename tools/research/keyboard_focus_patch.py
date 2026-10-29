"""Prepare a new exact-build GameAssembly copy with F8 as the L3 fallback.

This is a static PE edit only.  It changes the existing .nbk L3 key-code
immediate from LeftShift (304) to F8 (289), recomputes the PE checksum, and
refuses existing, aliased, or Steam destinations.
"""
from __future__ import annotations

from _research_paths import workspace, output_root, game_path

import argparse
import hashlib
import json
from pathlib import Path
import struct

import capstone
import pefile
import UnityPy


BASELINE_SHA256 = "3ddc1eb903eda90be06cc7079e2afa584d250b4430455b86564150fa05949703"
ORIGINAL_NATIVE_SHA256 = "c4dd5db599e5e5ce4adf25f09ffe70ad10e0928adf6a2e862176d537026b44ac"
INPUT_MANAGER_SHA256 = "70a141380052f0c2eb0d64c8bad71961648fe9791d79a6b2da37924b9bff4775"
IMAGE_BASE = 0x180000000
L3_STUB_RVA = 0x2E3D05D
L3_ENTRY_RVA = 0x6A9520
OLD_INSTRUCTION = bytes.fromhex("41ba30010000")  # mov r10d, 304
NEW_INSTRUCTION = bytes.fromhex("41ba21010000")  # mov r10d, 289
KEY_HELPERS = {0x1BD8730: "GetKeyDownInt", 0x1BD8770: "GetKeyInt"}
BUTTONS = {
    "Cross": (0x6A8F40, 0x2E3D000, 101), "Circle": (0x6A8E20, 0x2E3D012, 27),
    "Square": (0x6A9B20, 0x2E3D021, 9), "Triangle": (0x6A9BD0, 0x2E3D030, 102),
    "L1": (0x6A9400, 0x2E3D03F, 113), "R1": (0x6A9760, 0x2E3D04E, 114),
    "L3": (L3_ENTRY_RVA, L3_STUB_RVA, 304), "R3": (0x6A98C0, 0x2E3D06C, 99),
    "Share": (0x6A9A70, 0x2E3D07B, 112), "Options": (0x6A96B0, 0x2E3D08A, 109),
}
SHA = lambda data: hashlib.sha256(data).hexdigest()


def _pe(raw: bytes, exceptions: bool = False):
    pe = pefile.PE(data=raw, fast_load=True)
    if exceptions:
        pe.parse_data_directories(directories=[3])
    if pe.FILE_HEADER.Machine != 0x8664 or pe.OPTIONAL_HEADER.Magic != 0x20B:
        raise ValueError("Expected an AMD64 PE32+ image")
    return pe


def _runtime_rows(pe):
    return [(x.struct.BeginAddress, x.struct.EndAddress, x.struct.UnwindData)
            for x in pe.DIRECTORY_ENTRY_EXCEPTION]


def _stub_keycodes(raw: bytes, pe):
    result = {}
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    for name, (_, rva, _) in BUTTONS.items():
        offset = pe.get_offset_from_rva(rva)
        instructions = list(md.disasm(raw[offset:offset + 6], IMAGE_BASE + rva))
        if len(instructions) != 1 or instructions[0].mnemonic != "mov" or not instructions[0].op_str.startswith("r10d, "):
            raise ValueError(f"{name} stub no longer begins with the reviewed key-code load")
        result[name] = int(instructions[0].op_str.split(", ", 1)[1], 0)
    return result


def _redirects(raw: bytes, pe):
    rows = {}
    for name, (entry, stub, _) in BUTTONS.items():
        offset = pe.get_offset_from_rva(entry)
        actual = raw[offset:offset + 5]
        expected = b"\xe9" + struct.pack("<l", stub - (entry + 5))
        if actual != expected:
            raise ValueError(f"{name} entry redirect differs from the reviewed .nbk copy")
        rows[name] = {"entry_rva": hex(entry), "stub_rva": hex(stub), "bytes": actual.hex()}
    return rows


def scan_native_f8_reservation(raw: bytes):
    """Bounded scan of direct native calls to the two Unity integer key helpers."""
    if SHA(raw) != ORIGINAL_NATIVE_SHA256:
        raise ValueError("Original native evidence SHA256 differs from the reviewed build")
    pe = _pe(raw)
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64); md.detail = True
    calls = []
    for section in pe.sections:
        if not section.Characteristics & 0x20000000:
            continue
        block = raw[section.PointerToRawData:section.PointerToRawData + section.SizeOfRawData]
        instructions = list(md.disasm(block, section.VirtualAddress))
        for index, ins in enumerate(instructions):
            if (ins.mnemonic != "call" or not ins.operands or
                    ins.operands[0].type != capstone.x86.X86_OP_IMM or
                    ins.operands[0].imm not in KEY_HELPERS):
                continue
            immediate = None
            for prior in reversed(instructions[max(0, index - 12):index]):
                if prior.mnemonic.startswith("j") or prior.mnemonic in {"call", "ret"}:
                    break
                operands = prior.operands
                if (prior.mnemonic == "mov" and len(operands) == 2 and
                        operands[0].type == capstone.x86.X86_OP_REG and
                        operands[0].reg in {capstone.x86.X86_REG_ECX, capstone.x86.X86_REG_RCX} and
                        operands[1].type == capstone.x86.X86_OP_IMM):
                    immediate = operands[1].imm
                    break
            calls.append({"call_rva": hex(ins.address), "helper": KEY_HELPERS[ins.operands[0].imm],
                          "recovered_ecx_immediate": immediate})
    if any(row["recovered_ecx_immediate"] == 289 for row in calls):
        raise ValueError("F8 is already used by a recovered direct native integer-key call")
    return calls


def scan_input_manager_f8(raw: bytes):
    if SHA(raw) != INPUT_MANAGER_SHA256:
        raise ValueError("InputManager evidence SHA256 differs from the reviewed installed copy")
    env = UnityPy.load(raw)
    managers = [obj for obj in env.objects if obj.type.name == "InputManager"]
    if len(managers) != 1:
        raise ValueError("Expected exactly one serialized InputManager")
    axes = managers[0].read_typetree()["m_Axes"]
    fields = ("m_Name", "descriptiveName", "descriptiveNegativeName", "negativeButton",
              "positiveButton", "altNegativeButton", "altPositiveButton")
    hits = [{"axis": index, "field": field, "value": axis.get(field)}
            for index, axis in enumerate(axes) for field in fields
            if isinstance(axis.get(field), str) and "f8" in axis[field].lower()]
    if hits:
        raise ValueError("F8 is already present in a serialized InputManager binding")
    return len(axes), hits


def build(source: bytes, original_native: bytes, input_manager: bytes):
    if SHA(source) != BASELINE_SHA256:
        raise ValueError("Source must be the exact reviewed keyboard-buttons private copy")
    before_pe = _pe(source, exceptions=True)
    names = [s.Name.rstrip(b"\0").decode("ascii") for s in before_pe.sections]
    if names[-1:] != [".nbk"]:
        raise ValueError("Reviewed .nbk section is not the final PE section")
    l3_offset = before_pe.get_offset_from_rva(L3_STUB_RVA)
    if source[l3_offset:l3_offset + len(OLD_INSTRUCTION)] != OLD_INSTRUCTION:
        raise ValueError("L3 stub does not contain the reviewed LeftShift immediate")
    keys_before = _stub_keycodes(source, before_pe)
    if keys_before != {name: row[2] for name, row in BUTTONS.items()}:
        raise ValueError("One or more keyboard fallback key codes differ from the reviewed copy")
    redirects_before = _redirects(source, before_pe)
    runtime_before = _runtime_rows(before_pe)
    section_headers_before = [bytes(s.__pack__()) for s in before_pe.sections]
    exception_directory_before = bytes(source[
        before_pe.get_offset_from_rva(before_pe.OPTIONAL_HEADER.DATA_DIRECTORY[3].VirtualAddress):
        before_pe.get_offset_from_rva(before_pe.OPTIONAL_HEADER.DATA_DIRECTORY[3].VirtualAddress) +
        before_pe.OPTIONAL_HEADER.DATA_DIRECTORY[3].Size])

    direct_calls = scan_native_f8_reservation(original_native)
    axis_count, input_hits = scan_input_manager_f8(input_manager)

    result = bytearray(source)
    result[l3_offset:l3_offset + len(NEW_INSTRUCTION)] = NEW_INSTRUCTION
    checksum_at = before_pe.OPTIONAL_HEADER.get_field_absolute_offset("CheckSum")
    struct.pack_into("<L", result, checksum_at, 0)
    checksum = pefile.PE(data=bytes(result), fast_load=True).generate_checksum()
    struct.pack_into("<L", result, checksum_at, checksum)

    after_pe = _pe(bytes(result), exceptions=True)
    keys_after = _stub_keycodes(bytes(result), after_pe)
    expected_after = dict(keys_before); expected_after["L3"] = 289
    if keys_after != expected_after:
        raise ValueError("The output changed a fallback other than L3 or did not select F8")
    if _redirects(bytes(result), after_pe) != redirects_before:
        raise ValueError("An existing button entry redirect changed")
    if _runtime_rows(after_pe) != runtime_before:
        raise ValueError("PE runtime-function records changed")
    if [bytes(s.__pack__()) for s in after_pe.sections] != section_headers_before:
        raise ValueError("PE section headers changed")
    exception_at = after_pe.get_offset_from_rva(after_pe.OPTIONAL_HEADER.DATA_DIRECTORY[3].VirtualAddress)
    exception_after = bytes(result[exception_at:exception_at + after_pe.OPTIONAL_HEADER.DATA_DIRECTORY[3].Size])
    if exception_after != exception_directory_before:
        raise ValueError("PE exception-directory bytes changed")

    allowed = set(range(l3_offset, l3_offset + len(OLD_INSTRUCTION))) | set(range(checksum_at, checksum_at + 4))
    changed = [i for i, (a, b) in enumerate(zip(source, result)) if a != b]
    if not changed or any(i not in allowed for i in changed):
        raise ValueError("Output contains a mutation outside L3's immediate and the PE checksum")
    semantic = [i for i in changed if i not in range(checksum_at, checksum_at + 4)]
    if semantic != [l3_offset + 2]:
        raise ValueError("Expected exactly the low immediate byte to change from 0x30 to 0x21")

    manifest = {
        "format_version": 1,
        "kind": "prepared_keyboard_focus_f8_gameassembly_copy",
        "scope": "Exact-build, controller-first L3 keyboard fallback remap from LeftShift to F8.",
        "source_sha256": SHA(source), "copy_sha256": SHA(result),
        "target_executed": False, "network_used": False, "installation_changed": False,
        "edit": {"entry_rva": hex(L3_ENTRY_RVA), "stub_rva": hex(L3_STUB_RVA),
                 "file_offset": hex(l3_offset), "instruction_before": OLD_INSTRUCTION.hex(),
                 "instruction_after": NEW_INSTRUCTION.hex(), "key_before": "LeftShift",
                 "keycode_before": 304, "key_after": "F8", "keycode_after": 289,
                 "semantic_changed_file_offsets": [hex(i) for i in semantic]},
        "pe_checksum": {"file_offset": hex(checksum_at), "before": hex(before_pe.OPTIONAL_HEADER.CheckSum),
                        "after": hex(checksum)},
        "preservation": {"all_ten_entry_redirects_unchanged": True,
                         "other_nine_fallback_keycodes_unchanged": True,
                         "section_headers_unchanged": True, "exception_directory_bytes_unchanged": True,
                         "runtime_function_records_unchanged": len(runtime_before),
                         "only_l3_immediate_and_checksum_changed": True},
        "policy": {"original_PadPS4_L3_method_still_called_first": True,
                   "original_true_still_returns_true_without_keyboard": True,
                   "existing_isBlockedControls_guard_preserved": True,
                   "reset_true_still_uses_GetKeyDownInt": True,
                   "reset_false_still_uses_GetKeyInt": True,
                   "physical_PS4_L3_behavior_changed": False,
                   "keyboard_LeftShift_fallback_replaced_by_F8": True},
        "bounded_f8_reservation_evidence": {
            "original_native_sha256": SHA(original_native),
            "direct_integer_key_helper_calls": direct_calls,
            "recovered_immediates": sorted({row["recovered_ecx_immediate"] for row in direct_calls
                                            if row["recovered_ecx_immediate"] is not None}),
            "f8_immediate_289_found": False,
            "input_manager_sha256": SHA(input_manager), "input_manager_axis_count": axis_count,
            "serialized_f8_bindings": input_hits,
            "limit": "This proves no F8 in the reviewed serialized bindings or recovered immediate arguments at direct native calls to GetKeyInt/GetKeyDownInt; it is not an exhaustive proof over indirect/reflection input consumers."
        },
        "limitations": [
            "The F8 mapping is a deliberate keyboard compatibility addition, not a claim about an original game defect.",
            "The candidate has not run in Unity/IL2CPP and F8 has not yet been pressed in the game.",
            "LeftShift is no longer the keyboard L3 fallback in this copy; physical PS4 L3 remains controller-first and unchanged.",
            "Windows exception dispatch through the pre-existing .nbk wrapper and unwind metadata was not stress-tested by this edit.",
        ],
    }
    return bytes(result), manifest


def _new_path(parser, value: Path, protected: set[Path], label: str, suffix: str | None = None):
    path = value.resolve()
    if path in protected or path.exists() or "steamapps" in {part.lower() for part in path.parts}:
        parser.error(f"{label} must be a new distinct path outside steamapps")
    if suffix and path.suffix.lower() != suffix:
        parser.error(f"{label} must use {suffix}")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--original-native", required=True, type=Path)
    parser.add_argument("--input-manager", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    original = args.original_native.resolve(strict=True)
    manager = args.input_manager.resolve(strict=True)
    protected = {source, original, manager, Path(__file__).resolve()}
    destination = _new_path(parser, args.destination, protected, "Destination", ".dll")
    protected.add(destination)
    manifest_path = _new_path(parser, args.manifest, protected, "Manifest", ".json")
    try:
        output, manifest = build(source.read_bytes(), original.read_bytes(), manager.read_bytes())
    except (ValueError, KeyError, struct.error) as error:
        parser.error(str(error))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as stream:
        stream.write(output)
    manifest.update({"copy_path": str(destination), "copy_written": True,
                     "manifest_path": str(manifest_path)})
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, indent=2); stream.write("\n")
    print(json.dumps({"copy": str(destination), "copy_sha256": manifest["copy_sha256"],
                      "manifest": str(manifest_path), "target_executed": False}))


if __name__ == "__main__":
    main()
