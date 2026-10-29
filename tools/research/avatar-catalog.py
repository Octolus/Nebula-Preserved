"""Join shipped wardrobe manifests to native-observed default item literals.

This produces static catalog evidence, not an account entitlement database or a
complete executable default preset. It never starts the game.
"""

from _research_paths import workspace, output_root, game_path
import argparse
import collections
import hashlib
import json
import re
from pathlib import Path
import yaml


def decode_manifest_path(value):
    # Unity's .manifest text is YAML and quotes non-ASCII IDs with \xNN escapes.
    return yaml.safe_load(value) if value.startswith('"') else value


DEFAULTS = {
    'MALE': {
        'CLOTH_BODY_TORSO':'Gnvdg5DgdJYY5a56UBx1874HE25Xns2Y',
        'CLOTH_BODY_LEGS':'DC45Lq5kINd7sR6Ui7vn4vsyDrjU0nh0',
        'CLOTH_BODY_FEET':'d6X4a5fHWtFaAuP1kWkGDi6KE550fWjv',
        'CLOTH_BODY_HANDS':'O01QY505KRu3QWRH3QAH5f30p45Uv38B',
        'CLOTH_HEAD_FULL_HEAD_DRESS':'sL0D2k3asbB756Yb2qJ0LchSiLsKw5Cf',
    },
    'FEMALE': {
        'CLOTH_BODY_TORSO':'qC16ldGPI66LGk2oqD1j3Vj5TBuuJwqd',
        'CLOTH_BODY_LEGS':'nl7dD7Wr1aWU7LXDfU4u07BV4FHKRg17',
        'CLOTH_BODY_FEET':'M2R5I8VmkJGA3Rh5fpma5B3vxC5Le4J4',
        'CLOTH_BODY_HANDS':'kuVsMc0n42ay68uYlI7n5jT6bWK2OGJ1',
        'CLOTH_HEAD_FULL_HEAD_DRESS':'fVyLwiL15UE3U70354TJWIXiN8Y8K5C4',
        'CLOTH_HEAD_HAIRSTYLE':'Mmu8uwI34MmXbL0dsJmK72DehIrER4QH',
    },
}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--manifests',type=Path,default=(workspace() / 'work/evidence/assets/bundle-manifests.json'))
    ap.add_argument('--out',type=Path,default=(workspace() / 'results/protocol'))
    args=ap.parse_args()
    manifests=json.loads(args.manifests.read_text())
    pattern=re.compile(r'/Wardrobe_EAB/(MALE|FEMALE)/([^/]+)/([^/]+)/')
    hints={}
    for bundle in manifests:
        for asset in bundle['assets']:
            asset=decode_manifest_path(asset)
            match=pattern.search(asset)
            if match:
                gender,category,item_id=match.groups()
                hints.setdefault(item_id,[]).append((gender,category,asset))
    for gender,items in DEFAULTS.items():
        for category,item_id in items.items():
            hints.setdefault(item_id,[]).append((gender,category,'native ManagerPreset.LoadDefault'+gender+'Editor literal'))
    rows=[]
    auxiliary=[]
    for bundle in manifests:
        if not bundle['bundle'].startswith('04/'):continue
        for manifest_asset in bundle['assets']:
            asset=decode_manifest_path(manifest_asset)
            match=re.search(r'/([^/]+)/(FBX|Maps)/(.+)$',asset)
            if not match:
                auxiliary.append({'bundle':bundle['bundle'],'asset_path':asset})
                continue
            item_id,kind,filename=match.groups()
            identities=set((a,b) for a,b,c in hints.get(item_id,[]))
            direct=pattern.search(asset)
            if direct:
                gender,category,_=direct.groups()
            else:
                gender,category=next(iter(identities)) if len(identities)==1 else (None,None)
            rows.append({'gender':gender,'category':category,'item_id':item_id,'kind':kind,'filename':filename,
                         'asset_path':asset,'manifest_asset_text':manifest_asset,
                         'requested_resource_path':f'Wardrobe_EAB/{gender}/{category}/{item_id}/{kind}/{item_id}' if gender else None,
                         'category_evidence':hints.get(item_id,[]),'category_conflict':len(identities)>1,
                         'bundle':bundle['bundle'],'bundle_size':bundle['bundle_size'],
                         'manifest_sha256':bundle['manifest_sha256'],'dependencies':bundle['dependencies']})
    summary={'source':str(args.manifests.resolve()),'source_sha256':hashlib.sha256(args.manifests.read_bytes()).hexdigest(),
             'evidence_type':'shipped Unity bundle manifests, not observed server entitlements',
             'entries':len(rows),'distinct_ids':len(set(r['item_id'] for r in rows)),
             'by_gender':dict(collections.Counter(r['gender'] or 'UNKNOWN' for r in rows)),
             'by_category':dict(collections.Counter(r['category'] or 'UNKNOWN' for r in rows)),
             'limitations':['Catalog confirms shipped asset identity and category; it does not supply commercial item names, SKU IDs, ownership, prices, or original entitlement policy.','Lowercase bundle name differs from original-case item ID and asset path. Preserve item ID casing.']}
    summary['auxiliary_asset_count']=len(auxiliary)
    summary['item_bundle_count']=len(set(r['bundle'] for r in rows))
    summary['category_conflict_rows']=sum(r['category_conflict'] for r in rows)
    summary['unresolved_categories']=[{'item_id':r['item_id'],'bundle':r['bundle'],'asset_path':r['asset_path']} for r in rows if r['category'] is None]
    result={'summary':summary,'items':rows,'auxiliary_assets':auxiliary}
    args.out.mkdir(parents=True,exist_ok=True)
    (args.out/'avatar-asset-catalog.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    default_rows={}
    for gender,items in DEFAULTS.items():
        selected=[]
        for category,item_id in items.items():
            matches=[r for r in rows if r['gender']==gender and r['category']==category and r['item_id']==item_id and r['kind']=='FBX']
            assert len(matches)==1,(gender,category,item_id,len(matches))
            selected.append(matches[0])
        data='!'.join([r['item_id'] for r in selected]+[r['category'] for r in selected])
        default_rows[gender]={'default_editor_method_va':'0x18057c4d0' if gender=='MALE' else '0x18057b9a0','items':selected,
                              'id_assets_tablenames_json':{'data':data},
                              'order_note':'Native default-editor load call order (torso, legs, feet, hands, head, optional female hair); both halves use this same order. Original server preset slot order has not been recovered.',
                              'complete_preset':False,
                              'neutral_preset_fixture':'avatar-neutral-'+gender.lower()+'.json',
                              'neutral_preset_provenance':'avatar-neutral-seed-evidence.json',
                              'remaining_unknowns':['Original server numerical morph/bone/skin defaults and preset slot order.','Authored-neutral full JSON fixtures are separately reconstructed; no runtime avatar load has been attempted.']}
    (args.out/'avatar-default-catalog.json').write_text(json.dumps({'evidence_type':'native default-editor literals joined to shipped asset manifests','game_build':'Steam 919290 build11018722','defaults':default_rows},indent=2),encoding='utf-8')
    print(json.dumps(summary))

if __name__=='__main__':
    main()
