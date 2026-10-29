"""Read-only bounded native caller/field evidence for the world spawn audit."""

from _research_paths import workspace, output_root, game_path
import bisect
import hashlib
import json
import re
import struct
from pathlib import Path
import capstone
import pefile

ROOT = workspace()
PATH = ROOT / 'work/evidence/GameAssembly.dll'
data = PATH.read_bytes()
pe = pefile.PE(data=data)
names = {}
for item in json.loads((ROOT/'work/decompiled/script.json').read_text(encoding='utf-8-sig'))['ScriptMethod']:
    names.setdefault(item['Address'], []).append(item['Name'])
starts = sorted(names)
targets = {0x5e5b20:'Scenes.LoadLogicPrefab',0x5e8480:'Scenes.LoadLogicPrefab.MoveNext',0x43be60:'ManagerInstance.TCPInit',0x5ea260:'OnConnected.MoveAvatarDelay.MoveNext'}
callers = []
for section in pe.sections:
    if not section.Characteristics & 0x20000000:
        continue
    raw = section.get_data()
    for match in re.finditer(rb'[\xe8\xe9]', raw):
        p = match.start()
        if p+5 > len(raw):
            continue
        rva = section.VirtualAddress+p
        target = rva+5+struct.unpack_from('<i',raw,p+1)[0]
        if target not in targets:
            continue
        index = bisect.bisect_right(starts,rva)-1
        method = starts[index] if index>=0 else None
        callers.append({'rva':hex(rva),'target_rva':hex(target),'target':targets[target],'method_rva':hex(method) if method is not None else None,'method_names':names[method] if method is not None else [],'label_scope':'nearest preceding metadata method candidate' if method is not None else 'below first metadata method; unlabeled generated wrapper candidate'})
md = capstone.Cs(capstone.CS_ARCH_X86,capstone.CS_MODE_64)
md.detail = True
fields = []
examined = []
for start in starts:
    if not any(n.startswith('ManagerInstance$$') or n.startswith('ManagerInstanceNexus$$') for n in names[start]):
        continue
    end = starts[bisect.bisect_right(starts,start)]
    raw = pe.get_data(start,end-start)
    examined.append({'rva':hex(start),'end_rva':hex(end),'names':names[start],'raw_sha256':hashlib.sha256(raw).hexdigest()})
    for ins in md.disasm(raw,pe.OPTIONAL_HEADER.ImageBase+start):
        if any(op.type==capstone.x86.X86_OP_MEM and op.mem.disp==0x160 for op in ins.operands):
            fields.append({'method_rva':hex(start),'method_names':names[start],'instruction_rva':hex(ins.address-pe.OPTIONAL_HEADER.ImageBase),'instruction':f'{ins.mnemonic} {ins.op_str}'})
out=ROOT/'results/protocol/tcp-world-spawn-xrefs.json'
out.write_text(json.dumps({'scope':'Static executable E8/E9 candidate scan assigned nearest metadata methods, plus exact memory displacement0x160 in bounded ManagerInstance/ManagerInstanceNexus methods only. Displacement matches are not a global field-use proof. No target execution.','binary_sha256':hashlib.sha256(data).hexdigest(),'callers':callers,'manager_methods_examined':examined,'manager_displacement_0x160':fields},indent=2)+'\n',encoding='utf-8')
print(json.dumps({'out':str(out),'manager_methods':len(examined),'manager_0x160':fields,'callers':callers},indent=2))
