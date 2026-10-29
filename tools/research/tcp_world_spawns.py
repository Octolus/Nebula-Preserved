"""Read-only Unity scene/prefab spawn-point extraction; never starts Unity/game."""

from _research_paths import workspace, output_root, game_path
import hashlib
import json
from pathlib import Path
import UnityPy

ROOT = workspace()
BUNDLES = game_path('Nebula Realms_Data/StreamingAssets/StandaloneWindows')
OUT = ROOT / 'results/protocol/tcp-world-spawn-assets.json'

def mul(a,b):
    x,y,z,w = a
    X,Y,Z,W = b
    return [w*X+x*W+y*Z-z*Y,w*Y-x*Z+y*W+z*X,w*Z+x*Y-y*X+z*W,w*W-x*X-y*Y-z*Z]

def rot(q,v):
    r=mul(mul(q,list(v)+[0]),[-q[0],-q[1],-q[2],q[3]])
    return r[:3]

def vector(d,keys='xyz'):
    return [d[k] for k in keys]

reports=[]
for name in ['s/nexus','s/nexuslogicprefab']:
    path=BUNDLES/name
    env=UnityPy.load(str(path))
    objects={(o.assets_file.name,o.path_id):o for o in env.objects}
    gos={}
    transforms={}
    controllers=[]
    for o in env.objects:
        if o.type.name=='GameObject':
            gos[(o.assets_file.name,o.path_id)]=o.read_typetree()
        elif o.type.name in ['Transform','RectTransform']:
            transforms[(o.assets_file.name,o.path_id)]=o.read_typetree()
        elif o.type.name=='MonoBehaviour':
            try:
                d=o.read_typetree()
                if 'spawnPoints' in d:
                    script=o.read(check_read=False).m_Script.deref_parse_as_object()
                    controllers.append({'asset_file':o.assets_file.name,'path_id':o.path_id,'class':script.m_ClassName,'namespace':script.m_Namespace,'raw_sha256':hashlib.sha256(o.get_raw_data()).hexdigest(),'game_object':d.get('m_GameObject'),'spawnPoints':d['spawnPoints']})
            except Exception:
                pass
    def tree_record(file,pid):
        d=transforms[(file,pid)]
        go=gos.get((file,d['m_GameObject']['m_PathID']),{})
        return {'asset_file':file,'transform_path_id':pid,'game_object_path_id':d['m_GameObject']['m_PathID'],'name':go.get('m_Name'),'active_self':go.get('m_IsActive'),'local_position':d['m_LocalPosition'],'local_rotation':d['m_LocalRotation'],'local_scale':d['m_LocalScale'],'father':d['m_Father'],'raw_sha256':hashlib.sha256(objects[(file,pid)].get_raw_data()).hexdigest()}
    for c in controllers:
        c['resolved_spawn_points']=[]
        for index,p in enumerate(c['spawnPoints']):
            point={'index':index,'reference':p}
            if p['m_FileID']!=0 or (c['asset_file'],p['m_PathID']) not in transforms:
                point['resolution_error']='external or missing transform; no fabricated coordinates'
            else:
                file=c['asset_file']
                pid=p['m_PathID']
                d=transforms[(file,pid)]
                position=vector(d['m_LocalPosition'])
                rotation=vector(d['m_LocalRotation'],'xyzw')
                ancestry=[tree_record(file,pid)]
                parent=d['m_Father']
                while parent['m_PathID']:
                    if parent['m_FileID']!=0 or (file,parent['m_PathID']) not in transforms:
                        point['resolution_error']='ancestry has external/missing transform'
                        break
                    pid=parent['m_PathID']
                    d=transforms[(file,pid)]
                    scale=vector(d['m_LocalScale'])
                    pos=vector(d['m_LocalPosition'])
                    q=vector(d['m_LocalRotation'],'xyzw')
                    position=[a+b for a,b in zip(rot(q,[a*b for a,b in zip(position,scale)]),pos)]
                    rotation=mul(q,rotation)
                    ancestry.append(tree_record(file,pid))
                    parent=d['m_Father']
                point.update({'ancestry_leaf_to_root':ancestry,'computed_world_position':position,'computed_world_rotation':rotation,'computed_forward':rot(rotation,[0,0,1]),'coordinate_basis':'Static Unity Transform local TRS hierarchy; prefab coordinates assume root instantiated without additional parent transform.'})
            c['resolved_spawn_points'].append(point)
    report={'bundle':name,'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'containers':list(env.container),'controllers':controllers,'named_spawn_transforms':[tree_record(file,pid) for (file,pid),d in transforms.items() if 'spawn' in gos.get((file,d['m_GameObject']['m_PathID']),{}).get('m_Name','').lower()]}
    reports.append(report)
    print(name,'controllers',[(c['class'],len(c['spawnPoints'])) for c in controllers],'named spawn transforms',len(report['named_spawn_transforms']))
OUT.write_text(json.dumps({'scope':'Read-only serialized Unity asset evidence, not observed runtime scene transforms. No game/client/server launched.','bundles':reports},indent=2)+'\n',encoding='utf-8')
print(OUT)
