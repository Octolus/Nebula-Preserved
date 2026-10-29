"""Build companion/locomotion catalog from shipped manifests and static natives.

No game executable, server, listener or connection is started. Canonical item
prefabs are distinguished from dependency prefabs and misplaced wardrobe assets.
"""

from _research_paths import workspace, output_root, game_path
import argparse
import collections
import hashlib
import json
from pathlib import Path
import re
import yaml


KINDS={'COMPANIONS':('companions','02'),'LOCOMOTIONS':('locomotions','03')}
METHODS={
    'AES.Encrypt':'6a32c0',
    'NETGCloudSpace.Send_GetCompanionsIDAssetsCoroutine.MoveNext':'3fa400',
    'NETGCloudSpace.Send_GetLocomotionsIDAssetsCoroutine.MoveNext':'3fbc20',
    'MenuWheelPets.AddPetAssets':'4bd390',
    'MenuWheelLocomotions.AddLocomotionAssets':'4bbc90',
    'MenuWheelPets.ConfigureScroll':'4bd950',
    'MenuWheelLocomotions.ConfigureScroll':'4bc250',
    'NebulaPlayer.InstantiateCompanion.MoveNext':'6eaee0',
    'NebulaPlayerAnim.InstantiateLocomotion.MoveNext':'604760',
}


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def decode_path(text):
    return yaml.safe_load(text) if text.startswith('"') else text


def build(manifests):
    rows=[]
    auxiliary=[]
    thumbnail_index=collections.defaultdict(list)
    pattern=re.compile(r'/(COMPANIONS|LOCOMOTIONS)/([^/]+)/([^/]+)Thumbnail\.(?:png|jpg|jpeg)$',re.I)
    for bundle in manifests:
        for raw in bundle['assets']:
            path=decode_path(raw)
            match=pattern.search(path)
            if match and match[2]==match[3] and match[1].upper() in KINDS:
                thumbnail_index[(KINDS[match[1].upper()][0],match[2])].append({
                    'bundle':bundle['bundle'],'asset_path':path,
                    'manifest_sha256':bundle['manifest_sha256']})
    for bundle in manifests:
        prefix=bundle['bundle'].split('/')[0]
        if prefix not in ('02','03'):continue
        for raw in bundle['assets']:
            path=decode_path(raw)
            match=re.search(r'/(COMPANIONS|LOCOMOTIONS)/([^/]+)/([^/]+)\.prefab$',path)
            if not match or match[2]!=match[3]:
                auxiliary.append({'bundle':bundle['bundle'],'asset_path':path,
                    'reason':'Not a canonical category/itemID/itemID.prefab; auxiliary dependency or misplaced wardrobe resource'})
                continue
            table,item_id,_=match.groups()
            kind,expected_prefix=KINDS[table]
            expected_bundle=expected_prefix+'/'+item_id.lower()
            thumbnails=thumbnail_index.get((kind,item_id),[])
            reasons=[]
            if bundle['bundle']!=expected_bundle:reasons.append('Bundle identity conflicts with native category prefix and item ID')
            if len(thumbnails)!=1:reasons.append('Expected exactly one canonical thumbnail asset')
            if len(thumbnails)==1 and thumbnails[0]['bundle']!='th/'+item_id.lower()+'thumbnail':
                reasons.append('Thumbnail bundle identity conflicts with native item ID')
            rows.append({'kind':kind,'item_id':item_id,'table':table,'bundle':bundle['bundle'],
                'asset_path':path,'manifest_asset_text':raw,'bundle_size':bundle['bundle_size'],
                'manifest_sha256':bundle['manifest_sha256'],'dependencies':bundle['dependencies'],
                'requested_resource_path_native':'Wardrobe_EAB\\'+table+'\\'+item_id+'\\'+item_id,
                'requested_resource_path':'Wardrobe_EAB/'+table+'/'+item_id+'/'+item_id,
                'thumbnail_resource_path':'Wardrobe_EAB/'+table+'/'+item_id+'/'+item_id+'Thumbnail',
                'thumbnail_assets':thumbnails,'conflicts':reasons,'grantable':not reasons})
    grouped=collections.defaultdict(list)
    for row in rows:grouped[row['item_id']].append(row)
    for values in grouped.values():
        if len(values)>1:
            for row in values:
                row['conflicts'].append('Identifier has multiple canonical category/prefab mappings')
                row['grantable']=False
    return sorted(rows,key=lambda r:(r['kind'],r['item_id'])),auxiliary


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--manifests',type=Path,default=(workspace() / 'work/evidence/assets/bundle-manifests.json'))
    ap.add_argument('--out',type=Path,default=(workspace() / 'results/protocol'))
    args=ap.parse_args()
    rows,auxiliary=build(json.loads(args.manifests.read_text(encoding='utf-8')))
    sources=[]
    for name,rva in METHODS.items():
        path=(workspace() / 'work/evidence/ghidra/functions')/(rva+'.c')
        sources.append({'method':name,'rva':'0x'+rva,'va':hex(0x180000000+int(rva,16)),
                        'file':str(path),'sha256':digest(path)})
    summary={'canonical_items':len(rows),'grantable_items':sum(r['grantable'] for r in rows),
        'by_kind':dict(collections.Counter(r['kind'] for r in rows)),
        'excluded_asset_rows':len(auxiliary),'conflicting_items':sum(bool(r['conflicts']) for r in rows)}
    result={'format_version':1,'evidence_scope':'Static native consumers and shipped manifests; no runtime interoperability test',
        'game':{'app_id':919290,'build_id':11018722,'unity':'2021.3.9f1',
                'gameassembly_sha256':'c4dd5db599e5e5ce4adf25f09ffe70ad10e0928adf6a2e862176d537026b44ac'},
        'sources':[{'file':str(args.manifests),'sha256':digest(args.manifests)},
            {'file':'work/decompiled/script.json','sha256':digest((workspace() / 'work/decompiled/script.json'))},
            {'file':'work/decompiled/stringliteral.json','sha256':digest((workspace() / 'work/decompiled/stringliteral.json'))},
            {'file':str(Path(__file__)),'sha256':digest(Path(__file__))},*sources],
        'summary':summary,
        'http_contract':{
            'routes':{'companions':'GetCompanionsServlet','locomotions':'GetLocomotionsServlet'},
            'request_method':'GET','query_parameter':'data','request_logical_fields':'SessionGUID#PS4ID',
            'request_plaintext_before_encryption':'SessionGUID#PS4ID#platformName',
            'request_transport':'Direct NETGCloudSpace coroutine calls AES.Encrypt6a32c0, which internally appends #platformName before UTF8/AES; then Uri.EscapeDataString',
            'response_plaintext':'true#SessionGUID#itemID1#itemID2...',
            'empty_response':'true#SessionGUID',
            'response_fields':[{'index':0,'name':'success','type':'string','rule':'exact lowercase true'},
                {'index':1,'name':'SessionGUID','type':'string','rule':'must equal local PS4Info.SessionGUID'},
                {'index':'2..end','name':'asset_IDs','type':'plain string list','rule':'skip empty tokens; every nonempty token is an asset ID'}],
            'response_has_json':False,'response_has_count':False,'response_has_names':False,
            'native_acceptance':'Menu must still be active; empty list invokes menu empty callback, otherwise AddPetAssets/AddLocomotionAssets receives list.',
            'identifier_rules':'Use original-case canonical prefab IDs, not lowercase bundle names. Do not send a count, gender, display name or nonempty trailer.'},
        'local_policy':{'ownership':'Only explicit offline resource_admin grants; no payment or Steam order processing',
            'storage':'resource_entitlements SQLite table keyed ps4_id,kind,item_id; independent of wardrobe entitlements',
            'default_grants':'none; empty is an exact supported DTO',
            'ordering':'deterministic item_id order; original server order unavailable',
            'display_names':'local explicit label or item ID fallback; commercial labels unrecovered'},
        'limitations':['Shipped availability does not prove original ownership, prices, unlock policy or default grants.',
            'Manifest dependencies retain developer build-drive prefixes; runtime loader resolution has not been exercised.',
            'Canonical paths and thumbnails are verified statically; successful instantiation, AI/animation and multiplayer synchronization remain untested.',
            'Excluded nested dependency prefabs and three wardrobe FBX bundles under03 must not be independently granted as locomotions.'],
        'items':rows,'excluded_assets':auxiliary}
    args.out.mkdir(parents=True,exist_ok=True)
    (args.out/'resource-entitlements.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(summary))


if __name__=='__main__':main()
