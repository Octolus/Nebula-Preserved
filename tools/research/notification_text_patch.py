"""Prepare a new rapid+wardrobe client copy with a bounded notification-text fix.

This tool is execution-free: it parses and rewrites PE/COFF bytes only.  The
destination and JSON report must be new paths outside any Steam installation.
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

ROOT = workspace()
ASM = ROOT / "results/client-fixes/notification_text.s"
ASSEMBLY_SHA256 = "3c2ffe73d58a207bed0d829cada33eb468f6f34e7ba4f05efff36a6bbceb646d"
OBJECT_SHA256 = "9e65a06832343882297fee3763159d502e3eea330f7ea5252cfd8051479eacb7"
SOURCE_SHA256 = "ce1a74588e74499e282699e160b966439ffb4c278e8bcef791951e28a57b0dd0"
SECTION_SHA256 = {
    ".text": "8e8f0fece0578ff5fea7456f67728aaf5c0d540cd3b79c2b71c27aed0b2c5a77",
    ".xdata": "9166e32283e181556cc0566d1b0b42e86f1c601976e2244c8659e533a35705aa",
    ".pdata": "d2a32efaa7f7a503d8e876534fbe70d0f8117acd2d326268dd6a849832524217",
}
CALL_RVA = 0x477A02
CALL_BEFORE = bytes.fromhex("e8990bef00")
TARGETS = {
    "RewardLiteral": 0x24F7D08,
    "GiftPrefixLiteral": 0x2515838,
    "GiftSuffixLiteral": 0x2530B68,
    "StringConcat3": 0x1365160,
    "StringFormat4": 0x13685A0,
}
SHA = lambda data: hashlib.sha256(data).hexdigest()
ALIGN = lambda value, alignment: (value + alignment - 1) // alignment * alignment


def coff_sections(raw: bytes):
    machine, count, _, symoff, symcount, optional, _ = struct.unpack_from("<HHLLLHH", raw)
    if machine != 0x8664 or optional != 0:
        raise ValueError("Expected an AMD64 COFF object")
    strings = symoff + symcount * 18
    names = {}
    index = 0
    while index < symcount:
        at = symoff + index * 18
        name = raw[at:at + 8]
        if name[:4] == b"\0" * 4:
            start = strings + struct.unpack_from("<L", name, 4)[0]
            name = raw[start:raw.index(b"\0", start)]
        else:
            name = name.rstrip(b"\0")
        names[index] = name.decode("ascii")
        index += 1 + raw[at + 17]
    sections = {}
    for index in range(count):
        at = 20 + 40 * index
        name, _, _, size, offset, reloc, _, reloc_count, _, _ = struct.unpack_from("<8sLLLLLLHHL", raw, at)
        name = name.rstrip(b"\0").decode("ascii")
        rows = [struct.unpack_from("<LLH", raw, reloc + j * 10) for j in range(reloc_count)]
        sections[name] = (raw[offset:offset + size] if size else b"",
                          [(off, names[symbol], kind) for off, symbol, kind in rows])
    return sections


def unwind_summary(raw: bytes):
    version_flags, prologue, count, frame = struct.unpack_from("<BBBB", raw)
    if version_flags != 1 or frame != 0:
        raise ValueError("Unexpected unwind flags or frame pointer")
    entries = []
    registers = []
    stack = 0
    for index in range(count):
        offset, value = struct.unpack_from("<BB", raw, 4 + index * 2)
        operation, info = value & 15, value >> 4
        if operation == 0:
            registers.append(info); stack += 8
            entries.append({"offset": offset, "op": "push_nonvolatile", "register": info})
        elif operation == 2:
            size = info * 8 + 8; stack += size
            entries.append({"offset": offset, "op": "allocate_small", "bytes": size})
        else:
            raise ValueError("Unsupported generated unwind operation")
    if prologue != 11 or stack != 0x58 or sorted(registers) != [3, 6, 7, 12, 13]:
        raise ValueError("Unwind does not match five pushes plus 0x30 allocation")
    return {"version": 1, "flags": 0, "prologue_bytes": prologue,
            "total_stack_bytes_including_saved_registers": stack, "entries": entries}


def build(source: bytes, obj: bytes):
    if SHA(source) != SOURCE_SHA256:
        raise ValueError("Source must be the exact reviewed rapid+wardrobe private copy")
    if SHA(ASM.read_bytes()) != ASSEMBLY_SHA256 or SHA(obj) != OBJECT_SHA256:
        raise ValueError("Assembly or COFF object differs from the reviewed inputs")
    pe = pefile.PE(data=source, fast_load=True)
    pe.parse_data_directories(directories=[3])
    if pe.FILE_HEADER.Machine != 0x8664 or pe.OPTIONAL_HEADER.Magic != 0x20B:
        raise ValueError("Expected PE32+ AMD64")
    if pe.OPTIONAL_HEADER.DATA_DIRECTORY[4].Size or pe.get_overlay_data_start_offset() is not None:
        raise ValueError("Signed images and overlays are outside this patch policy")
    if not any(s.Name.rstrip(b"\0") == b".nbp" for s in pe.sections):
        raise ValueError("Reviewed rapid wrapper section is missing")
    call_offset = pe.get_offset_from_rva(CALL_RVA)
    if source[call_offset:call_offset + 5] != CALL_BEFORE:
        raise ValueError("Final notification String.Format call bytes do not match")

    sections = coff_sections(obj)
    if set(sections) != {".text", ".data", ".bss", ".xdata", ".pdata"}:
        raise ValueError("Unexpected COFF section set")
    if sections[".data"][0] or sections[".bss"][0] or sections[".xdata"][1]:
        raise ValueError("Unexpected generated data or unwind relocation")
    for name, digest in SECTION_SHA256.items():
        if SHA(sections[name][0]) != digest:
            raise ValueError(f"COFF {name} differs from reviewed wrapper")
    code = bytearray(sections[".text"][0])
    xdata = sections[".xdata"][0]
    start, end, unwind = struct.unpack("<LLL", sections[".pdata"][0])
    if (start, unwind) != (0, 0) or not 0 < end <= len(code):
        raise ValueError("Unexpected generated function extent")
    if sections[".pdata"][1] != [(0, ".text", 3), (4, ".text", 3), (8, ".xdata", 3)]:
        raise ValueError("Unexpected generated function-table relocations")
    unwind_info = unwind_summary(xdata)

    new_rva = ALIGN(max(s.VirtualAddress + max(s.Misc_VirtualSize, s.SizeOfRawData) for s in pe.sections),
                    pe.OPTIONAL_HEADER.SectionAlignment)
    expected_order = ["RewardLiteral", "GiftPrefixLiteral", "GiftSuffixLiteral", "StringConcat3", "StringFormat4"]
    if [x[1] for x in sections[".text"][1]] != expected_order:
        raise ValueError("Unexpected wrapper relocation sequence")
    relocations = []
    for off, symbol, kind in sections[".text"][1]:
        if kind != 4 or symbol not in TARGETS:
            raise ValueError("Only the reviewed RIP/rel32 relocations are allowed")
        addend = struct.unpack_from("<l", code, off)[0]
        if addend:
            raise ValueError("Unexpected COFF relocation addend")
        struct.pack_into("<l", code, off, TARGETS[symbol] - (new_rva + off + 4))
        relocations.append({"instruction_rva": hex(new_rva + off - 3 if symbol.endswith("Literal") else new_rva + off - 1),
                            "symbol": symbol, "target_rva": hex(TARGETS[symbol])})

    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64); md.detail = True
    instructions = list(md.disasm(code[:end], new_rva))
    if sum(x.size for x in instructions) != end or instructions[-1].mnemonic != "ret":
        raise ValueError("Generated code does not disassemble completely")
    boundaries = {x.address for x in instructions}
    for ins in instructions:
        if ins.mnemonic.startswith("j"):
            if not ins.operands or ins.operands[0].type != capstone.x86.X86_OP_IMM or ins.operands[0].imm not in boundaries:
                raise ValueError("Generated branch leaves the wrapper")
        for operand in ins.operands:
            if operand.type == capstone.x86.X86_OP_MEM and operand.mem.base == capstone.x86.X86_REG_RIP:
                target = ins.address + ins.size + operand.mem.disp
                if target not in TARGETS.values():
                    raise ValueError("Unexpected RIP-relative target")

    old_directory = pe.OPTIONAL_HEADER.DATA_DIRECTORY[3]
    original_rows = [(x.struct.BeginAddress, x.struct.EndAddress, x.struct.UnwindData)
                     for x in pe.DIRECTORY_ENTRY_EXCEPTION]
    if original_rows != sorted(original_rows) or any(a >= b for a, b, _ in original_rows):
        raise ValueError("Existing function table is not strictly bounded and sorted")
    unwind_at = ALIGN(len(code), 4)
    function_entry = (new_rva, new_rva + end, new_rva + unwind_at)
    rows = sorted(original_rows + [function_entry])
    table_at = ALIGN(unwind_at + len(xdata), 4)
    table = b"".join(struct.pack("<LLL", *row) for row in rows)
    blob = bytes(code).ljust(unwind_at, b"\0") + xdata
    blob = blob.ljust(table_at, b"\0") + table
    raw_at = ALIGN(len(source), pe.OPTIONAL_HEADER.FileAlignment)
    raw_size = ALIGN(len(blob), pe.OPTIONAL_HEADER.FileAlignment)
    header_at = pe.sections[-1].get_file_offset() + 40
    first_raw = min(s.PointerToRawData for s in pe.sections if s.PointerToRawData)
    if header_at + 40 > min(first_raw, pe.OPTIONAL_HEADER.SizeOfHeaders) or any(source[header_at:header_at + 40]):
        raise ValueError("No verified empty section-header slot")

    result = bytearray(source)
    struct.pack_into("<8sLLLLLLHHL", result, header_at, b".nbn\0\0\0\0", len(blob), new_rva,
                     raw_size, raw_at, 0, 0, 0, 0, 0x60000020)
    struct.pack_into("<H", result, pe.FILE_HEADER.get_field_absolute_offset("NumberOfSections"), pe.FILE_HEADER.NumberOfSections + 1)
    struct.pack_into("<L", result, pe.OPTIONAL_HEADER.get_field_absolute_offset("SizeOfCode"), pe.OPTIONAL_HEADER.SizeOfCode + raw_size)
    struct.pack_into("<L", result, pe.OPTIONAL_HEADER.get_field_absolute_offset("SizeOfImage"), ALIGN(new_rva + len(blob), pe.OPTIONAL_HEADER.SectionAlignment))
    struct.pack_into("<LL", result, old_directory.get_file_offset(), new_rva + table_at, len(table))
    replacement = b"\xe8" + struct.pack("<l", new_rva - (CALL_RVA + 5))
    result[call_offset:call_offset + 5] = replacement
    checksum_at = pe.OPTIONAL_HEADER.get_field_absolute_offset("CheckSum")
    struct.pack_into("<L", result, checksum_at, 0)
    result.extend(b"\0" * (raw_at - len(result)))
    result.extend(blob.ljust(raw_size, b"\0"))
    check = pefile.PE(data=bytes(result), fast_load=True)
    struct.pack_into("<L", result, checksum_at, check.generate_checksum())
    check = pefile.PE(data=bytes(result), fast_load=True); check.parse_data_directories(directories=[3])
    checked_rows = [(x.struct.BeginAddress, x.struct.EndAddress, x.struct.UnwindData) for x in check.DIRECTORY_ENTRY_EXCEPTION]
    if checked_rows != rows or original_rows != [x for x in checked_rows if x != function_entry]:
        raise ValueError("Existing runtime functions were not preserved exactly")

    allowed = set(range(header_at, header_at + 40)) | set(range(call_offset, call_offset + 5))
    for off, size in [(pe.FILE_HEADER.get_field_absolute_offset("NumberOfSections"), 2),
                      (pe.OPTIONAL_HEADER.get_field_absolute_offset("SizeOfCode"), 4),
                      (pe.OPTIONAL_HEADER.get_field_absolute_offset("SizeOfImage"), 4),
                      (checksum_at, 4), (old_directory.get_file_offset(), 8)]:
        allowed.update(range(off, off + size))
    changed = [i for i, (a, b) in enumerate(zip(source, result)) if a != b]
    if any(i not in allowed for i in changed):
        raise ValueError("Unexpected mutation of existing image bytes")
    spec = {
        "format_version": 1,
        "scope": "Exact-build private compatibility candidate; static and pure-authored-code validation only.",
        "source_sha256": SHA(source), "copy_sha256": SHA(result),
        "assembly_source_sha256": SHA(ASM.read_bytes()), "coff_sha256": SHA(obj),
        "target_executed": False, "network_used": False, "installation_changed": False,
        "redirect": {"call_rva": hex(CALL_RVA), "file_offset": hex(call_offset),
                     "original_hex": CALL_BEFORE.hex(), "replacement_hex": replacement.hex(),
                     "old_target_rva": hex(TARGETS["StringFormat4"]), "new_target_rva": hex(new_rva)},
        "new_section": {"name": ".nbn", "rva": hex(new_rva), "raw_offset": hex(raw_at),
                        "virtual_size": len(blob), "raw_size": raw_size, "code_bytes": end,
                        "characteristics": "read+execute; not writable"},
        "unwind": {**unwind_info, "rva": hex(new_rva + unwind_at), "hex": xdata.hex(),
                   "runtime_function": [hex(x) for x in function_entry],
                   "existing_entries_preserved": len(original_rows), "new_table_rva": hex(new_rva + table_at)},
        "native_relocations": relocations,
        "gate": {"body_nonnull_and_length_zero": True, "nullable_has_value": True,
                 "gift_type": 3, "reward_type": 4, "chat_entry_register_at_redirect": "rdi",
                 "gift_arguments_field": "ChatEntry+0x130"},
        "offline_checks": {"strict_rapid_input_hash": True, "all_code_disassembled": True,
                           "branches_remain_inside_wrapper": True, "only_reviewed_relocations": True,
                           "unwind_matches_prologue": True, "existing_runtime_functions_preserved": True,
                           "only_permitted_existing_bytes_changed": True},
        "limitations": [
            "The candidate has not run in Unity/IL2CPP; runtime rendering, GC behavior, and exception unwinding are untested.",
            "The compatibility step is limited to an empty final body for Gift(3) or Reward(4); nonempty bodies and all other types pass through unchanged.",
            "Static register evidence applies only to build 11018722 at redirect RVA 0x477A02.",
            "The wrapper reuses original IL2CPP literal slots and String.Concat/String.Format helpers for notification text; it adds no listener, attachment, identity, purchase, or security bypass.",
        ],
    }
    return bytes(result), spec


def safe_new_path(parser, path: Path, protected: set[Path], label: str, suffix: str | None = None):
    resolved = path.resolve()
    if resolved in protected or resolved.exists() or "steamapps" in [x.lower() for x in resolved.parts]:
        parser.error(f"{label} must be a new distinct path outside steamapps")
    if suffix and resolved.suffix.lower() != suffix:
        parser.error(f"{label} must use {suffix}")
    return resolved


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--object", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--spec", required=True, type=Path)
    args = parser.parse_args()
    source = args.source.resolve(strict=True); obj = args.object.resolve(strict=True)
    protected = {source, obj, ASM.resolve()}
    destination = safe_new_path(parser, args.destination, protected, "Destination")
    protected.add(destination)
    spec_path = safe_new_path(parser, args.spec, protected, "Specification", ".json")
    try:
        result, spec = build(source.read_bytes(), obj.read_bytes())
    except (ValueError, KeyError, struct.error) as error:
        parser.error(str(error))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as stream:
        stream.write(result)
    spec["copy_written"] = True; spec["copy_path"] = str(destination)
    spec["native_sources"] = []
    for relative in ["work/evidence/ghidra/functions/477470.c", "work/evidence/ghidra/functions/610d40.c", "work/decompiled/dump.cs"]:
        path = ROOT / relative
        spec["native_sources"].append({"path": relative, "sha256": SHA(path.read_bytes())})
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    with spec_path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(spec, indent=2) + "\n")
    print(json.dumps({"copy": str(destination), "copy_sha256": spec["copy_sha256"],
                      "spec": str(spec_path), "target_executed": False}))


if __name__ == "__main__":
    main()
