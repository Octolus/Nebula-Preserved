"""Prepare a new exact-build GameAssembly copy with a bounded rapid-exit report.

Never loads a DLL or starts a target. Default produces only a JSON specification.
--destination is optional and must name a new file outside the Steam install.
Compile the companion assembly with MinGW GCC before passing --object.
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
ASM = ROOT / "results/client-fixes/rapid_boat_exit.s"
ASSEMBLY_SHA256 = "b7a5d05492b108785573fb258ddb9728f81c9a396aa49fc6b966c9b141eaec66"
SECTION_SHA256 = {".text": "8855c6f62ece9558f5c3abeaa4101c3a04e9b58b59f1294051dbd4ffbc355eff",
                  ".xdata": "355f3c85099968d9aae46accfa9c3ab6a5c28a1eedb2b694cafa94016adebf49",
                  ".pdata": "191e1a08f692eb51aa55ede38bf67ed4560821f046f8f17e439f10d9f07b500c"}
ACCEPTED = {
    "c4dd5db599e5e5ce4adf25f09ffe70ad10e0928adf6a2e862176d537026b44ac": "original Steam build11018722",
    "29abe9dbf4f310ba72b4de19273da85c797e529fac6511ba40bb9f88314dc420": "same build with reviewed wardrobe loop fix only",
}
TARGETS = {"ManagerSingleton": 0x43CDF0, "OriginalExit": 0x545920,
           "TcpIsConnected": 0x5E79F0, "InfoSingleton": 0x423490,
           "StringNewUtf16": 0x2B11A0, "TcpSend": 0x5E7820}
CALL_RVA = 0x44C1CE
SHA = lambda data: hashlib.sha256(data).hexdigest()
ALIGN = lambda value, alignment: (value + alignment - 1) // alignment * alignment


def coff_sections(raw: bytes):
    machine, count, _, symoff, symcount, optional, _ = struct.unpack_from("<HHLLLHH", raw)
    if machine != 0x8664 or optional != 0:
        raise ValueError("Expected an AMD64 COFF object, not an executable")
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
        index += 1 + raw[at + 17]  # skip COFF auxiliary records
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
    return sections


def unwind_summary(raw: bytes):
    version_flags, prologue, count, frame = struct.unpack_from("<BBBB", raw)
    if version_flags != 1 or frame != 0:
        raise ValueError("Unexpected unwind handler, version or frame-pointer mode")
    entries = []; index = 0; stack = 0; registers = []
    while index < count:
        offset, value = struct.unpack_from("<BB", raw, 4 + 2 * index)
        operation, info = value & 15, value >> 4
        if operation == 0:  # UWOP_PUSH_NONVOL
            registers.append(info); stack += 8
            entries.append({"offset": offset, "op": "push_nonvolatile", "register": info})
        elif operation == 1 and info == 0:  # UWOP_ALLOC_LARGE, short scaled size
            size = struct.unpack_from("<H", raw, 6 + 2 * index)[0] * 8
            index += 1; stack += size
            entries.append({"offset": offset, "op": "allocate", "bytes": size})
        else:
            raise ValueError("Unsupported generated unwind operation")
        index += 1
    if prologue != 14 or stack != 0x328 or sorted(registers) != [3, 6, 7, 12, 13]:
        raise ValueError("Unwind does not describe expected five saves and 0x300 stack allocation")
    return {"version": 1, "flags": 0, "prologue_bytes": prologue,
            "total_stack_bytes_including_saved_registers": stack, "entries": entries}


def build(source: bytes, obj: bytes):
    digest = SHA(source)
    if digest not in ACCEPTED:
        raise ValueError("Unrecognized source hash; only original or wardrobe-only reviewed build is accepted")
    if SHA(ASM.read_bytes()) != ASSEMBLY_SHA256:
        raise ValueError("Assembly source differs from reviewed wrapper")
    pe = pefile.PE(data=source, fast_load=True)
    pe.parse_data_directories(directories=[0])
    if pe.FILE_HEADER.Machine != 0x8664 or pe.OPTIONAL_HEADER.Magic != 0x20B:
        raise ValueError("Expected PE32+ AMD64")
    if pe.OPTIONAL_HEADER.DATA_DIRECTORY[4].Size:
        raise ValueError("Signed image requires a separate signature policy")
    if pe.get_overlay_data_start_offset() is not None:
        raise ValueError("Unexpected overlay")
    call_offset = pe.get_offset_from_rva(CALL_RVA)
    before = bytes.fromhex("e84d970f00")
    if source[call_offset:call_offset + 5] != before:
        raise ValueError("Original rapid FixedUpdate call bytes do not match")
    export = {x.name.decode(): x.address for x in pe.DIRECTORY_ENTRY_EXPORT.symbols if x.name}
    if export.get("il2cpp_string_new_utf16") != TARGETS["StringNewUtf16"]:
        raise ValueError("Native managed-string allocator export does not match")

    sections = coff_sections(obj)
    if set(sections) != {".text", ".data", ".bss", ".xdata", ".pdata"}:
        raise ValueError("Unexpected COFF section set")
    if sections[".data"][0] or sections[".bss"][0] or sections[".xdata"][1]:
        raise ValueError("Unexpected data or unwind relocation")
    if any(SHA(sections[name][0]) != digest for name, digest in SECTION_SHA256.items()):
        raise ValueError("COFF code/unwind/function sections differ from reviewed wrapper")
    code = bytearray(sections[".text"][0]); xdata = sections[".xdata"][0]
    start, end, unwind = struct.unpack("<LLL", sections[".pdata"][0])
    if start != 0 or unwind != 0 or not 0 < end <= len(code):
        raise ValueError("Unexpected generated function extent")
    if sections[".pdata"][1] != [(0, ".text", 3), (4, ".text", 3), (8, ".xdata", 3)]:
        raise ValueError("Unexpected function-table relocations")
    unwind_info = unwind_summary(xdata)
    new_rva = ALIGN(max(x.VirtualAddress + max(x.Misc_VirtualSize, x.SizeOfRawData) for x in pe.sections), pe.OPTIONAL_HEADER.SectionAlignment)
    relocations = []
    for off, symbol, kind in sections[".text"][1]:
        if kind != 4 or symbol not in TARGETS or code[off - 1] != 0xE8:
            raise ValueError("Only expected native rel32 call relocations are allowed")
        addend = struct.unpack_from("<l", code, off)[0]
        if addend != 0:
            raise ValueError("Unexpected COFF call addend")
        struct.pack_into("<l", code, off, TARGETS[symbol] - (new_rva + off + 4))
        relocations.append({"call_rva": hex(new_rva + off - 1), "symbol": symbol, "target_rva": hex(TARGETS[symbol])})
    if [x[1] for x in sections[".text"][1]] != ["ManagerSingleton", "OriginalExit", "ManagerSingleton", "TcpIsConnected", "InfoSingleton", "StringNewUtf16", "TcpSend"]:
        raise ValueError("Unexpected native call sequence")

    # No instruction bytes are allowed to depend on unmapped absolute addresses.
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64); md.detail = True
    instructions = list(md.disasm(code[:end], new_rva))
    if sum(i.size for i in instructions) != end:
        raise ValueError("Generated code does not disassemble completely")
    boundaries = {i.address for i in instructions}
    for ins in instructions:
        if ins.mnemonic.startswith("j"):
            if not ins.operands or ins.operands[0].type != capstone.x86.X86_OP_IMM or ins.operands[0].imm not in boundaries:
                raise ValueError("Generated branch leaves wrapper or targets a partial instruction")
        for op in ins.operands:
            if op.type == capstone.x86.X86_OP_MEM and op.mem.base == capstone.x86.X86_REG_RIP:
                raise ValueError("Unexpected RIP-relative data dependency")
    if instructions[-1].mnemonic != "ret":
        raise ValueError("Missing final return")

    unwind_at = ALIGN(len(code), 4)
    old_directory = pe.OPTIONAL_HEADER.DATA_DIRECTORY[3]
    original_functions = pe.get_data(old_directory.VirtualAddress, old_directory.Size)
    if len(original_functions) % 12:
        raise ValueError("Invalid original function table")
    functions = [struct.unpack_from("<LLL", original_functions, off) for off in range(0, len(original_functions), 12)]
    if functions != sorted(functions) or any(a >= b for a, b, _ in functions):
        raise ValueError("Original function table not strictly bounded/sorted")
    function_entry = (new_rva, new_rva + end, new_rva + unwind_at)
    functions.append(function_entry); functions.sort()
    table = b"".join(struct.pack("<LLL", *row) for row in functions)
    table_at = ALIGN(unwind_at + len(xdata), 4)
    blob = bytes(code).ljust(unwind_at, b"\0") + xdata
    blob = blob.ljust(table_at, b"\0") + table
    raw_at = ALIGN(len(source), pe.OPTIONAL_HEADER.FileAlignment)
    raw_size = ALIGN(len(blob), pe.OPTIONAL_HEADER.FileAlignment)
    header_at = pe.sections[-1].get_file_offset() + 40
    first_raw = min(s.PointerToRawData for s in pe.sections if s.PointerToRawData)
    if header_at + 40 > min(first_raw, pe.OPTIONAL_HEADER.SizeOfHeaders) or any(source[header_at:header_at + 40]):
        raise ValueError("No verified empty section-header slot")
    result = bytearray(source)
    # Existing section contents/RVAs are unchanged; one new RX section is added.
    struct.pack_into("<8sLLLLLLHHL", result, header_at, b".nbp\0\0\0\0", len(blob), new_rva,
                     raw_size, raw_at, 0, 0, 0, 0, 0x60000020)
    struct.pack_into("<H", result, pe.FILE_HEADER.get_field_absolute_offset("NumberOfSections"), pe.FILE_HEADER.NumberOfSections + 1)
    struct.pack_into("<L", result, pe.OPTIONAL_HEADER.get_field_absolute_offset("SizeOfCode"), pe.OPTIONAL_HEADER.SizeOfCode + raw_size)
    struct.pack_into("<L", result, pe.OPTIONAL_HEADER.get_field_absolute_offset("SizeOfImage"), ALIGN(new_rva + len(blob), pe.OPTIONAL_HEADER.SectionAlignment))
    struct.pack_into("<LL", result, old_directory.get_file_offset(), new_rva + table_at, len(table))
    result[call_offset:call_offset + 5] = b"\xe8" + struct.pack("<l", new_rva - (CALL_RVA + 5))
    struct.pack_into("<L", result, pe.OPTIONAL_HEADER.get_field_absolute_offset("CheckSum"), 0)
    result.extend(b"\0" * (raw_at - len(result))); result.extend(blob.ljust(raw_size, b"\0"))
    check = pefile.PE(data=bytes(result), fast_load=True)
    struct.pack_into("<L", result, check.OPTIONAL_HEADER.get_field_absolute_offset("CheckSum"), check.generate_checksum())
    check = pefile.PE(data=bytes(result), fast_load=True)
    check.parse_data_directories(directories=[3])
    checked_rows = [(x.struct.BeginAddress, x.struct.EndAddress, x.struct.UnwindData) for x in check.DIRECTORY_ENTRY_EXCEPTION]
    if checked_rows != functions or len(check.sections) != len(pe.sections) + 1:
        raise ValueError("Reparsed PE function-table/section mismatch")
    allowed = set(range(header_at, header_at + 40)) | set(range(call_offset, call_offset + 5))
    for off, size in [(pe.FILE_HEADER.get_field_absolute_offset("NumberOfSections"), 2),
                      (pe.OPTIONAL_HEADER.get_field_absolute_offset("SizeOfCode"), 4),
                      (pe.OPTIONAL_HEADER.get_field_absolute_offset("SizeOfImage"), 4),
                      (pe.OPTIONAL_HEADER.get_field_absolute_offset("CheckSum"), 4),
                      (old_directory.get_file_offset(), 8)]:
        allowed.update(range(off, off + size))
    changed = [i for i, (a, b) in enumerate(zip(source, result)) if a != b]
    if any(i not in allowed for i in changed):
        raise ValueError("Unexpected mutation of original bytes")
    spec = {"format_version": 1, "scope": "Same-build compatibility candidate, static/offline validation only; original server parity not proven.",
            "source_sha256": digest, "source_variant": ACCEPTED[digest], "copy_sha256": SHA(result),
            "assembly_source_sha256": SHA(ASM.read_bytes()), "coff_sha256": SHA(obj),
            "original_changed_byte_count": len(changed), "target_executed": False, "installation_changed": False,
            "redirect": {"call_rva": hex(CALL_RVA), "file_offset": hex(call_offset), "original_hex": before.hex(), "replacement_hex": result[call_offset:call_offset + 5].hex(), "old_target_rva": "0x545920", "new_target_rva": hex(new_rva)},
            "new_section": {"name": ".nbp", "rva": hex(new_rva), "raw_offset": hex(raw_at), "virtual_size": len(blob), "raw_size": raw_size, "characteristics": "read+execute; not writable", "code_bytes": end},
            "unwind": {**unwind_info, "rva": hex(new_rva + unwind_at), "hex": xdata.hex(), "runtime_function": [hex(x) for x in function_entry], "original_entries_preserved": len(functions) - 1, "new_table_rva": hex(new_rva + table_at)},
            "native_calls": relocations,
            "offline_checks": {"strict_input_hash": True, "allocator_export_matches": True, "all_code_disassembled": True,
                               "all_branches_on_instruction_boundaries_inside_wrapper": True, "only_expected_rel32_calls": True,
                               "unwind_matches_stack_and_nonvolatile_registers": True, "existing_runtime_functions_preserved": True,
                               "new_pe_reparsed": True, "only_permitted_original_bytes_changed": True},
            "limitations": ["Candidate wrapper has not run in Unity/IL2CPP. Static checks do not prove runtime delivery or timing.",
                            "Shipped rapid index0 only; nonzero manager index fails closed after native exit.",
                            "Extra singleton getter before native exit is an authored compatibility step; current local actor identity is checked again after exit.",
                            "The managed string is allocated by exported IL2CPP API on the original managed game thread and passed immediately as TcpSend's managed argument; no raw allocation or manual GC field write.",
                            "Native exceptions propagate through generated unwind metadata; no new exception handler swallows original failures.",
                            "Sending False requires the separately implemented server remote refresh, since original S2C31 False is ignored."]}
    return bytes(result), spec


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--object", type=Path, required=True)
    p.add_argument("--spec", type=Path, required=True)
    p.add_argument("--destination", type=Path)
    a = p.parse_args()
    source = a.source.resolve(strict=True)
    object_path = a.object.resolve(strict=True)
    spec_path = a.spec.resolve()
    protected = {source, object_path, ASM.resolve()}
    if a.destination:
        destination = a.destination.resolve()
        if source == destination or destination.exists() or "steamapps" in [x.lower() for x in destination.parts]:
            p.error("Destination must be a new isolated file outside steamapps")
        protected.add(destination)
    if spec_path in protected or spec_path.exists() or "steamapps" in [x.lower() for x in spec_path.parts]:
        p.error("Specification must be a new separate JSON file outside steamapps and all input/output files")
    if spec_path.suffix.lower() != ".json":
        p.error("Specification must use the .json extension")
    try:
        result, spec = build(source.read_bytes(), object_path.read_bytes())
    except (ValueError, KeyError, struct.error) as e:
        p.error(str(e))
    evidence = []
    for name in ["44bab0", "545920", "545c50", "44ce10", "5e79f0", "43cdf0", "423490", "2b11a0"]:
        path = ROOT / "work/evidence/ghidra/functions" / (name + ".c")
        if path.exists():
            evidence.append({"path": str(path.relative_to(ROOT)), "sha256": SHA(path.read_bytes())})
    spec["native_sources"] = evidence
    spec["copy_written"] = bool(a.destination)
    if a.destination:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as f:
            f.write(result)
        spec["copy_path"] = str(destination)
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    with spec_path.open("x", encoding="utf-8") as output:
        output.write(json.dumps(spec, indent=2) + "\n")
    print(json.dumps({"spec": str(a.spec), "copy_written": bool(a.destination), "copy_sha256": spec["copy_sha256"], "target_executed": False}))


if __name__ == "__main__":
    main()
