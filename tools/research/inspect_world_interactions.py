"""Read-only shipped Unity world interaction inventory. Never starts the game.

GenericInteractable network IDs are assigned at runtime by FindObjectsOfType
enumeration, not serialized path IDs. This tool deliberately does not guess them.
"""

from _research_paths import workspace, output_root, game_path
import argparse
import collections
import gc
import hashlib
import json
import re
from pathlib import Path
import UnityPy

ROOT = workspace()
BASE = game_path('Nebula Realms_Data/StreamingAssets/StandaloneWindows')


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--all-logic', action='store_true')
    parser.add_argument('--output', type=Path, default=ROOT/'work/evidence/world-interaction-assets.json')
    args = parser.parse_args()
    dump = ROOT/'work/decompiled/dump.cs'
    classes = dict(re.findall(r'^public (?:abstract |sealed )?class (\w+) : ([\w.]+)', dump.read_text(encoding='utf8'), re.M))

    def generic(name):
        seen = set()
        while name and name not in seen:
            if name == 'GenericInteractable':
                return True
            seen.add(name)
            name = classes.get(name)
        return False

    wanted = {name for name in classes if generic(name)} | {
        'HarbourEnter', 'HarbourExit', 'HarbourSelectBoat', 'BoatTripManager',
        'FoodTruckManager', 'OktoberFestManager', 'FoodTruckTrigger', 'OktoberFestTrigger',
    }
    manifests = json.loads((ROOT/'work/evidence/assets/bundle-manifests.json').read_text(encoding='utf8'))
    names = sorted(x['bundle'] for x in manifests if x['bundle'].startswith('s/') and not x['bundle'].startswith('s/pre') and x['bundle'].endswith('logicprefab')) if args.all_logic else ['s/nexuslogicprefab', 's/leafparklogicprefab', 's/beachlogicprefab']
    reports = []
    for name in names:
        path = BASE/name
        env = UnityPy.load(str(path))
        objects = {(o.assets_file.name, o.path_id): o for o in env.objects}
        roots = {(p.assetsfile.name, p.path_id) for p in env.container.values()}

        def hierarchy(file, go_pid):
            seen = set()
            ancestry = []
            active = True
            while go_pid and (file, go_pid) not in seen:
                key = (file, go_pid)
                seen.add(key)
                go = objects.get(key)
                if not go or go.type.name != 'GameObject':
                    return {'error':'missing_game_object', 'ancestry':ancestry}
                d = go.read_typetree()
                active = active and bool(d.get('m_IsActive'))
                ancestry.append({'path_id':go_pid,'name':d.get('m_Name'),'active_self':d.get('m_IsActive')})
                if key in roots:
                    return {'under_container_root':True,'active_in_prefab_hierarchy':active,'ancestry':ancestry}
                transform = None
                for entry in d.get('m_Component',[]):
                    ref = entry['component']
                    target = objects.get((file,ref['m_PathID'])) if ref['m_FileID'] == 0 else None
                    if target and target.type.name in ('Transform','RectTransform'):
                        transform = target.read_typetree()
                        break
                if not transform:
                    return {'error':'missing_transform','ancestry':ancestry}
                parent_ref = transform['m_Father']
                if not parent_ref['m_PathID']:
                    return {'under_container_root':False,'active_in_prefab_hierarchy':active,'ancestry':ancestry}
                parent = objects.get((file,parent_ref['m_PathID'])) if parent_ref['m_FileID'] == 0 else None
                if not parent:
                    return {'error':'external_or_missing_parent','ancestry':ancestry}
                go_pid = parent.read_typetree()['m_GameObject']['m_PathID']
            return {'error':'hierarchy_cycle','ancestry':ancestry}
        counts = collections.Counter()
        errors = []
        relevant = []
        for obj in env.objects:
            if obj.type.name != 'MonoBehaviour':
                continue
            try:
                script = obj.read(check_read=False).m_Script.deref_parse_as_object()
                cls = script.m_ClassName
                counts[cls] += 1
            except Exception as error:
                errors.append({'phase':'class', 'path_id':obj.path_id, 'error':type(error).__name__})
                continue
            if cls not in wanted:
                continue
            row = {'class':cls, 'path_id':obj.path_id, 'asset_file':obj.assets_file.name, 'raw_sha256':hashlib.sha256(obj.get_raw_data()).hexdigest(), 'generic_interactable':generic(cls)}
            try:
                d = obj.read_typetree()
                row['fields'] = d
                go = objects.get((obj.assets_file.name, d['m_GameObject']['m_PathID']))
                if go:
                    go_data = go.read_typetree()
                    row['game_object_name'] = go_data.get('m_Name')
                    row['active_self'] = go_data.get('m_IsActive')
                    row['hierarchy'] = hierarchy(obj.assets_file.name,d['m_GameObject']['m_PathID'])
                row['network_id'] = None
                if generic(cls):
                    row['network_id_basis'] = 'Not serialized: assigned incrementally by AddGenericInteractable5deab0 during FindObjectsOfType enumeration5ea6e0.'
                if 'boatPrefab' in d:
                    row['boat_prefabs'] = []
                    for index, ref in enumerate(d['boatPrefab']):
                        boat = {'token':index, 'reference':ref}
                        target = objects.get((obj.assets_file.name, ref['m_PathID'])) if ref['m_FileID'] == 0 else None
                        if target:
                            boat['type'] = target.type.name
                            boat['raw_sha256'] = hashlib.sha256(target.get_raw_data()).hexdigest()
                            try:
                                td = target.read_typetree()
                                boat['fields'] = td
                                bg = objects.get((obj.assets_file.name, td.get('m_GameObject',{}).get('m_PathID')))
                                if bg:
                                    boat['game_object_name'] = bg.read_typetree().get('m_Name')
                            except Exception as error:
                                boat['parse_error'] = type(error).__name__
                        else:
                            boat['resolution_error'] = 'external or missing; no invented prefab'
                        row['boat_prefabs'].append(boat)
            except Exception as error:
                errors.append({'phase':'fields', 'path_id':obj.path_id, 'class':cls, 'error':type(error).__name__})
                row['parse_error'] = type(error).__name__
            relevant.append(row)
        reports.append({'bundle':name, 'sha256':hashlib.sha256(path.read_bytes()).hexdigest(), 'containers':list(env.container), 'mono_behaviours_classified':sum(counts.values()), 'class_counts':dict(sorted(counts.items())), 'errors':errors, 'interactions':relevant})
        print(name, 'classified',sum(counts.values()),'interactions',len(relevant),'errors',len(errors),flush=True)
        del env,objects
        gc.collect()
    result = {'scope':'Read-only asset metadata, not runtime. No game/server/listener/connections. path_id is Unity serialized identity, never assumed to equal network Id.', 'source_dump_sha256':hashlib.sha256(dump.read_bytes()).hexdigest(), 'tool_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'generic_classes':sorted(x for x in wanted if generic(x)), 'bundles':reports}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    print(args.output)


if __name__ == '__main__':
    main()
