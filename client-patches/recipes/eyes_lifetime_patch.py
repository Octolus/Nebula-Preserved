"""Build a work-only c11-stage female-eye lifetime guard, without target execution.

Only two 9-byte cached-item guards and the PE checksum change. All live getter
calls, position formulas, list contents, male traversal and EH metadata remain.
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
STAGING = Path(__file__).resolve().parent
SOURCE_SHA256 = "c11dc93f3f67bb09781d9c097ce85cc2e497af9bf83efabaf279ec2b03b0f3d5"
BRIDGE_SHA256 = "e493d6fa9af94df6626e950ee8e4483ede10d94fc81405b394090dd0e047ef10"
EYES_RVA, EYES_SIZE = 0x38F4A0, 0x860
EYES_SHA256 = "81779355198d73c5b6345beebf8a0c60004813ef494ccc8f4c5fd93d03a3028b"
GET_TRANSFORM = 0x1B85F10
SITES = (
    {"side": "female_left", "rva": 0x38FB0C, "next": 0x38FAF2, "end": 0x38FB25,
     "getter_before": 0x38FB17, "eh_state": 7,
     "original": "4885c90f84c501000033d2e8f4637f014885c00f84b0010000"},
    {"side": "female_right", "rva": 0x38FBFA, "next": 0x38FBE0, "end": 0x38FC13,
     "getter_before": 0x38FC05, "eh_state": 10,
     "original": "4885c90f84e800000033d2e806637f014885c00f84d3000000"},
)
RUNTIME_FUNCTION = (0x38F4A0, 0x38FCFD, 0x232946C)
FH4_HANDLER, FH4_INFO = 0x3228B8, 0x2329498
FH4_IP_MAP = 0x2329520
FH4_IP_BYTES = bytes.fromhex("207400350904a902088d04047600cd0610be00290216c800ae0868042a000c1016000c161600")
EXPECTED_STATES = (
    (0x38F4DA, -1), (0x38F727, 1), (0x38F7D1, 3), (0x38F8F4, 1),
    (0x38F92F, -1), (0x38FAE2, 7), (0x38FB41, -1), (0x38FBCB, 10),
    (0x38FC2F, -1), (0x38FC86, 3), (0x38FCBA, 1), (0x38FCCF, -1),
    (0x38FCD5, 7), (0x38FCE0, -1), (0x38FCE6, 10), (0x38FCF1, -1),
)
SHA = lambda data: hashlib.sha256(data).hexdigest()


def encode_block(site):
    start = site["rva"]
    def skip(opcode, offset):
        displacement = site["next"] - (start + offset + 2)
        if not -128 <= displacement <= 127:
            raise ValueError("MoveNext is not reachable by a short branch")
        return bytes([opcode]) + struct.pack("b", displacement)
    # RCX=current Transform; conditional instructions only read it/+10.
    # Native cachedPtr lifetime is the shipped Object.op_Implicit predicate.
    # JRCXZ tests the full RCX without flags; live-path XOR below retains original
    # flag behavior. The remaining16 bytes (getter and result check) stay exact.
    code = skip(0xE3, 0) + bytes.fromhex("4883791000") + skip(0x74, 7) + bytes.fromhex(site["original"])[9:]
    if len(code) != 25 or start + len(code) != site["end"]:
        raise ValueError("Guard block extent differs")
    return code


def inspect_block(site, code):
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True
    instructions = list(md.disasm(code, site["rva"]))
    if [(i.mnemonic, i.size) for i in instructions] != [
            ("jrcxz", 2), ("cmp", 5), ("je", 2), ("xor", 2),
            ("call", 5), ("test", 3), ("je", 6)]:
        raise ValueError("Unexpected lifetime guard instruction layout")
    if any(instructions[i].operands[0].imm != site["next"] for i in (0, 2)):
        raise ValueError("Guard branch does not continue original MoveNext")
    if instructions[4].operands[0].imm != GET_TRANSFORM or instructions[4].address != site["getter_before"]:
        raise ValueError("Original get_transform target changed")
    memory = instructions[1].operands[0]
    if (memory.type != capstone.x86.X86_OP_MEM or memory.mem.base != capstone.x86.X86_REG_RCX or
            memory.mem.disp != 0x10 or memory.size != 8 or instructions[1].operands[1].imm != 0):
        raise ValueError("Lifetime guard does not compare Unity cachedPtr to zero")
    if code != encode_block(site):
        raise ValueError("Guard bytes differ from exact encoding")
    return [{"rva": hex(i.address), "bytes": i.bytes.hex(),
             "instruction": i.mnemonic + " " + i.op_str} for i in instructions]


def decode_ip_map(data):
    """Bounded FH4 compressed unsigned integers; only this pinned IP table is used."""
    cursor = 0
    def read_unsigned():
        nonlocal cursor
        if cursor >= len(data):
            raise ValueError("Truncated FH4 integer")
        first = data[cursor]
        size = next((index + 1 for index in range(4) if not first & (1 << index)), 5)
        if cursor + size > len(data):
            raise ValueError("Truncated FH4 integer payload")
        value = (int.from_bytes(data[cursor + 1:cursor + 5], "little") if size == 5 else
                 int.from_bytes(data[cursor:cursor + size], "little") >> size)
        cursor += size
        return value
    count = read_unsigned()
    if not 1 <= count <= 128:
        raise ValueError("Unexpected FH4 IP-map count")
    rows, address = [], EYES_RVA
    for _ in range(count):
        delta, state = read_unsigned(), read_unsigned() - 1
        address += delta
        if not EYES_RVA <= address < RUNTIME_FUNCTION[1] or (rows and address <= rows[-1][0]):
            raise ValueError("Invalid FH4 IP-map address ordering")
        rows.append((address, state))
    if cursor != len(data):
        raise ValueError("Trailing FH4 IP-map bytes")
    return tuple(rows)


def state_for(address, states):
    found = [state for start, state in states if start <= address]
    if not found:
        raise ValueError("Address outside decoded exception states")
    return found[-1]


def validate_exception_layout(pe):
    directory = pe.OPTIONAL_HEADER.DATA_DIRECTORY[3]
    table = pe.get_data(directory.VirtualAddress, directory.Size)
    if len(table) != directory.Size or not table or len(table) % 12:
        raise ValueError("Invalid runtime function table")
    rows = tuple(struct.unpack_from("<III", table, offset) for offset in range(0, len(table), 12))
    if RUNTIME_FUNCTION not in rows:
        raise ValueError("Original EyesSeparation runtime function differs")
    unwind = pe.get_data(RUNTIME_FUNCTION[2], 0x2C)
    if unwind[:4] != bytes.fromhex("19270f00") or struct.unpack_from("<II", unwind, 0x24) != (FH4_HANDLER, FH4_INFO):
        raise ValueError("Original EH/unwind layout differs")
    if pe.get_data(FH4_INFO, 13) != bytes.fromhex("38a5943202c794320220953202"):
        raise ValueError("Original FH4 header/map pointers differ")
    if pe.get_data(FH4_IP_MAP, len(FH4_IP_BYTES)) != FH4_IP_BYTES:
        raise ValueError("Original FH4 IP-map bytes differ")
    states = decode_ip_map(FH4_IP_BYTES)
    if states != EXPECTED_STATES:
        raise ValueError("Decoded FH4 states differ")
    for site in SITES:
        for address in range(site["rva"], site["end"]):
            if state_for(address, states) != site["eh_state"]:
                raise ValueError("Guard would cross original C++ exception states")
    return {"runtime_function": [hex(value) for value in RUNTIME_FUNCTION],
            "runtime_functions_preserved": len(rows), "exception_table_sha256": SHA(table),
            "unwind_prefix_sha256": SHA(unwind), "FH4_handler_rva": hex(FH4_HANDLER),
            "FH4_ip_map_rva": hex(FH4_IP_MAP), "FH4_ip_map_bytes": FH4_IP_BYTES.hex(),
            "FH4_ip_states": [{"start": hex(start), "state": state} for start, state in states]}


def build(source):
    if SHA(source) != SOURCE_SHA256:
        raise ValueError("Source must be the reviewed c11 registry+neck+settings stage")
    pe = pefile.PE(data=source, fast_load=True)
    if pe.FILE_HEADER.Machine != 0x8664 or pe.OPTIONAL_HEADER.Magic != 0x20B:
        raise ValueError("Expected AMD64 PE32+")
    if SHA(pe.get_data(EYES_RVA, EYES_SIZE)) != EYES_SHA256:
        raise ValueError("Original complete EyesSeparation extent differs")
    if pe.OPTIONAL_HEADER.DATA_DIRECTORY[4].Size or pe.get_overlay_data_start_offset() is not None:
        raise ValueError("Signed/overlay source is unsupported")
    exception = validate_exception_layout(pe)
    result, patches, allowed = bytearray(source), [], []
    for site in SITES:
        original = bytes.fromhex(site["original"])
        if pe.get_data(site["rva"], 25) != original:
            raise ValueError("Original cached-item block differs: " + site["side"])
        replacement = encode_block(site)
        instructions = inspect_block(site, replacement)
        offset = pe.get_offset_from_rva(site["rva"])
        result[offset:offset + 9] = replacement[:9]
        allowed.append((offset, 9))
        patches.append({"side": site["side"], "rva": hex(site["rva"]), "length": 9,
                        "file_offset": hex(offset), "original": original.hex(),
                        "replacement": replacement.hex(), "next_rva": hex(site["next"]),
                        "live_continue_rva": hex(site["end"]), "getter_before": hex(site["getter_before"]),
                        "getter_after": hex(site["getter_before"]), "original_exception_state": site["eh_state"],
                        "instructions": instructions})
    checksum_offset = pe.OPTIONAL_HEADER.get_field_absolute_offset("CheckSum")
    check = pefile.PE(data=bytes(result), fast_load=True)
    struct.pack_into("<I", result, checksum_offset, check.generate_checksum())
    allowed.append((checksum_offset, 4))
    restored = bytearray(result)
    for offset, size in allowed:
        restored[offset:offset + size] = source[offset:offset + size]
    if restored != source or len(result) != len(source):
        raise ValueError("Unexpected change outside two9-byte guards and PE checksum")
    check = pefile.PE(data=bytes(result), fast_load=True)
    # Every PE header byte except CheckSum, and all existing tables/sections, are unchanged.
    first_code = min(section.PointerToRawData for section in pe.sections if section.SizeOfRawData)
    header_check = bytearray(result[:first_code])
    header_check[checksum_offset:checksum_offset + 4] = source[checksum_offset:checksum_offset + 4]
    if header_check != source[:first_code] or validate_exception_layout(check) != exception:
        raise ValueError("Original PE headers or exception metadata changed")
    for patch in patches:
        if check.get_data(int(patch["rva"], 16), 25).hex() != patch["replacement"]:
            raise ValueError("Candidate guard differs after reparse")
    return bytes(result), {
        "format_version": 1, "source_sha256": SHA(source), "candidate_sha256": SHA(result),
        "target_execution": False, "installation_changed": False, "work_staging_only": True,
        "required_bridge_sha256": BRIDGE_SHA256, "original_file_size": len(source),
        "candidate_file_size": len(result), "patches": patches, "exception_layout": exception,
        "packaging": "In-place exact9-byte guards; only CheckSum additionally changes; no appended section/code/data/table.",
        "checksum_file_offset": hex(checksum_offset),
        "semantics": "For each female cached Transform, skip only managed-null or cachedPtr-zero; otherwise preserve original get_transform, null-result exception and localPosition path.",
        "male_scope": "Male branch traverses current W_InitializeMALEFEMALE/AssetsLoaded children rather than the female cached eye lists; its entire instruction extent remains unchanged.",
        "preserved": ["All live-transform position formulas and XMM state", "Original getter targets/arguments and Win64 call alignment/shadow space", "Original stack frame and all nonvolatile registers", "Slider notifications, list contents/counts/versions and save behavior", "All existing PE sections, runtime functions, EH/FH4 data and prior registry/neck/settings bytes except CheckSum"],
        "limitations": ["Isolated static candidate; no native target execution performed.",
                        "Does not rebuild caches or add newly equipped clothing bones to the existing cached set.",
                        "Does not suppress unrelated Unity exceptions or repair unobserved malformed lists/slider dependencies.",
                        "Male removal and female eye movement/save/reload require controlled native acceptance."]}


def new_staging_path(path):
    target = path.resolve()
    if not target.is_relative_to(STAGING) or target.exists():
        raise ValueError("Output must be a new path inside this work staging directory")
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    args = parser.parse_args()
    try:
        destination, spec_path = new_staging_path(args.destination), new_staging_path(args.spec)
        if destination == spec_path:
            raise ValueError("Candidate and specification must be distinct")
        source_path = args.source.resolve(strict=True)
        candidate, spec = build(source_path.read_bytes())
    except (ValueError, OSError, struct.error, pefile.PEFormatError) as error:
        parser.error(str(error))
    spec.update(patcher_sha256=SHA(Path(__file__).read_bytes()), source_path=str(source_path),
                candidate_path=str(destination))
    destination.parent.mkdir(parents=True, exist_ok=True)
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as sink:
        sink.write(candidate)
    with spec_path.open("x", encoding="utf-8") as sink:
        sink.write(json.dumps(spec, indent=2) + "\n")
    print(json.dumps({"candidate_sha256": spec["candidate_sha256"], "specification": str(spec_path),
                      "target_execution": False, "installation_changed": False}))


if __name__ == "__main__":
    main()
