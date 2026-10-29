"""Inspect mixed world registries without starting/attaching to any target.

Reuses the earlier complete world inventory. Only failed script references are
reopened in shipped bundles. Never guesses wire IDs from serialized path IDs.
The optional bind command structurally validates an externally supplied audited
enumeration; it does not create such evidence or attest runtime correctness.
"""

from _research_paths import workspace, output_root, game_path
import argparse
import collections
import hashlib
import json
from pathlib import Path


ROOT = workspace()
BASE = game_path('Nebula Realms_Data/StreamingAssets/StandaloneWindows')
SCENES = ('campsilverlake', 'cutteridgeestate', 'sorcererseyrie',
          'bowling', 'thenebulian', 'thenebulianopenhouse', 'leafpark')
DEFERRED = frozenset({
    'JG_CampSilverLake_Killer_Launcher', 'JG_Ghost_Minigame', 'JG_Ghost_Candle',
    'JG_SorcerersEyrie_Ingredient', 'JG_SorcerersEyrie_PotionControl',
    'JG_SorcerersEyrie_RecipeControl',
})
ORDINARY = frozenset({
    'JG_ChaletFireplaceInteractable', 'JG_CampSilverLake_WeatherInteractable',
    'JG_CampSilverLake_Door', 'JG_CampSilverLake_TimeInteractable',
    'JG_WeatherInteractable', 'JG_DoorInteractable',
    'JG_SorcerersEyrie_TimeInteractable', 'DayNightBasicCycle',
})
NATIVE = ('5df620', '5decf0', '5deab0', '451060', '5ea6e0',
          '8951e0', '1b8b0f0', '6bdb40')
BINARY_SHA256 = 'c4dd5db599e5e5ce4adf25f09ffe70ad10e0928adf6a2e862176d537026b44ac'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def identity(row):
    return row['asset_file'], str(row['component_path_id'])


def classify(name):
    if name in DEFERRED:
        return 'deferred_minigame'
    if name in ORDINARY:
        return 'ordinary'
    return 'unreviewed'


def inspect(args):
    import UnityPy
    inventory = json.loads(args.inventory.read_text(encoding='utf-8-sig'))
    if inventory['source_dump_sha256'] != sha(ROOT/'work/decompiled/dump.cs'):
        raise ValueError('inventory_dump_hash_mismatch')
    reports = []
    for scene in SCENES:
        bundle_name = 's/' + scene + 'logicprefab'
        source = next(x for x in inventory['bundles'] if x['bundle'] == bundle_name)
        path = args.base / bundle_name
        if sha(path) != source['sha256']:
            raise ValueError('inventory_bundle_hash_mismatch:' + scene)
        generic = []
        for row in source['interactions']:
            if not row.get('generic_interactable'):
                continue
            hierarchy = row.get('hierarchy', {})
            generic.append({
                'class': row['class'], 'classification': classify(row['class']),
                'asset_file': row['asset_file'], 'component_path_id': str(row['path_id']),
                'raw_sha256': row['raw_sha256'], 'game_object_name': row.get('game_object_name'),
                'active_in_prefab_hierarchy': hierarchy.get('active_in_prefab_hierarchy'),
                'under_container_root': hierarchy.get('under_container_root'),
                'component_enabled': bool(row.get('fields', {}).get('m_Enabled')),
                'extension_count': len(row.get('fields', {}).get('data', [])),
                'initial_state': row.get('fields', {}).get('_isActive'),
                'ancestry': hierarchy.get('ancestry', []),
                'wire_id': None,
            })
        errors = source['errors']
        failures = []
        if errors:
            env = UnityPy.load(str(path))
            objects = {(x.assets_file.name, x.path_id): x for x in env.objects}
            by_pid = collections.defaultdict(list)
            for obj in env.objects:
                by_pid[obj.path_id].append(obj)
            for original in errors:
                matches = [x for x in by_pid[original['path_id']] if x.type.name == 'MonoBehaviour']
                if len(matches) != 1:
                    raise ValueError('ambiguous_failure_object:' + scene)
                obj = matches[0]
                fields = obj.read_typetree()
                ref = fields.get('m_Script', {})
                typ = obj.serialized_type
                script_hash = bytes(getattr(typ, 'script_id', b'')).hex()
                type_hash = bytes(getattr(typ, 'old_type_hash', b'')).hex()
                go_ref = fields.get('m_GameObject', {})
                go = objects.get((obj.assets_file.name, go_ref.get('m_PathID'))) if go_ref.get('m_FileID') == 0 else None
                missing = ref == {'m_FileID': 0, 'm_PathID': 0}
                stripped_base = set(fields) == {'m_GameObject', 'm_Enabled', 'm_Script', 'm_Name'}
                failures.append({
                    'component_path_id': str(obj.path_id), 'asset_file': obj.assets_file.name,
                    'phase': original['phase'], 'script_reference': ref,
                    'script_type_index': getattr(typ, 'script_type_index', None),
                    'script_id': script_hash, 'old_type_hash': type_hash,
                    'serialized_bytes': obj.byte_size, 'raw_sha256': hashlib.sha256(obj.get_raw_data()).hexdigest(),
                    'fields': sorted(fields),
                    'game_object_name': go.read_typetree().get('m_Name') if go else None,
                    'classification': 'null_script_base_only' if missing and stripped_base else 'unresolved',
                    'recoverable_monoscript_reference': not missing,
                    'all_zero_script_and_type_hash': bool(script_hash and type_hash) and set(script_hash + type_hash) == {'0'},
                })
            del env, objects
        active = [x for x in generic if x['active_in_prefab_hierarchy'] and x['under_container_root']]
        counts = collections.Counter(x['classification'] for x in active)
        unresolved = [x for x in failures if x['classification'] != 'null_script_base_only']
        reports.append({
            'scene_key': scene, 'bundle': bundle_name, 'bundle_sha256': source['sha256'],
            'generic_components': generic, 'active_generic_count': len(active),
            'active_ordinary_count': counts['ordinary'], 'active_deferred_count': counts['deferred_minigame'],
            'active_unreviewed_count': counts['unreviewed'],
            'previous_class_error_count': len(errors), 'null_script_base_only_count': len(failures)-len(unresolved),
            'genuinely_unresolved_count': len(unresolved), 'script_failures': failures,
            'numeric_allowlist_available': not counts['deferred_minigame'] and not counts['unreviewed'] and not unresolved,
            'static_candidate_range': [0, len(active)-1] if active and not counts['deferred_minigame'] and not counts['unreviewed'] and not unresolved else None,
            'mapping_limit': 'Only a static baseline count. Initial activation changes, dynamic housing registrations and engine enumeration can invalidate a numeric mapping.',
        })
        print(scene, 'active', len(active), 'ordinary', counts['ordinary'], 'deferred', counts['deferred_minigame'],
              'null_scripts', len(failures)-len(unresolved), 'unresolved', len(unresolved), flush=True)
    result = {
        'format_version': 1,
        'scope': 'Read-only shipped metadata/native pseudocode. No target execution, attach, UI, server, listener or connection. Numeric mixed-scene IDs remain unset.',
        'binary_sha256': BINARY_SHA256, 'inventory_sha256': sha(args.inventory),
        'tool_sha256': sha(__file__), 'dump_sha256': inventory['source_dump_sha256'],
        'id_assignment': {
            'initial_counter': -1, 'first_assigned_id': 0,
            'algorithm': 'Preincrement counter at NebulaInteractor+0x3c for each returned GenericInteractable, in array order.',
            'include_inactive': False,
            'enumeration_implementation': 'Unity engine internal call; no serialized pathId ordering proven.',
            'missing_script_conclusion': 'Null m_Script, script_type_index -1, zero script/type hashes and base-only32byte records provide no recoverable subtype. They are missing-script placeholders, not failed external-script resolution. Excluding them from typed GenericInteractable enumeration is a source-based inference, not runtime observation.',
            'dynamic_housing': 'HousingFurnishing.SaveAtServer6bdb40 registers placed children with GenericInteractable.Initialize; next IDs depend on prior registrations and object traversal order. A static baseline cannot authorize arbitrary later IDs.',
            'native_sources': [{'rva': '0x'+rva, 'sha256': sha(ROOT/'work/evidence/ghidra/functions'/f'{rva}.c')} for rva in NATIVE],
        },
        'scenes': reports,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2)+'\n', encoding='utf8')


def bind_registry(report, mapping, evidence_sha256):
    """Validate a full initial enumeration without fabricating its ordering.

    This only verifies mapping completeness and provenance references. The caller
    still owes an independent audit that the supplied order is the actual native
    order for every compatible client. Output deliberately remains unverified.
    """
    if mapping.get('format_version') != 1 or mapping.get('registration_epoch') != 'initial_scene':
        raise ValueError('unsupported_mapping_schema_or_epoch')
    scene = next((x for x in report['scenes'] if x['scene_key'] == mapping.get('scene_key')), None)
    if scene is None or scene['genuinely_unresolved_count'] or scene['active_unreviewed_count']:
        raise ValueError('scene_not_fully_classified')
    if mapping.get('bundle_sha256') != scene['bundle_sha256'] or mapping.get('binary_sha256') != report['binary_sha256']:
        raise ValueError('source_hash_mismatch')
    if mapping.get('evidence_artifact_sha256') != evidence_sha256 or len(evidence_sha256) != 64:
        raise ValueError('enumeration_evidence_hash_mismatch')
    expected = {identity(x): x for x in scene['generic_components'] if x['active_in_prefab_hierarchy'] and x['under_container_root']}
    entries = mapping.get('entries')
    if not isinstance(entries, list) or len(entries) != len(expected):
        raise ValueError('incomplete_enumeration')
    supplied, allowlist, deferred = set(), [], []
    for ordinal, entry in enumerate(entries):
        if type(entry.get('wire_id')) is not int or entry['wire_id'] != ordinal:
            raise ValueError('noncanonical_wire_id_order')
        key = identity(entry)
        if key not in expected or key in supplied:
            raise ValueError('unknown_or_duplicate_component')
        supplied.add(key)
        component = expected[key]
        if entry.get('raw_sha256') != component['raw_sha256']:
            raise ValueError('component_hash_mismatch')
        row = {'wire_id': ordinal, 'class': component['class'], 'asset_file': key[0],
               'component_path_id': key[1], 'raw_sha256': component['raw_sha256'],
               'extension_count': component['extension_count']}
        (allowlist if component['classification'] == 'ordinary' else deferred).append(row)
    return {'format_version': 1, 'scene_key': scene['scene_key'], 'bundle_sha256': scene['bundle_sha256'],
            'binary_sha256': report['binary_sha256'], 'registration_epoch': 'initial_scene',
            'evidence_artifact_sha256': evidence_sha256, 'structurally_validated': True,
            'native_order_verified': False, 'ready_for_automatic_admission': False,
            'ordinary_id_allowlist': allowlist, 'deferred_id_denylist': deferred,
            'warning': 'Structural validation cannot attest supplied native order. Do not auto-load until independently audited. Invalidate on dynamic registration, activation or client mapping mismatch.'}


def main():
    parser = argparse.ArgumentParser(__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    scan = commands.add_parser('inspect')
    scan.add_argument('--inventory', type=Path, default=ROOT/'work/evidence/world-interaction-assets.json')
    scan.add_argument('--base', type=Path, default=BASE)
    scan.add_argument('--output', type=Path, default=ROOT/'results/protocol/mixed-world-registries.json')
    binding = commands.add_parser('bind')
    binding.add_argument('--report', type=Path, required=True)
    binding.add_argument('--mapping', type=Path, required=True)
    binding.add_argument('--evidence', type=Path, required=True)
    binding.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'inspect':
        inspect(args)
    else:
        result = bind_registry(json.loads(args.report.read_text(encoding='utf-8-sig')),
                               json.loads(args.mapping.read_text(encoding='utf-8-sig')), sha(args.evidence))
        args.output.write_text(json.dumps(result, indent=2)+'\n', encoding='utf8')


if __name__ == '__main__':
    main()
