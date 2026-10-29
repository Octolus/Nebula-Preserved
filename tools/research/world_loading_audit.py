"""Read-only selection/hash inventory for the static world-loading audit."""

from _research_paths import workspace, output_root, game_path
import json
import hashlib
from pathlib import Path

ROOT = workspace()
OUT = ROOT / 'results/protocol'
META = ROOT / 'work/decompiled/script.json'
GHIDRA = ROOT / 'work/evidence/ghidra/functions'
methods = json.loads(META.read_text(encoding='utf-8'))['ScriptMethod']
prefixes = ('Assets.Scripts.Scene.Scenes', 'SpaceLoaderManager', 'SpacePREFAB', 'Booter',
            'Assets.Scripts.Boot.GameMusicInstantiator', 'PreInitLOAD',
            'ResourcesLoader', 'Assets.Scripts.NebulaAssetBundle.NebulaAssetBundleManager', 'loadbalancerConn',
            'Assets.Scripts.HTTPs.Tasks.N2.HTTPLoadSpace',
            'Assets.Scripts.HTTPs.Tasks.HTTPSpaceLoading')
exact = ('NETGcloudLogin$$LoadSpace', 'NETGcloudLogin$$JoinSpace',
         'NETGcloudLogin.<>c__DisplayClass31_0$$<JoinSpace>b__0',
         'NETGcloudLogin.<WaitUntilAllUnloaded>d__32$$MoveNext',
         'ManagerInstance$$Connect', 'ManagerInstance$$TCPInit',
         'ManagerInstance$$TCPInitialize', 'ManagerInstance$$OnClientConnect',
         'ManagerInstance$$InitPlayerTCP', 'ManagerInstance$$Launch',
         'NebulaPlayer$$Awake', 'NebulaPlayer$$Start', 'NebulaPlayer$$SetPlayer',
         'NebulaPlayer$$LoadAvatar', 'MANAGERLogin.<>c$$<LoginProcess>b__46_1')
selected = []
for m in methods:
    n = m['Name']
    if not (n.startswith(prefixes) or n in exact or 'OnConnectedProcessor' in n):
        continue
    if any(v in n for v in ('get_Current', 'Reset', 'Dispose', '.ctor', 'SetStateMachine')):
        continue
    p = GHIDRA / f"{m['Address']:x}.c"
    selected.append(dict(name=n, rva=f"0x{m['Address']:x}",
                         signature=m['Signature'], pseudocode_exists=p.exists(),
                         pseudocode=str(p.relative_to(ROOT)),
                         pseudocode_sha256=hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None))
(OUT / 'world-loading-methods.json').write_text(json.dumps(selected, indent=2)+'\n', encoding='utf-8')
for m in selected:
    print(m['rva'], 'OK' if m['pseudocode_exists'] else 'MISSING', m['name'])
