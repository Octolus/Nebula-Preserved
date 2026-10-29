"""Read-only minigame manager/table inventory. Never starts Unity or the game."""

from _research_paths import workspace, output_root, game_path
import collections
import gc
import hashlib
import json
from pathlib import Path
import UnityPy

ROOT = workspace()
BASE = game_path('Nebula Realms_Data/StreamingAssets/StandaloneWindows')
OUT = ROOT/'results/protocol/minigame-scene.json'
WANTED = {'BoardGamesManager','BoardGamesTable','DartsGameManager','DartsGameTable','PoolGameManager','PoolGameTable','BowlingGameManager','BowlingGameTable'}
reports=[]
for name in ('s/nexus','s/nexuslogicprefab','s/bowling','s/bowlinglogicprefab','s/leafpark','s/leafparklogicprefab'):
    path=BASE/name
    if not path.exists():
        reports.append({'bundle':name,'missing':True})
        continue
    env=UnityPy.load(str(path))
    objects={(o.assets_file.name,o.path_id):o for o in env.objects}
    classes=collections.Counter()
    errors=collections.Counter()
    class_errors=collections.Counter()
    relevant=[]
    for obj in env.objects:
        if obj.type.name!='MonoBehaviour':
            continue
        try:
            script=obj.read(check_read=False).m_Script.deref_parse_as_object()
            cls=script.m_ClassName
            classes[cls]+=1
        except Exception as error:
            class_errors[type(error).__name__]+=1
            continue
        # Classify using the native MonoBehaviour header first. Many unrelated
        # managed UI fields have UnityPy typetree limitations; those are not
        # needed to establish which minigame manager/table classes are present.
        if cls not in WANTED and not cls.endswith('Manager'):
            continue
        try:
            tree=obj.read_typetree()
            if cls not in WANTED and 'gameTables' not in tree:
                continue
            row={'class':cls,'asset_file':obj.assets_file.name,'path_id':obj.path_id,'raw_sha256':hashlib.sha256(obj.get_raw_data()).hexdigest()}
            for field in ('m_GameObject','m_Enabled','gameTables','tableData','players','cabinetDarts','spaceTypeGame','rulesPrefabs'):
                if field in tree:
                    row[field]=tree[field]
            game_object=objects.get((obj.assets_file.name,tree.get('m_GameObject',{}).get('m_PathID')))
            if game_object:
                go=game_object.read_typetree()
                row['game_object_name']=go.get('m_Name')
                row['active_self']=go.get('m_IsActive')
            if 'gameTables' in tree:
                row['configured_table_count']=len(tree['gameTables'])
            relevant.append(row)
        except Exception as error:
            errors[type(error).__name__]+=1
    reports.append({'bundle':name,'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'containers':list(env.container),'mono_behaviours_classified':sum(classes.values()),'class_counts':dict(sorted(classes.items())),'class_resolution_errors':dict(class_errors),'relevant_field_parse_errors':dict(errors),'minigames':relevant,'board_manager_configured_counts':[x['configured_table_count'] for x in relevant if x['class']=='BoardGamesManager' and 'configured_table_count' in x],'darts_manager_configured_counts':[x['configured_table_count'] for x in relevant if x['class']=='DartsGameManager' and 'configured_table_count' in x]})
    print(name,sum(classes.values()),'classified; class errors',dict(class_errors),'relevant field errors',dict(errors),';',[(x['class'],x.get('configured_table_count')) for x in relevant],flush=True)
    del env,objects
    gc.collect()
result={'scope':'Read-only serialized asset inventory, not runtime observations. Modern active paths only, not s/pre variants. Every MonoBehaviour is classified using its native header/MonoScript first; managed typetrees are then parsed only for relevant minigame/table classes or Manager classes. Empty manager/count arrays mean no such class present among successfully classified components, not a guessed positive count. Check both error counters before making absence claims. No game, server, listener or connection was executed.','bundles':reports,'source_binary_sha256':'c4dd5db599e5e5ce4adf25f09ffe70ad10e0928adf6a2e862176d537026b44ac'}
OUT.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(OUT)
