"""Locate x64 E8 direct-call candidates without target execution."""

from _research_paths import workspace, output_root, game_path
import bisect
import json
import struct
from pathlib import Path
import pefile

binary = (workspace() / 'work/evidence/GameAssembly.dll')
metadata = json.loads((workspace() / 'work/decompiled/script.json').read_text(encoding="utf-8-sig"))
pe = pefile.PE(str(binary))
base = pe.OPTIONAL_HEADER.ImageBase
names = {}
for method in metadata["ScriptMethod"]:
    names.setdefault(method["Address"], []).append(method["Name"])
starts = sorted(names)
targets = {0x5e7820:"TCPs.TCPClient.Send",0x5d7f90:"CustomEncrypt",0x5d7e90:"CustomDecrypt"}
rows=[]
for section in pe.sections:
    if not section.Characteristics & 0x20000000:
        continue
    raw=section.get_data()
    position=raw.find(b"\xe8")
    while position>=0:
        if position+5<=len(raw):
            rva=section.VirtualAddress+position
            target=rva+5+struct.unpack_from("<i",raw,position+1)[0]
            if target in targets:
                index=bisect.bisect_right(starts,rva)-1
                start=starts[index]
                rows.append({"target":targets[target],"target_rva":hex(target),"call_rva":hex(rva),"containing_method_rva":hex(start),"method_candidates":names[start]})
        position=raw.find(b"\xe8",position+1)
out=(workspace() / 'results/protocol/tcp-callers.json')
out.write_text(json.dumps({"scope":"Raw E8 direct-call candidates in executable sections, assigned nearest preceding IL2CPP metadata method; inspect bounded instruction stream to confirm code and calling semantics.","callers":rows},indent=2),encoding="utf-8")
for row in rows:
    print(row["target"],row["containing_method_rva"],row["call_rva"],row["method_candidates"][:3])
