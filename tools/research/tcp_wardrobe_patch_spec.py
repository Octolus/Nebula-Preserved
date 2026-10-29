"""Static byte/xref audit only. Produces a patch specification; changes no binary."""

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
BINARY = ROOT / 'work/evidence/GameAssembly.dll'
OUT = ROOT / 'results/protocol/tcp-wardrobe-patch.json'
data = BINARY.read_bytes()
pe = pefile.PE(data=data)
base = pe.OPTIONAL_HEADER.ImageBase
metadata = json.loads((ROOT / 'work/decompiled/script.json').read_text(encoding='utf-8-sig'))
names = {}
for m in metadata['ScriptMethod']:
    names.setdefault(m['Address'], []).append(m['Name'])
starts = sorted(names)
targets = {0x6083d0: 'HTTPGetAllInWardrobe.Process', 0x5dfbf0: 'OnConnectedProcessor.GetAllInWardrobe', 0x5e02f0: 'OnConnectedProcessor.ProcessAllInWardrobe', 0x5e09b0: 'OnConnectedProcessor wardrobe callback'}
slots = {0x24e0668: 'HTTPGetAllInWardrobe.TypeInfo', 0x250e6e0: 'OnConnectedProcessor wardrobe callback MethodInfo'}
rows = []
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
for section in pe.sections:
    if not section.Characteristics & 0x20000000:
        continue
    raw = section.get_data()
    for found in re.finditer(rb'[\xe8\xe9]', raw):
        p = found.start()
        if p + 5 > len(raw):
            continue
        rva = section.VirtualAddress + p
        dest = rva + 5 + struct.unpack_from('<i', raw, p + 1)[0]
        if dest not in targets:
            continue
        method = starts[bisect.bisect_right(starts, rva)-1]
        rows.append({'kind': 'direct-call/tail-jump candidate', 'rva': hex(rva), 'target_rva': hex(dest), 'target': targets[dest], 'method_rva': hex(method), 'method_names': names[method]})
    for found in re.finditer(rb'[\x48-\x4f][\x8b\x8d][\x05\x0d\x15\x1d\x25\x2d\x35\x3d]', raw):
        p = found.start()
        if p + 7 > len(raw):
            continue
        rva = section.VirtualAddress + p
        dest = rva + 7 + struct.unpack_from('<i', raw, p + 3)[0]
        if dest not in slots:
            continue
        method = starts[bisect.bisect_right(starts, rva)-1]
        ins = next(md.disasm(raw[p:p+7], base+rva))
        rows.append({'kind': 'RIP-relative metadata-slot reference', 'rva': hex(rva), 'target_rva': hex(dest), 'target': slots[dest], 'instruction': f'{ins.mnemonic} {ins.op_str}', 'method_rva': hex(method), 'method_names': names[method]})

rva = 0x608323
offset = pe.get_offset_from_rva(rva)
old = data[offset:offset+2]
new = bytes.fromhex('7f4e')
assert old == bytes.fromhex('7d4e'), old.hex()
changed = bytearray(data)
changed[offset:offset+2] = new
start = pe.get_offset_from_rva(0x608270)
end = pe.get_offset_from_rva(0x6083d0)
sha = lambda b: hashlib.sha256(b).hexdigest()
spec = {
  'scope': 'Static patch specification only. No game DLL loaded/executed, binary file modified, or client/server/protocol test run.',
  'binary': {'path': str(BINARY.relative_to(ROOT)), 'size':len(data), 'sha256':sha(data), 'preferred_image_base':hex(base)},
  'patch': {'method':'HTTPGetAllInWardrobe.OnResponse', 'method_rva':'0x608270', 'instruction_rva':hex(rva), 'instruction_va':hex(base+rva), 'file_offset':offset, 'file_offset_hex':hex(offset), 'original_hex':old.hex(), 'replacement_hex':new.hex(), 'original_disassembly':'jge 0x180608373', 'replacement_disassembly':'jg 0x180608373', 'change':'Only condition opcode byte7d->7f; displacement4e and all bounds checks retained.', 'original_instruction_sha256':sha(old), 'replacement_instruction_sha256':sha(new), 'context_start_rva':hex(rva-12), 'context_original_hex':data[offset-12:offset+2+12].hex(), 'context_original_sha256':sha(data[offset-12:offset+2+12]), 'original_bounded_method_sha256':sha(data[start:end]), 'replacement_bounded_method_sha256':sha(changed[start:end]), 'bounded_method_end_rva':'0x6083d0', 'hypothetical_single_patch_full_file_sha256':sha(changed)},
  'bounds_proof': ['Let L=input string[].Length; existing guard requires L>1 and input[1] nonempty.', 'Output allocation length M=L-1 at0x6082f8..0x608304. EDI/EAX initialize i=1 at0x60830c..0x608311.', 'Original cmp i,M at0x608320 then JGE exits on i>=M, so copies i1..M-1 to output0..M-2 and leaves output[M-1] null.', 'JG exits on i>M, so patched loop copies i1..M to output0..M-1.', 'For last copied i=M=L-1, source check0x608325 requires i<L, true; destination check0x608353 requires i-1<M, true. Neither bound check needs changing.', 'Increment at0x60836d and backward jump0x608371 return to same compare. Callback receives fully initialized M-element array.'],
  'response_contract': {'empty':'OK# (field1 empty; callback suppressed; unchanged by patch)', 'nonempty_patched':'OK#<PlayerLabelJson1>#...#<PlayerLabelJsonN> with NO final #', 'nonempty_original':'Every nonempty result leaves a final null element regardless of response trailer. Trailer only affects how many valid elements copy before null.', 'element_type':'JsonClasses.PlayerLabelJson JSON object, NOT bare GUID', 'required_native_fields':['GUID','status','nameColorX','nameColorY','nameColorZ','lastPosX','lastPosY','lastPosZ','gender'], 'declared_other_fields':['userName','mood'], 'ghost_dependency':'Nonlocal GUID must already exist in Memory.playerInfos; SetWardrobeGhost uses dictionary indexer.'},
  'null_consumer_evidence': {'consumer_rva':'0x5e02f0', 'delegate_callback_rva':'0x5e09b0', 'generic_json_wrapper_rva':'0x878180', 'json_fromjson_rva':'0x1bda950', 'finding':'No per-element null/empty guard. JsonUtility.FromJson returns null for null/empty JSON; consumer null-result branch reaches FUN_180287300 instead of continuing.', 'json_null_check':'IsNullOrEmpty call0x1bda992; true branch0x1bda999->0x1bdaa3a returnsnull.', 'source_null_slot_skip_safe':False},
  'xref_scope':'Executable-section direct E8/E9 candidates plus common 64-bit RIP-relative MOV/LEA references to exact TypeInfo and callback MethodInfo slots. Nearest preceding metadata method labels are candidates; this is not a global proof against reflection, indirect, inlined or uncommon encodings.',
  'xref_candidates': sorted(rows, key=lambda r:int(r['rva'],16)),
  'evidence_files': [{'path':str(p.relative_to(ROOT)), 'sha256':sha(p.read_bytes())} for p in [ROOT/'results/protocol/tcp-wardrobe-native.json',ROOT/'work/evidence/ghidra/functions/608270.c',ROOT/'work/evidence/ghidra/functions/5e02f0.c',ROOT/'work/evidence/ghidra/functions/5e09b0.c',ROOT/'work/evidence/ghidra/functions/5dfdc0.c',ROOT/'work/evidence/ghidra/functions/5dfbf0.c',ROOT/'work/evidence/ghidra/functions/5e0760.c']],
}
OUT.write_text(json.dumps(spec, indent=2)+'\n', encoding='utf-8')
print(json.dumps({'output':str(OUT), 'offset':hex(offset), 'original':old.hex(), 'replacement':new.hex(), 'xref_candidates':len(rows)}))
for row in sorted(rows,key=lambda r:int(r['rva'],16)):
    print(row['kind'],row['rva'],row['target'],row['method_rva'],row['method_names'][:3])
