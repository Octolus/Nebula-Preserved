"""Inspect nine unresolved wardrobe prefab headers without exporting textures."""

from _research_paths import workspace, output_root, game_path
import hashlib
import json
from pathlib import Path
import UnityPy


def main():
    dest=(workspace() / 'results/protocol')
    root=game_path('Nebula Realms_Data/StreamingAssets/StandaloneWindows')
    catalog=json.loads((dest/'avatar-asset-catalog.json').read_text())
    results=[]
    for entry in catalog['summary']['unresolved_categories']:
        path=root/entry['bundle']
        env=UnityPy.load(str(path))
        row={**entry,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
             'gameobjects':[],'renderers':[],'materials':[],'components':[]}
        for obj in env.objects:
            if obj.type.name=='GameObject':
                go=obj.read()
                row['gameobjects'].append({'path_id':obj.path_id,'name':go.m_Name})
            elif obj.type.name in ('MeshRenderer','SkinnedMeshRenderer'):
                data=obj.read()
                tree=obj.read_typetree()
                row['renderers'].append({'class':obj.type.name,'name':data.m_GameObject.deref_parse_as_object().m_Name,
                    'bone_names':[x.deref_parse_as_object().m_GameObject.deref_parse_as_object().m_Name for x in getattr(data,'m_Bones',[]) if x.path_id],
                    'blend_weights_count':len(tree.get('m_BlendShapeWeights',[]))})
            elif obj.type.name=='Material':
                row['materials'].append({'path_id':obj.path_id,'name':obj.read_typetree()['m_Name']})
            elif obj.type.name=='MonoBehaviour':
                data=obj.read(check_read=False)
                script=data.m_Script.deref_parse_as_object()
                try:fields=obj.read_typetree()
                except Exception as error:fields={'typetree_error':type(error).__name__}
                row['components'].append({'class':script.m_ClassName,'fields':fields})
        results.append(row)
    (dest/'avatar-unresolved-prefabs.json').write_text(json.dumps({'evidence_type':'static serialized prefab metadata, not inferred category assignments','items':results},indent=2),encoding='utf-8')
    print(json.dumps([{'id':r['item_id'],'components':[x['class'] for x in r['components']],'renderers':[x['name'] for x in r['renderers']],'materials':[x['name'] for x in r['materials']]} for r in results]))


if __name__=='__main__':main()
