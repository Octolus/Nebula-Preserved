"""Append keyboard height-trigger aliases to an exact private InputManager copy.

Creates new files only. Never changes an input, a live client, or Steam assets.
L1/Q and R1/R are native furniture rotation; these added rows are height input.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
from pathlib import Path
import UnityPy

SOURCE_SHA256 = '70a141380052f0c2eb0d64c8bad71961648fe9791d79a6b2da37924b9bff4775'
UNITY_VERSION = '2021.3.9f1'
AXES_BEFORE = 48
BINDINGS = [('joystick1_left_trigger', '1', 'LowerPlacedObject'),
            ('joystick1_right_trigger', '2', 'RaisePlacedObject')]

def sha(data):
    return hashlib.sha256(data).hexdigest()

def manager(env):
    objects=[o for o in env.objects if o.type.name=='InputManager']
    if len(objects)!=1:
        raise ValueError('Expected exactly one InputManager')
    return objects[0]

def other_hashes(env, excluded):
    return {f'{o.path_id}:{o.type.name}':sha(o.get_raw_data())
            for o in env.objects if o.path_id!=excluded}

def prepare(source: bytes):
    if sha(source)!=SOURCE_SHA256:
        raise ValueError('Source must be the reviewed 48-axis private world-controls copy')
    env=UnityPy.load(source)
    if env.file.unity_version!=UNITY_VERSION:
        raise ValueError('Unexpected Unity version')
    obj=manager(env)
    tree=obj.read_typetree()
    axes=tree['m_Axes']
    if len(axes)!=AXES_BEFORE or obj.path_id!=2:
        raise ValueError('Unexpected InputManager path or axis count')
    for name,_,_ in BINDINGS:
        original=[a for a in axes if a['m_Name']==name]
        if len(original)!=1 or original[0]['type']!=2 or original[0]['joyNum']!=1:
            raise ValueError(f'Expected one unmodified physical-controller axis {name}')
        if any(original[0][k] for k in ['negativeButton','positiveButton','altNegativeButton','altPositiveButton']):
            raise ValueError('Controller trigger already has keyboard buttons')
    template=next(a for a in axes if a['m_Name']=='dpad1_horizontal' and a['type']==0)
    additions=[]
    for name,key,_ in BINDINGS:
        row=copy.deepcopy(template)
        row.update(m_Name=name,descriptiveName='',descriptiveNegativeName='',
                   negativeButton='',positiveButton=key,altNegativeButton='',altPositiveButton='',
                   gravity=1000.0,dead=0.0010000000474974513,sensitivity=1000.0,
                   snap=False,invert=False,type=0,axis=0,joyNum=0)
        additions.append(row)
    expected=copy.deepcopy(tree)
    expected['m_Axes']=copy.deepcopy(axes)+additions
    before=other_hashes(env,obj.path_id)
    obj.save_typetree(expected)
    output=env.file.save()
    check=UnityPy.load(output)
    check_obj=manager(check)
    actual=check_obj.read_typetree()
    if check.file.unity_version!=UNITY_VERSION or actual!=expected:
        raise ValueError('Serialized InputManager does not match exactly two additive rows')
    if actual['m_Axes'][:AXES_BEFORE]!=axes or len(actual['m_Axes'])!=50:
        raise ValueError('Original 48 axis rows changed')
    after=other_hashes(check,check_obj.path_id)
    if before!=after:
        raise ValueError('Non-InputManager serialized object changed')
    report=dict(format_version=1,kind='prepared_keyboard_housing_trigger_copy',
                source_sha256=SOURCE_SHA256,copy_sha256=sha(output),
                source_size=len(source),copy_size=len(output),unity_version=UNITY_VERSION,
                input_manager_path_id=obj.path_id,axes_before=AXES_BEFORE,axes_after=50,
                added_rows=[dict(axis_index=AXES_BEFORE+i,action=BINDINGS[i][2],**row)
                            for i,row in enumerate(additions)],
                all_original_48_axis_rows_preserved=True,
                all_other_input_manager_fields_preserved=True,
                non_input_manager_object_count=len(before),
                all_non_input_manager_object_raw_hashes_preserved=True,
                non_input_manager_raw_hashes=before,
                source_changed=False,target_executed=False,listeners_started=False,runtime_proof=False,
                rotation='Existing Q/L1 and R/R1 callbacks rotate. Added 1/L2 and 2/R2 supply lower/raise analog input.',
                key_policy='Authored keyboard compatibility policy; plain 1/2 do not conflict with any existing InputManager key binding or reviewed PadPS4 button aliases. Global context exclusivity is not claimed.',
                limits=['Static serialization preservation only; no engine input/rotation/height runtime test.',
                        'Duplicate named axes use Unity maximum-absolute-value selection; controller rows are preserved, and simultaneous equal-magnitude inputs may tie.',
                        'PadPS4 blocked state and active housing mode still gate native behavior.'])
    return output,report

def validate_paths(source: Path,destination: Path,manifest: Path):
    source=source.resolve(strict=True)
    destination=destination.resolve()
    manifest=manifest.resolve()
    if destination==source or destination.exists() or 'steamapps' in [p.lower() for p in destination.parts]:
        raise ValueError('Destination must be a new file outside Steam and separate from input')
    if manifest in (source,destination) or manifest.exists() or manifest.suffix.lower()!='.json' or 'steamapps' in [p.lower() for p in manifest.parts]:
        raise ValueError('Manifest must be a new, separate JSON file outside Steam')
    return source,destination,manifest

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',required=True,type=Path)
    parser.add_argument('--destination',required=True,type=Path)
    parser.add_argument('--manifest',required=True,type=Path)
    args=parser.parse_args(argv)
    try:
        source,destination,manifest_path=validate_paths(args.source,args.destination,args.manifest)
        data=source.read_bytes()
        output,report=prepare(data)
        if source.read_bytes()!=data:
            raise ValueError('Source changed while preparing candidate')
    except (ValueError,OSError) as e:
        parser.error(str(e))
    destination.parent.mkdir(parents=True,exist_ok=True)
    with destination.open('xb') as f:
        f.write(output)
    report.update(source_path=str(source),copy_path=str(destination),
                  patch_tool_sha256=sha(Path(__file__).read_bytes()))
    manifest_path.parent.mkdir(parents=True,exist_ok=True)
    with manifest_path.open('x',encoding='utf-8') as f:
        f.write(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ['copy_sha256','axes_before','axes_after','source_changed','target_executed']}))

if __name__=='__main__':
    main()
