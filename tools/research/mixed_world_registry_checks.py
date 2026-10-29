"""Offline metadata/binding validation only; never runs target/network code."""

from _research_paths import workspace, output_root, game_path
import copy
import json
from pathlib import Path
from mixed_world_registry import ROOT, bind_registry


def main():
    report = json.loads((ROOT/'results/protocol/mixed-world-registries.json').read_text())
    scenes = {x['scene_key']: x for x in report['scenes']}
    assert report['id_assignment']['initial_counter'] == -1
    assert report['id_assignment']['first_assigned_id'] == 0
    assert report['id_assignment']['include_inactive'] is False
    expected = {'campsilverlake': (9, 8, 1, 0), 'cutteridgeestate': (3, 2, 1, 0),
                'sorcererseyrie': (12, 1, 11, 0), 'bowling': (0, 0, 0, 449),
                'thenebulian': (1, 1, 0, 21), 'thenebulianopenhouse': (0, 0, 0, 21),
                'leafpark': (0, 0, 0, 4)}
    for name, values in expected.items():
        row = scenes[name]
        assert tuple(row[k] for k in ('active_generic_count','active_ordinary_count','active_deferred_count','null_script_base_only_count')) == values
        assert row['genuinely_unresolved_count'] == 0
        for failure in row['script_failures']:
            assert failure['classification'] == 'null_script_base_only'
            assert failure['serialized_bytes'] == 32 and failure['script_type_index'] == -1
            assert failure['all_zero_script_and_type_hash'] is True
            assert failure['script_reference'] == {'m_FileID': 0, 'm_PathID': 0}
    assert scenes['thenebulian']['static_candidate_range'] == [0, 0]
    assert all(scenes[x]['numeric_allowlist_available'] is False for x in ('campsilverlake','cutteridgeestate','sorcererseyrie'))

    # Synthetic supplied order exercises structural validation. It is explicitly
    # NOT asserted to be the native order and must never become auto-admission.
    scene = scenes['campsilverlake']
    active = [x for x in scene['generic_components'] if x['active_in_prefab_hierarchy'] and x['under_container_root']]
    mapping = {'format_version': 1, 'registration_epoch': 'initial_scene', 'scene_key': scene['scene_key'],
               'bundle_sha256': scene['bundle_sha256'], 'binary_sha256': report['binary_sha256'],
               'evidence_artifact_sha256': 'a'*64,
               'entries': [{'wire_id': i, 'asset_file': x['asset_file'], 'component_path_id': x['component_path_id'],
                            'raw_sha256': x['raw_sha256']} for i, x in enumerate(active)]}
    result = bind_registry(report, mapping, 'a'*64)
    assert len(result['ordinary_id_allowlist']) == 8 and len(result['deferred_id_denylist']) == 1
    assert result['native_order_verified'] is False and result['ready_for_automatic_admission'] is False
    mutations = [
        lambda x: x.update(registration_epoch='dynamic_housing'),
        lambda x: x.update(bundle_sha256='0'*64),
        lambda x: x.update(binary_sha256='0'*64),
        lambda x: x.update(evidence_artifact_sha256='0'*64),
        lambda x: x['entries'].pop(),
        lambda x: x['entries'][0].update(wire_id=1),
        lambda x: x['entries'][0].update(wire_id=True),
        lambda x: x['entries'][0].update(raw_sha256='0'*64),
        lambda x: x['entries'][0].update(component_path_id='missing'),
        lambda x: x['entries'][1].update(asset_file=x['entries'][0]['asset_file'],component_path_id=x['entries'][0]['component_path_id']),
    ]
    for mutate in mutations:
        invalid = copy.deepcopy(mapping)
        mutate(invalid)
        try:
            bind_registry(report, invalid, 'a'*64)
        except ValueError:
            continue
        raise AssertionError('malformed mapping accepted')
    print('Mixed registry metadata: seven scenes and495 null-script records verified; ten malformed bindings rejected; synthetic mapping stays unverified.')


if __name__ == '__main__':
    main()
