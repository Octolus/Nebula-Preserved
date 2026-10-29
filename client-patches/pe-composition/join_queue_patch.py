"""Exact offline join-queue Update shim; no installation or target execution."""
from __future__ import annotations
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import struct
import subprocess
import capstone
import pefile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
INPUTS = {
    "default": ("GameAssembly.dll", "0ec5e89f91010e205b19ee4de29a4167c1deb7312a45733a866dbebec64a13ab"),
    "free-mouse": ("GameAssembly.dll", "6fc2fcdf0e4178b96069f25e4f2e8fcacf8af3c33fb68c4f144ae6a5fd4dd4df"),
}
COFF_READER = ROOT / "recipes/interaction_registry_patch.py"
COFF_READER_PIN = "6a65a9eab4340d759a5fc7509622b2fd741bae473fc8a954cadd7d7cb24ffdee"
UPDATE = 0x5E54C0
PROCESS = 0x5E5010
PREFIX = bytes.fromhex("33d2e949fbffff")
PROCESS_PREFIX = bytes.fromhex("41574883ec50803de3130502004c8bf9751f")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(ok, text):
    if not ok:
        raise ValueError(text)


def align(value, alignment):
    return (value + alignment - 1) // alignment * alignment


def coff_reader():
    require(sha(COFF_READER.read_bytes()) == COFF_READER_PIN, "Pinned COFF reader differs")
    spec = importlib.util.spec_from_file_location("join_queue_coff_reader", COFF_READER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.coff


def compose(source: bytes, obj: bytes):
    require(sha(source) in {pin for _, pin in INPUTS.values()}, "Exact default or explicit free-mouse input required")
    pe = pefile.PE(data=source)
    require(pe.FILE_HEADER.Machine == 0x8664 and pe.OPTIONAL_HEADER.Magic == 0x20B, "AMD64 PE32+ required")
    require(not pe.OPTIONAL_HEADER.DATA_DIRECTORY[4].Size and pe.get_overlay_data_start_offset() is None,
            "Unexpected signature or overlay")
    last = pe.sections[-1]
    require(last.Name.rstrip(b"\0") == b".nbi" and last.Characteristics == 0x60000020 and
            last.PointerToRawData + last.SizeOfRawData == len(source), "Exact terminal RX section required")
    require(pe.get_data(UPDATE, 7) == PREFIX, "Original Update leaf differs")
    require(pe.get_data(PROCESS, len(PROCESS_PREFIX)) == PROCESS_PREFIX, "Original ProcessTasks prefix differs")
    require(not any(x.struct.BeginAddress <= UPDATE < x.struct.EndAddress for x in pe.DIRECTORY_ENTRY_EXCEPTION),
            "Original Update is no longer an unwind-free leaf")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    require([(x.mnemonic, x.op_str, x.size) for x in md.disasm(PREFIX, UPDATE)] ==
            [("xor", "edx, edx", 2), ("jmp", "0x5e5010", 5)], "Update semantics differ")
    imports = {r.dll.lower(): {i.name: i.address - pe.OPTIONAL_HEADER.ImageBase for i in r.imports}
               for r in pe.DIRECTORY_ENTRY_IMPORT}
    require(b"NebulaAutomation_JoinQueueReady" not in imports.get(b"nebulaautomation.dll", {}),
            "Duplicate gate import unexpected")
    require(set(imports.get(b"nebulaautomation.dll", {})) ==
            {b"NebulaAutomation_EconomyShopInfoCompleted", b"NebulaAutomation_EconomyPurchasesCompleted"},
            "Automation loader dependency differs")
    targets = {"OriginalProcessTasks": PROCESS,
               "IatGetModuleHandleW": imports[b"kernel32.dll"][b"GetModuleHandleW"],
               "IatGetProcAddress": imports[b"kernel32.dll"][b"GetProcAddress"]}
    require(targets["IatGetModuleHandleW"] == 0x1DD20B8 and targets["IatGetProcAddress"] == 0x1DD20C0,
            "Kernel import slots differ")
    sections, symbols = coff_reader()(obj)
    by_name = {s["name"]: s for s in sections}
    require(set(by_name) == {".text", ".data", ".bss", ".xdata", ".pdata"}, "Unexpected COFF sections")
    require(not by_name[".data"]["data"] and not by_name[".bss"]["data"] and not by_name[".xdata"]["relocs"],
            "Unexpected mutable state or unwind relocations")
    names = {i + 1: s["name"] for i, s in enumerate(sections)}
    new_rva = last.VirtualAddress + last.SizeOfRawData
    blob = bytearray(by_name[".text"]["data"])
    wrappers = [s for s in symbols.values() if s["name"] == "JoinQueueUpdate"]
    require(len(wrappers) == 1 and names.get(wrappers[0]["section"]) == ".text", "Exact wrapper symbol required")
    wrapper = new_rva + wrappers[0]["value"]
    relocation_rows = []
    for offset, symbol, kind in by_name[".text"]["relocs"]:
        require(kind == 4, "Only REL32 code relocations supported")
        if symbol["section"] > 0:
            require(names.get(symbol["section"]) == ".text", "Relocation leaves wrapper text")
            target = new_rva + symbol["value"]
        else:
            require(symbol["name"] in targets, "Unapproved external symbol")
            target = targets[symbol["name"]]
        value = struct.unpack_from("<i", blob, offset)[0]
        struct.pack_into("<i", blob, offset, target + value - (new_rva + offset + 4))
        relocation_rows.append({"operand_rva": hex(new_rva + offset), "symbol": symbol["name"], "target_rva": hex(target)})
    xdata_at = align(len(blob), 4)
    blob.extend(bytes(xdata_at - len(blob)))
    blob.extend(by_name[".xdata"]["data"])
    pdata = bytearray(by_name[".pdata"]["data"])
    for offset, symbol, kind in by_name[".pdata"]["relocs"]:
        require(kind == 3 and names.get(symbol["section"]) in (".text", ".xdata"), "Unsupported pdata relocation")
        target = new_rva + (0 if names[symbol["section"]] == ".text" else xdata_at) + symbol["value"]
        value = struct.unpack_from("<I", pdata, offset)[0]
        struct.pack_into("<I", pdata, offset, target + value)
    require(len(pdata) == 12, "Exactly one generated runtime row required")
    generated = tuple(struct.unpack("<III", pdata))
    require(generated[0] == wrapper and new_rva <= generated[0] < generated[1] <= new_rva + xdata_at and
            new_rva + xdata_at <= generated[2] < new_rva + len(blob), "Generated unwind bounds differ")
    unwind = bytes(blob[generated[2] - new_rva:generated[2] - new_rva + 8])
    require(unwind[:4] == bytes.fromhex("01040100") and unwind[4:6] == bytes.fromhex("0462"),
            "Wrapper must use one 0x38 stack allocation unwind operation")
    original_rows = [(x.struct.BeginAddress, x.struct.EndAddress, x.struct.UnwindData) for x in pe.DIRECTORY_ENTRY_EXCEPTION]
    rows = sorted(original_rows + [generated])
    require(len(set(rows)) == len(rows) and all(rows[i][1] <= rows[i + 1][0] for i in range(len(rows) - 1)),
            "Runtime function overlap")
    table_at = align(len(blob), 4)
    blob.extend(bytes(table_at - len(blob)))
    blob.extend(b"".join(struct.pack("<III", *row) for row in rows))
    result = bytearray(source)
    allowed = set()

    def write(fmt, at, *values):
        struct.pack_into(fmt, result, at, *values)
        allowed.update(range(at, at + struct.calcsize(fmt)))

    offset = pe.get_offset_from_rva(UPDATE)
    patch = b"\xe9" + struct.pack("<i", wrapper - UPDATE - 5) + b"\x90\x90"
    result[offset:offset + 7] = patch
    allowed.update(range(offset, offset + 7))
    raw_size = align(len(blob), pe.OPTIONAL_HEADER.FileAlignment)
    write("<I", last.get_field_absolute_offset("Misc_VirtualSize"), last.SizeOfRawData + len(blob))
    write("<I", last.get_field_absolute_offset("SizeOfRawData"), last.SizeOfRawData + raw_size)
    write("<I", pe.OPTIONAL_HEADER.get_field_absolute_offset("SizeOfCode"), pe.OPTIONAL_HEADER.SizeOfCode + raw_size)
    write("<I", pe.OPTIONAL_HEADER.get_field_absolute_offset("SizeOfImage"), align(new_rva + len(blob), pe.OPTIONAL_HEADER.SectionAlignment))
    write("<II", pe.OPTIONAL_HEADER.DATA_DIRECTORY[3].get_file_offset(), new_rva + table_at, len(rows) * 12)
    write("<I", pe.OPTIONAL_HEADER.get_field_absolute_offset("CheckSum"), 0)
    result.extend(blob.ljust(raw_size, b"\0"))
    check = pefile.PE(data=bytes(result))
    write("<I", pe.OPTIONAL_HEADER.get_field_absolute_offset("CheckSum"), check.generate_checksum())
    check.close()
    check = pefile.PE(data=bytes(result))
    require([(x.struct.BeginAddress, x.struct.EndAddress, x.struct.UnwindData) for x in check.DIRECTORY_ENTRY_EXCEPTION] == rows,
            "Reparsed unwind table differs")
    require(check.get_data(PROCESS, len(PROCESS_PREFIX)) == PROCESS_PREFIX, "Original drain body changed")
    require(all(i in allowed for i, (a, b) in enumerate(zip(source, result)) if a != b), "Unexplained original-byte mutation")
    require([(r.dll, [(i.name, i.address - pe.OPTIONAL_HEADER.ImageBase) for i in r.imports]) for r in pe.DIRECTORY_ENTRY_IMPORT] ==
            [(r.dll, [(i.name, i.address - check.OPTIONAL_HEADER.ImageBase) for i in r.imports]) for r in check.DIRECTORY_ENTRY_IMPORT],
            "Existing imports changed")
    require(all(s.Characteristics & 0xA0000000 != 0xA0000000 for s in check.sections), "RWX section rejected")
    body = bytes(blob[generated[0] - new_rva:generated[1] - new_rva])
    decoded = list(md.disasm(body, wrapper))
    require(sum(i.size for i in decoded) == len(body), "Incomplete wrapper disassembly")
    report = {"source_sha256": sha(source), "output_sha256": sha(result), "bytes": len(result),
              "hook": {"rva": hex(UPDATE), "before": PREFIX.hex(), "after": patch.hex(), "target_rva": hex(wrapper)},
              "original_drain_rva": hex(PROCESS), "original_drain_unchanged": True,
              "generated_runtime_row": [hex(v) for v in generated], "unwind_bytes": unwind.hex(),
              "original_runtime_rows_preserved": len(original_rows), "relocations": relocation_rows,
              "wrapper_assembly": [f"{i.address:x}: {i.mnemonic} {i.op_str}" for i in decoded],
              "imports_unchanged": True, "existing_byte_changes_allowlisted": True,
              "installed": False, "game_launched": False}
    check.close()
    pe.close()
    return bytes(result), report

