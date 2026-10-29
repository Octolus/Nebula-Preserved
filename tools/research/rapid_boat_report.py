"""Bind the prepared compatibility candidate to static evidence; no target execution."""
from __future__ import annotations

from _research_paths import workspace, output_root, game_path
import hashlib
import json
from pathlib import Path

ROOT = workspace()
OUT = ROOT / 'results'

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path): return json.loads(path.read_text(encoding='utf-8-sig'))

def main():
    manifest = read(OUT/'client-fixes/prepared-rapid-copy.json')
    checks = read(OUT/'client-fixes/rapid-boat-offline-tests.json')
    candidate = Path(manifest['copy_path'])
    if sha(candidate) != manifest['copy_sha256']:
        raise ValueError('Prepared candidate hash mismatch')
    if checks['assembly_source_sha256'] != manifest['assembly_source_sha256'] or checks['coff_sha256'] != manifest['coff_sha256']:
        raise ValueError('Offline model and prepared candidate use different wrapper inputs')
    sources = manifest['native_sources']
    for row in sources:
        if sha(ROOT/row['path']) != row['sha256']:
            raise ValueError('Native evidence changed: '+row['path'])
    names = ['client-fixes/prepared-rapid-copy.json','client-fixes/rapid-boat-offline-tests.json',
             'client-fixes/rapid_boat_exit.s','tools/rapid_boat_patch.py','tools/rapid_boat_offline_tests.py',
             'tools/tests/test_patch_safety.py','mirror-server/UnityProject/Assets/Preservation/NebulaInstanceServer.cs']
    report = {
        'format_version':1,
        'scope':'Authored same-build rapid-boat compatibility candidate. Static PE checks and synthetic instruction-model tests only.',
        'observed_static':[
            'Rapid FixedUpdate calls native Exit at RVA0x44c1ce. Native Exit0x545920 does not emit opcode31 False.',
            'The ordinary non-rapid exit path can emit31 False. The S2C31 False consumer ignores release.',
            'The replacement instance therefore needs a remote retire/reseed when a guarded rapid release arrives.'
        ],
        'authored_compatibility':[
            'Redirect only that call to a new RX section. Preserve all existing unwind entries and add the wrapper entry.',
            'Capture local actor/vehicle, call original Exit exactly once, recheck local identity and cleared vehicle, and require TCP connectivity.',
            'For the shipped rapid index0, allocate a managed UTF16 string through IL2CPP and send31#GUID#False#0 through the original TCP sender.',
            'The instance retires only other viewers, delays reseeding by at least two Unity frames, and filters transform delivery while reseeding.'
        ],
        'manifest':manifest,
        'synthetic_checks':{'passed':checks['tests_passed'],'scope':checks['scope'],'checks':checks['checks']},
        'independent_review':{
            'kind':'static source/PE/native-evidence review by a separate worker',
            'findings':'No high-confidence ABI, relocation, field-write or unwind defect found in the reviewed candidate. An output-path overwrite issue in --spec was found and fixed.',
            'coverage':['Both accepted input variants reproduced in memory','All seven native call targets checked','Original138029 runtime-function entries preserved plus one','Eight native evidence hashes checked'],
            'limitation':'A review result is not proof of native execution, GC safety or server/client timing.'},
        'path_guards':'All three copy tools reject existing/installed/source output paths; manifests require a new JSON destination. Five CLI tests exercise rejection with synthetic inputs.',
        'candidate_hash_matches':True,
        'installation_changed':False,'game_executed':False,'listener_started':False,'game_ready':False,
        'remaining_unknowns':[
            'Windows loader/unwinder and live IL2CPP garbage collector have not exercised the wrapper.',
            'Additional helper calls can throw before the original caller continuation; native unwind metadata propagates rather than swallows exceptions.',
            'Two-frame remote teardown/reseed sequencing, animation state and transform races require future runtime validation.',
            'This is a new preservation compatibility policy, not a recovered original server operation.'
        ],
        'sources':[{'path':name,'sha256':sha(OUT/name)} for name in names],
    }
    (OUT/'protocol/rapid-boat-compatibility.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    lines = ['# Rapid-boat release compatibility candidate','',report['scope'],'',
        'The native rapid-boat exit sends no release packet. The prepared client copy adds a guarded release through the original sender, and the replacement instance refreshes remote viewers because the shipped release receiver cannot do that itself. This is authored compatibility behavior, not original server parity.','',
        'The candidate includes the separately reviewed wardrobe loop fix. It is a private copy under `work/patched-client-rapid`; the installed Steam binary is unchanged. Candidate SHA256: `'+manifest['copy_sha256']+'`.','',
        'Static checks cover PE layout, call relocations, instruction boundaries, stack alignment, unwind metadata and preservation of existing data. A synthetic instruction model passes '+str(checks['tests_passed'])+' cases using stubbed native functions; it executes no original game code. Independent review reproduced both supported input variants and found no high-confidence ABI or PE defect. Review did identify an output-path issue, now covered by rejection checks.','',
        'The new wrapper is486 bytes. The patch changes34 bytes within the old file and adds one RX section containing the wrapper and extended unwind table. It preserves all138029 original runtime-function records. The original exit is called exactly once; only a successful local index0 exit can send `31#GUID#False#0`.','',
        'Remaining limits: '+' '.join(report['remaining_unknowns']),'',
        'Full evidence and hashes: [report](rapid-boat-compatibility.json), [prepared-copy manifest](../client-fixes/prepared-rapid-copy.json), [synthetic checks](../client-fixes/rapid-boat-offline-tests.json), [instance reconstruction](../mirror-server/INSTANCE-RECONSTRUCTION.md).','']
    (OUT/'protocol/rapid-boat-compatibility.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps({'candidate_hash_matches':True,'synthetic_checks':checks['tests_passed'],'game_executed':False}))

if __name__ == '__main__': main()
