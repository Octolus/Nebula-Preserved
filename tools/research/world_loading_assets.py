"""Read-only local bundle closure and Nexus loader component audit."""

from _research_paths import workspace, output_root, game_path
import hashlib, json
from pathlib import Path
import UnityPy
ROOT=workspace()
INSTALL=game_path('')
BASE=INSTALL/'Nebula Realms_Data/StreamingAssets/StandaloneWindows'
MANIFEST=ROOT/'work/evidence/assets/bundle-manifests.json'
manifest={x['bundle']:x for x in json.loads(MANIFEST.read_text(encoding='utf-8'))}
def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f,'sha256').hexdigest()
def norm(p):
    p=p.replace('\\','/')
    marker='/StandaloneWindows/'
    return p.split(marker,1)[1] if marker in p else p
roots=['screenloader','pooler','nav','skinmaterials','gamemusic','s/preinitiload','s/initload','s/login',
       's/nebulaplayer','s/nexus','s/nexuslogicprefab']
pending=list(roots); seen={}
while pending:
    key=pending.pop(0)
    if key in seen:continue
    row=manifest.get(key)
    path=BASE/key
    deps=[norm(x) for x in row['dependencies']] if row else []
    seen[key]=dict(bundle=key,path=str(path),exists=path.is_file(),size=path.stat().st_size if path.is_file() else None,
                   sha256=sha(path) if path.is_file() else None,manifest=row,
                   normalized_dependencies=deps)
    pending+=deps
components=[];errors=[]
env=UnityPy.load(str(BASE/'s/nexus'))
for obj in env.objects:
    if obj.type.name!='MonoBehaviour':continue
    try:
        header=obj.read(check_read=False)
        script=header.m_Script.deref_parse_as_object()
        cls=script.m_ClassName
        if cls not in ['SpacePREFAB','SpaceLoaderManager','SpaceLoaderBalancer']:continue
        tree=obj.read_typetree()
        go=header.m_GameObject.deref_parse_as_object()
        components.append(dict(asset_file=obj.assets_file.name,path_id=obj.path_id,class_name=cls,
                               raw_sha256=hashlib.sha256(obj.get_raw_data()).hexdigest(),
                               game_object_name=go.m_Name,game_object_active_self=go.m_IsActive,
                               fields=tree))
    except Exception as e:
        errors.append(dict(path_id=obj.path_id,error=type(e).__name__,detail=str(e)))
boot_components=[];boot_errors=[]
boot_path=INSTALL/'Nebula Realms_Data/level0'
boot_env=UnityPy.load(str(boot_path))
for obj in boot_env.objects:
    if obj.type.name!='MonoBehaviour':continue
    try:
        header=obj.read(check_read=False)
        script=header.m_Script.deref_parse_as_object()
        go=header.m_GameObject.deref_parse_as_object()
        record=dict(asset_file=obj.assets_file.name,path_id=obj.path_id,
                    class_name=script.m_ClassName,game_object_name=go.m_Name,
                    game_object_active_self=go.m_IsActive,
                    raw_size=obj.byte_size,
                    raw_sha256=hashlib.sha256(obj.get_raw_data()).hexdigest())
        boot_components.append(record)
        record['fields']=obj.read_typetree()
    except Exception as e:
        boot_errors.append(dict(path_id=obj.path_id,error=type(e).__name__,detail=str(e)))
optional='s/nexusspaceevent'
out=dict(scope='Static local file existence/hashes and text-manifest dependency closure; no Unity player, server or connections. Serialized component parsing errors preserved. Manifest source paths normalize build-machine prefixes only; engine resolution not simulated.',
         manifest_inventory_sha256=sha(MANIFEST),roots=roots,bundles=list(seen.values()),
         missing=[k for k,v in seen.items() if not v['exists']],
         optional_space_event=dict(bundle=optional,exists=(BASE/optional).is_file()),
         nexus_loader_components=components,nexus_mono_parse_errors=errors,
         built_in_boot_scene=dict(path=str(boot_path),sha256=sha(boot_path),
                                  components=boot_components,parse_errors=boot_errors))
(ROOT/'results/protocol/world-loading-assets.json').write_text(json.dumps(out,indent=2)+'\n',encoding='utf-8')
print(json.dumps(dict(bundle_count=len(seen),missing=out['missing'],components=components,errors=errors),indent=2))
