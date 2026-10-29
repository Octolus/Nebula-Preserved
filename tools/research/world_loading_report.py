"""Summarize the recovered modern boot/allocation/loading path without execution."""
from __future__ import annotations

from _research_paths import workspace, output_root, game_path
import hashlib
import json
from pathlib import Path

ROOT = workspace()
OUT = ROOT / 'results'
PROTOCOL = OUT / 'protocol'
NATIVE = ROOT / 'work/evidence/ghidra/functions'

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    claims = [
        ('boot', 'observed_static', ['68b170','69f440','69f890','69f9e0','641ef0','634130'],
         'Booter starts local asset management/music/scenes, awaits navigation and NebulaPlayer loading, then loads preinitiload. Game music is loaded from the local gamemusic bundle.'),
        ('screen_loader', 'observed_static', ['429fd0','69fde0','5e9110'],
         'The initial Booter scene serializes one enabled ScreenLoader on an active root GameObject, so getInstance can return its cache or FindObjectOfType result without creating the first host. A separate compiled path can load the screenloader bundle, instantiate it and mark it DontDestroyOnLoad, but the reviewed Booter.Start/Init path does not invoke that loader.'),
        ('login_sentinel', 'observed_static', ['6ec320','3d5a40'],
         'Successful login calls NETGcloudLogin.LoadSpace with the literal Login. Mapping that sentinel to Nexus is an explicit replacement-service policy, not a recovered original default.'),
        ('allocation', 'observed_static', ['63c190','63beb0'],
         'HTTPSpaceLoading forwards response fields2..5 as instance ID, actual scene key, address and port. The scene key must identify a local scene bundle. The modern path does not strip invented owner or instance prefixes.'),
        ('scene_load', 'observed_static', ['5e9800','5eb640'],
         'Scenes.Load uses StreamingAssets/StandaloneWindows/s/<lowercase scene key>, unloads old logic/scenes, and calls Unity SceneManager.LoadSceneAsync. This transition destroys the old manager and disconnects its Mirror client.'),
        ('logic_prefab', 'observed_static', ['46fa80','617b10','4dc2f0'],
         'The active Nexus SpacePREFAB component loads local NexusLogicPREFAB before ManagerInstance.Launch. A missing optional space-event bundle is skipped. Resource dependencies reviewed on this path are local skinmaterials.'),
        ('direct_mirror_connection', 'observed_static', ['438a10','438520','4386b0'],
         'ManagerInstance copies the allocation address and port into Mirror NetworkManager and Telepathy and starts the client directly. No intermediate legacy load-balancer call was found on this traced modern path.'),
        ('watchdog', 'observed_static', ['444150'],
         'The connection coroutine waits up to30 realtime seconds before closing/reallocating a client that is still disconnected.'),
        ('local_entity', 'observed_static', ['6e88c0','6e82a0','5eb3a0'],
         'NebulaPlayer.Start/SetPlayer distinguishes Mirror local identity, stores the pending local player, and queues remotes. The connected coroutine waits for that local entity before requesting player label/avatar data.'),
        ('arrival', 'observed_static', ['5f63e0','5ea260'],
         'The HTTP last position is initially applied to the avatar ghost. After the local avatar loads, the client selects an actual scene spawn point before closing the loading screen; the first Mirror root position is not the final Nexus arrival point.'),
    ]
    rows = []
    for key, basis, rvas, text in claims:
        evidence = []
        for rva in rvas:
            path = NATIVE / (rva+'.c')
            if not path.exists():
                raise FileNotFoundError(f'Missing evidence for {key}: {path}')
            evidence.append({'rva':'0x'+rva, 'path':str(path.relative_to(ROOT)).replace('\\','/'), 'sha256':sha(path)})
        rows.append({'key':key,'basis':basis,'finding':text,'native_evidence':evidence})
    assets = json.loads((PROTOCOL/'world-loading-assets.json').read_text(encoding='utf-8'))
    loader = json.loads((PROTOCOL/'loader-bootstrap.json').read_text(encoding='utf-8'))
    if not loader.get('placement_proven') or loader.get('confidence') != 'high':
        raise RuntimeError('loader-bootstrap.json does not prove the initial serialized placement')
    shared_network = json.loads((PROTOCOL/'shared-server-networking.json').read_text(encoding='utf-8'))
    core_test = json.loads((PROTOCOL/'core-test-readiness.json').read_text(encoding='utf-8'))
    configuration = shared_network.get('configuration', {})
    allocation = shared_network.get('allocation', {})
    if (configuration.get('address_validation', {}).get('family') != 'IPv4'
            or configuration.get('advertised_addresses_must_match')
            != 'HTTP configured advertised IPv4 == every admitted instance descriptor ip'
            or not allocation.get('configured_exact_advertised_host_only')):
        raise RuntimeError('shared-server-networking.json lacks the exact advertised-IPv4 contract')
    if (core_test.get('profile', {}).get('name') != 'nexus-core-v1'
            or not core_test.get('profile', {}).get('both_required')
            or core_test.get('assessment', {}).get('game_ready') is not False
            or core_test.get('assessment', {}).get('protocol_complete') is not False):
        raise RuntimeError('core-test-readiness.json lacks the finite bilateral closed-readiness contract')
    screen_loader = next(row for row in rows if row['key'] == 'screen_loader')
    candidate = loader['initial_scene_screen_loader_components'][0]
    screen_loader['serialized_evidence'] = {
        'attachment':'protocol/loader-bootstrap.json',
        'startup_scene':loader['unity_build']['scenes'][0],
        'compiled_scene':loader['unity_build']['startup_compiled_file'],
        'mono_behaviour_path_id':candidate['mono_behaviour_path_id'],
        'game_object_path_id':candidate['game_object_path_id'],
        'game_object_name':candidate['game_object_name'],
        'enabled':candidate['enabled'],
        'active_self':candidate['active_self'],
        'is_scene_root':candidate['transform']['is_scene_root'],
        'script':candidate['script'],
        'confidence':loader['confidence'],
    }
    attachments = ['world-loading-assets.json','world-loading-methods.json','world-loading-native.json',
                   'world-loading-preinit-native.json','world-loading-xrefs.json','tcp-world-spawn.json',
                   'loader-bootstrap.json','shared-server-networking.json','core-test-readiness.json']
    report = {
        'format_version':1,
        'scope':'Static client-native and local serialized-asset evidence. No target execution, server, listener or connection.',
        'binary_sha256':sha(ROOT/'work/evidence/GameAssembly.dll'),
        'findings':rows,
        'asset_roots':assets['roots'], 'missing_required_asset_closure':assets['missing'],
        'optional_nexus_event':assets['optional_space_event'],
        'shared_server_networking':{
            'attachment':'protocol/shared-server-networking.json',
            'address_family':configuration['address_validation']['family'],
            'configured_exact_advertised_host_only':allocation['configured_exact_advertised_host_only'],
            'advertised_addresses_must_match':configuration['advertised_addresses_must_match'],
            'bind_and_advertised_addresses_are_separate':True,
            'same_host_local_files':allocation['same_host_local_files'],
            'current_producer_flags':allocation['current_producer_flags'],
        },
        'core_test_readiness':{
            'attachment':'protocol/core-test-readiness.json',
            'profile':core_test['profile']['name'],
            'bilateral_opt_in_required':core_test['profile']['both_required'],
            'eligible_after_prerequisites':core_test['assessment']['eligible_to_stage_controlled_validation_after_prerequisites'],
            'game_ready':core_test['assessment']['game_ready'],
            'protocol_complete':core_test['assessment']['protocol_complete'],
            'native_runtime_validated':core_test['assessment']['native_runtime_validated'],
        },
        'new_local_policies':['Login sentinel maps to a configured Nexus allocation.',
            'Allocation admits one explicitly configured concrete advertised IPv4 and selects only a fresh, protocol-complete descriptor for that exact address; game_ready must be true when present. Bind address and advertised address remain separate.'],
        'bounded_negative_searches':[
            'No separate legacy load-balancer call on the traced modern Nexus path. Direct E8/E9 references and type-info evidence do not exclude indirect or unrelated legacy uses.',
            'No remote asset server is required by the local bundle-loading calls reviewed here. This does not prove every optional feature uses local files.'],
        'remaining_unknowns':['No cross-version Unity engine, live Mirror delivery, scene rendering, or world arrival test has been performed.',
            'Static evidence does not establish when or whether the separate screenloader bundle loader is invoked outside the reviewed Booter.Start/Init path.',
            'The retired original allocation policy and service state are unavailable.'],
        'attachments':[{'path':'protocol/'+name,'sha256':sha(PROTOCOL/name)} for name in attachments],
        'game_ready':False,'networking_parity_proven':False,
    }
    (PROTOCOL/'world-loading-pipeline.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    lines = ['# Modern world-loading path', '', report['scope'], '',
             'The supported reconstruction path is **HTTP allocation → local scene/logic bundles → direct Mirror connection → local entity → avatar → scene spawn**. It does not require recreating an intermediate legacy load balancer on the path traced here.', '']
    for row in rows:
        lines += ['- **'+row['key'].replace('_',' ')+':** '+row['finding']+' Native RVAs: '+', '.join(x['rva'] for x in row['native_evidence'])+'.']
    lines += ['', 'All '+str(len(assets['roots']))+' selected bundle roots and their normalized text-manifest dependency closure exist in the installation. The optional Nexus event bundle is absent and the reviewed loader skips it. File existence and static manifest closure do not simulate Unity asset resolution.', '',
              'The backend now recognizes the `Login` sentinel. Its returned field3 remains the actual scene key, such as `Nexus`, while field2 is the distinct instance ID. The returned address/port come from a fresh validated descriptor matching the one explicitly configured concrete advertised IPv4; the bind address is a separate setting.', '',
              'The current instance advertises `protocol_complete:false` and `game_ready:false`; allocation stays closed during reconstruction. No status flag was changed to bypass this boundary.', '',
              'Remaining limits: '+ ' '.join(report['remaining_unknowns']), '',
              'Evidence and SHA256 hashes: [machine-readable report](world-loading-pipeline.json), [ScreenLoader bootstrap](loader-bootstrap.md), [shared-server networking](shared-server-networking.md), [finite core-test readiness](core-test-readiness.md), [local bundle closure](world-loading-assets.json), [bounded cross-references](world-loading-xrefs.json), [arrival transforms](tcp-world-spawn.md).', '']
    (PROTOCOL/'world-loading-pipeline.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps({'native_findings':len(rows),'asset_roots':len(assets['roots']),'missing':assets['missing']}))

if __name__ == '__main__': main()
