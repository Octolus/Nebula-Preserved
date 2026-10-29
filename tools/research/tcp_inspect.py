"""Batch static IL2CPP native inspection; never executes the target."""

from _research_paths import workspace, output_root, game_path
import argparse
import bisect
import hashlib
import json
from pathlib import Path

import capstone
import pefile


def main():
    p = argparse.ArgumentParser()
    p.add_argument("selectors", nargs="+")
    p.add_argument("--binary", default="work/evidence/GameAssembly.dll")
    p.add_argument("--metadata", default="work/decompiled/script.json")
    p.add_argument("--out", required=True)
    p.add_argument("--max-bytes", type=int, default=24000)
    a = p.parse_args()
    data = json.loads(Path(a.metadata).read_text(encoding="utf-8-sig"))
    pe = pefile.PE(a.binary)
    base = pe.OPTIONAL_HEADER.ImageBase
    names = {}
    for x in data["ScriptMethod"]:
        names.setdefault(x["Address"] + base, []).append(x["Name"])
    refs = {}
    for key in ["ScriptMetadata", "ScriptMetadataMethod", "ScriptString"]:
        for x in data.get(key, []):
            refs.setdefault(x["Address"] + base, []).append(x.get("Name", x.get("Value", str(x))))
    for x in json.loads(Path(a.metadata).with_name("stringliteral.json").read_text(encoding="utf-8-sig")):
        refs[int(x["address"], 16) + base] = [repr(x["value"])]
    starts = sorted(names)
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True
    targets = {}
    for selector in a.selectors:
        try:
            rva = int(selector, 16)
            va = rva if rva >= base else base + rva
            targets[va] = names.get(va, ["selected-address"])
        except ValueError:
            for va, labels in names.items():
                if any(selector in label for label in labels):
                    targets[va] = labels
    result = []
    for start, labels in sorted(targets.items()):
        idx = bisect.bisect_right(starts, start)
        end = min(starts[idx] if idx < len(starts) else start+a.max_bytes, start+a.max_bytes)
        raw = pe.get_data(start-base, end-start)
        instructions = []
        for ins in md.disasm(raw, start):
            annotations = []
            for op in ins.operands:
                if op.type == capstone.x86.X86_OP_IMM and op.imm in names:
                    annotations.extend(names[op.imm])
                elif op.type == capstone.x86.X86_OP_MEM and op.mem.base == capstone.x86.X86_REG_RIP:
                    annotations.extend(refs.get(ins.address+ins.size+op.mem.disp, []))
            instructions.append({"va":hex(ins.address),"rva":hex(ins.address-base),"op":ins.mnemonic,"args":ins.op_str,"annotations":annotations})
        result.append({"names":labels,"va":hex(start),"rva":hex(start-base),"end_va":hex(end),"raw_sha256":hashlib.sha256(raw).hexdigest(),"instructions":instructions})
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"binary":str(Path(a.binary).resolve()),"binary_sha256":hashlib.sha256(Path(a.binary).read_bytes()).hexdigest(),"metadata":str(Path(a.metadata).resolve()),"scope":"static bounded native disassembly; next metadata method or max-bytes boundary; not observed execution","methods":result},indent=2),encoding="utf-8")
    print(json.dumps({"out":str(out),"methods":len(result),"instructions":sum(len(x["instructions"]) for x in result)}))


if __name__ == "__main__":
    main()
