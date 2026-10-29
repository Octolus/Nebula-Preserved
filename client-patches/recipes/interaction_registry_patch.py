"""Build an isolated exact-build interaction-registry GameAssembly candidate.

The tool never writes its source or a Steam path. It accepts the reviewed F8
layered copy, a compiled AMD64 COFF wrapper, and the sibling bridge DLL.
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
ASM = ROOT / "shims/interaction_registry_bridge.s"
CPP = ROOT / "native-registry/interaction_registry_bridge.cpp"
ABI = ROOT / "native-registry/interaction_registry_bridge_abi.h"
SOURCE_SHA = "ec6f909d3af35c89cd287a2803b86839cd5d1b168bc1f76517eed2494c85e01b"
ASM_SHA = "efd230c15283b07927d83f927c8f5419a9c35ffa776e8e1affb04152ce360870"
CPP_SHA = "ebfea7fb5fec6d448fffd3c8d26d20b1701595e94f8e5060bb00b7f7ba468746"
OBJECT_SHA = "c1b78d89225789d355ccd694f4312bc419e4026707d8497d8ef1d556054bcf65"
ABI_SHA = "7d1ca53eb1c9f2df22b3e7595a5b1bfb72e52403e630b0fceaf106526b06b426"
DLL_SHA = "e493d6fa9af94df6626e950ee8e4483ede10d94fc81405b394090dd0e047ef10"

TARGETS = {
    "OriginalOccupableInitialize": 0x612380,
    "OriginalGenericInitialize": 0x451060,
    "OriginalInitialSetResult": 0x141C4B0,
    "OriginalSavePreset": 0x3A6A20,
    "OriginalFindObjects": 0x8951E0,
    "OriginalLoadAfterPrologue": 0x6BD285,
    "IatLoadLibraryExW": 0x1DD2440,
    "IatGetProcAddress": 0x1DD20C0,
    "IatGetModuleHandleW": 0x1DD20B8,
    "IatGetModuleFileNameW": 0x1DD2318,
}

PATCHES = (
    ("initial_begin", 0x5EAE90, bytes.fromhex("e84ba32a00"), "BeginInitialScan", 5),
    ("save_begin", 0x6BE9AC, bytes.fromhex("e82f681d00"), "BeginSaveScan", 5),
    ("initial_occupable", 0x5EAEC7, bytes.fromhex("e8b4740200"), "RecordInitialOccupable", 5),
    ("initial_generic", 0x5EAF1D, bytes.fromhex("e83e61e6ff"), "RecordInitialGeneric", 5),
    ("save_occupable", 0x6BEAB7, bytes.fromhex("e8c438f5ff"), "RecordSaveOccupable", 5),
    ("save_generic", 0x6BEB17, bytes.fromhex("e84425d9ff"), "RecordSaveGeneric", 5),
    ("load_occupable", 0x6CBC4A, bytes.fromhex("e83167f4ff"), "RecordLoadOccupable", 5),
    ("load_generic", 0x6CBC8E, bytes.fromhex("e8cd53d8ff"), "RecordLoadGeneric", 5),
    ("initial_commit", 0x5EAFE1, bytes.fromhex("e8ca14e300"), "CommitInitial", 5),
    ("save_commit", 0x6BEC57, bytes.fromhex("e8c47dceff"), "CommitSave", 5),
    ("load_commit", 0x6CA8DC, bytes.fromhex("488b5028488b4840ff5018"), "CommitLoad", 11),
)

JUMP_PATCHES = (
    ("load_begin", 0x6BD280, bytes.fromhex("48895c2408"), "BeginLoad", 5),
)

NATIVE_HELPERS = {
    "Component.get_transform": (0x1B85F10, "40534883ec20", "RCX component -> RAX Transform"),
    "Component.get_gameObject": (0x1B85ED0, "40534883ec20", "RCX component -> RAX GameObject"),
    "Transform.get_parent": (0x1B97190, "40534883ec20", "RCX transform -> RAX parent"),
    "Transform.GetSiblingIndex": (0x1B97210, "40534883ec20", "RCX transform -> EAX index"),
    "GameObject.GetComponentsInternal": (0x1B87670, "48895c240848896c2410488974241857",
                                          "RCX GameObject, RDX Type, R8/R9 flags, stack flags/list/MethodInfo -> array"),
    "Component.GetComponentInParent<HousingAssetGround>": (0x8658E0, "48895c24084889742410", "RCX component, RDX generic MethodInfo -> component"),
    "SceneManager.GetActiveScene": (0x1BAB240, "4883ec28", "returns Scene handle in EAX"),
    "Scene.get_name": (0x1BACAC0, "40534883ec20", "RCX points to Scene handle -> managed string"),
    "Scene.GetRootGameObjects": (0x1BAC930, "48895c24084889742410", "RCX points to Scene handle -> GameObject array"),
    "Object.get_name": (0x1B8C010, "40534883ec20", "RCX Unity object -> managed string"),
    "Transform.get_position": (0x1B991E0, "48895c2408574883ec20", "RCX Vector3 sret, RDX transform"),
    "Transform.get_eulerAngles": (0x1B98C70, "48895c2408574883ec40", "RCX Vector3 sret, RDX transform"),
    "TCPClient.Send": (0x5E7820, "48895c2410574883ec20", "RCX client, RDX managed string"),
    "TelepathyTransport..ctor": (0x12DDB60, "b8611e0000c6416a01", "writes 0x4000 server/client max message sizes"),
    "TelepathyTransport.GetMaxPacketSize": (0x73F8E0, "8b4174c3", "returns serverMaxMessageSize at +0x74"),
}

SHA = lambda data: hashlib.sha256(data).hexdigest()
ALIGN = lambda value, alignment: (value + alignment - 1) // alignment * alignment


def coff(raw: bytes):
    machine, section_count, _, symbols_at, symbol_count, optional_size, _ = struct.unpack_from("<HHLLLHH", raw)
    if machine != 0x8664 or optional_size != 0:
        raise ValueError("expected AMD64 COFF object")
    strings = symbols_at + symbol_count * 18
    symbols = {}
    index = 0
    while index < symbol_count:
        at = symbols_at + index * 18
        name_raw = raw[at:at + 8]
        if name_raw[:4] == b"\0\0\0\0":
            start = strings + struct.unpack_from("<L", name_raw, 4)[0]
            name = raw[start:raw.index(b"\0", start)].decode("ascii")
        else:
            name = name_raw.rstrip(b"\0").decode("ascii")
        value, section_number, kind, storage, aux = struct.unpack_from("<LhHBB", raw, at + 8)
        symbols[index] = {"name": name, "value": value, "section": section_number,
                          "kind": kind, "storage": storage}
        index += 1 + aux
    sections = []
    for index in range(section_count):
        at = 20 + optional_size + index * 40
        name, _, _, size, data_at, reloc_at, _, reloc_count, _, flags = struct.unpack_from("<8sLLLLLLHHL", raw, at)
        name = name.rstrip(b"\0").decode("ascii")
        relocs = []
        for j in range(reloc_count):
            offset, symbol_index, reloc_kind = struct.unpack_from("<LLH", raw, reloc_at + j * 10)
            relocs.append((offset, symbols[symbol_index], reloc_kind))
        sections.append({"name": name, "data": bytearray(raw[data_at:data_at + size]),
                         "relocs": relocs, "flags": flags})
    return sections, symbols


def build(source: bytes, obj: bytes, dll: bytes):
    if SHA(source) != SOURCE_SHA:
        raise ValueError("source must be the reviewed F8 layered GameAssembly copy")
    if (SHA(ASM.read_bytes()) != ASM_SHA or SHA(CPP.read_bytes()) != CPP_SHA or
            SHA(ABI.read_bytes()) != ABI_SHA or SHA(obj) != OBJECT_SHA):
        raise ValueError("wrapper source/object differs from the reviewed build")
    if SHA(dll) != DLL_SHA:
        raise ValueError("bridge DLL differs from the reviewed deterministic build")
    dll_pe = pefile.PE(data=dll, fast_load=False)
    if dll_pe.FILE_HEADER.Machine != 0x8664 or dll_pe.OPTIONAL_HEADER.Magic != 0x20B:
        raise ValueError("bridge DLL must be AMD64 PE32+")
    imported_dlls = {row.dll.decode().lower() for row in dll_pe.DIRECTORY_ENTRY_IMPORT}
    if any(name == "libwinpthread-1.dll" or
           (name != "kernel32.dll" and not name.startswith("api-ms-win-crt-"))
           for name in imported_dlls):
        raise ValueError(f"bridge DLL has an unshipped dependency: {sorted(imported_dlls)}")
    exports = {row.name.decode() for row in dll_pe.DIRECTORY_ENTRY_EXPORT.symbols if row.name}
    expected_exports = {"NebulaRegistry_AbiVersion", "NebulaRegistry_Initialize", "NebulaRegistry_Begin",
                        "NebulaRegistry_CaptureSave", "NebulaRegistry_Record", "NebulaRegistry_Commit"}
    if not expected_exports <= exports:
        raise ValueError("bridge DLL is missing required exports")

    pe = pefile.PE(data=source, fast_load=False)
    if pe.FILE_HEADER.Machine != 0x8664 or pe.OPTIONAL_HEADER.Magic != 0x20B:
        raise ValueError("expected AMD64 PE32+")
    if pe.OPTIONAL_HEADER.DATA_DIRECTORY[4].Size or pe.get_overlay_data_start_offset() is not None:
        raise ValueError("signed/overlay source is outside the reviewed profile")
    helper_rows = {}
    for name, (rva, expected_hex, abi) in NATIVE_HELPERS.items():
        expected = bytes.fromhex(expected_hex)
        offset = pe.get_offset_from_rva(rva)
        if source[offset:offset + len(expected)] != expected:
            raise ValueError(f"native helper prefix differs: {name}")
        helper_rows[name] = {"rva": hex(rva), "prefix": expected_hex, "abi": abi}
    metadata_rows = {
        "Component.GetComponentInParent<HousingAssetGround>": (0x24FC3A0, "a78502c000000000"),
    }
    for name, (rva, expected_hex) in metadata_rows.items():
        expected = bytes.fromhex(expected_hex)
        offset = pe.get_offset_from_rva(rva)
        if source[offset:offset + len(expected)] != expected:
            raise ValueError(f"generic MethodInfo slot differs: {name}")

    sections, symbols_by_index = coff(obj)
    by_name = {row["name"]: row for row in sections}
    if set(by_name) != {".text", ".data", ".bss", ".xdata", ".pdata"}:
        raise ValueError("unexpected COFF section set")
    if by_name[".data"]["data"] or by_name[".bss"]["data"] or by_name[".xdata"]["relocs"]:
        raise ValueError("wrapper must contain no mutable data or xdata relocations")

    new_rva = ALIGN(max(s.VirtualAddress + max(s.Misc_VirtualSize, s.SizeOfRawData) for s in pe.sections),
                    pe.OPTIONAL_HEADER.SectionAlignment)
    code = by_name[".text"]["data"]
    xdata = by_name[".xdata"]["data"]
    section_number = {i + 1: row["name"] for i, row in enumerate(sections)}
    public = {}
    wrapper_names = {row[3] for row in PATCHES + JUMP_PATCHES}
    for symbol in symbols_by_index.values():
        if symbol["name"] in wrapper_names:
            if section_number.get(symbol["section"]) != ".text":
                raise ValueError("wrapper export is not in .text")
            public[symbol["name"]] = symbol["value"]
    if set(public) != wrapper_names:
        raise ValueError("missing wrapper symbol")

    relocations = []
    for offset, symbol, kind in by_name[".text"]["relocs"]:
        if kind != 4 or symbol["name"] not in TARGETS:
            raise ValueError(f"unexpected text relocation {kind} to {symbol['name']}")
        addend = struct.unpack_from("<i", code, offset)[0]
        target = TARGETS[symbol["name"]]
        struct.pack_into("<i", code, offset, target + addend - (new_rva + offset + 4))
        relocations.append({"operand_rva": hex(new_rva + offset), "symbol": symbol["name"],
                            "target_rva": hex(target)})

    xdata_at = ALIGN(len(code), 4)
    xdata_rva = new_rva + xdata_at
    pdata = by_name[".pdata"]["data"]
    for offset, symbol, kind in by_name[".pdata"]["relocs"]:
        if kind != 3:
            raise ValueError("unexpected pdata relocation kind")
        section = section_number.get(symbol["section"])
        base = new_rva if section == ".text" else xdata_rva if section == ".xdata" else None
        if base is None:
            raise ValueError("pdata relocation points outside code/unwind sections")
        addend = struct.unpack_from("<L", pdata, offset)[0]
        struct.pack_into("<L", pdata, offset, base + symbol["value"] + addend)
    if len(pdata) % 12:
        raise ValueError("invalid generated pdata length")
    generated_functions = [struct.unpack_from("<LLL", pdata, off) for off in range(0, len(pdata), 12)]
    if len(generated_functions) != 13 or any(a >= b for a, b, _ in generated_functions):
        raise ValueError("unexpected generated runtime-function table")

    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    for begin, end, _ in generated_functions:
        instructions = list(md.disasm(bytes(code[begin - new_rva:end - new_rva]), begin))
        if (sum(row.size for row in instructions) != end - begin or not instructions or
                instructions[-1].mnemonic not in ("ret", "jmp")):
            raise ValueError("generated wrapper does not disassemble to a complete return")

    old_directory = pe.OPTIONAL_HEADER.DATA_DIRECTORY[3]
    original_table = pe.get_data(old_directory.VirtualAddress, old_directory.Size)
    if len(original_table) % 12:
        raise ValueError("invalid original runtime-function table")
    original_functions = [struct.unpack_from("<LLL", original_table, off)
                          for off in range(0, len(original_table), 12)]
    if original_functions != sorted(original_functions) or any(a >= b for a, b, _ in original_functions):
        raise ValueError("original runtime-function table is not strictly ordered/bounded")
    for begin, end, unwind in generated_functions:
        offset = unwind - xdata_rva
        if offset < 0 or offset + 4 > len(xdata):
            raise ValueError("generated unwind RVA leaves xdata")
        version_flags = xdata[offset]
        if version_flags & 7 != 1 or version_flags >> 3:
            raise ValueError("generated unwind metadata has unexpected version/handler flags")
    all_functions = sorted(original_functions + generated_functions)
    table = b"".join(struct.pack("<LLL", *row) for row in all_functions)
    table_at = ALIGN(xdata_at + len(xdata), 4)
    blob = bytes(code).ljust(xdata_at, b"\0") + bytes(xdata)
    blob = blob.ljust(table_at, b"\0") + table

    raw_at = ALIGN(len(source), pe.OPTIONAL_HEADER.FileAlignment)
    raw_size = ALIGN(len(blob), pe.OPTIONAL_HEADER.FileAlignment)
    header_at = pe.sections[-1].get_file_offset() + 40
    first_raw = min(s.PointerToRawData for s in pe.sections if s.PointerToRawData)
    if header_at + 40 > min(first_raw, pe.OPTIONAL_HEADER.SizeOfHeaders) or any(source[header_at:header_at + 40]):
        raise ValueError("no empty section-header slot")
    result = bytearray(source)
    struct.pack_into("<8sLLLLLLHHL", result, header_at, b".nbi\0\0\0\0", len(blob), new_rva,
                     raw_size, raw_at, 0, 0, 0, 0, 0x60000020)
    struct.pack_into("<H", result, pe.FILE_HEADER.get_field_absolute_offset("NumberOfSections"), pe.FILE_HEADER.NumberOfSections + 1)
    struct.pack_into("<L", result, pe.OPTIONAL_HEADER.get_field_absolute_offset("SizeOfCode"), pe.OPTIONAL_HEADER.SizeOfCode + raw_size)
    struct.pack_into("<L", result, pe.OPTIONAL_HEADER.get_field_absolute_offset("SizeOfImage"), ALIGN(new_rva + len(blob), pe.OPTIONAL_HEADER.SectionAlignment))
    struct.pack_into("<LL", result, old_directory.get_file_offset(), new_rva + table_at, len(table))

    patch_rows = []
    patch_ranges = set()
    for name, rva, before, wrapper, length in PATCHES:
        offset = pe.get_offset_from_rva(rva)
        if source[offset:offset + length] != before:
            raise ValueError(f"{name} original bytes differ")
        target = new_rva + public[wrapper]
        replacement = b"\xE8" + struct.pack("<i", target - (rva + 5)) + b"\x90" * (length - 5)
        result[offset:offset + length] = replacement
        patch_ranges.update(range(offset, offset + length))
        patch_rows.append({"name": name, "rva": hex(rva), "original": before.hex(),
                           "replacement": replacement.hex(), "wrapper_rva": hex(target)})
    for name, rva, before, wrapper, length in JUMP_PATCHES:
        offset = pe.get_offset_from_rva(rva)
        if source[offset:offset + length] != before:
            raise ValueError(f"{name} original bytes differ")
        target = new_rva + public[wrapper]
        replacement = b"\xE9" + struct.pack("<i", target - (rva + 5))
        result[offset:offset + length] = replacement
        patch_ranges.update(range(offset, offset + length))
        patch_rows.append({"name": name, "rva": hex(rva), "original": before.hex(),
                           "replacement": replacement.hex(), "wrapper_rva": hex(target)})

    struct.pack_into("<L", result, pe.OPTIONAL_HEADER.get_field_absolute_offset("CheckSum"), 0)
    result.extend(b"\0" * (raw_at - len(result)))
    result.extend(blob.ljust(raw_size, b"\0"))
    check = pefile.PE(data=bytes(result), fast_load=True)
    struct.pack_into("<L", result, check.OPTIONAL_HEADER.get_field_absolute_offset("CheckSum"), check.generate_checksum())
    check = pefile.PE(data=bytes(result), fast_load=False)
    checked_functions = [(x.struct.BeginAddress, x.struct.EndAddress, x.struct.UnwindData)
                         for x in check.DIRECTORY_ENTRY_EXCEPTION]
    if checked_functions != all_functions or len(check.sections) != len(pe.sections) + 1:
        raise ValueError("reparsed PE runtime-function/section mismatch")

    allowed = set(range(header_at, header_at + 40)) | patch_ranges
    for offset, size in ((pe.FILE_HEADER.get_field_absolute_offset("NumberOfSections"), 2),
                         (pe.OPTIONAL_HEADER.get_field_absolute_offset("SizeOfCode"), 4),
                         (pe.OPTIONAL_HEADER.get_field_absolute_offset("SizeOfImage"), 4),
                         (pe.OPTIONAL_HEADER.get_field_absolute_offset("CheckSum"), 4),
                         (old_directory.get_file_offset(), 8)):
        allowed.update(range(offset, offset + size))
    changed = [i for i, (a, b) in enumerate(zip(source, result)) if a != b]
    if any(i not in allowed for i in changed):
        raise ValueError("unexpected mutation of original bytes")

    spec = {
        "format_version": 1,
        "scope": "Isolated exact-build candidate only; not installed or executed.",
        "source_sha256": SHA(source), "candidate_sha256": SHA(result),
        "bridge_dll_sha256": SHA(dll), "wrapper_object_sha256": SHA(obj),
        "bridge_imports": sorted(imported_dlls),
        "patches": patch_rows, "relocations": relocations,
        "native_helpers": helper_rows,
        "generic_methodinfo_slots": {name: {"rva": hex(rva), "bytes": value}
                                     for name, (rva, value) in metadata_rows.items()},
        "new_section": {"name": ".nbi", "rva": hex(new_rva), "raw_offset": hex(raw_at),
                        "virtual_size": len(blob), "raw_size": raw_size, "code_size": len(code),
                        "xdata_size": len(xdata), "runtime_functions_added": len(generated_functions)},
        "original_runtime_functions_preserved": len(original_functions),
        "original_changed_byte_count": len(changed),
        "checks": {"strict_source_hash": True, "strict_wrapper_hash": True, "strict_bridge_dll_hash": True,
                   "no_unshipped_bridge_dependency": True,
                   "bridge_exports_present": True, "all_wrappers_disassemble": True,
                   "native_helper_prefixes_match": True, "generic_methodinfo_slots_match": True,
                   "generated_unwind_registered": True, "pe_reparsed": True,
                   "only_approved_original_bytes_changed": True},
        "target_executed": False, "steam_installation_changed": False,
        "limitations": ["Static validation does not prove Unity runtime behavior.",
                        "The bridge fails closed when semantic introspection or dense occupable lookup is incomplete.",
                        "Save registry activation remains server-pending until its typed ground signature matches the authoritative backend save."],
    }
    return bytes(result), spec


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--object", required=True, type=Path)
    parser.add_argument("--dll", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--spec", required=True, type=Path)
    args = parser.parse_args()
    source = args.source.resolve(strict=True); obj = args.object.resolve(strict=True); dll = args.dll.resolve(strict=True)
    destination = args.destination.resolve(); spec_path = args.spec.resolve()
    for output in (destination, spec_path):
        if output.exists() or output in (source, obj, dll) or "steamapps" in [part.lower() for part in output.parts]:
            parser.error("outputs must be new isolated paths outside Steam")
    result, report = build(source.read_bytes(), obj.read_bytes(), dll.read_bytes())
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(result)
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
