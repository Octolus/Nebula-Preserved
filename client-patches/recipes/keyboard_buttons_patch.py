"""Create a new exact-build GameAssembly copy with PadPS4 keyboard fallbacks.

The tool only parses and authors PE/COFF bytes. It never loads the DLL or
starts the game. Both output paths must be new, distinct, and outside Steam.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct

import capstone
import pefile

ROOT = Path(__file__).resolve().parents[1]
ASM = ROOT / "shims/keyboard_buttons.s"
SOURCE_SHA256 = "13158d2f08c9511c9cc283a6dda680081c5e1f6142bb86ddde1bfbd039de7fcb"
ASSEMBLY_SHA256 = "009c99a34f9114bc95db0eccafa0e4f8e4034368d986589e202f59afb3be0f48"
OBJECT_SHA256 = "d6fc963f20d236473ce8d60b5e2e2cac257086e195e8d9303907eae578bbcf93"
SECTION_SHA256 = {
    ".text": "ad93935f9d5d059f0c3fdf6e5d7aaf28700b1ddf343a1089a8ad2ff220e2468a",
    ".xdata": "a27f44b27519151a9a34a8157561b155bc9d35bf117a94880f64d31629fd1c87",
    ".pdata": "20a0180b2a89d9bd2e5c620b00e9bd4da5fc0c260b865fa0650bcbe3db3e932c",
}
BUTTONS = {
    "Cross": {"rva": 0x6A8F40, "key": "E", "keycode": 101},
    "Circle": {"rva": 0x6A8E20, "key": "Escape", "keycode": 27},
    "Square": {"rva": 0x6A9B20, "key": "Tab", "keycode": 9},
    "Triangle": {"rva": 0x6A9BD0, "key": "F", "keycode": 102},
    "L1": {"rva": 0x6A9400, "key": "Q", "keycode": 113},
    "R1": {"rva": 0x6A9760, "key": "R", "keycode": 114},
    "L3": {"rva": 0x6A9520, "key": "LeftShift", "keycode": 304},
    "R3": {"rva": 0x6A98C0, "key": "C", "keycode": 99},
    "Share": {"rva": 0x6A9A70, "key": "P", "keycode": 112},
    "Options": {"rva": 0x6A96B0, "key": "M", "keycode": 109},
}
EXTERNALS = {"UnityGetKeyDownInt": 0x1BD8730, "UnityGetKeyInt": 0x1BD8770}
EXTERNALS.update({"Original" + name + "Continue": row["rva"] + 5 for name, row in BUTTONS.items()})
STOLEN = bytes.fromhex("48895c2408")
SHA = lambda data: hashlib.sha256(data).hexdigest()
ALIGN = lambda value, alignment: (value + alignment - 1) // alignment * alignment


def coff(raw: bytes):
    machine, count, _, symoff, symcount, optional, _ = struct.unpack_from("<HHLLLHH", raw)
    if machine != 0x8664 or optional != 0:
        raise ValueError("Expected an AMD64 COFF object")
    strings = symoff + symcount * 18
    symbols = {}; names = {}; index = 0
    while index < symcount:
        at = symoff + index * 18; raw_name = raw[at:at + 8]
        if raw_name[:4] == b"\0" * 4:
            start = strings + struct.unpack_from("<L", raw_name, 4)[0]
            name = raw[start:raw.index(b"\0", start)].decode("ascii")
        else:
            name = raw_name.rstrip(b"\0").decode("ascii")
        value, section, typ, storage, aux = struct.unpack_from("<LhHBB", raw, at + 8)
        names[index] = name; symbols[name] = {"value": value, "section": section, "type": typ, "storage": storage}
        index += 1 + aux
    sections = {}
    for index in range(count):
        at = 20 + 40 * index
        name, _, _, size, offset, reloc, _, reloc_count, _, _ = struct.unpack_from("<8sLLLLLLHHL", raw, at)
        name = name.rstrip(b"\0").decode("ascii")
        rows = []
        for j in range(reloc_count):
            off, symbol, kind = struct.unpack_from("<LLH", raw, reloc + j * 10)
            rows.append((off, names[symbol], kind))
        sections[name] = (raw[offset:offset + size] if size else b"", rows)
    return sections, symbols


def unwind_summary(raw: bytes):
    version_flags, prologue, count, frame = struct.unpack_from("<BBBB", raw)
    if version_flags != 1 or frame != 0:
        raise ValueError("Unexpected unwind version, flags, or frame")
    stack = 0; registers = []; entries = []
    for index in range(count):
        offset, value = struct.unpack_from("<BB", raw, 4 + index * 2)
        operation, info = value & 15, value >> 4
        if operation == 0:
            stack += 8; registers.append(info)
            entries.append({"offset": offset, "op": "push_nonvolatile", "register": info})
        elif operation == 2:
            size = info * 8 + 8; stack += size
            entries.append({"offset": offset, "op": "allocate_small", "bytes": size})
        else:
            raise ValueError("Unsupported authored unwind operation")
    if prologue != 7 or stack != 0x48 or sorted(registers) != [3, 6, 7]:
        raise ValueError("Unwind does not match three pushes plus 0x30 allocation")
    return {"version": 1, "flags": 0, "prologue_bytes": prologue,
            "total_stack_bytes_including_saved_registers": stack, "entries": entries}


def build(source: bytes, obj: bytes):
    if SHA(source) != SOURCE_SHA256:
        raise ValueError("Source must be the exact reviewed notification+rapid+wardrobe private copy")
    if SHA(ASM.read_bytes()) != ASSEMBLY_SHA256 or SHA(obj) != OBJECT_SHA256:
        raise ValueError("Assembly or COFF object differs from the reviewed inputs")
    pe = pefile.PE(data=source, fast_load=True); pe.parse_data_directories(directories=[3])
    if pe.FILE_HEADER.Machine != 0x8664 or pe.OPTIONAL_HEADER.Magic != 0x20B:
        raise ValueError("Expected PE32+ AMD64")
    if pe.OPTIONAL_HEADER.DATA_DIRECTORY[4].Size or pe.get_overlay_data_start_offset() is not None:
        raise ValueError("Signed images and overlays are outside this patch policy")
    names = [s.Name.decode("ascii", "replace").rstrip(chr(0)) for s in pe.sections]
    if names[-2:] != [".nbp", ".nbn"]:
        raise ValueError("Prior rapid and notification sections are not both preserved")

    sections, symbols = coff(obj)
    if set(sections) != {".text", ".data", ".bss", ".xdata", ".pdata"}:
        raise ValueError("Unexpected COFF section set")
    if sections[".data"][0] or sections[".bss"][0] or sections[".xdata"][1]:
        raise ValueError("Unexpected generated data or unwind relocation")
    for name, digest in SECTION_SHA256.items():
        if SHA(sections[name][0]) != digest:
            raise ValueError(f"COFF {name} differs from reviewed wrapper")
    code = bytearray(sections[".text"][0]); xdata = sections[".xdata"][0]
    start, end, unwind = struct.unpack("<LLL", sections[".pdata"][0])
    if (start, end, unwind) != (0xA0, 0xFC, 0):
        raise ValueError("Unexpected common-wrapper function extent")
    if sections[".pdata"][1] != [(0, ".text", 3), (4, ".text", 3), (8, ".xdata", 3)]:
        raise ValueError("Unexpected authored function-table relocations")
    unwind_info = unwind_summary(xdata)
    stub_offsets = {}
    for name in BUTTONS:
        symbol = symbols.get("Keyboard" + name)
        if not symbol or symbol["section"] != 1:
            raise ValueError(f"Missing authored Keyboard{name} stub")
        stub_offsets[name] = symbol["value"]

    new_rva = ALIGN(max(s.VirtualAddress + max(s.Misc_VirtualSize, s.SizeOfRawData) for s in pe.sections),
                    pe.OPTIONAL_HEADER.SectionAlignment)
    expected_relocations = ["UnityGetKeyDownInt", "UnityGetKeyInt"] + ["Original" + name + "Continue" for name in BUTTONS]
    if [row[1] for row in sections[".text"][1]] != expected_relocations:
        raise ValueError("Unexpected authored relocation order")
    relocations = []
    for off, symbol, kind in sections[".text"][1]:
        if kind != 4 or symbol not in EXTERNALS or struct.unpack_from("<l", code, off)[0] != 0:
            raise ValueError("Only reviewed zero-addend rel32 relocations are allowed")
        struct.pack_into("<l", code, off, EXTERNALS[symbol] - (new_rva + off + 4))
        relocations.append({"instruction_rva": hex(new_rva + off - 1), "symbol": symbol,
                            "target_rva": hex(EXTERNALS[symbol])})

    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64); md.detail = True
    instructions = list(md.disasm(code, new_rva))
    if sum(x.size for x in instructions) != len(code):
        raise ValueError("Authored code does not disassemble completely")
    boundaries = {x.address for x in instructions}
    external_targets = set(EXTERNALS.values())
    for ins in instructions:
        if ins.mnemonic.startswith("j") and ins.operands and ins.operands[0].type == capstone.x86.X86_OP_IMM:
            if ins.operands[0].imm not in boundaries | external_targets:
                raise ValueError("Authored jump has an unexpected target")
        for operand in ins.operands:
            if operand.type == capstone.x86.X86_OP_MEM and operand.mem.base == capstone.x86.X86_REG_RIP:
                target = ins.address + ins.size + operand.mem.disp
                if target not in boundaries:
                    raise ValueError("Unexpected external RIP-relative data dependency")

    original_rows = [(x.struct.BeginAddress, x.struct.EndAddress, x.struct.UnwindData)
                     for x in pe.DIRECTORY_ENTRY_EXCEPTION]
    if original_rows != sorted(original_rows) or any(a >= b for a, b, _ in original_rows):
        raise ValueError("Existing runtime-function table is invalid")
    redirects = []
    for name, row in BUTTONS.items():
        rva = row["rva"]; offset = pe.get_offset_from_rva(rva)
        if source[offset:offset + 5] != STOLEN:
            raise ValueError(f"{name} entry does not match the reviewed five-byte prologue")
        owner = [entry for entry in original_rows if entry[0] == rva and rva + 5 < entry[1]]
        if len(owner) != 1:
            raise ValueError(f"{name} runtime-function extent was not established")
        destination = new_rva + stub_offsets[name]
        replacement = b"\xe9" + struct.pack("<l", destination - (rva + 5))
        redirects.append({"name": name, "entry_rva": hex(rva), "file_offset": hex(offset),
                          "original_hex": STOLEN.hex(), "replacement_hex": replacement.hex(),
                          "stub_rva": hex(destination), "original_continue_rva": hex(rva + 5),
                          "key": row["key"], "keycode": row["keycode"], "owner_runtime_function": [hex(x) for x in owner[0]]})

    unwind_at = ALIGN(len(code), 4)
    function_entry = (new_rva + start, new_rva + end, new_rva + unwind_at)
    rows = sorted(original_rows + [function_entry])
    table_at = ALIGN(unwind_at + len(xdata), 4)
    table = b"".join(struct.pack("<LLL", *row) for row in rows)
    blob = bytes(code).ljust(unwind_at, b"\0") + xdata
    blob = blob.ljust(table_at, b"\0") + table
    raw_at = ALIGN(len(source), pe.OPTIONAL_HEADER.FileAlignment); raw_size = ALIGN(len(blob), pe.OPTIONAL_HEADER.FileAlignment)
    header_at = pe.sections[-1].get_file_offset() + 40
    first_raw = min(s.PointerToRawData for s in pe.sections if s.PointerToRawData)
    if header_at + 40 > min(first_raw, pe.OPTIONAL_HEADER.SizeOfHeaders) or any(source[header_at:header_at + 40]):
        raise ValueError("No verified empty section-header slot")

    result = bytearray(source)
    struct.pack_into("<8sLLLLLLHHL", result, header_at, b".nbk\0\0\0\0", len(blob), new_rva,
                     raw_size, raw_at, 0, 0, 0, 0, 0x60000020)
    struct.pack_into("<H", result, pe.FILE_HEADER.get_field_absolute_offset("NumberOfSections"), pe.FILE_HEADER.NumberOfSections + 1)
    struct.pack_into("<L", result, pe.OPTIONAL_HEADER.get_field_absolute_offset("SizeOfCode"), pe.OPTIONAL_HEADER.SizeOfCode + raw_size)
    struct.pack_into("<L", result, pe.OPTIONAL_HEADER.get_field_absolute_offset("SizeOfImage"), ALIGN(new_rva + len(blob), pe.OPTIONAL_HEADER.SectionAlignment))
    directory = pe.OPTIONAL_HEADER.DATA_DIRECTORY[3]
    struct.pack_into("<LL", result, directory.get_file_offset(), new_rva + table_at, len(table))
    for item in redirects:
        offset = int(item["file_offset"], 16)
        result[offset:offset + 5] = bytes.fromhex(item["replacement_hex"])
    checksum_at = pe.OPTIONAL_HEADER.get_field_absolute_offset("CheckSum")
    struct.pack_into("<L", result, checksum_at, 0)
    result.extend(b"\0" * (raw_at - len(result))); result.extend(blob.ljust(raw_size, b"\0"))
    reparsed = pefile.PE(data=bytes(result), fast_load=True)
    struct.pack_into("<L", result, checksum_at, reparsed.generate_checksum())
    reparsed = pefile.PE(data=bytes(result), fast_load=True); reparsed.parse_data_directories(directories=[3])
    checked_rows = [(x.struct.BeginAddress, x.struct.EndAddress, x.struct.UnwindData) for x in reparsed.DIRECTORY_ENTRY_EXCEPTION]
    if checked_rows != rows or set(original_rows) != set(checked_rows) - {function_entry}:
        raise ValueError("Existing runtime-function records were not preserved exactly")

    allowed = set(range(header_at, header_at + 40))
    for item in redirects:
        offset = int(item["file_offset"], 16); allowed.update(range(offset, offset + 5))
    for off, size in [(pe.FILE_HEADER.get_field_absolute_offset("NumberOfSections"), 2),
                      (pe.OPTIONAL_HEADER.get_field_absolute_offset("SizeOfCode"), 4),
                      (pe.OPTIONAL_HEADER.get_field_absolute_offset("SizeOfImage"), 4),
                      (checksum_at, 4), (directory.get_file_offset(), 8)]:
        allowed.update(range(off, off + size))
    changed = [index for index, (before, after) in enumerate(zip(source, result)) if before != after]
    if any(index not in allowed for index in changed):
        raise ValueError("Unexpected mutation of existing image bytes")
    manifest = {
        "format_version": 1,
        "kind": "prepared_keyboard_buttons_gameassembly_copy",
        "scope": "Exact-build controller-first PadPS4 keyboard fallback; static/offline validation only.",
        "source_sha256": SHA(source), "copy_sha256": SHA(result),
        "assembly_source_sha256": SHA(ASM.read_bytes()), "coff_sha256": SHA(obj),
        "target_executed": False, "network_used": False, "installation_changed": False,
        "redirects": redirects,
        "new_section": {"name": ".nbk", "rva": hex(new_rva), "raw_offset": hex(raw_at),
                        "virtual_size": len(blob), "raw_size": raw_size, "code_bytes": len(code),
                        "characteristics": "read+execute; not writable"},
        "unwind": {**unwind_info, "rva": hex(new_rva + unwind_at), "hex": xdata.hex(),
                   "runtime_function": [hex(x) for x in function_entry],
                   "existing_entries_preserved": len(original_rows), "new_table_rva": hex(new_rva + table_at)},
        "native_relocations": relocations,
        "policy": {"original_method_called_first": True, "original_true_returns_true_without_keyboard": True,
                   "keyboard_requires_original_false": True, "keyboard_requires_isBlockedControls_false": True,
                   "reset_true_helper": "UnityEngine.Input.GetKeyDownInt",
                   "reset_false_helper": "UnityEngine.Input.GetKeyInt",
                   "helper_method_info": "null"},
        "offline_checks": {"strict_input_hash": True, "all_ten_stolen_prologues_exact": True,
                           "all_original_function_extents_established": True, "all_authored_code_disassembled": True,
                           "only_reviewed_relocations": True, "unwind_matches_common_prologue": True,
                           "existing_runtime_functions_preserved": True, "prior_sections_preserved": [".nbp", ".nbn"],
                           "only_permitted_existing_bytes_changed": True},
        "limitations": [
            "The candidate has not run in Unity/IL2CPP; physical controller and keyboard behavior are not runtime-tested.",
            "Windows exception dispatch through the entry stubs, trampolines, and generated unwind metadata is untested.",
            "The fallback is limited to the ten listed PadPS4 button methods and does not synthesize controller state.",
            "No game UI, listener, attachment, input injection, identity check, purchase check, or security check is changed.",
        ],
    }
    return bytes(result), manifest


def new_path(parser, path: Path, protected: set[Path], label: str, suffix=None):
    resolved = path.resolve()
    if resolved in protected or resolved.exists() or "steamapps" in [part.lower() for part in resolved.parts]:
        parser.error(f"{label} must be a new distinct path outside steamapps")
    if suffix and resolved.suffix.lower() != suffix:
        parser.error(f"{label} must use {suffix}")
    return resolved


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--object", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args(); source = args.source.resolve(strict=True); obj = args.object.resolve(strict=True)
    protected = {source, obj, ASM.resolve()}
    destination = new_path(parser, args.destination, protected, "Destination"); protected.add(destination)
    manifest_path = new_path(parser, args.manifest, protected, "Manifest", ".json")
    try:
        output, manifest = build(source.read_bytes(), obj.read_bytes())
    except (ValueError, KeyError, struct.error) as error:
        parser.error(str(error))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as stream: stream.write(output)
    manifest["copy_path"] = str(destination); manifest["copy_written"] = True
    manifest["native_sources"] = []
    evidence_names = [f"local-analysis-not-in-repository/functions/{row['rva']:x}.c" for row in BUTTONS.values()]
    evidence_names += ["local-analysis-not-in-repository/functions/1bd8730.c", "local-analysis-not-in-repository/functions/1bd8770.c", "local-analysis-not-in-repository/dump.cs"]
    for relative in evidence_names:
        path = ROOT / relative
        manifest["native_sources"].append({"path": relative, "available": path.is_file(), "sha256": SHA(path.read_bytes()) if path.is_file() else None})
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("x", encoding="utf-8") as stream: stream.write(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"copy": str(destination), "copy_sha256": manifest["copy_sha256"],
                      "manifest": str(manifest_path), "target_executed": False}))


if __name__ == "__main__": main()
