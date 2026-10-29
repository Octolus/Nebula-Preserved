"""Read-only E8/E9 candidates and known constants; not a callgraph completeness proof."""

from _research_paths import workspace, output_root, game_path
import bisect, hashlib, json, re, struct
from pathlib import Path
import pefile
ROOT=workspace()
raw=(ROOT/'work/evidence/GameAssembly.dll').read_bytes()
pe=pefile.PE(data=raw)
meta=json.loads((ROOT/'work/decompiled/script.json').read_text(encoding='utf-8'))
names={}
for m in meta['ScriptMethod']:
    names.setdefault(m['Address'],[]).append(m['Name'])
starts=sorted(names)
targets={0x12499a0:'loadbalancerConn.get_DevIp',0x12499d0:'loadbalancerConn.get_Ip',0x1249a00:'loadbalancerConn.get_port',
0x63beb0:'HTTPSpaceLoading.JoinSpace',0x3d54b0:'NETGcloudLogin.JoinSpace',0x46b4b0:'SpaceLoaderManager.JoinSpace',
0x635bf0:'HTTPLoadSpace.Process',0x5e9800:'Scenes.Load.MoveNext',0x611310:'NebulaAssetBundleManager.Initialize',
0x5e59f0:'Scenes.Initialize',0x4dc2f0:'ResourcesLoader.LoadDependenciesBundles',
0x648800:'AssetBundles.AssetBundleManager.SetDevelopmentAssetBundleServer',
0x6477f0:'AssetBundles.AssetBundleManager.Initialize()',0x6474e0:'AssetBundles.AssetBundleManager.Initialize(string)',
0x648b80:'AssetBundles.AssetBundleManager.SetSourceAssetBundleURL',0x648a20:'AssetBundles.AssetBundleManager.SetSourceAssetBundleDirectory',
0x68b0c0:'Booter.LoadScreenLoader',0x68b010:'Booter.LoadPooler',
0x5e5e10:'Scenes.LoadScreenLoader',0x5e5d40:'Scenes.LoadPooler'}
calls=[]
for s in pe.sections:
    if not s.Characteristics & 0x20000000: continue
    d=s.get_data()
    for match in re.finditer(rb'[\xe8\xe9]',d):
        i=match.start()
        if i+5>len(d):continue
        site=s.VirtualAddress+i
        t=site+5+struct.unpack_from('<i',d,i+1)[0]
        if t not in targets:continue
        ix=bisect.bisect_right(starts,site)-1
        owner=starts[ix] if ix>=0 else None
        calls.append(dict(site=hex(site),target=hex(t),target_name=targets[t],
                          nearest_method=hex(owner) if owner else None,
                          nearest_method_names=names[owner] if owner else [],
                          opcode=hex(d[i])))
consts={}
for rva in [0x1dd2c74,0x1dd2ce4,0x1dd2c5c]:
    b=pe.get_data(rva,4)
    consts[hex(rva)]=dict(raw=b.hex(),float32=struct.unpack('<f',b)[0])
out=dict(binary_sha256=hashlib.sha256(raw).hexdigest(),
         scope='All executable-section byte-position E8/E9 matches. Candidates are assigned nearest preceding metadata method and may include false positives or generic wrappers. Not indirect/virtual/inlined call coverage.',
         candidates=calls, constants=consts,
         loadbalancer_type_metadata=[m for m in meta['ScriptMetadata'] if 'LOADBALANCER' in m['Name']])
(ROOT/'results/protocol/world-loading-xrefs.json').write_text(json.dumps(out,indent=2)+'\n',encoding='utf-8')
print(json.dumps(out,indent=2))
