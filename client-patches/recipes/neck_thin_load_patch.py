"""Prepare an isolated original-build Neck Thin editor-load correction.

Only the exact 3001 SAVE-snapshot interaction-registry-stage copy is accepted. Two getter
call sites receive 100-saved instead of saved. No native code is loaded or
executed. Without --destination only a reviewable specification is written.
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
SOURCE_SHA256 = "3001b2e4cf014a7ec961c370b50a947c9b6d6f4be86446f3e5d4bffe203353e3"
GETTER_RVA = 0xE14680
HUNDRED_RVA = 0x1DD2CE4
GETTER_PREFIX = bytes.fromhex("48895c2408574883ec204863da488bf93b5918720733c9e804bf7100488b4f104885c974163b59187317f30f10449920488b5c24304883c4205fc3e8402c47ff")
SITES = (
    {"gender": "MALE", "field": "b73", "blend_index": 72, "slider_field_offset": "0x858",
     "rva": 0x58C94A, "context_rva": 0x58C938,
     "context": "4c8b05d1b3f701ba48000000488bcb488bf8e8317d88004885ff0f841e180000488b170f28c8488bcf4c8b8230040000ff9228040000"},
    {"gender": "FEMALE", "field": "b74", "blend_index": 73, "slider_field_offset": "0x868",
     "rva": 0x58DF19, "context_rva": 0x58DF07,
     "context": "4c8b05029ef701ba49000000488bcb488bf8e8626788004885ff0f8455020000488b170f28c8488bcf4c8b8230040000ff9228040000"},
)
UNWIND = bytes.fromhex("0104010004420000")
SHA = lambda value: hashlib.sha256(value).hexdigest()
ALIGN = lambda value, alignment: (value + alignment - 1) // alignment * alignment


def wrapper_code(rva):
    # Entry RSP=8 mod16; 0x28 reserves shadow32 and restores alignment.
    # Original RCX=list, EDX=index, R8=MethodInfo remain untouched before call.
    return (bytes.fromhex("4883ec28e8") + struct.pack("<i", GETTER_RVA - (rva + 9))
            + bytes.fromhex("f30f100d") + struct.pack("<i", HUNDRED_RVA - (rva + 17))
            + bytes.fromhex("f30f5cc80f28c14883c428c3"))


def verify_wrapper(code, rva):
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64); md.detail = True
    instructions = list(md.disasm(code, rva))
    if [(i.mnemonic, i.size) for i in instructions] != [
            ("sub", 4), ("call", 5), ("movss", 8), ("subss", 4),
            ("movaps", 3), ("add", 4), ("ret", 1)]:
        raise ValueError("Wrapper instruction layout differs")
    if instructions[1].operands[0].imm != GETTER_RVA:
        raise ValueError("Wrapper getter target differs")
    memory = instructions[2].operands[1]
    if memory.type != capstone.x86.X86_OP_MEM or memory.mem.base != capstone.x86.X86_REG_RIP or instructions[2].address + instructions[2].size + memory.mem.disp != HUNDRED_RVA:
        raise ValueError("Wrapper constant relocation differs")
    if code != wrapper_code(rva) or len(code) != 29 or UNWIND != bytes.fromhex("0104010004420000"):
        raise ValueError("Unexpected wrapper/stack/unwind bytes")
    return [{"rva": hex(i.address), "bytes": i.bytes.hex(), "instruction": i.mnemonic + " " + i.op_str} for i in instructions]


def build(source):
    if SHA(source) != SOURCE_SHA256:
        raise ValueError("Source is not the reviewed 3001 SAVE-snapshot interaction-registry stage")
    pe = pefile.PE(data=source, fast_load=True)
    if pe.FILE_HEADER.Machine != 0x8664 or pe.OPTIONAL_HEADER.Magic != 0x20B:
        raise ValueError("Expected AMD64 PE32+")
    if pe.OPTIONAL_HEADER.DATA_DIRECTORY[4].Size or pe.get_overlay_data_start_offset() is not None:
        raise ValueError("Signed or overlay input is unsupported")
    last = pe.sections[-1]
    if (last.Name.rstrip(b"\0") != b".nbi" or last.Characteristics != 0x60000020 or
            last.PointerToRawData + last.SizeOfRawData != len(source) or
            last.VirtualAddress != max(s.VirtualAddress for s in pe.sections) or
            last.Misc_VirtualSize > last.SizeOfRawData or
            any(s is not last and (s.PointerToRawData + s.SizeOfRawData > last.PointerToRawData or
                s.VirtualAddress + max(s.Misc_VirtualSize, s.SizeOfRawData) > last.VirtualAddress)
                for s in pe.sections)):
        raise ValueError("Expected final nonoverlapping RX .nbi at file/RVA end")
    if len(source) % pe.OPTIONAL_HEADER.FileAlignment or last.SizeOfRawData % 16:
        raise ValueError("Unexpected final raw alignment")
    if pe.get_data(GETTER_RVA, len(GETTER_PREFIX)) != GETTER_PREFIX or pe.get_data(HUNDRED_RVA, 4) != struct.pack("<f", 100):
        raise ValueError("Original getter or float100 constant differs")
    for site in SITES:
        context = bytes.fromhex(site["context"])
        if pe.get_data(site["context_rva"], len(context)) != context:
            raise ValueError("Original " + site["gender"] + " neck getter/setter context differs")
    directory = pe.OPTIONAL_HEADER.DATA_DIRECTORY[3]
    table = pe.get_data(directory.VirtualAddress, directory.Size)
    if len(table) != directory.Size or not table or len(table) % 12:
        raise ValueError("Invalid original exception table")
    rows = [struct.unpack_from("<III", table, at) for at in range(0, len(table), 12)]
    if rows != sorted(rows) or any(a >= b for a, b, _ in rows) or any(rows[i][1] > rows[i + 1][0] for i in range(len(rows) - 1)):
        raise ValueError("Original runtime functions overlap or are unsorted")

    wrapper_rva = last.VirtualAddress + last.SizeOfRawData
    code = wrapper_code(wrapper_rva)
    disassembly = verify_wrapper(code, wrapper_rva)
    unwind_at = ALIGN(len(code), 4)
    new_entry = (wrapper_rva, wrapper_rva + len(code), wrapper_rva + unwind_at)
    if rows[-1][1] > new_entry[0]:
        raise ValueError("Wrapper overlaps an existing runtime function")
    expanded = rows + [new_entry]
    table_at = unwind_at + len(UNWIND)
    blob = code.ljust(unwind_at, b"\0") + UNWIND + b"".join(struct.pack("<III", *row) for row in expanded)
    new_raw_size = ALIGN(last.SizeOfRawData + len(blob), pe.OPTIONAL_HEADER.FileAlignment)
    new_virtual_size = last.SizeOfRawData + len(blob)
    result = bytearray(source)
    allowed = []
    patches = []
    for site in SITES:
        at = pe.get_offset_from_rva(site["rva"])
        before = source[at:at + 5]
        if before != b"\xe8" + struct.pack("<i", GETTER_RVA - (site["rva"] + 5)):
            raise ValueError("Exact original call bytes differ")
        after = b"\xe8" + struct.pack("<i", wrapper_rva - (site["rva"] + 5))
        result[at:at + 5] = after; allowed.append((at, 5))
        patches.append({**{k: v for k, v in site.items() if k not in ("context", "rva", "context_rva")},
                        "call_rva": hex(site["rva"]), "file_offset": hex(at),
                        "original": before.hex(), "replacement": after.hex(), "wrapper_rva": hex(wrapper_rva)})
    header_fields = [
        (last.get_field_absolute_offset("Misc_VirtualSize"), new_virtual_size, "last_section.VirtualSize"),
        (last.get_field_absolute_offset("SizeOfRawData"), new_raw_size, "last_section.SizeOfRawData"),
        (pe.OPTIONAL_HEADER.get_field_absolute_offset("SizeOfCode"), pe.OPTIONAL_HEADER.SizeOfCode + new_raw_size - last.SizeOfRawData, "SizeOfCode"),
        (pe.OPTIONAL_HEADER.get_field_absolute_offset("SizeOfImage"), ALIGN(last.VirtualAddress + new_virtual_size, pe.OPTIONAL_HEADER.SectionAlignment), "SizeOfImage"),
        (directory.get_file_offset(), wrapper_rva + table_at, "ExceptionDirectory.RVA"),
        (directory.get_file_offset() + 4, len(expanded) * 12, "ExceptionDirectory.Size"),
        (pe.OPTIONAL_HEADER.get_field_absolute_offset("CheckSum"), 0, "CheckSum"),
    ]
    for offset, value, _ in header_fields:
        struct.pack_into("<I", result, offset, value); allowed.append((offset, 4))
    result.extend(blob.ljust(new_raw_size - last.SizeOfRawData, b"\0"))
    check = pefile.PE(data=bytes(result), fast_load=True)
    struct.pack_into("<I", result, pe.OPTIONAL_HEADER.get_field_absolute_offset("CheckSum"), check.generate_checksum())
    restored = bytearray(result[:len(source)])
    for offset, length in allowed:
        restored[offset:offset + length] = source[offset:offset + length]
    if restored != source:
        raise ValueError("Unexpected change outside the two calls/allowed PE headers")
    check = pefile.PE(data=bytes(result), fast_load=True)
    checked_directory = check.OPTIONAL_HEADER.DATA_DIRECTORY[3]
    if check.get_data(checked_directory.VirtualAddress, checked_directory.Size) != b"".join(struct.pack("<III", *row) for row in expanded):
        raise ValueError("Expanded runtime-function table differs after PE reparse")
    if check.FILE_HEADER.NumberOfSections != pe.FILE_HEADER.NumberOfSections or any(
            (a.Name, a.VirtualAddress, a.PointerToRawData, a.Characteristics) !=
            (b.Name, b.VirtualAddress, b.PointerToRawData, b.Characteristics)
            for a, b in zip(pe.sections, check.sections)):
        raise ValueError("Original section identity/RVA/file offset/permissions changed")
    if check.get_data(wrapper_rva, len(code)) != code or check.get_data(new_entry[2], len(UNWIND)) != UNWIND:
        raise ValueError("Appended wrapper/unwind differs after PE reparse")
    return bytes(result), {
        "format_version": 1, "source_sha256": SHA(source), "candidate_sha256": SHA(result),
        "target_execution": False, "installation_changed": False, "patches": patches,
        "wrapper": {"rva": hex(wrapper_rva), "length": len(code), "bytes": code.hex(), "instructions": disassembly,
                    "abi": "RCX List<float>, EDX index, R8 MethodInfo forwarded; XMM0 returns Single(100-saved); no nonvolatile register changes; RSP reserves/restores0x28"},
        "unwind": {"rva": hex(new_entry[2]), "bytes": UNWIND.hex(), "version": 1, "flags": 0,
                   "prologue_size": 4, "operation": "UWOP_ALLOC_SMALL", "stack_bytes": 40,
                   "runtime_function": [hex(value) for value in new_entry]},
        "packaging": {"mode": "append beyond original EOF and extend last RX .nbi; no new section header",
                      "original_section_count": len(pe.sections), "original_file_size": len(source),
                      "original_runtime_functions_preserved": len(rows), "added_runtime_functions": 1,
                      "new_table_rva": hex(wrapper_rva + table_at),
                      "allowed_headers": [{"name": name, "file_offset": hex(offset), "length": 4} for offset, _, name in header_fields]},
        "checks": {"strict_stage_hash": True, "exact_gender_field_index_call_contexts": True,
                   "original_sections_and_runtime_functions_preserved": True,
                   "no_certificate_overlay_or_code_cave": True,
                   "only_two_calls_and_explicit_headers_changed_in_original_extent": True,
                   "valid_wrapper_disassembly_and_unwind": True, "PE_reparsed": True},
        "limitations": ["Static candidate only; native load/save and Windows exception unwinding require controlled acceptance.",
                        "Original slider clamps to0..100. Finite off-range values therefore retain original UI clamp behavior.",
                        "Single precision 100-(100-weight) can quantize arbitrary fractional weights; representative0/25/50/75/100 roundtrip exactly. No bit-exact guarantee for every float.",
                        "Only neck-thin load sites change. Original callbacks, readers and female pectoral HTTP compensation remain unchanged."]}


def new_path(parser, path, protected):
    resolved = path.resolve()
    if resolved.exists() or resolved in protected or any(part.lower() == "steamapps" for part in resolved.parts):
        parser.error("Output must be a new distinct path outside steamapps")
    return resolved


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--destination", type=Path)
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    specification = new_path(parser, args.spec, {source})
    destination = new_path(parser, args.destination, {source, specification}) if args.destination else None
    try:
        candidate, spec = build(source.read_bytes())
    except (ValueError, KeyError, struct.error) as error:
        parser.error(str(error))
    spec["patcher_sha256"] = SHA(Path(__file__).read_bytes())
    spec["source_path"] = str(source)
    spec["candidate_written"] = destination is not None
    if destination:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as stream: stream.write(candidate)
        spec["candidate_path"] = str(destination)
    specification.parent.mkdir(parents=True, exist_ok=True)
    with specification.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(spec, indent=2) + "\n")
    print(json.dumps({"specification": str(specification), "candidate_sha256": spec["candidate_sha256"], "target_execution": False}))


if __name__ == "__main__": main()
