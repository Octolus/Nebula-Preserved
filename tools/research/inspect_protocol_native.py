"""Retain bounded static x64 instruction evidence for protocol helpers.

Requires pefile and capstone. No target code is executed.
"""
from __future__ import annotations

from _research_paths import workspace, output_root, game_path
import argparse
import hashlib
import json
from pathlib import Path
import capstone
import pefile


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--binary", type=Path, required=True)
    ap.add_argument("--script", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    pe = pefile.PE(str(args.binary), fast_load=True)
    base = pe.OPTIONAL_HEADER.ImageBase
    script = json.loads(args.script.read_text(encoding="utf-8-sig"))
    methods = {}
    for method in script["ScriptMethod"]:
        methods.setdefault(base + method["Address"], []).append(method["Name"])
    strings = {base + item["Address"]: item["Value"] for item in script["ScriptString"]}
    metadata = {base + item["Address"]: item["Name"] for item in script["ScriptMetadata"]}
    cs = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    cs.detail = True
    selected = {
        "Mirror.Extensions$$GetStableHashCode": 0x60,
        "Mirror.MessagePacking$$GetId<NebulaMessage>": 0x80,
        "Mirror.GeneratedNetworkCode$$_Write_NebulaMessage": 0x60,
        "Mirror.GeneratedNetworkCode$$_Read_NebulaMessage": 0x70,
        "Assets.Scripts.NebulaPlayers.NebulaPlayerSyncVars$$.cctor": 0x100,
        "Assets.Scripts.NebulaPlayers.NebulaPlayerSyncVars$$UserCode_SetSpeed__Single": 0x10,
        "Mirror.NetworkManager$$StartHost": 0x150,
        "Mirror.NetworkManager$$StartServer": 0x120,
    }
    for method in script["ScriptMethod"]:
        if method["Name"].startswith("Assets.Scripts.HTTPs.Tasks") and method["Name"].endswith("$$.cctor"):
            selected[method["Name"]] = 0x70
    result = []
    for method in script["ScriptMethod"]:
        if method["Name"] not in selected:
            continue
        start = base + method["Address"]
        offset = pe.get_offset_from_rva(method["Address"])
        raw = pe.__data__[offset:offset + selected[method["Name"]]]
        instructions = []
        literal_refs = []
        for ins in cs.disasm(raw, start):
            refs = []
            for op in ins.operands:
                if op.type == capstone.x86.X86_OP_IMM and op.imm in methods:
                    refs.append({"kind": "method-target", "va": hex(op.imm), "names": methods[op.imm]})
                elif op.type == capstone.x86.X86_OP_MEM and op.mem.base == capstone.x86.X86_REG_RIP:
                    ptr = ins.address + ins.size + op.mem.disp
                    if ptr in strings:
                        ref = {"kind": "il2cpp-string-slot", "va": hex(ptr), "value": strings[ptr]}
                        refs.append(ref)
                        literal_refs.append(ref)
                    elif ptr in metadata:
                        refs.append({"kind": "il2cpp-metadata-slot", "va": hex(ptr), "name": metadata[ptr]})
            instructions.append({"va": hex(ins.address), "bytes": ins.bytes.hex(), "mnemonic": ins.mnemonic, "operands": ins.op_str, "references": refs})
        result.append({"evidence_id": "NEB-STATIC-" + hex(method["Address"])[2:].upper(), "method": method["Name"], "va": hex(start), "rva": hex(method["Address"]), "file_offset": offset, "slice_length": len(raw), "slice_sha256": hashlib.sha256(raw).hexdigest(), "referenced_literals": literal_refs, "instructions": instructions})
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "bounded-native-protocol-evidence.json").write_text(json.dumps({"artifact": str(args.binary.resolve()), "sha256": hashlib.sha256(args.binary.read_bytes()).hexdigest(), "image_base": hex(base), "evidence_type": "static bounded x64 disassembly", "limitations": ["Slices are bounds selected by the analyst, not recovered complete function-body ranges.", "Disassembly does not establish execution, reachability, or actual runtime pointer contents.", "IL2CPP string-slot values and method identities come from Il2CppDumper metadata mapping."], "records": result}, indent=2), encoding="utf-8")
    commands = [{"method": r["method"], "evidence_id": r["evidence_id"], "referenced_literals": r["referenced_literals"]} for r in result if r["method"].startswith("Assets.Scripts.HTTPs.Tasks")]
    (args.out / "http-task-command-candidates.json").write_text(json.dumps(commands, indent=2), encoding="utf-8")
    print(json.dumps({"instruction_records": len(result), "http_task_command_records": len(commands)}))


if __name__ == "__main__":
    main()
