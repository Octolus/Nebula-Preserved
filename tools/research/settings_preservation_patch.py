"""Build an isolated native settings-compatibility candidate; never install or run it.

The reviewed af25 neck-v2 image is the only accepted input.  The patch adds:
* one UI-only NotificationLoginFriend save producer;
* a stack-local capture and fail-closed prefs-v1 PlatformOnly hydrator.

The shipped ShowPets GameObject is already inactive and is deliberately not
changed.  All original Steam/licensing code and the interaction bridge remain
byte-for-byte preserved.
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
SOURCE_SHA256 = "af25cec2ba6a9496f7c34b5ea8224f4ef5ab9f596bda6ae35bcb44197f30b195"
SHA = lambda value: hashlib.sha256(value).hexdigest()
ALIGN = lambda value, alignment: (value + alignment - 1) // alignment * alignment

# Source-proven method/data RVAs in Steam build 11018722.
SET_NOTIFICATION = 0x429A60
SPLIT = 0x136DBF0
SET_PLAYER_PREF = 0x4286C0
GET_PS4INFO = 0x423490
INIT_METADATA = 0x287160
ALLOC_OBJECT = 0x2872B0
SAVE_TYPEINFO_SLOT = 0x24E1370
SAVE_CTOR = 0x63A190
INT_TO_STRING = 0x150BA80
SAVE_PROCESS = 0x639DB0

PATCHES = (
    ("notification_ui_tail", 0x4AC3BA, bytes.fromhex("e9a1d6f7ff"), "jmp"),
    ("prefs_split_capture", 0x3FCF06, bytes.fromhex("e8e50cf700"), "call"),
    ("prefs_hydrate", 0x3FCFDD, bytes.fromhex("e8deb60200"), "call"),
)

UNWIND_NOTIFICATION = bytes.fromhex("010603000642027001300000")
UNWIND_CAPTURE = bytes.fromhex("0104010004420000")
UNWIND_HYDRATE = bytes.fromhex("0104010004620000")


class Emitter:
    def __init__(self, rva):
        self.rva = rva
        self.data = bytearray()
        self.labels = {}
        self.fixups = []

    @property
    def here(self):
        return self.rva + len(self.data)

    def emit(self, raw):
        self.data.extend(raw)

    def label(self, name):
        if name in self.labels:
            raise ValueError("duplicate label " + name)
        self.labels[name] = self.here

    def rel32(self, opcode, target):
        at = self.here
        self.emit(opcode + struct.pack("<i", target - (at + len(opcode) + 4)))

    def rip32(self, opcode, target):
        self.rel32(opcode, target)

    def branch(self, opcode, label):
        at = self.here
        self.emit(opcode + b"\0\0\0\0")
        self.fixups.append((at + len(opcode), at + len(opcode) + 4, label))

    def finish(self):
        for offset_rva, next_rva, label in self.fixups:
            if label not in self.labels:
                raise ValueError("missing label " + label)
            struct.pack_into("<i", self.data, offset_rva - self.rva,
                             self.labels[label] - next_rva)
        return bytes(self.data)


def notification_code(rva):
    e = Emitter(rva)
    e.emit(bytes.fromhex("53574883ec288bda4533c0"))       # save rbx/rdi; bool->ebx
    e.rel32(b"\xe8", SET_NOTIFICATION)
    e.rip32(bytes.fromhex("488d0d"), SAVE_TYPEINFO_SLOT)
    e.rel32(b"\xe8", INIT_METADATA)
    e.rip32(bytes.fromhex("488b0d"), SAVE_TYPEINFO_SLOT)
    e.rel32(b"\xe8", ALLOC_OBJECT)
    e.emit(bytes.fromhex("4885c0")); e.branch(bytes.fromhex("0f84"), "done")
    e.emit(bytes.fromhex("488bf833d2488bcf"))
    e.rel32(b"\xe8", SAVE_CTOR)
    e.emit(bytes.fromhex("895c2420488d4c242033d2"))
    e.rel32(b"\xe8", INT_TO_STRING)
    e.emit(bytes.fromhex("4533c94c8bc0ba13000000488bcf"))
    e.rel32(b"\xe8", SAVE_PROCESS)
    e.label("done")
    e.emit(bytes.fromhex("4883c4285f5bc3"))
    return e.finish()


def capture_code(rva):
    e = Emitter(rva)
    e.emit(bytes.fromhex("4883ec28"))
    e.rel32(b"\xe8", SPLIT)
    # Caller pre-call RSP +0x28 is wrapper post-sub RSP +0x58.
    e.emit(bytes.fromhex("48894424584883c428c3"))
    return e.finish()


def hydrate_code(rva):
    e = Emitter(rva)
    e.emit(bytes.fromhex(
        "4883ec38"              # shadow + locals
        "48894c2420"          # original manager
        "488b442468"          # caller [rsp+28] split array
        "4889442428"
        "4533c0"))
    e.rel32(b"\xe8", SET_PLAYER_PREF)
    e.emit(bytes.fromhex("488b4424284885c0")); e.branch(bytes.fromhex("0f84"), "done")
    e.emit(bytes.fromhex("83781805")); e.branch(bytes.fromhex("0f85"), "done")
    e.emit(bytes.fromhex("488b50384885d2")); e.branch(bytes.fromhex("0f84"), "done")
    e.emit(bytes.fromhex("837a1008")); e.branch(bytes.fromhex("0f85"), "done")
    e.emit(b"\x48\xb9" + struct.pack("<Q", 0x0066006500720070))
    e.emit(bytes.fromhex("48394a14")); e.branch(bytes.fromhex("0f85"), "done")
    e.emit(b"\x48\xb9" + struct.pack("<Q", 0x00310076002D0073))
    e.emit(bytes.fromhex("48394a1c")); e.branch(bytes.fromhex("0f85"), "done")
    e.emit(bytes.fromhex("488b50404885d2")); e.branch(bytes.fromhex("0f84"), "done")
    e.emit(bytes.fromhex("837a1001")); e.branch(bytes.fromhex("0f85"), "done")
    e.emit(bytes.fromhex("0fb7521483ea3083fa01")); e.branch(bytes.fromhex("0f87"), "done")
    e.emit(bytes.fromhex("8854243033c9"))
    e.rel32(b"\xe8", GET_PS4INFO)
    e.emit(bytes.fromhex("4885c0")); e.branch(bytes.fromhex("0f84"), "done")
    e.emit(bytes.fromhex("488b80680100004885c0")); e.branch(bytes.fromhex("0f84"), "done")
    e.emit(bytes.fromhex("0fb6542430885020"))
    e.label("done")
    # Clear the caller's managed-pointer scratch on all success/failure paths.
    e.emit(bytes.fromhex("48c7442468000000004883c438c3"))
    return e.finish()


def disassemble(code, rva):
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    return [{"rva": hex(i.address), "bytes": i.bytes.hex(),
             "instruction": i.mnemonic + (" " + i.op_str if i.op_str else "")}
            for i in md.disasm(code, rva)]


def verify_unwind(raw, stack, pushes=()):
    if raw[0] != 1 or raw[1] == 0 or raw[3] != 0:
        raise ValueError("Unexpected unwind header")
    count = raw[2]
    codes = raw[4:4 + count * 2]
    operations = []
    for at in range(0, len(codes), 2):
        offset, opinfo = codes[at:at + 2]
        operation, info = opinfo & 15, opinfo >> 4
        operations.append((offset, operation, info))
    allocations = [info * 8 + 8 for _, op, info in operations if op == 2]
    registers = [info for _, op, info in operations if op == 0]
    if allocations != [stack] or registers != list(pushes):
        raise ValueError("Unwind operations differ")
    return operations


def build(source):
    if SHA(source) != SOURCE_SHA256:
        raise ValueError("Source is not the reviewed af25 neck-v2 client stage")
    pe = pefile.PE(data=source, fast_load=True)
    if pe.FILE_HEADER.Machine != 0x8664 or pe.OPTIONAL_HEADER.Magic != 0x20B:
        raise ValueError("Expected AMD64 PE32+")
    if pe.OPTIONAL_HEADER.DATA_DIRECTORY[4].Size or pe.get_overlay_data_start_offset() is not None:
        raise ValueError("Signed or overlay input is unsupported")
    last = pe.sections[-1]
    if (last.Name.rstrip(b"\0") != b".nbi" or last.Characteristics != 0x60000020 or
            last.PointerToRawData + last.SizeOfRawData != len(source) or
            last.Misc_VirtualSize > last.SizeOfRawData):
        raise ValueError("Expected final RX .nbi at file end")
    for name, rva, original, _ in PATCHES:
        if pe.get_data(rva, len(original)) != original:
            raise ValueError(name + " original bytes differ")

    directory = pe.OPTIONAL_HEADER.DATA_DIRECTORY[3]
    old_table = pe.get_data(directory.VirtualAddress, directory.Size)
    if not old_table or len(old_table) != directory.Size or len(old_table) % 12:
        raise ValueError("Invalid original exception directory")
    old_rows = [struct.unpack_from("<III", old_table, at)
                for at in range(0, len(old_table), 12)]
    if old_rows != sorted(old_rows) or any(a >= b for a, b, _ in old_rows) or any(
            old_rows[i][1] > old_rows[i + 1][0] for i in range(len(old_rows) - 1)):
        raise ValueError("Original runtime functions are unsorted or overlap")

    cursor = last.VirtualAddress + last.SizeOfRawData
    wrappers = []
    for name, factory, unwind, stack, pushes in (
            ("notification_ui_save", notification_code, UNWIND_NOTIFICATION, 0x28, (7, 3)),
            ("prefs_split_capture", capture_code, UNWIND_CAPTURE, 0x28, ()),
            ("prefs_platform_hydrate", hydrate_code, UNWIND_HYDRATE, 0x38, ())):
        cursor = ALIGN(cursor, 16)
        code = factory(cursor)
        unwind_rva = ALIGN(cursor + len(code), 4)
        verify_unwind(unwind, stack, pushes)
        wrappers.append({"name": name, "rva": cursor, "code": code,
                         "unwind_rva": unwind_rva, "unwind": unwind})
        cursor = unwind_rva + len(unwind)
    new_rows = old_rows + [(w["rva"], w["rva"] + len(w["code"]), w["unwind_rva"])
                           for w in wrappers]
    if new_rows != sorted(new_rows) or any(new_rows[i][1] > new_rows[i + 1][0]
                                           for i in range(len(new_rows) - 1)):
        raise ValueError("Appended wrappers overlap")
    table_rva = ALIGN(cursor, 8)
    new_table = b"".join(struct.pack("<III", *row) for row in new_rows)
    end_rva = table_rva + len(new_table)
    append_size = end_rva - (last.VirtualAddress + last.SizeOfRawData)
    new_raw_size = ALIGN(last.SizeOfRawData + append_size, pe.OPTIONAL_HEADER.FileAlignment)
    new_virtual_size = last.SizeOfRawData + append_size
    blob = bytearray(new_raw_size - last.SizeOfRawData)
    base = last.VirtualAddress + last.SizeOfRawData
    for w in wrappers:
        blob[w["rva"] - base:w["rva"] - base + len(w["code"])] = w["code"]
        blob[w["unwind_rva"] - base:w["unwind_rva"] - base + len(w["unwind"])] = w["unwind"]
    blob[table_rva - base:table_rva - base + len(new_table)] = new_table

    result = bytearray(source)
    allowed = []
    patch_report = []
    target_by_name = {"notification_ui_tail": wrappers[0]["rva"],
                      "prefs_split_capture": wrappers[1]["rva"],
                      "prefs_hydrate": wrappers[2]["rva"]}
    for name, rva, original, kind in PATCHES:
        at = pe.get_offset_from_rva(rva); target = target_by_name[name]
        opcode = b"\xe9" if kind == "jmp" else b"\xe8"
        replacement = opcode + struct.pack("<i", target - (rva + 5))
        result[at:at + 5] = replacement; allowed.append((at, 5))
        patch_report.append({"name": name, "rva": hex(rva), "file_offset": hex(at),
                             "original": original.hex(), "replacement": replacement.hex(),
                             "target_rva": hex(target), "transfer": kind})

    header_fields = [
        (last.get_field_absolute_offset("Misc_VirtualSize"), new_virtual_size, "last_section.VirtualSize"),
        (last.get_field_absolute_offset("SizeOfRawData"), new_raw_size, "last_section.SizeOfRawData"),
        (pe.OPTIONAL_HEADER.get_field_absolute_offset("SizeOfCode"),
         pe.OPTIONAL_HEADER.SizeOfCode + new_raw_size - last.SizeOfRawData, "SizeOfCode"),
        (pe.OPTIONAL_HEADER.get_field_absolute_offset("SizeOfImage"),
         ALIGN(last.VirtualAddress + new_virtual_size, pe.OPTIONAL_HEADER.SectionAlignment), "SizeOfImage"),
        (directory.get_file_offset(), table_rva, "ExceptionDirectory.RVA"),
        (directory.get_file_offset() + 4, len(new_table), "ExceptionDirectory.Size"),
        (pe.OPTIONAL_HEADER.get_field_absolute_offset("CheckSum"), 0, "CheckSum"),
    ]
    for offset, value, _ in header_fields:
        struct.pack_into("<I", result, offset, value); allowed.append((offset, 4))
    result.extend(blob)
    parsed = pefile.PE(data=bytes(result), fast_load=True)
    struct.pack_into("<I", result, pe.OPTIONAL_HEADER.get_field_absolute_offset("CheckSum"),
                     parsed.generate_checksum())

    restored = bytearray(result[:len(source)])
    for offset, length in allowed:
        restored[offset:offset + length] = source[offset:offset + length]
    if restored != source:
        raise ValueError("Unexpected mutation outside three redirects and PE bookkeeping")
    parsed = pefile.PE(data=bytes(result), fast_load=True)
    checked = parsed.OPTIONAL_HEADER.DATA_DIRECTORY[3]
    if parsed.get_data(checked.VirtualAddress, checked.Size) != new_table:
        raise ValueError("Reparsed exception table differs")
    if parsed.FILE_HEADER.NumberOfSections != pe.FILE_HEADER.NumberOfSections or any(
            (a.Name, a.VirtualAddress, a.PointerToRawData, a.Characteristics) !=
            (b.Name, b.VirtualAddress, b.PointerToRawData, b.Characteristics)
            for a, b in zip(pe.sections, parsed.sections)):
        raise ValueError("Original section identity changed")

    wrapper_report = []
    for w, (_, _, _, stack, pushes) in zip(wrappers, (
            (None, None, None, 0x28, (7, 3)),
            (None, None, None, 0x28, ()),
            (None, None, None, 0x38, ()))):
        if parsed.get_data(w["rva"], len(w["code"])) != w["code"] or parsed.get_data(
                w["unwind_rva"], len(w["unwind"])) != w["unwind"]:
            raise ValueError(w["name"] + " bytes differ after PE reparse")
        wrapper_report.append({"name": w["name"], "rva": hex(w["rva"]),
            "length": len(w["code"]), "bytes": w["code"].hex(),
            "instructions": disassemble(w["code"], w["rva"]),
            "unwind_rva": hex(w["unwind_rva"]), "unwind": w["unwind"].hex(),
            "stack_bytes": stack, "saved_nonvolatile_registers": list(pushes)})

    return bytes(result), {
        "format_version": 1, "source_sha256": SHA(source), "candidate_sha256": SHA(result),
        "target_execution": False, "installation_changed": False,
        "patches": patch_report, "wrappers": wrapper_report,
        "show_pets": {"resources_assets_sha256": "adf9fcbca4f1b6910ab2a4d6260196cdb378f19c20dc616d1fd97c3b9b06eb1b",
            "game_object_path_id": 7522, "already_inactive": True, "asset_changed": False,
            "notification_game_object_path_id": 7950, "notification_remains_active": True},
        "platform_trailer": {"schema": "true#guid#PlayerPrefsJson#prefs-v1#0|1",
            "accepted_array_length": 5, "discriminator": "prefs-v1",
            "hydration": "direct byte write to PlayerPrefsManager+0x20 after original SetPlayerPref; no saving setter"},
        "packaging": {"mode": "append to final RX .nbi and copy/extend exception table",
            "original_file_size": len(source), "original_runtime_functions_preserved": len(old_rows),
            "added_runtime_functions": 3, "new_table_rva": hex(table_rva),
            "allowed_headers": [{"name": name, "file_offset": hex(offset), "length": 4}
                                for offset, _, name in header_fields]},
        "checks": {"strict_source_hash": True, "exact_original_redirect_bytes": True,
            "only_three_redirects_and_headers_changed_in_original_extent": True,
            "all_prior_bridge_neck_bytes_preserved": True, "runtime_functions_sorted_nonoverlapping": True,
            "valid_win64_unwind": True, "PE_reparsed": True, "steam_code_unchanged": True},
        "limitations": ["Static/offline candidate only; controlled native UI/login acceptance remains required.",
            "PlatformOnly functional cross-platform filtering remains runtime-unproven.",
            "A legacy or malformed prefs response intentionally keeps the authored/default current value.",
            "ShowPets remains hidden because no shipped state, hydration, or visibility consumer was recovered."]}


def new_path(parser, path, protected):
    resolved = path.resolve()
    if resolved.exists() or resolved in protected or any(x.lower() == "steamapps" for x in resolved.parts):
        parser.error("Output must be a new distinct path outside steamapps")
    return resolved


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--spec", required=True, type=Path)
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    destination = new_path(parser, args.destination, {source})
    specification = new_path(parser, args.spec, {source, destination})
    try:
        candidate, report = build(source.read_bytes())
    except (ValueError, KeyError, struct.error) as error:
        parser.error(str(error))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as stream:
        stream.write(candidate)
    report.update({"patcher_sha256": SHA(Path(__file__).read_bytes()),
                   "source_path": str(source), "candidate_path": str(destination),
                   "provenance_inputs": [
                       {"kind": "immutable_neck_v2_base", "path": str(source),
                        "sha256": SOURCE_SHA256},
                       {"kind": "original_resources_assets",
                        "path": "work/integration-client/Nebula Realms/Nebula Realms_Data/resources.assets",
                        "sha256": "adf9fcbca4f1b6910ab2a4d6260196cdb378f19c20dc616d1fd97c3b9b06eb1b"}]})
    specification.parent.mkdir(parents=True, exist_ok=True)
    with specification.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"candidate_sha256": report["candidate_sha256"],
                      "specification": str(specification), "target_execution": False}))


if __name__ == "__main__":
    main()
