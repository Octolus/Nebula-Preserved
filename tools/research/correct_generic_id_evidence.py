"""Record native counter initialization and correct the older one-based report."""

from _research_paths import workspace, output_root, game_path
import hashlib
import json
from pathlib import Path
import re

ROOT = workspace()
OUT = ROOT/'results'
NATIVE = ROOT/'work/evidence/ghidra/functions'

def main():
    ctor = (NATIVE/'5df620.c').read_text(encoding='utf-8')
    if 'param_1 + 0x38) = 0xffffffffffffffff' not in ctor:
        raise ValueError('Native paired Int32 counter initialization evidence changed')
    path = OUT/'protocol/tcp-world-interactions.json'
    report = json.loads(path.read_text(encoding='utf-8'))
    def correct(value):
        if isinstance(value,dict): return {k:correct(v) for k,v in value.items()}
        if isinstance(value,list): return [correct(v) for v in value]
        if isinstance(value,str): return value.replace('IDs1..N','IDs0..N-1').replace('ID1..N','ID0..N-1').replace('bounded1..N','bounded0..N-1')
        return value
    report = correct(report)
    report['generic_id_assignment']['counter_initialization'] = 'NebulaInteractor.ctor5df620 writes UInt64 -1 at+0x38, initializing both Int32 counters(+0x38,+0x3c) to-1. Initialize5decf0 does not reset them. AddGeneric preincrements, so first ID is0 and static count N permits0..N-1.'
    report['generic_id_assignment']['late_registration'] = 'HousingFurnishing.SaveAtServer6bdb40 initializes GenericInteractable components in placed housing children. These dynamic IDs require a verified registry expansion.'
    evidence = report['native_evidence'] if 'native_evidence' in report else None
    report['generic_id_counter_evidence'] = [
        {'rva':'0x'+rva,'path':str((NATIVE/(rva+'.c')).relative_to(ROOT)).replace('\\','/'),
         'sha256':hashlib.sha256((NATIVE/(rva+'.c')).read_bytes()).hexdigest()}
        for rva in ['5df620','5deab0','5decf0','6bdb40']]
    source = OUT/'mirror-server/UnityProject/Assets/Preservation/NebulaWorldState.cs'
    report['corrected_module_sha256'] = hashlib.sha256(source.read_bytes()).hexdigest()
    path.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    md = OUT/'protocol/tcp-world-interactions.md'
    text = md.read_text(encoding='utf-8').replace('IDs1..N','IDs0..N-1')
    text = re.sub(r'\| 1\.\.(\d+) \|',lambda m:'| 0..'+str(int(m.group(1))-1)+' |',text)
    marker = '**Native counter correction:**'
    if marker not in text:
        text += '\n'+marker+' `NebulaInteractor.ctor5df620` initializes both Int32 counters to -1 with one UInt64 write at+0x38. `AddGenericInteractable5deab0` preincrements the counter at+0x3c. The first wire ID is therefore0, and a static N-object registry accepts0..N-1. `Initialize5decf0` does not reset the counter. Placed housing components can register later through `HousingFurnishing.SaveAtServer6bdb40`; static bounds do not authorize those dynamic IDs.\n'
    md.write_text(text,encoding='utf-8')
    print('Native zero-based generic-ID correction recorded')

if __name__ == '__main__': main()
