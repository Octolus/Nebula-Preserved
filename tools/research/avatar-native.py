"""Capture bounded static x64 evidence for requested avatar method selectors."""

from _research_paths import workspace, output_root, game_path
import argparse
import bisect
import hashlib
import json
from pathlib import Path
import capstone
import pefile


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('selectors', nargs='+')
    ap.add_argument('--binary', type=Path, default=(workspace() / 'work/evidence/GameAssembly.dll'))
    ap.add_argument('--script', type=Path, default=(workspace() / 'work/decompiled/script.json'))
    ap.add_argument('--out', type=Path, default=(workspace() / 'results/protocol/avatar-native-evidence.json'))
    ap.add_argument('--max-bytes', type=int, default=65536)
    args = ap.parse_args()
    pe = pefile.PE(str(args.binary), fast_load=True)
    base = pe.OPTIONAL_HEADER.ImageBase
    script = json.loads(args.script.read_text(encoding='utf-8-sig'))
    methods = {}
    for item in script['ScriptMethod']:
        methods.setdefault(base + item['Address'], []).append(item['Name'])
    starts = sorted(methods)
    strings = {base+x['Address']: x['Value'] for x in script['ScriptString']}
    metadata = {base+x['Address']: x['Name'] for x in script['ScriptMetadata']}
    cs = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    cs.detail = True
    records = []
    for start, names in methods.items():
        if not any(selector in name for name in names for selector in args.selectors):
            continue
        end = min(starts[bisect.bisect_right(starts,start)] if start!=starts[-1] else start+args.max_bytes, start+args.max_bytes)
        offset = pe.get_offset_from_rva(start-base)
        raw = pe.__data__[offset:offset+end-start]
        instructions=[]
        for ins in cs.disasm(raw,start):
            refs=[]
            for op in ins.operands:
                if op.type==capstone.x86.X86_OP_IMM and op.imm in methods:
                    aliases=methods[op.imm]
                    refs.append({'kind':'method-target','va':hex(op.imm),'names':aliases[:20],'total_aliases':len(aliases)})
                elif op.type==capstone.x86.X86_OP_MEM and op.mem.base==capstone.x86.X86_REG_RIP:
                    ptr=ins.address+ins.size+op.mem.disp
                    if ptr in strings:
                        refs.append({'kind':'il2cpp-string-slot','va':hex(ptr),'value':strings[ptr]})
                    elif ptr in metadata:
                        refs.append({'kind':'il2cpp-metadata-slot','va':hex(ptr),'name':metadata[ptr]})
            instructions.append({'va':hex(ins.address),'bytes':ins.bytes.hex(),'mnemonic':ins.mnemonic,'operands':ins.op_str,'references':refs})
        matching_names=[n for n in names if any(s in n for s in args.selectors)]
        records.append({'names':matching_names,'total_aliases':len(names),'va':hex(start),'rva':hex(start-base),'file_offset':offset,'slice_length':len(raw),'slice_sha256':hashlib.sha256(raw).hexdigest(),'instructions':instructions})
    result={'artifact':str(args.binary.resolve()),'sha256':hashlib.sha256(args.binary.read_bytes()).hexdigest(),'image_base':hex(base),'evidence_type':'static bounded x64 disassembly','limitations':['Slice ends are the next known Il2CppDumper method address or analyst maximum, not authoritative function ranges.','Metadata names and string-slot interpretations do not establish runtime execution.'],'records':records}
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,indent=2),encoding='utf-8')
    for rec in records:
        literals=sorted(set(r['value'] for i in rec['instructions'] for r in i['references'] if r['kind']=='il2cpp-string-slot'))
        print(json.dumps({'names':rec['names'],'va':rec['va'],'slice_length':rec['slice_length'],'literals':literals}))

if __name__=='__main__':
    main()
