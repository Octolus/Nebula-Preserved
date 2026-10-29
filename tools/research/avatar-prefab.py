"""Read serialized avatar transforms, blend weights and material parameters.

No target executable is started. Texture payloads are never exported.
"""

from _research_paths import workspace, output_root, game_path
import argparse
import hashlib
import json
from pathlib import Path
import UnityPy


def vector(v):
    return {k:float(getattr(v,k)) for k in ('x','y','z')}


def hierarchy(transform):
    go=transform.m_GameObject.deref_parse_as_object()
    row={'name':go.m_Name,'transform_path_id':transform.object_reader.path_id,
         'local_position':vector(transform.m_LocalPosition),'local_scale':vector(transform.m_LocalScale),
         'local_rotation':{k:float(getattr(transform.m_LocalRotation,k)) for k in ('x','y','z','w')},
         'children':[]}
    for child in transform.m_Children:
        row['children'].append(hierarchy(child.deref_parse_as_object()))
    return row


def material_rows(env):
    names={}
    for obj in env.objects:
        if obj.type.name=='Texture2D':
            # m_Name is the first aligned Unity string in a Texture2D object.
            # Read its small header rather than decoding or retaining image data.
            raw=obj.get_raw_data()
            length=int.from_bytes(raw[:4],'little',signed=True)
            if 0<=length<4096:
                names[(obj.assets_file.name,obj.path_id)]=raw[4:4+length].decode('utf-8','replace')
    rows=[]
    for obj in env.objects:
        if obj.type.name!='Material':continue
        tree=obj.read_typetree()
        tex={}
        for key,value in tree.get('m_SavedProperties',{}).get('m_TexEnvs',[]):
            ptr=value['m_Texture']
            tex[key]=names.get((obj.assets_file.name,ptr['m_PathID'])) if ptr['m_FileID']==0 else None
        rows.append({'name':tree['m_Name'],'path_id':obj.path_id,'shader_ref':tree['m_Shader'],
                     'properties':tree.get('m_SavedProperties'),'texture_names':tex})
    return rows


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--game',type=Path,default=game_path(''))
    ap.add_argument('--out',type=Path,default=(workspace() / 'results/protocol/avatar-prefab-baselines.json'))
    args=ap.parse_args()
    root=args.game/'Nebula Realms_Data/StreamingAssets/StandaloneWindows'
    editor=root/'s/charactereditor'
    env=UnityPy.load(str(editor))
    bases={}
    for obj in env.objects:
        if obj.type.name!='GameObject' or obj.assets_file.name!='BuildPlayer-CharacterEditor.sharedAssets' or obj.path_id not in (1386,1363):continue
        go=obj.read()
        for pair in go.m_Component:
            reader=pair.component.deref()
            if reader.type.name=='Transform':
                bases[go.m_Name]=hierarchy(reader.read())
    skin=root/'skinmaterials'
    env=UnityPy.load(str(skin))
    materials=material_rows(env)
    defaults=json.loads((args.out.parent/'avatar-default-catalog.json').read_text())
    wardrobe_materials={}
    wardrobe_components={}
    for gender,data in defaults['defaults'].items():
        for item in data['items']:
            env=UnityPy.load(str(root/item['bundle']))
            wardrobe_materials[item['item_id']]=material_rows(env)
            components=[]
            for obj in env.objects:
                if obj.type.name!='MonoBehaviour':continue
                try:
                    data=obj.read(check_read=False)
                    script=data.m_Script.deref_parse_as_object()
                    if script.m_ClassName in ('HighHeel','HandType','AssetsLoaded'):
                        components.append({'class':script.m_ClassName,'path_id':obj.path_id,'fields':obj.read_typetree()})
                except Exception:
                    pass
            wardrobe_components[item['item_id']]=components
    heads={}
    for name in ['sl0d2k3asbb756yb2qj0lchsilskw5cf','fvylwil15ue3u70354tjwixin8y8k5c4']:
        path=root/'04'/name
        env=UnityPy.load(str(path))
        rows=[]
        for obj in env.objects:
            if obj.type.name!='SkinnedMeshRenderer':continue
            tree=obj.read_typetree()
            try:go=obj.read().m_GameObject.deref_parse_as_object().m_Name
            except Exception:go=None
            rows.append({'name':go,'path_id':obj.path_id,'blend_shape_weights':tree.get('m_BlendShapeWeights'),
                         'mesh_ref':tree.get('m_Mesh'),'materials':tree.get('m_Materials')})
        heads[name]={'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'renderers':rows}
    result={'evidence_type':'serialized Unity prefab/material state; not server preset defaults and not runtime execution',
            'sources':{'editor':{'path':str(editor),'sha256':hashlib.sha256(editor.read_bytes()).hexdigest()},
                       'skinmaterials':{'path':str(skin),'sha256':hashlib.sha256(skin.read_bytes()).hexdigest()}},
            'bases':bases,'skin_materials':materials,'default_heads':heads,'wardrobe_materials':wardrobe_materials,'wardrobe_components':wardrobe_components,
            'limitations':['Serialized base transforms can seed a neutral local reconstruction after matching ReadMale/FemaleBonesNETGCloud semantics. They are not evidence of original server numeric defaults.','Material texture references are retained as identifiers; images are not extracted.']}
    args.out.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({'bases':list(bases),'material_count':len(materials),'head_renderers':{k:len(v['renderers']) for k,v in heads.items()}}))

if __name__=='__main__':
    main()
