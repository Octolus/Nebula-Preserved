"""Bounded x64 disassembly with recovered IL2CPP method/string annotations."""

from _research_paths import workspace, output_root, game_path
import argparse
import bisect
import json
from pathlib import Path

import capstone
import pefile


def main():
    p = argparse.ArgumentParser()
    p.add_argument("selector", help="method substring or RVA in hex")
    p.add_argument("--binary", default="work/evidence/GameAssembly.dll")
    p.add_argument("--metadata", default="work/decompiled/script.json")
    p.add_argument("--max-bytes", type=int, default=20000)
    a = p.parse_args()
    data = json.loads(Path(a.metadata).read_text(encoding="utf-8-sig"))
    pe = pefile.PE(a.binary)
    base = pe.OPTIONAL_HEADER.ImageBase
    methods = data["ScriptMethod"]
    names = {}
    for x in methods:
        names.setdefault(x["Address"] + base, []).append(x["Name"])
    literals = json.loads(Path(a.metadata).with_name("stringliteral.json").read_text(encoding="utf-8-sig"))
    refs = {}
    for key in ["ScriptMetadata", "ScriptMetadataMethod", "ScriptString"]:
        for x in data.get(key, []):
            refs.setdefault(x["Address"] + base, []).append(x.get("Name", x.get("Value", str(x))))
    for x in literals:
        refs[int(x["address"], 16) + base] = [repr(x["value"])]
    starts = sorted(names)
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True
    try:
        rva = int(a.selector, 16)
        targets = [(rva if rva >= base else base + rva, "selected-address")]
    except ValueError:
        targets = [(x["Address"] + base, x["Name"]) for x in methods if a.selector in x["Name"]]
    for start, label in targets:
        print(f"\n{label} VA={start:#x} RVA={start-base:#x}")
        idx = bisect.bisect_right(starts, start)
        end = min(starts[idx] if idx < len(starts) else start + a.max_bytes, start + a.max_bytes)
        raw = pe.get_data(start-base, end-start)
        for ins in md.disasm(raw, start):
            extra = []
            for op in ins.operands:
                if op.type == capstone.x86.X86_OP_IMM and op.imm in names:
                    extra.extend(names[op.imm][:3])
                elif op.type == capstone.x86.X86_OP_MEM and op.mem.base == capstone.x86.X86_REG_RIP:
                    address = ins.address + ins.size + op.mem.disp
                    extra.extend(refs.get(address, []))
            print(f"{ins.address:#x}: {ins.mnemonic:8} {ins.op_str:55} {'; '.join(extra)}")


if __name__ == "__main__":
    main()
